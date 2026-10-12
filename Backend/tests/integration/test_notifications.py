import asyncio
import re
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.models.enums import NotificationType
from app.models.notification import Notification
from app.utils.time import utcnow
from tests.integration.test_matching_agent import buyer, farmer
from tests.integration.test_payments import setup

N = "/api/v1/notifications"


async def mk(db, uid, n, title="t", read=False, start=None):
    start = start or utcnow() - timedelta(minutes=n + 1)
    ids = []
    for i in range(n):
        row = Notification(user_id=uid, type=NotificationType.NEW_ORDER, title=f"{title}{i}", body="b", data={"i": i},
                           is_read=read, created_at=start + timedelta(seconds=i))
        db.add(row)
        await db.flush()
        ids.append(row.id)
    await db.commit()
    return ids


def fast_sse(app, **over):
    s = get_settings().model_copy(update={"SSE_POLL_SECONDS": 0.15, "SSE_MAX_SECONDS": 1, "SSE_MAX_CONNECTIONS_PER_USER": 2, **over})
    app.dependency_overrides[get_settings] = lambda: s


def events(text):
    return [m for m in re.findall(r"^id: (\S+)$", text, flags=re.M)]


async def test_only_own_notifications_are_visible(client, db):
    fh, fid = await farmer(client, 1)
    bh, bid = await buyer(client, 1)
    await mk(db, fid, 2, "mine")
    await mk(db, bid, 3, "theirs")
    d = (await client.get(N, headers=fh)).json()["data"]
    assert len(d["items"]) == 2 and d["unread_count"] == 2 and all(i["title"].startswith("mine") for i in d["items"])
    assert (await client.get(f"{N}/unread-count", headers=bh)).json()["data"]["unread_count"] == 3


async def test_ordering_pagination_and_unread_filter(client, db):
    fh, fid = await farmer(client, 1)
    ids = await mk(db, fid, 5)
    await client.post(f"{N}/{ids[0]}/read", headers=fh)
    page1 = (await client.get(f"{N}?limit=2", headers=fh)).json()["data"]
    assert [i["title"] for i in page1["items"]] == ["t4", "t3"] and page1["next_cursor"]
    page2 = (await client.get(f"{N}?limit=2&cursor={page1['next_cursor']}", headers=fh)).json()["data"]
    page3 = (await client.get(f"{N}?limit=2&cursor={page2['next_cursor']}", headers=fh)).json()["data"]
    assert [i["title"] for i in page2["items"] + page3["items"]] == ["t2", "t1", "t0"] and page3["next_cursor"] is None
    unread = (await client.get(f"{N}?unread_only=true", headers=fh)).json()["data"]
    assert len(unread["items"]) == 4 and unread["unread_count"] == 4
    assert (await client.get(f"{N}?limit=0", headers=fh)).status_code == 422


async def test_mark_read_is_idempotent_and_owner_only(client, db):
    fh, fid = await farmer(client, 1)
    bh, _ = await buyer(client, 1)
    [nid] = await mk(db, fid, 1)
    assert (await client.post(f"{N}/{nid}/read", headers=bh)).status_code == 404
    assert (await client.post(f"{N}/{nid}/read", headers=fh)).status_code == 204
    first = (await db.get(Notification, nid, populate_existing=True)).read_at
    assert (await client.post(f"{N}/{nid}/read", headers=fh)).status_code == 204
    assert (await db.get(Notification, nid, populate_existing=True)).read_at == first
    assert (await client.post(f"{N}/{uuid.uuid4()}/read", headers=fh)).status_code == 404
    assert (await client.post(f"{N}/{nid}/read")).status_code == 401


async def test_read_all_is_scoped_to_caller(client, db):
    fh, fid = await farmer(client, 1)
    bh, bid = await buyer(client, 1)
    await mk(db, fid, 3)
    await mk(db, bid, 2)
    assert (await client.post(f"{N}/read-all", headers=fh)).json()["data"]["marked"] == 3
    assert (await client.post(f"{N}/read-all", headers=fh)).json()["data"]["marked"] == 0
    assert (await client.get(f"{N}/unread-count", headers=bh)).json()["data"]["unread_count"] == 2


async def test_real_order_flow_notifies_the_farmer(app_ctx, client, db):
    c = await setup(client, db)
    rows = (await db.scalars(select(Notification).where(Notification.user_id == c["f1"], Notification.type == NotificationType.NEW_ORDER))).all()
    assert rows
    d = (await client.get(N, headers=c["fh"])).json()["data"]
    assert d["items"] and d["items"][0]["type"] == "NEW_ORDER"


async def test_sse_requires_auth_and_rejects_url_tokens(client, app_ctx):
    fast_sse(app_ctx)
    assert (await client.get(f"{N}/stream")).status_code == 401
    fh, _ = await farmer(client, 1)
    token = fh["Authorization"].split()[1]
    assert (await client.get(f"{N}/stream?access_token={token}")).status_code == 401


async def test_sse_streams_only_own_events_and_resumes(client, app_ctx, db):
    fast_sse(app_ctx, SSE_MAX_SECONDS=1)
    fh, fid = await farmer(client, 1)
    _, bid = await buyer(client, 1)
    ids = await mk(db, fid, 3, start=utcnow() + timedelta(seconds=30))  # future-dated so they are "new" vs. connect time
    await mk(db, bid, 2, start=utcnow() + timedelta(seconds=30))
    # resume from the first event: expect the other two of MY notifications only
    r = await client.get(f"{N}/stream", headers={**fh, "Last-Event-ID": str(ids[0])})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert events(r.text) == [str(ids[1]), str(ids[2])] and "theirs" not in r.text
    # foreign / invalid Last-Event-ID is ignored (never leaks or errors)
    foreign = (await db.scalars(select(Notification.id).where(Notification.user_id == bid))).first()
    for bad in (str(foreign), "not-a-uuid"):
        r = await client.get(f"{N}/stream", headers={**fh, "Last-Event-ID": bad})
        assert r.status_code == 200 and str(foreign) not in r.text


async def test_sse_delivers_notifications_created_while_connected(client, app_ctx, db):
    fast_sse(app_ctx, SSE_MAX_SECONDS=2)
    fh, fid = await farmer(client, 1)

    async def later():
        await asyncio.sleep(0.5)
        await mk(db, fid, 1, "live", start=utcnow() + timedelta(seconds=1))

    task = asyncio.create_task(later())
    r = await client.get(f"{N}/stream", headers=fh)
    await task
    assert "live0" in r.text and r.text.count("event: notification") == 1


async def test_sse_connection_cap_and_slot_release(client, app_ctx, redis):
    fast_sse(app_ctx, SSE_MAX_CONNECTIONS_PER_USER=2, SSE_MAX_SECONDS=1)
    fh, fid = await farmer(client, 1)
    await redis.set(f"sse:{fid}", 2)  # two streams already open
    r = await client.get(f"{N}/stream", headers=fh)
    assert r.status_code == 429 and r.json()["error"]["code"]
    assert int(await redis.get(f"sse:{fid}")) == 2  # a rejected attempt must not leak a slot
    await redis.set(f"sse:{fid}", 1)
    assert (await client.get(f"{N}/stream", headers=fh)).status_code == 200
    assert int(await redis.get(f"sse:{fid}")) == 1  # slot released when the stream ends
