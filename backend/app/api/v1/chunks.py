from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db
from backend.app.core.deps import require_tenant_membership
from backend.app.models.document import Document
from backend.app.services.chunks import ChunkService

router = APIRouter()


class ChunkResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    seq: int
    content: str
    token_count: int | None = None
    page: int | None = None
    position: dict


class ChunkListResponse(BaseModel):
    items: list[ChunkResponse]
    page: int
    size: int
    total: int


@router.get("/documents/{doc_id}/chunks", response_model=ChunkListResponse)
async def list_document_chunks(
    doc_id: uuid.UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ChunkListResponse:
    tenant_id, _user = ctx

    # Ensure document exists and is in tenant
    from sqlalchemy import select

    res = await db.execute(select(Document).where(Document.id == doc_id, Document.tenant_id == tenant_id))
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = ChunkService()
    page_obj = await svc.list_chunks(db, tenant_id=tenant_id, document_id=doc_id, page=page, size=size, q=q)

    return ChunkListResponse(
        items=[
            ChunkResponse(
                id=c.id,
                document_id=c.document_id,
                seq=c.seq,
                content=c.content,
                token_count=c.token_count,
                page=c.page,
                position=c.position,
            )
            for c in page_obj.items
        ],
        page=page_obj.page,
        size=page_obj.size,
        total=page_obj.total,
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkResponse)
async def get_chunk(
    chunk_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ChunkResponse:
    tenant_id, _user = ctx

    svc = ChunkService()
    c = await svc.get_chunk(db, tenant_id=tenant_id, chunk_id=chunk_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    return ChunkResponse(
        id=c.id,
        document_id=c.document_id,
        seq=c.seq,
        content=c.content,
        token_count=c.token_count,
        page=c.page,
        position=c.position,
    )
