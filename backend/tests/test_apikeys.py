# backend/tests/test_apikeys.py
"""
Test Suite — API Keys (Day 11)
================================
Tests the full API key lifecycle:
  create → list → verify → revoke
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest_asyncio.fixture
async def client():
    from main_final import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Create a user and return auth headers."""
    import time
    unique = int(time.time())
    user = {
        "email": f"keytest_{unique}@example.com",
        "username": f"keytest_{unique}",
        "password": "KeyTest123",
    }
    await client.post("/api/v1/auth/signup", json=user)
    login = await client.post("/api/v1/auth/login", json={
        "email": user["email"], "password": user["password"],
    })
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# CREATE KEY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_api_key_success(client: AsyncClient, auth_headers: dict):
    """User can create an API key and receives the full key once."""
    payload = {
        "name": "Test Key",
        "environment": "test",
        "rate_limit_per_minute": 30,
    }
    response = await client.post("/api/v1/keys/", json=payload, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()

    # Full key must be returned on creation
    assert "full_key" in data
    assert data["full_key"].startswith("mf_test_")   # Correct prefix for test env

    # Metadata fields
    assert data["name"] == "Test Key"
    assert data["environment"] == "test"
    assert data["rate_limit_per_minute"] == 30
    assert "id" in data

    # Full key must be long enough to be secure
    assert len(data["full_key"]) > 30


@pytest.mark.asyncio
async def test_api_key_prefix_format(client: AsyncClient, auth_headers: dict):
    """Live keys start with mf_live_ prefix."""
    response = await client.post("/api/v1/keys/", json={
        "name": "Live Key",
        "environment": "live",
    }, headers=auth_headers)

    assert response.status_code == 201
    assert response.json()["full_key"].startswith("mf_live_")


@pytest.mark.asyncio
async def test_create_key_requires_auth(client: AsyncClient):
    """Creating a key without JWT returns 401/403."""
    response = await client.post("/api/v1/keys/", json={"name": "Unauthorized"})
    assert response.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# LIST KEYS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_keys_returns_prefix_only(client: AsyncClient, auth_headers: dict):
    """Listed keys show prefix but never the full key."""
    # Create a key first
    await client.post("/api/v1/keys/", json={"name": "List Test"}, headers=auth_headers)

    response = await client.get("/api/v1/keys/", headers=auth_headers)
    assert response.status_code == 200

    keys = response.json()
    assert isinstance(keys, list)
    assert len(keys) > 0

    for key in keys:
        # full_key must NEVER appear in list response
        assert "full_key" not in key
        assert "key_hash" not in key
        assert "key_prefix" in key


@pytest.mark.asyncio
async def test_list_keys_empty_for_new_user(client: AsyncClient):
    """Brand new user has no API keys."""
    import time
    unique = int(time.time()) + 9999
    user = {
        "email": f"empty_{unique}@example.com",
        "username": f"empty_{unique}",
        "password": "Empty123",
    }
    await client.post("/api/v1/auth/signup", json=user)
    login = await client.post("/api/v1/auth/login", json={
        "email": user["email"], "password": user["password"],
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = await client.get("/api/v1/keys/", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


# ═══════════════════════════════════════════════════════════════════════════════
# REVOKE KEY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_revoke_key_success(client: AsyncClient, auth_headers: dict):
    """User can revoke their own key."""
    # Create a key
    create_response = await client.post(
        "/api/v1/keys/", json={"name": "To Revoke"}, headers=auth_headers,
    )
    key_id = create_response.json()["id"]

    # Revoke it
    revoke_response = await client.delete(f"/api/v1/keys/{key_id}", headers=auth_headers)
    assert revoke_response.status_code == 200
    assert "revoked" in revoke_response.json()["message"].lower()

    # Verify it shows as inactive in the list
    list_response = await client.get("/api/v1/keys/", headers=auth_headers)
    revoked_key = next(
        (k for k in list_response.json() if k["id"] == key_id), None
    )
    if revoked_key:
        assert revoked_key["is_active"] is False


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(client: AsyncClient, auth_headers: dict):
    """Revoking a key that doesn't exist returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(f"/api/v1/keys/{fake_id}", headers=auth_headers)
    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# KEY VERIFY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_verify_valid_key(client: AsyncClient, auth_headers: dict):
    """A freshly created key verifies as valid."""
    create_response = await client.post(
        "/api/v1/keys/", json={"name": "Verify Test"}, headers=auth_headers,
    )
    full_key = create_response.json()["full_key"]

    verify_response = await client.post(
        "/api/v1/keys/verify", params={"x_api_key": full_key},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["valid"] is True


@pytest.mark.asyncio
async def test_verify_fake_key(client: AsyncClient):
    """A random string fails verification."""
    verify_response = await client.post(
        "/api/v1/keys/verify", params={"x_api_key": "mf_live_thisisafakekeynotreal"},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["valid"] is False
