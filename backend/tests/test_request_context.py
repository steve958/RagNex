"""Request IDs and request logs (core/middleware.py)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import structlog
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from backend.app.core import middleware
from backend.app.main import create_app


@pytest.fixture
def request_logs(monkeypatch):
    """The http_request log lines, each with the context bound when it was written."""
    lines = []

    def info(event, **kw):
        lines.append({"event": event, **structlog.contextvars.get_contextvars(), **kw})

    monkeypatch.setattr(middleware.logger, "info", info)
    return lines


@pytest.mark.asyncio
async def test_request_log_line_carries_the_request_id(request_logs):
    """The docs say each request's log lines carry its ID. The request log line didn't: it
    was written after the ID was unbound."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health", headers={"X-Request-ID": "trace-me"})
    assert r.headers["X-Request-ID"] == "trace-me"
    (line,) = [entry for entry in request_logs if entry["event"] == "http_request"]
    assert line["request_id"] == "trace-me"
    assert line["status_code"] == 200
    assert line["path"] == "/health"


@pytest.mark.asyncio
async def test_streamed_response_is_timed_and_logged_with_its_id(request_logs):
    """A streamed answer's body is part of the request: its logs carry the request ID and
    the logged time covers it. Before, both stopped when the headers were sent."""
    seen_while_streaming = []

    async def stream(request):
        async def body():
            yield b"first "
            await asyncio.sleep(0.2)
            seen_while_streaming.append(structlog.contextvars.get_contextvars().get("request_id"))
            yield b"last"

        return StreamingResponse(body())

    app = middleware.RequestContextMiddleware(Starlette(routes=[Route("/s", stream)]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/s", headers={"X-Request-ID": "stream-1"})
    assert r.text == "first last"
    assert seen_while_streaming == ["stream-1"]
    (line,) = request_logs
    assert line["request_id"] == "stream-1"
    assert line["elapsed_ms"] >= 200


@pytest.mark.asyncio
async def test_request_id_is_generated_when_missing(request_logs):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    generated = r.headers["X-Request-ID"]
    assert len(generated) == 32
    assert request_logs[-1]["request_id"] == generated


@pytest.mark.asyncio
async def test_unhandled_error_is_logged_as_500(request_logs):
    async def boom(request):
        raise RuntimeError("boom")

    app = middleware.RequestContextMiddleware(Starlette(routes=[Route("/boom", boom)]))
    with pytest.raises(RuntimeError):
        await app({"type": "http", "method": "GET", "path": "/boom", "headers": [], "query_string": b""},
                  _no_body, _discard)
    assert request_logs[-1]["status_code"] == 500


async def _no_body():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _discard(message):
    pass
