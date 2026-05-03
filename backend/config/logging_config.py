# backend/config/logging_config.py
"""
Structured JSON Logging (Day 12)
===================================
Replaces all print() statements with proper structured logging.

WHY STRUCTURED LOGGING?
  print("User logged in")  ← unstructured, impossible to query/filter
  vs
  logger.info("user.login", extra={"user_id": "abc", "ip": "1.2.3.4"})
  → {"time":"2024-01-15T10:30:00Z","level":"INFO","event":"user.login",
     "user_id":"abc","ip":"1.2.3.4","service":"meterflow","version":"1.0.0"}

Benefits:
  - Machine-parseable: Datadog/CloudWatch/Grafana can query fields
  - Filterable: "show all errors for user X in the last hour"
  - Alertable: "alert if error_rate > 5% in 5 minutes"
  - Traceable: request_id links all logs for a single request

Log levels (use the right one):
  DEBUG    → detailed debugging, disabled in production
  INFO     → normal events: login, key created, invoice generated
  WARNING  → unexpected but handled: rate limit hit, payment failed
  ERROR    → unhandled exceptions, requires investigation
  CRITICAL → system-level failures: DB down, Redis unreachable

Real-world: Every serious company sends JSON logs to a log aggregator.
  Datadog, Splunk, Grafana Loki, AWS CloudWatch all ingest JSON logs.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON.
    Every log entry is a valid JSON object — easy to parse and query.

    Output example:
    {"time":"2024-01-15T10:30:00.123Z","level":"INFO","logger":"meterflow.auth",
     "message":"user.login.success","user_id":"abc123","ip":"192.168.1.1",
     "duration_ms":45.2,"service":"meterflow","env":"production"}
    """

    def __init__(self, service: str = "meterflow", env: str = "development"):
        super().__init__()
        self.service = service
        self.env = env

    def format(self, record: logging.LogRecord) -> str:
        # Base log structure
        log_data: dict[str, Any] = {
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "env": self.env,
        }

        # Add any extra fields passed via extra={...}
        extra_fields = {
            k: v for k, v in record.__dict__.items()
            if k not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }
        }
        log_data.update(extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add source location in DEBUG mode
        if record.levelno == logging.DEBUG:
            log_data["location"] = f"{record.filename}:{record.lineno}"

        return json.dumps(log_data, default=str)


def setup_logging(
    level: str = "INFO",
    service: str = "meterflow",
    env: str = "development",
) -> None:
    """
    Configure the root logger with JSON output.
    Call this once at application startup (in lifespan).

    Args:
        level:   Log level string ("DEBUG", "INFO", "WARNING", "ERROR")
        service: Service name for log identification
        env:     Environment name ("development", "production", "staging")
    """
    # Remove existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Create JSON handler for stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service=service, env=env))

    # Configure root logger
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


# ── Pre-configured loggers for each module ────────────────────────────────────
# Import and use these instead of print() or creating loggers manually.

def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Use module name as convention."""
    return logging.getLogger(f"meterflow.{name}")


# Convenience loggers — import these in each module
auth_logger     = get_logger("auth")
billing_logger  = get_logger("billing")
api_key_logger  = get_logger("apikey")
webhook_logger  = get_logger("webhook")
celery_logger   = get_logger("celery")
db_logger       = get_logger("database")


# ── Usage examples (don't run — just documentation) ───────────────────────────
"""
# In auth_routes.py:
from backend.config.logging_config import auth_logger

auth_logger.info("user.login.success", extra={
    "user_id": str(user.id),
    "email": user.email,
    "ip": request.client.host,
})

auth_logger.warning("user.login.failed", extra={
    "email": payload.email,
    "reason": "invalid_password",
    "ip": request.client.host,
})

# In billing_tasks.py:
from backend.config.logging_config import billing_logger

billing_logger.info("invoice.generated", extra={
    "user_id": user_id,
    "billing_month": billing_month,
    "total_usd": bill["total_cost_usd"],
    "total_requests": total_requests,
})

# In webhook_tasks.py:
from backend.config.logging_config import webhook_logger

webhook_logger.error("webhook.delivery.failed", extra={
    "url": webhook_url,
    "attempt": attempt_number,
    "status_code": response_status,
    "error": str(exc),
})
"""
