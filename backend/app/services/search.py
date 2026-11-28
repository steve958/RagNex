from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from opensearchpy.exceptions import NotFoundError
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.models.tenant import Tenant
from backend.app.services.cache import CacheService
from backend.app.services.embeddings import EmbeddingConfig, create_embedding_service
from backend.app.services.model_settings import effective_embedding_config
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.rerank import RerankError, rerank, rerank_enabled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    kb_id: str
    tenant_id: str
    content: str
    score: float
    source: str  # bm25|vector|hybrid|reranked (score is then the re-ranker's)


class SearchService:
    def __init__(self) -> None:
        self._os = OpenSearchService()

    async def _load_embedding_config(self, tenant_id: uuid.UUID) -> EmbeddingConfig:
        """Load per-tenant embedding config, falling back to server defaults."""

        # The shared engine: a new one per search opened (and closed) a database connection
        # every time, a large part of a search's cost under load (docs/performance.md).
        Session = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with Session() as db:
            res = await db.execute(sa.select(Tenant.embedding_config).where(Tenant.id == tenant_id))
            raw = dict(res.scalar_one_or_none() or {})

        # Shared with the Settings checks, so search and indexing use what owners set.
        return effective_embedding_config(raw)

    @staticmethod
    def _rrf(rank: int, *, k: int = 60, weight: float = 1.0) -> float:
        # Reciprocal Rank Fusion score.
        return float(weight) / float(k + rank)

    def _extract_hits(self, resp: dict, *, source: str) -> list[SearchHit]:
        out: list[SearchHit] = []
        hits = (resp.get("hits") or {}).get("hits") or []
        for h in hits:
            src = h.get("_source") or {}
            out.append(
                SearchHit(
                    chunk_id=str(src.get("chunk_id") or h.get("_id")),
                    doc_id=str(src.get("doc_id")),
                    kb_id=str(src.get("kb_id")),
                    tenant_id=str(src.get("tenant_id")),
                    content=str(src.get("content") or ""),
                    score=float(h.get("_score") or 0.0),
                    source=source,
                )
            )
        return out

    async def search(
        self,
        *,
        tenant_id: uuid.UUID,
        kb_ids: Sequence[uuid.UUID],
        query: str,
        top_k: int = 10,
        bm25_k: int | None = None,
        vector_k: int | None = None,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
        rerank_results: bool = True,
    ) -> list[SearchHit]:
        """Hybrid search across one or more knowledge bases of a tenant.

        All of a tenant's chunks live in one index, so several KBs are searched in a single
        query and ranked together (not per KB and then merged). If a re-ranker is configured
        (and rerank_results), the best fused candidates are re-scored by it; hits then have
        source "reranked". If it fails, the fused order is used.
        """
        if not kb_ids:
            raise ValueError("kb_ids must not be empty")
        top_k = max(1, min(100, int(top_k)))
        use_reranker = rerank_results and rerank_enabled()
        pool = max(top_k, settings.rerank_candidates) if use_reranker else top_k
        # Fetch extra candidates: hits from deleted documents are dropped after fusion.
        bm25_k = max(pool, int(bm25_k or pool * 2))
        vector_k = max(pool, int(vector_k or pool * 2))

        # The workspace's index is created with the workspace and by indexing; search only
        # reads it (a missing index means nothing is indexed yet).
        index = OpenSearchService.get_index_name(tenant_id)
        client = self._os._client()  # noqa: SLF001

        filters = [
            {"term": {"tenant_id": str(tenant_id)}},
            {"terms": {"kb_id": sorted({str(k) for k in kb_ids})}},
        ]

        # Only the fields hits are made of: with the stored vector (1024 numbers per chunk),
        # each response was about ten times larger, all of it parsed and thrown away.
        fields = ["chunk_id", "doc_id", "kb_id", "tenant_id", "content"]
        bm25_body = {
            "size": bm25_k,
            "_source": fields,
            "query": {
                "bool": {
                    "must": [{"match": {"content": {"query": query}}}],
                    "filter": filters,
                }
            },
        }

        # Embed query and do vector search.
        cfg = await self._load_embedding_config(tenant_id)
        cache = CacheService()
        embedder = create_embedding_service(cfg, cache=cache)
        emb = await embedder.embed_cached([query])

        expected_dim = int(getattr(settings, "embedding_dimension", emb.dimension or 0))
        if expected_dim and emb.dimension and emb.dimension != expected_dim:
            raise ValueError(f"Embedding dimension mismatch: got {emb.dimension}, expected {expected_dim}")

        qvec = emb.vectors[0]

        # OpenSearch k-NN plugin supports filter in the knn query (preferred).
        vector_body = {
            "size": vector_k,
            "_source": fields,
            "query": {
                "knn": {
                    "content_vector": {
                        "vector": qvec,
                        "k": vector_k,
                        "filter": {"bool": {"filter": filters}},
                    }
                }
            },
        }

        # The client is synchronous: run the queries in threads, side by side, so they don't
        # hold up the API's event loop (and every other request with it).
        try:
            bm25_resp, vector_resp = await asyncio.gather(
                asyncio.to_thread(client.search, index=index, body=bm25_body),
                asyncio.to_thread(client.search, index=index, body=vector_body),
            )
        except NotFoundError:
            return []

        bm25_hits = self._extract_hits(bm25_resp, source="bm25")
        vector_hits = self._extract_hits(vector_resp, source="vector")

        # Fuse with RRF.
        scores: dict[str, float] = {}
        merged: dict[str, SearchHit] = {}

        for i, h in enumerate(bm25_hits, start=1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + self._rrf(i, k=rrf_k, weight=bm25_weight)
            merged.setdefault(h.chunk_id, h)

        for i, h in enumerate(vector_hits, start=1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + self._rrf(i, k=rrf_k, weight=vector_weight)
            merged.setdefault(h.chunk_id, h)

        fused = [
            SearchHit(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                kb_id=h.kb_id,
                tenant_id=h.tenant_id,
                content=h.content,
                score=float(scores.get(h.chunk_id, 0.0)),
                source="hybrid",
            )
            for h in merged.values()
        ]

        fused.sort(key=lambda x: x.score, reverse=True)
        fused = await self._drop_deleted(tenant_id, fused)
        if use_reranker:
            return await self._rerank(query, fused[:pool], top_k)
        return fused[:top_k]

    @staticmethod
    async def _rerank(query: str, candidates: list[SearchHit], top_k: int) -> list[SearchHit]:
        try:
            ranked = await rerank(query, [h.content for h in candidates])
        except RerankError as e:
            # Better a slightly worse order than no answer: fall back to the fused ranking.
            logger.warning("Re-ranking failed, using the search order instead: %s", e)
            return candidates[:top_k]
        out = []
        for r in ranked[:top_k]:
            h = candidates[r.index]
            out.append(SearchHit(h.chunk_id, h.doc_id, h.kb_id, h.tenant_id, h.content, r.score, "reranked"))
        return out

    async def _drop_deleted(self, tenant_id: uuid.UUID, hits: list[SearchHit]) -> list[SearchHit]:
        """Remove hits whose document or knowledge base is deleted (or no longer exists).

        Deletion purges index entries in the background; this makes a delete take effect
        immediately and covers the time until (or a failure of) that purge.
        """
        if not hits:
            return hits
        doc_ids: set[uuid.UUID] = set()
        for h in hits:
            try:
                doc_ids.add(uuid.UUID(h.doc_id))
            except ValueError:
                continue  # malformed entry: can't be a live document

        live: set[str] = set()
        if doc_ids:
            Session = async_sessionmaker(get_engine(), expire_on_commit=False)
            async with Session() as db:
                res = await db.execute(
                    sa.select(Document.id)
                    .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
                    .where(
                        Document.id.in_(doc_ids),
                        Document.tenant_id == tenant_id,
                        Document.deleted_at.is_(None),
                        KnowledgeBase.deleted_at.is_(None),
                    )
                )
                live = {str(i) for i in res.scalars().all()}
        return [h for h in hits if h.doc_id in live]
