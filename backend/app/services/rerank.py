"""Re-ranking search results with a cross-encoder model served over HTTP.

Search finds candidates by keywords and by vector similarity; a re-ranker then reads the
question and each candidate passage together and scores how well the passage answers it,
which is more accurate than either signal alone. It runs as a separate service:

- RERANK_PROVIDER=cohere: the common `POST {base}/rerank` API
  ({model, query, documents, top_n} -> {results: [{index, relevance_score}]}), served by
  vLLM, Infinity, Jina and Cohere.
- RERANK_PROVIDER=tei: Hugging Face Text Embeddings Inference,
  `POST {base}/rerank` ({query, texts} -> [{index, score}]).
- RERANK_PROVIDER=none (default): no re-ranking.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from backend.app.core.config import settings
from backend.app.core.http import tls_context


class RerankError(RuntimeError):
    """The re-ranker couldn't be used for this request."""


@dataclass(frozen=True)
class Ranked:
    index: int  # position in the documents passed in
    score: float


def rerank_enabled() -> bool:
    return settings.rerank_provider in {"cohere", "tei"} and bool(settings.rerank_base_url)


def _parse(provider: str, payload: object, count: int) -> list[Ranked]:
    if provider == "cohere":
        items = payload.get("results") if isinstance(payload, dict) else None
        key = "relevance_score"
    else:
        items = payload
        key = "score"
    if not isinstance(items, list):
        raise RerankError("unexpected response from the re-ranker")
    ranked = []
    for item in items:
        try:
            index, score = int(item["index"]), float(item[key])
        except (KeyError, TypeError, ValueError) as e:
            raise RerankError("unexpected response from the re-ranker") from e
        if not 0 <= index < count:
            raise RerankError("the re-ranker returned an index out of range")
        ranked.append(Ranked(index, score))
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked


async def rerank(query: str, documents: Sequence[str], *, client: httpx.AsyncClient | None = None) -> list[Ranked]:
    """Scores for `documents` against `query`, best first. Raises RerankError."""
    if not documents:
        return []
    provider = settings.rerank_provider
    url = f"{settings.rerank_base_url.rstrip('/')}/rerank"
    if provider == "cohere":
        body: dict = {"model": settings.rerank_model, "query": query, "documents": list(documents), "top_n": len(documents)}
    else:
        body = {"query": query, "texts": list(documents), "truncate": True}
    headers = {"Authorization": f"Bearer {settings.rerank_api_key}"} if settings.rerank_api_key else {}

    owned = client is None
    client = client or httpx.AsyncClient(timeout=settings.rerank_timeout_s, verify=tls_context())
    try:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as e:
        raise RerankError(f"the re-ranker answered HTTP {e.response.status_code}") from e
    except (httpx.HTTPError, ValueError) as e:
        raise RerankError(f"the re-ranker couldn't be reached ({type(e).__name__})") from e
    finally:
        if owned:
            await client.aclose()
    return _parse(provider, payload, len(documents))
