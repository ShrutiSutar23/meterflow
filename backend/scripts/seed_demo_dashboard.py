"""
Seed demo dashboard data for a local MeterFlow user.

This script fills the normal backend stores used by the frontend:
- PostgreSQL usage_records drive billing summary cards.
- PostgreSQL api_keys drive the active key count.
- MongoDB api_request_logs drive charts and the Logs page.

Run from the repository root:
    python -m backend.scripts.seed_demo_dashboard --username john_dev
"""

import argparse
import asyncio
import hashlib
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, delete, select


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config.database import AsyncSessionLocal, pg_engine, Base  # noqa: E402
from backend.config.settings import settings  # noqa: E402
from backend.models.apikey_model import APIKey  # noqa: E402
from backend.models.billing_model import UsageRecord  # noqa: E402
from backend.models.log_model import LOGS_COLLECTION  # noqa: E402
from backend.models.user_model import User  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


DEMO_ENDPOINT_PREFIX = "/api/v1/demo/"
DEMO_SOURCE = "dashboard_seed"


def _make_key(environment: str = "live") -> tuple[str, str, str]:
    raw = secrets.token_urlsafe(32)
    full_key = f"mf_{environment}_{raw}"
    return full_key, full_key[:12], hashlib.sha256(full_key.encode()).hexdigest()


async def _find_user(session, username: str | None, email: str | None) -> User:
    filters = []
    if username:
        filters.append(User.username == username)
    if email:
        filters.append(User.email == email)

    if filters:
        result = await session.execute(select(User).where(*filters))
        user = result.scalar_one_or_none()
        if user:
            return user

    result = await session.execute(select(User).order_by(User.created_at.desc()))
    user = result.scalars().first()
    if not user:
        raise RuntimeError("No users found. Sign up in the app first, then rerun this script.")
    return user


async def _ensure_api_keys(session, user: User) -> list[APIKey]:
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.created_at.asc())
    )
    keys = list(result.scalars().all())
    active = [key for key in keys if key.is_active]

    while len(active) < 2:
        _, prefix, key_hash = _make_key("live" if len(active) == 0 else "test")
        api_key = APIKey(
            user_id=user.id,
            key_prefix=prefix,
            key_hash=key_hash,
            name="Demo Production Key" if len(active) == 0 else "Demo Test Key",
            description="Seeded demo key for dashboard testing",
            environment="live" if len(active) == 0 else "test",
            scopes=["read:usage", "write:events"],
            rate_limit_per_minute=120,
            rate_limit_per_day=10000,
            is_active=True,
        )
        session.add(api_key)
        await session.flush()
        active.append(api_key)

    return active


async def _seed_usage_records(session, user: User, keys: list[APIKey], total: int) -> None:
    billing_month = datetime.now(timezone.utc).strftime("%Y-%m")

    await session.execute(
        delete(UsageRecord).where(
            and_(
                UsageRecord.user_id == user.id,
                UsageRecord.billing_month == billing_month,
                UsageRecord.endpoint.like(f"{DEMO_ENDPOINT_PREFIX}%"),
            )
        )
    )

    endpoints = [
        "/api/v1/demo/checkout",
        "/api/v1/demo/customers",
        "/api/v1/demo/meters",
        "/api/v1/demo/invoices",
        "/api/v1/demo/webhooks",
    ]
    methods = ["GET", "POST", "POST", "GET", "POST"]
    now = datetime.now(timezone.utc)

    rows = []
    for idx in range(total):
        day_offset = idx % 14
        endpoint_index = idx % len(endpoints)
        status_code = 500 if idx % 97 == 0 else 429 if idx % 71 == 0 else 404 if idx % 43 == 0 else 200
        rows.append(
            UsageRecord(
                user_id=user.id,
                api_key_id=keys[idx % len(keys)].id if keys else None,
                endpoint=endpoints[endpoint_index],
                method=methods[endpoint_index],
                status_code=status_code,
                response_time_ms=round(random.uniform(32, 260), 1),
                units_consumed=1,
                cost_usd=0.0005 if status_code < 500 else 0.0,
                billing_month=billing_month,
                created_at=now - timedelta(days=day_offset, minutes=idx % 720),
            )
        )

    session.add_all(rows)
    user.requests_this_month = total
    user.monthly_request_limit = user.monthly_request_limit or 10000
    user.plan = user.plan or "free"


