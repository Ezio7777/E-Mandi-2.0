import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core.database import get_sessionmaker, transactional
from app.core.errors import InsufficientStockError
from app.models.audit_log import AuditLog
from app.models.enums import ListingStatus
from app.models.listing import Listing
from app.services.inventory import InventoryService
from sqlalchemy import select

from tests.integration.conftest import bearer, register
from tests.integration.test_images import confirm, img_bytes, upload

L = "/api/v1/listings"
PAYLOAD = {"crop_name": "Tomato", "crop_category": "VEGETABLE", "quantity_kg": 500, "base_price": 28.5,
           "location": "Bengaluru", "state": "Karnataka"}


async def farmer(client, email="f1@example.com"):
    t = await register(client, email=email)
    return bearer(t), t["user"]["id"]


async def buyer(client, email="b1@example.com"):
    return bearer(await register(client, email=email, role="BUYER"))


async def create(client, h, **over):
    r = await client.post(L, json={**PAYLOAD, **over}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def set_status(db, lid, status, **kw):
    l = await db.get(Listing, uuid.UUID(lid))
    l.status = status
    for k, v in kw.items():
        setattr(l, k, v)
    await db.commit()
    db.expire_all()


async def test_create_and_api_shape(client):
    h, fid = await farmer(client)
    d = await create(client, h)
    assert d["status"] == "DRAFT" and d["base_price"] == 28.5 and d["quantity_kg"] == 500
    assert d["available_kg"] == 500 and d["farmer"]["id"] == fid and d["ai_grade"] is None
    assert "email" not in str(d["farmer"]) and d["suggested_price"] is None


async def test_only_farmers_create_and_validation(client):
    b = await buyer(client)
    assert (await client.post(L, json=PAYLOAD, headers=b)).status_code == 403
    assert (await client.post(L, json=PAYLOAD)).status_code == 401
    h, _ = await farmer(client)
    for bad in ({"quantity_kg": 0}, {"quantity_kg": -5}, {"base_price": 0}, {"base_price": 10.555},
                {"quantity_kg": 1.2345}, {"crop_name": "x"}, {"status": "ACTIVE"}, {"ai_grade": "A"},
                {"farmer_id": str(uuid.uuid4())}, {"harvest_date": str(date.today() + timedelta(days=400))}):
        assert (await client.post(L, json={**PAYLOAD, **bad}, headers=h)).status_code == 422, bad


async def test_update_rules(client, db):
    h, _ = await farmer(client)
    h2, _ = await farmer(client, "f2@example.com")
    d = await create(client, h)
    r = await client.patch(f"{L}/{d['id']}", json={"base_price": 30, "crop_name": "Roma Tomato"}, headers=h)
    assert r.json()["data"]["base_price"] == 30 and r.json()["data"]["crop_name"] == "Roma Tomato"
    assert (await client.patch(f"{L}/{d['id']}", json={"base_price": 31}, headers=h2)).status_code == 404
    for bad in ({"status": "ACTIVE"}, {"ai_grade": "A"}, {"suggested_price": 1}, {"reserved_kg": 0}):
        assert (await client.patch(f"{L}/{d['id']}", json=bad, headers=h)).status_code == 422
    await set_status(db, d["id"], ListingStatus.ACTIVE, reserved_kg=Decimal(100))
    assert (await client.patch(f"{L}/{d['id']}", json={"crop_name": "Onion"}, headers=h)).status_code == 409
    assert (await client.patch(f"{L}/{d['id']}", json={"quantity_kg": 50}, headers=h)).status_code == 409
    assert (await client.patch(f"{L}/{d['id']}", json={"quantity_kg": 150, "base_price": 33}, headers=h)).status_code == 200
    await set_status(db, d["id"], ListingStatus.SOLD)
    assert (await client.patch(f"{L}/{d['id']}", json={"base_price": 1}, headers=h)).status_code == 409


async def test_update_writes_diff_audit_and_noop_is_silent(client, db):
    h, _ = await farmer(client)
    d = await create(client, h)
    await client.patch(f"{L}/{d['id']}", json={"base_price": 40, "location": "Bengaluru"}, headers=h)
    await client.patch(f"{L}/{d['id']}", json={"base_price": 40}, headers=h)  # no change
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "listing.updated"))).all()
    assert len(rows) == 1 and rows[0].previous_state == {"base_price_paise": 2850} and rows[0].new_state == {"base_price_paise": 4000}


