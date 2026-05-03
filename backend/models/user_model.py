# backend/models/user_model.py
"""
User Model (PostgreSQL Table)
==============================
This defines the 'users' table in PostgreSQL.
Think of a model as the blueprint for your database table.

Real-world: Every SaaS (Stripe, GitHub, Twilio) has a users table
with similar fields: id, email, hashed_password, role, created_at.

NEVER store plain text passwords. Always hash them (bcrypt/argon2).
"""

from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime, timezone

from backend.config.database import Base


class UserRole(str, enum.Enum):
    """
    Role-Based Access Control (RBAC)
    
    Real-world pattern used by: AWS (IAM roles), GitHub, Google Cloud.
    - ADMIN: Can manage all users, view all billing, override limits
    - DEVELOPER: Regular paying customer - creates APIs, tracks usage
    - VIEWER: Read-only access (e.g., a team member who can only see dashboards)
    """
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"

    # ── Primary Key ───────────────────────────────────────────────────────────
    # We use UUID instead of integer IDs for security.
    # Why? Integer IDs (1, 2, 3...) let attackers enumerate users.
    # UUID (550e8400-e29b-41d4...) is unpredictable.
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # ── Identity Fields ───────────────────────────────────────────────────────
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    
    # NEVER store plain passwords! 
    # bcrypt hash looks like: "$2b$12$EixZaYVK1fsbw1ZfbX3OXe..."
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)

    # ── Role & Status ─────────────────────────────────────────────────────────
    role = Column(SAEnum(UserRole), default=UserRole.DEVELOPER, nullable=False)
    is_active = Column(Boolean, default=True)           # Can be deactivated
    is_verified = Column(Boolean, default=False)        # Email verification
    
    # ── Billing Plan ──────────────────────────────────────────────────────────
    plan = Column(String(50), default="free")           # free, starter, pro, enterprise
    monthly_request_limit = Column(Integer, default=10_000)
    requests_this_month = Column(Integer, default=0)

    # ── Timestamps ────────────────────────────────────────────────────────────
    # Always track when records are created and updated. 
    # Essential for debugging and billing disputes.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), 
                       default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships (Foreign Keys) ──────────────────────────────────────────
    # One user can have MANY API keys (one-to-many relationship)
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user")

    def __repr__(self):
        return f"<User {self.email} | Role: {self.role} | Plan: {self.plan}>"
