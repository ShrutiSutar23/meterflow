# backend/services/billing_service.py
"""
Billing Service (Day 4)
========================
The billing engine is the financial brain of MeterFlow.
It calculates what each user owes based on their API usage.

Pricing Model: Usage-Based (like AWS, Stripe, Twilio)
  - Free tier:    0–10,000 requests/month = $0.00
  - Paid:         Every 1,000 requests above free tier = $0.50
  - Examples:
      50,000 requests → (50,000 - 10,000) / 1,000 × $0.50 = $20.00
     100,000 requests → (100,000 - 10,000) / 1,000 × $0.50 = $45.00
     500,000 requests → (500,000 - 10,000) / 1,000 × $0.50 = $245.00

Plan tiers (monthly request limits):
  free:       10,000  req/month  → $0.00 base  + overage
  starter:    50,000  req/month  → $29.00/month + overage
  pro:       500,000  req/month  → $99.00/month + overage
  enterprise: 10M     req/month  → Custom pricing

Real-world: This is very similar to how:
  - AWS Lambda charges per invocation
  - Twilio charges per SMS/call
  - Stripe charges per API call
  - Sendgrid charges per email sent
"""

from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update

from backend.models.billing_model import UsageRecord, Invoice
from backend.models.user_model import User
from backend.config.settings import settings


# ── Pricing Constants ─────────────────────────────────────────────────────────
PLAN_PRICING = {
    "free":       {"monthly_base_usd": 0.00,   "free_requests": 10_000,   "overage_per_1k": 0.50},
    "starter":    {"monthly_base_usd": 29.00,  "free_requests": 50_000,   "overage_per_1k": 0.40},
    "pro":        {"monthly_base_usd": 99.00,  "free_requests": 500_000,  "overage_per_1k": 0.30},
    "enterprise": {"monthly_base_usd": 499.00, "free_requests": 5_000_000, "overage_per_1k": 0.20},
}

COST_PER_REQUEST = settings.COST_PER_1000_REQUESTS / 1000  # Cost per single request


