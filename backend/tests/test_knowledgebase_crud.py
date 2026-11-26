"""Knowledge base get/update/delete, including across tenants and after deletion."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from backend.app.main import create_app


async def _user(http: httpx.AsyncClient) -> dict:
    r = await http.post(
        "/api/v1/auth/register", json={"email": f"kb_{uuid.uuid4().hex}@example.com", "password": "test-password-1"}
    )
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    tenant = (await http.get("/api/v1/tenants", headers=auth)).json()[0]["id"]
    return {**auth, "X-Tenant-ID": tenant}


@pytest_asyncio.fixture
async def setup():
    from backend.app.core.rate_limit import limiter

    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        limiter.reset()
        mine, theirs = await _user(http), await _user(http)
        r = await http.post(
            "/api/v1/knowledgebases", json={"name": "Docs", "description": "first"}, headers=mine
        )
        assert r.status_code == 200, r.text
        yield http, mine, theirs, r.json()["id"]


@pytest.mark.asyncio
async def test_update_changes_only_the_given_fields(setup):
    http, mine, _theirs, kb = setup
    r = await http.put(f"/api/v1/knowledgebases/{kb}", json={"template": "paper"}, headers=mine)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": kb, "name": "Docs", "description": "first", "template": "paper"}

    r = await http.put(f"/api/v1/knowledgebases/{kb}", json={"name": "Renamed", "description": "second"}, headers=mine)
    assert r.json()["name"] == "Renamed" and r.json()["description"] == "second" and r.json()["template"] == "paper"
    assert (await http.get(f"/api/v1/knowledgebases/{kb}", headers=mine)).json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_other_tenants_cannot_see_or_change_it(setup):
    http, mine, theirs, kb = setup
    assert (await http.get(f"/api/v1/knowledgebases/{kb}", headers=theirs)).status_code == 404
    assert (await http.put(f"/api/v1/knowledgebases/{kb}", json={"name": "x"}, headers=theirs)).status_code == 404
    assert (await http.delete(f"/api/v1/knowledgebases/{kb}", headers=theirs)).status_code == 404
    assert kb not in {k["id"] for k in (await http.get("/api/v1/knowledgebases", headers=theirs)).json()}
    # Pointing at my tenant with their token doesn't help either.
    sneaky = {"Authorization": theirs["Authorization"], "X-Tenant-ID": mine["X-Tenant-ID"]}
    assert (await http.get(f"/api/v1/knowledgebases/{kb}", headers=sneaky)).status_code == 403
    assert (await http.get(f"/api/v1/knowledgebases/{kb}", headers=mine)).json()["name"] == "Docs"


@pytest.mark.asyncio
async def test_deleted_knowledge_base_is_gone_everywhere(setup):
    http, mine, _theirs, kb = setup
    assert (await http.delete(f"/api/v1/knowledgebases/{kb}", headers=mine)).status_code == 200
    assert (await http.get(f"/api/v1/knowledgebases/{kb}", headers=mine)).status_code == 404
    assert (await http.put(f"/api/v1/knowledgebases/{kb}", json={"name": "back"}, headers=mine)).status_code == 404
    assert (await http.delete(f"/api/v1/knowledgebases/{kb}", headers=mine)).status_code == 404
    assert kb not in {k["id"] for k in (await http.get("/api/v1/knowledgebases", headers=mine)).json()}
    r = await http.post(f"/api/v1/knowledgebases/{kb}/documents", files={"file": ("a.md", b"# x\n")}, headers=mine)
    assert r.status_code == 404
