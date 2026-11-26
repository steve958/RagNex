from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.main import create_app
from backend.app.services.opensearch import OpenSearchService


def test_index_name_format():
    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert OpenSearchService.get_index_name(tid) == "chunks_12345678123456781234567812345678"


@pytest.mark.asyncio
async def test_create_tenant_calls_ensure_index(monkeypatch):
    app = create_app()

    called = {"n": 0}

    def fake_ensure_index(self, tenant_id):
        called["n"] += 1
        assert isinstance(tenant_id, uuid.UUID)
        return OpenSearchService.get_index_name(tenant_id)

    monkeypatch.setattr("backend.app.api.v1.tenants.OpenSearchService.ensure_index", fake_ensure_index)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": f"u_{uuid.uuid4().hex}@example.com", "password": "pw"},
        )
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        r = await client.post(
            "/api/v1/tenants",
            json={"name": "t2"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert r.status_code == 200, r.text
        assert called["n"] == 1


def test_ensure_chunks_policy_tolerates_existing_policy(monkeypatch):
    """Regression: ISM policy PUT returns 409 once the policy exists; that must not fail
    search/indexing (which call this on every request)."""
    from opensearchpy.exceptions import ConflictError

    calls = []

    class FakeTransport:
        def perform_request(self, method, url, body=None):
            calls.append((method, url))
            raise ConflictError(409, "version_conflict_engine_exception", {})

    class FakeClient:
        transport = FakeTransport()

    monkeypatch.setattr(OpenSearchService, "_client", lambda self: FakeClient())

    OpenSearchService().ensure_chunks_policy()  # must not raise
    assert calls == [("PUT", "/_plugins/_ism/policies/ragnex-chunks-policy")]
