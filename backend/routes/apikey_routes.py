# backend/routes/apikey_routes.py
"""
API Key Management Routes
==========================
  POST   /api/v1/keys/          → Create a new API key
  GET    /api/v1/keys/          → List all my API keys
  GET    /api/v1/keys/{key_id}  → Get single key details
  DELETE /api/v1/keys/{key_id}  → Revoke (deactivate) a key
  POST   /api/v1/keys/verify    → Verify a key is valid (internal use)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from backend.config.database import get_db
from backend.controllers.schemas import (
    CreateAPIKeyRequest, APIKeyCreatedResponse,
    APIKeyResponse, MessageResponse,
)
from backend.services.apikey_service import (
    create_api_key, list_user_api_keys,
    revoke_api_key, get_key_by_hash,
)
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()


@router.post("/", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new API key.
    
    ⚠️  IMPORTANT: The full key is only shown ONCE in the response!
    Save it immediately - it cannot be retrieved again (we only store a hash).
    
    Test with Postman:
    POST http://localhost:8000/api/v1/keys/
    Headers: Authorization: Bearer <your_access_token>
    Body: {"name": "My Production Key", "environment": "live"}
    """
    # Limit how many keys a user can have (abuse prevention)
    existing_keys = await list_user_api_keys(db, str(current_user.id))
    active_keys = [k for k in existing_keys if k.is_active]
    
    MAX_KEYS = {"free": 2, "starter": 5, "pro": 20, "enterprise": 100}
    plan_limit = MAX_KEYS.get(current_user.plan, 2)
    
    if len(active_keys) >= plan_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Key limit reached for {current_user.plan} plan ({plan_limit} keys). Upgrade to create more.",
        )
    
    api_key_record, full_key = await create_api_key(
        db=db,
        user=current_user,
        name=payload.name,
        description=payload.description,
        environment=payload.environment,
        scopes=payload.scopes,
        rate_limit_per_minute=payload.rate_limit_per_minute,
    )
    
    # Build response - include full_key HERE (only time it's ever sent)
    return APIKeyCreatedResponse(
        id=api_key_record.id,
        name=api_key_record.name,
        key_prefix=api_key_record.key_prefix,
        full_key=full_key,  # ← This is the ONLY time we reveal the full key
        environment=api_key_record.environment,
        scopes=api_key_record.scopes,
        rate_limit_per_minute=api_key_record.rate_limit_per_minute,
        created_at=api_key_record.created_at,
    )


@router.get("/", response_model=List[APIKeyResponse])
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the current user.
    Returns metadata only - never the actual key value.
    
    Test with Postman:
    GET http://localhost:8000/api/v1/keys/
    Headers: Authorization: Bearer <your_access_token>
    """
    keys = await list_user_api_keys(db, str(current_user.id))
    return keys


@router.delete("/{key_id}", response_model=MessageResponse)
async def revoke_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke (deactivate) an API key.
    
    The key record is kept for audit history but marked inactive.
    Any requests using this key will immediately get 401 Unauthorized.
    
    Test with Postman:
    DELETE http://localhost:8000/api/v1/keys/{key_id}
    Headers: Authorization: Bearer <your_access_token>
    """
    success = await revoke_api_key(db, str(key_id), str(current_user.id))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or you don't have permission to revoke it.",
        )
    
    return MessageResponse(message="API key revoked successfully. All requests using this key will now fail.")


@router.post("/verify")
async def verify_key(
    x_api_key: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Internal endpoint to verify if an API key is valid.
    Used by other microservices in a multi-service architecture.
    
    Real-world: This is called an "introspection endpoint" - 
    used in OAuth 2.0 to validate tokens between services.
    """
    api_key = await get_key_by_hash(db, x_api_key)
    
    if not api_key:
        return {"valid": False, "reason": "Key not found or revoked"}
    
    return {
        "valid": True,
        "key_id": str(api_key.id),
        "user_id": str(api_key.user_id),
        "scopes": api_key.scopes,
        "rate_limit_per_minute": api_key.rate_limit_per_minute,
    }
