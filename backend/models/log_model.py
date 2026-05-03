# backend/models/log_model.py
"""
API Request Log Model (MongoDB)
================================
Every single API request gets logged here.
This is NOT a SQLAlchemy model - it's a plain Python dataclass
because MongoDB is schema-less (no fixed columns).

Why MongoDB for logs?
  - High write volume: millions of logs per day
  - Schema flexibility: each log can have different metadata
  - No JOINs needed: logs are self-contained documents
  - TTL indexes: MongoDB can auto-delete old logs after 90 days

Real-world: Datadog, New Relic, AWS CloudWatch all use similar
document-based storage for logs and metrics.

A single log document looks like this in MongoDB:
{
  "_id": ObjectId("..."),
  "request_id": "uuid",
  "user_id": "uuid",
  "api_key_id": "uuid",
  "endpoint": "/api/v1/data/fetch",
  "method": "POST",
  "status_code": 200,
  "response_time_ms": 42.5,
  "request_size_bytes": 256,
  "response_size_bytes": 1024,
  "ip_address": "192.168.1.1",
  "user_agent": "curl/7.68.0",
  "error_message": null,
  "metadata": { "region": "us-east-1", "version": "v2" },
  "timestamp": ISODate("2024-01-15T10:30:00Z"),
  "billing_month": "2024-01"
}
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid


class APIRequestLog(BaseModel):
    """
    Represents one API request log entry stored in MongoDB.
    Pydantic handles serialization/deserialization to/from MongoDB documents.
    """

    # ── Identifiers ───────────────────────────────────────────────────────────
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None           # Who made the request (if authenticated)
    api_key_id: Optional[str] = None        # Which API key was used

    # ── Request Details ───────────────────────────────────────────────────────
    endpoint: str                           # e.g., "/api/v1/data/fetch"
    method: str                             # GET, POST, PUT, DELETE, PATCH
    status_code: int                        # HTTP status: 200, 404, 500...
    response_time_ms: float = 0.0           # Latency in milliseconds
    request_size_bytes: int = 0             # Size of request body
    response_size_bytes: int = 0            # Size of response body

    # ── Client Info ───────────────────────────────────────────────────────────
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    country_code: Optional[str] = None     # For geo-analytics (future)

    # ── Error Tracking ────────────────────────────────────────────────────────
    is_error: bool = False
    error_message: Optional[str] = None
    error_type: Optional[str] = None        # e.g., "ValidationError", "AuthError"

    # ── Billing ───────────────────────────────────────────────────────────────
    billing_month: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m")
    )
    is_billable: bool = True                # False for health checks, docs, etc.

    # ── Flexible Metadata ────────────────────────────────────────────────────
    # Store any extra context - great for debugging specific issues
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ── Timestamp ─────────────────────────────────────────────────────────────
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo_doc(self) -> dict:
        """Convert to a MongoDB-compatible dictionary."""
        doc = self.model_dump()
        # Convert datetime to proper format for MongoDB
        doc["timestamp"] = self.timestamp
        return doc

    @classmethod
    def from_mongo_doc(cls, doc: dict) -> "APIRequestLog":
        """Create an instance from a MongoDB document."""
        doc.pop("_id", None)  # Remove MongoDB's internal _id field
        return cls(**doc)


# ── MongoDB Collection Names ───────────────────────────────────────────────────
LOGS_COLLECTION = "api_request_logs"
METRICS_COLLECTION = "api_metrics_hourly"  # Pre-aggregated hourly metrics (Day 5)
