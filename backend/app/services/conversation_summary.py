"""Running summaries of long chat sessions.

A chat prompt holds the question, retrieved passages and as much recent conversation as
fits (services/prompt_budget.py). Without a summary, older exchanges simply drop out, and
the model forgets what the conversation was about. So once the conversation not yet
summarized grows past a share of the prompt space, its oldest exchanges are folded into
a running summary stored on the session (ChatSession.summary, covering messages up to
ChatSession.summary_through). Prompts then send the summary in place of those messages.

Folding runs after an answer is saved, in the background, so it never delays an answer.
It folds well below the threshold (to half of it), so it happens every few turns rather
than every turn. Two folds racing on the same session can't overwrite each other: a fold
is only saved if the summary hasn't changed since it started.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.services.llm import LLMConfig, LLMMessage, LLMService
from backend.app.services.prompt_budget import message_tokens, prompt_space

logger = logging.getLogger(__name__)

# Fold once the history after the summary needs more than this share of the prompt
# space, and fold down to half of it.
FOLD_AT = 0.35
FOLD_TO = 0.5
# Summary length: this share of the prompt space, at most this many tokens.
SUMMARY_SHARE = 0.08
SUMMARY_MAX_TOKENS = 600
# Longest piece of one message passed to the summarizer, in characters.
_MAX_MESSAGE_CHARS = 4000


@dataclass(frozen=True)
class Exchange:
    question: str
    answer: str
    through: dt.datetime  # created_at of the answer


def exchanges_after(messages: Sequence[ChatMessage], through: dt.datetime | None) -> list[Exchange]:
    """Answered (question, answer) pairs among messages created after `through`, oldest first.
    Unanswered questions and system or empty messages are skipped, as in prompts."""
    out: list[Exchange] = []
    pending: str | None = None
    for m in messages:
        if through is not None and m.created_at <= through:
            continue
        if not (m.content or "").strip() or m.role not in {"user", "assistant"}:
            continue
        if m.role == "user":
            pending = m.content
        elif pending is not None:
            out.append(Exchange(pending, m.content, m.created_at))
            pending = None
    return out


def _cost(e: Exchange) -> int:
    return message_tokens(e.question) + message_tokens(e.answer)


def exchanges_to_fold(exchanges: Sequence[Exchange], context_window: int, reserve_for_answer: int) -> int:
    """How many of the oldest exchanges to fold into the summary now (0 = none yet).
    The newest exchange is always kept word for word."""
    space = prompt_space(context_window, reserve_for_answer)
    costs = [_cost(e) for e in exchanges]
    remaining = sum(costs)
    if remaining <= FOLD_AT * space:
        return 0
    target = FOLD_AT * FOLD_TO * space
    n = 0
    while n < len(costs) - 1 and remaining > target:
        remaining -= costs[n]
        n += 1
    return n


def summary_token_cap(context_window: int, reserve_for_answer: int) -> int:
    return max(64, min(SUMMARY_MAX_TOKENS, int(SUMMARY_SHARE * prompt_space(context_window, reserve_for_answer))))


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_MESSAGE_CHARS else text[:_MAX_MESSAGE_CHARS] + " [...]"


def fold_prompt(previous: str | None, exchanges: Sequence[Exchange], max_words: int) -> list[LLMMessage]:
    # Small models tend to answer with just the new messages, dropping the summary so far;
    # the instructions spell out that the result replaces it.
    instructions = (
        "You keep a running summary of a conversation between a user and an assistant that "
        "answers from the user's documents. You get the current summary and the messages "
        "that came after it. Write the new summary. It replaces the current summary, so it "
        "must keep everything from the current summary that may still matter, and add what "
        "the new messages contribute: what the user is working on and asked, the facts, "
        "figures, names and sources given in answers, decisions, and open questions. Write "
        f"plain prose in the conversation's language, at most {max_words} words. Do not "
        "copy the messages or write 'User:' or 'Assistant:'. Reply with the summary only."
    )
    current = previous.strip() if previous and previous.strip() else "(none yet)"
    lines = ["<current_summary>", current, "</current_summary>", "", "<new_messages>"]
    for e in exchanges:
        lines += [f"User: {_clip(e.question)}", f"Assistant: {_clip(e.answer)}"]
    lines += ["</new_messages>", "", "Write the new summary."]
    return [LLMMessage(role="system", content=instructions), LLMMessage(role="user", content="\n".join(lines))]


_TRANSCRIPT_LINE = re.compile(r"^\s*(user|assistant)\s*:", re.IGNORECASE | re.MULTILINE)


def looks_like_summary(text: str) -> bool:
    """Reject output that is a transcript rather than a summary: a model that echoes the
    messages drops the summary so far, and saving that would lose it."""
    return bool(text.strip()) and not _TRANSCRIPT_LINE.search(text)


async def refresh_summary(
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    llm_config: LLMConfig,
    make_llm: Callable[[LLMConfig], LLMService],
) -> bool:
    """Fold the session's oldest unsummarized exchanges into its summary if its history
    has grown past the threshold. Returns True if a new summary was saved."""
    if not settings.chat_summary_enabled:
        return False
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        row = (
            await db.execute(
                sa.select(ChatSession.summary, ChatSession.summary_through).where(
                    ChatSession.id == session_id,
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            return False
        previous, through = row
        query = sa.select(ChatMessage).where(ChatMessage.session_id == session_id)
        if through is not None:
            query = query.where(ChatMessage.created_at > through)
        messages = (await db.execute(query.order_by(ChatMessage.created_at.asc()))).scalars().all()

    exchanges = exchanges_after(messages, through)
    n = exchanges_to_fold(exchanges, llm_config.context_window, llm_config.max_tokens)
    if n == 0:
        return False
    fold = exchanges[:n]

    cap = summary_token_cap(llm_config.context_window, llm_config.max_tokens)
    llm = make_llm(llm_config.model_copy(update={"max_tokens": cap}))
    result = await llm.generate(fold_prompt(previous, fold, max_words=int(cap * 0.7)))
    summary = (result.content or "").strip()
    if not looks_like_summary(summary):
        logger.warning("Summarizing chat session %s returned no usable summary; keeping the old one", session_id)
        return False

    async with Session() as db:
        saved = await db.execute(
            sa.update(ChatSession)
            .where(
                ChatSession.id == session_id,
                # Only if nobody else updated it meanwhile.
                ChatSession.summary_through.is_not_distinct_from(through),
            )
            .values(summary=summary, summary_through=fold[-1].through)
        )
        await db.commit()
    if saved.rowcount != 1:
        logger.info("Chat session %s was summarized concurrently; discarding this summary", session_id)
        return False
    logger.info("Chat session %s: folded %d exchange(s) into its summary", session_id, n)
    return True
