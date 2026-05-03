# backend/tests/test_auth.py
"""
Test Suite — Authentication (Day 11)
=======================================
Tests every auth endpoint end-to-end using pytest + httpx.

WHY TESTS MATTER:
  - Catch regressions (code changes that break existing features)
  - Document expected behavior (tests are living documentation)
  - Required before deploying to production
  - Every serious company (Google, Stripe, GitHub) has extensive tests

HOW FASTAPI TESTING WORKS:
  - httpx.AsyncClient with app=app creates a test client
  - No real HTTP server needed — runs in-process
  - Tests use a separate test database (DB_URL_TEST in .env)
  - Each test is isolated — no shared state

RUN TESTS:
  cd backend
  pytest tests/ -v                    # Run all tests verbosely
  pytest tests/test_auth.py -v        # Run only auth tests
  pytest tests/ -v --tb=short         # Short tracebacks on failure
  pytest tests/ -v -k "test_login"    # Run only tests matching name

INTERVIEW TOPIC:
  "What testing strategies do you use?"
  Answer: Unit tests (pure functions), Integration tests (API endpoints),
  E2E tests (full user flow). We use pytest for backend,
  Vitest/React Testing Library for frontend.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# We import the app from main_final
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixtures ──────────────────────────────────────────────────────────────────
# Fixtures are reusable setup/teardown functions.
# @pytest.fixture means: run this before any test that requests it.

@pytest_asyncio.fixture
async def client():
    """
    Create a test HTTP client connected to the FastAPI app.
    No real server needed — runs entirely in memory.
    """
    from main_final import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient):
    """
    Create a test user and return their credentials.
    Used by tests that need an existing user.
    """
    user_data = {
        "email": "pytest_user@example.com",
        "username": "pytest_user",
        "password": "TestPass123",
        "full_name": "Pytest User",
    }
    response = await client.post("/api/v1/auth/signup", json=user_data)

    # If user already exists from a previous test run, that's OK
    assert response.status_code in (201, 409), f"Unexpected status: {response.status_code}"

    return user_data


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, registered_user: dict):
    """
    Log in and return Authorization headers.
    Used by any test that needs a protected endpoint.
    """
    response = await client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Server returns 200 with status=healthy."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "dependencies" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Root endpoint returns service info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "MeterFlow"


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNUP TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_signup_success(client: AsyncClient):
    """New user can register successfully."""
    import time
    unique_email = f"newuser_{int(time.time())}@example.com"
    payload = {
        "email": unique_email,
        "username": f"newuser_{int(time.time())}",
        "password": "SecurePass123",
        "full_name": "New User",
    }
    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 201
    data = response.json()

    # Check returned fields
    assert data["email"] == unique_email
    assert "id" in data
    assert "hashed_password" not in data    # CRITICAL: password must never be returned
    assert data["plan"] == "free"
    assert data["role"] == "developer"


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient, registered_user: dict):
    """Registering with an existing email returns 409 Conflict."""
    response = await client.post("/api/v1/auth/signup", json={
        "email": registered_user["email"],     # Same email
        "username": "different_username_99",
        "password": "AnotherPass123",
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signup_weak_password(client: AsyncClient):
    """Passwords without numbers are rejected."""
    response = await client.post("/api/v1/auth/signup", json={
        "email": "weakpass@example.com",
        "username": "weakpassuser",
        "password": "onlyletters",     # No numbers → should fail
    })
    assert response.status_code == 422    # Validation error


@pytest.mark.asyncio
async def test_signup_invalid_email(client: AsyncClient):
    """Invalid email format is rejected."""
    response = await client.post("/api/v1/auth/signup", json={
        "email": "not-an-email",
        "username": "testuser99",
        "password": "ValidPass123",
    })
    assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, registered_user: dict):
    """Valid credentials return access and refresh tokens."""
    response = await client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })

    assert response.status_code == 200
    data = response.json()

    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0

    # Verify tokens are JWT format (3 parts separated by dots)
    assert len(data["access_token"].split(".")) == 3


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, registered_user: dict):
    """Wrong password returns 401, not 403 or 404."""
    response = await client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": "WrongPassword999",
    })
    assert response.status_code == 401
    # Must NOT say "user not found" (enumeration vulnerability)
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient):
    """Non-existent email returns same 401 as wrong password (no enumeration)."""
    response = await client.post("/api/v1/auth/login", json={
        "email": "doesnotexist@example.com",
        "password": "AnyPassword123",
    })
    assert response.status_code == 401
    # Same error message as wrong password — no information leakage
    assert "invalid" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# JWT PROTECTED ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_me_authenticated(client: AsyncClient, auth_headers: dict):
    """Authenticated user can retrieve their own profile."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "hashed_password" not in data    # CRITICAL security check
    assert "id" in data


@pytest.mark.asyncio
async def test_get_me_no_token(client: AsyncClient):
    """Endpoint returns 403 without a token."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    """Fake token returns 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer fake.token.here"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh(client: AsyncClient, registered_user: dict):
    """Refresh token returns new access token."""
    # Login to get refresh token
    login_response = await client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    refresh_token = login_response.json()["refresh_token"]

    # Use refresh token
    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 200
    new_data = refresh_response.json()
    assert "access_token" in new_data
    # New token should be different from original
    assert new_data["access_token"] != login_response.json()["access_token"]
