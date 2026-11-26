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
    # The earlier question was never really answered, so it is left out rather than
    # sent as two user turns in a row.
    assert sent == [("user", "next question")]


@pytest.mark.asyncio
async def test_prompt_keeps_answered_exchanges_and_skips_unanswered_questions(monkeypatch):
    """A failed/interrupted turn leaves a question with no answer in history; the next
    prompt must still alternate user/assistant and end with the new question."""
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    prompts = _patch_generate(monkeypatch, chat_module, "ok")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        await _insert_messages(
            session_id,
            headers,
            [("user", "q1"), ("assistant", "a1"), ("user", "q2 (generation failed)"), ("user", "q3"), ("assistant", "a3")],
        )
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "q4"}, headers=headers
        )
    assert r.status_code == 200, r.text
    sent = [(m.role, m.content) for m in prompts[0] if m.role != "system"]
    assert sent == [("user", "q1"), ("assistant", "a1"), ("user", "q3"), ("assistant", "a3"), ("user", "q4")]


@pytest.mark.asyncio
async def test_long_history_is_trimmed_to_context_window(monkeypatch):
    """With a small window, only the newest exchanges that fit are sent, plus the question."""
    from backend.app.api.v1 import chat as chat_module
    from backend.app.services import llm as llm_module

    monkeypatch.setattr(llm_module.settings, "llm_context_window", 1200)
    monkeypatch.setattr(llm_module.settings, "llm_max_tokens", 200)
    _patch_search(monkeypatch, chat_module)
    prompts = _patch_generate(monkeypatch, chat_module, "ok")

    filler = " ".join(["word"] * 60)  # ~60+ tokens per message
    rows = []
    for i in range(30):
        rows += [("user", f"q{i} {filler}"), ("assistant", f"a{i} {filler}")]

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        await _insert_messages(session_id, headers, rows)
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "latest question"}, headers=headers
        )
    assert r.status_code == 200, r.text

    sent = [(m.role, m.content.split()[0]) for m in prompts[0] if m.role != "system"]
    assert sent[-1] == ("user", "latest")
    kept = sent[:-1]
    assert 0 < len(kept) < 60, "history should be trimmed, but not dropped entirely"
    # Kept history is the newest, contiguous, complete exchanges.
    n = len(kept) // 2
    assert kept == [x for i in range(30 - n, 30) for x in (("user", f"q{i}"), ("assistant", f"a{i}"))]
    # The retrieved context is still there.
    assert any("context chunk one" in m.content for m in prompts[0] if m.role == "system")


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
