# backend/services/stripe_service.py
"""
Stripe Payment Integration (Day 8)
=====================================
Stripe is the world's most popular payment processor.
MeterFlow uses it for:
  1. Saving payment methods (credit cards) — via SetupIntent
  2. Charging users at month-end — via PaymentIntent
  3. Creating customers in Stripe's system
  4. Handling payment failures and retries

HOW STRIPE WORKS (simple explanation):
  ┌─────────────────────────────────────────────────────┐
  │  User enters card on frontend                       │
  │         ↓                                           │
  │  Stripe.js tokenizes it (card never hits our server)│
  │         ↓                                           │
  │  Frontend sends "payment_method_id" to our backend  │
  │         ↓                                           │
  │  We attach it to their Stripe Customer object       │
  │         ↓                                           │
  │  At month end: we call stripe.charge(customer_id)   │
  └─────────────────────────────────────────────────────┘

CRITICAL SECURITY: We never handle raw card numbers.
Stripe.js captures them directly from the browser and
returns a token/PaymentMethod ID. This is called
"client-side tokenization" — the standard for PCI compliance.

Real-world: Stripe powers Shopify, Lyft, Instacart, DoorDash.
"""

import stripe
from typing import Optional
from datetime import datetime, timezone

from backend.config.settings import settings

# Initialize Stripe with your secret key
stripe.api_key = settings.STRIPE_SECRET_KEY


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

async def create_stripe_customer(
    email: str,
    name: str,
    user_id: str,
) -> str:
    """
    Create a Customer object in Stripe.

    Every user needs a Stripe Customer to:
    - Save payment methods
    - Charge later
    - View invoice history

    Returns the Stripe Customer ID (e.g., "cus_abc123...")
    We store this in our users table for future charges.

    Real-world: You create the customer at signup and store
    the ID. Stripe keeps all payment data on their servers —
    you just keep the reference ID.
    """
    try:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={
                "meterflow_user_id": user_id,   # Link back to our DB
            },
        )
        return customer.id
    except stripe.error.StripeError as e:
        raise ValueError(f"Stripe customer creation failed: {e.user_message}")


async def get_stripe_customer(customer_id: str) -> dict:
    """Retrieve a Stripe customer's details."""
    try:
        customer = stripe.Customer.retrieve(customer_id)
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
            "default_payment_method": customer.invoice_settings.default_payment_method,
        }
    except stripe.error.StripeError as e:
        raise ValueError(f"Could not retrieve customer: {e.user_message}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT METHODS
# ═══════════════════════════════════════════════════════════════════════════════

async def create_setup_intent(customer_id: str) -> dict:
    """
    Create a SetupIntent — used to save a card WITHOUT charging it.

    Flow:
    1. Backend calls this → gets client_secret
    2. Backend sends client_secret to frontend
    3. Frontend uses Stripe.js + client_secret to show card form
    4. User enters card — Stripe tokenizes it
    5. Card is saved to the customer for future charges

    The card number NEVER touches our server.
    Only Stripe handles it (PCI DSS compliance).

    Returns client_secret to send to frontend.
    """
    try:
        setup_intent = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=["card"],
            usage="off_session",    # Card will be charged without user being present
            metadata={"purpose": "meterflow_billing"},
        )
        return {
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
        }
    except stripe.error.StripeError as e:
        raise ValueError(f"SetupIntent failed: {e.user_message}")


async def list_payment_methods(customer_id: str) -> list[dict]:
    """
    List all saved payment methods for a customer.
    Used to display saved cards in the billing settings UI.
    """
    try:
        payment_methods = stripe.PaymentMethod.list(
            customer=customer_id,
            type="card",
        )
        return [
            {
                "id": pm.id,
                "brand": pm.card.brand,           # "visa", "mastercard", "amex"
                "last4": pm.card.last4,            # "4242"
                "exp_month": pm.card.exp_month,
                "exp_year": pm.card.exp_year,
                "is_default": False,               # We'll set this from customer object
            }
            for pm in payment_methods.data
        ]
    except stripe.error.StripeError as e:
        raise ValueError(f"Could not list payment methods: {e.user_message}")


async def set_default_payment_method(
    customer_id: str, payment_method_id: str
) -> bool:
    """Set the default payment method for auto-charging."""
    try:
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )
        return True
    except stripe.error.StripeError:
        return False


async def delete_payment_method(payment_method_id: str) -> bool:
    """Detach (remove) a saved payment method."""
    try:
        stripe.PaymentMethod.detach(payment_method_id)
        return True
    except stripe.error.StripeError:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# CHARGING USERS
