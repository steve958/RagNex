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
        # The two queries run side by side, so tell them apart by kind, not by order.
        def search(self, index=None, body=None):
            if "bool" in body["query"]:
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

    monkeypatch.setattr("backend.app.services.search.OpenSearchService._client", lambda self: _FakeClient())
    # Fake doc ids ("d1") are not in Postgres; deletion filtering is tested separately.
    async def keep_all(self, tenant_id, hits):
        return hits

    monkeypatch.setattr("backend.app.services.search.SearchService._drop_deleted", keep_all)

    hits = await svc.search(tenant_id=tenant_id, kb_ids=[kb_id], query="q", top_k=3, rrf_k=1)

    # B appears in both lists, should win.
    assert hits[0].chunk_id == "B"
    assert {h.chunk_id for h in hits} == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_kb_search_endpoint(monkeypatch):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    # Patch search service to avoid OpenSearch in API test.
    async def fake_search(self, *, tenant_id, kb_ids, query, top_k=10, **kwargs):
        from backend.app.services.search import SearchHit

        return [
            SearchHit(chunk_id="c1", doc_id="d1", kb_id=str(kb_ids[0]), tenant_id=str(tenant_id), content="hello", score=1.0, source="hybrid")
        ]

    monkeypatch.setattr("backend.app.services.search.SearchService.search", fake_search)

    eng = get_engine()
    Session = async_sessionmaker(eng, expire_on_commit=False)

    email = f"u_{uuid.uuid4().hex}@example.com"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": "test-password-1"})
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


@pytest.mark.asyncio
async def test_search_filters_on_every_requested_knowledge_base(monkeypatch):
    """Both the BM25 and the k-NN query must be restricted to exactly the requested KBs."""
    tenant_id = uuid.uuid4()
    kb_ids = [uuid.uuid4(), uuid.uuid4()]

    class _Embedder:
        async def embed_cached(self, texts):
            from backend.app.services.embeddings import EmbeddingResult

            return EmbeddingResult(vectors=[[0.1, 0.2, 0.3]], dimension=3)

    bodies: list[dict] = []

    class _Client:
        def search(self, index=None, body=None):
            bodies.append(body)
            return {"hits": {"hits": []}}

    async def fake_load_cfg(self, tid):
        from backend.app.services.embeddings import EmbeddingConfig

        return EmbeddingConfig()

    monkeypatch.setattr("backend.app.services.search.SearchService._load_embedding_config", fake_load_cfg)
    monkeypatch.setattr("backend.app.services.search.create_embedding_service", lambda cfg, cache=None: _Embedder())
    monkeypatch.setattr("backend.app.services.search.settings.embedding_dimension", 3)
    monkeypatch.setattr("backend.app.services.search.OpenSearchService._client", lambda self: _Client())

    await SearchService().search(tenant_id=tenant_id, kb_ids=kb_ids, query="q", top_k=3)

    expected = {"terms": {"kb_id": sorted(str(k) for k in kb_ids)}}
    (bm25,) = [b for b in bodies if "bool" in b["query"]]
    (knn,) = [b for b in bodies if "knn" in b["query"]]
    bm25_filters = bm25["query"]["bool"]["filter"]
    knn_filters = knn["query"]["knn"]["content_vector"]["filter"]["bool"]["filter"]
    for filters in (bm25_filters, knn_filters):
        assert expected in filters
        assert {"term": {"tenant_id": str(tenant_id)}} in filters


@pytest.mark.asyncio
async def test_search_requires_at_least_one_knowledge_base():
    with pytest.raises(ValueError, match="kb_ids"):
        await SearchService().search(tenant_id=uuid.uuid4(), kb_ids=[], query="q")


def _search_with_client(monkeypatch, client):
    async def fake_load_cfg(self, tid):
        from backend.app.services.embeddings import EmbeddingConfig

        return EmbeddingConfig()

    class _Embedder:
        async def embed_cached(self, texts):
            from backend.app.services.embeddings import EmbeddingResult

            return EmbeddingResult(vectors=[[0.1, 0.2, 0.3]], dimension=3)

    monkeypatch.setattr("backend.app.services.search.SearchService._load_embedding_config", fake_load_cfg)
    monkeypatch.setattr("backend.app.services.search.create_embedding_service", lambda cfg, cache=None: _Embedder())
    monkeypatch.setattr("backend.app.services.search.settings.embedding_dimension", 3)
    monkeypatch.setattr("backend.app.services.search.OpenSearchService._client", lambda self: client)
    return SearchService().search(tenant_id=uuid.uuid4(), kb_ids=[uuid.uuid4()], query="q", top_k=3)


@pytest.mark.asyncio
async def test_search_only_reads(monkeypatch):
    """Search used to write the index template and check the index on every request, a
    cluster-state write each time. It only queries."""
    calls = []

    class _Client:
        @property
        def indices(self):
            raise AssertionError("search must not manage indices")

        @property
        def transport(self):
            raise AssertionError("search must not manage policies")

        def search(self, index=None, body=None):
            calls.append(index)
            return {"hits": {"hits": []}}

    assert await _search_with_client(monkeypatch, _Client()) == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_search_does_not_fetch_stored_vectors(monkeypatch):
    """Returning each hit's vector made responses about ten times larger (455 KB instead of
    40 KB for 20 hits), all parsed and thrown away."""
    bodies = []

    class _Client:
        def search(self, index=None, body=None):
            bodies.append(body)
            return {"hits": {"hits": []}}

    await _search_with_client(monkeypatch, _Client())
    for body in bodies:
        assert "content_vector" not in body["_source"]
        assert "content" in body["_source"]


@pytest.mark.asyncio
async def test_search_runs_its_queries_off_the_event_loop(monkeypatch):
    """The OpenSearch client blocks; run on the event loop, one slow query held up every
    other request in that API process."""
    import threading

    main = threading.get_ident()
    threads = []

    class _Client:
        def search(self, index=None, body=None):
            threads.append(threading.get_ident())
            return {"hits": {"hits": []}}

    await _search_with_client(monkeypatch, _Client())
    assert len(threads) == 2 and main not in threads


@pytest.mark.asyncio
async def test_search_without_an_index_finds_nothing(monkeypatch):
    """A workspace whose index doesn't exist yet has nothing indexed: no hits, not an error."""
    from opensearchpy.exceptions import NotFoundError

    class _Client:
        def search(self, index=None, body=None):
            raise NotFoundError(404, "index_not_found_exception", {})

    assert await _search_with_client(monkeypatch, _Client()) == []


@pytest.mark.asyncio
async def test_search_reuses_database_connections():
    """Search read the workspace's embedding settings through a new engine each time: a new
    database connection per search, a large part of a search's cost under load."""
    from sqlalchemy import event
    from sqlalchemy.pool import Pool

    svc = SearchService()
    tenant_id = uuid.uuid4()
    await svc._load_embedding_config(tenant_id)  # warm up the shared pool

    opened = []

    def listener(*_args):
        opened.append(1)

    event.listen(Pool, "connect", listener)
    try:
        for _ in range(3):
            await svc._load_embedding_config(tenant_id)
    finally:
        event.remove(Pool, "connect", listener)
    assert opened == []
