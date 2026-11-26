from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services import model_settings

SECRET = "sk-tenant-secret-0123456789"


class Client:
    """One registered user (the owner of their own tenant) talking to the API."""

    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.auth: dict = {}
        self.user_id = ""
        self.tenant_id = ""

    async def register(self) -> "Client":
        r = await self.http.post(
            "/api/v1/auth/register", json={"email": f"ms_{uuid.uuid4().hex}@example.com", "password": "test-password-1"}
        )
        assert r.status_code == 200, r.text
        self.auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.user_id = (await self.http.get("/api/v1/auth/me", headers=self.auth)).json()["id"]
        self.tenant_id = (await self.http.get("/api/v1/tenants", headers=self.auth)).json()[0]["id"]
        return self

    async def get(self, tenant_id: str | None = None) -> httpx.Response:
        return await self.http.get(f"/api/v1/tenants/{tenant_id or self.tenant_id}/model-settings", headers=self.auth)

    async def put(self, body: dict, tenant_id: str | None = None) -> httpx.Response:
        return await self.http.put(
            f"/api/v1/tenants/{tenant_id or self.tenant_id}/model-settings", json=body, headers=self.auth
        )


@pytest_asyncio.fixture
async def api():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_defaults_come_from_server_settings(api):
    owner = await Client(api).register()
    r = await owner.get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_edit"] is True
    assert body["llm"]["effective"]["provider"] == settings.llm_provider
    assert body["llm"]["effective"]["model"] == settings.llm_model
    assert body["llm"]["effective"]["context_window"] == settings.llm_context_window
    assert body["llm"]["overrides"] == {} and body["llm"]["has_api_key"] is False
    assert body["embedding"]["effective"]["model"] == settings.embedding_model
    assert body["embedding"]["locked"] is False
    assert body["embedding"]["dimension"] == settings.embedding_dimension


@pytest.mark.asyncio
async def test_owner_overrides_and_resets_llm_settings(api):
    owner = await Client(api).register()
    r = await owner.put({"llm": {"model": "mistral", "temperature": 0.7, "context_window": 32768}})
    assert r.status_code == 200, r.text
    llm = r.json()["llm"]
    assert llm["overrides"] == {"model": "mistral", "temperature": 0.7, "context_window": 32768}
    assert llm["effective"]["model"] == "mistral"
    # Defaults always show the server's values, whatever the tenant overrides.
    assert llm["defaults"]["model"] == settings.llm_model
    assert llm["defaults"]["context_window"] == settings.llm_context_window
    assert llm["effective"]["provider"] == settings.llm_provider  # not overridden

    # A section replaces the managed overrides: omitted fields go back to server defaults.
    r = await owner.put({"llm": {"model": "mistral"}})
    assert r.json()["llm"]["overrides"] == {"model": "mistral"}
    assert r.json()["llm"]["effective"]["temperature"] == settings.llm_temperature

    # Omitting a section leaves it untouched.
    r = await owner.put({})
    assert r.json()["llm"]["overrides"] == {"model": "mistral"}

    r = await owner.put({"llm": {}})
    assert r.json()["llm"]["overrides"] == {}


@pytest.mark.asyncio
async def test_api_key_is_write_only(api):
    owner = await Client(api).register()
    r = await owner.put({"llm": {"model": "m", "api_key": SECRET}})
    assert r.status_code == 200 and r.json()["llm"]["has_api_key"] is True
    assert SECRET not in r.text
    assert SECRET not in (await owner.get()).text

    # Omitting api_key keeps it; null clears it.
    r = await owner.put({"llm": {"model": "other"}})
    assert r.json()["llm"]["has_api_key"] is True
    r = await owner.put({"llm": {"model": "other", "api_key": None}})
    assert r.json()["llm"]["has_api_key"] is False


@pytest.mark.asyncio
async def test_members_can_read_but_not_change(api):
    owner = await Client(api).register()
    member = await Client(api).register()
    r = await api.post(
        f"/api/v1/tenants/{owner.tenant_id}/members",
        json={"user_id": member.user_id, "role": "member"},
        headers=owner.auth,
    )
    assert r.status_code == 200, r.text

    r = await member.get(owner.tenant_id)
    assert r.status_code == 200 and r.json()["can_edit"] is False
    r = await member.put({"llm": {"model": "x"}}, owner.tenant_id)
    assert r.status_code == 403

    stranger = await Client(api).register()
    assert (await stranger.get(owner.tenant_id)).status_code == 403


@pytest.mark.asyncio
async def test_base_url_must_be_on_the_server_allowlist(api, monkeypatch):
    owner = await Client(api).register()
    for url in ("http://169.254.169.254/latest", "http://postgres:5432"):
        r = await owner.put({"llm": {"base_url": url}})
        assert r.status_code == 422, url
        assert "not allowed" in r.json()["detail"]

    monkeypatch.setattr(settings, "tenant_model_base_urls", ["http://gpu-box:11434/"])
    r = await owner.put({"llm": {"base_url": "http://gpu-box:11434/"}})
    assert r.status_code == 200, r.text
    assert r.json()["llm"]["effective"]["base_url"] == "http://gpu-box:11434"
    assert r.json()["allowed_base_urls"] == ["http://gpu-box:11434"]


