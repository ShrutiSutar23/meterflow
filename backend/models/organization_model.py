# backend/models/organization_model.py
"""
Multi-Tenancy: Organization Model (Day 10)
============================================
Multi-tenancy means ONE deployment of MeterFlow serves MULTIPLE
independent customers (tenants), each fully isolated from others.

In MeterFlow, each "tenant" is an Organization.

Real-world examples:
  - GitHub: Your company has an "Org" with members + repos
  - Slack:  Your company has a "Workspace"
  - AWS:    Your company has an "Account" with IAM users
  - Stripe: Your company has a "Team" with multiple members

Organization data model:
  Organization
    ├── Members (org_members table) — users with roles inside the org
    ├── API Keys — scoped to the org
    ├── Usage Records — billed to the org, not individual users
    └── Invoices — one invoice per org per month

Tenancy isolation levels (from weakest to strongest):
  1. Row-level (shared DB, org_id column) ← We use this
  2. Schema-level (one schema per tenant)
  3. Database-level (one DB per tenant)

Row-level is used by GitHub, Slack, Linear, Notion.
Database-level is used by Salesforce, enterprise healthcare SaaS.

IMPORTANT: Every query that touches org-owned data MUST filter
by org_id. This is the #1 security requirement in multi-tenancy.
"""

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime, timezone

from backend.config.database import Base


class OrgMemberRole(str, enum.Enum):
    """
    Roles inside an organization (different from global UserRole).

    owner:   Full control — can delete org, manage billing
    admin:   Manage members, API keys, view all usage
    member:  Create/use API keys, view own usage only
    viewer:  Read-only access to dashboards
    billing: Can only see billing/invoices (useful for finance team)
    """
    OWNER   = "owner"
    ADMIN   = "admin"
    MEMBER  = "member"
    VIEWER  = "viewer"
    BILLING = "billing"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    # slug = URL-safe name: "acme-corp" → acme-corp.meterflow.io (future)

    description = Column(String(500), nullable=True)
    logo_url = Column(String(500), nullable=True)
    website = Column(String(255), nullable=True)

    # ── Billing (org-level plan, not user-level) ──────────────────────────────
    plan = Column(String(50), default="free")
    stripe_customer_id = Column(String(255), nullable=True, index=True)
    has_payment_method = Column(Boolean, default=False)
    monthly_request_limit = Column(Integer, default=10_000)
    requests_this_month = Column(Integer, default=0)

    # ── Settings ──────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True)
    max_members = Column(Integer, default=5)    # Limit per plan
    max_api_keys = Column(Integer, default=10)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                       default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ─────────────────────────────────────────────────────────
    members = relationship("OrgMember", back_populates="organization", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Organization {self.slug} | Plan: {self.plan}>"


class OrgMember(Base):
    """
    Junction table between Users and Organizations.
    A user can belong to MULTIPLE organizations (like GitHub).
    Each membership has its own role inside that org.

    Example:
      Alice is OWNER of "Acme Corp" and MEMBER of "Open Source Project"
    """
    __tablename__ = "org_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Foreign Keys ──────────────────────────────────────────────────────────
    org_id  = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)

    # ── Role inside this org ──────────────────────────────────────────────────
    role = Column(SAEnum(OrgMemberRole), default=OrgMemberRole.MEMBER, nullable=False)

    # ── Status ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True)

    # ── Invite tracking ───────────────────────────────────────────────────────
    invited_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    invited_at = Column(DateTime(timezone=True), nullable=True)
    joined_at  = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    organization = relationship("Organization", back_populates="members")

    def __repr__(self):
        return f"<OrgMember user={self.user_id} org={self.org_id} role={self.role}>"


class OrgInvite(Base):
    """
    Pending invitation to join an organization.
    Stores a secure token sent via email.
    Expires after 7 days.
    """
    __tablename__ = "org_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                    nullable=False)
    invited_email = Column(String(255), nullable=False)
    role = Column(SAEnum(OrgMemberRole), default=OrgMemberRole.MEMBER)
    token = Column(String(64), unique=True, nullable=False, index=True)
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
