"""Remove a soft-deleted document's data from search, the database and object storage.

Deletion is two-phase:
  1. The API marks the Document (and, for a KB delete, its KnowledgeBase) deleted. From
     then on search and chunk endpoints ignore it, so the delete takes effect immediately.
  2. This task purges the data itself: OpenSearch entries, chunk rows and the stored file.
     It retries on failure and is idempotent, so it is safe to run more than once.

The Document row is kept (with deleted_at set) as a record of what existed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from celery.exceptions import Retry
from minio.error import S3Error
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.celery_app import celery_app
from backend.app.core.config import settings
from backend.app.models.document import Chunk, Document
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5


async def _purge(document_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session() as db:
            doc = (
                await db.execute(
                    sa.select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if doc is None:
                return {"status": "missing"}
            if doc.deleted_at is None:
                # Never purge a live document, e.g. if the task was queued by mistake.
                return {"status": "skipped", "reason": "document is not deleted"}

            # Search index first: once this succeeds the content can't be retrieved again.
            indexed = await asyncio.to_thread(OpenSearchService().delete_document_chunks, tenant_id, document_id)

            res = await db.execute(
                sa.delete(Chunk).where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
            )
            chunk_rows = res.rowcount or 0

            file_removed = False
            if doc.storage_key:
                try:
                    await StorageService().delete_file(tenant_id, doc.storage_key)
                except S3Error as e:
                    if e.code not in {"NoSuchKey", "NoSuchBucket"}:
                        raise
                file_removed = True
                doc.storage_key = None

            await db.commit()
    finally:
        await eng.dispose()

    return {"status": "purged", "index_entries": indexed, "chunk_rows": chunk_rows, "file_removed": file_removed}


@celery_app.task(bind=True, name="backend.app.tasks.purge.purge_document", max_retries=_MAX_RETRIES)
def purge_document(self, document_id: str, tenant_id: str) -> dict:
    try:
        result = asyncio.run(_purge(uuid.UUID(document_id), uuid.UUID(tenant_id)))
    except Retry:
        raise
    except Exception as e:
        retries = int(getattr(self.request, "retries", 0) or 0)
        logger.warning("Purge of document %s failed (attempt %d): %s", document_id, retries + 1, e)
        # Search already hides the document, so retrying later is safe.
        raise self.retry(exc=e, countdown=min(600, 10 * 2**retries))
    return {"document_id": document_id, "tenant_id": tenant_id, **result}


def enqueue_purges(tenant_id: uuid.UUID, document_ids: Iterable[uuid.UUID]) -> None:
    """Queue purges for deleted documents. Best-effort: if the broker is unavailable the
    delete still holds (search ignores deleted documents); the data just stays until purged."""
    for doc_id in document_ids:
        try:
            purge_document.apply_async(args=[str(doc_id), str(tenant_id)], priority=3)
        except Exception:  # noqa: BLE001
            logger.exception("Could not queue purge for deleted document %s", doc_id)
