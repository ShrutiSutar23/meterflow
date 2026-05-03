# backend/routes/password_routes.py
"""
Password Reset Routes (Day 11)
================================
  POST /api/v1/auth/forgot-password  → Request reset email
  POST /api/v1/auth/reset-password   → Submit new password with token
  POST /api/v1/auth/change-password  → Change password (logged-in user)

SECURITY DESIGN:
  1. User submits email → we generate a secure random token
  2. Store token in Redis: "pwreset:{token}" → user_id  (1 hour TTL)
  3. Email the reset URL: /reset-password?token=<token>
  4. User clicks link → frontend sends token + new password to us
  5. We look up token in Redis, find user, update password
  6. Delete token from Redis immediately (single-use)

WHY REDIS (not DB)?
  - Tokens are temporary — no need to clutter your DB
  - TTL built-in — auto-expires after 1 hour
  - Fast lookup — O(1) key lookup

SECURITY RULES:
  - Always return the same message whether email exists or not
    (prevents account enumeration — attacker can't discover emails)
  - Token is single-use — delete it immediately after use
  - Token expires in 1 hour — limits attack window
  - New reset request invalidates old token
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr

from backend.config.database import get_db, get_redis
from backend.services.auth_service import hash_password, get_user_by_email, get_user_by_id
from backend.services.email_service import send_password_reset_email
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()

RESET_TOKEN_TTL = 3600          # 1 hour in seconds
RESET_KEY_PREFIX = "pwreset:"   # Redis key prefix


# ── Schemas ───────────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    class Config:
        json_schema_extra = {"example": {"email": "user@example.com"}}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    class Config:
        json_schema_extra = {
            "example": {
                "token": "abc123def456...",
                "new_password": "NewSecurePass456",
            }
        }


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Request a password reset email.

    ALWAYS returns success message — never reveal if email exists.
    This prevents attackers from discovering which emails are registered.

    Test with Postman:
      POST /api/v1/auth/forgot-password
      Body: {"email": "test@example.com"}
      → Always returns 200 with same message
    """
    # Look up user (silently do nothing if not found)
    user = await get_user_by_email(db, payload.email)

    if user and user.is_active and redis:
        # Generate a secure random token
        token = secrets.token_urlsafe(32)   # 43 chars of URL-safe random data

        # Store in Redis: key="pwreset:abc123..." value="user-uuid" TTL=1hr
        await redis.setex(
            f"{RESET_KEY_PREFIX}{token}",
            RESET_TOKEN_TTL,
            str(user.id),
        )

        # Send email (non-blocking — we don't await the result to slow down response)
        import asyncio
        asyncio.create_task(
            send_password_reset_email(user.email, user.username, token)
        )

    # Always return the same response
    return {
        "message": "If that email is registered, you'll receive a reset link shortly.",
        "expires_in_minutes": 60,
    }


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Submit a new password using the reset token from email.

    Steps:
    1. Look up token in Redis → get user_id
    2. Delete token (single-use — prevent replay attacks)
    3. Hash new password
    4. Update user record
    5. Return success

    Test with Postman:
      POST /api/v1/auth/reset-password
      Body: {"token": "<from_email>", "new_password": "NewPass123"}
    """
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    # Validate password strength
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not any(c.isdigit() for c in payload.new_password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number.")

    # Look up token
    redis_key = f"{RESET_KEY_PREFIX}{payload.token}"
    user_id = await redis.get(redis_key)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token. Please request a new one.",
        )

    # Delete token immediately (single-use)
    await redis.delete(redis_key)

    # Find user and update password
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="User not found or account deactivated.")

    user.hashed_password = hash_password(payload.new_password)
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Gap 6 fix: invalidate ALL existing sessions — old tokens can't be used
    if redis:
        from backend.services.token_blacklist import blacklist_all_user_tokens
        await blacklist_all_user_tokens(str(user.id), redis)

    return {
        "message": "Password updated successfully. You can now log in with your new password.",
    }


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Change password for a logged-in user.
    Requires the current password for security (prevents session hijack attacks).

    Test with Postman:
      POST /api/v1/auth/change-password
      Headers: Authorization: Bearer <token>
      Body: {"current_password": "OldPass123", "new_password": "NewPass456"}
    """
    from backend.services.auth_service import verify_password

    # Verify current password
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    # Validate new password
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    if not any(c.isdigit() for c in payload.new_password):
        raise HTTPException(status_code=400, detail="New password must contain at least one number.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password.")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.updated_at = datetime.now(timezone.utc)

    # Gap 6 fix: invalidate all other active sessions after password change
    if redis:
        from backend.services.token_blacklist import blacklist_all_user_tokens
        await blacklist_all_user_tokens(str(current_user.id), redis)

    return {"message": "Password changed successfully. All other sessions have been logged out."}
