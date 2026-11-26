from __future__ import annotations

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.chat import ChatMessage

from test_chat_stream import _messages_in_db, _parse_sse, _patch_llm, _patch_search, _setup_session


def _patch_generate(monkeypatch, chat_module, reply: str) -> list:
    """Fake non-streaming LLM returning `reply`; returns a list capturing the prompts."""
    prompts: list = []

    class FixedLLM(chat_module.LLMService):
        async def generate(self, messages):
            prompts.append(messages)
            return chat_module.LLMResult(content=reply)

    monkeypatch.setattr(
        chat_module, "_make_llm_service", lambda: FixedLLM(chat_module.default_llm_config()), raising=True
    )
    return prompts


async def _insert_messages(session_id: uuid.UUID, headers: dict, rows: list[tuple[str, str]]) -> None:
    """Insert rows in ONE transaction: exactly the case that used to produce tied timestamps."""
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        for role, content in rows:
            db.add(
                ChatMessage(
                    tenant_id=uuid.UUID(headers["X-Tenant-ID"]),
                    session_id=session_id,
                    role=role,
                    content=content,
                    citations=[],
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_send_message_orders_question_before_answer(monkeypatch):
    """Question and answer are written in one transaction; they must not share a timestamp."""
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    _patch_generate(monkeypatch, chat_module, "the answer")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "the question"}, headers=headers
        )
        assert r.status_code == 200, r.text

    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        rows = (
            await db.execute(
                sa.select(ChatMessage.role, ChatMessage.created_at).where(ChatMessage.session_id == session_id)
            )
        ).all()
    stamps = {role: ts for role, ts in rows}
    assert stamps["user"] < stamps["assistant"]
    assert await _messages_in_db(session_id) == [("user", "the question"), ("assistant", "the answer")]


@pytest.mark.asyncio
async def test_empty_reply_is_rejected_and_not_saved(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    _patch_generate(monkeypatch, chat_module, "  \n")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "hello"}, headers=headers
        )
    assert r.status_code == 502
    assert r.json()["detail"] == "The model returned an empty response"
    # Rolled back as a whole, so the user can simply resend.
    assert await _messages_in_db(session_id) == []


@pytest.mark.asyncio
async def test_empty_streamed_reply_emits_error_and_is_not_saved(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    _patch_llm(monkeypatch, chat_module, [])  # model streams nothing

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages/stream", json={"content": "hello"}, headers=headers
        )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert [e for e, _ in events] == ["meta", "error"]
    assert events[-1][1]["detail"] == "The model returned an empty response"
    assert await _messages_in_db(session_id) == [("user", "hello")]


@pytest.mark.asyncio
async def test_session_with_stored_empty_message_still_works(monkeypatch):
    """An empty assistant row saved before the fix must not break every later turn."""
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    prompts = _patch_generate(monkeypatch, chat_module, "fine now")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        await _insert_messages(session_id, headers, [("user", "earlier question"), ("assistant", "")])

        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "next question"}, headers=headers
        )
    assert r.status_code == 200, r.text
    sent = [(m.role, m.content) for m in prompts[0] if m.role != "system"]
    assert sent == [("user", "earlier question"), ("user", "next question")]


@pytest.mark.asyncio
async def test_history_latest_returns_newest_page_in_order():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        await _insert_messages(
            session_id, headers, [("user" if i % 2 == 0 else "assistant", f"msg-{i}") for i in range(5)]
        )

        r = await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", params={"limit": 2, "latest": "true"}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert [m["content"] for m in body["items"]] == ["msg-3", "msg-4"]
        assert body["offset"] == 3 and body["total"] == 5

        # Fewer messages than the limit: everything, from the start.
        r = await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", params={"limit": 100, "latest": "true"}, headers=headers
        )
        assert [m["content"] for m in r.json()["items"]] == [f"msg-{i}" for i in range(5)]
        assert r.json()["offset"] == 0
