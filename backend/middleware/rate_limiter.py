# backend/middleware/rate_limiter.py
"""
Rate Limiting Middleware
=========================
This sits in front of ALL requests and enforces usage limits.
If a user sends too many requests, we return 429 Too Many Requests.

Algorithm: Fixed Window Counter (simplest, used by many companies)
- Track: "user_X made N requests in the last 60 seconds"
- If N > limit → reject with 429
- Every 60 seconds, the counter resets

More advanced: Sliding Window, Token Bucket, Leaky Bucket
(These are great interview topics! Mention that Stripe and Cloudflare
use token bucket for smoother rate limiting.)

Real-world: 
- Stripe: 100 req/sec per key
- Twitter API: 300 tweets/3 hours
- OpenAI: 60 req/min on free tier

This middleware stores counts in Redis (in-memory, nanosecond latency).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import time

from backend.config.database import redis_client
from backend.config.settings import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Intercepts every request BEFORE it reaches your route handler.
    
    Middleware stack (order matters!):
    Request → CORSMiddleware → RateLimitMiddleware → Route Handler → Response
    """

    # Paths that bypass rate limiting
    EXCLUDED_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        """
        This method is called for EVERY request.
        
        Args:
            request: The incoming HTTP request
            call_next: Function to pass request to the next handler
        """
        # Skip rate limiting for excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Skip if Redis isn't connected (graceful degradation)
        if not redis_client:
            return await call_next(request)

        # ── Identify the client ───────────────────────────────────────────────
        # Priority: API Key > JWT user ID > IP address
        client_id = self._get_client_identifier(request)
        
        # ── Check Rate Limit ─────────────────────────────────────────────────
        is_allowed, current_count, limit = await self._check_rate_limit(client_id)
        
        if not is_allowed:
            # Return 429 with helpful headers (standard practice)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit: {limit} per minute.",
                    "retry_after": 60,
                },
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + 60),
                    "Retry-After": "60",
                },
            )

        # ── Process request ───────────────────────────────────────────────────
        response = await call_next(request)
        
        # Add rate limit info to response headers (helpful for API consumers)
        remaining = max(0, limit - current_count)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
        
        return response

    def _get_client_identifier(self, request: Request) -> str:
        """
        Determine WHO is making this request.
        
        We use this as the Redis key for counting requests.
        More specific identifier = more accurate per-user limiting.
        """
        # Check for API key in header (most specific)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{api_key[:20]}"  # Use prefix for privacy
        
        # Check for JWT token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_preview = auth_header[7:27]  # First 20 chars
            return f"jwt:{token_preview}"
        
        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")  # Behind proxy/nginx
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"ip:{client_ip}"

    async def _check_rate_limit(
        self, client_id: str, limit: int = None
    ) -> tuple[bool, int, int]:
        """
        Fixed Window Rate Limiting using Redis.
        
        Redis commands used:
        - INCR key      : Increment counter (creates key if missing)
        - EXPIRE key N  : Set key to expire in N seconds
        
        The key expires every 60 seconds, resetting the counter.
        This is the "fixed window" pattern.
        
        Returns: (is_allowed, current_count, limit)
        """
        limit = limit or settings.RATE_LIMIT_PER_MINUTE
        
        # Redis key format: "ratelimit:ip:192.168.1.1" (expires in 60s)
        redis_key = f"ratelimit:{client_id}"
        
        # Use Redis pipeline for atomic operations (prevents race conditions)
        pipe = redis_client.pipeline()
        pipe.incr(redis_key)            # Increment counter
        pipe.expire(redis_key, 60)      # Set 60-second expiry (if not already set)
        results = await pipe.execute()
        
        current_count = results[0]  # Value after increment
        
        is_allowed = current_count <= limit
        return is_allowed, current_count, limit
