# backend/routes/billing_routes.py
"""
Billing Routes
===============
  GET  /api/v1/billing/summary          → Current month usage + cost estimate
  GET  /api/v1/billing/invoices         → Invoice history
  GET  /api/v1/billing/invoices/{month} → Single month invoice detail
  GET  /api/v1/billing/plans            → Available pricing plans
  POST /api/v1/billing/simulate         → Simulate a bill for N requests (useful UX)

Test with Postman:
  GET http://localhost:8000/api/v1/billing/summary
  Headers: Authorization: Bearer <token>
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.config.database import get_db
from backend.services.billing_service import (
    get_current_month_usage, get_invoice_history,
    calculate_bill, PLAN_PRICING,
)
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()


@router.get("/summary")
async def get_billing_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Current month billing summary.
    Shows exactly what the user will owe at month end.

    Real-world: This is like AWS Cost Explorer's "current month forecast".
    """
    summary = await get_current_month_usage(db, str(current_user.id))
    return {
        "user": {
            "plan": current_user.plan,
            "monthly_limit": current_user.monthly_request_limit,
        },
        "billing": summary,
    }


@router.get("/invoices")
async def list_invoices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All past invoices for the current user."""
    invoices = await get_invoice_history(db, str(current_user.id))
    return {"invoices": invoices}


@router.get("/plans")
async def get_pricing_plans():
    """
    Return all available plans and their pricing.
    Used to power the pricing page on the frontend.
    No auth required — public endpoint.
    """
    plans = []
    for plan_name, pricing in PLAN_PRICING.items():
        plans.append({
            "name": plan_name,
            "monthly_base_usd": pricing["monthly_base_usd"],
            "included_requests": pricing["free_requests"],
            "overage_per_1000_usd": pricing["overage_per_1k"],
            "features": _get_plan_features(plan_name),
        })
    return {"plans": plans}


@router.post("/simulate")
async def simulate_bill(
    requests: int,
    plan: str = "free",
):
    """
    Calculate what a bill would be for N requests on a given plan.
    Great UX feature — lets users explore pricing before upgrading.

    Example:
      POST /api/v1/billing/simulate?requests=75000&plan=starter
      → Shows: base $29 + $10 overage = $39 total
    """
    from datetime import datetime, timezone
    billing_month = datetime.now(timezone.utc).strftime("%Y-%m")
    bill = calculate_bill(plan, requests, billing_month)
    return bill


def _get_plan_features(plan: str) -> list[str]:
    features = {
        "free":       ["10K req/month", "2 API keys", "7-day log retention", "Community support"],
        "starter":    ["50K req/month", "5 API keys", "30-day log retention", "Email support", "Webhooks"],
        "pro":        ["500K req/month", "20 API keys", "90-day log retention", "Priority support", "Analytics"],
        "enterprise": ["10M req/month", "Unlimited keys", "1-year log retention", "SLA guarantee", "Custom limits"],
    }
    return features.get(plan, [])
