# backend/routes/stripe_routes.py
"""
Stripe Payment Routes (Day 8)
================================
Endpoints:
  POST /api/v1/payments/setup-intent        → Create SetupIntent (save card)
  GET  /api/v1/payments/methods             → List saved cards
  POST /api/v1/payments/methods/default     → Set default card
  DELETE /api/v1/payments/methods/{pm_id}   → Remove a card
  POST /api/v1/payments/charge              → Manual charge (admin)
  GET  /api/v1/payments/portal             → Stripe billing portal URL

Flow for saving a card (frontend → backend):
  1. User clicks "Add Card"
  2. Frontend calls POST /setup-intent → gets client_secret
  3. Frontend passes client_secret to Stripe.js card form
  4. User enters card → Stripe tokenizes it
  5. Stripe calls your webhook: setup_intent.succeeded
  6. Card is now attached to the customer, ready for charges

Test with Postman:
  POST http://localhost:8000/api/v1/payments/setup-intent
  Headers: Authorization: Bearer <token>
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from backend.config.database import get_db
from backend.services.stripe_service import (
    create_stripe_customer,
    create_setup_intent,
    list_payment_methods,
    set_default_payment_method,
    delete_payment_method,
    charge_customer,
    issue_refund,
)
from backend.utils.dependencies import get_current_user, require_role
from backend.models.user_model import User, UserRole


router = APIRouter()


# ── Helper: ensure user has a Stripe customer ID ──────────────────────────────
async def ensure_stripe_customer(user: User, db: AsyncSession) -> str:
    """
    Lazily create a Stripe Customer if one doesn't exist.
    This is called "lazy initialization" — we only create
    the Stripe customer when they first try to add a payment method,
    not at signup (keeps Stripe clean).
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    # Create Stripe customer
    customer_id = await create_stripe_customer(
        email=user.email,
        name=user.full_name or user.username,
        user_id=str(user.id),
    )

    # Save it to our DB
    user.stripe_customer_id = customer_id
    await db.flush()

    return customer_id


# ── Setup Intent ──────────────────────────────────────────────────────────────
@router.post("/setup-intent")
async def get_setup_intent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Stripe SetupIntent to save a payment method.

    The returned client_secret is used by Stripe.js on the
    frontend to show a secure card input form.

    NEVER pass the client_secret to anyone other than the user
    who requested it — it grants access to confirm the setup.

    Frontend usage:
        const stripe = await loadStripe(STRIPE_PUBLIC_KEY);
        const elements = stripe.elements({ clientSecret });
        const cardElement = elements.create('card');
        // On form submit:
        stripe.confirmCardSetup(clientSecret, { payment_method: { card: cardElement } })
    """
    customer_id = await ensure_stripe_customer(current_user, db)

    try:
        result = await create_setup_intent(customer_id)
        return {
            "client_secret": result["client_secret"],
            "setup_intent_id": result["setup_intent_id"],
            "stripe_customer_id": customer_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── List Payment Methods ──────────────────────────────────────────────────────
@router.get("/methods")
async def get_payment_methods(
    current_user: User = Depends(get_current_user),
):
    """
    List all saved cards for the current user.

    Response example:
    [
      {
        "id": "pm_abc123",
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2027
      }
    ]

    Note: We never return actual card numbers — only the last 4 digits.
    This is what Stripe exposes and it's all you ever need for display.
    """
    if not current_user.stripe_customer_id:
        return {"payment_methods": [], "has_payment_method": False}

    try:
        methods = await list_payment_methods(current_user.stripe_customer_id)
        return {
            "payment_methods": methods,
            "has_payment_method": len(methods) > 0,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Set Default Payment Method ────────────────────────────────────────────────
class SetDefaultRequest(BaseModel):
    payment_method_id: str


@router.post("/methods/default")
async def set_default_method(
    payload: SetDefaultRequest,
    current_user: User = Depends(get_current_user),
):
    """Set which saved card to use for automatic charges."""
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No payment methods saved.")

    success = await set_default_payment_method(
        current_user.stripe_customer_id,
        payload.payment_method_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set default payment method.")

    return {"message": "Default payment method updated."}


# ── Remove Payment Method ─────────────────────────────────────────────────────
@router.delete("/methods/{payment_method_id}")
async def remove_payment_method(
    payment_method_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Detach (remove) a saved card.
    The user will need to add a new one before next billing cycle.
    """
    success = await delete_payment_method(payment_method_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not remove payment method.")

    # Update our DB to reflect no payment method
    current_user.has_payment_method = False
    await db.flush()

    return {"message": "Payment method removed."}


# ── Manual Charge (Admin only) ────────────────────────────────────────────────
class ManualChargeRequest(BaseModel):
    user_id: str
    amount_usd: float
    description: str


@router.post("/charge")
async def manual_charge(
    payload: ManualChargeRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually charge a user. ADMIN ONLY.

    Used for:
    - Correcting billing errors
    - Custom enterprise invoices
    - Testing payment flows

    Real-world: Stripe's dashboard also has a manual charge button.
    We're just adding it as an API for automation.
    """
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if not user or not user.stripe_customer_id:
        raise HTTPException(status_code=404, detail="User not found or no payment method.")

    try:
        charge_result = await charge_customer(
            customer_id=user.stripe_customer_id,
            amount_usd=payload.amount_usd,
            description=payload.description,
            metadata={"admin_initiated": "true", "target_user": payload.user_id},
        )
        return charge_result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Refund ────────────────────────────────────────────────────────────────────
class RefundRequest(BaseModel):
    payment_intent_id: str
    amount_usd: Optional[float] = None
    reason: str = "requested_by_customer"


@router.post("/refund")
async def create_refund(
    payload: RefundRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Issue a refund. ADMIN ONLY."""
    try:
        result = await issue_refund(
            payment_intent_id=payload.payment_intent_id,
            amount_usd=payload.amount_usd,
            reason=payload.reason,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
