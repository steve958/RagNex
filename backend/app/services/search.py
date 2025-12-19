from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.models.tenant import Tenant
from backend.app.services.cache import CacheService
from backend.app.services.embeddings import EmbeddingConfig, create_embedding_service
from backend.app.services.opensearch import OpenSearchService


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    kb_id: str
    tenant_id: str
    content: str
    score: float
    source: str  # bm25|vector|hybrid


class SearchService:
    def __init__(self) -> None:
        self._os = OpenSearchService()

    async def _load_embedding_config(self, tenant_id: uuid.UUID) -> EmbeddingConfig:
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
        kb_id: uuid.UUID,
        query: str,
        top_k: int = 10,
        bm25_k: int | None = None,
        vector_k: int | None = None,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
    ) -> list[SearchHit]:
        top_k = max(1, min(100, int(top_k)))
        bm25_k = max(top_k, int(bm25_k or top_k))
        vector_k = max(top_k, int(vector_k or top_k))

        index = self._os.ensure_index(tenant_id)
        client = self._os._client()  # noqa: SLF001

        filters = [
            {"term": {"tenant_id": str(tenant_id)}},
            {"term": {"kb_id": str(kb_id)}},
        ]

        bm25_body = {
            "size": bm25_k,
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

        bm25_resp = client.search(index=index, body=bm25_body)
        vector_resp = client.search(index=index, body=vector_body)

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
        return fused[:top_k]
