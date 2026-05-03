# backend/tasks/metric_tasks.py
"""
Metric Aggregation Tasks
==========================
Pre-computes hourly metrics and caches them in Redis.

Why pre-aggregate?
  - Dashboard loads in <100ms instead of querying millions of raw logs
  - Reduces MongoDB query load
  - Enables real-time counter updates

This is the "Lambda Architecture" pattern:
  - Batch layer:   MongoDB stores raw logs (source of truth)
  - Speed layer:   Redis stores real-time counters
  - Serving layer: Pre-aggregated summaries for dashboards

Real-world: Netflix, LinkedIn, Airbnb all use this pattern.
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


@celery_app.task(name="tasks.metric_tasks.aggregate_hourly_metrics")
def aggregate_hourly_metrics() -> dict:
    """
    Runs every hour (2 minutes past the hour).
    Computes metrics for the previous hour and caches in Redis.
    """
    return _run_async(_aggregate_hourly_async())


async def _aggregate_hourly_async() -> dict:
    from backend.config.database import mongo_db, redis_client, AsyncSessionLocal
    from sqlalchemy import select
    from backend.models.user_model import User
    from backend.models.log_model import LOGS_COLLECTION

    if not mongo_db:
        return {"status": "skipped", "reason": "MongoDB not connected"}

    now = datetime.now(timezone.utc)
    hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    hour_end = hour_start + timedelta(hours=1)
    hour_key = hour_start.strftime("%Y-%m-%d-%H")

    # Get all active users
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id).where(User.is_active == True))
        user_ids = [str(row[0]) for row in result.all()]

    processed = 0
    for user_id in user_ids:
        pipeline = [
            {"$match": {
                "user_id": user_id,
                "timestamp": {"$gte": hour_start, "$lt": hour_end},
            }},
            {"$group": {
                "_id": None,
                "count": {"$sum": 1},
                "errors": {"$sum": {"$cond": ["$is_error", 1, 0]}},
                "avg_latency": {"$avg": "$response_time_ms"},
            }},
        ]

        results = await mongo_db[LOGS_COLLECTION].aggregate(pipeline).to_list(1)

        if results and redis_client:
            r = results[0]
            cache_key = f"metrics:hourly:{user_id}:{hour_key}"
            await redis_client.hset(cache_key, mapping={
                "count": r["count"],
                "errors": r["errors"],
                "avg_latency": round(r.get("avg_latency") or 0, 1),
                "error_rate": round(r["errors"] / max(r["count"], 1) * 100, 2),
            })
            await redis_client.expire(cache_key, 86400 * 7)  # Keep 7 days
            processed += 1

    return {"hour": hour_key, "users_processed": processed}
