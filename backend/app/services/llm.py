from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from typing import AsyncIterator, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import settings


Role = Literal["user", "assistant", "system"]

# Generous read timeout: local models can pause for a while between tokens
# (e.g. while loading weights), and a full non-streamed answer can take minutes.
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class LLMError(RuntimeError):
    """Raised when a provider returns an error payload (as opposed to an HTTP error)."""


class LLMMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class LLMConfig(BaseModel):
    """Configuration for an LLM provider.

    For now we support providers that expose either:
    - Ollama chat API (local HTTP server), or
    - OpenAI-compatible /v1/chat/completions endpoints (OpenAI, vLLM, etc.).
    """

    provider: Literal["ollama", "openai", "vllm"] = "ollama"
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048


@dataclass(frozen=True)
class LLMResult:
    content: str
    model: str | None = None
    finish_reason: str | None = None
    # Raw provider-specific usage payload, if available.
    usage: dict | None = None


class LLMService(abc.ABC):
    """Abstract interface for chat-style LLMs.

    This will be used by the RAG chat pipeline (P4-3).
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    @abc.abstractmethod
    async def generate(self, messages: list[LLMMessage]) -> LLMResult:  # pragma: no cover - interface
        """Generate a single response for the given conversation messages."""

    async def generate_stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Yield response text fragments as they are produced.

        Default for providers without native streaming: yield the full response once.
        """

        result = await self.generate(messages)
        yield result.content


class OllamaLLM(LLMService):
    """LLM provider using the Ollama /api/chat HTTP API.

    See https://github.com/ollama/ollama/blob/main/docs/api.md. Streaming responses
    are newline-delimited JSON objects, each carrying a `message.content` fragment.
    """

    def _request(self, messages: list[LLMMessage], *, stream: bool) -> tuple[str, dict]:
        base_url = (self.cfg.base_url or settings.ollama_base_url).rstrip("/")
        payload = {
            "model": self.cfg.model,
            "messages": [m.model_dump() for m in messages],
            "stream": stream,
            "options": {
                "temperature": float(self.cfg.temperature),
                # max_tokens is provider-specific; Ollama treats this as num_predict.
                "num_predict": int(self.cfg.max_tokens),
            },
        }
        return f"{base_url}/api/chat", payload

    async def generate(self, messages: list[LLMMessage]) -> LLMResult:
        url, payload = self._request(messages, stream=False)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        message = (data.get("message") or {})
        content = str(message.get("content") or "")
        return LLMResult(
            content=content,
            model=str(data.get("model") or self.cfg.model),
            finish_reason=str(data.get("done_reason") or ""),
            usage=None,
        )

    async def generate_stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        url, payload = self._request(messages, stream=True)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise LLMError(str(data["error"]))
                    fragment = (data.get("message") or {}).get("content")
                    if fragment:
                        yield fragment
                    if data.get("done"):
                        break


class OpenAICompatibleLLM(LLMService):
    """LLM provider using OpenAI-compatible /chat/completions API.

    This is intended to work with OpenAI itself as well as vLLM or other
    services that mimic the OpenAI API surface. Streaming uses server-sent
    events: `data: {json}` lines terminated by `data: [DONE]`.
    """

    def _request(self, messages: list[LLMMessage], *, stream: bool) -> tuple[str, dict, dict]:
        base_url = (self.cfg.base_url or settings.openai_base_url).rstrip("/")

        api_key = self.cfg.api_key or settings.openai_api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.cfg.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": float(self.cfg.temperature),
            "max_tokens": int(self.cfg.max_tokens),
            "stream": stream,
        }
        return f"{base_url}/chat/completions", headers, payload

    async def generate(self, messages: list[LLMMessage]) -> LLMResult:
        url, headers, payload = self._request(messages, stream=False)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("Empty choices in chat completion response")

        choice = choices[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "")

        return LLMResult(
            content=content,
            model=str(data.get("model") or self.cfg.model),
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=data.get("usage"),
        )

    async def generate_stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        url, headers, payload = self._request(messages, stream=True)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank separators, comments, event: lines
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    data = json.loads(data_str)
                    if data.get("error"):
                        raise LLMError(str(data["error"]))
                    choices = data.get("choices") or []
                    if not choices:
                        continue  # e.g. trailing usage-only chunk
                    fragment = (choices[0].get("delta") or {}).get("content")
                    if fragment:
                        yield fragment


def create_llm_service(cfg: LLMConfig) -> LLMService:
    """Factory that returns an appropriate LLMService implementation.

    This mirrors the pattern used by `create_embedding_service`.
    """

    if cfg.provider == "ollama":
        return OllamaLLM(cfg)
    if cfg.provider in {"openai", "vllm"}:
        return OpenAICompatibleLLM(cfg)
    raise ValueError(f"Unknown LLM provider: {cfg.provider}")


def default_llm_config() -> LLMConfig:
    """Build an LLMConfig from global Settings.

    Per-tenant overrides (P4-1) can be wired later by reading a JSONB field
    from the Tenant model, similar to `embedding_config`.
    """

    return LLMConfig(
        provider=settings.llm_provider,  # type: ignore[arg-type]
        model=settings.llm_model,
        base_url=None,
        temperature=float(settings.llm_temperature),
        max_tokens=int(settings.llm_max_tokens),
    )
