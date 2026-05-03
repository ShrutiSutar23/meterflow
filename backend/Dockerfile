# backend/Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# Production Dockerfile for MeterFlow Backend
#
# Multi-stage build:
#   Stage 1 (builder): Install dependencies into a temp layer
#   Stage 2 (runtime): Copy only what's needed — smaller final image
#
# Why multi-stage?
#   - Build tools (gcc, pip, etc.) stay in the builder stage
#   - Final image is smaller and has fewer attack vectors
#   - Used by Google, Netflix, Stripe for all Python services
#
# Build:  docker build -t meterflow-backend .
# Run:    docker run -p 8000:8000 --env-file .env meterflow-backend
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir stripe==8.9.0 sendgrid==6.11.0

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install only runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create non-root user (security best practice)
# Never run production containers as root
RUN useradd -m -u 1001 meterflow && chown -R meterflow:meterflow /app
USER meterflow

# Expose port
EXPOSE 8000

# Health check — Docker will restart the container if this fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Start command
# workers=4: handle 4 concurrent requests (tune based on CPU cores)
# --no-access-log: use our own structured logging instead
CMD ["uvicorn", "main_final:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--no-access-log"]
