"""Workspace (tenant) and member management: who may do what.

Coverage showed these endpoints were mostly untested; reading them found that roles were
free text and that the last owner could be demoted, leaving a workspace nobody can manage.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from backend.app.main import create_app

PASSWORD = "test-password-1"


class User:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def register(self) -> "User":
        r = await self.http.post(
            "/api/v1/auth/register", json={"email": f"tm_{uuid.uuid4().hex}@example.com", "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        self.auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.id = (await self.http.get("/api/v1/auth/me", headers=self.auth)).json()["id"]
        self.own_tenant = (await self.http.get("/api/v1/tenants", headers=self.auth)).json()[0]["id"]
        return self

    async def call(self, method: str, path: str, json: dict | None = None) -> httpx.Response:
        return await self.http.request(method, f"/api/v1/tenants{path}", json=json, headers=self.auth)


@pytest_asyncio.fixture
async def team():
    """owner (of their own tenant T), member of T, and a stranger."""
    from backend.app.core.rate_limit import limiter

    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        limiter.reset()
        owner, member, stranger = [await User(http).register() for _ in range(3)]
        t = owner.own_tenant
        r = await owner.call("POST", f"/{t}/members", {"user_id": member.id, "role": "member"})
        assert r.status_code == 200, r.text
        yield owner, member, stranger, t


async def _tenants_of(user: User) -> set[str]:
    return {x["id"] for x in (await user.call("GET", "")).json()}


@pytest.mark.asyncio
async def test_member_and_stranger_permissions(team):
    owner, member, stranger, t = team

    assert (await member.call("GET", f"/{t}")).status_code == 200
    assert (await stranger.call("GET", f"/{t}")).status_code == 403

    for who, expected in ((member, 403), (stranger, 403)):
        assert (await who.call("PUT", f"/{t}", {"name": "hijacked"})).status_code == expected
        assert (await who.call("POST", f"/{t}/members", {"user_id": stranger.id, "role": "owner"})).status_code == expected
        assert (await who.call("PUT", f"/{t}/members/{member.id}", {"role": "owner"})).status_code == expected
        assert (await who.call("DELETE", f"/{t}/members/{owner.id}")).status_code == expected
        assert (await who.call("DELETE", f"/{t}")).status_code == expected

    assert (await owner.call("GET", f"/{t}")).json()["name"] != "hijacked"
    assert t not in await _tenants_of(stranger)


@pytest.mark.asyncio
async def test_owner_can_rename_promote_and_remove(team):
    owner, member, stranger, t = team

    r = await owner.call("PUT", f"/{t}", {"name": "Renamed"})
    assert r.status_code == 200 and (await owner.call("GET", f"/{t}")).json()["name"] == "Renamed"

    assert (await owner.call("PUT", f"/{t}/members/{member.id}", {"role": "owner"})).status_code == 200
    # As an owner now, the former member can manage the workspace.
    assert (await member.call("PUT", f"/{t}", {"name": "By new owner"})).status_code == 200

    assert (await owner.call("DELETE", f"/{t}/members/{member.id}")).status_code == 200
    assert t not in await _tenants_of(member)
    assert (await member.call("GET", f"/{t}")).status_code == 403


@pytest.mark.asyncio
async def test_removed_member_loses_access_to_workspace_data(team):
    owner, member, stranger, t = team
    member_headers = {**member.auth, "X-Tenant-ID": t}
    assert (await member.http.get("/api/v1/knowledgebases", headers=member_headers)).status_code == 200

    assert (await owner.call("DELETE", f"/{t}/members/{member.id}")).status_code == 200
    assert (await member.http.get("/api/v1/knowledgebases", headers=member_headers)).status_code == 403


@pytest.mark.asyncio
async def test_last_owner_cannot_be_removed_or_demoted(team):
    owner, member, stranger, t = team

    r = await owner.call("DELETE", f"/{t}/members/{owner.id}")
    assert r.status_code == 400 and "last owner" in r.json()["detail"]

    # Regression: demoting the only owner used to succeed, leaving nobody able to manage it.
    r = await owner.call("PUT", f"/{t}/members/{owner.id}", {"role": "member"})
    assert r.status_code == 400 and "last owner" in r.json()["detail"]
    r = await owner.call("POST", f"/{t}/members", {"user_id": owner.id, "role": "member"})
    assert r.status_code == 400 and "last owner" in r.json()["detail"]

    # With a second owner, the first may step down.
    assert (await owner.call("PUT", f"/{t}/members/{member.id}", {"role": "owner"})).status_code == 200
    assert (await owner.call("PUT", f"/{t}/members/{owner.id}", {"role": "member"})).status_code == 200
    assert (await member.call("DELETE", f"/{t}/members/{owner.id}")).status_code == 200


@pytest.mark.asyncio
async def test_roles_must_be_known(team):
    owner, member, stranger, t = team
    for role in ("admin", "superuser", "x" * 5000, ""):
        r = await owner.call("PUT", f"/{t}/members/{member.id}", {"role": role})
        assert r.status_code == 422, (role[:20], r.status_code, r.text[:120])
        r = await owner.call("POST", f"/{t}/members", {"user_id": stranger.id, "role": role})
        assert r.status_code == 422, (role[:20], r.status_code)
    assert t not in await _tenants_of(stranger)


@pytest.mark.asyncio
async def test_missing_users_and_memberships_are_404(team):
    owner, member, stranger, t = team
    ghost = str(uuid.uuid4())
    assert (await owner.call("POST", f"/{t}/members", {"user_id": ghost})).status_code == 404
    assert (await owner.call("PUT", f"/{t}/members/{stranger.id}", {"role": "member"})).status_code == 404
    assert (await owner.call("DELETE", f"/{t}/members/{stranger.id}")).status_code == 404
    assert (await owner.call("GET", f"/{uuid.uuid4()}")).status_code == 403  # not a member of a random id


@pytest.mark.asyncio
async def test_owner_can_delete_workspace(team):
    owner, member, stranger, t = team
    assert (await owner.call("DELETE", f"/{t}")).status_code == 200
    assert t not in await _tenants_of(owner)
    assert t not in await _tenants_of(member)
    assert (await member.http.get("/api/v1/knowledgebases", headers={**member.auth, "X-Tenant-ID": t})).status_code == 403
