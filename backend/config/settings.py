import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "MeterFlow"
    DEBUG: bool = False
    API_VERSION: str = "v1"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    POSTGRES_URL: str = (
        "postgresql+asyncpg://meterflow_user:password@localhost:5432/meterflow_db"
    )

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "meterflow_logs"

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── JWT Authentication ────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = (
        "CHANGE_THIS_IN_PRODUCTION_USE_RANDOM_64_CHAR_STRING"
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # ── Billing Tiers ─────────────────────────────────────────────────────────
    FREE_TIER_MONTHLY_REQUESTS: int = 10_000
    COST_PER_1000_REQUESTS: float = 0.50

    # ── Stripe & Email ────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    SENDGRID_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@meterflow.io"

    # ── Settings Loader ───────────────────────────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.exists(".env") else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()