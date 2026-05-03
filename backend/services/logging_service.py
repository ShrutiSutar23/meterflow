# backend/services/logging_service.py
"""
Logging Service
================
Query and retrieve API request logs from MongoDB.

MongoDB query patterns used here are very common in analytics:
  - Filter by user, date range, status code, endpoint
  - Paginate results (skip + limit)
  - Aggregate: count errors, sum requests, avg latency

This service is used by:
  - /logs routes: User views their own request history
  - Analytics service: Calculates metrics from raw logs
  - Admin panel: Investigate issues

Real-world: This is exactly how Datadog's log explorer works —
you filter, search, and aggregate millions of log entries.

MongoDB Query Performance Tips:
  1. Always index fields you filter on
  2. Use projections (return only needed fields)
  3. Use aggregation pipeline for complex queries
  4. Create TTL indexes to auto-delete old logs
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.log_model import LOGS_COLLECTION


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create MongoDB indexes for optimal query performance.
    Call this once on startup.

    Without indexes, MongoDB does a full collection scan (slow!).
    With indexes, it jumps directly to matching documents (fast!).

    Real-world: Missing MongoDB indexes are a very common cause
    of production performance issues.
    """
    collection = db[LOGS_COLLECTION]

    # Compound index: most common query is "logs for user X in time range"
    await collection.create_index(
        [("user_id", 1), ("timestamp", -1)],
        name="idx_user_timestamp",
    )
    # Index for API key lookups
    await collection.create_index(
        [("api_key_id", 1), ("timestamp", -1)],
        name="idx_apikey_timestamp",
    )
    # Index for billing aggregations by month
    await collection.create_index(
        [("user_id", 1), ("billing_month", 1)],
        name="idx_user_billing_month",
    )
    # Index for status code filtering (error analysis)
    await collection.create_index("status_code", name="idx_status_code")

    # TTL Index: Auto-delete logs older than 90 days
    # MongoDB's TTL feature deletes documents automatically!
    # Real-world: GDPR/compliance often requires data retention limits.
    await collection.create_index(
        "timestamp",
        name="idx_ttl_90days",
        expireAfterSeconds=90 * 24 * 3600,  # 90 days in seconds
    )

    print("✅ MongoDB indexes created")


async def get_user_logs(
    db: AsyncIOMotorDatabase,
    user_id: str,
    page: int = 1,
    page_size: int = 50,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_code: Optional[int] = None,
    endpoint_filter: Optional[str] = None,
    api_key_id: Optional[str] = None,
) -> dict:
    """
    Retrieve paginated request logs for a user.

    Pagination pattern: skip = (page - 1) * page_size
    Example: page=2, page_size=50 → skip first 50, return next 50

    Returns:
        {
          "logs": [...],
          "total": 1523,
          "page": 2,
          "page_size": 50,
          "total_pages": 31
        }
    """
    # ── Build query filter ────────────────────────────────────────────────────
    query: dict = {"user_id": user_id}

    # Date range filter
    date_filter = {}
    if start_date:
        date_filter["$gte"] = start_date
    if end_date:
        date_filter["$lte"] = end_date
    if date_filter:
        query["timestamp"] = date_filter

    # Optional filters
    if status_code:
        query["status_code"] = status_code
    if endpoint_filter:
        # MongoDB regex search (like SQL LIKE '%pattern%')
        query["endpoint"] = {"$regex": endpoint_filter, "$options": "i"}
    if api_key_id:
        query["api_key_id"] = api_key_id

    # ── Count total matching documents ────────────────────────────────────────
    total = await db[LOGS_COLLECTION].count_documents(query)

    # ── Fetch paginated results ───────────────────────────────────────────────
    skip = (page - 1) * page_size
    cursor = (
        db[LOGS_COLLECTION]
        .find(
            query,
            # Projection: only return these fields (saves bandwidth)
            {
                "_id": 0,
                "request_id": 1,
                "endpoint": 1,
                "method": 1,
                "status_code": 1,
                "response_time_ms": 1,
                "timestamp": 1,
                "is_error": 1,
                "api_key_id": 1,
                "ip_address": 1,
            },
        )
        .sort("timestamp", -1)   # Most recent first
        .skip(skip)
        .limit(page_size)
    )

    logs = await cursor.to_list(length=page_size)

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


async def get_log_detail(
    db: AsyncIOMotorDatabase,
    request_id: str,
    user_id: str,
) -> Optional[dict]:
    """Get full details of a single log entry."""
    doc = await db[LOGS_COLLECTION].find_one(
        {"request_id": request_id, "user_id": user_id},
        {"_id": 0},  # Exclude MongoDB _id
    )
    return doc


async def get_usage_summary(
    db: AsyncIOMotorDatabase,
    user_id: str,
    billing_month: str,  # e.g., "2024-01"
) -> dict:
    """
    Get usage summary for billing purposes.
    Uses MongoDB aggregation pipeline.

    Aggregation pipeline = like SQL GROUP BY + SUM + COUNT.
    MongoDB processes it server-side (very efficient).
    """
    pipeline = [
        # Stage 1: Filter documents
        {
            "$match": {
                "user_id": user_id,
                "billing_month": billing_month,
                "is_billable": True,
            }
        },
        # Stage 2: Group and calculate totals
        {
            "$group": {
                "_id": None,
                "total_requests": {"$sum": 1},
                "total_errors": {"$sum": {"$cond": ["$is_error", 1, 0]}},
                "avg_response_time_ms": {"$avg": "$response_time_ms"},
                "max_response_time_ms": {"$max": "$response_time_ms"},
                "min_response_time_ms": {"$min": "$response_time_ms"},
                "total_data_bytes": {"$sum": "$response_size_bytes"},
            }
        },
        # Stage 3: Shape the output
        {
            "$project": {
                "_id": 0,
                "total_requests": 1,
                "total_errors": 1,
                "error_rate_pct": {
                    "$multiply": [
                        {"$divide": ["$total_errors", {"$max": ["$total_requests", 1]}]},
                        100
                    ]
                },
                "avg_response_time_ms": {"$round": ["$avg_response_time_ms", 1]},
                "max_response_time_ms": 1,
                "min_response_time_ms": 1,
                "total_data_mb": {
                    "$round": [{"$divide": ["$total_data_bytes", 1_048_576]}, 2]
                },
            }
        },
    ]

    results = await db[LOGS_COLLECTION].aggregate(pipeline).to_list(1)
    if not results:
        return {
            "total_requests": 0, "total_errors": 0,
            "error_rate_pct": 0.0, "avg_response_time_ms": 0.0,
            "max_response_time_ms": 0.0, "min_response_time_ms": 0.0,
            "total_data_mb": 0.0,
        }
    return results[0]
