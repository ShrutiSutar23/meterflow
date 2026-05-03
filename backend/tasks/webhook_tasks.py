# backend/tasks/webhook_tasks.py
"""
Webhook Delivery Tasks (Day 9)
================================
These Celery tasks handle:
  1. Delivering outbound webhooks to user endpoints (with retries)
  2. Processing inbound Stripe events asynchronously
  3. Sending billing alert webhooks when usage thresholds are crossed

OUTBOUND WEBHOOK DELIVERY FLOW:
  1. Billing event happens (e.g., 80% limit reached)
  2. We call trigger_billing_webhook("billing.limit_warning", user_id, data)
  3. This queues deliver_webhook.delay(...)
  4. Celery worker POSTs to the user's registered URL
  5. If the POST fails → retry up to 5 times with exponential backoff
  6. If still failing → mark webhook as failing, notify user

WEBHOOK SECURITY (HMAC-SHA256 signing):
  We sign every outbound webhook payload with the user's secret:
    signature = HMAC-SHA256(secret, f"{timestamp}.{payload_json}")
    Header: X-MeterFlow-Signature: t=<timestamp>,v1=<signature>

  This is EXACTLY how Stripe signs their webhooks.
  Users can verify: received webhook is genuinely from MeterFlow.

Real-world: GitHub, Stripe, Twilio, PagerDuty all follow this
same signing pattern. It's the industry standard.
"""

import json
import hmac
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.config.celery_app import celery_app


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# OUTBOUND WEBHOOK DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

def _sign_webhook_payload(payload_json: str, secret: str, timestamp: str) -> str:
    """
    Create HMAC-SHA256 signature for outbound webhooks.

    Format (same as Stripe):
      signed_payload = f"{timestamp}.{payload_json}"
      signature = HMAC-SHA256(secret_key, signed_payload)

    Users verify this on their end:
      expected = HMAC-SHA256(their_secret, f"{timestamp}.{body}")
      is_valid = hmac.compare_digest(expected, received_signature)
    """
    signed_payload = f"{timestamp}.{payload_json}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


@celery_app.task(
    name="tasks.webhook_tasks.deliver_webhook",
    bind=True,
    max_retries=5,
    # Exponential backoff: 30s, 60s, 120s, 240s, 480s
    default_retry_delay=30,
)
def deliver_webhook(
    self,
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
    webhook_url: str,
    signing_secret: str = None,
) -> dict:
    """
    Deliver one outbound webhook to a user's endpoint.

    Retries up to 5 times with exponential backoff on failure.
    Each retry doubles the wait time (30s → 60s → 120s → 240s → 480s).

    After all retries fail:
    - Increments failure_count in Redis
    - After 10 consecutive failures → disables the webhook
    - Notifies the user via email (TODO Day 9 follow-up)

    Args:
        user_id:        Owner of the webhook registration
        event_type:     e.g., "billing.limit_warning"
        payload:        Event data to send
        webhook_url:    User's registered endpoint URL
        signing_secret: HMAC secret for signature header
    """
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    payload_json = json.dumps(payload, default=str)

    # ── Build headers ─────────────────────────────────────────────────────────
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MeterFlow-Webhook/1.0",
        "X-MeterFlow-Event": event_type,
        "X-MeterFlow-Delivery": self.request.id or "manual",
        "X-MeterFlow-Timestamp": timestamp,
    }

    # Add HMAC signature if secret is configured
    if signing_secret:
        sig = _sign_webhook_payload(payload_json, signing_secret, timestamp)
        headers["X-MeterFlow-Signature"] = f"t={timestamp},v1={sig}"

    # ── Send the HTTP POST ────────────────────────────────────────────────────
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                webhook_url,
                content=payload_json,
                headers=headers,
            )

            # Consider 2xx as success
            if response.status_code >= 200 and response.status_code < 300:
                _run_async(_record_delivery_success(user_id))
                return {
                    "status": "delivered",
                    "url": webhook_url,
                    "response_code": response.status_code,
                    "attempt": self.request.retries + 1,
                }

            # 4xx = user's server rejected it (don't retry)
            if 400 <= response.status_code < 500:
                return {
                    "status": "rejected",
                    "url": webhook_url,
                    "response_code": response.status_code,
                    "reason": f"Endpoint returned {response.status_code}",
                }

            # 5xx = user's server error → retry
            raise Exception(f"Server error: {response.status_code}")

    except httpx.TimeoutException:
        # Endpoint timed out → retry
        _run_async(_record_delivery_failure(user_id))
        raise self.retry(
            exc=Exception("Webhook delivery timed out"),
            countdown=30 * (2 ** self.request.retries),  # Exponential backoff
        )
    except Exception as exc:
        _run_async(_record_delivery_failure(user_id))
        if self.request.retries < self.max_retries:
            raise self.retry(
                exc=exc,
                countdown=30 * (2 ** self.request.retries),
            )
        # All retries exhausted
        return {
            "status": "failed",
            "url": webhook_url,
            "error": str(exc),
            "attempts": self.max_retries + 1,
        }


