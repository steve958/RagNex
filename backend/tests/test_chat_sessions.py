from __future__ import annotations

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.knowledge_base import KnowledgeBase


@pytest.mark.asyncio
async def test_chat_session_crud_flow():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"chat_{uuid.uuid4().hex}@example.com"
    password = "pw"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user and get access token
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        # Look up default tenant for this user
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

            # Create a knowledge base for the tenant
            kb = KnowledgeBase(tenant_id=tenant_id, name="kb-chat")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

        # Create chat session associated with that KB
        create_payload = {
            "kb_ids": [str(kb_id)],
            "system_prompt": "You are RagNex.",
            "name": "Test session",
        }
        r = await client.post(
            "/api/v1/chat/sessions",
            json=create_payload,
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        session_id = uuid.UUID(body["id"])
        assert body["name"] == "Test session"
        assert body["system_prompt"] == "You are RagNex."
        assert body["kb_ids"] == [str(kb_id)]

        # List sessions for this user/tenant
        r = await client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        sessions = r.json()
        assert len(sessions) == 1
        assert sessions[0]["id"] == str(session_id)

        # Get single session
        r = await client.get(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        sess = r.json()
        assert sess["id"] == str(session_id)
        assert sess["kb_ids"] == [str(kb_id)]

        # Delete session
        r = await client.delete(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # After deletion, list should be empty
        r = await client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        assert r.json() == []


@pytest.mark.asyncio
async def test_chat_session_rejects_unknown_kb():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"chat_{uuid.uuid4().hex}@example.com"
    password = "pw"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

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

        # Use a random kb_id that does not exist for this tenant
        bad_kb_id = uuid.uuid4()
        r = await client.post(
            "/api/v1/chat/sessions",
            json={"kb_ids": [str(bad_kb_id)]},
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 404
