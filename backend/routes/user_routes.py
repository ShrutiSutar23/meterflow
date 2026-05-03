# backend/routes/user_routes.py
"""
User Management Routes
=======================
  GET    /api/v1/users/me         → Get my profile
  PATCH  /api/v1/users/me         → Update my profile  
  GET    /api/v1/users/           → List all users (admin only)
  GET    /api/v1/users/{id}       → Get user by ID (admin only)
  PATCH  /api/v1/users/{id}/plan  → Change user's billing plan (admin only)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID

from backend.config.database import get_db
from backend.controllers.schemas import UserResponse, UserUpdateRequest, MessageResponse
from backend.utils.dependencies import get_current_user, require_role
from backend.models.user_model import User, UserRole


router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Get the authenticated user's profile."""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update profile fields."""
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.username is not None:
        # Check username not taken
        result = await db.execute(
            select(User).where(User.username == payload.username.lower(), User.id != current_user.id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken.")
        current_user.username = payload.username.lower()
    
    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.get("/", response_model=List[UserResponse])
async def list_all_users(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    List all users. ADMIN ONLY.
    
    This demonstrates RBAC (Role-Based Access Control) in action.
    Non-admin users will get 403 Forbidden.
    
    Test: Try with a non-admin user's token → should get 403.
    Then try with admin token → should get full user list.
    """
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.patch("/{user_id}/plan", response_model=UserResponse)
async def change_user_plan(
    user_id: UUID,
    plan: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's billing plan. ADMIN ONLY."""
    VALID_PLANS = {"free": 10_000, "starter": 50_000, "pro": 500_000, "enterprise": 10_000_000}
    
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose from: {list(VALID_PLANS.keys())}")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    
    user.plan = plan
    user.monthly_request_limit = VALID_PLANS[plan]
    
    await db.flush()
    await db.refresh(user)
    return user
