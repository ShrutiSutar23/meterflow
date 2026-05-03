# backend/models/billing_model.py
"""
Usage Record / Billing Model
==============================
Every API call gets recorded here for billing purposes.
This is the foundation of "usage-based billing" (like AWS, Stripe).

Real-world: AWS charges per API call, per GB transferred, per second of compute.
This table is how they track what you owe at the end of the month.

At month end, we SUM all UsageRecords per user → generate invoice.
"""

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone

from backend.config.database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Who made this request? ────────────────────────────────────────────────
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True, index=True)

    # ── Request Details ───────────────────────────────────────────────────────
    endpoint = Column(String(500), nullable=False)          # Which API endpoint
    method = Column(String(10), nullable=False)             # GET, POST, etc.
    status_code = Column(Integer, nullable=False)           # 200, 404, 500, etc.
    response_time_ms = Column(Float, nullable=True)         # How long it took (ms)
    
    # ── Billing ───────────────────────────────────────────────────────────────
    units_consumed = Column(Integer, default=1)             # 1 request = 1 unit
    cost_usd = Column(Float, default=0.0)                   # Cost of this request
    is_billed = Column(Boolean, default=False)              # Has this been invoiced?
    
    # ── Billing Period ────────────────────────────────────────────────────────
    billing_month = Column(String(7), nullable=False)       # "2024-01" (YYYY-MM)
    
    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), 
                       default=lambda: datetime.now(timezone.utc), 
                       index=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    user = relationship("User", back_populates="usage_records")
    api_key = relationship("APIKey", back_populates="usage_records")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    billing_month = Column(String(7), nullable=False)   # "2024-01"
    total_requests = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    status = Column(String(20), default="pending")      # pending, paid, failed
    
    stripe_invoice_id = Column(String(255), nullable=True)  # Stripe's invoice ID
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime(timezone=True), nullable=True)
