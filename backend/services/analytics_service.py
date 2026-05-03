# backend/services/analytics_service.py
"""
Analytics Service (Day 5)
==========================
Generates all the metrics shown on the dashboard:
  - Request volume over time (line chart)
  - Latency percentiles: p50, p95, p99
  - Error rate percentage
  - Top endpoints by request count
  - Status code distribution
  - Hourly request heatmap

This uses MongoDB's Aggregation Pipeline — a powerful way to
process large amounts of data server-side.

Aggregation Pipeline = like a SQL query with GROUP BY, HAVING,
ORDER BY, but expressed as a series of transformation stages.

Real-world: Datadog, Grafana, New Relic all do this kind of
pre-aggregation on the fly or via materialized views.

Interview topic: "How do you calculate p99 latency?"
  Answer: Sort all response times, take the value at the 99th
  percentile. MongoDB's $percentile operator does this natively.
  For real-time systems, use HdrHistogram or t-digest algorithms
  (used by Prometheus, Datadog).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.log_model import LOGS_COLLECTION


async def get_request_volume_over_time(
    db: AsyncIOMotorDatabase,
    user_id: str,
    days: int = 30,
    granularity: str = "day",  # "hour", "day"
) -> list[dict]:
    """
    Request count per time period.
    Powers the main line chart on the dashboard.

    Example output:
    [
      {"period": "2024-01-01", "total": 4523, "errors": 12},
      {"period": "2024-01-02", "total": 5102, "errors": 8},
      ...
    ]
    """
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # MongoDB date grouping format
    if granularity == "hour":
        date_format = "%Y-%m-%d %H:00"
        date_trunc = {
            "year": {"$year": "$timestamp"},
            "month": {"$month": "$timestamp"},
            "day": {"$dayOfMonth": "$timestamp"},
            "hour": {"$hour": "$timestamp"},
        }
    else:  # day
        date_format = "%Y-%m-%d"
        date_trunc = {
            "year": {"$year": "$timestamp"},
            "month": {"$month": "$timestamp"},
            "day": {"$dayOfMonth": "$timestamp"},
        }

    pipeline = [
        # Filter: this user's logs in the time range
        {"$match": {
            "user_id": user_id,
            "timestamp": {"$gte": start_date},
            "is_billable": True,
        }},
        # Group by time period
        {"$group": {
            "_id": date_trunc,
            "total": {"$sum": 1},
            "errors": {"$sum": {"$cond": ["$is_error", 1, 0]}},
            "avg_latency": {"$avg": "$response_time_ms"},
        }},
        # Sort chronologically
        {"$sort": {"_id": 1}},
        # Reshape output
        {"$project": {
            "_id": 0,
            "period": {
                "$dateToString": {
                    "format": date_format,
                    "date": {
                        "$dateFromParts": "_id"
                    }
                }
            },
            "total": 1,
            "errors": 1,
            "avg_latency": {"$round": ["$avg_latency", 1]},
        }},
    ]

    # Simpler date formatting fallback
    pipeline_simple = [
        {"$match": {
            "user_id": user_id,
            "timestamp": {"$gte": start_date},
            "is_billable": True,
        }},
        {"$addFields": {
            "day": {
                "$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}
            }
        }},
        {"$group": {
            "_id": "$day",
            "total": {"$sum": 1},
            "errors": {"$sum": {"$cond": ["$is_error", 1, 0]}},
            "avg_latency": {"$avg": "$response_time_ms"},
        }},
        {"$sort": {"_id": 1}},
        {"$project": {
            "_id": 0,
            "period": "$_id",
            "total": 1,
            "errors": 1,
            "avg_latency": {"$round": ["$avg_latency", 1]},
        }},
    ]

    results = await db[LOGS_COLLECTION].aggregate(pipeline_simple).to_list(1000)
    return results


async def get_latency_percentiles(
    db: AsyncIOMotorDatabase,
    user_id: str,
    hours: int = 24,
) -> dict:
    """
    Calculate p50, p95, p99 latency for the last N hours.

    Why percentiles matter (real interview answer):
      - Average (mean) can be misleading. 
      - If 99% of requests take 10ms but 1% take 10,000ms,
        the average looks fine but users are experiencing timeouts.
      - p99 = "99% of requests are faster than this value"
      - SLOs (Service Level Objectives) are set using percentiles:
        Google's SRE book uses p99 < 200ms as a common target.

    MongoDB's $percentile operator (v5.0+):
      Calculates percentiles natively in the aggregation pipeline.
    """
    start = datetime.now(timezone.utc) - timedelta(hours=hours)

    pipeline = [
        {"$match": {
            "user_id": user_id,
            "timestamp": {"$gte": start},
            "response_time_ms": {"$exists": True, "$gt": 0},
        }},
        {"$group": {
            "_id": None,
            "p50": {"$percentile": {"input": "$response_time_ms", "p": [0.50], "method": "approximate"}},
            "p95": {"$percentile": {"input": "$response_time_ms", "p": [0.95], "method": "approximate"}},
            "p99": {"$percentile": {"input": "$response_time_ms", "p": [0.99], "method": "approximate"}},
            "avg": {"$avg": "$response_time_ms"},
            "max": {"$max": "$response_time_ms"},
            "count": {"$sum": 1},
        }},
    ]

    try:
        results = await db[LOGS_COLLECTION].aggregate(pipeline).to_list(1)
        if results:
            r = results[0]
            return {
                "p50_ms": round(r["p50"][0], 1) if r.get("p50") else 0,
                "p95_ms": round(r["p95"][0], 1) if r.get("p95") else 0,
                "p99_ms": round(r["p99"][0], 1) if r.get("p99") else 0,
                "avg_ms": round(r.get("avg", 0), 1),
                "max_ms": round(r.get("max", 0), 1),
                "sample_count": r.get("count", 0),
                "window_hours": hours,
            }
    except Exception:
        # MongoDB < 5.0 fallback: manual percentile calculation
        return await _fallback_percentiles(db, user_id, start)

    return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "avg_ms": 0, "max_ms": 0, "sample_count": 0}


async def _fallback_percentiles(db, user_id, start) -> dict:
    """Fallback for older MongoDB: fetch all latencies and sort in Python."""
    cursor = db[LOGS_COLLECTION].find(
        {"user_id": user_id, "timestamp": {"$gte": start}, "response_time_ms": {"$gt": 0}},
        {"response_time_ms": 1, "_id": 0},
    ).sort("response_time_ms", 1)

    docs = await cursor.to_list(10000)
    if not docs:
        return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "avg_ms": 0, "max_ms": 0, "sample_count": 0}

    latencies = sorted(d["response_time_ms"] for d in docs)
    n = len(latencies)

    def percentile(pct):
        idx = int(n * pct)
        return round(latencies[min(idx, n - 1)], 1)

    return {
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "avg_ms": round(sum(latencies) / n, 1),
        "max_ms": round(latencies[-1], 1),
        "sample_count": n,
        "window_hours": 24,
    }


async def get_error_rate_analysis(
    db: AsyncIOMotorDatabase,
    user_id: str,
    days: int = 7,
) -> dict:
    """
    Error rate breakdown by status code.

    Returns:
    {
      "overall_error_rate_pct": 2.3,
      "total_requests": 10000,
      "total_errors": 230,
      "by_status_code": {
        "400": 120,
        "401": 30,
        "404": 50,
        "500": 30
      },
      "4xx_count": 200,
      "5xx_count": 30
    }
    """
    start = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = [
        {"$match": {
            "user_id": user_id,
            "timestamp": {"$gte": start},
        }},
        {"$group": {
            "_id": "$status_code",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]

    results = await db[LOGS_COLLECTION].aggregate(pipeline).to_list(100)

    total = sum(r["count"] for r in results)
    errors = sum(r["count"] for r in results if r["_id"] >= 400)
    client_errors = sum(r["count"] for r in results if 400 <= r["_id"] < 500)
    server_errors = sum(r["count"] for r in results if r["_id"] >= 500)

    by_code = {str(r["_id"]): r["count"] for r in results if r["_id"] >= 400}

    return {
        "overall_error_rate_pct": round(errors / max(total, 1) * 100, 2),
        "total_requests": total,
        "total_errors": errors,
        "4xx_count": client_errors,
        "5xx_count": server_errors,
        "by_status_code": by_code,
        "window_days": days,
    }


async def get_top_endpoints(
    db: AsyncIOMotorDatabase,
    user_id: str,
    days: int = 7,
    limit: int = 10,
) -> list[dict]:
    """
    Top N most-called endpoints with their performance stats.

    Example output:
    [
      {"endpoint": "/api/v1/data/fetch", "method": "POST",
       "count": 4523, "avg_latency": 45.2, "error_rate_pct": 0.5},
      ...
    ]
    """
    start = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = [
        {"$match": {
            "user_id": user_id,
            "timestamp": {"$gte": start},
        }},
        {"$group": {
            "_id": {"endpoint": "$endpoint", "method": "$method"},
            "count": {"$sum": 1},
            "errors": {"$sum": {"$cond": ["$is_error", 1, 0]}},
            "avg_latency": {"$avg": "$response_time_ms"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {
            "_id": 0,
            "endpoint": "$_id.endpoint",
            "method": "$_id.method",
            "count": 1,
            "errors": 1,
            "avg_latency_ms": {"$round": ["$avg_latency", 1]},
            "error_rate_pct": {
                "$round": [
                    {"$multiply": [
                        {"$divide": ["$errors", {"$max": ["$count", 1]}]},
                        100
                    ]},
                    2
                ]
            },
        }},
    ]

    return await db[LOGS_COLLECTION].aggregate(pipeline).to_list(limit)


async def get_dashboard_summary(
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> dict:
    """
    One-call endpoint that returns ALL data needed for the dashboard.
    Reduces the number of round-trips from frontend to backend.

    Returns everything the dashboard needs in a single response.
    """
    # Run all queries concurrently using asyncio.gather
    import asyncio

    volume, latency, errors, top_endpoints = await asyncio.gather(
        get_request_volume_over_time(db, user_id, days=30),
        get_latency_percentiles(db, user_id, hours=24),
        get_error_rate_analysis(db, user_id, days=7),
        get_top_endpoints(db, user_id, days=7),
    )

    return {
        "volume_30d": volume,
        "latency_24h": latency,
        "errors_7d": errors,
        "top_endpoints_7d": top_endpoints,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
