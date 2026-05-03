# Testing Guide

## Backend Tests

Backend tests live in:

```text
backend/tests/
```

Current test areas:

- `test_auth.py`
- `test_apikeys.py`
- `test_billing.py`
- `conftest.py`

Run tests:

```bash
cd backend
pytest
```

Run a single file:

```bash
pytest tests/test_auth.py
```

Run with verbose output:

```bash
pytest -v
```

## Frontend Checks

The frontend currently defines build scripts but no automated test script.

Run a production build:

```bash
cd frontend
npm run build
```

Preview the production build:

```bash
npm run preview
```

## Manual Smoke Test

After starting Docker, backend, Celery, and frontend:

1. Open `http://localhost:5173`.
2. Sign up for a new account.
3. Confirm you are redirected into the protected dashboard.
4. Create an API key from the API Keys page.
5. Use the playground or API calls to create usage.
6. Visit Dashboard, Billing, and Logs.
7. Check `http://localhost:8000/health`.
8. Check `http://localhost:8000/docs`.

## API Smoke Test

```bash
curl http://localhost:8000/health
```

Signup:

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"you@example.com\",\"username\":\"you\",\"password\":\"password123\",\"full_name\":\"Your Name\"}"
```

Login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"you@example.com\",\"password\":\"password123\"}"
```

Use the returned access token:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## What To Test When Adding Features

- Route-level success and failure cases.
- Authenticated and unauthenticated access.
- Role-protected access.
- Database writes and rollbacks.
- API key creation and verification without exposing stored raw keys.
- Billing calculations at free-tier and paid-tier boundaries.
- Celery task behavior for retries and idempotency.
- Frontend state transitions for loading, error, and empty states.
