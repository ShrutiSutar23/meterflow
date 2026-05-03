# Architecture

MeterFlow is split into four runtime layers: frontend, API backend, data stores, and background workers.

## Runtime Components

```text
Browser
  |
  | React dashboard, Axios, JWT bearer token
  v
FastAPI backend
  |
  |-- PostgreSQL: users, API keys, usage records, invoices, organizations
  |-- MongoDB: request logs and analytics collections
  |-- Redis: rate limiting, token blacklist, Celery broker/result backend
  |
  v
Celery workers and beat scheduler
```

In production, Nginx sits in front of FastAPI as the reverse proxy and SSL termination layer.

## Backend Design

The backend follows a route/service/model shape:

- `backend/main.py` creates the FastAPI app, registers middleware, includes routers, and manages startup/shutdown.
- `backend/routes/` contains HTTP endpoint handlers. Routes should stay thin and delegate business decisions.
- `backend/services/` contains domain logic for auth, API keys, billing, analytics, organizations, Stripe, email, logging, and webhooks.
- `backend/models/` contains SQLAlchemy models for PostgreSQL and Pydantic models for MongoDB documents.
- `backend/controllers/schemas.py` contains request and response schemas.
- `backend/utils/dependencies.py` contains reusable FastAPI dependencies for authentication and authorization.
- `backend/middleware/` contains cross-cutting request handling.

## Data Model Summary

PostgreSQL stores relational source-of-truth data:

| Table | Purpose |
| --- | --- |
| `users` | Account identity, role, plan, verification, payment metadata |
| `api_keys` | Hashed API keys, scopes, limits, status, usage counters |
| `usage_records` | Per-request billable usage records |
| `invoices` | Monthly billing summaries |
| `organizations` | Tenant/workspace records |
| `org_members` | User membership and organization role |
| `org_invites` | Pending organization invitations |

MongoDB stores operational event data:

| Collection | Purpose |
| --- | --- |
| `api_request_logs` | Request logs with endpoint, method, status, latency, errors, metadata |
| `api_metrics_hourly` | Pre-aggregated hourly metrics for dashboards |

Redis supports:

- Fixed-window rate limiting.
- Celery broker and result backend.
- Token blacklist/session invalidation helpers.

## Request Lifecycle

1. Client sends a request to FastAPI.
2. CORS, rate limiting, and request logging middleware run.
3. Route dependencies validate JWTs, API keys, or roles.
4. Route handler calls a service function.
5. Service reads/writes PostgreSQL, MongoDB, Redis, Stripe, SendGrid, or webhook targets.
6. Slow or scheduled work is delegated to Celery.
7. Response is returned to the client.
8. Request metadata is logged for analytics and debugging.

## Authentication and Authorization

MeterFlow uses JWT access and refresh tokens for dashboard users. Access tokens are attached as:

```http
Authorization: Bearer <access_token>
```

API keys are generated with a MeterFlow prefix, hashed with SHA-256, and stored by hash. The full key is returned once during creation. Later validation hashes the incoming key and compares it with stored hashes.

Global user roles:

- `admin`
- `developer`
- `viewer`

Organization member roles:

- `owner`
- `admin`
- `member`
- `viewer`
- `billing`

## Background Jobs

Celery is configured in `backend/config/celery_app.py`.

Scheduled jobs:

| Schedule | Task |
| --- | --- |
| Daily at 00:05 UTC | `aggregate_daily_usage` |
| Hourly at minute 2 | `aggregate_hourly_metrics` |
| Monthly on day 1 at 01:00 UTC | `generate_monthly_invoices` |

Task modules:

- `backend/tasks/log_tasks.py`
- `backend/tasks/billing_tasks.py`
- `backend/tasks/metric_tasks.py`
- `backend/tasks/webhook_tasks.py`

## Frontend Design

The frontend is a Vite React app.

- `src/App.jsx` defines public and protected routes.
- `src/store/authStore.js` keeps user state in Zustand and persists basic auth state to local storage.
- `src/services/axios.js` centralizes API calls, adds bearer tokens, and refreshes tokens after `401` responses.
- `src/pages/` contains the visible product pages: login/signup, dashboard, API keys, billing, and logs.

Protected routes redirect unauthenticated users to `/login`.