async def _record_delivery_success(user_id: str) -> None:
    """Reset failure counter on successful delivery."""
    from backend.config.database import redis_client
    import json
    if not redis_client:
        return
    key = f"webhooks:{user_id}"
    raw = await redis_client.get(key)
    if raw:
        data = json.loads(raw)
        data["failure_count"] = 0
        data["last_delivery"] = datetime.now(timezone.utc).isoformat()
        await redis_client.set(key, json.dumps(data))


async def _record_delivery_failure(user_id: str) -> None:
    """Increment failure counter. Disable webhook after 10 consecutive failures."""
    from backend.config.database import redis_client
    import json
    if not redis_client:
        return
    key = f"webhooks:{user_id}"
    raw = await redis_client.get(key)
    if raw:
        data = json.loads(raw)
        data["failure_count"] = data.get("failure_count", 0) + 1
        if data["failure_count"] >= 10:
            data["is_active"] = False   # Auto-disable failing webhooks
        await redis_client.set(key, json.dumps(data))


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING ALERT TRIGGERS
# These are called from billing_tasks.py when thresholds are crossed
# ═══════════════════════════════════════════════════════════════════════════════

@celery_app.task(name="tasks.webhook_tasks.trigger_billing_webhook")
def trigger_billing_webhook(
    user_id: str,
    event_type: str,
    event_data: dict[str, Any],
) -> dict:
    """
    Look up the user's registered webhook and deliver the billing event.

    Called from:
    - billing_tasks.check_usage_limits → "billing.limit_warning"
    - billing_tasks.generate_monthly_invoices → "billing.invoice_created"
    - webhook_service._handle_payment_succeeded → "billing.payment_succeeded"
    - webhook_service._handle_payment_failed → "billing.payment_failed"
    """
    return _run_async(_trigger_async(user_id, event_type, event_data))


async def _trigger_async(user_id: str, event_type: str, event_data: dict) -> dict:
    from backend.config.database import redis_client
    import json

    if not redis_client:
        return {"status": "skipped", "reason": "Redis not available"}

    key = f"webhooks:{user_id}"
    raw = await redis_client.get(key)
    if not raw:
        return {"status": "skipped", "reason": "No webhook registered"}

    webhook_cfg = json.loads(raw)

    # Check if this event type is subscribed to
    if event_type not in webhook_cfg.get("events", []):
        return {"status": "skipped", "reason": f"Event {event_type} not subscribed"}

    # Check if webhook is still active
    if not webhook_cfg.get("is_active", True):
        return {"status": "skipped", "reason": "Webhook disabled (too many failures)"}

    # Build the full event payload (standard structure like Stripe)
    full_payload = {
        "id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{user_id[:8]}",
        "type": event_type,
        "created": int(datetime.now(timezone.utc).timestamp()),
        "data": event_data,
        "api_version": "2024-01",
        "livemode": True,
    }

    # Queue delivery
    deliver_webhook.delay(
        user_id=user_id,
        event_type=event_type,
        payload=full_payload,
        webhook_url=webhook_cfg["url"],
        signing_secret=webhook_cfg.get("secret") or None,
    )

    return {"status": "queued", "event": event_type, "url": webhook_cfg["url"]}


# ═══════════════════════════════════════════════════════════════════════════════
# INBOUND STRIPE EVENT PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

@celery_app.task(
    name="tasks.webhook_tasks.process_stripe_event",
    bind=True,
    max_retries=3,
)
def process_stripe_event(
    self,
    event_id: str,
    event_type: str,
    event_data: dict,
) -> dict:
    """
    Process a verified Stripe webhook event asynchronously.

    This is queued by the webhook_routes.py endpoint, which returns
    200 to Stripe immediately. Actual processing happens here.

    Idempotency: Check if this event_id was already processed.
    Stripe may send the same event more than once.
    """
    return _run_async(_process_stripe_async(event_id, event_type, event_data))


async def _process_stripe_async(event_id: str, event_type: str, event_data: dict) -> dict:
    from backend.config.database import AsyncSessionLocal, redis_client
    import stripe

    # ── Idempotency check ─────────────────────────────────────────────────────
    # Redis key: "stripe_event:<event_id>" → expires in 24 hours
    if redis_client:
        processed_key = f"stripe_event:{event_id}"
        already_processed = await redis_client.get(processed_key)
        if already_processed:
            return {"status": "already_processed", "event_id": event_id}
        # Mark as processed (24 hour TTL)
        await redis_client.setex(processed_key, 86400, "1")

    # ── Process the event ────────────────────────────────────────────────────
    # Reconstruct a stripe.Event-like object from the stored data
    event_obj = stripe.util.convert_to_stripe_object(event_data)

    async with AsyncSessionLocal() as db:
        from backend.services.webhook_service import handle_stripe_event
        result = await handle_stripe_event(event_obj, db)
        await db.commit()

    return {"status": "processed", "event_id": event_id, "result": result}
