"""End-to-end: upload -> parse -> chunk -> embed -> index -> search -> streamed chat.

Runs against the real dev stack (Postgres, MinIO, OpenSearch, Redis) through the HTTP API
and the real Celery task code. Only two things are substituted:

- Celery broker: tasks enqueued with `apply_async` are captured and executed in-process
  with `.apply()` (what a worker would do), so no worker process is needed.
- Embedding model and LLM: a deterministic hashed bag-of-words embedding (so vector search
  still ranks lexically similar text higher) and a fake streaming LLM that records its prompt.

Skipped automatically when OpenSearch or MinIO is not reachable.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.main import create_app
from backend.app.services.embeddings import EmbeddingResult, EmbeddingService
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService
from backend.app.tasks.indexing import index_document
from backend.app.tasks.parsing import parse_document

from test_chat_stream import _parse_sse

SOLAR_DOC = b"""# Solar panel care

Photovoltaic panels convert sunlight into electricity. Dust and pollen on the glass
reduce output, so clean the photovoltaic panels twice a year with soft water and a
non-abrasive brush. Never use a pressure washer on photovoltaic panels.
"""

BREAD_DOC = b"""# Sourdough basics

A sourdough starter is a culture of wild yeast and lactic acid bacteria. Feed the
starter with flour and water daily, and bake once it doubles within six hours.
"""

# Same topic as SOLAR_DOC, but in a different knowledge base: must never be returned.
OTHER_KB_DOC = b"""# Photovoltaic warranty