def calculate_bill(
    plan: str,
    total_requests: int,
    billing_month: str,
) -> dict:
    """
    Calculate the bill for a user based on their plan and usage.

    Returns a detailed breakdown (important for invoice transparency):
    {
      "plan": "starter",
      "billing_month": "2024-01",
      "total_requests": 75000,
      "included_requests": 50000,
      "billable_requests": 25000,
      "base_cost_usd": 29.00,
      "overage_cost_usd": 10.00,   ← 25 × $0.40
      "total_cost_usd": 39.00,
      "cost_per_1k_overage": 0.40,
    }
    """
    pricing = PLAN_PRICING.get(plan, PLAN_PRICING["free"])

    included = pricing["free_requests"]
    base_cost = pricing["monthly_base_usd"]
    per_1k = pricing["overage_per_1k"]

    # How many requests are beyond the plan's included limit?
    overage_requests = max(0, total_requests - included)

    # Calculate overage cost (rounded to 2 decimal places)
    overage_cost = float(
        Decimal(str(overage_requests / 1000 * per_1k))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    total_cost = round(base_cost + overage_cost, 2)

    return {
        "plan": plan,
        "billing_month": billing_month,
        "total_requests": total_requests,
        "included_requests": included,
        "billable_requests": overage_requests,
        "base_cost_usd": base_cost,
        "overage_cost_usd": overage_cost,
        "total_cost_usd": total_cost,
        "cost_per_1k_overage": per_1k,
    }


async def record_usage(
    db: AsyncSession,
    user_id: str,
    api_key_id: Optional[str],
    endpoint: str,
    method: str,
    status_code: int,
    response_time_ms: float = 0.0,
) -> UsageRecord:
    """
    Record a single API usage event in PostgreSQL.
    Called by the request logger for billable requests.

    Note: For high-traffic systems (millions of req/day), you'd
    batch these writes using Celery + bulk insert instead of
    one INSERT per request. We'll optimize this in Day 6.
    """
    billing_month = datetime.now(timezone.utc).strftime("%Y-%m")
    cost = COST_PER_REQUEST if status_code < 500 else 0.0  # Don't charge for server errors

    record = UsageRecord(
        user_id=user_id,
        api_key_id=api_key_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        response_time_ms=response_time_ms,
        units_consumed=1,
        cost_usd=cost,
        billing_month=billing_month,
    )
    db.add(record)
    await db.flush()
    return record


async def get_current_month_usage(db: AsyncSession, user_id: str) -> dict:
    """
    Get the current month's usage summary from PostgreSQL.
    Used for the billing page and overage alerts.
    """
    billing_month = datetime.now(timezone.utc).strftime("%Y-%m")

    result = await db.execute(
        select(
            func.count(UsageRecord.id).label("total_requests"),
            func.sum(UsageRecord.cost_usd).label("total_cost"),
            func.avg(UsageRecord.response_time_ms).label("avg_latency"),
        ).where(
            and_(
                UsageRecord.user_id == user_id,
                UsageRecord.billing_month == billing_month,
            )
        )
    )
    row = result.one()

    # Get user plan info
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        return {}

    total_requests = row.total_requests or 0
    bill = calculate_bill(user.plan, total_requests, billing_month)

    return {
        **bill,
        "avg_latency_ms": round(row.avg_latency or 0.0, 1),
        "requests_remaining": max(0, user.monthly_request_limit - total_requests),
        "usage_pct": round(total_requests / max(user.monthly_request_limit, 1) * 100, 1),
    }


async def generate_invoice(db: AsyncSession, user_id: str, billing_month: str) -> Invoice:
    """
    Generate (or update) the monthly invoice for a user.
    Called by the Celery monthly cron job on the 1st of each month.

    Steps:
    1. Sum all usage records for the month
    2. Calculate the bill
    3. Create/update an Invoice record
    4. Mark all usage records as billed
    5. (Later: trigger Stripe charge)
    """
    # ── Aggregate usage for the month ────────────────────────────────────────
    result = await db.execute(
        select(
            func.count(UsageRecord.id).label("total_requests"),
            func.sum(UsageRecord.cost_usd).label("total_cost"),
        ).where(
            and_(
                UsageRecord.user_id == user_id,
                UsageRecord.billing_month == billing_month,
                UsageRecord.is_billed == False,
            )
        )
    )
    row = result.one()
    total_requests = row.total_requests or 0

    # Get user for plan info
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    # ── Calculate bill ────────────────────────────────────────────────────────
    bill = calculate_bill(user.plan, total_requests, billing_month)

    # ── Create or update invoice ──────────────────────────────────────────────
    existing = await db.execute(
        select(Invoice).where(
            and_(Invoice.user_id == user_id, Invoice.billing_month == billing_month)
        )
    )
    invoice = existing.scalar_one_or_none()

    if invoice:
        invoice.total_requests = total_requests
        invoice.total_cost_usd = bill["total_cost_usd"]
    else:
        invoice = Invoice(
            user_id=user_id,
            billing_month=billing_month,
            total_requests=total_requests,
            total_cost_usd=bill["total_cost_usd"],
            status="pending",
        )
        db.add(invoice)

    # ── Mark usage records as billed ──────────────────────────────────────────
    await db.execute(
        update(UsageRecord)
        .where(
            and_(
                UsageRecord.user_id == user_id,
                UsageRecord.billing_month == billing_month,
                UsageRecord.is_billed == False,
            )
        )
        .values(is_billed=True)
    )

    await db.flush()
    return invoice


async def get_invoice_history(db: AsyncSession, user_id: str) -> list:
    """Retrieve all past invoices for a user."""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.user_id == user_id)
        .order_by(Invoice.billing_month.desc())
    )
    return result.scalars().all()
