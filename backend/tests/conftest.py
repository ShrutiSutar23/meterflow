# backend/tests/conftest.py
"""
Shared Test Fixtures
=====================
conftest.py is automatically loaded by pytest before any test file.
Fixtures defined here are available to ALL test files without importing.

Think of fixtures as "test helpers":
  - client     → HTTP test client
  - auth_headers → pre-logged-in user headers
  - admin_headers → admin user headers
  - test_user  → user dict with credentials

Real-world: Large projects have extensive conftest.py files.
Django, FastAPI, Flask all use this pattern.
"""

import pytest
import pytest_asyncio
import time
import sys
import os

# Make sure we can import from the backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture(scope="session")
async def app():
    """Create the FastAPI app once per test session."""
    from main_final import app as fastapi_app
    return fastapi_app


@pytest_asyncio.fixture
async def client(app):
    """HTTP test client — created fresh for each test."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(client: AsyncClient) -> dict:
    """
    Create a unique test user for each test.
    Uses timestamp to ensure uniqueness across parallel test runs.
    """
    unique = int(time.time() * 1000)  # millisecond precision
    user_data = {
        "email": f"testuser_{unique}@example.com",
        "username": f"testuser_{unique}",
        "password": "TestPass123",
        "full_name": "Test User",
    }
    response = await client.post("/api/v1/auth/signup", json=user_data)
    assert response.status_code == 201, f"Failed to create test user: {response.text}"
    return user_data


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: dict) -> dict:
    """Authorization headers for the test user."""
    response = await client.post("/api/v1/auth/login", json={
        "email": test_user["email"],
        "password": test_user["password"],
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_api_key(client: AsyncClient, auth_headers: dict) -> dict:
    """
    Create a test API key and return full key data.
    The full_key is included here (only available at creation time).
    """
    response = await client.post(
        "/api/v1/keys/",
        json={"name": "Test Key", "environment": "test"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()   # Includes full_key


@pytest_asyncio.fixture
async def api_key_headers(test_api_key: dict) -> dict:
    """Headers using API key authentication (X-API-Key)."""
    return {"X-API-Key": test_api_key["full_key"]}
