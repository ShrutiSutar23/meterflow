# # backend/config/settings.py
# """
# Settings / Environment Variables
# ==================================
# We NEVER hardcode passwords or secrets in code.
# Instead, we use a .env file (ignored by git) and load it here.

# Real-world: Companies like Stripe, Twilio, AWS all use environment
# variables to keep secrets out of source code (prevents breaches).
# """

# from pydantic_settings import BaseSettings
# from functools import lru_cache


# class Settings(BaseSettings):
#     # ── App ───────────────────────────────────────────────────────────────────
#     APP_NAME: str = "MeterFlow"
#     DEBUG: bool = False
#     API_VERSION: str = "v1"

#     # ── PostgreSQL (Users, Billing, API Keys) ─────────────────────────────────
#     # Why PostgreSQL? It's relational - perfect for structured data like 
#     # users, payments, and API keys that have clear relationships.
#     POSTGRES_URL: str = "postgresql+asyncpg://meterflow_user:password@localhost:5432/meterflow_db"

#     # ── MongoDB (API Logs) ────────────────────────────────────────────────────
#     # Why MongoDB? Logs are unstructured, high-volume, and schema-flexible.
#     # Each API call may have different metadata - MongoDB handles this perfectly.
#     MONGODB_URL: str = "mongodb://localhost:27017"
#     MONGODB_DB_NAME: str = "meterflow_logs"

#     # ── Redis (Rate Limiting + Caching) ───────────────────────────────────────
#     # Why Redis? It's in-memory (lightning fast). 
#     # Perfect for: "has this user made 100 requests in the last minute?"
#     REDIS_URL: str = "redis://localhost:6379"

#     # ── JWT Authentication ────────────────────────────────────────────────────
#     # JWT = JSON Web Token. Like a signed hotel keycard - proves who you are.
#     # SECRET_KEY signs the token. NEVER share this. 
#     # Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
#     JWT_SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION_USE_RANDOM_64_CHAR_STRING"
#     JWT_ALGORITHM: str = "HS256"
#     JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60        # 1 hour
#     JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7           # 1 week

#     # ── Rate Limiting ─────────────────────────────────────────────────────────
#     RATE_LIMIT_PER_MINUTE: int = 60     # Free tier: 60 req/min
#     RATE_LIMIT_BURST: int = 10          # Allow short bursts

#     # ── Billing Tiers ────────────────────────────────────────────────────────
#     FREE_TIER_MONTHLY_REQUESTS: int = 10_000
#     COST_PER_1000_REQUESTS: float = 0.50  # $0.50 per 1000 requests (like AWS pricing)

#     # ── Stripe (for later) ───────────────────────────────────────────────────
#     STRIPE_SECRET_KEY: str = ""
#     STRIPE_WEBHOOK_SECRET: str = ""

#     # ── Email / SendGrid (Day 11) ────────────────────────────────────────────
#     SENDGRID_API_KEY: str = ""          # SG.xxxxx — get from app.sendgrid.com
#     EMAIL_FROM: str = "noreply@meterflow.io"  # Must be verified in SendGrid

#     class Config:
#         env_file = ".env"         # Load from .env file
#         env_file_encoding = "utf-8"
#         case_sensitive = True


# # ── Singleton Pattern ─────────────────────────────────────────────────────────
# # lru_cache means we only create Settings() ONCE - not on every import.
# # This is a common production pattern to avoid re-reading .env repeatedly.
# @lru_cache()
# def get_settings() -> Settings:
#     return Settings()


# settings = get_settings()

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "MeterFlow"
    DEBUG: bool = False
    API_VERSION: str = "v1"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    POSTGRES_URL: str = "postgresql+asyncpg://meterflow_user:password@localhost:5432/meterflow_db"

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "meterflow_logs"

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── JWT Authentication ────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION_USE_RANDOM_64_CHAR_STRING"
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

    # ── Configuration Loader ──────────────────────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()