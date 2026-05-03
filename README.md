# MeterFlow

MeterFlow is a full-stack usage-based API billing platform. It combines a FastAPI backend, a React dashboard, PostgreSQL billing data, MongoDB request logs, Redis rate limiting, Celery background jobs, Stripe payments, SendGrid email hooks, and Docker-based local/production deployment.

The project is useful as a SaaS backend reference for API key management, metered usage, analytics dashboards, invoices, webhooks, organizations, and role-based access control.

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend API | FastAPI, Uvicorn, Pydantic |
| Frontend | React 18, Vite, React Router, Zustand, Recharts, Axios |
| SQL data | PostgreSQL, SQLAlchemy async, Alembic |
| Log/analytics data | MongoDB, Motor |
| Cache and queues | Redis |
| Background jobs | Celery, Celery Beat |
| Payments | Stripe |
| Email | SendGrid REST API through HTTPX |
| Deployment | Docker Compose, Nginx |
| Tests | Pytest, pytest-asyncio |

## Main Features

- JWT authentication with access and refresh tokens.
- Password reset, email verification, logout, and token blacklist support.
- Stripe-style API keys stored as SHA-256 hashes, with full key shown only once.
- Fixed-window Redis rate limiting.
- Request logging middleware that writes API request logs to MongoDB.
- Usage records and invoice generation for usage-based billing.
- Analytics endpoints for dashboard KPIs, volume, latency, errors, endpoints, and logs.
- Stripe payment method, charge, refund, and inbound webhook routes.
- User-managed outbound webhooks.
- Organization and member management for multi-tenant workflows.
- React dashboard pages for login/signup, metrics, API keys, billing, and logs.

## Repository Layout

```text
meterflow/
  backend/
    main.py                    FastAPI app entry point
    config/                    settings, database clients, logging, Celery app
    routes/                    HTTP route handlers
    services/                  business logic
    models/                    SQLAlchemy and Mongo/Pydantic data models
    middleware/                rate limiting and request logging
    tasks/                     Celery background tasks
    controllers/schemas.py     Pydantic request/response schemas
    alembic/                   database migrations
    tests/                     backend tests
    scripts/                   utility scripts
  frontend/
    src/App.jsx                routes and protected layout
    src/pages/                 dashboard pages
    src/services/axios.js      API client and token refresh
    src/store/authStore.js     Zustand auth state
  nginx/nginx.conf             production reverse proxy
  docker-compose.yml           local databases and Redis UI
  docker-compose.prod.yml      production stack
  docs/                        project documentation
```

## Quick Start

### 1. Start infrastructure

```bash
docker-compose up -d
```

This starts PostgreSQL, MongoDB, Redis, and Redis Commander.

### 2. Configure the backend

Create `backend/.env` from the documented values in [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

For local Docker defaults, the important values are:

```env
POSTGRES_URL=postgresql+asyncpg://meterflow_user:your_password@localhost:5432/meterflow_db
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=meterflow_logs
REDIS_URL=redis://localhost:6379
JWT_SECRET_KEY=replace-with-a-long-random-secret
```

### 3. Install and run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
cd ..
uvicorn backend.main:app --reload
```

Run Uvicorn from the repository root because the code imports modules with the `backend.*` package path:

```bash
uvicorn backend.main:app --reload
```

### 4. Start background workers

Run these in separate terminals from the repository root:

```bash
celery -A backend.config.celery_app worker --loglevel=info
celery -A backend.config.celery_app beat --loglevel=info
```

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend reads `VITE_API_URL`; use `http://localhost:8000/api/v1` during local development if the Vite proxy is not configured.

## Useful URLs

| Service | URL |
| --- | --- |
| Backend root | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health check | http://localhost:8000/health |
| Frontend | http://localhost:5173 |
| Redis Commander | http://localhost:8081 |

## Common API Flow

1. `POST /api/v1/auth/signup` creates a user.
2. `POST /api/v1/auth/login` returns access and refresh tokens.
3. `GET /api/v1/auth/me` validates the bearer token.
4. `POST /api/v1/keys/` creates an API key.
5. `GET /api/v1/keys/` lists API key metadata.
6. `POST /api/v1/playground/run` simulates a metered API request.
7. `GET /api/v1/billing/summary` shows current usage and projected billing.
8. `GET /api/v1/analytics/dashboard` returns dashboard metrics.
9. `GET /api/v1/logs` returns request logs.

See [docs/API.md](docs/API.md) for the full endpoint map.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [Environment Variables](docs/ENVIRONMENT.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Testing Guide](docs/TESTING.md)

## Testing

Backend tests live in `backend/tests`.

```bash
cd backend
pytest
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Notes

- Do not commit real `.env` files or secrets.
- API keys are intentionally unrecoverable after creation because only their hash is stored.
- The current local Docker compose file exposes database ports for developer convenience. The production compose file keeps databases internal.
- MongoDB logs are intended for analytics and debugging; PostgreSQL remains the source of truth for users, API keys, usage records, invoices, and organizations.
