# backend/utils/dependencies.py
"""
FastAPI Dependency Injection
==============================
"Dependencies" are reusable functions that FastAPI automatically calls
before your route handler runs.

Think of them like bouncers at a club:
- get_current_user → "Show me your ID (JWT token)"
- require_admin    → "VIP section only (admin role)"
- get_api_key_user → "Show me your access pass (API key)"

Real-world: This pattern is used by FastAPI, Flask-Login, Django auth.
It's cleaner than copy-pasting auth code into every route.
"""

from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.database import get_db, get_redis
from backend.services.auth_service import decode_token, get_user_by_id
from backend.services.apikey_service import get_key_by_hash
from backend.services.token_blacklist import is_token_blacklisted, is_user_tokens_invalidated
from backend.models.user_model import User, UserRole
from backend.models.apikey_model import APIKey


# ── HTTP Bearer token extractor ───────────────────────────────────────────────
# Reads the "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer(auto_error=False)

# ── API Key Header extractor ──────────────────────────────────────────────────
# Reads the "X-API-Key: mf_live_abc123" header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ═══════════════════════════════════════════════════════════════════════════════
# JWT-based Authentication (for Dashboard / Web App)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Security(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> User:
    """
    Extract and validate the JWT token from the Authorization header.
    Now includes Redis blacklist check for real logout support.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise credentials_exception

    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        jti: str = payload.get("jti")
        iat: int = payload.get("iat", 0)

        if not user_id or token_type != "access":
            raise credentials_exception
    except ValueError:
        raise credentials_exception

    # ── Blacklist check ────────────────────────────────────────────────────
    if jti and await is_token_blacklisted(jti, redis):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if await is_user_tokens_invalidated(user_id, iat, redis):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise credentials_exception

    return user


# ── Convenience type alias ─────────────────────────────────────────────────────
CurrentUser = Annotated[User, Depends(get_current_user)]


# ═══════════════════════════════════════════════════════════════════════════════
# Role-Based Access Control (RBAC)
# ═══════════════════════════════════════════════════════════════════════════════

def require_role(*roles: UserRole):
    """
    Factory function that creates a dependency for specific roles.
    
    Usage:
        @router.delete("/users/{id}")
        async def delete_user(user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    
    Real-world: AWS IAM, Google Cloud IAM, GitHub Teams all use this pattern.
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {[r.value for r in roles]}",
            )
        return current_user
    return role_checker


# Shortcut dependencies for common role checks
require_admin = Depends(require_role(UserRole.ADMIN))
require_developer_or_admin = Depends(require_role(UserRole.DEVELOPER, UserRole.ADMIN))


# ═══════════════════════════════════════════════════════════════════════════════
# API Key Authentication (for external API consumers)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_current_api_key(
    raw_key: Annotated[Optional[str], Security(api_key_header)],
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """
    Authenticate requests using API Keys (X-API-Key header).
    
    This is used when external systems call your API.
    The JWT auth above is for YOUR dashboard users.
    
    Usage:
        @router.get("/data")
        async def get_data(api_key: APIKey = Depends(get_current_api_key)):
            ...
    """
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Include 'X-API-Key' header.",
        )
    
    api_key = await get_key_by_hash(db, raw_key)
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )
    
    # Check expiry
    from datetime import datetime, timezone
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired.",
        )
    
    return api_key