# ═══════════════════════════════════════════════════════════════════════════════

async def charge_customer(
    customer_id: str,
    amount_usd: float,
    description: str,
    metadata: dict = None,
) -> dict:
    """
    Charge a customer's default payment method.
    Called by the monthly billing cron job.

    Stripe amounts are in CENTS (integer), not dollars.
    $29.50 → 2950 cents

    Returns:
        {
          "payment_intent_id": "pi_abc123",
          "status": "succeeded" | "requires_action" | "failed",
          "amount_charged_usd": 29.50
        }

    Real-world failure scenarios:
    - Card declined → status = "failed"
    - 3D Secure required → status = "requires_action"
    - Insufficient funds → Stripe returns decline_code
    """
    if amount_usd < 0.50:
        # Stripe minimum charge is $0.50
        return {"status": "skipped", "reason": "Amount below Stripe minimum ($0.50)"}

    amount_cents = int(round(amount_usd * 100))  # Convert to cents

    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            customer=customer_id,
            description=description,
            confirm=True,                       # Charge immediately
            off_session=True,                   # User is not present
            payment_method_types=["card"],
            metadata=metadata or {},
        )

        return {
            "payment_intent_id": payment_intent.id,
            "status": payment_intent.status,   # "succeeded", "requires_action", "canceled"
            "amount_charged_usd": amount_usd,
            "charged_at": datetime.now(timezone.utc).isoformat(),
        }

    except stripe.error.CardError as e:
        # The card was declined
        err = e.error
        return {
            "payment_intent_id": None,
            "status": "failed",
            "decline_code": err.decline_code,   # e.g., "insufficient_funds", "do_not_honor"
            "message": err.message,
        }
    except stripe.error.StripeError as e:
        raise ValueError(f"Payment failed: {e.user_message}")


async def create_stripe_invoice(
    customer_id: str,
    line_items: list[dict],
    billing_month: str,
) -> dict:
    """
    Create a Stripe Invoice (more formal than PaymentIntent).
    Stripe handles the PDF, email delivery, and payment link.

    This is the enterprise-grade approach — Stripe sends the
    invoice email automatically, handles dunning (retry on failure),
    and generates a PDF invoice.

    line_items format:
    [
      {"description": "Base plan (Starter)", "amount_cents": 2900},
      {"description": "Overage: 25,000 requests", "amount_cents": 1000},
    ]
    """
    try:
        # Create invoice items first
        for item in line_items:
            if item["amount_cents"] > 0:
                stripe.InvoiceItem.create(
                    customer=customer_id,
                    amount=item["amount_cents"],
                    currency="usd",
                    description=item["description"],
                )

        # Create and finalize the invoice
        invoice = stripe.Invoice.create(
            customer=customer_id,
            auto_advance=True,      # Automatically finalize and send
            collection_method="charge_automatically",
            metadata={"billing_month": billing_month},
        )

        # Finalize it (triggers charge + email)
        invoice = stripe.Invoice.finalize_invoice(invoice.id)

        return {
            "stripe_invoice_id": invoice.id,
            "status": invoice.status,           # "draft", "open", "paid", "void"
            "amount_due_usd": invoice.amount_due / 100,
            "invoice_pdf_url": invoice.invoice_pdf,
            "hosted_invoice_url": invoice.hosted_invoice_url,   # Link user can pay on
        }

    except stripe.error.StripeError as e:
        raise ValueError(f"Invoice creation failed: {e.user_message}")


# ═══════════════════════════════════════════════════════════════════════════════
# REFUNDS
# ═══════════════════════════════════════════════════════════════════════════════

async def issue_refund(
    payment_intent_id: str,
    amount_usd: Optional[float] = None,  # None = full refund
    reason: str = "requested_by_customer",
) -> dict:
    """
    Issue a full or partial refund.

    reason options: "duplicate", "fraudulent", "requested_by_customer"

    Real-world: Important for customer service workflows.
    Stripe handles the bank transfer back to the customer's card.
    """
    try:
        refund_params = {
            "payment_intent": payment_intent_id,
            "reason": reason,
        }
        if amount_usd is not None:
            refund_params["amount"] = int(round(amount_usd * 100))

        refund = stripe.Refund.create(**refund_params)
        return {
            "refund_id": refund.id,
            "status": refund.status,
            "amount_refunded_usd": refund.amount / 100,
        }
    except stripe.error.StripeError as e:
        raise ValueError(f"Refund failed: {e.user_message}")
