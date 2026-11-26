"""Sign-up settings, operator-created accounts, and rate limits shared through Redis."""

from __future__ import annotations

import io
import uuid

import httpx
import pytest
import pytest_asyncio
import redis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.user import TenantMembership, User
from backend.app.services import accounts

PASSWORD = "test-password-1"


def _email(domain: str = "example.com") -> str:
    return f"reg_{uuid.uuid4().hex}@{domain}"


@pytest_asyncio.fixture
async def http():
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def signup(monkeypatch):
    def configure(enabled: bool = True, domains: list[str] | None = None):
        monkeypatch.setattr(settings, "registration_enabled", enabled)
        monkeypatch.setattr(settings, "registration_email_domains", domains or [])

    return configure


async def _user(email: str) -> User | None:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        return (await db.execute(sa.select(User).where(User.email == email))).scalar_one_or_none()


async def _memberships(user_id: uuid.UUID) -> list[TenantMembership]:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        rows = await db.execute(sa.select(TenantMembership).where(TenantMembership.user_id == user_id))
        return list(rows.scalars())


async def _register(http, email: str) -> httpx.Response:
    return await http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})


# --- Sign-up settings ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_is_open_by_default(http):
    assert settings.registration_enabled is True  # existing deployments keep working
    r = await http.get("/api/v1/auth/registration")
    assert r.json() == {"enabled": True, "email_domains": []}
    email = _email()
    assert (await _register(http, email)).status_code == 200


@pytest.mark.asyncio
async def test_closed_signup_refuses_and_creates_nothing(http, signup):
    signup(enabled=False)
    assert (await http.get("/api/v1/auth/registration")).json()["enabled"] is False

    email = _email()
    r = await _register(http, email)
    assert r.status_code == 403
    assert "closed" in r.json()["detail"]
    assert await _user(email) is None


@pytest.mark.asyncio
async def test_signup_limited_to_listed_domains(http, signup):
    signup(domains=["Example.org", "@corp.example"])  # case and a leading @ are tolerated
    info = (await http.get("/api/v1/auth/registration")).json()
    assert info == {"enabled": True, "email_domains": ["example.org", "corp.example"]}

    assert (await _register(http, _email("example.org"))).status_code == 200
    assert (await _register(http, f"reg_{uuid.uuid4().hex}@EXAMPLE.ORG")).status_code == 200
    assert (await _register(http, _email("corp.example"))).status_code == 200

    for refused in (_email("example.com"), _email("evil.example.org"), _email("example.org.evil.com")):
        r = await _register(http, refused)
        assert r.status_code == 403, refused
        assert await _user(refused) is None


@pytest.mark.asyncio
async def test_existing_accounts_can_still_log_in_when_signup_closes(http, signup):
    email = _email()
    assert (await _register(http, email)).status_code == 200
    signup(enabled=False)
    r = await http.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200


# --- Operator-created accounts -------------------------------------------------------------


def _cli(argv: list[str], monkeypatch, password: str = PASSWORD) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    return accounts.main(["create-user", *argv, "--password-stdin"])


@pytest.mark.asyncio
async def test_operator_creates_user_with_own_workspace_while_signup_closed(http, signup, monkeypatch, capsys):
    signup(enabled=False)
    email = _email()
    # main() runs its own event loop, so run it outside this test's loop.
    import anyio.to_thread

    assert await anyio.to_thread.run_sync(lambda: _cli([email], monkeypatch)) == 0
    assert "with a new workspace" in capsys.readouterr().out

    user = await _user(email)
    assert [m.role for m in await _memberships(user.id)] == ["owner"]
    r = await http.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_operator_adds_new_user_to_existing_workspace(http, monkeypatch):
    owner = _email()
    tokens = (await _register(http, owner)).json()
    me = {"Authorization": f"Bearer {tokens['access_token']}"}
    workspace = (await http.get("/api/v1/tenants", headers=me)).json()[0]["id"]

    import anyio.to_thread

    email = _email()
    code = await anyio.to_thread.run_sync(lambda: _cli([email, "--workspace", workspace], monkeypatch))
    assert code == 0
    memberships = await _memberships((await _user(email)).id)
    assert [(str(m.tenant_id), m.role) for m in memberships] == [(workspace, "member")]  # no extra workspace


@pytest.mark.asyncio
async def test_operator_errors_are_reported_without_creating_anything(http, monkeypatch, capsys):
    import anyio.to_thread

    def run(argv, password=PASSWORD):
        return anyio.to_thread.run_sync(lambda: _cli(argv, monkeypatch, password))

    taken = _email()
    assert (await _register(http, taken)).status_code == 200
    assert await run([taken]) == 1
    assert "already registered" in capsys.readouterr().err

    missing = _email()
    assert await run([missing, "--workspace", str(uuid.uuid4())]) == 1
    assert "not found" in capsys.readouterr().err
    assert await _user(missing) is None

    short = _email()
    assert await run([short], password="short") == 1
    assert "at least 8" in capsys.readouterr().err
    assert await _user(short) is None

    assert await run(["not-an-email"]) == 1


def test_role_needs_a_workspace(monkeypatch):
    with pytest.raises(SystemExit):
        _cli([_email(), "--role", "owner"], monkeypatch)


# --- Rate limits ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_counts_are_shared_through_redis(http):
    """Counts must live in Redis: kept in process memory, each API worker would allow its own
    full quota. Reading them from a separate Redis connection stands in for another process."""
    other = redis.Redis.from_url(settings.redis_url)

    def login_count() -> int:
        # Compare before and after: counts from earlier runs may still be in Redis.
        return sum(int(other.get(k) or 0) for k in other.scan_iter(match="*ragnex*login*") if other.type(k) == b"string")

    before = login_count()
    for _ in range(3):
        r = await http.post("/api/v1/auth/login", json={"email": _email(), "password": "wrong-password"})
        assert r.status_code == 401
    assert login_count() - before == 3


@pytest.mark.asyncio
async def test_list_workspaces_shows_ids_for_create_user(http, capsys):
    owner = _email()
    tokens = (await _register(http, owner)).json()
    me = {"Authorization": f"Bearer {tokens['access_token']}"}
    workspace = (await http.get("/api/v1/tenants", headers=me)).json()[0]["id"]

    import anyio.to_thread

    assert await anyio.to_thread.run_sync(lambda: accounts.main(["list-workspaces"])) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(workspace))
    assert f"(created by {owner})" in line
