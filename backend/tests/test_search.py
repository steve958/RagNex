from __future__ import annotations

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.search import SearchService


@pytest.mark.asyncio
async def test_search_service_hybrid_rrf(monkeypatch):
    svc = SearchService()

    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Skip DB embed config loading.
    async def fake_load_cfg(self, tenant_id):
        from backend.app.services.embeddings import EmbeddingConfig

        return EmbeddingConfig(provider="ollama", model="m", rps=0)

    monkeypatch.setattr("backend.app.services.search.SearchService._load_embedding_config", fake_load_cfg)

    class _FakeEmbedder:
        async def embed_cached(self, texts: list[str]):
            return type("Res", (), {"vectors": [[0.0, 0.0, 0.0]], "dimension": 3})()

    monkeypatch.setattr("backend.app.services.search.create_embedding_service", lambda cfg, cache=None: _FakeEmbedder())
    monkeypatch.setattr("backend.app.services.search.settings.embedding_dimension", 3)

    # Fake OpenSearch.
    class _FakeClient:
        def __init__(self):
            self.calls = 0

        def search(self, index=None, body=None):
            self.calls += 1
            if self.calls == 1:
                # BM25 ranking: A, B
                return {
                    "hits": {
                        "hits": [
                            {"_id": "A", "_score": 10, "_source": {"chunk_id": "A", "doc_id": "d1", "kb_id": str(kb_id), "tenant_id": str(tenant_id), "content": "alpha"}},
                            {"_id": "B", "_score": 9, "_source": {"chunk_id": "B", "doc_id": "d1", "kb_id": str(kb_id), "tenant_id": str(tenant_id), "content": "beta"}},
                        ]
                    }
                }
            # Vector ranking: B, C
            return {
                "hits": {
                    "hits": [
                        {"_id": "B", "_score": 0.9, "_source": {"chunk_id": "B", "doc_id": "d1", "kb_id": str(kb_id), "tenant_id": str(tenant_id), "content": "beta"}},
                        {"_id": "C", "_score": 0.8, "_source": {"chunk_id": "C", "doc_id": "d2", "kb_id": str(kb_id), "tenant_id": str(tenant_id), "content": "gamma"}},
                    ]
                }
            }

    monkeypatch.setattr("backend.app.services.search.OpenSearchService.ensure_index", lambda self, tid: "chunks_test")
    monkeypatch.setattr("backend.app.services.search.OpenSearchService._client", lambda self: _FakeClient())
    # Fake doc ids ("d1") are not in Postgres; deletion filtering is tested separately.
    async def keep_all(self, tenant_id, hits):
        return hits

    monkeypatch.setattr("backend.app.services.search.SearchService._drop_deleted", keep_all)

    hits = await svc.search(tenant_id=tenant_id, kb_id=kb_id, query="q", top_k=3, rrf_k=1)

    # B appears in both lists, should win.
    assert hits[0].chunk_id == "B"
    assert {h.chunk_id for h in hits} == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_kb_search_endpoint(monkeypatch):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    # Patch search service to avoid OpenSearch in API test.
    async def fake_search(self, *, tenant_id, kb_id, query, top_k=10, **kwargs):
        from backend.app.services.search import SearchHit

        return [
            SearchHit(chunk_id="c1", doc_id="d1", kb_id=str(kb_id), tenant_id=str(tenant_id), content="hello", score=1.0, source="hybrid")
        ]

    monkeypatch.setattr("backend.app.services.search.SearchService.search", fake_search)

    eng = get_engine()
    Session = async_sessionmaker(eng, expire_on_commit=False)

    email = f"u_{uuid.uuid4().hex}@example.com"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": "pw"})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        async with Session() as db:
            tenant_id = (
                await db.execute(
                    sa.text(
                        "select t.id from tenants t join tenant_memberships m on m.tenant_id=t.id join users u on u.id=m.user_id where u.email=:email limit 1"
                    ),
                    {"email": email},
                )
            ).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

        r = await client.post(
            f"/api/v1/knowledgebases/{kb_id}/search",
            json={"query": "hello", "top_k": 5},
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hits"][0]["chunk_id"] == "c1"
        assert body["hits"][0]["content"] == "hello"
