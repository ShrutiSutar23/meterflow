# backend/models/apikey_model.py
"""
API Key Model
==============
This is how customers authenticate to USE your APIs.
Think of it like a physical key - it unlocks access to your service.



Security rules (industry standard):
1. Never store the raw key in the database
2. Store a HASH of the key (like passwords)
3. Show the full key ONCE to the user, then never again
4. Prefix the key so users know which service it's for (mf_ = MeterFlow)
"""

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone

from backend.config.database import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # ── Foreign Key: Who owns this key? ──────────────────────────────────────
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                     nullable=False, index=True)

    # ── Key Storage ───────────────────────────────────────────────────────────
    # key_prefix: First 8 chars shown in UI (e.g., "mf_live_")
    # Used so users can identify which key they're looking at
    key_prefix = Column(String(20), nullable=False)     # e.g., "mf_live_ab"
    
    # key_hash: SHA-256 hash of the full key. We verify by hashing incoming requests.
    # This way even if DB is breached, attacker can't use the keys.
    key_hash = Column(String(64), nullable=False, unique=True, index=True)

    # ── Metadata ─────────────────────────────────────────────────────────────
    name = Column(String(255), nullable=False)          # User-given name: "Production Key"
    description = Column(String(500), nullable=True)    # Optional notes
    environment = Column(String(20), default="live")    # "live" or "test"
    
    # ── Rate Limiting (per-key limits) ────────────────────────────────────────
    # Each key can have different limits (e.g., a test key has lower limits)
    rate_limit_per_minute = Column(Integer, default=60)
    rate_limit_per_day = Column(Integer, default=10_000)
    
    # ── Permissions (Scopes) ─────────────────────────────────────────────────
    # Like OAuth scopes - what can this key do?
    # Example: ["read:usage", "write:data", "admin:billing"]
    scopes = Column(JSON, default=list)

    # ── Status ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Optional expiry
    
    # ── Usage Stats ───────────────────────────────────────────────────────────
    total_requests = Column(Integer, default=0)         # Lifetime request count

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                       default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ─────────────────────────────────────────────────────────
    user = relationship("User", back_populates="api_keys")
    usage_records = relationship("UsageRecord", back_populates="api_key")

    def __repr__(self):
        return f"<APIKey {self.key_prefix}... | User: {self.user_id} | Active: {self.is_active}>"
