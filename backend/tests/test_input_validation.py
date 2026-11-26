"""Hostile and malformed input gets a clear 4xx, never a 500, and nothing unsafe is stored.

Regression: NUL bytes and over-long values reached Postgres and came back as 500s; empty
passwords, unknown KB templates, unknown API-key scopes and multi-megabyte prompts were
accepted; upload filenames were stored with paths and direction-override characters.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.core.security import PasswordHasher
from backend.app.core.validation import safe_filename
from backend.app.main import create_app
from backend.app.models.user import User
from backend.app.services.parsing import parse_document_binary

from test_e2e_pipeline import _stack_available

LONG = "x" * 5000
NUL = "bad\x00value"
PASSWORD = "test-password-1"


class Client:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def setup(self) -> "Client":
        r = await self.http.post(
            "/api/v1/auth/register", json={"email": f"iv_{uuid.uuid4().hex}@example.com", "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        self.auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        tenant = (await self.http.get("/api/v1/tenants", headers=self.auth)).json()[0]["id"]
        self.headers = {**self.auth, "X-Tenant-ID": tenant}
        r = await self.http.post("/api/v1/knowledgebases", json={"name": "kb"}, headers=self.headers)
        self.kb = r.json()["id"]
        return self


@pytest_asyncio.fixture
async def client():
    # raise_app_exceptions=False: an unhandled error must show up as a 500 response here
    # (what a real client would see), not as an exception in the test.
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield await Client(http).setup()


def _cases(c: Client) -> list[tuple[str, str, str, object, dict, str]]:
    """(name, method, path, json body, headers, field expected in the error)."""
    h, auth, kb = c.headers, c.auth, c.kb
    new_email = lambda: f"iv_{uuid.uuid4().hex}@example.com"  # noqa: E731
    return [
        ("huge password", "POST", "/api/v1/auth/register", {"email": new_email(), "password": "p" * 2_000_000}, {}, "password"),
        ("empty password", "POST", "/api/v1/auth/register", {"email": new_email(), "password": ""}, {}, "password"),
        ("short password", "POST", "/api/v1/auth/register", {"email": new_email(), "password": "1234567"}, {}, "password"),
        ("kb NUL name", "POST", "/api/v1/knowledgebases", {"name": NUL}, h, "name"),
        ("kb multi-line name", "POST", "/api/v1/knowledgebases", {"name": "a\nb"}, h, "name"),
        ("kb RTL-override name", "POST", "/api/v1/knowledgebases", {"name": "inv\u202efdp.exe"}, h, "name"),
        ("kb blank name", "POST", "/api/v1/knowledgebases", {"name": "   "}, h, "name"),
        ("kb long template", "POST", "/api/v1/knowledgebases", {"name": "k", "template": LONG}, h, "template"),
        ("kb unknown template", "POST", "/api/v1/knowledgebases", {"name": "k", "template": "nonsense"}, h, "template"),
        ("kb huge description", "POST", "/api/v1/knowledgebases", {"name": "k", "description": "d" * 20_000}, h, "description"),
        ("kb NUL description", "POST", "/api/v1/knowledgebases", {"name": "k", "description": NUL}, h, "description"),
        ("kb update template", "PUT", f"/api/v1/knowledgebases/{kb}", {"template": LONG}, h, "template"),
        ("session long name", "POST", "/api/v1/chat/sessions", {"kb_ids": [kb], "name": LONG}, h, "name"),
        ("session NUL prompt", "POST", "/api/v1/chat/sessions", {"kb_ids": [kb], "system_prompt": NUL}, h, "system_prompt"),
        ("session huge prompt", "POST", "/api/v1/chat/sessions", {"kb_ids": [kb], "system_prompt": "s" * 20_000}, h, "system_prompt"),
        ("session too many kbs", "POST", "/api/v1/chat/sessions", {"kb_ids": [str(uuid.uuid4()) for _ in range(51)]}, h, "kb_ids"),
        ("api key long name", "POST", "/api/v1/api-keys", {"name": LONG, "scopes": ["read"]}, h, "name"),
        ("api key NUL name", "POST", "/api/v1/api-keys", {"name": NUL, "scopes": ["read"]}, h, "name"),
        ("api key unknown scope", "POST", "/api/v1/api-keys", {"name": "k", "scopes": ["admin"]}, h, "scopes"),
        ("tenant long name", "POST", "/api/v1/tenants", {"name": LONG}, auth, "name"),
        ("tenant empty name", "POST", "/api/v1/tenants", {"name": ""}, auth, "name"),
        ("tenant NUL name", "POST", "/api/v1/tenants", {"name": NUL}, auth, "name"),
        ("search NUL query", "POST", f"/api/v1/knowledgebases/{kb}/search", {"query": NUL}, h, "query"),
    ]


@pytest.mark.asyncio
async def test_hostile_json_input_is_rejected_with_422(client):
    from backend.app.core.rate_limit import limiter

    failures = []
    for name, method, path, body, headers, field in _cases(client):
        limiter.reset()
        r = await client.http.request(method, path, json=body, headers=headers)
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        if r.status_code != 422 or not any(field in e.get("loc", []) for e in detail if isinstance(e, dict)):
            failures.append((name, r.status_code, str(detail)[:120]))
    assert failures == []


@pytest.mark.asyncio
async def test_other_malformed_requests_get_clear_4xx(client):
    bad_tenant = await client.http.get(
        "/api/v1/knowledgebases", headers={**client.auth, "X-Tenant-ID": "not-a-uuid"}
    )
    assert bad_tenant.status_code == 400
    assert bad_tenant.json()["detail"] == "Invalid X-Tenant-ID header (expected a UUID)"

    missing_tenant = await client.http.get("/api/v1/knowledgebases", headers=client.auth)
    assert missing_tenant.json()["detail"] == "Missing X-Tenant-ID header"

    malformed = await client.http.post(
        "/api/v1/knowledgebases", content="{not json", headers={**client.headers, "Content-Type": "application/json"}
    )
    assert malformed.status_code == 422

    assert (await client.http.get("/api/v1/documents/not-a-uuid", headers=client.headers)).status_code == 422


@pytest.mark.asyncio
async def test_valid_unicode_input_is_accepted(client):
    r = await client.http.post(
        "/api/v1/knowledgebases",
        json={"name": "  Café ☀ 太阳能  ", "description": "Line one\nLine two\twith tab", "template": "laws"},
        headers=client.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Café ☀ 太阳能"  # trimmed, otherwise unchanged


@pytest.mark.asyncio
async def test_accounts_with_old_short_passwords_can_still_log_in(client):
    email = f"legacy_{uuid.uuid4().hex}@example.com"
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        db.add(User(email=email, password_hash=PasswordHasher().hash("pw")))
        await db.commit()
    r = await client.http.post("/api/v1/auth/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200, r.text


# --- Filenames ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd.md", "passwd.md"),
        ("..\\..\\windows\\evil.md", "evil.md"),
        ("/abs/path.md", "path.md"),
        ("C:\\abs\\path.md", "path.md"),
        ("nul\x00byte.md", "nulbyte.md"),
        ("new\nline.md", "newline.md"),
        ("invoice\u202efdp.md", "invoicefdp.md"),  # direction override removed
        ("zero\u200bwidth.md", "zerowidth.md"),
        ("  spaced name.md  ", "spaced name.md"),
        ("café ☀.md", "café ☀.md"),
        ("trailing.md.", "trailing.md"),
        ("", "upload"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_shortens_long_names_but_keeps_the_extension():
    name = safe_filename("a" * 600 + ".docx")
    assert len(name) == 255 and name.endswith(".docx")


needs_stack = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


@needs_stack
@pytest.mark.asyncio
async def test_uploaded_filenames_are_stored_clean(client):
    from backend.app.core.rate_limit import limiter

    for raw, expected in [
        ("../../etc/passwd.md", "passwd.md"),
        ("..\\..\\windows\\evil.md", "evil.md"),
        ("invoice\u202etxt.md", "invoicetxt.md"),
        ("a" * 600 + ".md", "a" * 252 + ".md"),
    ]:
        limiter.reset()
        r = await client.http.post(
            f"/api/v1/knowledgebases/{client.kb}/documents", files={"file": (raw, b"# Hi\n\ntext\n")}, headers=client.headers
        )
        assert r.status_code == 200, (raw, r.text)
        assert r.json()["filename"] == expected

    for raw in (".md", "   .md", "noext"):
        r = await client.http.post(
            f"/api/v1/knowledgebases/{client.kb}/documents", files={"file": (raw, b"text")}, headers=client.headers
        )
        assert r.status_code == 400, raw


@needs_stack
@pytest.mark.asyncio
async def test_values_the_database_rejects_become_422_not_500(client):
    """Safety net for fields without request-level validation: here the upload's
    Content-Type, stored in a 255-character column."""
    r = await client.http.post(
        f"/api/v1/knowledgebases/{client.kb}/documents",
        files={"file": ("ok.md", b"# Hi\n", "text/markdown; x=" + "a" * 400)},
        headers=client.headers,
    )
    assert r.status_code == 422, r.text
    assert "too long" in r.json()["detail"]


def test_nul_bytes_in_document_text_are_removed():
    parsed = parse_document_binary(filename="a.txt", binary=b"before\x00after\nnext line\n", parser_config={})
    joined = "\n".join(parsed["sections"])
    assert "\x00" not in joined and "beforeafter" in joined


@pytest.mark.asyncio
async def test_safety_net_only_converts_data_errors():
    """Real database failures (e.g. a constraint violation or lost connection) must still be
    500s; only SQLSTATE class 22 ("data exception") is the client's fault."""
    from sqlalchemy.exc import DBAPIError

    from backend.app.main import _invalid_input

    class FakeDriverError(Exception):
        def __init__(self, sqlstate):
            super().__init__(sqlstate)
            self.sqlstate = sqlstate

    request = type("Req", (), {"method": "POST", "url": type("U", (), {"path": "/x"})()})()

    too_long = DBAPIError("stmt", {}, FakeDriverError("22001"))
    assert (await _invalid_input(request, too_long)).status_code == 422

    for state in ("23505", "08006", None):  # unique violation, connection failure, unknown
        err = DBAPIError("stmt", {}, FakeDriverError(state))
        with pytest.raises(DBAPIError):
            await _invalid_input(request, err)
