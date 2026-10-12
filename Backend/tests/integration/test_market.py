from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from app.core.dependencies import get_embedding_provider
from app.models.audit_log import AuditLog
from app.models.market_report import MarketReport
from app.services.embedding import EmbeddingProviderError, HashEmbeddingProvider
from app.workers.embedding_jobs import embed_market_reports_job
from tests.integration.conftest import bearer, register
from tests.integration.test_grading import make_admin

M = "/api/v1/market"
TODAY = date.today()


def rep(crop="Tomato", days_ago=0, avg=30.0, location="Bengaluru", market="Yeshwanthpur APMC", source="Sample Data", **kw):
    return {"crop": crop, "location": location, "market": market, "min_price": avg - 3, "max_price": avg + 4,
            "average_price": avg, "report_date": str(TODAY - timedelta(days=days_ago)), "source": source,
            "is_sample": True, **kw}


async def seed(client, admin, reports):
    r = await client.post(f"{M}/reports", json={"reports": reports}, headers=admin)
    assert r.status_code == 201, r.text
    return r


async def test_ingest_rbac_and_validation(client, db):
    admin = await make_admin(db, client)
    farmer = bearer(await register(client))
    assert (await client.post(f"{M}/reports", json={"reports": [rep()]}, headers=farmer)).status_code == 403
    assert (await client.post(f"{M}/reports", json={"reports": [rep()]})).status_code == 401
    for bad in ({"min_price": 40.0}, {"max_price": 10.0}, {"average_price": 0}, {"average_price": 10.555},
                {"report_date": str(TODAY + timedelta(days=5))}, {"crop": "x"}, {"unknown": 1}):
        r = await client.post(f"{M}/reports", json={"reports": [{**rep(), **bad}]}, headers=admin)
        assert r.status_code == 422, bad
    assert (await client.post(f"{M}/reports", json={"reports": []}, headers=admin)).status_code == 422


async def test_upsert_is_idempotent_normalises_crop_and_audited(app_ctx, client, db):
    admin = await make_admin(db, client)
    r = await seed(client, admin, [rep(crop="tamatar", avg=30.0)])
    assert r.json()["data"] == {"upserted": 1, "embedding_job_queued": True}
    assert app_ctx.state.fake_queue.jobs[-1][0] == "embed_market_reports_job"
    await seed(client, admin, [rep(crop="TOMATO", avg=32.0), rep(crop="Tomato", avg=32.0)])  # same natural key x2
    rows = (await db.scalars(select(MarketReport))).all()
    assert len(rows) == 1 and rows[0].crop == "Tomato" and rows[0].average_price_paise == 3200
    a = (await db.scalars(select(AuditLog).where(AuditLog.action == "market.reports_upserted"))).all()
    assert len(a) == 2 and a[0].meta["crops"] == ["Tomato"] and a[0].meta["sample"] is True


async def test_prices_latest_and_filters(client, db):
    admin = await make_admin(db, client)
    await seed(client, admin, [rep(days_ago=2, avg=28), rep(days_ago=0, avg=31), rep(crop="Onion", avg=20),
                               rep(location="Mysuru", market="Mysuru APMC", avg=27), rep(days_ago=200, avg=10)])
    h = bearer(await register(client))
    d = (await client.get(f"{M}/prices?crop=tamatar&days=30", headers=h)).json()["data"]
    assert len(d) == 3 and all(x["crop"] == "Tomato" and x["is_sample"] for x in d)
    assert d[0]["report_date"] >= d[-1]["report_date"] and isinstance(d[0]["average_price"], float)
    assert len((await client.get(f"{M}/prices?crop=Tomato&location=mysuru", headers=h)).json()["data"]) == 1
    assert len((await client.get(f"{M}/prices?crop=Tomato&days=365", headers=h)).json()["data"]) == 4
    assert (await client.get(f"{M}/latest?crop=tomato&location=Bengaluru", headers=h)).json()["data"]["average_price"] == 31.0
    assert (await client.get(f"{M}/latest?crop=tomato&location=Nowhere", headers=h)).json()["data"]["crop"] == "Tomato"  # falls back
    assert (await client.get(f"{M}/latest?crop=dragonfruit", headers=h)).status_code == 404
    assert (await client.get(f"{M}/prices")).status_code == 401


