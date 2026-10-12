import uuid
from io import BytesIO

import jwt
from pydantic import SecretStr
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import sign_token
from app.models.audit_log import AuditLog
from app.models.enums import CropCategory, ListingStatus
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from tests.integration.conftest import bearer, register

I = "/api/v1/images"


def img_bytes(fmt="JPEG", size=(400, 300)) -> bytes:
    b = BytesIO()
    Image.new("RGB", size, "green").save(b, fmt)
    return b.getvalue()


async def mk_listing(db, farmer_id, status=ListingStatus.DRAFT) -> Listing:
    l = Listing(farmer_id=uuid.UUID(farmer_id), crop_name="Tomato", crop_category=CropCategory.VEGETABLE,
                quantity_kg=100, base_price_paise=3000, location="Bengaluru", status=status)
    db.add(l)
    await db.commit()
    return l


async def farmer(client, email="f1@example.com"):
    t = await register(client, email=email)
    return t, bearer(t), t["user"]["id"]


def key_of(init_resp) -> str:
    return jwt.decode(init_resp["upload_token"], options={"verify_signature": False})["key"]


async def upload(client, app_ctx, h, listing, data=None, ct="image/jpeg", name="a.jpg", replace=None, size=None):
    body = {"listing_id": str(listing.id), "filename": name, "content_type": ct, "size_bytes": size or 1000}
    if replace:
        body["replace_image_id"] = replace
    r = await client.post(f"{I}/init", json=body, headers=h)
    assert r.status_code == 200, r.text
    init = r.json()["data"]
    if data is not None:
        app_ctx.state.fake_storage.put(key_of(init), data)
    return init


async def confirm(client, h, init):
    return await client.post(f"{I}/confirm", json={"upload_token": init["upload_token"]}, headers=h)


async def test_happy_path_metadata_and_key_format(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    init = await upload(client, app_ctx, h, l, img_bytes())
    key = key_of(init)
    assert key.startswith(f"e-mandi/listings/{l.id}/") and key.endswith(".jpg")
    assert init["fields"]["key"] == key and init["max_bytes"] == 5 * 1024 * 1024
    r = await confirm(client, h, init)
    d = r.json()["data"]
    assert r.status_code == 200 and d["is_primary"] and (d["width"], d["height"]) == (400, 300)
    assert d["url"].startswith("https://fake-s3.local/") and "sig=" in d["url"]
    row = (await db.scalars(select(ListingImage))).one()
    assert row.s3_key == key and row.content_type == "image/jpeg" and len(row.sha256) == 64
    assert "e-mandi/listings" not in str(row.__dict__.get("data", ""))  # no binary stored
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "image.uploaded"))).one()
    assert a.meta["listing_id"] == str(l.id)


