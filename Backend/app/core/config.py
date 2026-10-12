"""Typed application settings, loaded only from environment variables / .env."""
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = {"", "replace-with-long-random-string", "change-me", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"
    DEMO_MODE: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Data stores
    DATABASE_URL: str = "postgresql+asyncpg://emandi:change-me@localhost:5432/emandi"
    REDIS_URL: str = "redis://localhost:6379/0"
    EMBEDDING_DIM: int = 768
    EMBEDDING_PROVIDER: Literal["hash", "gemini"] = "hash"  # hash = offline lexical (dev/test); gemini = semantic
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10

    # JWT / sessions
    JWT_SECRET: SecretStr = SecretStr("")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    JWT_ISSUER: str = "e-mandi"

    # OTP
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_LENGTH: int = 6

    # Google OIDC
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")

    # AWS / S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: SecretStr = SecretStr("")
    AWS_REGION: str = "ap-south-1"
    AWS_S3_BUCKET: str = ""
    AWS_S3_PUBLIC_BASE_URL: str = ""
    S3_PRESIGN_EXPIRE_SECONDS: int = 300
    S3_READ_URL_EXPIRE_SECONDS: int = 900
    S3_ENDPOINT_URL: str = ""  # optional (LocalStack/MinIO in dev)
    IMAGE_MAX_COUNT_PER_LISTING: int = 5
    IMAGE_MAX_BYTES: int = 5 * 1024 * 1024
    IMAGE_MIN_DIMENSION: int = 200
    IMAGE_MAX_DIMENSION: int = 8000

    # AI providers (model names are ALWAYS configuration)
    GEMINI_API_KEY: SecretStr = SecretStr("")
    GEMINI_VISION_MODEL: str = ""
    GEMINI_EMBEDDING_MODEL: str = ""
    GEMINI_TEXT_MODEL: str = ""
    OPENAI_API_KEY: SecretStr = SecretStr("")
    OPENAI_VISION_MODEL: str = ""
    OPENAI_TRANSCRIPTION_MODEL: str = ""
    OPENAI_TEXT_MODEL: str = ""
    GRADING_CONFIDENCE_THRESHOLD: float = 0.75
    AI_PROVIDER_TIMEOUT_SECONDS: float = 30.0
    GRADING_CACHE_TTL_DAYS: int = 30
    GRADING_MAX_ATTEMPTS: int = 3

    # Payments
    PAYMENT_PROVIDER: Literal["mock", "razorpay"] = "mock"
    PAYMENT_KEY_ID: str = ""
    PAYMENT_KEY_SECRET: SecretStr = SecretStr("")
    PAYMENT_WEBHOOK_SECRET: SecretStr = SecretStr("")
    RESERVATION_TTL_MINUTES: int = 30

    # Buyer matching: search scope expansion (km; 0 = same city, -1 = anywhere) and result cap
    MATCH_RADIUS_STEPS_KM: str = "0,50,150,400,-1"
    MATCH_MAX_RESULTS: int = 10

    # Backups
    BACKUP_S3_BUCKET: str = ""
    BACKUP_S3_PREFIX: str = "e-mandi/backups/"
    BACKUP_RETENTION_DAYS: int = 14

    @property
    def match_radius_steps(self) -> list[int]:
        return [int(x) for x in self.MATCH_RADIUS_STEPS_KM.split(",") if x.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if "*" in self.cors_origins_list:
            raise ValueError("CORS_ORIGINS must not contain '*' (credentials are enabled)")
        secret = self.JWT_SECRET.get_secret_value()
        if self.ENVIRONMENT == "production":
            if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
                raise ValueError("JWT_SECRET must be a random string of >= 32 chars in production")
        elif secret in _INSECURE_JWT_SECRETS:
            # Dev/test convenience only. Never reachable in production (checked above).
            object.__setattr__(self, "JWT_SECRET", SecretStr("dev-only-insecure-secret-not-for-prod-0000"))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
