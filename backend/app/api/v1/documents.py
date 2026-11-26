from __future__ import annotations

import datetime as dt
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.core.deps import require_tenant_membership
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.parsing import SUPPORTED_EXTENSIONS
from backend.app.services.storage import StorageService
from backend.app.tasks.parsing import parse_document
from backend.app.tasks.purge import enqueue_purges

router = APIRouter()


class DocumentUploadResponse(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    status: str
    task_id: str


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    status: str

    parse_task_id: str | None = None
    parse_progress: float
    parse_message: str | None = None

    index_task_id: str | None = None
    index_progress: float
    index_message: str | None = None

    error_message: str | None = None

    created_at: str | None = None
    updated_at: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentStatusResponse]




def _status_response(doc: Document) -> DocumentStatusResponse:
    return DocumentStatusResponse(
        id=doc.id,
        kb_id=doc.kb_id,
        filename=doc.filename,
        status=doc.status,
        parse_task_id=doc.parse_task_id,
        parse_progress=float(doc.parse_progress or 0.0),
        parse_message=doc.parse_message,
        index_task_id=doc.index_task_id,
        index_progress=float(doc.index_progress or 0.0),
        index_message=doc.index_message,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat() if getattr(doc, "created_at", None) else None,
        updated_at=doc.updated_at.isoformat() if getattr(doc, "updated_at", None) else None,
    )


@router.get("/documents/{doc_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    doc_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    tenant_id, _user = ctx

    res = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _status_response(doc)


@router.get("/knowledgebases/{kb_id}/documents", response_model=DocumentListResponse)
async def list_documents_for_knowledge_base(
    kb_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    tenant_id, _user = ctx

    # Ensure KB belongs to tenant
    res_kb = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = res_kb.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    res_docs = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
    )
    docs = res_docs.scalars().all()

    items = [_status_response(doc) for doc in docs]

    return DocumentListResponse(items=items)


def _get_size_bytes(file: UploadFile) -> int | None:
    # Best-effort: UploadFile.file is usually a SpooledTemporaryFile.
    try:
        pos = file.file.tell()
        file.file.seek(0, os.SEEK_END)
        size = int(file.file.tell())
        file.file.seek(pos, os.SEEK_SET)
        return size
    except Exception:
        return None


@router.post("/knowledgebases/{kb_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    from_page: int = 0,
    to_page: int = 100000,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    tenant_id, _user = ctx

    # Validate KB belongs to tenant
    res = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = res.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext or '(no extension)'}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    size_bytes = _get_size_bytes(file)
    max_bytes = int(settings.max_upload_size_mb) * 1024 * 1024
    if size_bytes is not None and size_bytes > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="The file is empty")

    # Create DB row first (status pending), then upload, then commit
    doc = Document(
        tenant_id=tenant_id,
        kb_id=kb_id,
        filename=filename,
        mime_type=file.content_type,
        size_bytes=size_bytes,
        status="pending",
    )
    db.add(doc)
    await db.flush()

    storage = StorageService()
    try:
        object_key = await storage.upload_file(tenant_id, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}")

    doc.storage_key = object_key
    await db.commit()

    # Queue parsing task
    async_result = parse_document.apply_async(
        args=[str(doc.id), str(tenant_id), {"from_page": from_page, "to_page": to_page, **(kb.parser_config or {})}],
        priority=5,
    )

    # Store task id for status lookup.
    doc.parse_task_id = str(async_result.id)
    await db.commit()

    return DocumentUploadResponse(
        id=doc.id,
        kb_id=kb_id,
        filename=doc.filename,
        status=doc.status,
        task_id=str(async_result.id),
    )


@router.delete("/documents/{doc_id}", response_model=dict)
async def delete_document(
    doc_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a document for the current tenant.

    Marks it deleted (search and chunk endpoints ignore it from now on), then queues a
    purge of its indexed chunks, chunk rows and stored file.
    """
    tenant_id, _user = ctx

    res = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    import datetime as _dt

    doc.deleted_at = _dt.datetime.now(tz=_dt.timezone.utc)
    await db.commit()
    enqueue_purges(tenant_id, [doc.id])
    return {"ok": True}


# --- Reprocessing ------------------------------------------------------------------------

# Statuses in which a parse/index task is (supposedly) still working on the document.
_IN_PROGRESS = {"pending", "parsing", "done", "indexing"}
# After this long without any update, an "in progress" document is considered stuck
# (e.g. its worker died) and may be reprocessed.
REPROCESS_STALE_AFTER = dt.timedelta(minutes=30)


class ReprocessFailedResponse(BaseModel):
    queued: list[uuid.UUID]
    skipped: list[dict]


async def _reprocess_blocker(doc: Document, tenant_id: uuid.UUID) -> str | None:
    """Why this document can't be reprocessed right now, or None if it can."""
    if doc.status in _IN_PROGRESS:
        updated = doc.updated_at or doc.created_at
        if updated is not None and dt.datetime.now(dt.timezone.utc) - updated < REPROCESS_STALE_AFTER:
            return "The document is already being processed."
    if not doc.storage_key or not await StorageService().file_exists(tenant_id, doc.storage_key):
        return "The original file is no longer stored. Upload the document again."
    return None


async def _queue_reprocess(db: AsyncSession, doc: Document, kb: KnowledgeBase, tenant_id: uuid.UUID) -> None:
    """Reset processing state and queue parsing again (indexing follows automatically and
    replaces the document's previous index entries)."""
    doc.status = "pending"
    doc.error_message = None
    doc.parse_progress, doc.parse_message = 0.0, "queued for reprocessing"
    doc.index_progress, doc.index_message = 0.0, None
    doc.parse_task_id = doc.index_task_id = None
    await db.commit()  # the worker must see the reset row

    async_result = parse_document.apply_async(
        args=[str(doc.id), str(tenant_id), {"from_page": 0, "to_page": 100000, **(kb.parser_config or {})}],
        priority=5,
    )
    doc.parse_task_id = str(async_result.id)
    await db.commit()


async def _load_kb(db: AsyncSession, tenant_id: uuid.UUID, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.post("/documents/{doc_id}/reprocess", response_model=DocumentStatusResponse)
async def reprocess_document(
    doc_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Parse and index the stored file again, e.g. after a failure or a parser fix."""
    tenant_id, _user = ctx
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    kb = await _load_kb(db, tenant_id, doc.kb_id)

    reason = await _reprocess_blocker(doc, tenant_id)
    if reason:
        raise HTTPException(status_code=409, detail=reason)

    await _queue_reprocess(db, doc, kb, tenant_id)
    await db.refresh(doc)
    return _status_response(doc)


@router.post("/knowledgebases/{kb_id}/documents/reprocess-failed", response_model=ReprocessFailedResponse)
async def reprocess_failed_documents(
    kb_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ReprocessFailedResponse:
    """Reprocess every failed document in a knowledge base."""
    tenant_id, _user = ctx
    kb = await _load_kb(db, tenant_id, kb_id)
    failed = (
        await db.execute(
            select(Document)
            .where(
                Document.kb_id == kb_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
                Document.status == "failed",
            )
            .order_by(Document.created_at.asc())
        )
    ).scalars().all()

    queued: list[uuid.UUID] = []
    skipped: list[dict] = []
    for doc in failed:
        reason = await _reprocess_blocker(doc, tenant_id)
        if reason:
            skipped.append({"id": str(doc.id), "filename": doc.filename, "reason": reason})
            continue
        await _queue_reprocess(db, doc, kb, tenant_id)
        queued.append(doc.id)
    return ReprocessFailedResponse(queued=queued, skipped=skipped)
