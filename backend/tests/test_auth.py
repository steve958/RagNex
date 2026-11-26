from __future__ import annotations

import os
import uuid

import pytest
import httpx
from sqlalchemy import text

from backend.app.main import create_app
from backend.app.core.db import get_engine


@pytest.mark.asyncio
async def test_register_login_me_and_api_keys():
    # Ensure DB is reachable
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.execute(text("select 1"))

    app = create_app()

    email = f"test_{uuid.uuid4().hex}@example.com"
    password = "secret123!"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        tokens = r.json()
        assert "access_token" in tokens and "refresh_token" in tokens

        access = tokens["access_token"]

        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["email"] == email

        # Create API key requires tenant header. For now, use the default tenant created at register.
        # Fetch it via SQL directly.
        async with eng.connect() as conn:
            res = await conn.execute(
                text(
                    "select t.id from tenants t "
                    "join tenant_memberships m on m.tenant_id=t.id "
                    "join users u on u.id=m.user_id "
                    "where u.email=:email limit 1"
                ),
                {"email": email},
            )
            tenant_id = res.scalar_one()

        r = await client.post(
            "/api/v1/api-keys",
            json={"name": "test", "scopes": ["read"]},
            headers={
                "Authorization": f"Bearer {access}",
                "X-Tenant-ID": str(tenant_id),
            },
        )
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["api_key"].startswith("rk_")


@pytest.mark.asyncio
async def test_expired_access_token_is_rejected_and_refresh_issues_working_tokens():
    """The contract the frontend's refresh-on-401 relies on."""
    from datetime import datetime, timedelta, timezone

    from backend.app.core.security import TokenService

    tokens = TokenService()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register", json={"email": f"refresh_{uuid.uuid4().hex}@example.com", "password": "test-password-1"}
        )
        assert r.status_code == 200, r.text
        refresh_token = r.json()["refresh_token"]
        user_id = tokens.verify_token(r.json()["access_token"], expected_type="access").user_id

        expired = tokens._encode(  # noqa: SLF001
            user_id=user_id, token_type="access", exp=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401

        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r.status_code == 200, r.text
        new = r.json()
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"})
        assert r.status_code == 200 and r.json()["id"] == str(user_id)

        # The new refresh token works too (the frontend stores and reuses it).
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
        assert r.status_code == 200, r.text

        # An access token is not a refresh token, and garbage is rejected.
        for bad in (new["access_token"], "not-a-jwt"):
            r = await client.post("/api/v1/auth/refresh", json={"refresh_token": bad})
            assert r.status_code == 401, bad
