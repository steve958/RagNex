"""The examples in docs/api.md, run against the real API (dev stack, fake models).

If one of these fails, the guide is wrong or the API changed: update whichever is out of date.
"""

from __future__ import annotations

import json
import uuid

import pytest

from test_deletion import SOLAR_DOC, Api, _with_api, pipeline  # noqa: F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.mark.asyncio
async def test_signing_in_and_choosing_the_workspace(pipeline):
    async def scenario(api: Api):
        email = f"guide_{uuid.uuid4().hex}@example.com"
        await api.client.post("/api/v1/auth/register", json={"email": email, "password": "test-password-1"})

        r = await api.client.post("/api/v1/auth/login", json={"email": email, "password": "test-password-1"})
        tokens = r.json()
        assert set(tokens) == {"access_token", "refresh_token", "token_type"} and tokens["token_type"] == "bearer"
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}

        workspaces = (await api.client.get("/api/v1/tenants", headers=bearer)).json()
        assert set(workspaces[0]) == {"id", "name", "role"} and workspaces[0]["name"] == f"{email}'s tenant"
        assert workspaces[0]["role"] == "owner"

        r = await api.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200 and "access_token" in r.json()
        assert (await api.client.get("/api/v1/auth/me", headers=bearer)).json()["email"] == email

        # Workspace-scoped requests need X-Tenant-ID.
        r = await api.client.get("/api/v1/knowledgebases", headers=bearer)
        assert r.status_code == 400 and "X-Tenant-ID" in r.json()["detail"]

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_documented_workflow(pipeline):
    async def scenario(api: Api):
        h = api.headers

        # Knowledge bases
        r = await api.client.post(
            "/api/v1/knowledgebases", headers=h,
            json={"name": "Policies", "description": "HR policies", "template": "laws"},
        )
        kb = r.json()
        assert set(kb) == {"id", "name", "description", "template"} and kb["template"] == "laws"
        r = await api.client.put(f"/api/v1/knowledgebases/{kb['id']}", headers=h, json={"name": "HR policies"})
        assert r.json()["name"] == "HR policies" and r.json()["description"] == "HR policies"

        # Uploading, with a page range as query parameters
        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb['id']}/documents?from_page=0&to_page=20", headers=h,
            files={"file": ("handbook.md", SOLAR_DOC, "text/markdown")},
        )
        upload = r.json()
        assert set(upload) == {"id", "kb_id", "filename", "status", "task_id"} and upload["status"] == "pending"
        doc = upload["id"]

        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb['id']}/documents", headers=h, files={"file": ("old.doc", b"x", "application/msword")}
        )
        assert r.status_code == 400 and "Supported" in r.json()["detail"]

        # Reprocessing while it's still being processed: 409
        assert (await api.client.post(f"/api/v1/documents/{doc}/reprocess", headers=h)).status_code == 409

        # Waiting until it's ready
        await pipeline.drain()
        status = (await api.client.get(f"/api/v1/documents/{doc}", headers=h)).json()
        assert status["status"] == "indexed" and status["error_message"] is None
        assert {"parse_progress", "index_progress"} <= set(status)

        # Other document requests
        listed = (await api.client.get(f"/api/v1/knowledgebases/{kb['id']}/documents", headers=h)).json()
        assert [d["id"] for d in listed["items"]] == [doc]
        chunks = (await api.client.get(f"/api/v1/documents/{doc}/chunks?q=solar&page=1&size=20", headers=h)).json()
        assert chunks["items"] and chunks["page"] == 1
        one = (await api.client.get(f"/api/v1/chunks/{chunks['items'][0]['id']}", headers=h)).json()
        assert one["document_id"] == doc
        r = await api.client.post(f"/api/v1/knowledgebases/{kb['id']}/documents/reprocess-failed", headers=h)
        assert r.json() == {"queued": [], "skipped": []}

        # Search
        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb['id']}/search", headers=h, json={"query": "solar panels", "top_k": 5}
        )
        hits = r.json()["hits"]
        assert hits and set(hits[0]) == {"chunk_id", "doc_id", "content", "score"} and len(hits) <= 5

        # Chat
        r = await api.client.post(
            "/api/v1/chat/sessions", headers=h,
            json={"kb_ids": [kb["id"]], "name": "HR questions", "system_prompt": "Answer briefly."},
        )
        session = r.json()
        assert session["name"] == "HR questions" and session["system_prompt"] == "Answer briefly."
        sid = session["id"]

        r = await api.client.post(f"/api/v1/chat/sessions/{sid}/messages", headers=h, json={"content": "solar panels?"})
        answer = r.json()
        assert answer["role"] == "assistant" and answer["content"]
        assert set(answer["citations"][0]) == {"chunk_id", "doc_id", "kb_id", "score"}

        r = await api.client.post(
            f"/api/v1/chat/sessions/{sid}/messages/stream", headers=h, json={"content": "And for part-time staff?"}
        )
        events = _events(r.text)
        names = [e for e, _ in events]
        assert names[0] == "meta" and names[-1] == "done" and set(names[1:-1]) == {"delta"}
        meta, done = events[0][1], events[-1][1]
        assert meta["user_message"]["content"] == "And for part-time staff?" and "citations" in meta
        assert done["role"] == "assistant"
        assert done["content"] == "".join(d["text"] for e, d in events if e == "delta")

        r = await api.client.post(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages/stream", headers=h, json={"content": "x"})
        assert r.status_code == 404  # an ordinary HTTP error, not an event

        history = (await api.client.get(f"/api/v1/chat/sessions/{sid}/messages?latest=true&limit=2", headers=h)).json()
        assert [m["role"] for m in history["items"]] == ["user", "assistant"]
        assert history["items"][1]["content"] == done["content"]
        assert [s["id"] for s in (await api.client.get("/api/v1/chat/sessions", headers=h)).json()] == [sid]

        # Download, then delete
        assert (await api.client.get(f"/api/v1/documents/{doc}/file", headers=h)).content == SOLAR_DOC
        assert (await api.client.delete(f"/api/v1/documents/{doc}", headers=h)).status_code == 200

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_api_key_access_as_documented(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        r = await api.client.post("/api/v1/api-keys", headers=api.headers, json={"name": "nightly-sync", "scopes": ["read"]})
        created = r.json()
        assert set(created) == {"id", "api_key"} and created["api_key"].startswith("rk_")
        listed = (await api.client.get("/api/v1/api-keys", headers=api.headers)).json()
        assert created["api_key"] not in json.dumps(listed)

        read = {"X-API-Key": created["api_key"], "X-Tenant-ID": str(api.tenant_id)}
        assert (await api.client.get("/api/v1/knowledgebases", headers=read)).status_code == 200
        # Search is a POST but only reads, so a read key may use it.
        r = await api.client.post(f"/api/v1/knowledgebases/{kb}/search", headers=read, json={"query": "x"})
        assert r.status_code == 200
        r = await api.client.post("/api/v1/knowledgebases", headers=read, json={"name": "nope"})
        assert r.status_code == 403
        # Accounts need a signed-in user.
        r = await api.client.get("/api/v1/api-keys", headers=read)
        assert r.status_code == 403 and "API keys can't use it" in r.json()["detail"]
        # A key only works in its own workspace.
        r = await api.client.get("/api/v1/knowledgebases", headers={**read, "X-Tenant-ID": str(uuid.uuid4())})
        assert r.status_code == 403

        r = await api.client.post("/api/v1/api-keys/revoke", headers=api.headers, json={"id": created["id"]})
        assert r.status_code == 200
        assert (await api.client.get("/api/v1/knowledgebases", headers=read)).status_code == 401

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_documented_error_format(pipeline):
    async def scenario(api: Api):
        r = await api.client.post("/api/v1/knowledgebases", headers=api.headers, json={"name": ""})
        assert r.status_code == 422
        problem = r.json()["detail"][0]
        assert "name" in problem["loc"] and problem["msg"]

        r = await api.client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=api.headers)
        assert r.status_code == 404 and r.json() == {"detail": "Document not found"}

    await _with_api(scenario)
