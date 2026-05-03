# backend/tasks/billing_tasks.py
"""
Billing Celery Tasks (Cron Jobs)
==================================
These tasks run AUTOMATICALLY on a schedule (like Linux cron jobs).
The schedule is defined in config/celery_app.py.

Tasks in this file:
  1. aggregate_daily_usage    → Runs daily at midnight
  2. generate_monthly_invoices → Runs on 1st of each month at 1 AM
  3. check_usage_limits       → Runs hourly to send overage alerts
  4. reset_monthly_counters   → Runs on 1st to reset request counts

Real-world: This is how Stripe generates invoices, how AWS
sends billing alerts, and how Twilio resets monthly limits.

Interview topic: "How would you design a billing system?"
  Answer: Event-driven (log every call) + batch aggregation
  (sum up at month end) + scheduled jobs for invoicing.
"""

import asyncio
from datetime import datetime, timezone, timedelta

from backend.config.celery_app import celery_app


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="tasks.billing_tasks.aggregate_daily_usage")
def aggregate_daily_usage() -> dict:
    """
    Daily aggregation task — runs at 12:05 AM UTC.

    What it does:
    1. Queries yesterday's UsageRecords from PostgreSQL
    2. Groups by user
    3. Stores daily summary in Redis (for fast dashboard reads)

    Why aggregate? Instead of querying millions of raw records
    every time a user opens their dashboard, we pre-compute
    daily totals. This is called "materialized views" or
    "pre-aggregation" in data engineering.
    """
    return _run_async(_aggregate_daily_async())


async def _aggregate_daily_async() -> dict:
    from backend.config.database import AsyncSessionLocal, redis_client
    from sqlalchemy import select, func, and_
    from backend.models.billing_model import UsageRecord

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = yesterday.replace(hour=23, minute=59, second=59)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(
                UsageRecord.user_id,
                func.count(UsageRecord.id).label("total_requests"),
                func.sum(UsageRecord.cost_usd).label("total_cost"),
                func.avg(UsageRecord.response_time_ms).label("avg_latency"),
            )
            .where(
                and_(
                    UsageRecord.created_at >= start,
                    UsageRecord.created_at <= end,
                    UsageRecord.is_billable == True,
                )
            )
            .group_by(UsageRecord.user_id)
        )
        rows = result.all()

    # Store in Redis for fast dashboard reads
    processed = 0
    if redis_client:
        pipe = redis_client.pipeline()
        for row in rows:
            key = f"daily_usage:{row.user_id}:{date_str}"
            pipe.hset(key, mapping={
                "requests": row.total_requests,
                "cost_usd": round(row.total_cost or 0, 4),
                "avg_latency_ms": round(row.avg_latency or 0, 1),
            })
            pipe.expire(key, 86400 * 32)  # Keep for 32 days
            processed += 1
        await pipe.execute()

    return {"date": date_str, "users_processed": processed}


@celery_app.task(name="tasks.billing_tasks.generate_monthly_invoices")
def generate_monthly_invoices() -> dict:
    """
    Monthly invoice generation — runs on the 1st at 1 AM UTC.

    For each active user:
    1. Sum their usage records for the previous month
    2. Apply their plan pricing
    3. Generate an Invoice record
    4. Send invoice email (later: integrate with SendGrid)
    5. Trigger Stripe charge (later: Day 8)
    """
    return _run_async(_generate_invoices_async())


async def _generate_invoices_async() -> dict:
    from backend.config.database import AsyncSessionLocal
    from sqlalchemy import select
    from backend.models.user_model import User
    from backend.services.billing_service import generate_invoice

    # Calculate previous month (invoices are for last month)
    now = datetime.now(timezone.utc)
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    generated = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.is_active == True)
        )
        users = result.scalars().all()

        for user in users:
            try:
                await generate_invoice(db, str(user.id), prev_month)
                generated += 1
            except Exception as e:
                errors += 1
                print(f"Invoice error for user {user.id}: {e}")

        await db.commit()

    return {
        "billing_month": prev_month,
        "invoices_generated": generated,
        "errors": errors,
    }


@celery_app.task(name="tasks.billing_tasks.check_usage_limits")
def check_usage_limits() -> dict:
    """
    Overage alert task — runs hourly.

    If a user has used >80% or >100% of their monthly limit,
    send them a warning email/webhook.

    Real-world: AWS sends SNS notifications at 80%/100% of budget.
    Twilio sends emails before you hit SMS limits.
    """
    return _run_async(_check_limits_async())


async def _check_limits_async() -> dict:
    from backend.config.database import AsyncSessionLocal
    from sqlalchemy import select
    from backend.models.user_model import User

    alerts_sent = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.is_active == True)
        )
        users = result.scalars().all()

        for user in users:
            usage_pct = (user.requests_this_month / max(user.monthly_request_limit, 1)) * 100

            if usage_pct >= 100:
                # Send limit-exceeded email
                import asyncio
                from backend.services.email_service import send_usage_warning_email
                asyncio.create_task(send_usage_warning_email(
                    email=user.email,
                    username=user.username,
                    usage_pct=usage_pct,
                    requests_used=user.requests_this_month,
                    requests_limit=user.monthly_request_limit,
                    plan=user.plan,
                ))
                # Fire outbound webhook
                from backend.tasks.webhook_tasks import trigger_billing_webhook
                trigger_billing_webhook.delay(
                    user_id=str(user.id),
                    event_type="billing.limit_exceeded",
                    event_data={
                        "usage_pct": round(usage_pct, 1),
                        "requests_used": user.requests_this_month,
                        "requests_limit": user.monthly_request_limit,
                        "plan": user.plan,
                    },
                )
                alerts_sent += 1

            elif usage_pct >= 80:
                # Send 80% warning email
                import asyncio
                from backend.services.email_service import send_usage_warning_email
                asyncio.create_task(send_usage_warning_email(
                    email=user.email,
                    username=user.username,
                    usage_pct=usage_pct,
                    requests_used=user.requests_this_month,
                    requests_limit=user.monthly_request_limit,
                    plan=user.plan,
                ))
                # Fire outbound webhook
                from backend.tasks.webhook_tasks import trigger_billing_webhook
                trigger_billing_webhook.delay(
                    user_id=str(user.id),
                    event_type="billing.limit_warning",
                    event_data={
                        "usage_pct": round(usage_pct, 1),
                        "requests_used": user.requests_this_month,
                        "requests_limit": user.monthly_request_limit,
                        "plan": user.plan,
                    },
                )
                alerts_sent += 1

    return {"alerts_sent": alerts_sent}


@celery_app.task(name="tasks.billing_tasks.reset_monthly_counters")
def reset_monthly_counters() -> dict:
    """
    Reset request counters on the 1st of each month.
    Runs right after generate_monthly_invoices.
    """
    return _run_async(_reset_counters_async())


async def _reset_counters_async() -> dict:
    from backend.config.database import AsyncSessionLocal
    from sqlalchemy import update
    from backend.models.user_model import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(User).values(requests_this_month=0)
        )
        await db.commit()
        return {"users_reset": result.rowcount}
