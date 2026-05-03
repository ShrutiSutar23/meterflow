# backend/routes/webhook_routes.py
"""
Webhook Routes (Day 9)
========================
Two types of webhooks in MeterFlow:

  Type 1 — INBOUND (Stripe → Us):
    Stripe calls POST /api/v1/webhooks/stripe when a payment event happens.
    We verify the signature, process the event, return 200 immediately.

  Type 2 — OUTBOUND (Us → User's servers):
    When a billing event happens (usage limit, invoice generated),
    we POST to the user's registered webhook URL.
    This lets users automate responses to billing events in their own systems.

INBOUND WEBHOOK RULES (critical for reliability):
  1. ALWAYS return 200 quickly (< 3 seconds)
     Stripe will retry if you return 5xx or timeout.
  2. Process the event ASYNCHRONOUSLY (Celery task)
     Never do heavy DB work in the webhook handler itself.
  3. Store the raw event for replay/debugging
  4. Make handlers IDEMPOTENT
     Stripe may send the same event twice — handle it safely.

Real-world: Stripe says "Your endpoint must return a 200 status
code within 30 seconds or we'll retry up to 3 times over 3 days."
"""

from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import json
import hmac
import hashlib
from datetime import datetime, timezone

from backend.config.database import get_db
from backend.services.webhook_service import verify_stripe_webhook, handle_stripe_event
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# INBOUND: Stripe → MeterFlow
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Stripe sends all payment events here.

    MUST return 200 quickly — we immediately queue processing to Celery.

    To test locally:
      1. Install Stripe CLI: brew install stripe/stripe-cli/stripe
      2. Run: stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe
      3. In another terminal: stripe trigger payment_intent.succeeded
      4. Watch this endpoint receive the event

    Security: Stripe signs every webhook with your STRIPE_WEBHOOK_SECRET.
    We verify this signature before processing ANYTHING.
    """
    # ── Read raw body (needed for signature verification) ─────────────────────
    # IMPORTANT: We must read the RAW bytes — not parsed JSON.
    # The signature is computed over the raw body bytes.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    # ── Verify signature ──────────────────────────────────────────────────────
    try:
        event = verify_stripe_webhook(payload, sig_header)
    except ValueError as e:
        # Log this — could be a security attempt
        print(f"⚠️  Webhook signature verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # ── Store raw event for audit trail ───────────────────────────────────────
    # We queue the ACTUAL processing to Celery (don't block Stripe)
    try:
        from backend.tasks.webhook_tasks import process_stripe_event
        process_stripe_event.delay(
            event_id=event["id"],
            event_type=event["type"],
            event_data=json.loads(payload.decode("utf-8")),
        )
    except Exception as e:
        # Log but don't fail — we already received the event
        print(f"Failed to queue Stripe event {event['id']}: {e}")

    # ── Return 200 immediately ────────────────────────────────────────────────
    # Stripe requires this. If we don't respond quickly, it retries.
    return {"received": True, "event_id": event["id"], "type": event["type"]}


# ═══════════════════════════════════════════════════════════════════════════════
# OUTBOUND: MeterFlow → User's Servers
# User-registered webhooks for billing events
# ═══════════════════════════════════════════════════════════════════════════════

class RegisterWebhookRequest(BaseModel):
    url: HttpUrl
    events: List[str]
    secret: Optional[str] = None    # Users can set a signing secret to verify our calls

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://your-server.com/webhooks/meterflow",
                "events": ["billing.limit_warning", "billing.invoice_created", "billing.payment_failed"],
                "secret": "your_webhook_signing_secret",
            }
        }


@router.post("/register")
async def register_webhook(
    payload: RegisterWebhookRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a URL to receive billing event notifications.

    When we generate an invoice, exceed limits, or a payment fails,
    we POST to this URL so users can automate their own workflows.

    Supported events:
      billing.limit_warning      → Usage reached 80% of monthly limit
      billing.limit_exceeded     → Usage exceeded monthly limit
      billing.invoice_created    → Monthly invoice generated
      billing.payment_succeeded  → Payment successful
      billing.payment_failed     → Payment failed
      apikey.revoked             → An API key was revoked

    Real-world: GitHub webhooks, Stripe webhooks, Twilio webhooks
    all follow this same pattern — register a URL, receive POST calls.
    """
    valid_events = {
        "billing.limit_warning", "billing.limit_exceeded",
        "billing.invoice_created", "billing.payment_succeeded",
        "billing.payment_failed", "apikey.revoked",
    }

    invalid = set(payload.events) - valid_events
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event types: {list(invalid)}. Valid: {list(valid_events)}",
        )

    # Store webhook registration in Redis for fast lookup
    from backend.config.database import redis_client
    import json
    webhook_data = {
        "url": str(payload.url),
        "events": payload.events,
        "secret": payload.secret or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
        "failure_count": 0,
    }
    redis_key = f"webhooks:{current_user.id}"
    if redis_client:
        await redis_client.set(redis_key, json.dumps(webhook_data))

    return {
        "message": "Webhook registered successfully.",
        "url": str(payload.url),
        "events": payload.events,
        "test_tip": f"Send a test: POST /api/v1/webhooks/test",
    }


@router.post("/test")
async def send_test_webhook(
    current_user: User = Depends(get_current_user),
):
    """
    Send a test webhook delivery to the registered URL.
    Lets users verify their webhook endpoint is working.

    Real-world: Stripe, GitHub, and Twilio all have "Send test webhook"
    buttons in their dashboards for exactly this purpose.
    """
    from backend.config.database import redis_client
    import json

    redis_key = f"webhooks:{current_user.id}"
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    webhook_json = await redis_client.get(redis_key)
    if not webhook_json:
        raise HTTPException(
            status_code=404,
            detail="No webhook registered. Call POST /api/v1/webhooks/register first.",
        )

    webhook_data = json.loads(webhook_json)

    # Queue a test delivery via Celery
    from backend.tasks.webhook_tasks import deliver_webhook
    deliver_webhook.delay(
        user_id=str(current_user.id),
        event_type="webhook.test",
        payload={
            "event": "webhook.test",
            "message": "This is a test webhook from MeterFlow",
            "user_id": str(current_user.id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        webhook_url=webhook_data["url"],
        signing_secret=webhook_data.get("secret"),
    )

    return {
        "message": "Test webhook queued for delivery.",
        "destination": webhook_data["url"],
    }


@router.get("/")
async def list_webhooks(
    current_user: User = Depends(get_current_user),
):
    """List registered webhook configurations for current user."""
    from backend.config.database import redis_client
    import json

    if not redis_client:
        return {"webhooks": []}

    redis_key = f"webhooks:{current_user.id}"
    webhook_json = await redis_client.get(redis_key)

    if not webhook_json:
        return {"webhooks": []}

    webhook_data = json.loads(webhook_json)
    # Never return the signing secret
    webhook_data.pop("secret", None)

    return {"webhooks": [webhook_data]}


@router.delete("/")
async def delete_webhook(
    current_user: User = Depends(get_current_user),
):
    """Remove the registered webhook."""
    from backend.config.database import redis_client

    if redis_client:
        await redis_client.delete(f"webhooks:{current_user.id}")

    return {"message": "Webhook removed."}
