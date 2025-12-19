from __future__ import annotations

import uuid

import pytest
import httpx

from backend.app.main import create_app


@pytest.mark.asyncio
async def test_cross_tenant_access_forbidden():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email1 = f"u1_{uuid.uuid4().hex}@example.com"
    email2 = f"u2_{uuid.uuid4().hex}@example.com"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email1, "password": "pw"})
        assert r.status_code == 200
        t1 = r.json()["access_token"]

        r = await client.post("/api/v1/auth/register", json={"email": email2, "password": "pw"})
        assert r.status_code == 200
        t2 = r.json()["access_token"]

        # user1 creates a second tenant
        r = await client.post(
            "/api/v1/tenants",
            json={"name": "t2"},
            headers={"Authorization": f"Bearer {t1}"},
        )
        assert r.status_code == 200
        tenant_created = r.json()["id"]

        # user2 cannot access that tenant
        r = await client.get(
            f"/api/v1/tenants/{tenant_created}",
            headers={"Authorization": f"Bearer {t2}"},
        )
        assert r.status_code == 403
