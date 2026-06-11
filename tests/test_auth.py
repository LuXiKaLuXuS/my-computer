import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"

    username = f"authuser_{uuid.uuid4().hex[:6]}"
    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    assert reg.status_code == 201
    assert "access_token" in reg.json()
    assert "refresh_token" in reg.json()

    login = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.json()