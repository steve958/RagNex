"""Authentication failure paths (coverage showed most were never exercised)."""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import jwt
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.user import User

PASSWORD = "test-password-1"


@pytest_asyncio.fixture
async def api():
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        email = f"af_{uuid.uuid4().hex}@example.com"
        r = await http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        http.email, http.tokens = email, r.json()  # type: ignore[attr-defined]
        yield http


async def _me(api, headers: dict) -> httpx.Response:
    return await api.get("/api/v1/auth/me", headers=headers)


@pytest.mark.asyncio
async def test_bad_credentials_are_401(api):
    access, refresh = api.tokens["access_token"], api.tokens["refresh_token"]
    assert (await _me(api, {"Authorization": f"Bearer {access}"})).status_code == 200

    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access", "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 600},
        "another-secret-of-at-least-thirty-two-bytes!!",
        algorithm="HS256",
    )
    unsigned = jwt.encode({"sub": str(uuid.uuid4()), "typ": "access"}, key=None, algorithm="none")
    for headers, detail in [
        ({}, "Missing credentials"),
        ({"Authorization": f"Basic {access}"}, "Invalid authorization header"),
        ({"Authorization": "Bearer not-a-jwt"}, "Invalid token"),
        ({"Authorization": f"Bearer {refresh}"}, "Invalid token"),  # refresh token is not an access token
        ({"Authorization": f"Bearer {forged}"}, "Invalid token"),  # signed with another secret
        ({"Authorization": f"Bearer {unsigned}"}, "Invalid token"),  # alg=none
        ({"X-API-Key": "rk_not_a_real_key"}, "Invalid API key"),
    ]:
        r = await _me(api, headers)
        assert r.status_code == 401, (headers, r.text)
        assert r.json()["detail"] == detail


@pytest.mark.asyncio
async def test_deleted_user_can_neither_use_tokens_nor_log_in(api):
    access = api.tokens["access_token"]
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        await db.execute(sa.update(User).where(User.email == api.email).values(deleted_at=dt.datetime.now(dt.timezone.utc)))
        await db.commit()

    assert (await _me(api, {"Authorization": f"Bearer {access}"})).status_code == 401
    r = await api.post("/api/v1/auth/login", json={"email": api.email, "password": PASSWORD})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_does_not_reveal_which_emails_exist(api, monkeypatch):
    from backend.app.api.v1 import auth as auth_module

    calls: list[str] = []
    real_verify = auth_module.password_hasher.verify

    def counting_verify(password, password_hash):
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_module.password_hasher, "verify", counting_verify)

    wrong_password = await api.post("/api/v1/auth/login", json={"email": api.email, "password": "wrong-password"})
    unknown_email = await api.post(
        "/api/v1/auth/login", json={"email": f"nobody_{uuid.uuid4().hex}@example.com", "password": "wrong-password"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Invalid credentials"}
    # Both paths do the (slow) hash check, so timing doesn't tell them apart.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_duplicate_registration_and_logout(api):
    r = await api.post("/api/v1/auth/register", json={"email": api.email, "password": PASSWORD})
    assert r.status_code == 400 and r.json()["detail"] == "Email already registered"
    assert (await api.post("/api/v1/auth/logout")).status_code == 200
    # The secret in use is the one the app validated at startup.
    assert len(settings.jwt_secret.encode()) >= 32
