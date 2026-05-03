# backend/services/organization_service.py
"""
Organization (Multi-Tenancy) Service (Day 10)
===============================================
Handles all business logic for organizations:
  - Create / update / delete org
  - Invite members via email token
  - Accept / decline invitations
  - Change member roles
  - Remove members
  - Check permissions (is user an admin of this org?)

TENANT ISOLATION RULE:
  Every query on org-owned data MUST include an org_id filter.
  Never return data from another org — that's a data breach.

  BAD:  SELECT * FROM api_keys WHERE user_id = $user_id
  GOOD: SELECT * FROM api_keys WHERE user_id = $user_id AND org_id = $org_id

Permission matrix:
  Action                owner  admin  member  viewer  billing
  ─────────────────────────────────────────────────────────────
  Delete org              ✓
  Change billing          ✓
  Manage members          ✓      ✓
  Manage API keys         ✓      ✓       ✓
  View all usage          ✓      ✓       ✓       ✓
  View billing/invoices   ✓      ✓                       ✓
  Use API keys            ✓      ✓       ✓
"""

import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, delete
from sqlalchemy.orm import selectinload

from backend.models.organization_model import Organization, OrgMember, OrgInvite, OrgMemberRole
from backend.models.user_model import User


# ═══════════════════════════════════════════════════════════════════════════════
# ORGANIZATION CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def create_organization(
    db: AsyncSession,
    name: str,
    slug: str,
    owner: User,
    description: str = None,
) -> Organization:
    """
    Create a new organization and make the creator the OWNER.

    Steps:
    1. Check slug is unique (like GitHub username)
    2. Create Organization record
    3. Create OrgMember record with OWNER role
    4. Return org

    Slug rules: lowercase, alphanumeric + hyphens, 3–50 chars
    Example: "Acme Corp" → slug "acme-corp"
    """
    # Check slug uniqueness
    existing = await db.execute(
        select(Organization).where(Organization.slug == slug.lower())
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Slug '{slug}' is already taken.")

    org = Organization(
        name=name,
        slug=slug.lower(),
        description=description,
    )
    db.add(org)
    await db.flush()  # Get the org.id

    # Make creator the owner
    membership = OrgMember(
        org_id=org.id,
        user_id=owner.id,
        role=OrgMemberRole.OWNER,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(membership)
    await db.flush()
    await db.refresh(org)

    return org


async def get_org_by_slug(db: AsyncSession, slug: str) -> Optional[Organization]:
    result = await db.execute(
        select(Organization)
        .where(Organization.slug == slug, Organization.is_active == True)
        .options(selectinload(Organization.members))
    )
    return result.scalar_one_or_none()


async def get_user_orgs(db: AsyncSession, user_id: str) -> List[dict]:
    """
    Get all organizations a user belongs to, with their role in each.

    Returns:
    [
      {"org": {...}, "role": "owner", "joined_at": "..."},
      {"org": {...}, "role": "member", "joined_at": "..."},
    ]
    """
    result = await db.execute(
        select(OrgMember, Organization)
        .join(Organization, OrgMember.org_id == Organization.id)
        .where(
            OrgMember.user_id == user_id,
            OrgMember.is_active == True,
            Organization.is_active == True,
        )
        .order_by(OrgMember.joined_at.desc())
    )
    rows = result.all()

    return [
        {
            "org_id": str(member.org_id),
            "org_name": org.name,
            "org_slug": org.slug,
            "role": member.role.value,
            "joined_at": member.joined_at,
            "plan": org.plan,
        }
        for member, org in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION CHECKING
# ═══════════════════════════════════════════════════════════════════════════════

async def get_member_role(
    db: AsyncSession, org_id: str, user_id: str
) -> Optional[OrgMemberRole]:
    """Get a user's role in an org. Returns None if not a member."""
    result = await db.execute(
        select(OrgMember.role)
        .where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
            OrgMember.is_active == True,
        )
    )
    row = result.scalar_one_or_none()
    return row


async def require_org_role(
    db: AsyncSession,
    org_id: str,
    user_id: str,
    minimum_role: OrgMemberRole,
) -> OrgMemberRole:
    """
    Check user has at least the required role in the org.
    Raises PermissionError if not.

    Role hierarchy (strongest → weakest):
    OWNER > ADMIN > MEMBER > VIEWER / BILLING

    Usage:
        await require_org_role(db, org_id, user.id, OrgMemberRole.ADMIN)
        # Raises if user is not at least an admin
    """
    ROLE_HIERARCHY = {
        OrgMemberRole.OWNER:   5,
        OrgMemberRole.ADMIN:   4,
        OrgMemberRole.MEMBER:  3,
        OrgMemberRole.VIEWER:  2,
        OrgMemberRole.BILLING: 2,
    }

    user_role = await get_member_role(db, org_id, user_id)
    if not user_role:
        raise PermissionError("You are not a member of this organization.")

    if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY.get(minimum_role, 0):
        raise PermissionError(
            f"This action requires {minimum_role.value} role. Your role: {user_role.value}"
        )
    return user_role


# ═══════════════════════════════════════════════════════════════════════════════
# MEMBER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

async def invite_member(
    db: AsyncSession,
    org_id: str,
    invited_email: str,
    role: OrgMemberRole,
    invited_by: User,
) -> OrgInvite:
    """
    Send an invite to join the organization.

    Generates a secure random token and stores it.
    The invite link is: https://app.meterflow.io/invite/<token>

    In production, send this link via email (SendGrid/SES).
    The invite expires in 7 days.

    Real-world: GitHub, Slack, Notion all use this exact flow.
    """
    # Check org member limit
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise ValueError("Organization not found.")

    member_count_result = await db.execute(
        select(OrgMember)
        .where(OrgMember.org_id == org_id, OrgMember.is_active == True)
    )
    current_count = len(member_count_result.scalars().all())

    if current_count >= org.max_members:
        raise ValueError(
            f"Organization has reached its member limit ({org.max_members}). "
            "Upgrade your plan to add more members."
        )

    # Generate secure invite token
    token = secrets.token_urlsafe(32)

    invite = OrgInvite(
        org_id=org_id,
        invited_email=invited_email.lower(),
        role=role,
        token=token,
        invited_by=invited_by.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)

    # TODO Day 11: Send invite email via SendGrid
    # await send_invite_email(invited_email, org.name, token, invited_by.username)

    return invite


async def accept_invite(
    db: AsyncSession,
    token: str,
    user: User,
) -> OrgMember:
    """
    Accept an organization invitation using the secure token.

    Steps:
    1. Find invite by token
    2. Verify not expired or already used
    3. Check the accepting user's email matches the invite email
    4. Create OrgMember record
    5. Mark invite as used
    """
    result = await db.execute(
        select(OrgInvite)
        .where(
            OrgInvite.token == token,
            OrgInvite.is_used == False,
            OrgInvite.expires_at > datetime.now(timezone.utc),
        )
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise ValueError("Invite not found, already used, or expired.")

    if invite.invited_email != user.email:
        raise ValueError(
            "This invite was sent to a different email address. "
            "Please sign in with the invited email."
        )

    # Check if already a member
    existing_member = await get_member_role(db, str(invite.org_id), str(user.id))
    if existing_member:
        raise ValueError("You are already a member of this organization.")

    # Create membership
    membership = OrgMember(
        org_id=invite.org_id,
        user_id=user.id,
        role=invite.role,
        invited_by_user_id=invite.invited_by,
        invited_at=invite.created_at,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(membership)

    # Mark invite as used
    invite.is_used = True
    invite.accepted_at = datetime.now(timezone.utc)

    await db.flush()
    return membership


async def update_member_role(
    db: AsyncSession,
    org_id: str,
    target_user_id: str,
    new_role: OrgMemberRole,
) -> bool:
    """Change a member's role in the org."""
    result = await db.execute(
        update(OrgMember)
        .where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == target_user_id,
        )
        .values(role=new_role)
    )
    return result.rowcount > 0


async def remove_member(
    db: AsyncSession,
    org_id: str,
    target_user_id: str,
) -> bool:
    """Remove a member from the org (soft delete)."""
    result = await db.execute(
        update(OrgMember)
        .where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == target_user_id,
            OrgMember.role != OrgMemberRole.OWNER,  # Can't remove owner
        )
        .values(is_active=False)
    )
    return result.rowcount > 0


async def list_org_members(db: AsyncSession, org_id: str) -> List[dict]:
    """List all members of an organization with their user details."""
    result = await db.execute(
        select(OrgMember, User)
        .join(User, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org_id, OrgMember.is_active == True)
        .order_by(OrgMember.joined_at.asc())
    )
    rows = result.all()
    return [
        {
            "user_id": str(member.user_id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": member.role.value,
            "joined_at": member.joined_at,
        }
        for member, user in rows
    ]
