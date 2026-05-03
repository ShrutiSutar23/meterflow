# backend/routes/analytics_routes.py
"""
Analytics Routes
=================
  GET /api/v1/analytics/dashboard    → Full dashboard data (all metrics combined)
  GET /api/v1/analytics/volume       → Request volume over time (chart data)
  GET /api/v1/analytics/latency      → p50/p95/p99 latency
  GET /api/v1/analytics/errors       → Error rate breakdown
  GET /api/v1/analytics/endpoints    → Top endpoints by usage
  GET /api/v1/logs                   → Paginated request logs
  GET /api/v1/logs/{request_id}      → Single log detail

Test with Postman:
  GET http://localhost:8000/api/v1/analytics/dashboard
  Headers: Authorization: Bearer <token>
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from backend.config.database import get_db, get_mongo_db
from backend.services.analytics_service import (
    get_dashboard_summary,
    get_request_volume_over_time,
    get_latency_percentiles,
    get_error_rate_analysis,
    get_top_endpoints,
)
from backend.services.logging_service import get_user_logs, get_log_detail, get_usage_summary
from backend.utils.dependencies import get_current_user
from backend.models.user_model import User


router = APIRouter()


@router.get("/analytics/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """
    Single endpoint that returns ALL dashboard data.
    
    Runs 4 MongoDB aggregations concurrently (asyncio.gather).
    Total time ≈ slowest single query, not sum of all queries.
    
    Real-world: BFF (Backend for Frontend) pattern — 
    one endpoint shaped exactly for the frontend's needs.
    Reduces network round-trips from 4 to 1.
    """
    if mongo is None:
        return {"error": "Analytics database not available"}
    return await get_dashboard_summary(mongo, str(current_user.id))


@router.get("/analytics/volume")
async def get_volume(
    days: int = Query(default=30, ge=1, le=90, description="Number of days to look back"),
    granularity: str = Query(default="day", pattern="^(day|hour)$"),
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """
    Request volume over time for line charts.
    
    Query params:
      ?days=30&granularity=day   → 30 daily data points
      ?days=7&granularity=hour   → 168 hourly data points
    """
    if mongo is None:
        return {"data": []}
    data = await get_request_volume_over_time(mongo, str(current_user.id), days, granularity)
    return {"data": data, "days": days, "granularity": granularity}


@router.get("/analytics/latency")
async def get_latency(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """
    Latency percentiles for the last N hours.
    
    Interview answer when asked about this:
    "We use p99 for SLO monitoring because it captures
    tail latency — the worst experience real users have."
    """
    if mongo is None:
        return {}
    return await get_latency_percentiles(mongo, str(current_user.id), hours)


@router.get("/analytics/errors")
async def get_errors(
    days: int = Query(default=7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """Error rate breakdown by status code."""
    if mongo is None:
        return {}
    return await get_error_rate_analysis(mongo, str(current_user.id), days)


@router.get("/analytics/endpoints")
async def get_endpoints(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """Top endpoints by request count with performance stats."""
    if mongo is None:
        return {"data": []}
    data = await get_top_endpoints(mongo, str(current_user.id), days, limit)
    return {"data": data}


@router.get("/logs")
async def list_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status_code: Optional[int] = None,
    endpoint: Optional[str] = None,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """
    Paginated request log viewer.
    
    Supports filtering by:
      - Date range:   ?start_date=2024-01-01T00:00:00Z
      - Status code:  ?status_code=500
      - Endpoint:     ?endpoint=/api/v1/data
      - API key:      ?api_key_id=<uuid>
    
    Test:
      GET /api/v1/logs?status_code=500&page=1&page_size=20
    """
    if mongo is None:
        return {"logs": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 0}

    return await get_user_logs(
        db=mongo,
        user_id=str(current_user.id),
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        status_code=status_code,
        endpoint_filter=endpoint,
        api_key_id=api_key_id,
    )


@router.get("/logs/{request_id}")
async def get_log(
    request_id: str,
    current_user: User = Depends(get_current_user),
    mongo=Depends(get_mongo_db),
):
    """Get full details of a single request log."""
    if mongo is None:
        return {}
    doc = await get_log_detail(mongo, request_id, str(current_user.id))
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Log not found.")
    return doc
