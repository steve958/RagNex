from __future__ import annotations

import uuid

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.models.document import Chunk, Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.models.tenant import Tenant
from backend.app.tasks.indexing import index_document


class _DummyCache:
    async def get(self, key: str):
        return None

    async def set(self, key: str, value, ttl: int = 3600):
        return None


@pytest.mark.asyncio
async def test_indexing_task_indexes_chunks_and_updates_document(monkeypatch):
    # Avoid Redis.
    monkeypatch.setattr("backend.app.tasks.indexing.CacheService", lambda: _DummyCache())

    # Force small embedding dimension so we don't depend on a real model.
    monkeypatch.setattr("backend.app.tasks.indexing.settings.embedding_dimension", 3)

    class _FakeEmbedder:
        async def embed_cached(self, texts: list[str]):
            # 3-dim vectors, stable ordering
            return type("Res", (), {"vectors": [[1.0, 0.0, 0.0] for _ in texts], "dimension": 3})()

    monkeypatch.setattr("backend.app.tasks.indexing.create_embedding_service", lambda cfg, cache=None: _FakeEmbedder())

    captured = {"actions": None}

    def fake_bulk(client, actions, raise_on_error=False, raise_on_exception=False, **_kwargs):
        captured["actions"] = list(actions)
        return (len(captured["actions"]), [])

    monkeypatch.setattr("backend.app.tasks.indexing.bulk", fake_bulk)

    monkeypatch.setattr("backend.app.tasks.indexing.OpenSearchService.ensure_index", lambda self, tenant_id: "chunks_test")
    monkeypatch.setattr("backend.app.tasks.indexing.OpenSearchService._client", lambda self: object())

    eng = get_engine()
    Session = async_sessionmaker(eng, expire_on_commit=False)

    tenant_id = uuid.uuid4()

    async with Session() as db:
        t = Tenant(id=tenant_id, name="t")
        db.add(t)
        await db.flush()

        kb = KnowledgeBase(tenant_id=tenant_id, name="kb")
        db.add(kb)
        await db.flush()

        doc = Document(tenant_id=tenant_id, kb_id=kb.id, filename="a.txt", status="done")
        db.add(doc)
        await db.flush()

        # Two chunks.
        db.add_all(
            [
                Chunk(tenant_id=tenant_id, document_id=doc.id, seq=0, content="hello", position={}),
                Chunk(tenant_id=tenant_id, document_id=doc.id, seq=1, content="world", position={}),
            ]
        )
        await db.commit()
        doc_id = doc.id

    # Run task in a background thread so it can use asyncio.run internally.
    await anyio.to_thread.run_sync(lambda: index_document.run(str(doc_id), str(tenant_id)))

    assert captured["actions"] is not None
    assert len(captured["actions"]) == 2
    assert captured["actions"][0]["content"] == "hello"
    assert captured["actions"][1]["content"] == "world"

    async with Session() as db:
        row = (
            await db.execute(
                sa.text("select status, index_progress, index_message from documents where id=:id"),
                {"id": doc_id},
            )
        ).mappings().one()
        assert row["status"] == "indexed"
        assert float(row["index_progress"]) == 1.0
        assert row["index_message"] == "indexed"
