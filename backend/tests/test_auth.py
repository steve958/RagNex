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
