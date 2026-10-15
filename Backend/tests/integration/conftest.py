import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.core.config import get_settings
from app.core.database import dispose_engine, get_engine, get_sessionmaker
from app.core.dependencies import get_google_verifier, get_job_queue, get_otp_sender, get_payment_provider, get_storage
from app.core.errors import ProviderError, UnauthorizedError
from app.integrations.aws.s3 import ObjectHead, PresignedPost
from app.integrations.google.oidc import GoogleIdentity
from app.integrations.payments.mock import MockPaymentProvider
from app.main import create_app
from app.models.base import Base
from app.models.enums import AuthProvider, UserRole
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.auth import DEMO_ACCOUNTS
from app.workers.queue import RecordingJobQueue
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True,
                   capture_output=True)


class FakeGoogle:
    def __init__(self) -> None:
        self.identity: GoogleIdentity | None = None

    async def verify(self, credential: str) -> GoogleIdentity:
        if self.identity is None or credential.startswith("bad"):
            raise UnauthorizedError("Invalid Google credential")
        return self.identity


class CaptureOTP:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    async def send(self, phone: str, code: str) -> None:
        self.codes[phone] = code


class FakeStorage:
    """In-memory ObjectStorage (same Protocol as S3Storage)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.modified: dict[str, object] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def presign_post(self, key, content_type, max_bytes, expires):
        return PresignedPost("https://fake-s3.local/bucket", {"key": key, "Content-Type": content_type})

    async def presign_get(self, key, expires):
        return f"https://fake-s3.local/{key}?sig=abc"

    async def head(self, key):
        return ObjectHead(len(self.objects[key]), None) if key in self.objects else None

    async def get_bytes(self, key, max_bytes):
        data = self.objects[key]
        if len(data) > max_bytes:
            raise ProviderError("too big")
        return data

    async def delete(self, key):
        self.objects.pop(key, None)

    async def list_keys(self, prefix, limit):
        from datetime import UTC, datetime
        return [(k, self.modified.get(k, datetime.now(UTC))) for k in sorted(self.objects) if k.startswith(prefix)][:limit]


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[Redis]:
    r = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


@pytest_asyncio.fixture
async def app_ctx(redis):
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    app = create_app()
    app.state.redis = redis
    google, otp = FakeGoogle(), CaptureOTP()
    app.dependency_overrides[get_google_verifier] = lambda: google
    app.dependency_overrides[get_otp_sender] = lambda: otp
    storage, queue = FakeStorage(), RecordingJobQueue()
    provider = MockPaymentProvider(get_settings())
    app.dependency_overrides[get_payment_provider] = lambda: provider
    app.state.fake_provider = provider
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.state.fake_queue = queue
    app.dependency_overrides[get_storage] = lambda: storage
    app.state.fake_google, app.state.fake_otp, app.state.fake_storage = google, otp, storage
    yield app
    await dispose_engine()


@pytest_asyncio.fixture
async def client(app_ctx) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_ctx), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    async with get_sessionmaker()() as s:
        yield s


@pytest_asyncio.fixture
async def demo_users(db) -> dict[str, User]:
    out = {}
    for kind, (email, role, name) in DEMO_ACCOUNTS.items():
        u = User(email=email, full_name=name, role=role, is_demo=True, email_verified=True,
                 auth_provider=AuthProvider.LOCAL, profile=UserProfile(display_name=name))
        db.add(u)
        out[kind] = u
    await db.commit()
    return out


REG = {"email": "farmer1@example.com", "password": "Sup3rSecret!", "full_name": "Ravi Kumar", "role": "FARMER"}


async def register(client: AsyncClient, **over) -> dict:
    r = await client.post("/api/v1/auth/register", json={**REG, **over})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


_ = uuid, UserRole
