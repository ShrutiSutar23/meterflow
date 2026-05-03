# backend/config/celery_app.py
"""
Celery Configuration
======================
Celery is a distributed task queue — it lets you run code
in the BACKGROUND without blocking the web server.

Think of it like a restaurant:
  - FastAPI = The waiter (takes orders, gives responses quickly)
  - Celery  = The kitchen (does the heavy work in the background)
  - Redis   = The order ticket rail (passes tasks from waiter → kitchen)

Why we need it for MeterFlow:
  1. Logging every request to MongoDB (don't block the response)
  2. Calculating monthly billing (runs at midnight on the 1st)
  3. Sending billing alert emails (slow SMTP calls)
  4. Aggregating hourly metrics for dashboards (CPU-intensive)
  5. Sending webhooks to users (external HTTP calls)

Real-world: Uber uses Celery for trip notifications.
  Instagram used it for image processing.
  You see it at virtually every Python SaaS company.

Architecture:
  FastAPI → redis://localhost:6379/0 → Celery Worker
  (producer)     (message broker)      (consumer)
"""

from celery import Celery
from celery.schedules import crontab

from backend.config.settings import settings


# ── Create the Celery app ──────────────────────────────────────────────────────
celery_app = Celery(
    "meterflow",
    broker=settings.REDIS_URL,          # Redis as the message broker
    backend=settings.REDIS_URL,         # Redis also stores task results
    include=[                           # Auto-discover task modules
        "backend.tasks.log_tasks",
        "backend.tasks.billing_tasks",
        "backend.tasks.metric_tasks",
    ],
)

# ── Celery Configuration ───────────────────────────────────────────────────────
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Performance
    worker_prefetch_multiplier=4,       # Each worker grabs 4 tasks at once
    task_acks_late=True,                # Acknowledge task AFTER completion (safer)
    worker_max_tasks_per_child=1000,    # Restart worker after 1000 tasks (memory leak prevention)

    # Retry policy
    task_max_retries=3,
    task_default_retry_delay=60,        # Wait 60 seconds before retrying

    # Result expiry (keep results for 1 hour then delete from Redis)
    result_expires=3600,

    broker_connection_retry_on_startup=True,

    # ── Scheduled Tasks (Cron Jobs) ───────────────────────────────────────────
    # These run automatically at the specified time.
    beat_schedule={
        # Run billing aggregation every day at midnight UTC
        "daily-billing-aggregation": {
            "task": "backend.tasks.billing_tasks.aggregate_daily_usage",
            "schedule": crontab(hour=0, minute=5),  # 12:05 AM UTC daily
        },
        # Aggregate hourly metrics for dashboards
        "hourly-metrics-aggregation": {
            "task": "backend.tasks.metric_tasks.aggregate_hourly_metrics",
            "schedule": crontab(minute=2),          # 2 minutes past every hour
        },
        # Monthly invoice generation (1st of each month at 1 AM)
        "monthly-invoice-generation": {
            "task": "backend.tasks.billing_tasks.generate_monthly_invoices",
            "schedule": crontab(hour=1, minute=0, day_of_month=1),
        },
    },
)
