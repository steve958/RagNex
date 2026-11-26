from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.db import get_db, get_engine
from backend.app.core.validation import Name, Text
from backend.app.core.deps import require_tenant_membership
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.llm import LLMConfig, LLMMessage, LLMService, LLMResult, create_llm_service
from backend.app.services.model_settings import load_tenant_llm_config
from backend.app.services.prompt_budget import build_prompt
from backend.app.services.search import SearchHit, SearchService


logger = logging.getLogger(__name__)

_EMPTY_REPLY = "The model returned an empty response"
KB_DELETED_DETAIL = "This chat's knowledge base has been deleted, so it can't answer new questions"

router = APIRouter(prefix="/chat")


class CreateSessionRequest(BaseModel):
    kb_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    # Sent with every message, so bounded well below the context window.
    system_prompt: Text(10_000) | None = None
    name: Name() | None = None


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    system_prompt: str | None
    kb_ids: list[uuid.UUID]
    created_at: datetime


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    kb_id: str
    score: float


class ChatMessageRequest(BaseModel):
    content: Text(10_000) = Field(min_length=1)
    top_k: int = Field(default=6, ge=1, le=20)


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[Citation]
    created_at: datetime


class MessageHistoryItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[Citation]
    created_at: datetime
    token_estimate: int


class MessageHistoryResponse(BaseModel):
    items: list[MessageHistoryItem]
    total: int
    offset: int
    limit: int


async def _load_kbs(db: AsyncSession, tenant_id: uuid.UUID, kb_ids: list[uuid.UUID]) -> list[KnowledgeBase]:
    if not kb_ids:
        raise HTTPException(status_code=400, detail="kb_ids must not be empty")

    res = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.id.in_(kb_ids),
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kbs = res.scalars().all()
    found_ids = {kb.id for kb in kbs}
    if len(found_ids) != len(set(kb_ids)):
        missing = sorted({str(k) for k in kb_ids if k not in found_ids})
        raise HTTPException(status_code=404, detail={"error": "Knowledge base not found", "kb_ids": missing})
    return kbs


def _to_response(session: ChatSession) -> ChatSessionResponse:
    kb_ids = [kb.id for kb in session.knowledge_bases]
    return ChatSessionResponse(
        id=session.id,
        name=session.name,
        system_prompt=session.system_prompt,
        kb_ids=kb_ids,
        created_at=session.created_at,
    )


def _estimate_tokens(text: str) -> int:
    # Very rough token estimate; good enough for relative sizing and metadata.
    return max(1, len(text.split()))


def _to_message_response(msg: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        citations=[Citation(**c) for c in (msg.citations or [])],
        created_at=msg.created_at,
    )


def _to_history_item(msg: ChatMessage) -> MessageHistoryItem:
    return MessageHistoryItem(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        citations=[Citation(**c) for c in (msg.citations or [])],
        created_at=msg.created_at,
        token_estimate=_estimate_tokens(msg.content or ""),
    )


def _make_llm_service(cfg: LLMConfig) -> LLMService:
    return create_llm_service(cfg)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    req: CreateSessionRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    tenant_id, user = ctx

    kbs = await _load_kbs(db, tenant_id, req.kb_ids)

    session = ChatSession(
        tenant_id=tenant_id,
        user_id=user.id,
        name=req.name,
        system_prompt=req.system_prompt,
    )
    session.knowledge_bases = kbs

    db.add(session)
    await db.commit()
    await db.refresh(session)

    return _to_response(session)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionResponse]:
    tenant_id, user = ctx

    res = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
        .order_by(ChatSession.created_at.desc())
    )
    sessions = res.scalars().unique().all()

    # knowledge_bases is configured with selectin loading, so accessing it here is safe.
    return [_to_response(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    tenant_id, user = ctx

    res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    )
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Ensure knowledge_bases is loaded for response conversion.
    await db.refresh(session)
    return _to_response(session)


@router.delete("/sessions/{session_id}", response_model=dict)
async def delete_session(
    session_id: uuid.UUID,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, user = ctx

    res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    )
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Hard delete for now; schema supports soft-delete if needed later.
    await db.delete(session)
    await db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=MessageHistoryResponse)
