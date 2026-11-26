"""Deleting documents and knowledge bases, against the real dev stack.

Deletion is two-phase: marking deleted hides content immediately (search, chunk and chat
endpoints), and a background purge removes the index entries, chunk rows and stored file.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.document import Chunk, Document
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService
from backend.app.tasks.indexing import index_document
from backend.app.tasks.parsing import parse_document
from backend.app.tasks.purge import purge_document

from test_chat_stream import _parse_sse
from test_e2e_pipeline import (
    BREAD_DOC,
    SOLAR_DOC,
    TaskQueue,
    _cleanup_tenant_data,
    _fake_embedding_factory,
    _stack_available,
)

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")

QUERY = "How should I clean photovoltaic panels?"


@pytest.fixture
def pipeline(monkeypatch):
    """Capture Celery tasks, fake the embedding model and LLM. Yields the task queue."""
    from backend.app.api.v1 import chat as chat_module
    from backend.app.services import search as search_module
    from backend.app.tasks import indexing as indexing_module

    queue = TaskQueue()
    for task in (parse_document, index_document, purge_document):
        monkeypatch.setattr(task, "apply_async", queue.capture(task))
    monkeypatch.setattr(indexing_module, "create_embedding_service", _fake_embedding_factory)
    monkeypatch.setattr(search_module, "create_embedding_service", _fake_embedding_factory)

    class EchoLLM(chat_module.LLMService):
        async def generate(self, messages):
            return chat_module.LLMResult(content="answer")

        async def generate_stream(self, messages):
            yield "answer"

    monkeypatch.setattr(chat_module, "_make_llm_service", lambda cfg: EchoLLM(cfg))
    return queue


class Api:
    """Small helper around the HTTP API for one freshly registered user."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.headers: dict = {}
        self.tenant_id: uuid.UUID | None = None

    async def register(self) -> None:
        r = await self.client.post(
            "/api/v1/auth/register", json={"email": f"del_{uuid.uuid4().hex}@example.com", "password": "pw"}
        )
        assert r.status_code == 200, r.text
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await self.client.get("/api/v1/tenants", headers=auth)
        self.tenant_id = uuid.UUID(r.json()[0]["id"])
        self.headers = {**auth, "X-Tenant-ID": str(self.tenant_id)}

    async def create_kb(self, name: str) -> str:
        r = await self.client.post("/api/v1/knowledgebases", json={"name": name}, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    async def upload(self, kb_id: str, filename: str, body: bytes) -> str:
        r = await self.client.post(
            f"/api/v1/knowledgebases/{kb_id}/documents",
            files={"file": (filename, body, "text/markdown")},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    async def search(self, kb_id: str) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/knowledgebases/{kb_id}/search", json={"query": QUERY, "top_k": 5}, headers=self.headers
        )

    async def chunk_ids(self, doc_id: str) -> list[str]:
        r = await self.client.get(f"/api/v1/documents/{doc_id}/chunks", headers=self.headers)
        assert r.status_code == 200, r.text
        return [c["id"] for c in r.json()["items"]]


def _index_count(tenant_id: uuid.UUID, doc_id: str) -> int:
    from opensearchpy.exceptions import NotFoundError

    client = OpenSearchService()._client()  # noqa: SLF001
    try:
        resp = client.count(
            index=OpenSearchService.get_index_name(tenant_id), body={"query": {"term": {"doc_id": doc_id}}}
        )
    except NotFoundError:
        return 0  # tenant never had anything indexed
    return int(resp["count"])


async def _db_state(doc_id: str) -> tuple[int, str | None]:
    """(number of chunk rows, storage_key) for a document."""
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        rows = (await db.execute(sa.select(sa.func.count()).where(Chunk.document_id == uuid.UUID(doc_id)))).scalar_one()
        key = (await db.execute(sa.select(Document.storage_key).where(Document.id == uuid.UUID(doc_id)))).scalar_one()
    return int(rows), key


def _object_exists(tenant_id: uuid.UUID, key: str) -> bool:
    storage = StorageService()
    try:
        storage._client.stat_object(StorageService.bucket_for_tenant(tenant_id), key)  # noqa: SLF001
        return True
    except Exception:
        return False


async def _with_api(test):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
        api = Api(client)
        try:
            await api.register()
            await test(api)
        finally:
            if api.tenant_id is not None:
                await asyncio.to_thread(_cleanup_tenant_data, api.tenant_id)


@pytest.mark.asyncio
async def test_deleted_document_is_hidden_immediately_and_purged(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        solar = await api.upload(kb, "solar.md", SOLAR_DOC)
        bread = await api.upload(kb, "bread.md", BREAD_DOC)
        await pipeline.drain()

        solar_chunks = await api.chunk_ids(solar)
        _, storage_key = await _db_state(solar)
        assert _index_count(api.tenant_id, solar) > 0 and _object_exists(api.tenant_id, storage_key)
        hits = (await api.search(kb)).json()["hits"]
        assert hits[0]["doc_id"] == solar

        r = await api.client.delete(f"/api/v1/documents/{solar}", headers=api.headers)
        assert r.status_code == 200, r.text
        assert [t.name for t, _ in pipeline.pending] == ["backend.app.tasks.purge.purge_document"]

        # --- Before the purge runs, the document is already gone everywhere it's served ---
        hits = (await api.search(kb)).json()["hits"]
        assert solar not in {h["doc_id"] for h in hits}
        assert bread in {h["doc_id"] for h in hits}, "other documents must still be found"
        r = await api.client.get(f"/api/v1/chunks/{solar_chunks[0]}", headers=api.headers)
        assert r.status_code == 404
        assert (await api.client.get(f"/api/v1/documents/{solar}", headers=api.headers)).status_code == 404

        r = await api.client.post("/api/v1/chat/sessions", json={"kb_ids": [kb]}, headers=api.headers)
        session_id = r.json()["id"]
        r = await api.client.post(
            f"/api/v1/chat/sessions/{session_id}/messages/stream", json={"content": QUERY}, headers=api.headers
        )
        meta = _parse_sse(r.text)[0][1]
        assert solar not in {c["doc_id"] for c in meta["citations"]}

        # --- The purge removes the data itself -------------------------------------------
        [result] = await pipeline.drain()
        assert result["status"] == "purged"
        assert result["index_entries"] == len(solar_chunks) and result["chunk_rows"] == len(solar_chunks)
        assert result["file_removed"] is True
        assert _index_count(api.tenant_id, solar) == 0
        assert await _db_state(solar) == (0, None)
        assert not _object_exists(api.tenant_id, storage_key)
        assert _index_count(api.tenant_id, bread) > 0, "purge must not touch other documents"

        # Idempotent: running it again is harmless.
        again = await asyncio.to_thread(purge_document.apply, args=[solar, str(api.tenant_id)])
        assert again.get()["status"] == "purged" and again.get()["index_entries"] == 0

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_deleted_knowledge_base_hides_content_and_blocks_its_chats(pipeline):
    async def scenario(api: Api):
        keep = await api.create_kb("keep")
        doomed = await api.create_kb("doomed")
        kept_doc = await api.upload(keep, "bread.md", BREAD_DOC)
        doomed_doc = await api.upload(doomed, "solar.md", SOLAR_DOC)
        await pipeline.drain()

        r = await api.client.post("/api/v1/chat/sessions", json={"kb_ids": [doomed]}, headers=api.headers)
        session_id = r.json()["id"]
        r = await api.client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": QUERY}, headers=api.headers
        )
        assert r.status_code == 200, r.text

        r = await api.client.delete(f"/api/v1/knowledgebases/{doomed}", headers=api.headers)
        assert r.status_code == 200, r.text
        assert r.json()["documents_deleted"] == 1

        assert (await api.search(doomed)).status_code == 404
        assert (await api.client.get(f"/api/v1/documents/{doomed_doc}", headers=api.headers)).status_code == 404

        # The chat refuses new questions with a clear reason...
        for path in ("messages", "messages/stream"):
            r = await api.client.post(
                f"/api/v1/chat/sessions/{session_id}/{path}", json={"content": "again"}, headers=api.headers
            )
            assert r.status_code == 400, (path, r.text)
            assert "knowledge base has been deleted" in r.json()["detail"]
        # ...but its history stays readable.
        r = await api.client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=api.headers)
        assert [m["role"] for m in r.json()["items"]] == ["user", "assistant"]

        [result] = await pipeline.drain()
        assert result["document_id"] == doomed_doc and result["status"] == "purged"
        assert _index_count(api.tenant_id, doomed_doc) == 0
        assert _index_count(api.tenant_id, kept_doc) > 0
        assert (await api.search(keep)).status_code == 200

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_document_deleted_mid_pipeline_is_never_indexed(pipeline):
    """Delete after parsing queued indexing: indexing must not write the document back."""

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)

        # Run only the parse task; it queues indexing.
        task, args = pipeline.pending.pop(0)
        assert (await asyncio.to_thread(task.apply, args=args)).get()["status"] == "done"
        assert [t.name for t, _ in pipeline.pending] == ["backend.app.tasks.indexing.index_document"]

        r = await api.client.delete(f"/api/v1/documents/{doc}", headers=api.headers)
        assert r.status_code == 200, r.text

        results = {r["task"].rsplit(".", 1)[-1]: r["status"] for r in await pipeline.drain()}
        assert results == {"index_document": "deleted", "purge_document": "purged"}
        assert _index_count(api.tenant_id, doc) == 0
        assert await _db_state(doc) == (0, None)

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_purge_refuses_a_live_document(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)
        await pipeline.drain()

        result = (await asyncio.to_thread(purge_document.apply, args=[doc, str(api.tenant_id)])).get()
        assert result["status"] == "skipped"
        assert _index_count(api.tenant_id, doc) > 0

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_document_is_marked_failed_if_indexing_cannot_be_queued(pipeline, monkeypatch):
    """Regression: a failure to queue indexing used to be swallowed, leaving the document
    at "done" forever: never searchable, with no error shown."""

    def broker_down(*_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)
        monkeypatch.setattr(index_document, "apply_async", broker_down)

        results = await pipeline.drain()
        assert [r["task"].rsplit(".", 1)[-1] for r in results] == ["parse_document"]

        r = await api.client.get(f"/api/v1/documents/{doc}", headers=api.headers)
        body = r.json()
        assert body["status"] == "failed"
        assert "indexing could not be started" in body["error_message"]

    await _with_api(scenario)
