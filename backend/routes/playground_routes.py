# backend/routes/playground_routes.py
"""
API Playground (Day 11)
=========================
A sandbox endpoint where users can test their API keys live,
directly from the dashboard — no Postman needed.

What it does:
  - Accepts a test request (method, endpoint, headers, body)
  - Validates the API key provided
  - Executes the request against MeterFlow's own API
  - Returns the response + timing + headers
  - Logs it as a real usage event (billable)

Real-world: Stripe has a "test mode" playground.
  Twilio has a "Try it" console.
  Postman has a built-in runner.
  This is MeterFlow's version — embedded in the dashboard.

Why build this?
  - Users can verify their API key works instantly
  - No switching between tools (dashboard → Postman → back)
  - Great for demos and onboarding new developers
  - Reduces support tickets ("my key doesn't work")
"""

import time
import httpx
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.database import get_db
from backend.services.apikey_service import get_key_by_hash
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()

# Endpoints allowed in the playground (whitelist for security)
ALLOWED_ENDPOINTS = {
    "/api/v1/auth/me":              "GET",
    "/api/v1/keys/":                "GET",
    "/api/v1/billing/summary":      "GET",
    "/api/v1/billing/plans":        "GET",
    "/api/v1/analytics/dashboard":  "GET",
    "/api/v1/analytics/latency":    "GET",
    "/api/v1/analytics/errors":     "GET",
    "/api/v1/logs":                 "GET",
    "/api/v1/billing/simulate":     "POST",
}


class PlaygroundRequest(BaseModel):
    """A test request to execute against the MeterFlow API."""
    api_key: str                                    # The API key to test
    endpoint: str                                   # e.g. "/api/v1/billing/summary"
    method: str = "GET"                             # HTTP method
    query_params: Optional[dict[str, Any]] = None  # e.g. {"days": 7}
    body: Optional[dict[str, Any]] = None          # Request body for POST

    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "mf_live_abc123...",
                "endpoint": "/api/v1/billing/summary",
                "method": "GET",
            }
        }


class PlaygroundResponse(BaseModel):
    """Full result of the test request."""
    success: bool
    status_code: int
    response_body: Any
    response_headers: dict
    response_time_ms: float
    endpoint_called: str
    api_key_prefix: str
    request_id: str
    error: Optional[str] = None


@router.post("/run", response_model=PlaygroundResponse)
async def run_playground(
    payload: PlaygroundRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a test API call using the provided key.

    Security rules:
    1. The API key must belong to the logged-in user (can't test others' keys)
    2. Only whitelisted endpoints are allowed (no arbitrary URLs)
    3. The call is made server-side (we control the target)
    4. It IS a real call — it counts toward usage and rate limits

    Test with Postman:
      POST /api/v1/playground/run
      Headers: Authorization: Bearer <jwt_token>
      Body: {
        "api_key": "mf_live_your_key_here",
        "endpoint": "/api/v1/billing/summary",
        "method": "GET"
      }
    """
    import uuid

    # ── Validate the API key belongs to this user ──────────────────────────
    api_key_record = await get_key_by_hash(db, payload.api_key)

    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")

    if str(api_key_record.user_id) != str(current_user.id):
        # Key doesn't belong to this user — security violation attempt
        raise HTTPException(status_code=403, detail="This API key does not belong to your account.")

    # ── Validate endpoint ──────────────────────────────────────────────────
    endpoint = payload.endpoint.rstrip("/")
    if endpoint not in ALLOWED_ENDPOINTS:
        raise HTTPException(
            status_code=400,
            detail=f"Endpoint not available in playground. Allowed: {list(ALLOWED_ENDPOINTS.keys())}",
        )

    expected_method = ALLOWED_ENDPOINTS[endpoint]
    if payload.method.upper() != expected_method:
        raise HTTPException(
            status_code=400,
            detail=f"Endpoint {endpoint} only supports {expected_method}.",
        )

    # ── Execute the request ────────────────────────────────────────────────
    base_url = "http://localhost:8000"
    full_url = f"{base_url}{endpoint}"
    request_id = str(uuid.uuid4())

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method=payload.method.upper(),
                url=full_url,
                params=payload.query_params,
                json=payload.body,
                headers={
                    "X-API-Key": payload.api_key,
                    "X-Playground-Request-ID": request_id,
                    "Content-Type": "application/json",
                },
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Parse response
        try:
            response_body = response.json()
        except Exception:
            response_body = {"raw": response.text}

        # Filter response headers to useful ones only
        safe_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() in {
                "content-type", "x-request-id", "x-response-time",
                "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
            }
        }

        return PlaygroundResponse(
            success=response.status_code < 400,
            status_code=response.status_code,
            response_body=response_body,
            response_headers=safe_headers,
            response_time_ms=round(elapsed_ms, 2),
            endpoint_called=endpoint,
            api_key_prefix=api_key_record.key_prefix,
            request_id=request_id,
        )

    except httpx.TimeoutException:
        return PlaygroundResponse(
            success=False,
            status_code=504,
            response_body={},
            response_headers={},
            response_time_ms=15000,
            endpoint_called=endpoint,
            api_key_prefix=api_key_record.key_prefix,
            request_id=request_id,
            error="Request timed out after 15 seconds.",
        )
    except Exception as e:
        return PlaygroundResponse(
            success=False,
            status_code=500,
            response_body={},
            response_headers={},
            response_time_ms=0,
            endpoint_called=endpoint,
            api_key_prefix=api_key_record.key_prefix,
            request_id=request_id,
            error=str(e),
        )


@router.get("/endpoints")
async def list_playground_endpoints(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the list of endpoints available in the playground.
    Used by the frontend to populate the endpoint dropdown.
    """
    return {
        "endpoints": [
            {
                "path": path,
                "method": method,
                "description": _endpoint_descriptions.get(path, ""),
            }
            for path, method in ALLOWED_ENDPOINTS.items()
        ]
    }


_endpoint_descriptions = {
    "/api/v1/auth/me":             "Get your user profile",
    "/api/v1/keys/":               "List your API keys",
    "/api/v1/billing/summary":     "Current month usage and estimated bill",
    "/api/v1/billing/plans":       "View all pricing plans",
    "/api/v1/analytics/dashboard": "Full analytics dashboard data",
    "/api/v1/analytics/latency":   "p50/p95/p99 latency stats",
    "/api/v1/analytics/errors":    "Error rate breakdown",
    "/api/v1/logs":                "View recent API request logs",
    "/api/v1/billing/simulate":    "Simulate a bill for N requests",
}
