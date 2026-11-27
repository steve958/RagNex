"""Anthropic (Claude) chat provider, using the official `anthropic` SDK.

Used for answers and conversation summaries when LLM_PROVIDER (or a workspace's setting)
is "anthropic". Anthropic has no embedding API, so embeddings keep their own provider.

Differences from the other providers that callers should know:
- No temperature is sent: current Claude models reject sampling parameters.
- Thinking is on in current models and its tokens count toward max_tokens, so
  LLM_MAX_TOKENS needs room for it (docs/configuration.md).
- A refusal (stop_reason "refusal") raises LLMRefusal instead of returning empty text.
  On models that support it, refusals are first retried server-side on a fallback model
  (`fallbacks: "default"`), unless ANTHROPIC_REFUSAL_FALLBACK is off.
- Requests always stream (also for non-streamed answers), which avoids HTTP timeouts on
  long answers; the final message is collected at the end.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from backend.app.core.config import settings
from backend.app.services.llm import LLMError, LLMMessage, LLMRefusal, LLMResult, LLMService

logger = logging.getLogger(__name__)

# Models that accept server-side refusal fallbacks with `fallbacks: "default"`, which
# picks the fallback model by refusal category.
FALLBACK_MODELS = frozenset(
    {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def to_anthropic_messages(messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, str]]]:
    """RagNex messages -> (system, messages) for the Messages API.

    RagNex sends its system prompt, retrieved context and conversation summary as system
    messages; Claude takes those as the top-level `system` field."""
    system = [m.content for m in messages if m.role == "system"]
    turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
    if not turns or turns[0]["role"] != "user":
        raise LLMError("A Claude conversation must start with a user message")
    return ("\n\n".join(system) or None), turns


class AnthropicLLM(LLMService):
    def _client(self) -> anthropic.AsyncAnthropic:
        # api_key=None lets the SDK resolve credentials itself (ANTHROPIC_API_KEY, ...).
        kwargs: dict[str, Any] = {"api_key": self.cfg.api_key or settings.anthropic_api_key}
        if self.cfg.base_url:  # a workspace endpoint from TENANT_MODEL_BASE_URLS
            kwargs["base_url"] = self.cfg.base_url
        return anthropic.AsyncAnthropic(**kwargs)

    def _uses_fallbacks(self) -> bool:
        return settings.anthropic_refusal_fallback and self.cfg.model in FALLBACK_MODELS

    def _stream(self, client: anthropic.AsyncAnthropic, messages: list[LLMMessage]):
        system, turns = to_anthropic_messages(messages)
        params: dict[str, Any] = {"model": self.cfg.model, "max_tokens": self.cfg.max_tokens, "messages": turns}
        if system:
            params["system"] = system
        if self._uses_fallbacks():
            return client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks="default")
        return client.messages.stream(**params)

    def _check(self, message: Any) -> None:
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise LLMRefusal(getattr(details, "category", None) if details else None)
        if message.stop_reason == "max_tokens":
            logger.warning(
                "Claude answer cut off at max_tokens=%d (model %s); thinking counts toward it, "
                "so raise LLM_MAX_TOKENS",
                self.cfg.max_tokens,
                self.cfg.model,
            )

    async def generate(self, messages: list[LLMMessage]) -> LLMResult:
        async with self._client() as client:
            async with self._stream(client, messages) as stream:
                message = await stream.get_final_message()
        self._check(message)
        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage.to_dict() if getattr(message, "usage", None) is not None else None
        return LLMResult(content=text, model=message.model, finish_reason=message.stop_reason, usage=usage)

    async def generate_stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        async with self._client() as client:
            async with self._stream(client, messages) as stream:
                async for text in stream.text_stream:
                    yield text
                message = await stream.get_final_message()
        self._check(message)