@pytest.mark.asyncio
async def test_switching_to_openai_requires_own_key(api, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    owner = await Client(api).register()
    r = await owner.put({"llm": {"provider": "openai", "model": "gpt-4o-mini"}})
    assert r.status_code == 422
    assert "API key is required" in r.json()["detail"]

    r = await owner.put({"llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": SECRET}})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_invalid_llm_settings_are_rejected(api):
    owner = await Client(api).register()
    r = await owner.put({"llm": {"context_window": 2048, "max_tokens": 2000}})
    assert r.status_code == 422 and "context window" in r.json()["detail"]
    assert (await owner.put({"llm": {"temperature": 5}})).status_code == 422
    assert (await owner.put({"llm": {"provider": "anthropic"}})).status_code == 422
    assert (await owner.put({"llm": {"unknown_field": 1}})).status_code == 422


@pytest.mark.asyncio
async def test_chat_uses_the_tenants_llm_settings(api, monkeypatch):
    from backend.app.api.v1 import chat as chat_module
    from backend.app.services.search import SearchHit

    owner = await Client(api).register()
    r = await owner.put({"llm": {"model": "tenant-model", "temperature": 0.9, "context_window": 16384}})
    assert r.status_code == 200, r.text

    async def fake_search(self, *, tenant_id, kb_ids, query, top_k=10, **_):
        return [SearchHit("c1", "d1", str(kb_ids[0]), str(tenant_id), "ctx", 1.0, "hybrid")]

    used: list = []

    class Recording(chat_module.LLMService):
        async def generate(self, messages):
            return chat_module.LLMResult(content="ok")

    def make(cfg):
        used.append(cfg)
        return Recording(cfg)

    monkeypatch.setattr(chat_module.SearchService, "search", fake_search)
    monkeypatch.setattr(chat_module, "_make_llm_service", make)

    headers = {**owner.auth, "X-Tenant-ID": owner.tenant_id}
    kb = (await api.post("/api/v1/knowledgebases", json={"name": "kb"}, headers=headers)).json()["id"]
    session = (await api.post("/api/v1/chat/sessions", json={"kb_ids": [kb]}, headers=headers)).json()["id"]
    r = await api.post(f"/api/v1/chat/sessions/{session}/messages", json={"content": "hi"}, headers=headers)
    assert r.status_code == 200, r.text

    assert (used[0].model, used[0].temperature, used[0].context_window) == ("tenant-model", 0.9, 16384)
    assert used[0].provider == settings.llm_provider


async def _add_document(tenant_id: str, status: str) -> None:
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        kb = KnowledgeBase(tenant_id=uuid.UUID(tenant_id), name="kb")
        db.add(kb)
        await db.flush()
        db.add(Document(tenant_id=uuid.UUID(tenant_id), kb_id=kb.id, filename="a.md", status=status))
        await db.commit()


@pytest.mark.asyncio
async def test_embedding_model_change_is_probed_for_dimension(api, monkeypatch):
    owner = await Client(api).register()
    probed: list = []

    async def probe(cfg):
        probed.append(cfg)
        return 384 if cfg.model == "small-model" else settings.embedding_dimension

    monkeypatch.setattr(model_settings, "_probe_dimension", probe)

    r = await owner.put({"embedding": {"model": "small-model"}})
    assert r.status_code == 422 and "384-dimensional" in r.json()["detail"]

    r = await owner.put({"embedding": {"model": "good-model"}})
    assert r.status_code == 200, r.text
    assert r.json()["embedding"]["effective"]["model"] == "good-model"
    assert [c.model for c in probed] == ["small-model", "good-model"]

    # Search and indexing read the same stored settings.
    from backend.app.services.search import SearchService

    cfg = await SearchService()._load_embedding_config(uuid.UUID(owner.tenant_id))
    assert cfg.model == "good-model"


@pytest.mark.asyncio
async def test_embedding_model_is_locked_once_documents_are_indexed(api, monkeypatch):
    owner = await Client(api).register()
    monkeypatch.setattr(model_settings, "_probe_dimension", lambda cfg: _dim())
    await _add_document(owner.tenant_id, "indexed")

    assert (await owner.get()).json()["embedding"]["locked"] is True
    r = await owner.put({"embedding": {"model": "another-model"}})
    assert r.status_code == 409 and "indexed documents" in r.json()["detail"]

    # Changes that keep the same model (e.g. the API key) are still allowed.
    r = await owner.put({"embedding": {"api_key": SECRET}})
    assert r.status_code == 200 and r.json()["embedding"]["has_api_key"] is True


@pytest.mark.asyncio
async def test_failed_documents_do_not_lock_the_embedding_model(api, monkeypatch):
    owner = await Client(api).register()
    monkeypatch.setattr(model_settings, "_probe_dimension", lambda cfg: _dim())
    await _add_document(owner.tenant_id, "failed")

    r = await owner.put({"embedding": {"model": "another-model"}})
    assert r.status_code == 200, r.text


async def _dim() -> int:
    return settings.embedding_dimension


@pytest.mark.asyncio
async def test_unreachable_embedding_model_is_rejected(api, monkeypatch):
    owner = await Client(api).register()

    class Broken:
        async def embed(self, texts):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(model_settings, "create_embedding_service", lambda cfg, cache=None: Broken())
    r = await owner.put({"embedding": {"model": "missing-model"}})
    assert r.status_code == 422
    assert "could not use model 'missing-model'" in r.json()["detail"]

    # Nothing was stored.
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        from backend.app.models.tenant import Tenant

        stored = (
            await db.execute(sa.select(Tenant.embedding_config).where(Tenant.id == uuid.UUID(owner.tenant_id)))
        ).scalar_one()
    assert stored == {}
