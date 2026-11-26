"""Backfill for deletions made before purging existed, against the real dev stack."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.deletion_backfill import main, run_backfill

from test_deletion import (  # noqa: F401 (pipeline is a fixture)
    BREAD_DOC,
    SOLAR_DOC,
    Api,
    _db_state,
    _index_count,
    _object_exists,
    _with_api,
    pipeline,
)
from test_e2e_pipeline import _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")

WARRANTY_DOC = b"# Warranty\n\nPanels are covered for twenty-five years.\n"


async def _legacy_delete(*, doc_id: str | None = None, kb_id: str | None = None) -> dt.datetime:
    """Delete the way the API did before purging existed: only set deleted_at."""
    when = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        if doc_id:
            await db.execute(sa.update(Document).where(Document.id == uuid.UUID(doc_id)).values(deleted_at=when))
        if kb_id:
            await db.execute(
                sa.update(KnowledgeBase).where(KnowledgeBase.id == uuid.UUID(kb_id)).values(deleted_at=when)
            )
        await db.commit()
    return when


async def _deleted_at(doc_id: str) -> dt.datetime | None:
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        return (
            await db.execute(sa.select(Document.deleted_at).where(Document.id == uuid.UUID(doc_id)))
        ).scalar_one()


async def _add_deleted_doc_with_missing_file(tenant_id: uuid.UUID, kb_id: str) -> str:
    """A deleted document whose file never reached MinIO (the old upload bug)."""
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        doc = Document(
            tenant_id=tenant_id,
            kb_id=uuid.UUID(kb_id),
            filename="ghost.md",
            status="failed",
            storage_key=f"{uuid.uuid4().hex}/ghost.md",
            deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        db.add(doc)
        await db.commit()
        return str(doc.id)


@pytest.mark.asyncio
async def test_backfill_purges_data_left_by_old_deletions(pipeline):
    async def scenario(api: Api):
        kb_a = await api.create_kb("a")
        kb_b = await api.create_kb("b")
        deleted_doc = await api.upload(kb_a, "solar.md", SOLAR_DOC)
        live_doc = await api.upload(kb_a, "bread.md", BREAD_DOC)
        doc_in_deleted_kb = await api.upload(kb_b, "warranty.md", WARRANTY_DOC)
        await pipeline.drain()

        _, deleted_key = await _db_state(deleted_doc)
        await _legacy_delete(doc_id=deleted_doc)
        kb_deleted_at = await _legacy_delete(kb_id=kb_b)
        ghost = await _add_deleted_doc_with_missing_file(api.tenant_id, kb_a)

        # --- Dry run: reports, changes nothing ------------------------------------------
        report = await run_backfill(tenant_id=api.tenant_id)
        assert report.dry_run
        assert report.documents_marked == 1  # the document in the deleted KB
        assert report.to_purge == 3  # deleted_doc, doc_in_deleted_kb, ghost
        assert await _deleted_at(doc_in_deleted_kb) is None
        assert _index_count(api.tenant_id, deleted_doc) > 0

        # --- Execute ----------------------------------------------------------------------
        report = await run_backfill(execute=True, tenant_id=api.tenant_id)
        assert report.failures == []
        assert (report.documents_marked, report.purged) == (1, 3)

        assert await _deleted_at(doc_in_deleted_kb) == kb_deleted_at
        for doc in (deleted_doc, doc_in_deleted_kb, ghost):
            assert _index_count(api.tenant_id, doc) == 0, doc
            assert await _db_state(doc) == (0, None), doc
        assert not _object_exists(api.tenant_id, deleted_key)

        # The live document is untouched.
        assert await _deleted_at(live_doc) is None
        assert _index_count(api.tenant_id, live_doc) > 0
        assert (await _db_state(live_doc))[0] > 0

        # --- Re-running finds nothing left ------------------------------------------------
        again = await run_backfill(execute=True, tenant_id=api.tenant_id)
        assert (again.documents_marked, again.to_purge, again.purged) == (0, 0, 0)

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_backfill_limit_and_enqueue(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        docs = [await api.upload(kb, f"d{i}.md", SOLAR_DOC) for i in range(3)]
        await pipeline.drain()
        for d in docs:
            await _legacy_delete(doc_id=d)

        report = await run_backfill(execute=True, tenant_id=api.tenant_id, limit=2)
        assert (report.to_purge, report.purged) == (2, 2)

        # --enqueue hands the rest to Celery (captured by the pipeline fixture).
        report = await run_backfill(execute=True, enqueue=True, tenant_id=api.tenant_id)
        assert (report.to_purge, report.enqueued, report.purged) == (1, 1, 0)
        [result] = await pipeline.drain()
        assert result["status"] == "purged"
        assert all(_index_count(api.tenant_id, d) == 0 for d in docs)

    await _with_api(scenario)


def test_cli_rejects_enqueue_without_execute():
    with pytest.raises(SystemExit) as exc:
        main(["--enqueue"])
    assert exc.value.code == 2
