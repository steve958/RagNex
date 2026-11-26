from __future__ import annotations

import httpx
import pytest

from backend.app.main import create_app


@pytest.mark.asyncio
async def test_health_ok():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_request_id_roundtrip():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health", headers={"X-Request-ID": "abc"})
        assert r.status_code == 200
        assert r.headers.get("X-Request-ID") == "abc"


@pytest.mark.asyncio
async def test_health_ready_patched(monkeypatch):
    # Patch dependency checks so this test doesn't require docker services running.
    async def ok_postgres():
        return "OK"

    async def ok_redis():
        return "PONG"

    async def ok_minio():
        return "buckets=0"

    async def skipped_opensearch():
        return "SKIPPED"

    monkeypatch.setattr("backend.app.api.v1.health.check_postgres", ok_postgres)
    monkeypatch.setattr("backend.app.api.v1.health.check_redis", ok_redis)
    monkeypatch.setattr("backend.app.api.v1.health.check_minio", ok_minio)
    monkeypatch.setattr("backend.app.api.v1.health.check_opensearch", skipped_opensearch)

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health/ready")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert set(body["components"].keys()) == {"postgres", "redis", "minio", "opensearch"}


@pytest.mark.asyncio
async def test_cors_preflight_allows_auth_and_tenant_headers():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.options(
            "/api/v1/chat/sessions/x/messages/stream",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-tenant-id,content-type",
            },
        )
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "x-tenant-id" in allowed and "authorization" in allowed