Clean photovoltaic panels are covered by the warranty for twenty-five years.
"""

QUERY = "How should I clean photovoltaic panels?"


def _stack_available() -> bool:
    try:
        httpx.get(settings.opensearch_url, timeout=2.0)
        httpx.get(f"{settings.s3_endpoint_url.rstrip('/')}/minio/health/live", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


class HashEmbedding(EmbeddingService):
    """Deterministic stand-in for a real embedding model: L2-normalised hashed word counts."""

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        dim = int(settings.embedding_dimension)
        vectors = []
        for text in texts:
            vec = [0.0] * dim
            for word in re.findall(r"\w+", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return EmbeddingResult(vectors=vectors, dimension=dim)


def _fake_embedding_factory(cfg, cache=None):
    # No cache: the Redis cache key includes provider/model, so caching these vectors
    # would poison lookups for the real model configured in settings.
    return HashEmbedding(cfg, cache=None)


@dataclass
class TaskQueue:
    """Captures Celery `apply_async` calls and runs them like a worker would."""

    pending: list[tuple[object, list]] = field(default_factory=list)

    def capture(self, task):
        def fake_apply_async(args=None, kwargs=None, **_options):
            self.pending.append((task, list(args or [])))
            return type("FakeAsyncResult", (), {"id": f"e2e-{uuid.uuid4()}"})()

        return fake_apply_async

    async def drain(self) -> list[dict]:
        """Run queued tasks (and anything they enqueue) until the queue is empty."""
        results = []
        while self.pending:
            task, args = self.pending.pop(0)
            # Tasks call asyncio.run(), so they must run outside this test's event loop.
            eager = await asyncio.to_thread(task.apply, args=args)
            results.append({"task": task.name, **eager.get()})
        return results


def _cleanup_tenant_data(tenant_id: uuid.UUID) -> None:
    os_client = OpenSearchService()._client()  # noqa: SLF001
    os_client.indices.delete(index=f"{OpenSearchService.get_index_name(tenant_id)}*", ignore=[404])

    storage = StorageService()
    minio = storage._client  # noqa: SLF001
    bucket = StorageService.bucket_for_tenant(tenant_id)
    if minio.bucket_exists(bucket):
        for obj in minio.list_objects(bucket, recursive=True):
            minio.remove_object(bucket, obj.object_name)
        minio.remove_bucket(bucket)


@pytest.mark.asyncio
async def test_upload_to_streamed_answer(monkeypatch):
    from backend.app.api.v1 import chat as chat_module
    from backend.app.services import search as search_module
    from backend.app.tasks import indexing as indexing_module

    queue = TaskQueue()
    monkeypatch.setattr(parse_document, "apply_async", queue.capture(parse_document))
    monkeypatch.setattr(index_document, "apply_async", queue.capture(index_document))
    monkeypatch.setattr(indexing_module, "create_embedding_service", _fake_embedding_factory)
    monkeypatch.setattr(search_module, "create_embedding_service", _fake_embedding_factory)

    prompts: list = []

    class RecordingLLM(chat_module.LLMService):
        async def generate(self, messages):
            raise AssertionError("streaming endpoint must not call generate()")

        async def generate_stream(self, messages):
            prompts.append(messages)
            for fragment in ["Clean them ", "twice a year."]:
                yield fragment

    monkeypatch.setattr(chat_module, "_make_llm_service", lambda: RecordingLLM(chat_module.default_llm_config()))

    tenant_id: uuid.UUID | None = None
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
        try:
            # --- Account, tenant and knowledge bases --------------------------------------
            r = await client.post(
                "/api/v1/auth/register",
                json={"email": f"e2e_{uuid.uuid4().hex}@example.com", "password": "pw"},
            )
            assert r.status_code == 200, r.text
            auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await client.get("/api/v1/tenants", headers=auth)
            assert r.status_code == 200, r.text
            tenant_id = uuid.UUID(r.json()[0]["id"])
            headers = {**auth, "X-Tenant-ID": str(tenant_id)}

            kb_ids = {}
            for name in ("kb-a", "kb-b"):
                r = await client.post("/api/v1/knowledgebases", json={"name": name}, headers=headers)
                assert r.status_code == 200, r.text
                kb_ids[name] = r.json()["id"]

            # --- Upload (real MinIO) -------------------------------------------------------
            doc_ids = {}
            for kb, filename, body in [
                ("kb-a", "solar.md", SOLAR_DOC),
                ("kb-a", "bread.md", BREAD_DOC),
                ("kb-b", "warranty.md", OTHER_KB_DOC),
            ]:
                r = await client.post(
                    f"/api/v1/knowledgebases/{kb_ids[kb]}/documents",
                    files={"file": (filename, body, "text/markdown")},
                    headers=headers,
                )
                assert r.status_code == 200, r.text
                doc_ids[filename] = r.json()["id"]
                assert r.json()["status"] == "pending"

            # --- Parse + chunk, then embed + index (real task code) ------------------------
            results = await queue.drain()
            statuses = sorted((res["task"].rsplit(".", 1)[-1], res["status"]) for res in results)
            assert statuses == [("index_document", "indexed")] * 3 + [("parse_document", "done")] * 3, results

            for filename, doc_id in doc_ids.items():
                r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
                assert r.status_code == 200, r.text
                doc = r.json()
                assert doc["status"] == "indexed", (filename, doc)
                assert doc["parse_progress"] == 1.0 and doc["index_progress"] == 1.0
                assert doc["error_message"] is None

            r = await client.get(f"/api/v1/documents/{doc_ids['solar.md']}/chunks", headers=headers)
            assert r.status_code == 200, r.text
            solar_chunks = r.json()["items"]
            assert solar_chunks and "pressure washer" in " ".join(c["content"] for c in solar_chunks)

            # OpenSearch makes new documents searchable on its refresh interval; force it.
            os_client = OpenSearchService()._client()  # noqa: SLF001
            os_client.indices.refresh(index=OpenSearchService.get_index_name(tenant_id))

            # --- Hybrid search (real OpenSearch BM25 + k-NN) -------------------------------
            r = await client.post(
                f"/api/v1/knowledgebases/{kb_ids['kb-a']}/search",
                json={"query": QUERY, "top_k": 5},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            hits = r.json()["hits"]
            assert hits, "expected search hits"
            assert hits[0]["doc_id"] == doc_ids["solar.md"]
            assert {h["doc_id"] for h in hits} <= {doc_ids["solar.md"], doc_ids["bread.md"]}, (
                "search leaked a document from another knowledge base"
            )

            # --- Streamed RAG chat ---------------------------------------------------------
            r = await client.post(
                "/api/v1/chat/sessions", json={"kb_ids": [kb_ids["kb-a"]]}, headers=headers
            )
            assert r.status_code == 201, r.text
            session_id = r.json()["id"]

            r = await client.post(
                f"/api/v1/chat/sessions/{session_id}/messages/stream",
                json={"content": QUERY, "top_k": 3},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            events = _parse_sse(r.text)
            assert [e for e, _ in events] == ["meta", "delta", "delta", "done"]

            # The retrieved chunk text actually reached the model's prompt.
            prompt_text = "\n".join(m.content for m in prompts[0])
            assert "pressure washer" in prompt_text
            assert "twenty-five years" not in prompt_text  # kb-b content must not leak
            assert prompts[0][-1].role == "user" and prompts[0][-1].content == QUERY

            # Citations point at the real document and resolve to a real chunk.
            done = events[-1][1]
            assert done["content"] == "Clean them twice a year."
            top = done["citations"][0]
            assert top["doc_id"] == doc_ids["solar.md"]
            assert top["kb_id"] == kb_ids["kb-a"]
            r = await client.get(f"/api/v1/chunks/{top['chunk_id']}", headers=headers)
            assert r.status_code == 200, r.text
            assert "photovoltaic" in r.json()["content"].lower()

            # The exchange is persisted in the session history.
            r = await client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
            assert [(m["role"], m["content"]) for m in r.json()["items"]] == [
                ("user", QUERY),
                ("assistant", "Clean them twice a year."),
            ]
        finally:
            if tenant_id is not None:
                await asyncio.to_thread(_cleanup_tenant_data, tenant_id)
