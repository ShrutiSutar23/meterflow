# backend/controllers/schemas.py
"""
Pydantic Schemas (Request/Response Validation)
=================================================
Pydantic validates incoming request data BEFORE it hits your business logic.
It's like a strict form validator.

Two types:
1. Request schemas  → Validate what comes IN  (e.g., SignupRequest)
2. Response schemas → Shape what goes OUT     (e.g., UserResponse)

Why response schemas?
- They prevent leaking sensitive fields (like hashed_password!)
- They define a stable API contract for frontend developers
- Auto-generate API documentation (Swagger UI at /docs)

Real-world: FastAPI + Pydantic is used by Netflix, Uber, Spotify for their APIs.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
import re


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class SignupRequest(BaseModel):
    """Validates user registration data."""
    email: EmailStr                         # Pydantic validates email format
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        """Only allow letters, numbers, underscores, and hyphens."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, _ and -")
        return v.lower()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Basic password strength check."""
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v

    model_config = {"json_schema_extra": {
        "example": {
            "email": "developer@example.com",
            "username": "john_dev",
            "password": "SecurePass123",
            "full_name": "John Developer"
        }
    }}


class LoginRequest(BaseModel):
    """Login credentials."""
    email: EmailStr
    password: str

    model_config = {"json_schema_extra": {
        "example": {"email": "developer@example.com", "password": "SecurePass123"}
    }}


class TokenResponse(BaseModel):
    """JWT tokens returned after successful login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int             # Seconds until access token expires


class RefreshTokenRequest(BaseModel):
    """Request to refresh an expired access token."""
    refresh_token: str


# ═══════════════════════════════════════════════════════════════════════════════
# USER SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class UserResponse(BaseModel):
    """
    Safe user data to return in API responses.
    
    NOTICE: hashed_password is NOT here!
    This is the response schema pattern - it acts as a filter,
    ensuring sensitive fields never leave the server.
    """
    id: UUID
    email: str
    username: str
    full_name: Optional[str]
    role: str
    plan: str
    is_active: bool
    is_verified: bool
    monthly_request_limit: int
    requests_this_month: int
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = {"from_attributes": True}    # Allow creating from SQLAlchemy model


class UserUpdateRequest(BaseModel):
    """Fields a user can update in their profile."""
    full_name: Optional[str] = Field(None, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=30)


# ═══════════════════════════════════════════════════════════════════════════════
# API KEY SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class CreateAPIKeyRequest(BaseModel):
    """Request body for creating a new API key."""
    name: str = Field(min_length=1, max_length=255, description="A friendly name for this key")
    description: Optional[str] = Field(None, max_length=500)
    environment: str = Field(default="live", pattern="^(live|test)$")
    scopes: List[str] = Field(default=["read:usage"])
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)

    model_config = {"json_schema_extra": {
        "example": {
            "name": "Production Backend",
            "description": "Used by our main app server",
            "environment": "live",
            "scopes": ["read:usage", "write:data"],
            "rate_limit_per_minute": 60
        }
    }}


class APIKeyCreatedResponse(BaseModel):
    """
    Response when a key is first created.
    Includes the FULL key (shown only ONCE).
    After this, only key_prefix is ever returned.
    """
    id: UUID
    name: str
    key_prefix: str
    full_key: str               # ← SHOWN ONLY THIS ONE TIME
    environment: str
    scopes: List[str]
    rate_limit_per_minute: int
    created_at: datetime
    
    model_config = {"from_attributes": True}


class APIKeyResponse(BaseModel):
    """
    Standard API key info (NO full key, NO hash - just metadata).
    Used in list/get endpoints.
    """
    id: UUID
    name: str
    key_prefix: str             # e.g., "mf_live_ab" - safe to display
    description: Optional[str]
    environment: str
    scopes: List[str]
    rate_limit_per_minute: int
    is_active: bool
    total_requests: int
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class MessageResponse(BaseModel):
    """Simple message response for operations like delete, revoke, etc."""
    message: str
    success: bool = True


class ErrorResponse(BaseModel):
    """Standard error response shape."""
    error: str
    detail: str
    status_code: int
