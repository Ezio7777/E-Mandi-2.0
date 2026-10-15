import io
import uuid

import pytest
from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.enums import DocumentStatus, ListingStatus
from app.models.listing_document import ListingDocument
from app.models.notification import Notification
from app.utils.pdf import InvalidPdf, sniff_pdf
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject
from sqlalchemy import select

from tests.conftest import wire
from tests.integration.test_grading import make_admin
from tests.integration.test_images import farmer, mk_listing

D = "/api/v1/documents"


def pdf_bytes(pages=1, mutate=None, encrypt=None) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    if mutate:
        mutate(w)
    if encrypt:
        w.encrypt(encrypt)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def with_js(w):
    w.add_js("app.alert(1)")


def with_open_action(w):
    w._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("1")})


async def init(client, h, lid, **over):
    body = {"listingId": str(lid), "filename": "cert.pdf", "contentType": "application/pdf", "sizeBytes": 1000, "docType": "QUALITY_CERTIFICATE",
            "title": "APEDA cert", **over}
    return await client.post(f"{D}/init", headers=h, json=body)


async def upload_confirm(client, app_ctx, h, lid, data):
    r = await init(client, h, lid)
    assert r.status_code == 200, r.text
    d = wire(r)["data"]
    app_ctx.state.fake_storage.put(d["objectKey"], data)
    return d, await client.post(f"{D}/confirm", headers=h, json={"uploadToken": d["uploadToken"]})


async def setup(client, db, status=ListingStatus.ACTIVE):
    _, h, fid = await farmer(client)
    l = await mk_listing(db, fid, status)
    return h, l


def test_pdf_sniffing_accepts_plain_and_rejects_unsafe():
    assert sniff_pdf(pdf_bytes(2), max_pages=5).pages == 2
    for bad in (b"hello", b"%PDF-1.4 truncated", pdf_bytes(encrypt="pw"), pdf_bytes(mutate=with_js), pdf_bytes(mutate=with_open_action), pdf_bytes(pages=3)):
        with pytest.raises(InvalidPdf):
            sniff_pdf(bad, max_pages=2)


async def test_upload_confirm_happy_path_and_idempotent_replay(app_ctx, client, db):
    h, l = await setup(client, db)
    d, r = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes(2))
    body = wire(r)["data"]
    assert r.status_code == 201 and body["status"] == "PENDING_REVIEW" and body["pageCount"] == 2 and body["docType"] == "QUALITY_CERTIFICATE"
    assert d["objectKey"].startswith(f"e-mandi/listings/{l.id}/") and d["objectKey"].endswith(".pdf") and d["maxBytes"] == get_settings().DOCUMENT_MAX_BYTES
    assert "sig=" in body["url"]
    r2 = await client.post(f"{D}/confirm", headers=h, json={"uploadToken": d["uploadToken"]})
    assert wire(r2)["data"]["id"] == body["id"]
    assert len((await db.scalars(select(ListingDocument))).all()) == 1
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "document.uploaded"))).one()


@pytest.mark.parametrize("over", [{"contentType": "image/png"}, {"filename": "cert.exe"}, {"sizeBytes": 50 * 1024 * 1024}])
async def test_init_rejects_bad_declarations(client, db, over):
    h, l = await setup(client, db)
    assert (await init(client, h, l.id, **over)).status_code == 422


@pytest.mark.parametrize("data", [b"not a pdf at all", pdf_bytes(encrypt="pw"), pdf_bytes(mutate=with_js), pdf_bytes(pages=25)])
async def test_confirm_rejects_and_deletes_invalid_files(app_ctx, client, db, data):
    h, l = await setup(client, db)
    d, r = await upload_confirm(client, app_ctx, h, l.id, data)
    assert r.status_code == 422
    assert d["objectKey"] not in app_ctx.state.fake_storage.objects
    assert (await db.scalars(select(ListingDocument))).all() == []


async def test_confirm_without_upload_and_foreign_token(app_ctx, client, db):
    h, l = await setup(client, db)
    d = wire(await init(client, h, l.id))["data"]
    assert (await client.post(f"{D}/confirm", headers=h, json={"uploadToken": d["uploadToken"]})).status_code == 422
    _, h2, _ = await farmer(client, "f2@example.com")
    assert (await client.post(f"{D}/confirm", headers=h2, json={"uploadToken": d["uploadToken"]})).status_code == 403
    assert (await init(client, h2, l.id)).status_code == 404  # not the owner


async def test_per_listing_limit_and_sold_listing_blocked(app_ctx, client, db):
    h, l = await setup(client, db)
    for _ in range(get_settings().DOCUMENT_MAX_PER_LISTING):
        assert (await upload_confirm(client, app_ctx, h, l.id, pdf_bytes()))[1].status_code == 201
    assert (await init(client, h, l.id)).status_code == 409
    _, hh, fid = await farmer(client, "f3@example.com")
    l2 = await mk_listing(db, fid, ListingStatus.SOLD)
    assert (await init(client, hh, l2.id)).status_code == 409


