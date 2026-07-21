"""Auth tests (Phase 3): login, token, /me, rejection paths."""

from __future__ import annotations

import os

import httpx
import pytest

from cartograph.auth.models import Tenant, User

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)


async def test_login_ok(client: httpx.AsyncClient, tenant_user: tuple[Tenant, User, str]) -> None:
    _, user, password = tenant_user
    resp = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "access_token" in resp.cookies


async def test_login_wrong_password(
    client: httpx.AsyncClient, tenant_user: tuple[Tenant, User, str]
) -> None:
    _, user, _ = tenant_user
    resp = await client.post("/api/auth/login", json={"email": user.email, "password": "nope"})
    assert resp.status_code == 401


async def test_login_unknown_user(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "whatever"}
    )
    assert resp.status_code == 401


async def test_me_with_bearer(
    client: httpx.AsyncClient,
    tenant_user: tuple[Tenant, User, str],
    auth_headers: dict[str, str],
) -> None:
    tenant, user, _ = tenant_user
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == user.email
    assert body["tenant_id"] == str(tenant.id)


async def test_me_with_cookie(
    client: httpx.AsyncClient, tenant_user: tuple[Tenant, User, str]
) -> None:
    _, user, password = tenant_user
    login = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    resp = await client.get("/api/auth/me", cookies={"access_token": login.json()["access_token"]})
    assert resp.status_code == 200


async def test_me_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_garbage_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
