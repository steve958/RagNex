from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.document import Chunk


@dataclass(frozen=True)
class ChunkPage:
    items: list[Chunk]
    total: int
    page: int
    size: int


class ChunkService:
    async def store_chunks(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[dict],
        delete_existing: bool = True,
    ) -> int:
        """Persist chunks for a document.

        `chunks` items should include at least:
          - content: str
          - token_count: int|None
        Optional:
          - page: int
          - position: dict
        """

        if delete_existing:
            await db.execute(delete(Chunk).where(Chunk.document_id == document_id))

        rows: list[Chunk] = []
        for i, ch in enumerate(chunks):
            rows.append(
                Chunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    seq=i,
                    content=str(ch.get("content") or ""),
                    token_count=ch.get("token_count"),
                    page=ch.get("page"),
                    position=ch.get("position") or {},
                )
            )

        db.add_all(rows)
        await db.flush()
        return len(rows)

    async def list_chunks(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        q: str | None = None,
    ) -> ChunkPage:
        page = max(1, int(page))
        size = min(100, max(1, int(size)))

        where = [Chunk.tenant_id == tenant_id, Chunk.document_id == document_id]
        if q:
            where.append(Chunk.content.ilike(f"%{q}%"))

        total = (
            await db.execute(select(func.count()).select_from(Chunk).where(*where))
        ).scalar_one()

        res = await db.execute(
            select(Chunk)
            .where(*where)
            .order_by(Chunk.seq.asc())
            .limit(size)
            .offset((page - 1) * size)
        )
        items = res.scalars().all()
        return ChunkPage(items=items, total=int(total), page=page, size=size)

    async def get_chunk(self, db: AsyncSession, *, tenant_id: uuid.UUID, chunk_id: uuid.UUID) -> Chunk | None:
        res = await db.execute(select(Chunk).where(Chunk.id == chunk_id, Chunk.tenant_id == tenant_id))
        return res.scalar_one_or_none()
