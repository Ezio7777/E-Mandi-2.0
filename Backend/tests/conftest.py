"""Global test environment. Forces an isolated DB/Redis so tests can never touch dev data."""
import os

os.environ.update({
    "ENVIRONMENT": "test",
    "DEMO_MODE": "true",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
                                   "postgresql+asyncpg://postgres:postgres@localhost:5433/emandi_test"),
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1"),
    "JWT_SECRET": "test-secret-test-secret-test-secret-0123456789",
    "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "LOG_LEVEL": "WARNING",
    "PAYMENT_PROVIDER": "mock",
    "PAYMENT_KEY_ID": "rzp_test_mockkey",
    "PAYMENT_WEBHOOK_SECRET": "test-webhook-secret-0123456789",
})
