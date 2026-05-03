# backend/services/webhook_service.py
"""
Webhook Handler Service (Day 9)
=================================
Webhooks = Stripe calling YOUR server when something happens.

Instead of polling Stripe every minute ("did the payment succeed?"),
Stripe POSTs to your endpoint the moment something happens.

Events we handle:
  payment_intent.succeeded       → Mark invoice as paid
  payment_intent.payment_failed  → Retry logic, notify user
  customer.subscription.deleted  → Downgrade to free plan
  invoice.payment_failed         → Suspend account after 3 failures
  setup_intent.succeeded         → Card saved successfully

SECURITY: Every webhook MUST be verified with the signature.
Stripe signs every webhook with your STRIPE_WEBHOOK_SECRET.
Without verification, anyone could POST fake events to your endpoint.

How to get your webhook secret:
  1. Go to Stripe Dashboard → Developers → Webhooks
  2. Add endpoint: https://yourdomain.com/api/v1/webhooks/stripe
  3. Copy the signing secret → set as STRIPE_WEBHOOK_SECRET in .env

For local testing:
  stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe
"""

import stripe
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from backend.config.settings import settings
from backend.models.user_model import User
from backend.models.billing_model import Invoice


def verify_stripe_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """
    Verify the webhook signature and construct the Event object.

    This is CRITICAL for security. Without this check, a malicious
    actor could POST fake "payment succeeded" events to your endpoint
    and get free access.

    Stripe uses HMAC-SHA256 to sign the payload with your secret.
    We verify the signature before processing any event.

    Raises ValueError if signature is invalid.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
        return event
    except ValueError:
        raise ValueError("Invalid webhook payload")
    except stripe.error.SignatureVerificationError:
        raise ValueError("Invalid webhook signature — possible forgery attempt")


async def handle_stripe_event(event: stripe.Event, db: AsyncSession) -> dict:
    """
    Route a verified Stripe event to the appropriate handler.

    This is the main dispatcher — like a switch statement for events.
    Each event type gets its own handler function.

    Returns a processing result for logging.
    """
    event_type = event["type"]
    event_data = event["data"]["object"]

    handlers = {
        "payment_intent.succeeded":         _handle_payment_succeeded,
        "payment_intent.payment_failed":    _handle_payment_failed,
        "setup_intent.succeeded":           _handle_setup_intent_succeeded,
        "customer.deleted":                 _handle_customer_deleted,
        "invoice.payment_succeeded":        _handle_invoice_paid,
        "invoice.payment_failed":           _handle_invoice_payment_failed,
    }

    handler = handlers.get(event_type)
    if handler:
        result = await handler(event_data, db)
        return {"event": event_type, "status": "processed", "result": result}

    # Unknown event type — log it but don't fail (Stripe sends many event types)
    return {"event": event_type, "status": "ignored"}


# ─── Individual Event Handlers ────────────────────────────────────────────────

async def _handle_payment_succeeded(data: dict, db: AsyncSession) -> dict:
    """
    Payment was successful → mark invoice as paid.

    Called when: A PaymentIntent completes successfully.
    Action: Update invoice status to "paid" in our DB.
    """
    payment_intent_id = data["id"]
    billing_month = data.get("metadata", {}).get("billing_month")
    customer_id = data.get("customer")

    if not billing_month or not customer_id:
        return {"skipped": True, "reason": "Missing metadata"}

    # Find the user by Stripe customer ID
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return {"skipped": True, "reason": "User not found"}

    # Mark invoice as paid
    await db.execute(
        update(Invoice)
        .where(
            Invoice.user_id == user.id,
            Invoice.billing_month == billing_month,
        )
        .values(
            status="paid",
            stripe_invoice_id=payment_intent_id,
            paid_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    # Send webhook alert to user (covered in webhook_routes.py)
    return {"user_id": str(user.id), "billing_month": billing_month, "status": "paid"}


async def _handle_payment_failed(data: dict, db: AsyncSession) -> dict:
    """
    Payment failed → update invoice, notify user, potentially suspend.

    Stripe retry behavior (configurable in Dashboard):
    - Day 1: First attempt
    - Day 3: Second attempt
    - Day 5: Third attempt
    - Day 7: Final attempt → subscription canceled

    After 3 failures, we downgrade the user to free plan.
    """
    customer_id = data.get("customer")
    billing_month = data.get("metadata", {}).get("billing_month")
    failure_message = data.get("last_payment_error", {}).get("message", "Unknown error")
    decline_code = data.get("last_payment_error", {}).get("decline_code", "")

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return {"skipped": True}

    # Mark invoice as failed
    if billing_month:
        await db.execute(
            update(Invoice)
            .where(Invoice.user_id == user.id, Invoice.billing_month == billing_month)
            .values(status="failed")
        )

    # TODO: Send payment failure email via SendGrid
    # await send_payment_failed_email(user.email, failure_message)

    await db.commit()
    return {
        "user_id": str(user.id),
        "decline_code": decline_code,
        "message": failure_message,
    }


async def _handle_setup_intent_succeeded(data: dict, db: AsyncSession) -> dict:
    """
    Card saved successfully → update user's payment method status.
    """
    customer_id = data.get("customer")
    payment_method_id = data.get("payment_method")

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return {"skipped": True}

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(has_payment_method=True)
    )
    await db.commit()
    return {"user_id": str(user.id), "payment_method": payment_method_id}


async def _handle_customer_deleted(data: dict, db: AsyncSession) -> dict:
    """Stripe customer was deleted → clear stripe_customer_id."""
    customer_id = data.get("id")
    await db.execute(
        update(User)
        .where(User.stripe_customer_id == customer_id)
        .values(stripe_customer_id=None, has_payment_method=False)
    )
    await db.commit()
    return {"customer_id": customer_id}


async def _handle_invoice_paid(data: dict, db: AsyncSession) -> dict:
    """Stripe Invoice paid → mark our Invoice record as paid."""
    stripe_invoice_id = data.get("id")
    customer_id = data.get("customer")
    await db.execute(
        update(Invoice)
        .where(Invoice.stripe_invoice_id == stripe_invoice_id)
        .values(status="paid", paid_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"stripe_invoice_id": stripe_invoice_id}


async def _handle_invoice_payment_failed(data: dict, db: AsyncSession) -> dict:
    """Stripe Invoice payment failed repeatedly → downgrade user."""
    customer_id = data.get("customer")
    attempt_count = data.get("attempt_count", 1)

    # After 3 failed attempts, downgrade to free
    if attempt_count >= 3:
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(plan="free", monthly_request_limit=10_000)
            )
            await db.commit()
            # TODO: Send account suspension email

    return {"customer_id": customer_id, "attempt_count": attempt_count}
