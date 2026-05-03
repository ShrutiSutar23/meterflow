# backend/tasks/log_tasks.py
"""
Celery Log Tasks
=================
These tasks run in the background (not in the web server process).

How it works:
  1. Web request comes in
  2. Middleware captures the log data
  3. Middleware calls: save_request_log.delay(log_data)
      ↑ This is NON-BLOCKING — returns immediately
  4. Celery worker (separate process) picks up the task
  5. Worker writes to MongoDB + updates Redis counters
  6. Web server already sent the response 50ms ago

The .delay() call puts the task into Redis queue.
A separate Celery worker process picks it up and runs it.

To start the Celery worker:
  celery -A config.celery_app worker --loglevel=info

To start the scheduler (for cron jobs):
  celery -A config.celery_app beat --loglevel=info
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.config.celery_app import celery_app


def _run_async(coro):
    """
    Helper to run async code inside a Celery task.
    
    Celery tasks are synchronous by default.
    Our database calls are async (motor, aioredis).
    This helper creates a new event loop to bridge the gap.
    
    Real-world pattern: Many teams use celery-pool-asyncio
    for a cleaner solution, but this works perfectly for our needs.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="tasks.log_tasks.save_request_log",
    bind=True,              # 'self' = access to task instance (for retries)
    max_retries=3,
    default_retry_delay=10, # 10 seconds between retries
    ignore_result=True,     # We don't need the return value stored in Redis
)
def save_request_log(self, log_doc: dict[str, Any]) -> None:
    """
    Save one API request log to MongoDB.
    Also updates the real-time usage counters in Redis.
    
    Called by: RequestLoggerMiddleware after every request
    Runs in:   Celery worker process (background)
    
    Args:
        log_doc: Dictionary representation of an APIRequestLog
    """
    try:
        _run_async(_save_log_async(log_doc))
    except Exception as exc:
        # Retry the task if it fails (network blip, MongoDB timeout, etc.)
        raise self.retry(exc=exc)


async def _save_log_async(log_doc: dict[str, Any]) -> None:
    """
    Actual async implementation of log saving.
    
    Does 3 things:
    1. Insert the log document into MongoDB
    2. Increment the user's request counter in PostgreSQL (async)
    3. Update real-time counters in Redis for dashboards
    """
    from backend.config.database import mongo_db, redis_client, AsyncSessionLocal
    from backend.models.log_model import LOGS_COLLECTION
    from sqlalchemy import update
    from backend.models.user_model import User
    from backend.models.apikey_model import APIKey
    from datetime import timezone

    # ── 1. Write to MongoDB ───────────────────────────────────────────────────
    if mongo_db is not None:
        # Convert datetime strings back to datetime objects if needed
        if isinstance(log_doc.get("timestamp"), str):
            from datetime import datetime
            log_doc["timestamp"] = datetime.fromisoformat(log_doc["timestamp"])

        await mongo_db[LOGS_COLLECTION].insert_one(log_doc)

    # ── 2. Update PostgreSQL usage counters ────────────────────────────────────
    user_id = log_doc.get("user_id")
    api_key_id = log_doc.get("api_key_id")
    is_billable = log_doc.get("is_billable", True)

    if user_id and is_billable:
        async with AsyncSessionLocal() as db:
            # Increment user's monthly request count
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(requests_this_month=User.requests_this_month + 1)
            )
            # Increment API key's lifetime request count
            if api_key_id:
                from datetime import datetime, timezone
                await db.execute(
                    update(APIKey)
                    .where(APIKey.id == api_key_id)
                    .values(
                        total_requests=APIKey.total_requests + 1,
                        last_used_at=datetime.now(timezone.utc),
                    )
                )
            await db.commit()

    # ── 3. Update real-time Redis counters ────────────────────────────────────
    # These power the live dashboard numbers
    if redis_client and user_id and is_billable:
        billing_month = log_doc.get("billing_month", datetime.now(timezone.utc).strftime("%Y-%m"))
        status_code = log_doc.get("status_code", 200)
        is_error = status_code >= 400

        pipe = redis_client.pipeline()

        # Monthly request count per user
        pipe.incr(f"usage:{user_id}:{billing_month}:total")
        pipe.expire(f"usage:{user_id}:{billing_month}:total", 86400 * 35)  # 35 days

        # Error count
        if is_error:
            pipe.incr(f"usage:{user_id}:{billing_month}:errors")
            pipe.expire(f"usage:{user_id}:{billing_month}:errors", 86400 * 35)

        # Today's request count (for daily charts)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pipe.incr(f"usage:{user_id}:daily:{today}")
        pipe.expire(f"usage:{user_id}:daily:{today}", 86400 * 8)  # 8 days

        await pipe.execute()


@celery_app.task(
    name="tasks.log_tasks.bulk_save_logs",
    ignore_result=True,
)
def bulk_save_logs(log_docs: list[dict]) -> None:
    """
    Batch insert multiple logs at once.
    More efficient than individual inserts for high-traffic scenarios.
    
    Used when: Processing backlog, replaying logs, testing.
    """
    _run_async(_bulk_save_async(log_docs))


async def _bulk_save_async(log_docs: list[dict]) -> None:
    from backend.config.database import mongo_db
    from backend.models.log_model import LOGS_COLLECTION

    if mongo_db and log_docs:
        await mongo_db[LOGS_COLLECTION].insert_many(log_docs, ordered=False)
        # ordered=False means: don't stop if one insert fails
