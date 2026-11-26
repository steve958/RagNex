from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.core.deps import require_tenant_membership
from backend.app.main import create_app
from backend.app.models.user import User

TENANT = uuid.uuid4()


class DummyResult:
    def __init__(self, state: str, result=None, tb: str | None = None):
        self.state = state
        self.result = result
        self.traceback = tb

    def ready(self) -> bool:
        return self.state in {"SUCCESS", "FAILURE"}

    def successful(self) -> bool:
        return self.state == "SUCCESS"

    def failed(self) -> bool:
        return self.state == "FAILURE"


async def _get(monkeypatch, result: DummyResult) -> httpx.Response:
    app = create_app()
    user = User(id=uuid.uuid4(), email="x@example.com", password_hash="")
    app.dependency_overrides[require_tenant_membership] = lambda: (TENANT, user)
    monkeypatch.setattr("backend.app.api.v1.tasks.celery_app.AsyncResult", lambda task_id: result)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/tasks/abc")


@pytest.mark.asyncio
async def test_own_tenants_task_result_is_returned(monkeypatch):
    r = await _get(monkeypatch, DummyResult("SUCCESS", {"tenant_id": str(TENANT), "status": "done"}))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["id"], body["state"], body["ready"], body["successful"]) == ("abc", "SUCCESS", True, True)
    assert body["result"] == {"tenant_id": str(TENANT), "status": "done"}


@pytest.mark.asyncio
async def test_other_tenants_task_is_not_found(monkeypatch):
    r = await _get(monkeypatch, DummyResult("SUCCESS", {"tenant_id": str(uuid.uuid4()), "status": "done"}))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_failed_task_reveals_no_traceback(monkeypatch):
    r = await _get(monkeypatch, DummyResult("FAILURE", ValueError("boom at /app/secret/path"), tb="Traceback ..."))
    assert r.status_code == 404
    assert "Traceback" not in r.text and "secret" not in r.text


@pytest.mark.asyncio
async def test_pending_task_shows_only_its_state(monkeypatch):
    r = await _get(monkeypatch, DummyResult("PENDING"))
    assert r.status_code == 200
    assert r.json() == {"id": "abc", "state": "PENDING", "ready": False, "successful": False, "result": None}