async def test_init_authorization(app_ctx, client, db):
    _, h1, f1 = await farmer(client)
    _, h2, _ = await farmer(client, "f2@example.com")
    buyer = await register(client, email="b@example.com", role="BUYER")
    l = await mk_listing(db, f1)
    body = {"listing_id": str(l.id), "filename": "a.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    assert (await client.post(f"{I}/init", json=body)).status_code == 401
    assert (await client.post(f"{I}/init", json=body, headers=h2)).status_code == 404  # not the owner
    assert (await client.post(f"{I}/init", json=body, headers=bearer(buyer))).status_code == 404
    assert (await client.post(f"{I}/init", json={**body, "listing_id": str(uuid.uuid4())}, headers=h1)).status_code == 404


async def test_init_declared_validation(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    base = {"listing_id": str(l.id), "filename": "a.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    for bad in ({"content_type": "image/gif", "filename": "a.gif"}, {"content_type": "application/pdf"},
                {"filename": "a.png"}, {"filename": "a.jpg.exe"}, {"filename": "noext"},
                {"size_bytes": 6 * 1024 * 1024}, {"size_bytes": 0}):
        r = await client.post(f"{I}/init", json={**base, **bad}, headers=h)
        assert r.status_code == 422, bad


async def test_invalid_files_rejected_and_deleted(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    st = app_ctx.state.fake_storage
    cases = {
        "not an image": b"<?php echo 1; ?>" * 50,
        "png declared as jpeg": img_bytes("PNG"),
        "too small": img_bytes(size=(50, 50)),
        "truncated": img_bytes()[:200],
        "too big": b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 + 10),
    }
    for name, data in cases.items():
        init = await upload(client, app_ctx, h, l, data)
        r = await confirm(client, h, init)
        assert r.status_code in (422, 502), name
        assert key_of(init) not in st.objects, f"{name}: object should be deleted"
    assert (await db.scalars(select(ListingImage))).all() == []


async def test_confirm_without_upload(app_ctx, client, db):
    _, h, fid = await farmer(client)
    init = await upload(client, app_ctx, h, await mk_listing(db, fid), None)
    assert (await confirm(client, h, init)).status_code == 422


async def test_token_bound_to_user_and_signed(app_ctx, client, db):
    _, h1, f1 = await farmer(client)
    _, h2, _ = await farmer(client, "f2@example.com")
    l = await mk_listing(db, f1)
    init = await upload(client, app_ctx, h1, l, img_bytes())
    assert (await confirm(client, h2, init)).status_code == 403  # someone else's grant
    forged = sign_token({"purpose": "listing_image", "uid": f1, "lid": str(l.id), "key": "e-mandi/x", "ct": "image/jpeg"},
                        typ="upload", ttl_seconds=60, settings=get_settings().model_copy(update={"JWT_SECRET": SecretStr("x" * 40)}))
    assert (await client.post(f"{I}/confirm", json={"upload_token": forged}, headers=h1)).status_code == 401
    expired = sign_token({"purpose": "listing_image", "uid": f1, "lid": str(l.id), "key": "k", "ct": "image/jpeg"},
                         typ="upload", ttl_seconds=-5)
    assert (await client.post(f"{I}/confirm", json={"upload_token": expired}, headers=h1)).status_code == 401
    access_as_upload = h1["Authorization"].split()[1]
    assert (await client.post(f"{I}/confirm", json={"upload_token": access_as_upload}, headers=h1)).status_code == 401


async def test_confirm_is_idempotent(app_ctx, client, db):
    _, h, fid = await farmer(client)
    init = await upload(client, app_ctx, h, await mk_listing(db, fid), img_bytes())
    a, b = await confirm(client, h, init), await confirm(client, h, init)
    assert a.json()["data"]["id"] == b.json()["data"]["id"]
    assert len((await db.scalars(select(ListingImage))).all()) == 1


async def test_max_five_images(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    for _ in range(5):
        assert (await confirm(client, h, await upload(client, app_ctx, h, l, img_bytes()))).status_code == 200
    body = {"listing_id": str(l.id), "filename": "a.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    assert (await client.post(f"{I}/init", json=body, headers=h)).status_code == 409
    # grants obtained BEFORE reaching the cap are still blocked at confirm and their object is cleaned
    l2 = await mk_listing(db, fid)
    inits = [await upload(client, app_ctx, h, l2, img_bytes()) for _ in range(6)]
    codes = [(await confirm(client, h, i)).status_code for i in inits]
    assert codes == [200] * 5 + [409]
    assert key_of(inits[5]) not in app_ctx.state.fake_storage.objects


async def test_upload_blocked_while_analyzing(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid, ListingStatus.ANALYZING)
    body = {"listing_id": str(l.id), "filename": "a.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    assert (await client.post(f"{I}/init", json=body, headers=h)).status_code == 409


async def test_replace_keeps_primary_and_deletes_old_object(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    first = (await confirm(client, h, await upload(client, app_ctx, h, l, img_bytes()))).json()["data"]
    old_key = (await db.get(ListingImage, uuid.UUID(first["id"]))).s3_key
    init = await upload(client, app_ctx, h, l, img_bytes("PNG"), ct="image/png", name="b.png", replace=first["id"])
    new = (await confirm(client, h, init)).json()["data"]
    assert new["id"] != first["id"] and new["is_primary"] and new["content_type"] == "image/png"
    assert old_key not in app_ctx.state.fake_storage.objects
    db.expire_all()
    assert len((await db.scalars(select(ListingImage))).all()) == 1
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "image.replaced"))).one()


async def test_primary_and_delete_rules(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    lid = l.id
    a = (await confirm(client, h, await upload(client, app_ctx, h, l, img_bytes()))).json()["data"]
    b = (await confirm(client, h, await upload(client, app_ctx, h, l, img_bytes()))).json()["data"]
    assert a["is_primary"] and not b["is_primary"]
    assert (await client.post(f"{I}/{b['id']}/primary", headers=h)).json()["data"]["is_primary"] is True
    imgs = (await client.get(f"{I}/listing/{lid}", headers=h)).json()["data"]
    assert sum(i["is_primary"] for i in imgs) == 1
    assert (await client.delete(f"{I}/{b['id']}", headers=h)).status_code == 204  # primary deleted
    db.expire_all()
    left = (await db.scalars(select(ListingImage))).one()
    assert left.id == uuid.UUID(a["id"]) and left.is_primary  # promoted
    l_db = await db.get(Listing, lid)
    l_db.status = ListingStatus.ACTIVE
    await db.commit()
    assert (await client.delete(f"{I}/{a['id']}", headers=h)).status_code == 409  # last image of ACTIVE listing


async def test_delete_and_primary_ownership(app_ctx, client, db):
    _, h1, f1 = await farmer(client)
    _, h2, _ = await farmer(client, "f2@example.com")
    l = await mk_listing(db, f1)
    a = (await confirm(client, h1, await upload(client, app_ctx, h1, l, img_bytes()))).json()["data"]
    assert (await client.delete(f"{I}/{a['id']}", headers=h2)).status_code == 404
    assert (await client.post(f"{I}/{a['id']}/primary", headers=h2)).status_code == 404


async def test_listing_image_visibility(app_ctx, client, db):
    _, h, fid = await farmer(client)
    buyer = bearer(await register(client, email="b@example.com", role="BUYER"))
    l = await mk_listing(db, fid)
    await confirm(client, h, await upload(client, app_ctx, h, l, img_bytes()))
    assert (await client.get(f"{I}/listing/{l.id}", headers=buyer)).status_code == 404  # DRAFT is private
    l_db = await db.get(Listing, l.id)
    l_db.status = ListingStatus.ACTIVE
    await db.commit()
    r = await client.get(f"{I}/listing/{l.id}", headers=buyer)
    assert r.status_code == 200 and len(r.json()["data"]) == 1
    assert (await client.get(f"{I}/listing/{l.id}")).status_code == 401


async def test_profile_avatar_flow(app_ctx, client, db):
    t, h, uid = await farmer(client)
    r = await client.post(f"{I}/profile/init", json={"filename": "me.png", "content_type": "image/png",
                                                     "size_bytes": 100}, headers=h)
    init = r.json()["data"]
    key = key_of(init)
    assert key.startswith(f"e-mandi/profiles/{uid}/") and key.endswith(".png")
    app_ctx.state.fake_storage.put(key, img_bytes("PNG"))
    ok = await client.post(f"{I}/profile/confirm", json={"upload_token": init["upload_token"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["data"]["url"].endswith("sig=abc")
    # a listing grant can't be used as an avatar grant
    _, _, fid = await farmer(client, "f9@example.com")
    l = await mk_listing(db, uid)
    li = await upload(client, app_ctx, h, l, img_bytes())
    assert (await client.post(f"{I}/profile/confirm", json={"upload_token": li["upload_token"]}, headers=h)).status_code == 403


async def test_init_rate_limited_per_user(app_ctx, client, db):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid)
    body = {"listing_id": str(l.id), "filename": "a.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    codes = [(await client.post(f"{I}/init", json=body, headers=h)).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429
