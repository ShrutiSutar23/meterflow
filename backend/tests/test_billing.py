# backend/tests/test_billing.py
"""
Test Suite — Billing (Day 11)
================================
Tests the billing calculation engine and API endpoints.
Billing math bugs = wrong charges = very angry customers.
This is why billing tests matter more than almost anything else.
"""

import pytest
from backend.services.billing_service import calculate_bill


# ═══════════════════════════════════════════════════════════════════════════════
# PURE FUNCTION TESTS (no DB needed — fast)
# ═══════════════════════════════════════════════════════════════════════════════

def test_free_plan_within_limit():
    """Free plan with 5,000 requests (under 10k limit) costs $0."""
    bill = calculate_bill("free", 5_000, "2024-01")
    assert bill["total_cost_usd"] == 0.0
    assert bill["overage_cost_usd"] == 0.0
    assert bill["billable_requests"] == 0


def test_free_plan_at_exact_limit():
    """Free plan at exactly 10,000 requests costs exactly $0."""
    bill = calculate_bill("free", 10_000, "2024-01")
    assert bill["total_cost_usd"] == 0.0
    assert bill["billable_requests"] == 0


def test_free_plan_overage():
    """Free plan with 11,000 requests: 1,000 overage at $0.50/1k = $0.50."""
    bill = calculate_bill("free", 11_000, "2024-01")
    assert bill["billable_requests"] == 1_000
    assert bill["overage_cost_usd"] == 0.50
    assert bill["total_cost_usd"] == 0.50


def test_starter_plan_base_cost():
    """Starter plan always has $29 base cost regardless of usage."""
    bill = calculate_bill("starter", 0, "2024-01")
    assert bill["base_cost_usd"] == 29.00
    assert bill["total_cost_usd"] == 29.00


def test_starter_plan_within_limit():
    """Starter plan with 40,000 requests (under 50k): just base $29."""
    bill = calculate_bill("starter", 40_000, "2024-01")
    assert bill["overage_cost_usd"] == 0.0
    assert bill["total_cost_usd"] == 29.00


def test_starter_plan_overage():
    """Starter: 75,000 requests = base $29 + 25k overage at $0.40/1k = $10 = $39."""
    bill = calculate_bill("starter", 75_000, "2024-01")
    assert bill["billable_requests"] == 25_000
    assert bill["overage_cost_usd"] == 10.00
    assert bill["total_cost_usd"] == 39.00


def test_pro_plan_large_overage():
    """Pro: 600,000 requests = base $99 + 100k overage at $0.30/1k = $30 = $129."""
    bill = calculate_bill("pro", 600_000, "2024-01")
    assert bill["overage_cost_usd"] == 30.00
    assert bill["total_cost_usd"] == 129.00


def test_bill_metadata_fields():
    """Bill response contains all required fields."""
    bill = calculate_bill("starter", 60_000, "2024-01")
    required_fields = [
        "plan", "billing_month", "total_requests", "included_requests",
        "billable_requests", "base_cost_usd", "overage_cost_usd",
        "total_cost_usd", "cost_per_1k_overage",
    ]
    for field in required_fields:
        assert field in bill, f"Missing field: {field}"


def test_bill_never_negative():
    """Bill total is never negative (no credits create negative bills)."""
    bill = calculate_bill("free", 0, "2024-01")
    assert bill["total_cost_usd"] >= 0
    assert bill["overage_cost_usd"] >= 0


def test_unknown_plan_defaults_to_free():
    """Unknown plan falls back to free tier pricing."""
    bill = calculate_bill("unknown_plan", 5_000, "2024-01")
    assert bill["total_cost_usd"] == 0.0


def test_rounding_precision():
    """Bill amounts are rounded to 2 decimal places (cents precision)."""
    bill = calculate_bill("free", 10_333, "2024-01")
    cost = bill["overage_cost_usd"]
    # Should be rounded to 2 decimal places
    assert cost == round(cost, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_billing_plans_endpoint_public():
    """Plans endpoint is public — no auth required."""
    import pytest_asyncio
    from httpx import AsyncClient, ASGITransport
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from main_final import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/billing/plans")
        assert response.status_code == 200
        data = response.json()
        assert "plans" in data
        plan_names = [p["name"] for p in data["plans"]]
        assert "free" in plan_names
        assert "starter" in plan_names
        assert "pro" in plan_names


@pytest.mark.asyncio
async def test_billing_simulate_endpoint():
    """Simulate endpoint calculates bill correctly for given inputs."""
    from httpx import AsyncClient, ASGITransport
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from main_final import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/billing/simulate",
            params={"requests": 75000, "plan": "starter"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_cost_usd"] == 39.00
        assert data["plan"] == "starter"
