"""Reprocessing documents: parse and index the stored file again. Real dev stack."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.models.document import Chunk, Document
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService

from format_samples import MARKER, docx
from test_deletion import SOLAR_DOC, Api, _index_count, _with_api, pipeline  # noqa: F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


def _break_parsing(monkeypatch) -> list:
    """Make parsing fail until the returned switch is set (simulates e.g. the old DOCX bug)."""
    import backend.app.tasks.parsing as parsing_task

    real = parsing_task.parse_document_binary
    fixed: list = []

    def maybe_broken(**kwargs):
        if not fixed:
            raise TypeError("parser called with the wrong arguments")
        return real(**kwargs)

    monkeypatch.setattr(parsing_task, "parse_document_binary", maybe_broken)
    return fixed


async def _status(api: Api, doc: str) -> dict:
    r = await api.client.get(f"/api/v1/documents/{doc}", headers=api.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _reprocess(api: Api, doc: str):
    return await api.client.post(f"/api/v1/documents/{doc}/reprocess", headers=api.headers)


async def _set_doc(doc: str, **values) -> None:
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        await db.execute(sa.update(Document).where(Document.id == uuid.UUID(doc)).values(**values))
        await db.commit()


async def _chunk_ids(doc: str) -> set[str]:
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        rows = await db.execute(sa.select(Chunk.id).where(Chunk.document_id == uuid.UUID(doc)))
        return {str(i) for i in rows.scalars().all()}


def _refresh(tenant_id) -> None:
    OpenSearchService()._client().indices.refresh(index=OpenSearchService.get_index_name(tenant_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_failed_document_recovers_after_reprocessing(pipeline, monkeypatch):
    fixed = _break_parsing(monkeypatch)

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "report.docx", docx())
        await pipeline.drain()
        before = await _status(api, doc)
        assert before["status"] == "failed" and "wrong arguments" in before["error_message"]

        fixed.append(True)  # e.g. the parser fix was deployed
        r = await _reprocess(api, doc)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending" and r.json()["error_message"] is None

        results = await pipeline.drain()
        assert [x["status"] for x in results] == ["done", "indexed"], results
        after = await _status(api, doc)
        assert after["status"] == "indexed" and after["error_message"] is None

        _refresh(api.tenant_id)
        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb}/search", json={"query": MARKER}, headers=api.headers
        )
        assert doc in {h["doc_id"] for h in r.json()["hits"]}

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_reprocessing_replaces_index_entries_instead_of_adding(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)
        await pipeline.drain()
        old_chunks = await _chunk_ids(doc)
        assert _index_count(api.tenant_id, doc) == len(old_chunks) > 0

        assert (await _reprocess(api, doc)).status_code == 200
        await pipeline.drain()

        new_chunks = await _chunk_ids(doc)
        assert new_chunks and not (new_chunks & old_chunks), "chunks should be re-created"
        _refresh(api.tenant_id)
        assert _index_count(api.tenant_id, doc) == len(new_chunks), "stale index entries left behind"

        # Every search hit resolves to a chunk that exists.
        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb}/search", json={"query": "photovoltaic panels"}, headers=api.headers
        )
        hits = r.json()["hits"]
        assert hits
        for h in hits:
            assert (await api.client.get(f"/api/v1/chunks/{h['chunk_id']}", headers=api.headers)).status_code == 200

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_document_in_progress_is_refused_unless_stuck(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)  # queued, not yet processed: "pending"

        r = await _reprocess(api, doc)
        assert r.status_code == 409 and "already being processed" in r.json()["detail"]

        # A document stuck "parsing" for an hour (its worker died) can be reprocessed.
        stale = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        await _set_doc(doc, status="parsing", updated_at=stale)
        pipeline.pending.clear()  # the original task never ran
        r = await _reprocess(api, doc)
        assert r.status_code == 200, r.text
        results = await pipeline.drain()
        assert [x["status"] for x in results] == ["done", "indexed"]

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_missing_file_is_refused_with_a_clear_reason(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)
        await pipeline.drain()

        Session = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with Session() as db:
            key = (await db.execute(sa.select(Document.storage_key).where(Document.id == uuid.UUID(doc)))).scalar_one()
        await StorageService().delete_file(api.tenant_id, key)

        r = await _reprocess(api, doc)
        assert r.status_code == 409 and "Upload the document again" in r.json()["detail"]
        assert (await _status(api, doc))["status"] == "indexed", "a refused reprocess must not change the document"

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_reprocess_respects_tenant_deletion_and_key_scopes(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "solar.md", SOLAR_DOC)
        await pipeline.drain()

        # Another tenant's user can't reach it.
        other = Api(api.client)
        await other.register()
        assert (await api.client.post(f"/api/v1/documents/{doc}/reprocess", headers=other.headers)).status_code == 404

        # A read-only API key can't trigger it.
        r = await api.client.post("/api/v1/api-keys", json={"name": "ro", "scopes": ["read"]}, headers=api.headers)
        read_key = {"X-API-Key": r.json()["api_key"], "X-Tenant-ID": str(api.tenant_id)}
        assert (await api.client.post(f"/api/v1/documents/{doc}/reprocess", headers=read_key)).status_code == 403

        # A deleted document is gone.
        assert (await api.client.delete(f"/api/v1/documents/{doc}", headers=api.headers)).status_code == 200
        assert (await _reprocess(api, doc)).status_code == 404

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_reprocess_failed_queues_only_failed_documents(pipeline, monkeypatch):
    fixed = _break_parsing(monkeypatch)

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        failed_a = await api.upload(kb, "a.md", SOLAR_DOC)
        failed_b = await api.upload(kb, "b.docx", docx())
        missing = await api.upload(kb, "c.md", SOLAR_DOC)
        await pipeline.drain()  # all three fail
        fixed.append(True)
        healthy = await api.upload(kb, "d.md", SOLAR_DOC)
        await pipeline.drain()
        assert (await _status(api, healthy))["status"] == "indexed"

        Session = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with Session() as db:
            key = (
                await db.execute(sa.select(Document.storage_key).where(Document.id == uuid.UUID(missing)))
            ).scalar_one()
        await StorageService().delete_file(api.tenant_id, key)

        r = await api.client.post(f"/api/v1/knowledgebases/{kb}/documents/reprocess-failed", headers=api.headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["queued"]) == {failed_a, failed_b}
        assert [(s["id"], s["filename"]) for s in body["skipped"]] == [(missing, "c.md")]
        assert "Upload the document again" in body["skipped"][0]["reason"]

        await pipeline.drain()
        for d in (failed_a, failed_b, healthy):
            assert (await _status(api, d))["status"] == "indexed"
        assert (await _status(api, missing))["status"] == "failed"

    await _with_api(scenario)
