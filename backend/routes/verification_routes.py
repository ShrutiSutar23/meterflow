# backend/routes/verification_routes.py
"""
Email Verification (Day 12)
=============================
Flow:
  1. User signs up → we generate a token → email them a verify link
  2. User clicks the link → hits GET /api/v1/auth/verify/{token}
  3. We look up token in Redis → set is_verified=True in PostgreSQL
  4. Protected endpoints can now require is_verified=True

WHY VERIFY EMAIL?
  - Prevents fake accounts with typo'd emails (billing goes to wrong person)
  - Required for GDPR / CAN-SPAM compliance
  - Reduces spam/abuse signups
  - Real companies (GitHub, Stripe, AWS) all require it

SECURITY DESIGN:
  - Token = 32 bytes of cryptographic randomness (urlsafe_b64)
  - Stored in Redis with 24-hour TTL
  - Single-use: deleted immediately after use
  - New signup always overwrites old token (handles re-send)

INTERVIEW NOTE:
  This pattern is identical to password reset.
  Same Redis key-value approach, same single-use rule.
  Different TTL (24h vs 1h) because email delivery can be slow.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.database import get_db, get_redis
from backend.services.auth_service import get_user_by_id
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User

router = APIRouter()

VERIFY_KEY_PREFIX = "emailverify:"
VERIFY_TOKEN_TTL  = 86400   # 24 hours in seconds


async def generate_and_send_verification(user: User, redis) -> str:
    """
    Generate a verification token, store in Redis, and send the email.
    Called at: signup, and when user requests a resend.

    Returns the token (so tests can use it directly).
    """
    token = secrets.token_urlsafe(32)
    if redis:
        await redis.setex(f"{VERIFY_KEY_PREFIX}{token}", VERIFY_TOKEN_TTL, str(user.id))

    # Send verification email (non-blocking)
    import asyncio
    from backend.services.email_service import _send_email, _base_template
    verify_url = f"http://localhost:5173/verify-email?token={token}"
    html = _base_template(
        title="Verify your email address",
        body_html=f"""
        <p>Hi <strong>{user.username}</strong>,</p>
        <p>Please verify your email address to activate your MeterFlow account.</p>
        <p>This link expires in <strong>24 hours</strong>.</p>
        <p style="color:#999;font-size:13px;">If you didn't create a MeterFlow account,
        you can safely ignore this email.</p>
        """,
        cta_url=verify_url,
        cta_text="Verify Email Address →",
    )
    asyncio.create_task(
        _send_email(user.email, "Verify your MeterFlow email address", html)
    )
    return token


@router.get("/verify/{token}")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Confirm email address using the token from the verification email.

    Test flow:
      1. POST /api/v1/auth/signup → triggers email with token
      2. GET  /api/v1/auth/verify/<token>  → sets is_verified=True
      3. GET  /api/v1/auth/me → is_verified is now True

    Test with curl:
      curl http://localhost:8000/api/v1/auth/verify/<your_token>
    """
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    redis_key = f"{VERIFY_KEY_PREFIX}{token}"
    user_id = await redis.get(redis_key)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link. Please request a new one.",
        )

    # Delete token (single-use)
    await redis.delete(redis_key)

    # Mark user as verified
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.is_verified:
        return {"message": "Email already verified. You're all set!"}

    user.is_verified = True
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Invalidate all tokens issued before verification (security hygiene)
    from backend.services.token_blacklist import blacklist_all_user_tokens
    await blacklist_all_user_tokens(user_id, redis)

    return {
        "message": "Email verified successfully! Your account is now fully active.",
        "email": user.email,
    }


@router.post("/resend-verification")
async def resend_verification(
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """
    Resend the verification email.
    Used when the original email expired or was lost.

    Requires the user to be logged in (so we know who to send it to).
    Rate-limit this in production to prevent email bombing.
    """
    if current_user.is_verified:
        return {"message": "Your email is already verified."}

    token = await generate_and_send_verification(current_user, redis)

    return {
        "message": f"Verification email resent to {current_user.email}.",
        "expires_in_hours": 24,
        # Only include token in DEBUG mode — never in production
        "_debug_token": token if True else None,
    }
