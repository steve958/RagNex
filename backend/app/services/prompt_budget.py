"""Fit a RAG chat prompt into the model's context window.

Priority when space runs out:
  1. system prompt + instructions + the current question (always sent)
  2. retrieved chunks, best-ranked first (lower-ranked ones are dropped)
  3. conversation history, newest exchanges first (older ones are dropped)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from deepdoc.common.token_utils import num_tokens_from_string

from backend.app.services.llm import LLMMessage
from backend.app.services.search import SearchHit

# Fill only this share of the window: token counts below are estimates, not the
# model's tokenizer.
_SAFETY_RATIO = 0.9
# Role markers / formatting the chat template adds per message.
_PER_MESSAGE_OVERHEAD = 4
# Never plan with less prompt space than this, even if settings are inconsistent.
_MIN_PROMPT_TOKENS = 512

RAG_INSTRUCTIONS = (
    "You are a helpful assistant for the RagNex system. "
    "Answer the user's question using ONLY the following retrieved context."
)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate. The word/punctuation count under-counts long or rare
    words that real tokenizers split, so also take ~4 chars/token and use the larger."""
    if not text:
        return 0
    return max(num_tokens_from_string(text), (len(text) + 3) // 4)


def _message_tokens(content: str) -> int:
    return estimate_tokens(content) + _PER_MESSAGE_OVERHEAD


def _hit_block(index: int, hit: SearchHit) -> str:
    # Keep context compact but still traceable.
    return f"[{index}] doc_id={hit.doc_id} score={hit.score:.3f}\n{hit.content}\n"


def _context_message(blocks: list[str]) -> str:
    return f"{RAG_INSTRUCTIONS}\n\nContext:\n" + "\n".join(blocks)


def answered_exchanges(history: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Reduce stored history to complete (question, answer) pairs.

    Drops system and empty messages, and user messages that never got an answer
    (generation failed or was interrupted), so the model never sees two questions
    in a row or an empty turn.
    """
    pairs: list[tuple[str, str]] = []
    pending_question: str | None = None
    for role, content in history:
        if not content.strip() or role not in {"user", "assistant"}:
            continue
        if role == "user":
            pending_question = content  # a newer question replaces an unanswered one
        elif pending_question is not None:
            pairs.append((pending_question, content))
            pending_question = None
    return pairs


@dataclass(frozen=True)
class PromptPlan:
    messages: list[LLMMessage]
    used_hits: list[SearchHit]
    dropped_hits: int
    dropped_exchanges: int
    estimated_tokens: int


def build_prompt(
    *,
    question: str,
    hits: Sequence[SearchHit],
    history: Sequence[tuple[str, str]],
    system_prompt: str | None,
    context_window: int,
    reserve_for_answer: int,
) -> PromptPlan:
    """Assemble system prompt + retrieved context + history + question within budget.

    `history` is (role, content) in chronological order, excluding the current question.
    """
    budget = max(_MIN_PROMPT_TOKENS, int(context_window * _SAFETY_RATIO) - reserve_for_answer)

    # 1. Always sent.
    used = _message_tokens(question) + _message_tokens(_context_message([]))
    if system_prompt:
        used += _message_tokens(system_prompt)

    # 2. Retrieved chunks in rank order; skip any that don't fit (a smaller, lower-ranked
    #    one may still fit after a large one is skipped).
    used_hits: list[SearchHit] = []
    blocks: list[str] = []
    for hit in hits:
        block = _hit_block(len(blocks) + 1, hit)
        cost = estimate_tokens(block) + 1  # +1 for the joining newline
        if used + cost <= budget:
            blocks.append(block)
            used_hits.append(hit)
            used += cost

    # 3. History, newest exchange first; stop at the first one that doesn't fit so the
    #    kept history stays contiguous.
    exchanges = answered_exchanges(history)
    kept: list[tuple[str, str]] = []
    for q, a in reversed(exchanges):
        cost = _message_tokens(q) + _message_tokens(a)
        if used + cost > budget:
            break
        kept.append((q, a))
        used += cost
    kept.reverse()

    messages: list[LLMMessage] = []
    if system_prompt:
        messages.append(LLMMessage(role="system", content=system_prompt))
    messages.append(LLMMessage(role="system", content=_context_message(blocks)))
    for q, a in kept:
        messages.append(LLMMessage(role="user", content=q))
        messages.append(LLMMessage(role="assistant", content=a))
    messages.append(LLMMessage(role="user", content=question))

    return PromptPlan(
        messages=messages,
        used_hits=used_hits,
        dropped_hits=len(hits) - len(used_hits),
        dropped_exchanges=len(exchanges) - len(kept),
        estimated_tokens=used,
    )
