from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db
from backend.app.core.validation import Name, Text
from backend.app.core.deps import require_tenant_membership, require_tenant_read
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.search import SearchHit, SearchService
from backend.app.tasks.purge import enqueue_purges

router = APIRouter(prefix="/knowledgebases")


# Chunking templates that exist (services/chunking/); anything else used to be stored and
# silently treated as "general".
Template = Literal["general", "laws", "paper"]


class KnowledgeBaseCreateRequest(BaseModel):
    name: Name()
    description: Text(10_000) | None = None
    template: Template = "general"


class KnowledgeBaseUpdateRequest(BaseModel):
    name: Name() | None = None
    description: Text(10_000) | None = None
    template: Template | None = None


class KnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    template: str


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeBaseResponse]:
    tenant_id, _user = ctx
    res = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.deleted_at.is_(None))
        .order_by(KnowledgeBase.created_at.asc())
    )
    rows = res.scalars().all()
    return [
        KnowledgeBaseResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            template=row.template,
        )
        for row in rows
    ]


@router.post("", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    req: KnowledgeBaseCreateRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    tenant_id, _user = ctx
    kb = KnowledgeBase(
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        template=req.template or "general",
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseResponse(id=kb.id, name=kb.name, description=kb.description, template=kb.template)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    tenant_id, _user = ctx
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
    return KnowledgeBaseResponse(id=kb.id, name=kb.name, description=kb.description, template=kb.template)


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    req: KnowledgeBaseUpdateRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    tenant_id, _user = ctx
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

    if req.name is not None:
        kb.name = req.name
    if req.description is not None:
        kb.description = req.description
    if req.template is not None:
        kb.template = req.template

    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseResponse(id=kb.id, name=kb.name, description=kb.description, template=kb.template)


@router.delete("/{kb_id}", response_model=dict)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _user = ctx
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

    # Mark the KB and all its documents deleted in one transaction (search ignores them
    # immediately), then purge the documents' data in the background.
    import datetime as _dt

    now = _dt.datetime.now(tz=_dt.timezone.utc)
    kb.deleted_at = now
    res = await db.execute(
        update(Document)
        .where(Document.kb_id == kb_id, Document.tenant_id == tenant_id, Document.deleted_at.is_(None))
        .values(deleted_at=now)
        .returning(Document.id)
    )
    doc_ids = list(res.scalars().all())
    await db.commit()
    enqueue_purges(tenant_id, doc_ids)
    return {"ok": True, "documents_deleted": len(doc_ids)}


class SearchRequest(BaseModel):
    query: Text(10_000) = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)

    # Optional knobs
    bm25_k: int | None = Field(default=None, ge=1, le=500)
    vector_k: int | None = Field(default=None, ge=1, le=500)
    rrf_k: int = Field(default=60, ge=1, le=10_000)
    bm25_weight: float = Field(default=1.0, ge=0.0)
    vector_weight: float = Field(default=1.0, ge=0.0)


class SearchHitResponse(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    score: float


class SearchResponse(BaseModel):
    hits: list[SearchHitResponse]


@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search_knowledge_base(
    kb_id: uuid.UUID,
    req: SearchRequest,
    ctx=Depends(require_tenant_read),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    tenant_id, _user = ctx

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

    svc = SearchService()
    hits: list[SearchHit] = await svc.search(
        tenant_id=tenant_id,
        kb_ids=[kb_id],
        query=req.query,
        top_k=req.top_k,
        bm25_k=req.bm25_k,
        vector_k=req.vector_k,
        rrf_k=req.rrf_k,
        bm25_weight=req.bm25_weight,
        vector_weight=req.vector_weight,
    )

    return SearchResponse(
        hits=[
            SearchHitResponse(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                content=h.content,
                score=h.score,
            )
            for h in hits
        ]
    )
