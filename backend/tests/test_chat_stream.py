from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.chat import ChatMessage
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.services.search import SearchHit


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        assert event is not None and data is not None, block
        events.append((event, data))
    return events


async def _setup_session(client: httpx.AsyncClient) -> tuple[dict, uuid.UUID]:
    """Register a user, create a KB and a chat session. Returns (headers, session_id)."""
    email = f"stream_{uuid.uuid4().hex}@example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "pw"})
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]

    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        tenant_id = (
            await db.execute(
                sa.text(
                    "select m.tenant_id from tenant_memberships m "
                    "join users u on u.id=m.user_id where u.email=:email limit 1"
                ),
                {"email": email},
            )
        ).scalar_one()
        kb = KnowledgeBase(tenant_id=tenant_id, name="kb-stream")
        db.add(kb)
        await db.commit()
        kb_id = kb.id

    headers = {"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)}
    r = await client.post("/api/v1/chat/sessions", json={"kb_ids": [str(kb_id)]}, headers=headers)
    assert r.status_code == 201, r.text
    return headers, uuid.UUID(r.json()["id"])


async def _messages_in_db(session_id: uuid.UUID) -> list[tuple[str, str]]:
    Session = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with Session() as db:
        res = await db.execute(
            sa.select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return [(role, content) for role, content in res.all()]


def _patch_search(monkeypatch, chat_module) -> None:
    async def fake_search(self, *, tenant_id, kb_id, query, top_k=10, **_kwargs):
        return [
            SearchHit(
                chunk_id="c1",
                doc_id="d1",
                kb_id=str(kb_id),
                tenant_id=str(tenant_id),
                content="context chunk one",
                score=1.0,
                source="hybrid",
            )
        ]

    monkeypatch.setattr(chat_module.SearchService, "search", fake_search, raising=True)


def _patch_llm(monkeypatch, chat_module, fragments: list[str], fail_after: int | None = None) -> list:
    """Install a fake LLM that streams `fragments`; returns a list capturing the prompts."""
    seen_prompts: list = []

    class StreamingLLM(chat_module.LLMService):
        async def generate(self, messages):
            raise AssertionError("streaming endpoint must not call generate()")

        async def generate_stream(self, messages):
            seen_prompts.append(messages)
            for i, f in enumerate(fragments):
                if fail_after is not None and i == fail_after:
                    raise RuntimeError("provider exploded")
                yield f

    monkeypatch.setattr(
        chat_module, "_make_llm_service", lambda: StreamingLLM(chat_module.default_llm_config()), raising=True
    )
    return seen_prompts


@pytest.mark.asyncio
async def test_stream_message_emits_events_and_persists(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    prompts = _patch_llm(monkeypatch, chat_module, ["Hello", ", ", "world\nsecond line"])

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)

        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages/stream",
            json={"content": "Say hello"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(r.text)
    names = [e for e, _ in events]
    assert names == ["meta", "delta", "delta", "delta", "done"]

    meta = events[0][1]
    assert meta["user_message"]["role"] == "user"
    assert meta["user_message"]["content"] == "Say hello"
    assert meta["citations"][0]["chunk_id"] == "c1"

    # Newlines inside a fragment survive SSE framing thanks to JSON encoding.
    assert "".join(d["text"] for e, d in events if e == "delta") == "Hello, world\nsecond line"

    done = events[-1][1]
    assert done["role"] == "assistant"
    assert done["content"] == "Hello, world\nsecond line"
    assert done["citations"][0]["doc_id"] == "d1"

    assert await _messages_in_db(session_id) == [
        ("user", "Say hello"),
        ("assistant", "Hello, world\nsecond line"),
    ]

    # The new user turn reaches the model exactly once, as the final message.
    user_turns = [m.content for m in prompts[0] if m.role == "user"]
    assert user_turns == ["Say hello"]
    assert prompts[0][-1].content == "Say hello"


@pytest.mark.asyncio
async def test_stream_message_llm_failure_emits_error(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    _patch_llm(monkeypatch, chat_module, ["partial", "never sent"], fail_after=1)

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages/stream",
            json={"content": "Will fail"},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    events = _parse_sse(r.text)
    assert [e for e, _ in events] == ["meta", "delta", "error"]
    assert "RuntimeError" in events[-1][1]["detail"]
    # Provider error text is not leaked to the client.
    assert "exploded" not in events[-1][1]["detail"]

    # User message is kept; no partial assistant message is saved.
    assert await _messages_in_db(session_id) == [("user", "Will fail")]


@pytest.mark.asyncio
async def test_stream_message_unknown_session_is_404(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_llm(monkeypatch, chat_module, ["unused"])

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, _ = await _setup_session(client)
        r = await client.post(
            f"/api/v1/chat/sessions/{uuid.uuid4()}/messages/stream",
            json={"content": "hi"},
            headers=headers,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Chat session not found"


async def _stream_and_disconnect_after_first_event(app, path: str, headers: dict, payload: dict) -> list[bytes]:
    """Drive the ASGI app directly and send http.disconnect once the first SSE event
    has been written, like a browser tab closing mid-answer. Returns body chunks seen."""
    body = json.dumps(payload).encode()
    request_sent = False
    disconnect = asyncio.Event()
    chunks: list[bytes] = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append(message["body"])
            disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in {**headers, "Content-Type": "application/json"}.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=10)
    return chunks


@pytest.mark.asyncio
async def test_answer_is_saved_even_if_client_disconnects_mid_stream(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _patch_search(monkeypatch, chat_module)
    release = asyncio.Event()

    class SlowLLM(chat_module.LLMService):
        async def generate(self, messages):
            raise AssertionError("not used")

        async def generate_stream(self, messages):
            yield "First half, "
            await release.wait()  # the client is gone by the time we continue
            yield "second half."

    monkeypatch.setattr(chat_module, "_make_llm_service", lambda: SlowLLM(chat_module.default_llm_config()))

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, session_id = await _setup_session(client)

    chunks = await _stream_and_disconnect_after_first_event(
        app, f"/api/v1/chat/sessions/{session_id}/messages/stream", headers, {"content": "Tell me"}
    )
    received = b"".join(chunks).decode()
    assert "event: meta" in received and "second half" not in received

    # The request is over; generation must still be running, then finish and save.
    assert chat_module._generation_tasks, "generation should outlive the disconnected request"
    release.set()
    await asyncio.wait_for(asyncio.gather(*chat_module._generation_tasks), timeout=10)

    assert await _messages_in_db(session_id) == [
        ("user", "Tell me"),
        ("assistant", "First half, second half."),
    ]
