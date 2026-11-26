from __future__ import annotations

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.models.chat import ChatMessage
from backend.app.services.search import SearchHit


@pytest.mark.asyncio
async def test_chat_message_rag_flow_monkeypatched(monkeypatch):
    """Smoke-test the chat message endpoint with patched Search + LLM.

    This avoids requiring a running OpenSearch cluster or LLM backend.
    """

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"chatmsg_{uuid.uuid4().hex}@example.com"
    password = "pw"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user and obtain access token
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        # Resolve tenant and create a KB
        eng = get_engine()
        Session = async_sessionmaker(eng, expire_on_commit=False)
        async with Session() as db:
            tenant_id = (
                await db.execute(
                    sa.text(
                        "select t.id from tenants t "
                        "join tenant_memberships m on m.tenant_id=t.id "
                        "join users u on u.id=m.user_id "
                        "where u.email=:email limit 1"
                    ),
                    {"email": email},
                )
            ).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb-chat-msg")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

        # Create a chat session for that KB
        r = await client.post(
            "/api/v1/chat/sessions",
            json={"kb_ids": [str(kb_id)], "name": "RAG session"},
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 201, r.text
        session_id = uuid.UUID(r.json()["id"])

        # Patch SearchService.search and _make_llm_service in the chat module
        from backend.app.api.v1 import chat as chat_module

        async def fake_search(self, *, tenant_id, kb_id, query, top_k=10, **_kwargs):  # type: ignore[override]
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

        class DummyLLM(chat_module.LLMService):  # type: ignore[misc]
            async def generate(self, messages):  # type: ignore[override]
                # Echo last user message content with a prefix so we can assert on it.
                last_user = [m for m in messages if m.role == "user"][-1]
                return chat_module.LLMResult(content=f"ANSWER: {last_user.content}")

        def fake_make_llm_service() -> chat_module.LLMService:
            return DummyLLM(chat_module.default_llm_config())

        monkeypatch.setattr(chat_module, "_make_llm_service", fake_make_llm_service, raising=True)

        # Send a chat message through the RAG endpoint
        payload = {"content": "What is in the context?", "top_k": 3}
        r = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["role"] == "assistant"
        assert body["content"].startswith("ANSWER: ")
        # Citations should be present and reference the fake SearchHit
        assert body["citations"]
        assert body["citations"][0]["doc_id"] == "d1"
        assert body["citations"][0]["chunk_id"] == "c1"
        assert body["citations"][0]["kb_id"] == str(kb_id)


@pytest.mark.asyncio
async def test_chat_message_history_pagination():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"history_{uuid.uuid4().hex}@example.com"
    password = "pw"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user and obtain access token
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        # Resolve tenant and create a KB + session
        eng = get_engine()
        Session = async_sessionmaker(eng, expire_on_commit=False)
        async with Session() as db:
            tenant_id = (
                await db.execute(
                    sa.text(
                        "select t.id from tenants t "
                        "join tenant_memberships m on m.tenant_id=t.id "
                        "join users u on u.id=m.user_id "
                        "where u.email=:email limit 1"
                    ),
                    {"email": email},
                )
            ).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb-history")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

            # Create a session row directly
            from backend.app.models.chat import ChatSession

            session = ChatSession(tenant_id=tenant_id, user_id=(
                await db.execute(sa.text("select id from users where email=:email"), {"email": email})
            ).scalar_one())
            session.knowledge_bases = [kb]
            db.add(session)
            await db.commit()
            session_id = session.id

            # Insert a few messages
            for i in range(3):
                m = ChatMessage(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"msg-{i}",
                    citations=[],
                )
                db.add(m)
            await db.commit()

        # Page 1
        r = await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages",
            params={"offset": 0, "limit": 2},
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["offset"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["items"][0]["content"] == "msg-0"
        assert body["items"][0]["token_estimate"] >= 1

        # Page 2
        r = await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages",
            params={"offset": 2, "limit": 2},
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["offset"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["content"] == "msg-2"