async def _seed_mongo_logs(user: User, keys: list[APIKey], total: int) -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        db = client[settings.MONGODB_DB_NAME]
        collection = db[LOGS_COLLECTION]

        await collection.delete_many({"user_id": str(user.id), "metadata.source": DEMO_SOURCE})

        endpoints = [
            ("/api/v1/demo/checkout", "POST"),
            ("/api/v1/demo/customers", "GET"),
            ("/api/v1/demo/meters", "POST"),
            ("/api/v1/demo/invoices", "GET"),
            ("/api/v1/demo/webhooks", "POST"),
        ]
        now = datetime.now(timezone.utc)
        docs = []

        daily_base = [280, 340, 420, 390, 510, 460, 620, 570, 690, 740, 680, 810, 760, 880]
        base_total = max(sum(daily_base), 1)
        daily_counts = [int(base_count * total / base_total) for base_count in daily_base]
        for idx in range(total - sum(daily_counts)):
            daily_counts[-(idx % len(daily_counts)) - 1] += 1

        for day_index, count in enumerate(daily_counts):
            day = now - timedelta(days=13 - day_index)
            for request_index in range(count):
                endpoint, method = endpoints[(request_index + day_index) % len(endpoints)]
                status_code = 500 if request_index % 101 == 0 else 429 if request_index % 79 == 0 else 404 if request_index % 53 == 0 else 200
                is_error = status_code >= 400
                docs.append(
                    {
                        "request_id": f"demo-{day_index:02d}-{request_index:04d}",
                        "user_id": str(user.id),
                        "api_key_id": str(keys[request_index % len(keys)].id) if keys else None,
                        "endpoint": endpoint,
                        "method": method,
                        "status_code": status_code,
                        "response_time_ms": round(random.uniform(28, 310), 1),
                        "request_size_bytes": random.randint(180, 2200),
                        "response_size_bytes": random.randint(420, 9600),
                        "ip_address": f"192.168.1.{20 + request_index % 120}",
                        "user_agent": "MeterFlow Demo Client/1.0",
                        "is_error": is_error,
                        "error_message": "Demo request failed" if is_error else None,
                        "error_type": "DemoError" if is_error else None,
                        "billing_month": day.strftime("%Y-%m"),
                        "is_billable": True,
                        "metadata": {"source": DEMO_SOURCE, "demo": True},
                        "timestamp": day.replace(
                            hour=request_index % 24,
                            minute=(request_index * 7) % 60,
                            second=(request_index * 13) % 60,
                            microsecond=0,
                        ),
                    }
                )

        if docs:
            await collection.insert_many(docs)
    finally:
        client.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local MeterFlow dashboard demo data.")
    parser.add_argument("--username", default="john_dev", help="Target username. Defaults to john_dev.")
    parser.add_argument("--email", default="developer@example.com", help="Target email. Defaults to developer@example.com.")
    parser.add_argument("--requests", type=int, default=6840, help="Demo request count for this month.")
    args = parser.parse_args()

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        user = await _find_user(session, args.username, args.email)
        keys = await _ensure_api_keys(session, user)
        await _seed_usage_records(session, user, keys, args.requests)
        await session.commit()

    await _seed_mongo_logs(user, keys, args.requests)

    print(f"Seeded dashboard data for {user.username} <{user.email}>")
    print(f"Requests this month: {args.requests}")
    print(f"Active API keys ensured: {len([key for key in keys if key.is_active])}")


if __name__ == "__main__":
    asyncio.run(main())