async def test_visibility_and_browse(client, db):
    h, _ = await farmer(client)
    h2, _ = await farmer(client, "f2@example.com")
    b = await buyer(client)
    draft, active = await create(client, h), await create(client, h, crop_name="Onion")
    await set_status(db, active["id"], ListingStatus.ACTIVE)
    assert (await client.get(f"{L}/{draft['id']}", headers=b)).status_code == 404
    assert (await client.get(f"{L}/{draft['id']}", headers=h2)).status_code == 404
    assert (await client.get(f"{L}/{draft['id']}", headers=h)).status_code == 200
    assert (await client.get(f"{L}/{active['id']}", headers=b)).status_code == 200
    items = (await client.get(L, headers=b)).json()["data"]["items"]
    assert [i["id"] for i in items] == [active["id"]]
    # buyers cannot see drafts even by asking for them
    assert (await client.get(f"{L}?status=DRAFT", headers=b)).json()["data"]["items"][0]["id"] == active["id"]
    mine = (await client.get(f"{L}/mine", headers=h)).json()["data"]["items"]
    assert {i["id"] for i in mine} == {draft["id"], active["id"]}
    assert (await client.get(f"{L}/mine", headers=b)).status_code == 403


async def test_filters_and_cursor_pagination(client, db):
    h, _ = await farmer(client)
    b = await buyer(client)
    ids = []
    for i in range(5):
        d = await create(client, h, crop_name="Tomato" if i < 3 else "Potato", base_price=10 + i * 10,
                         location="Mysuru" if i == 0 else "Bengaluru")
        await set_status(db, d["id"], ListingStatus.ACTIVE)
        ids.append(d["id"])
    await set_status(db, ids[0], ListingStatus.ACTIVE, ai_grade="A")
    async def ids_for(q):
        return [i["id"] for i in (await client.get(f"{L}?{q}", headers=b)).json()["data"]["items"]]
    assert set(await ids_for("crop=tomato")) == set(ids[:3])
    assert await ids_for("location=mysu") == [ids[0]]
    assert set(await ids_for("min_price=30&max_price=40")) == {ids[2], ids[3]}
    assert await ids_for("min_grade=B") == [ids[0]]
    assert (await client.get(f"{L}?max_price=10.999", headers=b)).status_code == 422
    seen, cursor = [], None
    for _ in range(5):
        r = (await client.get(f"{L}?limit=2" + (f"&cursor={cursor}" if cursor else ""), headers=b)).json()["data"]
        seen += [i["id"] for i in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5 and seen == list(reversed(ids))
    assert (await client.get(f"{L}?cursor=garbage", headers=b)).status_code == 422


async def test_submit_requires_image_then_analyzing(app_ctx, client, db):
    h, _ = await farmer(client)
    d = await create(client, h)
    r = await client.post(f"{L}/{d['id']}/submit", headers=h)
    assert r.status_code == 409 and "photo" in r.json()["error"]["message"]
    l = await db.get(Listing, uuid.UUID(d["id"]))
    init = await upload(client, app_ctx, h, l, img_bytes())
    await confirm(client, h, init)
    r = await client.post(f"{L}/{d['id']}/submit", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "ANALYZING" and r.json()["data"]["image_count"] == 1
    assert r.json()["data"]["primary_image_url"].startswith("https://fake-s3.local/")
    assert (await client.post(f"{L}/{d['id']}/submit", headers=h)).status_code == 409
    assert (await client.patch(f"{L}/{d['id']}", json={"base_price": 5}, headers=h)).status_code == 409


async def test_archive_rules(client, db):
    h, _ = await farmer(client)
    h2, _ = await farmer(client, "f2@example.com")
    d = await create(client, h)
    assert (await client.post(f"{L}/{d['id']}/archive", headers=h2)).status_code == 404
    await set_status(db, d["id"], ListingStatus.ACTIVE, reserved_kg=Decimal(10))
    assert (await client.post(f"{L}/{d['id']}/archive", headers=h)).status_code == 409
    await set_status(db, d["id"], ListingStatus.ACTIVE, reserved_kg=Decimal(0))
    r = await client.post(f"{L}/{d['id']}/archive", headers=h)
    assert r.json()["data"]["status"] == "ARCHIVED"
    assert (await client.post(f"{L}/{d['id']}/archive", headers=h)).status_code == 409


# ---------------- inventory ----------------
async def test_inventory_view_and_adjust(client, db):
    h, _ = await farmer(client)
    d = await create(client, h)
    await set_status(db, d["id"], ListingStatus.ACTIVE, reserved_kg=Decimal(200))
    inv = (await client.get("/api/v1/inventory", headers=h)).json()["data"]
    assert inv[0]["available_kg"] == 300
    r = await client.patch(f"/api/v1/inventory/{d['id']}", json={"quantity_kg": 150, "reason": "spoilage"}, headers=h)
    assert r.status_code == 409  # below reserved
    r = await client.patch(f"/api/v1/inventory/{d['id']}", json={"quantity_kg": 200, "reason": "spoilage"}, headers=h)
    assert r.json()["data"]["status"] == "RESERVED" and r.json()["data"]["available_kg"] == 0
    r = await client.patch(f"/api/v1/inventory/{d['id']}", json={"quantity_kg": 300, "reason": "new harvest"}, headers=h)
    assert r.json()["data"]["status"] == "ACTIVE"
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "inventory.adjusted"))).all().__len__() == 2
    b = await buyer(client)
    assert (await client.get("/api/v1/inventory", headers=b)).status_code == 403


