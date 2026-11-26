from __future__ import annotations

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
from backend.app.core.deps import require_tenant_membership
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.llm import LLMMessage, LLMService, LLMResult, default_llm_config, create_llm_service
from backend.app.services.search import SearchHit, SearchService


logger = logging.getLogger(__name__)

_EMPTY_REPLY = "The model returned an empty response"

router = APIRouter(prefix="/chat")


class CreateSessionRequest(BaseModel):
    kb_ids: list[uuid.UUID] = Field(min_length=1)
    system_prompt: str | None = None
    name: str | None = None


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
    content: str = Field(min_length=1, max_length=10_000)
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


def _make_llm_service() -> LLMService:
    cfg = default_llm_config()
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


async def _build_context_from_hits(hits: list[SearchHit]) -> str:
    lines: list[str] = []
    for i, h in enumerate(hits, start=1):
        # Keep context compact but still traceable.
        lines.append(f"[{i}] doc_id={h.doc_id} score={h.score:.3f}\n{h.content}\n")
    return "\n".join(lines)


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

    # For now we support a single KB per session for retrieval; if multiple are configured,
    # we use the first one. Multi-KB retrieval can be added later.
    kb = session.knowledge_bases[0]

    # Load prior turns before adding the new user message; it is appended explicitly
    # below as the final user turn.
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

    # Retrieve relevant chunks.
    search = SearchService()
    hits = await search.search(
        tenant_id=tenant_id,
        kb_id=kb.id,
        query=req.content,
        top_k=req.top_k,
    )
    context_text = await _build_context_from_hits(hits)

    # Build LLM messages: system prompt + retrieved context + history + current user message.
    # Context goes in a separate system message to keep it clearly delimited.
    llm_messages: list[LLMMessage] = []
    if session.system_prompt:
        llm_messages.append(LLMMessage(role="system", content=session.system_prompt))
    llm_messages.append(
        LLMMessage(
            role="system",
            content=(
                "You are a helpful assistant for the RagNex system. "
                "Answer the user's question using ONLY the following retrieved context.\n\n"
                f"Context:\n{context_text}"
            ),
        )
    )
    for m in history:
        # Empty messages can't be sent (LLMMessage requires content); older rows may
        # contain one from before empty replies were rejected.
        if m.role == "system" or not m.content.strip():
            continue
        role = m.role if m.role in {"user", "assistant"} else "user"
        llm_messages.append(LLMMessage(role=role, content=m.content))
    llm_messages.append(LLMMessage(role="user", content=req.content))

    return _PreparedTurn(
        session=session,
        user_msg=user_msg,
        llm_messages=llm_messages,
        citations=_build_citations_from_hits(hits),
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

    llm: LLMService = _make_llm_service()
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
    or `error`: {"detail": "..."} if generation fails part-way (nothing is persisted
    for the assistant in that case; the user message is kept).

    Validation errors (404/400) are returned as normal HTTP errors before streaming starts.
    """
    tenant_id, user = ctx
    turn = await _prepare_turn(db, tenant_id, user.id, session_id, req)

    # Commit the user message now: the stream outlives this request-scoped work,
    # and the reply is saved with its own DB session below.
    await db.commit()
    await db.refresh(turn.user_msg)
    user_payload = _to_message_response(turn.user_msg).model_dump(mode="json")

    llm: LLMService = _make_llm_service()

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("meta", {"user_message": user_payload, "citations": turn.citations})

        parts: list[str] = []
        try:
            async for fragment in llm.generate_stream(turn.llm_messages):
                parts.append(fragment)
                yield _sse("delta", {"text": fragment})
        except Exception as exc:  # noqa: BLE001 - surface any provider failure to the client
            logger.exception("LLM streaming failed for chat session %s", session_id)
            yield _sse("error", {"detail": f"Generation failed: {type(exc).__name__}"})
            return

        if not "".join(parts).strip():
            yield _sse("error", {"detail": _EMPTY_REPLY})
            return

        SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with SessionLocal() as write_db:
            assistant_msg = ChatMessage(
                tenant_id=tenant_id,
                session_id=session_id,
                role="assistant",
                content="".join(parts),
                citations=turn.citations,
            )
            write_db.add(assistant_msg)
            await write_db.commit()
            await write_db.refresh(assistant_msg)
        yield _sse("done", _to_message_response(assistant_msg).model_dump(mode="json"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stop reverse proxies (nginx) from buffering the stream.
            "X-Accel-Buffering": "no",
        },
    )