async def list_messages(
    session_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    latest: bool = False,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> MessageHistoryResponse:
    """List messages for a chat session with basic offset/limit pagination.

    With `latest=true`, `offset` is ignored and the newest `limit` messages are returned
    (still oldest-first); the response's `offset` says where that page starts.

    The endpoint is scoped to the current tenant and user; cross-tenant or
    cross-user access is forbidden via the session lookup.
    """

    tenant_id, user = ctx

    # Verify the session exists and belongs to this user/tenant.
    res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    )
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    offset = max(0, int(offset))
    limit = max(1, min(100, int(limit)))

    # Total count
    res = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id == session.id,
            ChatMessage.tenant_id == tenant_id,
        )
    )
    total = int(res.scalar_one() or 0)
    if latest:
        offset = max(0, total - limit)

    # Page of messages ordered by created_at ascending
    res = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session.id,
            ChatMessage.tenant_id == tenant_id,
        )
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    msgs = res.scalars().all()

    return MessageHistoryResponse(
        items=[_to_history_item(m) for m in msgs],
        total=total,
        offset=offset,
        limit=limit,
    )


async def _load_history_messages(db: AsyncSession, session: ChatSession) -> list[ChatMessage]:
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    return res.scalars().all()


def _build_citations_from_hits(hits: list[SearchHit], limit: int = 5) -> list[dict]:
    out: list[dict] = []
    for h in hits[:limit]:
        out.append(
            {
                "chunk_id": h.chunk_id,
                "doc_id": h.doc_id,
                "kb_id": h.kb_id,
                "score": float(h.score),
            }
        )
    return out


@dataclass
class _PreparedTurn:
    session: ChatSession
    user_msg: ChatMessage
    llm_messages: list[LLMMessage]
    citations: list[dict]
    llm_config: LLMConfig  # the tenant's effective model settings


