from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db
from backend.app.core.deps import require_tenant_membership
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.search import SearchHit, SearchService

router = APIRouter(prefix="/knowledgebases")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
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
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    tenant_id, _user = ctx

    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    svc = SearchService()
    hits: list[SearchHit] = await svc.search(
        tenant_id=tenant_id,
        kb_id=kb_id,
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
