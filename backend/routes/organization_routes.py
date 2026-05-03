# backend/routes/organization_routes.py
"""
Organization Routes (Day 10)
==============================
  POST   /api/v1/orgs/                        → Create organization
  GET    /api/v1/orgs/                        → List my organizations
  GET    /api/v1/orgs/{slug}                  → Get org details
  PATCH  /api/v1/orgs/{slug}                  → Update org (admin+)
  DELETE /api/v1/orgs/{slug}                  → Delete org (owner only)

  GET    /api/v1/orgs/{slug}/members          → List members
  POST   /api/v1/orgs/{slug}/members/invite   → Invite a user
  POST   /api/v1/orgs/invites/{token}/accept  → Accept an invite
  PATCH  /api/v1/orgs/{slug}/members/{uid}    → Change member role
  DELETE /api/v1/orgs/{slug}/members/{uid}    → Remove member

Test with Postman:
  POST http://localhost:8000/api/v1/orgs/
  Headers: Authorization: Bearer <token>
  Body: {"name": "Acme Corp", "slug": "acme-corp"}
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID

from backend.config.database import get_db
from backend.services.organization_service import (
    create_organization, get_org_by_slug, get_user_orgs,
    require_org_role, invite_member, accept_invite,
    update_member_role, remove_member, list_org_members,
)
from backend.models.organization_model import OrgMemberRole
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9-]+$",
                      description="URL-safe name: lowercase, numbers, hyphens only")
    description: Optional[str] = Field(None, max_length=500)

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Acme Corporation",
                "slug": "acme-corp",
                "description": "Building the future of widgets",
            }
        }


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    website: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str
    role: OrgMemberRole = OrgMemberRole.MEMBER

    class Config:
        json_schema_extra = {
            "example": {"email": "colleague@example.com", "role": "member"}
        }


class UpdateMemberRoleRequest(BaseModel):
    role: OrgMemberRole


# ═══════════════════════════════════════════════════════════════════════════════
# ORGANIZATION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: CreateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new organization. The creator automatically becomes OWNER.

    After creation, you can:
    - Invite team members
    - Create API keys scoped to the org
    - View consolidated billing for the whole team

    Test:
      POST /api/v1/orgs/
      Body: {"name": "My Startup", "slug": "my-startup"}
    """
    try:
        org = await create_organization(
            db=db,
            name=payload.name,
            slug=payload.slug,
            owner=current_user,
            description=payload.description,
        )
        return {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "plan": org.plan,
            "your_role": "owner",
            "created_at": org.created_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/")
async def list_my_orgs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all organizations the current user belongs to.
    Includes their role in each org.
    """
    orgs = await get_user_orgs(db, str(current_user.id))
    return {"organizations": orgs, "count": len(orgs)}


@router.get("/{slug}")
async def get_org(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get organization details.
    User must be a member to view.
    """
    org = await get_org_by_slug(db, slug)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    # Verify user is a member
    role = await _check_member(db, str(org.id), str(current_user.id))

    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "plan": org.plan,
        "monthly_request_limit": org.monthly_request_limit,
        "requests_this_month": org.requests_this_month,
        "member_count": len([m for m in org.members if m.is_active]),
        "your_role": role.value,
        "created_at": org.created_at,
    }


