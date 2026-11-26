from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import AsyncIterator, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import settings


Role = Literal["user", "assistant", "system"]


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
        """Streaming interface.

        For now we provide a simple default that yields the full response once.
        Providers that support real streaming can override this in a follow-up
        task without changing callers.
        """

        result = await self.generate(messages)
        yield result.content


class OllamaLLM(LLMService):
    """LLM provider using the Ollama /api/chat HTTP API.

    See https://github.com/ollama/ollama for details. We intentionally keep
    the implementation minimal and only support non-streaming responses.
    """

    async def generate(self, messages: list[LLMMessage]) -> LLMResult:
        base_url = (self.cfg.base_url or settings.ollama_base_url).rstrip("/")
        url = f"{base_url}/api/chat"

        payload = {
            "model": self.cfg.model,
            "messages": [m.model_dump() for m in messages],
            "options": {
                "temperature": float(self.cfg.temperature),
                # max_tokens is provider-specific; Ollama treats this as num_predict.
                "num_predict": int(self.cfg.max_tokens),
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60.0)
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


class OpenAICompatibleLLM(LLMService):
    """LLM provider using OpenAI-compatible /chat/completions API.

    This is intended to work with OpenAI itself as well as vLLM or other
    services that mimic the OpenAI API surface.
    """

    async def generate(self, messages: list[LLMMessage]) -> LLMResult:
        base_url = (self.cfg.base_url or settings.openai_base_url).rstrip("/")
        url = f"{base_url}/chat/completions"

        api_key = self.cfg.api_key or settings.openai_api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.cfg.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": float(self.cfg.temperature),
            "max_tokens": int(self.cfg.max_tokens),
            "stream": False,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=60.0)
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