async def _run(op, *items):
    async with get_sessionmaker()() as s:
        try:
            async with transactional(s):
                await getattr(InventoryService(s), op)(list(items))
            return "ok"
        except InsufficientStockError:
            return "insufficient"


async def test_no_overselling_under_concurrency(client, db):
    h, _ = await farmer(client)
    d = await create(client, h, quantity_kg=100)
    await set_status(db, d["id"], ListingStatus.ACTIVE)
    lid = uuid.UUID(d["id"])
    results = await asyncio.gather(*[_run("reserve_many", (lid, Decimal(10))) for _ in range(30)])
    assert results.count("ok") == 10 and results.count("insufficient") == 20
    l = await db.get(Listing, lid)
    await db.refresh(l)
    assert l.reserved_kg == 100 and l.available_kg == 0 and l.status == ListingStatus.RESERVED
    assert await _run("reserve_many", (lid, Decimal(1))) == "insufficient"


async def test_release_and_commit_sale_lifecycle(client, db):
    h, _ = await farmer(client)
    d = await create(client, h, quantity_kg=100)
    await set_status(db, d["id"], ListingStatus.ACTIVE)
    lid = uuid.UUID(d["id"])
    assert await _run("reserve_many", (lid, Decimal(100))) == "ok"
    await db.refresh(await db.get(Listing, lid))
    assert (await db.get(Listing, lid)).status == ListingStatus.RESERVED
    await _run("release_many", (lid, Decimal(40)))
    l = await db.get(Listing, lid)
    await db.refresh(l)
    assert l.reserved_kg == 60 and l.status == ListingStatus.ACTIVE
    await _run("commit_sale_many", (lid, Decimal(60)))
    await db.refresh(l)
    assert (l.quantity_kg, l.reserved_kg, l.status) == (40, 0, ListingStatus.ACTIVE)
    assert await _run("reserve_many", (lid, Decimal(40))) == "ok"
    await _run("commit_sale_many", (lid, Decimal(40)))
    await db.refresh(l)
    assert l.quantity_kg == 0 and l.status == ListingStatus.SOLD
    assert await _run("reserve_many", (lid, Decimal(1))) == "insufficient"


async def test_multi_listing_reservation_is_atomic(client, db):
    h, _ = await farmer(client)
    a = await create(client, h, quantity_kg=10)
    b = await create(client, h, quantity_kg=5)
    for x in (a, b):
        await set_status(db, x["id"], ListingStatus.ACTIVE)
    ia, ib = uuid.UUID(a["id"]), uuid.UUID(b["id"])
    assert await _run("reserve_many", (ia, Decimal(10)), (ib, Decimal(6))) == "insufficient"  # b short => a untouched
    la = await db.get(Listing, ia)
    await db.refresh(la)
    assert la.reserved_kg == 0 and la.status == ListingStatus.ACTIVE
