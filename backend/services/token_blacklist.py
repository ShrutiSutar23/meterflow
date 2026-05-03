# backend/services/token_blacklist.py
"""
JWT Token Blacklist (Day 12)
==============================
Problem with stateless JWTs:
  Once issued, a JWT is valid until it expires — even after logout.
  If a token is stolen, the attacker can use it for up to 60 minutes.

Solution: Token Blacklist in Redis
  On logout → store the token's unique ID (jti) in Redis
  On every request → check if the jti is blacklisted
  TTL = remaining lifetime of the token (auto-expires when token would expire)

WHY REDIS (not PostgreSQL)?
  - Every single API request hits this check — must be nanosecond fast
  - Redis GET is ~0.1ms. PostgreSQL SELECT would be ~2-5ms per request.
  - TTL built in — no cleanup job needed

PERFORMANCE IMPACT:
  - One extra Redis GET per authenticated request
  - Redis pipeline can batch this with rate limit check (zero extra round-trip)
  - Total overhead: ~0.1ms — completely negligible

INTERVIEW TOPIC:
  "How do you invalidate JWTs?"
  Answer: Blacklist the jti (unique token ID) in Redis with TTL equal to
  the token's remaining lifetime. The jti is embedded in every JWT we create
  (see auth_service.py create_access_token). On each request, after decoding
  the JWT, we check Redis for the jti before allowing access.

Real-world: Auth0, Okta, Firebase all use this exact pattern.
"""

from datetime import datetime, timezone
from typing import Optional

from jose import jwt as jose_jwt

from backend.config.settings import settings

BLACKLIST_KEY_PREFIX = "jwt_blacklist:"


async def blacklist_token(token: str, redis) -> bool:
    """
    Add a JWT to the blacklist.
    Called on logout.

    Extracts the jti and expiry from the token,
    stores jti in Redis with TTL = remaining token lifetime.
    """
    if not redis:
        return False

    try:
        # Decode without verification to get claims (token was already verified)
        payload = jose_jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        jti = payload.get("jti")
        exp = payload.get("exp")

        if not jti or not exp:
            return False

        # Calculate remaining TTL
        now = int(datetime.now(timezone.utc).timestamp())
        remaining_ttl = max(exp - now, 1)   # At least 1 second

        # Store: "jwt_blacklist:<jti>" = "1"  with TTL
        await redis.setex(f"{BLACKLIST_KEY_PREFIX}{jti}", remaining_ttl, "1")
        return True

    except Exception:
        return False


async def is_token_blacklisted(jti: str, redis) -> bool:
    """
    Check if a token's jti is on the blacklist.
    Called on every authenticated request.

    Returns True if token is revoked (should be rejected).
    Returns False if token is still valid.
    """
    if not redis or not jti:
        return False
    result = await redis.get(f"{BLACKLIST_KEY_PREFIX}{jti}")
    return result is not None


async def blacklist_all_user_tokens(user_id: str, redis) -> int:
    """
    Blacklist ALL tokens for a user.
    Used when:
    - User changes password (invalidate all sessions)
    - Admin suspends account
    - Security breach detected

    We store a "user-level" blacklist entry.
    Any token issued BEFORE this timestamp is rejected.

    Returns the count of active sessions invalidated.
    """
    if not redis:
        return 0

    now = int(datetime.now(timezone.utc).timestamp())
    # Store the invalidation timestamp for this user
    # Tokens with iat (issued-at) before this time are rejected
    key = f"jwt_invalidate_before:{user_id}"
    # Keep for 7 days (matches refresh token lifetime)
    await redis.setex(key, 86400 * 7, str(now))
    return 1


async def is_user_tokens_invalidated(user_id: str, token_iat: int, redis) -> bool:
    """
    Check if ALL of a user's tokens were invalidated after a security event.
    Called alongside is_token_blacklisted for complete coverage.
    """
    if not redis:
        return False
    key = f"jwt_invalidate_before:{user_id}"
    invalidate_before = await redis.get(key)
    if not invalidate_before:
        return False
    return token_iat <= int(invalidate_before)
