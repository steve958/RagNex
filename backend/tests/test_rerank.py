"""Re-ranking search results (services/rerank.py) and its use in search and chat."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.services import rerank as rerank_module
from backend.app.services import search as search_module
from backend.app.services.rerank import RerankError, rerank
from backend.app.services.search import SearchHit, SearchService

from test_deletion import Api, _with_api, pipeline  # noqa: F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available


@pytest.fixture
def reranker(monkeypatch):
    def configure(provider: str = "tei", base_url: str = "http://reranker", **extra):
        monkeypatch.setattr(settings, "rerank_provider", provider)
        monkeypatch.setattr(settings, "rerank_base_url", base_url)
        for k, v in extra.items():
            monkeypatch.setattr(settings, k, v)

    return configure


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- The client ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tei_format(reranker):
    reranker("tei", "http://tei:80/")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json=[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}])

    async with _client(handler) as client:
        ranked = await rerank("q", ["a", "b"], client=client)
    assert seen["url"] == "http://tei/rerank"
    assert seen["body"] == {"query": "q", "texts": ["a", "b"], "truncate": True}
    assert [(r.index, r.score) for r in ranked] == [(1, 0.9), (0, 0.1)]


@pytest.mark.asyncio
async def test_cohere_format_with_model_and_key(reranker):
    reranker("cohere", "https://api.example.com/v1", rerank_model="m", rerank_api_key="sk-r")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        # Results not sorted, as some servers return them in input order.
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.8}]})

    async with _client(handler) as client:
        ranked = await rerank("q", ["a", "b"], client=client)
    assert seen["url"] == "https://api.example.com/v1/rerank" and seen["auth"] == "Bearer sk-r"
    assert seen["body"] == {"model": "m", "query": "q", "documents": ["a", "b"], "top_n": 2}
    assert [r.index for r in ranked] == [1, 0]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(200, text="not json"), "couldn't be reached"),
        (httpx.Response(200, json={"oops": 1}), "unexpected response"),
        (httpx.Response(200, json=[{"index": 7, "score": 1}]), "out of range"),
    ],
)
@pytest.mark.asyncio
async def test_bad_answers_raise_rerank_error(reranker, response, message):
    reranker("tei")
    async with _client(lambda request: response) as client:
        with pytest.raises(RerankError, match=message):
            await rerank("q", ["a", "b"], client=client)


def test_disabled_without_provider_or_url(reranker):
    reranker("none")
    assert not rerank_module.rerank_enabled()
    reranker("tei", "")
    assert not rerank_module.rerank_enabled()
    reranker("tei", "http://x")
    assert rerank_module.rerank_enabled()


# --- In search -----------------------------------------------------------------------------


def _hit(n: int) -> SearchHit:
    return SearchHit(f"c{n}", f"d{n}", "kb", "t", f"passage {n}", 1.0 / n, "hybrid")


@pytest.mark.asyncio
async def test_reranker_decides_the_order_and_scores(monkeypatch):
    async def fake_rerank(query, documents):
        # Prefer the last candidate: re-ranking can promote a hit from deep in the list.
        return [rerank_module.Ranked(len(documents) - 1, 0.99), rerank_module.Ranked(0, 0.5)]

    monkeypatch.setattr(search_module, "rerank", fake_rerank)
    out = await SearchService._rerank("q", [_hit(n) for n in range(1, 31)], top_k=2)
    assert [(h.chunk_id, h.score, h.source) for h in out] == [("c30", 0.99, "reranked"), ("c1", 0.5, "reranked")]


@pytest.mark.asyncio
async def test_reranker_failure_falls_back_to_search_order(monkeypatch):
    async def broken(query, documents):
        raise RerankError("the re-ranker answered HTTP 503")

    # Record the warning call itself: Alembic's logging setup (run by another test)
    # disables existing loggers, so log capture would depend on test order.
    warnings: list[str] = []
    monkeypatch.setattr(search_module.logger, "warning", lambda msg, *args: warnings.append(msg % args))
    monkeypatch.setattr(search_module, "rerank", broken)
    out = await SearchService._rerank("q", [_hit(n) for n in range(1, 6)], top_k=3)
    assert [h.chunk_id for h in out] == ["c1", "c2", "c3"] and {h.source for h in out} == {"hybrid"}
    assert warnings == ["Re-ranking failed, using the search order instead: the re-ranker answered HTTP 503"]


@pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")
@pytest.mark.asyncio
async def test_search_endpoint_and_chat_use_the_reranker(pipeline, reranker, monkeypatch):
    reranker("tei", rerank_candidates=15)
    calls: list[int] = []

    async def reverse(query, documents):
        calls.append(len(documents))
        n = len(documents)
        return [rerank_module.Ranked(i, float(i)) for i in reversed(range(n))]

    monkeypatch.setattr(search_module, "rerank", reverse)

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        # Long enough to become many passages (a passage is about 512 tokens).
        filler = " ".join(f"Inspect mounting bolt {j} and wipe the glass surface gently." for j in range(40))
        body = "\n\n".join(f"Section {i}. Solar panel maintenance note {i}. {filler}" for i in range(20)).encode()
        await api.upload(kb, "notes.md", body)
        await pipeline.drain()

        url = f"/api/v1/knowledgebases/{kb}/search"
        plain = (await api.client.post(url, headers=api.headers, json={"query": "solar panel", "top_k": 3, "rerank": False})).json()
        assert plain["reranked"] is False and calls == []

        r = (await api.client.post(url, headers=api.headers, json={"query": "solar panel", "top_k": 3})).json()
        assert r["reranked"] is True and len(r["hits"]) == 3
        # More candidates than top_k were offered to the re-ranker, and its order was used:
        # with this fake, the *last* candidates come first.
        assert calls[-1] > 3
        assert [h["chunk_id"] for h in r["hits"]] != [h["chunk_id"] for h in plain["hits"]]
        assert r["hits"][0]["score"] == calls[-1] - 1

        # Chat retrieves through the same search, so it is re-ranked too.
        sid = (await api.client.post("/api/v1/chat/sessions", headers=api.headers, json={"kb_ids": [kb]})).json()["id"]
        before = len(calls)
        r = await api.client.post(f"/api/v1/chat/sessions/{sid}/messages", headers=api.headers, json={"content": "solar panel"})
        assert r.status_code == 200 and len(calls) == before + 1
        assert r.json()["citations"][0]["score"] == calls[-1] - 1

    await _with_api(scenario)
