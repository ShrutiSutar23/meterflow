# backend/middleware/request_logger.py
"""
Request Logging Middleware
============================
This middleware wraps EVERY request and automatically:
  1. Records start time
  2. Lets the request process normally
  3. Records end time → calculates latency
  4. Extracts user identity (from JWT or API key)
  5. Sends log to MongoDB asynchronously (via Celery task)

KEY DESIGN DECISION: We log ASYNCHRONOUSLY.
  - If we logged synchronously (waiting for MongoDB write),
    every request would be ~5-20ms slower.
  - Instead, we fire-and-forget to Celery → user gets response
    immediately, log is written in the background.

Real-world: This is exactly how Datadog APM, AWS X-Ray,
and Google Cloud Trace work — they intercept requests at the
middleware layer and send telemetry asynchronously.

Timeline of a request:
  Incoming Request
       ↓
  [RateLimitMiddleware]  ← checks Redis (Day 1-2)
       ↓
  [RequestLoggerMiddleware]  ← starts timer ← (this file)
       ↓
  Route Handler  ← your actual business logic
       ↓
  [RequestLoggerMiddleware]  ← stops timer, sends log to Celery
       ↓
  Response sent to client
"""

import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.models.log_model import APIRequestLog


# Paths we never log (health checks, docs, static files)
NON_BILLABLE_PATHS = {
    "/health", "/", "/docs", "/redoc",
    "/openapi.json", "/favicon.ico",
}


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """
    Intercepts every HTTP request to log it.

    The logging itself is non-blocking — we schedule it as a
    background Celery task after the response is sent.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip logging for non-billable paths
        if request.url.path in NON_BILLABLE_PATHS:
            return await call_next(request)

        # ── Start timer ───────────────────────────────────────────────────────
        start_time = time.perf_counter()           # High-precision timer
        request_id = str(uuid.uuid4())

        # Attach request_id so route handlers can reference it
        request.state.request_id = request_id

        # ── Get request size ─────────────────────────────────────────────────
        content_length = request.headers.get("content-length", "0")
        request_size = int(content_length) if content_length.isdigit() else 0

        # ── Process the actual request ────────────────────────────────────────
        response = await call_next(request)

        # ── Calculate latency ────────────────────────────────────────────────
        duration_ms = (time.perf_counter() - start_time) * 1000  # Convert to ms

        # ── Extract identity ─────────────────────────────────────────────────
        user_id, api_key_id = self._extract_identity(request)

        # ── Determine response size ───────────────────────────────────────────
        response_size = int(response.headers.get("content-length", 0))

        # ── Build log entry ───────────────────────────────────────────────────
        is_error = response.status_code >= 400
        is_billable = (
            request.url.path not in NON_BILLABLE_PATHS
            and response.status_code < 500   # Server errors don't bill users
        )

        log_entry = APIRequestLog(
            request_id=request_id,
            user_id=user_id,
            api_key_id=api_key_id,
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            response_time_ms=round(duration_ms, 2),
            request_size_bytes=request_size,
            response_size_bytes=response_size,
            ip_address=self._get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            is_error=is_error,
            error_message=response.headers.get("X-Error-Message"),
            is_billable=is_billable,
            metadata={
                "query_params": dict(request.query_params),
                "host": request.headers.get("host"),
            },
        )

        # ── Send to background task (non-blocking) ────────────────────────────
        # Import here to avoid circular imports
        try:
            from backend.tasks.log_tasks import save_request_log
            # .delay() sends the task to Celery's Redis queue
            # The current request is NOT blocked waiting for this
            save_request_log.delay(log_entry.to_mongo_doc())
        except Exception:
            # Never let logging failures break the actual request
            pass

        # ── Add useful debug headers to response ──────────────────────────────
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"

        return response

    def _extract_identity(self, request: Request) -> tuple[Optional[str], Optional[str]]:
        """
        Try to find who made this request.
        We check request.state which may have been set by auth middleware.
        """
        user_id = getattr(request.state, "user_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)
        return user_id, api_key_id

    def _get_client_ip(self, request: Request) -> str:
        """
        Get the real client IP address.
        Behind a proxy/load balancer, the real IP is in X-Forwarded-For header.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
