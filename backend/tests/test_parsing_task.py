from __future__ import annotations

import uuid

import anyio
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.document import Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.tasks.parsing import parse_document


@pytest.mark.asyncio
async def test_parsing_task_updates_document_and_status_api(monkeypatch):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    email = f"u_{uuid.uuid4().hex}@example.com"
    password = "pw"

    # Patch out external deps.
    async def fake_download(self, tenant_id, object_key):
        return b"hello"

    monkeypatch.setattr("backend.app.tasks.parsing.StorageService.download_file", fake_download)

    def fake_parse(filename: str, binary: bytes, parser_config: dict | None = None):
        return {"filename": filename, "ext": ".txt", "sections": ["hello"], "tables": []}

    monkeypatch.setattr("backend.app.tasks.parsing.parse_document_binary", fake_parse)

    async def fake_publish(tenant_id, document_id, payload):
        return None

    monkeypatch.setattr("backend.app.tasks.parsing._publish_progress", fake_publish)

    eng = get_engine()
    Session = async_sessionmaker(eng, expire_on_commit=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        async with Session() as db:
            tenant_id = (await db.execute(
                sa.text(
                    "select t.id from tenants t join tenant_memberships m on m.tenant_id=t.id join users u on u.id=m.user_id where u.email=:email limit 1"
                ),
                {"email": email},
            )).scalar_one()

            kb = KnowledgeBase(tenant_id=tenant_id, name="kb")
            db.add(kb)
            await db.flush()

            doc = Document(
                tenant_id=tenant_id,
                kb_id=kb.id,
                filename="a.txt",
                storage_key="test/key",
                status="pending",
            )
            db.add(doc)
            await db.commit()
            doc_id = doc.id

        # Run task in a background thread so it can use asyncio.run internally.
        await anyio.to_thread.run_sync(lambda: parse_document.run(str(doc_id), str(tenant_id), {}))

        async with Session() as db:
            row = (
                await db.execute(
                    sa.text(
                        "select status, parse_progress, parse_message, parsed_data from documents where id=:id"
                    ),
                    {"id": doc_id},
                )
            ).mappings().one()
            assert row["status"] == "done"
            assert float(row["parse_progress"]) == 1.0
            assert row["parse_message"] == "done"
            assert row["parsed_data"]["sections"] == ["hello"]

            # Chunks should be created.
            cnt = (
                await db.execute(sa.text("select count(*) from chunks where document_id=:id"), {"id": doc_id})
            ).scalar_one()
            assert int(cnt) >= 1

        r = await client.get(
            f"/api/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == str(doc_id)
        assert body["status"] == "done"
        assert body["parse_progress"] == 1.0

        # List chunks endpoint (pagination)
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks?page=1&size=10",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        lst = r.json()
        assert lst["total"] >= 1
        assert len(lst["items"]) >= 1
        chunk_id = lst["items"][0]["id"]

        # Search within document
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks?page=1&size=10&q=hello",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        lst2 = r.json()
        assert lst2["total"] >= 1

        # Get chunk by id
        r = await client.get(
            f"/api/v1/chunks/{chunk_id}",
            headers={"Authorization": f"Bearer {access}", "X-Tenant-ID": str(tenant_id)},
        )
        assert r.status_code == 200, r.text
        one = r.json()
        assert one["document_id"] == str(doc_id)
