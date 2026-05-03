# backend/services/auth_service.py
"""
Authentication Service
=======================
This handles all the logic for:
1. Hashing passwords (bcrypt)
2. Creating JWT tokens (login credentials)
3. Verifying JWT tokens (checking if user is logged in)

Think of JWT like a theme park wristband:
- You prove your identity ONCE at the entrance (login)
- You get a wristband (JWT token) 
- Every ride (API endpoint) just checks your wristband
- No need to show ID again until the wristband expires

Interview topic: JWT vs Session-based auth
- JWT: Stateless (no server storage needed). Great for microservices.
- Session: Stateful (server stores session). Better for single servers.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config.settings import settings
from backend.models.user_model import User


# ── Password Hashing ──────────────────────────────────────────────────────────
# bcrypt automatically adds a "salt" (random data) before hashing.
# This means even if two users have the same password, their hashes are different.
# schemes=["bcrypt"] means we use the bcrypt algorithm (industry standard).
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Convert plain text password to bcrypt hash.
    Example: "mypassword123" → "$2b$12$EixZaYVK1fsbw1ZfbX3OXe...."
    
    This is one-way - you can NEVER reverse a bcrypt hash back to the password.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check if a plain password matches a stored hash.
    Used during login to verify the user's entered password.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Token Creation ────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a short-lived JWT access token (default: 60 minutes).
    
    The token contains:
    - sub: The user's ID (subject)
    - exp: Expiry timestamp
    - type: "access" 
    - jti: Unique token ID (for future revocation support)
    
    Real-world: This is exactly what GitHub, Google, Stripe use for their API tokens.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "type": "access",
        "jti": str(uuid.uuid4()),   # Unique ID for this specific token
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """
    Creates a long-lived JWT refresh token (default: 7 days).
    
    The refresh token is used to get a NEW access token when the old one expires.
    This avoids forcing users to re-login every hour.
    
    Flow:
    1. User logs in → gets access_token (1hr) + refresh_token (7 days)
    2. After 1hr, access_token expires
    3. Frontend sends refresh_token → gets new access_token
    4. After 7 days, refresh_token expires → user must re-login
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh", "jti": str(uuid.uuid4())},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT token.
    Raises JWTError if token is invalid, expired, or tampered with.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")


# ── Database User Operations ──────────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Fetch user from PostgreSQL by email address."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    """Fetch user from PostgreSQL by UUID."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    """
    Verify email + password combination.
    
    Security best practice: Always say "invalid credentials" (not "user not found")
    to prevent user enumeration attacks (attacker discovering which emails exist).
    """
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


async def create_user(db: AsyncSession, email: str, username: str, 
                      password: str, full_name: str = None) -> User:
    """
    Register a new user.
    
    Steps:
    1. Hash the password
    2. Create User object
    3. Add to PostgreSQL
    4. Return the created user
    """
    user = User(
        email=email.lower().strip(),
        username=username.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    await db.flush()    # flush to get the generated ID without committing
    await db.refresh(user)
    return user
