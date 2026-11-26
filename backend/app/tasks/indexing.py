from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from celery.exceptions import Retry
from opensearchpy.helpers import bulk
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.celery_app import celery_app
from backend.app.core.config import settings
from backend.app.models.document import Chunk, Document
from backend.app.models.tenant import Tenant
from backend.app.services.cache import CacheService
from backend.app.services.embeddings import EmbeddingConfig, create_embedding_service
from backend.app.services.opensearch import OpenSearchService


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _update_doc(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    error_message: str | None = None,
    index_task_id: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session() as db:
            res = await db.execute(
                sa.select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
            doc = res.scalar_one_or_none()
            if doc is None:
                return

            if status is not None:
                doc.status = status
            if progress is not None:
                doc.index_progress = float(progress)
            if message is not None:
                doc.index_message = message
            if error_message is not None:
                doc.error_message = error_message
            if index_task_id is not None:
                doc.index_task_id = index_task_id
            if started_at is not None:
                doc.index_started_at = started_at
            if completed_at is not None:
                doc.index_completed_at = completed_at

            await db.commit()
    finally:
        await eng.dispose()


async def _is_deleted(tenant_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session() as db:
            deleted_at = (
                await db.execute(
                    sa.select(Document.deleted_at).where(Document.id == document_id, Document.tenant_id == tenant_id)
                )
            ).one_or_none()
        return deleted_at is None or deleted_at[0] is not None  # missing counts as deleted
    finally:
        await eng.dispose()


async def _load_embedding_config(tenant_id: uuid.UUID) -> EmbeddingConfig:
    """Load per-tenant embedding config, falling back to server defaults."""

    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session() as db:
            res = await db.execute(sa.select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            raw = dict(getattr(tenant, "embedding_config", {}) or {}) if tenant is not None else {}

        cfg = {
            "provider": raw.get("provider") or settings.embedding_provider,
            "model": raw.get("model") or settings.embedding_model,
            "base_url": raw.get("base_url"),
            "api_key": raw.get("api_key"),
            "timeout_s": float(raw.get("timeout_s") or 60.0),
            "batch_size": int(raw.get("batch_size") or settings.embedding_batch_size),
            "rps": float(raw.get("rps") or settings.embedding_rps),
            "cache_ttl_s": int(raw.get("cache_ttl_s") or settings.embedding_cache_ttl_s),
        }
        return EmbeddingConfig(**cfg)
    finally:
        await eng.dispose()


@celery_app.task(bind=True, name="backend.app.tasks.indexing.index_document")
def index_document(self, document_id: str, tenant_id: str) -> dict:
    """Index all chunks for a document into OpenSearch.

    Steps:
    - mark document as indexing
    - load document + chunks
    - embed chunk texts (cached)
    - bulk index chunk docs into OpenSearch tenant index
    - mark indexed or failed
    """

    doc_uuid = uuid.UUID(document_id)
    tenant_uuid = uuid.UUID(tenant_id)
    task_id = getattr(self.request, "id", None)

    async def run_async() -> dict:
        await _update_doc(
            tenant_uuid,
            doc_uuid,
            status="indexing",
            progress=0.01,
            message="starting",
            error_message=None,
            index_task_id=str(task_id) if task_id else None,
            started_at=_now(),
        )

        # Load chunks
        eng = create_async_engine(settings.database_url, pool_pre_ping=True)
        Session = async_sessionmaker(eng, expire_on_commit=False)
        try:
            async with Session() as db:
                doc = (
                    await db.execute(
                        sa.select(Document).where(Document.id == doc_uuid, Document.tenant_id == tenant_uuid)
                    )
                ).scalar_one_or_none()
                if doc is None:
                    return {"document_id": document_id, "tenant_id": tenant_id, "status": "missing"}
                if doc.deleted_at is not None:
                    return {"document_id": document_id, "tenant_id": tenant_id, "status": "deleted"}

                chunk_rows = (
                    await db.execute(
                        sa.select(Chunk)
                        .where(Chunk.document_id == doc_uuid, Chunk.tenant_id == tenant_uuid)
                        .order_by(Chunk.seq.asc())
                    )
                ).scalars().all()
        finally:
            await eng.dispose()

        if not chunk_rows:
            await _update_doc(tenant_uuid, doc_uuid, status="indexed", progress=1.0, message="no chunks", completed_at=_now())
            return {"document_id": document_id, "tenant_id": tenant_id, "status": "indexed", "chunks": 0}

        await _update_doc(tenant_uuid, doc_uuid, progress=0.1, message="embedding")

        cfg = await _load_embedding_config(tenant_uuid)
        cache = CacheService()
        embedder = create_embedding_service(cfg, cache=cache)

        texts = [c.content for c in chunk_rows]
        emb = await embedder.embed_cached(texts)

        expected_dim = int(getattr(settings, "embedding_dimension", emb.dimension or 0))
        if expected_dim and emb.dimension and emb.dimension != expected_dim:
            raise ValueError(f"Embedding dimension mismatch: got {emb.dimension}, expected {expected_dim}")

        await _update_doc(tenant_uuid, doc_uuid, progress=0.7, message="indexing")

        os_svc = OpenSearchService()
        index_name = os_svc.ensure_index(tenant_uuid)
        client = os_svc._client()  # noqa: SLF001 (internal helper)

        actions = []
        for ch, vec in zip(chunk_rows, emb.vectors, strict=False):
            actions.append(
                {
                    "_op_type": "index",
                    "_index": index_name,
                    "_id": str(ch.id),
                    "chunk_id": str(ch.id),
                    "doc_id": str(ch.document_id),
                    "kb_id": str(doc.kb_id),
                    "tenant_id": str(tenant_uuid),
                    "content": ch.content,
                    "content_vector": vec,
                    "created_at": ch.created_at.isoformat() if getattr(ch, "created_at", None) else _now().isoformat(),
                }
            )

        def _do_bulk():
            # raise_on_error=False lets us inspect failures and decide retry.
            # refresh=wait_for: entries must be visible to delete_by_query, or a purge that
            # runs right after this could miss them.
            return bulk(client, actions, raise_on_error=False, raise_on_exception=False, refresh="wait_for")

        ok, errors = await asyncio.to_thread(_do_bulk)
        if errors:
            # Surface only a small summary to the caller.
            raise RuntimeError(f"OpenSearch bulk index had failures (ok={ok}, errors={len(errors)})")

        # Deleted while we were embedding/indexing? Its purge may have run before our
        # writes landed, so remove them ourselves.
        if await _is_deleted(tenant_uuid, doc_uuid):
            await asyncio.to_thread(os_svc.delete_document_chunks, tenant_uuid, doc_uuid)
            return {"document_id": document_id, "tenant_id": tenant_id, "status": "deleted"}

        await _update_doc(tenant_uuid, doc_uuid, status="indexed", progress=1.0, message="indexed", completed_at=_now())
        return {"document_id": document_id, "tenant_id": tenant_id, "status": "indexed", "chunks": len(actions)}

    try:
        return asyncio.run(run_async())
    except Retry:
        raise
    except Exception as e:
        retries = int(getattr(self.request, "retries", 0) or 0)
        if retries < 3:
            raise self.retry(exc=e, countdown=min(60, 2 ** (retries + 1)))

        try:
            asyncio.run(
                _update_doc(
                    tenant_uuid,
                    doc_uuid,
                    status="failed",
                    progress=1.0,
                    message="failed",
                    error_message=f"{type(e).__name__}: {e}",
                    completed_at=_now(),
                )
            )
        except Exception:
            pass
        return {"document_id": document_id, "tenant_id": tenant_id, "status": "failed"}
