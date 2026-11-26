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
async def test_upload_document_creates_row_and_enqueues(monkeypatch):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"u_{uuid.uuid4().hex}@example.com"
    password = "test-password-1"

    # Patch storage upload to avoid requiring local MinIO.
    async def fake_upload(self, tenant_id, file):
        return "test/key"

    monkeypatch.setattr("backend.app.api.v1.documents.StorageService.upload_file", fake_upload)

    class DummyAsyncResult:
        def __init__(self, id_: str):
            self.id = id_

    def fake_apply_async(*args, **kwargs):
        return DummyAsyncResult("task123")

    monkeypatch.setattr("backend.app.api.v1.documents.parse_document.apply_async", fake_apply_async)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        # Find default tenant_id for the user
        eng = get_engine()
        Session = async_sessionmaker(eng, expire_on_commit=False)
        async with Session() as db:
            tenant_id = (await db.execute(sa.text(
                "select t.id from tenants t join tenant_memberships m on m.tenant_id=t.id join users u on u.id=m.user_id where u.email=:email limit 1"
            ), {"email": email})).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

        files = {"file": ("a.txt", b"hello", "text/plain")}
        r = await client.post(
            f"/api/v1/knowledgebases/{kb_id}/documents",
            files=files,
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kb_id"] == str(kb_id)
        assert body["filename"] == "a.txt"
        assert body["status"] == "pending"
        assert body["task_id"] == "task123"

        # Verify document exists in DB
        async with Session() as db:
            row = (await db.execute(sa.text("select filename, status, storage_key from documents where id=:id"), {"id": body["id"]})).mappings().one()
            assert row["filename"] == "a.txt"
            assert row["status"] == "pending"
            assert row["storage_key"] == "test/key"


@pytest.mark.asyncio
async def test_upload_document_rejects_extension(monkeypatch):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"u_{uuid.uuid4().hex}@example.com"
    password = "test-password-1"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        eng = get_engine()
        Session = async_sessionmaker(eng, expire_on_commit=False)
        async with Session() as db:
            tenant_id = (await db.execute(sa.text(
                "select t.id from tenants t join tenant_memberships m on m.tenant_id=t.id join users u on u.id=m.user_id where u.email=:email limit 1"
            ), {"email": email})).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb")
            db.add(kb)
            await db.commit()
            kb_id = kb.id

        files = {"file": ("a.exe", b"nope", "application/octet-stream")}
        r = await client.post(
            f"/api/v1/knowledgebases/{kb_id}/documents",
            files=files,
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 400