@router.patch("/{slug}")
async def update_org(
    slug: str,
    payload: UpdateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update org details. Requires ADMIN or OWNER role."""
    org = await _get_org_or_404(db, slug)

    try:
        await require_org_role(db, str(org.id), str(current_user.id), OrgMemberRole.ADMIN)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if payload.name is not None:
        org.name = payload.name
    if payload.description is not None:
        org.description = payload.description
    if payload.website is not None:
        org.website = payload.website

    await db.flush()
    return {"message": "Organization updated.", "slug": org.slug}


@router.delete("/{slug}")
async def delete_org(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete (deactivate) organization. OWNER ONLY.

    We soft-delete (is_active=False) to preserve billing history.
    Hard deletion would lose invoice records.
    """
    org = await _get_org_or_404(db, slug)

    try:
        await require_org_role(db, str(org.id), str(current_user.id), OrgMemberRole.OWNER)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    org.is_active = False
    await db.flush()
    return {"message": f"Organization '{org.name}' has been deactivated."}


# ═══════════════════════════════════════════════════════════════════════════════
# MEMBER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{slug}/members")
async def get_members(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all members and their roles.
    Any org member can view the members list.
    """
    org = await _get_org_or_404(db, slug)
    await _check_member(db, str(org.id), str(current_user.id))  # Must be a member

    members = await list_org_members(db, str(org.id))
    return {"members": members, "count": len(members)}


@router.post("/{slug}/members/invite", status_code=201)
async def invite(
    slug: str,
    payload: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Invite a user to join the organization.
    Requires ADMIN or OWNER role.

    This creates an invite token that should be emailed to the recipient.
    The token is valid for 7 days.

    In production, hook this up to SendGrid/SES to send the invite email.

    Test flow:
    1. POST /api/v1/orgs/my-org/members/invite  → get invite_token
    2. POST /api/v1/orgs/invites/<token>/accept  → accept with another account
    """
    org = await _get_org_or_404(db, slug)

    try:
        await require_org_role(db, str(org.id), str(current_user.id), OrgMemberRole.ADMIN)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Can't invite owner role via invite (must be set manually)
    if payload.role == OrgMemberRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot invite someone as owner.")

    try:
        invite_record = await invite_member(
            db=db,
            org_id=str(org.id),
            invited_email=payload.email,
            role=payload.role,
            invited_by=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"Invite sent to {payload.email}",
        "invite_token": invite_record.token,           # In production: this goes via email only
        "invite_url": f"/api/v1/orgs/invites/{invite_record.token}/accept",
        "expires_at": invite_record.expires_at,
        "role": payload.role.value,
    }


@router.post("/invites/{token}/accept")
async def accept_org_invite(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an organization invite using the token from the invite email.

    The accepting user must be logged in and their email must match
    the invite email (security check).
    """
    try:
        membership = await accept_invite(db, token, current_user)
        return {
            "message": "You have joined the organization!",
            "org_id": str(membership.org_id),
            "role": membership.role.value,
            "joined_at": membership.joined_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{slug}/members/{user_id}")
async def change_member_role(
    slug: str,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Change a member's role. Requires ADMIN or OWNER.
    Cannot change the OWNER's role (there must always be one owner).
    """
    org = await _get_org_or_404(db, slug)

    try:
        await require_org_role(db, str(org.id), str(current_user.id), OrgMemberRole.ADMIN)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if payload.role == OrgMemberRole.OWNER:
        raise HTTPException(status_code=400, detail="Use the transfer ownership endpoint instead.")

    success = await update_member_role(db, str(org.id), str(user_id), payload.role)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found.")

    return {"message": f"Role updated to {payload.role.value}"}


@router.delete("/{slug}/members/{user_id}")
async def remove_org_member(
    slug: str,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a member from the organization.
    - ADMIN/OWNER can remove any non-owner member
    - Members can remove themselves (leave the org)
    """
    org = await _get_org_or_404(db, slug)

    # Allow self-removal OR admin removing others
    if str(user_id) != str(current_user.id):
        try:
            await require_org_role(db, str(org.id), str(current_user.id), OrgMemberRole.ADMIN)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))

    success = await remove_member(db, str(org.id), str(user_id))
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not remove member. They may be the owner or not a member.",
        )

    return {"message": "Member removed from organization."}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_org_or_404(db: AsyncSession, slug: str) -> object:
    org = await get_org_by_slug(db, slug)
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization '{slug}' not found.")
    return org


async def _check_member(db: AsyncSession, org_id: str, user_id: str):
    role = await require_org_role.__wrapped__(db, org_id, user_id, OrgMemberRole.VIEWER) \
        if hasattr(require_org_role, '__wrapped__') else None
    # Simpler fallback
    from backend.services.organization_service import get_member_role
    role = await get_member_role(db, org_id, user_id)
    if not role:
        raise HTTPException(status_code=403, detail="You are not a member of this organization.")
    return role
