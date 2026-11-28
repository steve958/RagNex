from __future__ import annotations

import abc
import asyncio
import hashlib
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.core.http import tls_context
from backend.app.services.cache import CacheService


EmbeddingProviderName = Literal["ollama", "vllm", "openai"]


class EmbeddingConfig(BaseModel):
    provider: EmbeddingProviderName = "ollama"
    model: str = "bge-m3"
    api_key: str | None = None
    base_url: str | None = None
    timeout_s: float = 60.0
    batch_size: int = 32
    rps: float = 5.0
    cache_ttl_s: int = 24 * 3600


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    dimension: int


class RateLimiter:
    """Simple async rate limiter (requests per second)."""

    def __init__(self, rps: float):
        self.rps = float(rps)
        self._lock = asyncio.Lock()
        self._next_time = 0.0

    async def wait(self) -> None:
        if self.rps <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_time:
                await asyncio.sleep(self._next_time - now)
            self._next_time = max(self._next_time, now) + (1.0 / self.rps)


class EmbeddingService(abc.ABC):
    def __init__(self, cfg: EmbeddingConfig, cache: CacheService | None = None):
        self.cfg = cfg
        self.cache = cache
        self._rl = RateLimiter(cfg.rps)

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...

    def dimension(self) -> int:
        raise NotImplementedError

    def _cache_key(self, text: str) -> str:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"emb:{self.cfg.provider}:{self.cfg.model}:{h}"

    async def _get_cached(self, texts: list[str]) -> tuple[list[list[float] | None], list[int]]:
        if self.cache is None:
            return [None for _ in texts], list(range(len(texts)))

        cached: list[list[float] | None] = []
        missing_idx: list[int] = []
        for i, t in enumerate(texts):
            v = await self.cache.get(self._cache_key(t))
            if isinstance(v, list):
                cached.append(v)
            else:
                cached.append(None)
                missing_idx.append(i)
        return cached, missing_idx

    async def _store_cached(self, texts: list[str], vectors: list[list[float]]) -> None:
        if self.cache is None:
            return
        for t, v in zip(texts, vectors, strict=False):
            await self.cache.set(self._cache_key(t), v, ttl=self.cfg.cache_ttl_s)

    async def embed_cached(self, texts: list[str]) -> EmbeddingResult:
        cached, missing_idx = await self._get_cached(texts)
        if not missing_idx:
            vecs = [v for v in cached if v is not None]
            dim = len(vecs[0]) if vecs else 0
            return EmbeddingResult(vectors=vecs, dimension=dim)

        missing_texts = [texts[i] for i in missing_idx]
        res = await self.embed(missing_texts)

        await self._store_cached(missing_texts, res.vectors)

        # Reconstruct in original order
        out: list[list[float]] = []
        it = iter(res.vectors)
        for v in cached:
            if v is None:
                out.append(next(it))
            else:
                out.append(v)

        return EmbeddingResult(vectors=out, dimension=res.dimension)


class OllamaEmbedding(EmbeddingService):
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        base_url = (self.cfg.base_url or settings.ollama_base_url).rstrip("/")
        url = f"{base_url}/api/embeddings"

        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s, verify=tls_context()) as client:
            for t in texts:
                await self._rl.wait()
                r = await client.post(url, json={"model": self.cfg.model, "prompt": t})
                r.raise_for_status()
                data = r.json()
                vec = data.get("embedding")
                if not isinstance(vec, list):
                    raise ValueError("Invalid Ollama embedding response")
                vectors.append([float(x) for x in vec])

        dim = len(vectors[0]) if vectors else 0
        return EmbeddingResult(vectors=vectors, dimension=dim)


class OpenAICompatibleEmbedding(EmbeddingService):
    """Embedding provider using OpenAI-compatible /v1/embeddings API."""

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        base_url = (self.cfg.base_url or settings.openai_base_url).rstrip("/")
        url = f"{base_url}/embeddings"

        api_key = self.cfg.api_key or settings.openai_api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        batch = max(1, int(self.cfg.batch_size))
        vectors: list[list[float]] = []

        async with httpx.AsyncClient(timeout=self.cfg.timeout_s, verify=tls_context()) as client:
            for i in range(0, len(texts), batch):
                await self._rl.wait()
                chunk = texts[i : i + batch]
                r = await client.post(url, headers=headers, json={"model": self.cfg.model, "input": chunk})
                r.raise_for_status()
                data = r.json()
                items = data.get("data")
                if not isinstance(items, list):
                    raise ValueError("Invalid embeddings response")

                # items sorted by index
                items = sorted(items, key=lambda x: x.get("index", 0))
                for it in items:
                    vec = it.get("embedding")
                    if not isinstance(vec, list):
                        raise ValueError("Invalid embeddings response")
                    vectors.append([float(x) for x in vec])

        dim = len(vectors[0]) if vectors else 0
        return EmbeddingResult(vectors=vectors, dimension=dim)


class OpenAIEmbedding(OpenAICompatibleEmbedding):
    pass


class VLLMEmbedding(OpenAICompatibleEmbedding):
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        # vLLM typically exposes OpenAI-compatible endpoints.
        if not (self.cfg.base_url or settings.vllm_base_url):
            raise ValueError("vllm_base_url is not configured")
        return await super().embed(texts)


def create_embedding_service(cfg: EmbeddingConfig, cache: CacheService | None = None) -> EmbeddingService:
    if cfg.provider == "ollama":
        return OllamaEmbedding(cfg, cache=cache)
    if cfg.provider == "openai":
        return OpenAIEmbedding(cfg, cache=cache)
    if cfg.provider == "vllm":
        return VLLMEmbedding(cfg, cache=cache)
    raise ValueError(f"Unknown provider: {cfg.provider}")
