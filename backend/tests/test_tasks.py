from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.core.deps import get_current_user
from backend.app.main import create_app
from backend.app.models.user import User


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


@pytest.mark.asyncio
async def test_task_status_success(monkeypatch):
    app = create_app()

    dummy_user = User(id=uuid.uuid4(), email="x@example.com", password_hash="")
    app.dependency_overrides[get_current_user] = lambda: dummy_user

    def fake_async_result(task_id: str):
        return DummyResult(state="SUCCESS", result={"ok": True})

    monkeypatch.setattr("backend.app.api.v1.tasks.celery_app.AsyncResult", fake_async_result)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/tasks/abc")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "abc"
        assert body["state"] == "SUCCESS"
        assert body["ready"] is True
        assert body["successful"] is True
        assert body["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_task_status_failure_includes_traceback(monkeypatch):
    app = create_app()

    dummy_user = User(id=uuid.uuid4(), email="x@example.com", password_hash="")
    app.dependency_overrides[get_current_user] = lambda: dummy_user

    def fake_async_result(task_id: str):
        return DummyResult(state="FAILURE", result=ValueError("boom"), tb="trace")

    monkeypatch.setattr("backend.app.api.v1.tasks.celery_app.AsyncResult", fake_async_result)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/tasks/boom")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "FAILURE"
        assert body["ready"] is True
        assert body["successful"] is False
        assert body["traceback"] == "trace"
