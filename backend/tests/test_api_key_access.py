"""API keys are limited to their own tenant and scopes, and can't manage the account.

Regression: keys used to authenticate as their user everywhere — in every tenant the user
belonged to, ignoring scopes, including creating more keys and deleting tenants.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from backend.app.main import create_app


class Setup:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def build(self) -> "Setup":
        r = await self.http.post(
            "/api/v1/auth/register", json={"email": f"key_{uuid.uuid4().hex}@example.com", "password": "pw"}
        )
        assert r.status_code == 200, r.text
        self.jwt = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.tenant_a = (await self.http.get("/api/v1/tenants", headers=self.jwt)).json()[0]["id"]
        r = await self.http.post("/api/v1/tenants", json={"name": "second"}, headers=self.jwt)
        assert r.status_code == 200, r.text
        self.tenant_b = str(r.json()["id"])
        self.kb_a = await self._create_kb(self.tenant_a)
        return self

    async def _create_kb(self, tenant: str) -> str:
        r = await self.http.post(
            "/api/v1/knowledgebases", json={"name": "kb"}, headers={**self.jwt, "X-Tenant-ID": tenant}
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    async def key(self, scopes: list[str]) -> dict:
        """Create a key in tenant A; return headers using it (with tenant A selected)."""
        r = await self.http.post(
            "/api/v1/api-keys", json={"name": "k", "scopes": scopes}, headers={**self.jwt, "X-Tenant-ID": self.tenant_a}
        )
        assert r.status_code == 200, r.text
        self.last_key_id = r.json()["id"]
        return {"X-API-Key": r.json()["api_key"], "X-Tenant-ID": self.tenant_a}


@pytest_asyncio.fixture
async def setup(monkeypatch):
    from backend.app.api.v1 import knowledgebases as kb_module

    async def no_hits(self, **_kwargs):
        return []

    monkeypatch.setattr(kb_module.SearchService, "search", no_hits)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield await Setup(http).build()


@pytest.mark.asyncio
async def test_key_only_works_in_its_own_tenant(setup):
    key = await setup.key(["read", "write"])
    assert (await setup.http.get("/api/v1/knowledgebases", headers=key)).status_code == 200

    other = {**key, "X-Tenant-ID": setup.tenant_b}  # the key's user IS a member of B
    r = await setup.http.get("/api/v1/knowledgebases", headers=other)
    assert r.status_code == 403
    assert "not valid for this tenant" in r.json()["detail"]


@pytest.mark.asyncio
async def test_read_scope_allows_reads_and_search_but_not_writes(setup):
    key = await setup.key(["read"])
    assert (await setup.http.get("/api/v1/knowledgebases", headers=key)).status_code == 200
    r = await setup.http.post(f"/api/v1/knowledgebases/{setup.kb_a}/search", json={"query": "q"}, headers=key)
    assert r.status_code == 200, r.text

    for method, path, body in [
        ("POST", "/api/v1/knowledgebases", {"name": "nope"}),
        ("DELETE", f"/api/v1/knowledgebases/{setup.kb_a}", None),
        ("POST", "/api/v1/chat/sessions", {"kb_ids": [setup.kb_a]}),
    ]:
        r = await setup.http.request(method, path, json=body, headers=key)
        assert r.status_code == 403, (method, path, r.text)
        assert "scopes" in r.json()["detail"]

    # The KB is still there.
    assert (await setup.http.get(f"/api/v1/knowledgebases/{setup.kb_a}", headers=key)).status_code == 200


@pytest.mark.asyncio
async def test_write_scope_allows_writes_and_implies_read(setup):
    key = await setup.key(["write"])
    assert (await setup.http.post("/api/v1/knowledgebases", json={"name": "ok"}, headers=key)).status_code == 200
    assert (await setup.http.get("/api/v1/knowledgebases", headers=key)).status_code == 200


@pytest.mark.asyncio
async def test_key_without_scopes_can_do_nothing(setup):
    key = await setup.key([])
    assert (await setup.http.get("/api/v1/knowledgebases", headers=key)).status_code == 403


@pytest.mark.asyncio
async def test_keys_cannot_manage_the_account(setup):
    key = await setup.key(["read", "write"])
    for method, path, body in [
        ("POST", "/api/v1/api-keys", {"name": "escalate", "scopes": ["write"]}),
        ("GET", "/api/v1/api-keys", None),
        ("GET", "/api/v1/tenants", None),
        ("POST", "/api/v1/tenants", {"name": "x"}),
        ("DELETE", f"/api/v1/tenants/{setup.tenant_a}", None),
        ("GET", f"/api/v1/tenants/{setup.tenant_b}/model-settings", None),
        ("PUT", f"/api/v1/tenants/{setup.tenant_a}/model-settings", {"llm": {"model": "x"}}),
    ]:
        r = await setup.http.request(method, path, json=body, headers=key)
        assert r.status_code == 403, (method, path, r.text)
        assert "requires signing in" in r.json()["detail"]

    # Nothing was changed: the tenant still exists for the signed-in user.
    tenants = (await setup.http.get("/api/v1/tenants", headers=setup.jwt)).json()
    assert setup.tenant_a in {t["id"] for t in tenants}


@pytest.mark.asyncio
async def test_revoked_key_is_rejected(setup):
    key = await setup.key(["read"])
    r = await setup.http.post(
        "/api/v1/api-keys/revoke", json={"id": setup.last_key_id}, headers={**setup.jwt, "X-Tenant-ID": setup.tenant_a}
    )
    assert r.status_code == 200, r.text
    assert (await setup.http.get("/api/v1/knowledgebases", headers=key)).status_code == 401
