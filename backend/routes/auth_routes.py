# backend/routes/auth_routes.py
"""
Authentication Routes
======================
Endpoints:
  POST /api/v1/auth/signup    → Register new user
  POST /api/v1/auth/login     → Get JWT tokens
  POST /api/v1/auth/refresh   → Refresh expired access token
  POST /api/v1/auth/logout    → Invalidate token (client-side)
  GET  /api/v1/auth/me        → Get current user profile
"""

from fastapi import APIRouter, Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from backend.config.database import get_db, get_redis
from backend.controllers.schemas import (
    SignupRequest, LoginRequest, TokenResponse,
    RefreshTokenRequest, UserResponse, MessageResponse,
)
from backend.services.auth_service import (
    authenticate_user, create_user, create_access_token,
    create_refresh_token, decode_token, get_user_by_email,
    get_user_by_id,
)
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User
from backend.config.settings import settings


router = APIRouter()

bearer_scheme = HTTPBearer()

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Register a new user.

    Steps:
    1. Check email isn't already taken
    2. Check username isn't already taken
    3. Hash password
    4. Create user in PostgreSQL
    5. Send verification email (non-blocking background task)
    6. Return user profile (no password!)

    Test with Postman:
    POST http://localhost:8000/api/v1/auth/signup
    Body: {"email": "test@example.com", "username": "testuser", "password": "Test1234"}
    """
    # Check for duplicate email
    existing_email = await get_user_by_email(db, payload.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Check for duplicate username
    from sqlalchemy import select
    from backend.models.user_model import User as UserModel
    result = await db.execute(
        select(UserModel).where(UserModel.username == payload.username.lower())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already taken.",
        )

    # Create the user
    user = await create_user(
        db=db,
        email=payload.email,
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
    )

    # Gap 2 fix: send verification email (fire-and-forget, never blocks signup)
    try:
        from backend.routes.verification_routes import generate_and_send_verification
        import asyncio
        asyncio.create_task(generate_and_send_verification(user, redis))
    except Exception:
        pass  # Email failure must never fail signup

    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Login and receive JWT tokens.
    
    Returns:
    - access_token  (short-lived, 60 min) → use for API requests
    - refresh_token (long-lived, 7 days)  → use to get new access token
    
    Test with Postman:
    POST http://localhost:8000/api/v1/auth/login
    Body: {"email": "test@example.com", "password": "Test1234"}
    """
    user = await authenticate_user(db, payload.email, payload.password)
    
    if not user:
        # IMPORTANT: Use the same error for wrong email AND wrong password.
        # This prevents "user enumeration" attacks.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    
    # Update last login time
    user.last_login_at = datetime.now(timezone.utc)
    
    # Generate tokens
    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
    refresh_token = create_refresh_token(user_id=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """
    Exchange a refresh token for a new access token.
    
    Flow:
    1. Frontend detects access token expired (401 response)
    2. Frontend calls this endpoint with refresh token
    3. Gets new access token without user re-logging in
    
    Test with Postman:
    POST http://localhost:8000/api/v1/auth/refresh
    Body: {"refresh_token": "<your_refresh_token>"}
    """
    try:
        payload_data = decode_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )
    
    # Verify it's actually a refresh token (not an access token)
    if payload_data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )
    
    user = await get_user_by_id(db, payload_data["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated.",
        )
    
    # Issue new tokens
    new_access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
    new_refresh_token = create_refresh_token(user_id=str(user.id))
    
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    Get the currently logged-in user's profile.
    
    Requires: Authorization: Bearer <access_token>
    
    Test with Postman:
    GET http://localhost:8000/api/v1/auth/me
    Headers: Authorization: Bearer <your_access_token>
    """
    return current_user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Security(bearer_scheme)],
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """
    Logout endpoint — properly blacklists the JWT token.

    The token is added to Redis blacklist with TTL = remaining lifetime.
    Any future request using this token returns 401 immediately.

    Test with Postman:
      POST /api/v1/auth/logout
      Headers: Authorization: Bearer <your_token>
      → Try using the same token again → should get 401
    """
    if credentials and redis:
        from backend.services.token_blacklist import blacklist_token
        await blacklist_token(credentials.credentials, redis)

    return MessageResponse(message=f"Logged out successfully. Token revoked.")
