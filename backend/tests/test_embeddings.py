from __future__ import annotations

import types

import pytest

from backend.app.services.embeddings import (
    EmbeddingConfig,
    OpenAICompatibleEmbedding,
    OllamaEmbedding,
    create_embedding_service,
)


class FakeCache:
    def __init__(self):
        self.store: dict[str, object] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl: int = 3600):
        self.store[key] = value


@pytest.mark.asyncio
async def test_ollama_embed_parses_response(monkeypatch):
    cfg = EmbeddingConfig(provider="ollama", model="m", base_url="http://x")
    svc = OllamaEmbedding(cfg)

    class DummyResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embedding": [1, 2, 3]}

    async def fake_post(self, url, json=None, headers=None):
        return DummyResp()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    res = await svc.embed(["a", "b"])
    assert res.dimension == 3
    assert res.vectors == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]


@pytest.mark.asyncio
async def test_openai_compatible_batches_and_orders(monkeypatch):
    cfg = EmbeddingConfig(provider="openai", model="m", base_url="http://x", batch_size=2, rps=0)
    svc = OpenAICompatibleEmbedding(cfg)

    class DummyResp:
        def raise_for_status(self):
            return None

        def json(self):
            # reversed indexes to ensure sorting
            return {"data": [{"index": 1, "embedding": [2, 2]}, {"index": 0, "embedding": [1, 1]}]}

    calls = {"n": 0}

    async def fake_post(self, url, json=None, headers=None):
        calls["n"] += 1
        return DummyResp()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    res = await svc.embed(["a", "b", "c"])
    assert calls["n"] == 2
    assert res.dimension == 2
    # order should be [1,1] then [2,2] for each batch
    assert res.vectors[0] == [1.0, 1.0]
    assert res.vectors[1] == [2.0, 2.0]


@pytest.mark.asyncio
async def test_embedding_cache_hit_miss(monkeypatch):
    cache = FakeCache()

    cfg = EmbeddingConfig(provider="ollama", model="m", base_url="http://x", rps=0)
    svc = create_embedding_service(cfg, cache=cache)  # type: ignore[arg-type]

    # fake embed called once for miss only
    async def fake_embed(self, texts):
        return types.SimpleNamespace(vectors=[[0.0] for _ in texts], dimension=1)

    monkeypatch.setattr(type(svc), "embed", fake_embed)

    r1 = await svc.embed_cached(["a", "b"])
    assert r1.vectors == [[0.0], [0.0]]

    r2 = await svc.embed_cached(["a", "b"])
    assert r2.vectors == [[0.0], [0.0]]