async def test_embedding_job_and_semantic_search(app_ctx, client, db):
    admin = await make_admin(db, client)
    await seed(client, admin, [rep(), rep(crop="Onion", avg=20), rep(crop="Wheat", location="Delhi", market="Azadpur", avg=25)])
    assert await embed_market_reports_job({"embedder": HashEmbeddingProvider(768)}) == 3
    assert await embed_market_reports_job({"embedder": HashEmbeddingProvider(768)}) == 0  # nothing left
    n = (await db.execute(text("select count(*) from market_reports where embedding is not null"))).scalar()
    assert n == 3
    h = bearer(await register(client))
    d = (await client.get(f"{M}/search?q=tomato price in Bengaluru", headers=h)).json()["data"]
    assert d["mode"] == "semantic" and d["crop"] == "Tomato"
    assert d["hits"][0]["report"]["crop"] == "Tomato" and 0 < d["hits"][0]["similarity"] <= 1
    d2 = (await client.get(f"{M}/search?q=ಈರುಳ್ಳಿ ಬೆಲೆ", headers=h)).json()["data"]  # Kannada -> canonical crop filter
    assert d2["crop"] == "Onion" and d2["hits"][0]["report"]["crop"] == "Onion"
    d3 = (await client.get(f"{M}/search?q=grain rates&location=delhi", headers=h)).json()["data"]
    assert [x["report"]["crop"] for x in d3["hits"]] == ["Wheat"]


async def test_changed_report_is_reembedded_and_other_model_vectors_ignored(app_ctx, client, db):
    admin = await make_admin(db, client)
    await seed(client, admin, [rep()])
    await embed_market_reports_job({"embedder": HashEmbeddingProvider(768)})
    await seed(client, admin, [rep(avg=35.0)])  # update -> embedding invalidated
    row = (await db.scalars(select(MarketReport))).one()
    await db.refresh(row)
    assert row.embedding is None and row.embedding_model is None
    await embed_market_reports_job({"embedder": HashEmbeddingProvider(768)})
    await db.execute(text("update market_reports set embedding_model = 'gemini:other:768'"))
    await db.commit()
    h = bearer(await register(client))
    d = (await client.get(f"{M}/search?q=tomato", headers=h)).json()["data"]
    assert d["mode"] == "keyword"  # vectors from another model are never compared; deterministic fallback used


async def test_search_falls_back_to_keyword_when_provider_fails(app_ctx, client, db):
    admin = await make_admin(db, client)
    await seed(client, admin, [rep()])

    class Broken:
        model_id, dim = "gemini:x:768", 768

        async def embed_query(self, t):
            raise EmbeddingProviderError("timeout")

    app_ctx.dependency_overrides[get_embedding_provider] = lambda: Broken()
    h = bearer(await register(client))
    d = (await client.get(f"{M}/search?q=tamatar bhav", headers=h)).json()["data"]
    assert d["mode"] == "keyword" and d["hits"][0]["report"]["crop"] == "Tomato" and d["hits"][0]["similarity"] is None


async def test_search_validation_and_rate_limit(client, db):
    h = bearer(await register(client))
    assert (await client.get(f"{M}/search?q=x", headers=h)).status_code == 422
    assert (await client.get(f"{M}/search?q=tomato&k=99", headers=h)).status_code == 422
    codes = [(await client.get(f"{M}/search?q=tomato", headers=h)).status_code for _ in range(32)]
    assert codes[:28] == [200] * 28 and codes[-1] == 429  # 2 invalid requests above also count


async def test_price_recommendation_endpoint_contract(client, db):
    admin = await make_admin(db, client)
    await seed(client, admin, [rep(days_ago=d, avg=30 + d * 0.0) for d in (0, 1, 2, 3)])
    h = bearer(await register(client))
    r = await client.get(f"{M}/price-recommendation?crop=tamatar&location=Bengaluru&grade=A&quantity_kg=200", headers=h)
    d = r.json()["data"]
    assert r.status_code == 200
    assert {"suggested", "rangeMin", "rangeMax", "referencePrice", "trend", "explanation", "source"} <= d.keys()
    assert d["rangeMin"] <= d["suggested"] <= d["rangeMax"] and d["referencePrice"] == 30.0
    assert d["suggested"] == 33.0 and d["isSample"] is True and d["scope"] == "local" and "Sample" in d["source"]
    assert d["factors"][1]["name"] == "grade" and "effectPct" in d["factors"][1]
    b = (await client.get(f"{M}/price-recommendation?crop=tomato&grade=D", headers=h)).json()["data"]
    assert b["scope"] == "national_fallback" and b["suggested"] < 30  # no location => national scope, grade D discount
    assert (await client.get(f"{M}/price-recommendation?crop=dragonfruit", headers=h)).status_code == 404
    assert (await client.get(f"{M}/price-recommendation?crop=tomato&quantity_kg=0", headers=h)).status_code == 422
    assert (await client.get(f"{M}/price-recommendation?crop=tomato&grade=Z", headers=h)).status_code == 422
