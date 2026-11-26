from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
import sqlalchemy as sa
from celery.exceptions import Retry
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.celery_app import celery_app
from backend.app.core.config import settings
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.chunks import ChunkService
from backend.app.services.parsing import parse_document_binary
from backend.app.services.storage import StorageService


async def _update_doc(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    error_message: str | None = None,
    parsed_data: dict | None = None,
    parse_task_id: str | None = None,
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
                doc.parse_progress = float(progress)
            if message is not None:
                doc.parse_message = message
            if error_message is not None:
                doc.error_message = error_message
            if parsed_data is not None:
                doc.parsed_data = parsed_data
            if parse_task_id is not None:
                doc.parse_task_id = parse_task_id
            if started_at is not None:
                doc.parse_started_at = started_at
            if completed_at is not None:
                doc.parse_completed_at = completed_at

            await db.commit()
    finally:
        await eng.dispose()


async def _publish_progress(tenant_id: uuid.UUID, document_id: uuid.UUID, payload: dict) -> None:
    # Best-effort: publish progress on a redis pubsub channel.
    r = redis.from_url(settings.redis_url, decode_responses=False)
    try:
        channel = f"docs:{tenant_id}:{document_id}:progress"
        await r.publish(channel, json.dumps(payload).encode("utf-8"))
    except Exception:
        pass
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(bind=True, name="backend.app.tasks.parsing.parse_document")
def parse_document(self, document_id: str, tenant_id: str, parser_config: dict | None = None) -> dict:
    """Parse a document stored in MinIO.

    Steps:
    - mark document as parsing
    - download from MinIO
    - route to DeepDoc parser by extension
    - store normalized parsed output on the Document row
    - mark done or failed

    Progress is stored on the Document row and also published to Redis pub/sub.
    """

    cfg = parser_config or {}

    doc_uuid = uuid.UUID(document_id)
    tenant_uuid = uuid.UUID(tenant_id)

    task_id = getattr(self.request, "id", None)

    async def run_async() -> dict:
        await _update_doc(
            tenant_uuid,
            doc_uuid,
            status="parsing",
            progress=0.01,
            message="starting",
            error_message=None,
            parse_task_id=str(task_id) if task_id else None,
            started_at=_now(),
        )
        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 0.01, "message": "starting"})

        # Load document row for filename + storage key + KB settings
        eng = create_async_engine(settings.database_url, pool_pre_ping=True)
        Session = async_sessionmaker(eng, expire_on_commit=False)
        try:
            async with Session() as db:
                res = await db.execute(
                    sa.select(Document).where(Document.id == doc_uuid, Document.tenant_id == tenant_uuid)
                )
                doc = res.scalar_one()
                filename = doc.filename
                storage_key = doc.storage_key

                kb = (
                    await db.execute(
                        sa.select(KnowledgeBase).where(
                            KnowledgeBase.id == doc.kb_id, KnowledgeBase.tenant_id == tenant_uuid
                        )
                    )
                ).scalar_one_or_none()

                kb_template = (kb.template if kb is not None else "general")
                kb_parser_config = (kb.parser_config if kb is not None else {})
        finally:
            await eng.dispose()

        if not storage_key:
            await _update_doc(
                tenant_uuid,
                doc_uuid,
                status="failed",
                progress=1.0,
                message="missing storage key",
                error_message="Document has no storage_key",
                completed_at=_now(),
            )
            return {"document_id": document_id, "tenant_id": tenant_id, "status": "failed"}

        await _update_doc(tenant_uuid, doc_uuid, progress=0.1, message="downloading")
        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 0.1, "message": "downloading"})

        storage = StorageService()
        binary = await storage.download_file(tenant_uuid, storage_key)

        await _update_doc(tenant_uuid, doc_uuid, progress=0.6, message="parsing")
        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 0.6, "message": "parsing"})

        parsed = parse_document_binary(filename=filename, binary=binary, parser_config=cfg)

        await _update_doc(tenant_uuid, doc_uuid, progress=0.8, message="chunking")
        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 0.8, "message": "chunking"})

        # Build chunks based on KB template.
        template = str((kb_template or "general")).lower()
        parser_cfg = dict(kb_parser_config or {})

        chunks_payload: list[dict]
        if template == "laws":
            from backend.app.services.chunking.laws import LawsChunkConfig, chunk_laws_document

            chunks_payload = chunk_laws_document(parsed, LawsChunkConfig(**{k: v for k, v in parser_cfg.items() if k in {"chunk_token_num", "delimiter", "tree_depth", "layout_recognize"}}))
        elif template == "paper":
            from backend.app.services.chunking.paper import PaperChunkConfig, chunk_paper_document

            paper_out = chunk_paper_document(parsed, PaperChunkConfig(**{k: v for k, v in parser_cfg.items() if k in {"chunk_token_num", "layout_recognize"}}))
            chunks_payload = [{"content": c["content"], "token_count": c.get("token_count") } for c in paper_out.get("chunks", [])]
            # include extracted metadata back into parsed_data
            parsed = {**parsed, "paper": {k: paper_out.get(k) for k in ["title", "authors", "abstract"]}}
        else:
            from backend.app.services.chunking.general import GeneralChunkConfig, chunk_parsed_document

            chunks_payload = chunk_parsed_document(parsed, GeneralChunkConfig(**{k: v for k, v in parser_cfg.items() if k in {"chunk_token_num", "delimiter", "layout_recognize", "analyze_hyperlink"}}))

        await _update_doc(tenant_uuid, doc_uuid, progress=0.95, message="saving")
        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 0.95, "message": "saving"})

        # Save parsed_data + chunks transactionally.
        eng2 = create_async_engine(settings.database_url, pool_pre_ping=True)
        Session2 = async_sessionmaker(eng2, expire_on_commit=False)
        try:
            async with Session2() as db:
                # Row lock until commit: a concurrent delete waits for us, so its purge
                # (queued after the delete commits) sees and removes these chunks.
                res = await db.execute(
                    sa.select(Document)
                    .where(Document.id == doc_uuid, Document.tenant_id == tenant_uuid)
                    .with_for_update()
                )
                doc2 = res.scalar_one_or_none()
                if doc2 is None or doc2.deleted_at is not None:
                    # Deleted while parsing: its purge may already have run, so writing
                    # chunks now would leave orphans behind.
                    return {"document_id": document_id, "tenant_id": tenant_id, "status": "deleted"}

                # store chunks
                svc = ChunkService()
                await svc.store_chunks(db, tenant_id=tenant_uuid, document_id=doc_uuid, chunks=chunks_payload)

                # update document
                if doc2 is not None:
                    doc2.status = "done"
                    doc2.parse_progress = 1.0
                    doc2.parse_message = "done"
                    doc2.parsed_data = parsed
                    doc2.parse_completed_at = _now()

                    # Queue indexing (P3-3). Best-effort.
                    try:
                        from backend.app.tasks.indexing import index_document

                        async_result = index_document.apply_async(args=[str(doc_uuid), str(tenant_uuid)], priority=5)
                        doc2.index_task_id = str(async_result.id)
                    except Exception:
                        pass

                await db.commit()
        finally:
            await eng2.dispose()

        await _publish_progress(tenant_uuid, doc_uuid, {"progress": 1.0, "message": "done"})

        return {"document_id": document_id, "tenant_id": tenant_id, "status": "done", "chunks": len(chunks_payload)}

    try:
        return asyncio.run(run_async())
    except Retry:
        raise
    except Exception as e:
        # Retry a few times for transient errors.
        retries = int(getattr(self.request, "retries", 0) or 0)
        if retries < 3:
            raise self.retry(exc=e, countdown=min(60, 2 ** (retries + 1)))

        # Permanent failure: mark failed.
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
