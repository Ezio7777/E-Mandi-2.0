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
    MAX_REQUEST_BYTES: int = 10 * 1024 * 1024  # app-level body cap (5 MB image/audio limits + multipart overhead)
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
    SMS_PROVIDER: Literal["auto", "console", "sns"] = "auto"  # auto: console in dev, NOT configured in production
    SMS_SENDER_ID: str = ""                                    # DLT-registered header (India); optional elsewhere
    SMS_AWS_REGION: str = ""                                   # SNS region for SMS (default AWS_REGION)
    SMS_TEMPLATE: str = "Your E-MANDI verification code is {code}. It expires in {minutes} minutes. Do not share it."

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
    DOCUMENT_MAX_BYTES: int = 5 * 1024 * 1024
    DOCUMENT_MAX_PAGES: int = 20
    DOCUMENT_MAX_PER_LISTING: int = 5

    # AI providers (model names are ALWAYS configuration)
    GEMINI_API_KEY: SecretStr = SecretStr("")
    GEMINI_VISION_MODEL: str = ""
    GEMINI_EMBEDDING_MODEL: str = ""
    GEMINI_TEXT_MODEL: str = ""
    OPENAI_API_KEY: SecretStr = SecretStr("")
    OPENAI_VISION_MODEL: str = ""
    OPENAI_TRANSCRIPTION_MODEL: str = ""
    GEMINI_TRANSCRIPTION_MODEL: str = ""
    OPENAI_TTS_MODEL: str = ""  # optional spoken answers; empty = text-only
    OPENAI_TTS_VOICE: str = ""
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

    # Disputes / live notifications
    DISPUTE_WINDOW_DAYS: int = 7  # after COMPLETED
    SSE_POLL_SECONDS: float = 3.0
    SSE_MAX_SECONDS: int = 300  # clients reconnect (Last-Event-ID) so connections are bounded
    SSE_MAX_CONNECTIONS_PER_USER: int = 3

    # Voice assistant (audio is processed in memory and never stored; transcripts live only in the short Redis session)
    VOICE_MAX_AUDIO_BYTES: int = 5 * 1024 * 1024
    VOICE_MAX_TEXT_CHARS: int = 500
    VOICE_SESSION_TTL_SECONDS: int = 1800
    VOICE_SESSION_MAX_TURNS: int = 6
    VOICE_TOOL_TIMEOUT_SECONDS: float = 10.0
    VOICE_TTS_MAX_CHARS: int = 600

    # Agent observability
    AGENT_STUCK_MINUTES: int = 15  # QUEUED/RUNNING longer than this is reported as stuck in the Agent Control Center
    ANALYTICS_CACHE_SECONDS: int = 300

    # Recovery sweepers (Stage 18)
    RECOVERY_QUEUED_AFTER_MINUTES: int = 5      # QUEUED execution older than this had its enqueue lost
    RECOVERY_RUNNING_AFTER_MINUTES: int = 30    # RUNNING execution older than this is presumed crashed
    RECOVERY_ANALYZING_AFTER_MINUTES: int = 30  # listing stuck in ANALYZING with no in-flight grading run
    RECOVERY_MAX_ATTEMPTS: int = 3              # re-enqueues per execution/listing before it is failed / routed to review
    RECOVERY_WEBHOOK_AFTER_SECONDS: int = 120   # stored-but-unprocessed payment events are re-applied after this
    RECOVERY_APPROVED_ACTION_MINUTES: int = 5   # PendingAction stuck APPROVED (crash before execution)
    RECOVERY_BATCH: int = 100
    RECOVERY_REMATCH_DAYS: int = 14
    ORPHAN_S3_AFTER_HOURS: int = 24
    ORPHAN_S3_MAX_DELETES: int = 200

    # Fraud & Risk Agent: deterministic rule thresholds. A rule firing means FLAGGED_FOR_REVIEW, never a verdict.
    RISK_PRICE_DEVIATION_MEDIUM_PCT: int = 50   # listing price vs market reference
    RISK_PRICE_DEVIATION_HIGH_PCT: int = 80
    RISK_LARGE_LOT_KG: int = 50000
    RISK_LISTING_EDITS_PER_HOUR: int = 5
    RISK_PAYMENT_FAILURES_24H: int = 3          # >= this: MEDIUM; >= this + 2: HIGH
    RISK_ORDERS_PER_HOUR: int = 10
    RISK_NEW_ACCOUNT_HOURS: int = 24
    RISK_NEW_ACCOUNT_ORDER_PAISE: int = 10_000_000  # Rs 1,00,000
    RISK_LOW_CONFIDENCE_FLAG: float = 0.5       # grading confidence below this is also a LOW signal
    RISK_PROPOSE_BAN_ON_HIGH: bool = False      # if true, a HIGH signal on a user queues a BAN_USER request for admin approval

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
            if self.SMS_PROVIDER == "console":
                raise ValueError("SMS_PROVIDER=console must not be used in production (it logs OTP codes)")
            if "change-me" in self.DATABASE_URL:
                raise ValueError("DATABASE_URL still contains the placeholder password in production")
            if self.PAYMENT_PROVIDER == "razorpay" and not (
                    self.PAYMENT_KEY_ID and self.PAYMENT_KEY_SECRET.get_secret_value() and self.PAYMENT_WEBHOOK_SECRET.get_secret_value()):
                raise ValueError("PAYMENT_KEY_ID, PAYMENT_KEY_SECRET and PAYMENT_WEBHOOK_SECRET are required for the razorpay provider")
        elif secret in _INSECURE_JWT_SECRETS:
            # Dev/test convenience only. Never reachable in production (checked above).
            object.__setattr__(self, "JWT_SECRET", SecretStr("dev-only-insecure-secret-not-for-prod-0000"))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