async def test_visibility_buyers_only_see_verified(app_ctx, client, db):
    from tests.integration.conftest import bearer, register
    admin = await make_admin(db, client)
    h, l = await setup(client, db)
    _, r1 = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes())
    _, r2 = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes())
    id1, id2 = wire(r1)["data"]["id"], wire(r2)["data"]["id"]
    assert (await client.post(f"{D}/{id1}/verify", headers=admin)).status_code == 200
    buyer = bearer(await register(client, email="b@example.com", role="BUYER"))
    seen = wire(await client.get(f"{D}/listing/{l.id}", headers=buyer))["data"]
    assert [x["id"] for x in seen] == [id1]
    assert len(wire(await client.get(f"{D}/listing/{l.id}", headers=h))["data"]) == 2
    assert len(wire(await client.get(f"{D}/listing/{l.id}", headers=admin))["data"]) == 2
    assert id2


async def test_admin_review_flow_audit_notifications_and_guards(app_ctx, client, db, demo_users):
    admin = await make_admin(db, client)
    h, l = await setup(client, db)
    _, fid = None, l.farmer_id
    _, r = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes())
    did = wire(r)["data"]["id"]
    assert (await db.scalars(select(Notification).where(Notification.title == "Document awaiting review"))).all()
    assert (await client.post(f"{D}/{did}/verify", headers=h)).status_code == 403  # farmer cannot self-verify
    q = wire(await client.get(f"{D}/admin/queue", headers=admin))
    assert [x["id"] for x in q["data"]["items"]] == [did] and q["data"]["nextCursor"] is None
    assert (await client.get(f"{D}/admin/queue", headers=h)).status_code == 403
    assert (await client.post(f"{D}/{did}/reject", headers=admin, json={"reason": "x"})).status_code == 422
    r = await client.post(f"{D}/{did}/reject", headers=admin, json={"reason": "Blurry scan"})
    assert wire(r)["data"]["status"] == "REJECTED" and wire(r)["data"]["reviewReason"] == "Blurry scan"
    assert (await client.post(f"{D}/{did}/verify", headers=admin)).status_code == 409  # decided once
    assert (await db.scalars(select(Notification).where(Notification.user_id == fid, Notification.title == "Document rejected"))).one()
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "document.rejected"))).one()
    await db.rollback()
    assert (await db.get(ListingDocument, uuid.UUID(did))).status == DocumentStatus.REJECTED


async def test_concurrent_review_decides_once(app_ctx, client, db):
    import asyncio
    admin = await make_admin(db, client)
    h, l = await setup(client, db)
    did = wire((await upload_confirm(client, app_ctx, h, l.id, pdf_bytes()))[1])["data"]["id"]
    rs = await asyncio.gather(client.post(f"{D}/{did}/verify", headers=admin), client.post(f"{D}/{did}/reject", headers=admin, json={"reason": "not legible"}))
    assert sorted(r.status_code for r in rs) == [200, 409]


async def test_delete_by_owner_removes_object_and_others_get_404(app_ctx, client, db):
    h, l = await setup(client, db)
    d, r = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes())
    did = wire(r)["data"]["id"]
    _, h2, _ = await farmer(client, "f2@example.com")
    assert (await client.delete(f"{D}/{did}", headers=h2)).status_code == 404
    assert (await client.delete(f"{D}/{did}", headers=h)).status_code == 204
    assert d["objectKey"] not in app_ctx.state.fake_storage.objects
    assert (await client.delete(f"{D}/{did}", headers=h)).status_code == 404


async def test_orphan_sweeper_keeps_documents_and_deletes_orphans(app_ctx, client, db, redis):
    from datetime import UTC, datetime, timedelta

    from app.core.database import get_sessionmaker
    from app.services.recovery import RecoveryService
    from app.workers.queue import RecordingJobQueue
    h, l = await setup(client, db)
    d, _ = await upload_confirm(client, app_ctx, h, l.id, pdf_bytes())
    orphan = f"e-mandi/listings/{l.id}/{uuid.uuid4()}.pdf"
    st = app_ctx.state.fake_storage
    st.put(orphan, b"x")
    old = datetime.now(UTC) - timedelta(days=3)
    st.modified[orphan] = st.modified[d["objectKey"]] = old
    out = await RecoveryService(get_sessionmaker(), get_settings(), RecordingJobQueue(), redis, st, None).sweep_orphan_images()
    assert out["deleted"] == 1 and orphan not in st.objects and d["objectKey"] in st.objects


async def test_listing_shows_verified_document_count(app_ctx, client, db):
    admin = await make_admin(db, client)
    h, l = await setup(client, db)
    did = wire((await upload_confirm(client, app_ctx, h, l.id, pdf_bytes()))[1])["data"]["id"]
    assert wire(await client.get(f"/api/v1/listings/{l.id}", headers=h))["data"]["verifiedDocumentCount"] == 0
    await client.post(f"{D}/{did}/verify", headers=admin)
    assert wire(await client.get(f"/api/v1/listings/{l.id}", headers=h))["data"]["verifiedDocumentCount"] == 1
