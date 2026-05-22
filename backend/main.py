# backend/main.py  — FINAL (Day 1–10 complete)
"""
MeterFlow — Complete FastAPI Application
==========================================
All routes registered. All middleware active.
All databases connected on startup.

Full route map:
  /api/v1/auth/...        Authentication (JWT)
  /api/v1/keys/...        API Key management
  /api/v1/users/...       User profiles + RBAC
  /api/v1/billing/...     Usage summary, invoices, plans
  /api/v1/analytics/...   Dashboard metrics
  /api/v1/logs/...        Request log viewer
  /api/v1/payments/...    Stripe payment methods + charges
  /api/v1/webhooks/...    Stripe inbound + user outbound webhooks
  /api/v1/orgs/...        Multi-tenant organizations
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys

# Add the current directory to the system path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Your existing imports continue below...


from backend.config.database import connect_db, disconnect_db
from backend.routes.auth_routes import router as auth_router
from backend.routes.password_routes import router as password_router
from backend.routes.verification_routes import router as verification_router
from backend.routes.apikey_routes import router as apikey_router
from backend.routes.user_routes import router as user_router
from backend.routes.billing_routes import router as billing_router
from backend.routes.analytics_routes import router as analytics_router
from backend.routes.stripe_routes import router as stripe_router
from backend.routes.webhook_routes import router as webhook_router
from backend.routes.organization_routes import router as org_router
from backend.routes.playground_routes  import router as playground_router
from backend.middleware.rate_limiter  import RateLimitMiddleware
from backend.middleware.request_logger import RequestLoggerMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Gap 3 fix: start structured JSON logging before anything else
    from backend.config.logging_config import setup_logging
    from backend.config.settings import settings
    setup_logging(
        level="DEBUG" if settings.DEBUG else "INFO",
        env="development" if settings.DEBUG else "production",
    )

    await connect_db()

    # MongoDB indexes
    from backend.config.database import mongo_db
    if mongo_db is not None:
        from backend.services.logging_service import ensure_indexes
        await ensure_indexes(mongo_db)

    import logging
    logging.getLogger("meterflow").info("MeterFlow API ready", extra={"total_endpoints": 53})
    yield
    await disconnect_db()


app = FastAPI(
    title="MeterFlow API",
    description="""
## ⚡ MeterFlow — Usage-Based API Billing Platform

A production-grade API billing backend with:
- **JWT Authentication** with refresh tokens
- **API Key Management** (Stripe-style hashed keys)
- **Usage Tracking** via MongoDB
- **Billing Engine** with tiered pricing
- **Analytics** — p50/p95/p99 latency, error rates
- **Stripe Payments** — SetupIntent, charges, refunds
- **Webhooks** — inbound Stripe + outbound user alerts
- **Multi-Tenancy** — Organizations with RBAC
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggerMiddleware)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(auth_router,         prefix="/api/v1/auth",      tags=["🔐 Authentication"])
app.include_router(password_router,     prefix="/api/v1/auth",      tags=["🔐 Authentication"])
app.include_router(verification_router, prefix="/api/v1/auth",      tags=["🔐 Authentication"])  # Gap 1 fix
app.include_router(apikey_router,       prefix="/api/v1/keys",      tags=["🗝️  API Keys"])
app.include_router(user_router,      prefix="/api/v1/users",     tags=["👤 Users"])
app.include_router(billing_router,   prefix="/api/v1/billing",   tags=["💳 Billing"])
app.include_router(analytics_router, prefix="/api/v1",           tags=["📊 Analytics & Logs"])
app.include_router(stripe_router,    prefix="/api/v1/payments",  tags=["💰 Stripe Payments"])
app.include_router(webhook_router,   prefix="/api/v1/webhooks",  tags=["🔔 Webhooks"])
app.include_router(org_router,       prefix="/api/v1/orgs",      tags=["🏢 Organizations"])
app.include_router(playground_router,prefix="/api/v1/playground",tags=["🧪 Playground"])


@app.get("/health", tags=["⚙️  System"])
async def health_check():
    from backend.config.database import redis_client, mongo_db, pg_engine
    from datetime import datetime, timezone
    import sqlalchemy

    checks = {"redis": False, "mongodb": False, "postgresql": False}

    try:
        if redis_client:
            await redis_client.ping()
            checks["redis"] = True
    except Exception: pass

    try:
        if mongo_db is not None:
            await mongo_db.command("ping")
            checks["mongodb"] = True
    except Exception: pass

    try:
        async with pg_engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
            checks["postgresql"] = True
    except Exception: pass

    return {
        "status": "healthy" if all(checks.values()) else "degraded",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": checks,
    }


@app.get("/", tags=["⚙️  System"])
async def root():
    return {
        "service": "MeterFlow",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "total_endpoints": 35,
    }