async def _prepare_turn(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    req: ChatMessageRequest,
) -> _PreparedTurn:
    """Shared setup for a chat turn: load session, persist (flush) the user message,
    retrieve context and build the LLM prompt. Raises HTTPException on invalid input."""

    res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user_id,
            ChatSession.deleted_at.is_(None),
        )
    )
    session = res.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Ensure knowledge bases are loaded.
    await db.refresh(session)
    if not session.knowledge_bases:
        raise HTTPException(status_code=400, detail="Chat session has no knowledge bases configured")
    live_kbs = [kb for kb in session.knowledge_bases if kb.deleted_at is None]
    if not live_kbs:
        # History stays readable; only new questions are refused.
        raise HTTPException(status_code=400, detail=KB_DELETED_DETAIL)

    # Load prior turns before adding the new user message; it is passed separately as
    # the current question.
    history = await _load_history_messages(db, session)

    user_msg = ChatMessage(
        tenant_id=tenant_id,
        session_id=session.id,
        role="user",
        content=req.content,
        citations=[],
    )
    db.add(user_msg)
    await db.flush()

    # Retrieve relevant chunks from all of the session's (live) knowledge bases, ranked together.
    search = SearchService()
    hits = await search.search(
        tenant_id=tenant_id,
        kb_ids=[kb.id for kb in live_kbs],
        query=req.content,
        top_k=req.top_k,
    )

    # Fit system prompt + context + history + question into the tenant model's context window.
    cfg = await load_tenant_llm_config(db, tenant_id)
    plan = build_prompt(
        question=req.content,
        hits=hits,
        history=[(m.role, m.content) for m in history],
        system_prompt=session.system_prompt,
        context_window=cfg.context_window,
        reserve_for_answer=cfg.max_tokens,
    )
    if plan.dropped_hits or plan.dropped_exchanges:
        logger.info(
            "Prompt trimmed to fit context window for chat session %s: dropped %d chunk(s), "
            "%d earlier exchange(s); ~%d tokens",
            session.id,
            plan.dropped_hits,
            plan.dropped_exchanges,
            plan.estimated_tokens,
        )

    return _PreparedTurn(
        session=session,
        user_msg=user_msg,
        llm_messages=plan.messages,
        # Cite only what the model was actually shown.
        citations=_build_citations_from_hits(plan.used_hits),
        llm_config=cfg,
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def send_message(
    session_id: uuid.UUID,
    req: ChatMessageRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> ChatMessageResponse:
    tenant_id, user = ctx
    turn = await _prepare_turn(db, tenant_id, user.id, session_id, req)

    llm: LLMService = _make_llm_service(turn.llm_config)
    result: LLMResult = await llm.generate(turn.llm_messages)
    if not result.content.strip():
        # Not committed, so the user message is rolled back too and can simply be resent.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_EMPTY_REPLY)

    assistant_msg = ChatMessage(
        tenant_id=tenant_id,
        session_id=turn.session.id,
        role="assistant",
        content=result.content,
        citations=turn.citations,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    return _to_message_response(assistant_msg)


def _sse(event: str, data: object) -> str:
    """Format one server-sent event. JSON-encoding the payload keeps newlines in
    model output from breaking SSE framing."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# Answers being generated in the background. Holding a reference keeps the event loop
# from garbage-collecting a task whose client has disconnected.
_generation_tasks: set[asyncio.Task] = set()


async def _generate_and_save(
    llm: LLMService,
    turn: _PreparedTurn,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    events: asyncio.Queue,
) -> None:
    """Generate the answer and persist it, publishing SSE events to `events`.

    Runs as its own task so the answer is completed and saved even if the client
    disconnects mid-stream. Always ends by putting `None` on the queue.
    """
    try:
        parts: list[str] = []
        try:
            async for fragment in llm.generate_stream(turn.llm_messages):
                parts.append(fragment)
                events.put_nowait(("delta", {"text": fragment}))
        except Exception as exc:  # noqa: BLE001 - surface any provider failure to the client
            logger.exception("LLM streaming failed for chat session %s", session_id)
            events.put_nowait(("error", {"detail": f"Generation failed: {type(exc).__name__}"}))
            return

        content = "".join(parts)
        if not content.strip():
            events.put_nowait(("error", {"detail": _EMPTY_REPLY}))
            return

        SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with SessionLocal() as write_db:
            assistant_msg = ChatMessage(
                tenant_id=tenant_id,
                session_id=session_id,
                role="assistant",
                content=content,
                citations=turn.citations,
            )
            write_db.add(assistant_msg)
            await write_db.commit()
            await write_db.refresh(assistant_msg)
        events.put_nowait(("done", _to_message_response(assistant_msg).model_dump(mode="json")))
    except Exception:  # noqa: BLE001 - e.g. DB failure while saving
        logger.exception("Saving the streamed answer failed for chat session %s", session_id)
        events.put_nowait(("error", {"detail": "Failed to save the answer"}))
    finally:
        events.put_nowait(None)


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: uuid.UUID,
    req: ChatMessageRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Like `send_message`, but streams the answer as server-sent events.

    Events, in order:
      - `meta`:  {"user_message": ChatMessage, "citations": [...]}
      - `delta`: {"text": "<fragment>"}  (repeated)
      - `done`:  ChatMessage (the persisted assistant message)
    or `error`: {"detail": "..."} if generation fails or returns nothing (no assistant
    message is saved then; the user message is kept, and is left out of later prompts).

    Generation is not tied to the connection: if the client disconnects, the answer is
    still completed and saved, and shows up in the session history.

    Validation errors (404/400) are returned as normal HTTP errors before streaming starts.
    """
    tenant_id, user = ctx
    turn = await _prepare_turn(db, tenant_id, user.id, session_id, req)

    # Commit the user message now: the stream outlives this request-scoped work,
    # and the reply is saved with its own DB session.
    await db.commit()
    await db.refresh(turn.user_msg)
    user_payload = _to_message_response(turn.user_msg).model_dump(mode="json")

    llm: LLMService = _make_llm_service(turn.llm_config)
    events: asyncio.Queue = asyncio.Queue()  # unbounded: the producer never waits on the client
    task = asyncio.create_task(_generate_and_save(llm, turn, tenant_id, session_id, events))
    _generation_tasks.add(task)
    task.add_done_callback(_generation_tasks.discard)

    async def event_stream() -> AsyncIterator[str]:
        # If the client disconnects, this generator is cancelled; the task is not.
        yield _sse("meta", {"user_message": user_payload, "citations": turn.citations})
        while (item := await events.get()) is not None:
            yield _sse(*item)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stop reverse proxies (nginx) from buffering the stream.
            "X-Accel-Buffering": "no",
        },
    )
