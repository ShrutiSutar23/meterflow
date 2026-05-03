# backend/services/apikey_service.py
"""
API Key Service
================
Handles generating, validating, and revoking API keys.

Security design (industry standard, used by Stripe/Twilio/SendGrid):

  Key format:  mf_live_xK9pQ2rL8nJwTvZ3...  (total 48 chars)
               ──┬──── ──┬── ─────┬──────
                 │       │        └─ 32 random chars (the secret part)
                 │       └─ environment (live/test)
                 └─ service prefix

  What we store in DB:
    - key_prefix  = "mf_live_xK9p"  (first 12 chars, shown in UI)
    - key_hash    = SHA-256(full_key)  (for fast lookup & verification)
  
  What we show user:
    - Full key ONCE at creation time only. After that, it's gone forever.
    - This is exactly how Stripe and GitHub work.
"""

import secrets
import hashlib
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from backend.models.apikey_model import APIKey
from backend.models.user_model import User


def generate_api_key(environment: str = "live") -> tuple[str, str, str]:
    """
    Generate a new API key.
    
    Returns:
        full_key   : The complete key shown to the user ONCE (e.g., mf_live_abc123...)
        key_prefix : First 12 chars for display in UI (e.g., mf_live_ab)
        key_hash   : SHA-256 hash stored in DB for verification
    
    Why SHA-256 and not bcrypt?
    - bcrypt is slow by design (good for passwords, bad for API key lookups)
    - SHA-256 is fast (we need to verify on EVERY request)
    - API keys are already random (long entropy), so no need for salt
    """
    # Generate 32 cryptographically secure random bytes → 64 hex chars
    raw_secret = secrets.token_urlsafe(32)  # URL-safe base64, 43 chars
    
    # Build full key with prefix
    prefix = f"mf_{environment}_"
    full_key = f"{prefix}{raw_secret}"
    
    # Store first 12 chars as the display prefix
    key_prefix = full_key[:12]
    
    # Hash the full key for storage
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    
    return full_key, key_prefix, key_hash


def hash_api_key(api_key: str) -> str:
    """Hash an incoming API key for DB lookup. Used during request verification."""
    return hashlib.sha256(api_key.encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    user: User,
    name: str,
    description: str = None,
    environment: str = "live",
    scopes: List[str] = None,
    rate_limit_per_minute: int = 60,
) -> tuple[APIKey, str]:
    """
    Create and save a new API key for a user.
    
    Returns:
        (api_key_record, full_key)
        The full_key must be sent to the user NOW and never stored/shown again.
    """
    full_key, key_prefix, key_hash = generate_api_key(environment)
    
    api_key = APIKey(
        user_id=user.id,
        key_prefix=key_prefix,
        key_hash=key_hash,
        name=name,
        description=description,
        environment=environment,
        scopes=scopes or ["read:usage"],
        rate_limit_per_minute=rate_limit_per_minute,
    )
    
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    
    # Return the DB record AND the full key (shown once to user)
    return api_key, full_key


async def get_key_by_hash(db: AsyncSession, raw_key: str) -> Optional[APIKey]:
    """
    Look up an API key by hashing the incoming value.
    Used in middleware to authenticate every incoming API request.
    
    Flow:
    1. Request comes in with header: X-API-Key: mf_live_abc123...
    2. We hash it: SHA-256(mf_live_abc123...) → abc456def...
    3. We look up that hash in the DB
    4. If found and active → request is authenticated
    """
    key_hash = hash_api_key(raw_key)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)
    )
    return result.scalar_one_or_none()


async def list_user_api_keys(db: AsyncSession, user_id: str) -> List[APIKey]:
    """Get all API keys for a user (never returns the actual key value)."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == user_id)
        .order_by(APIKey.created_at.desc())
    )
    return result.scalars().all()


async def revoke_api_key(db: AsyncSession, key_id: str, user_id: str) -> bool:
    """
    Deactivate an API key (soft delete - we keep the record for audit logs).
    Real companies never hard-delete keys because they need billing/audit history.
    """
    result = await db.execute(
        update(APIKey)
        .where(APIKey.id == key_id, APIKey.user_id == user_id)
        .values(is_active=False, updated_at=datetime.now(timezone.utc))
    )
    return result.rowcount > 0


async def update_key_last_used(db: AsyncSession, key_id: str) -> None:
    """Update the last_used_at timestamp and increment total_requests counter."""
    await db.execute(
        update(APIKey)
        .where(APIKey.id == key_id)
        .values(
            last_used_at=datetime.now(timezone.utc),
            total_requests=APIKey.total_requests + 1,
        )
    )
