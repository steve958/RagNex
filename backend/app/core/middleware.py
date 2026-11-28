from __future__ import annotations

import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.logging import logger

# The middlewares here are plain ASGI rather than Starlette's BaseHTTPMiddleware. That one
# returns from call_next as soon as the response headers are ready, so a streamed answer's
# body ran after the request's log line was written and its request ID unbound; it also
# cost about a tenth of the API's CPU under load (docs/performance.md).


class RequestContextMiddleware:
    """Give every request an ID and log it when it's finished.

    The ID comes from the X-Request-ID request header, or is generated. It is returned in the
    response header and bound to every log line written while the request runs, including
    the "http_request" line itself and anything logged while a response streams.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID"):
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        req_id = Headers(scope=scope).get(self.header_name) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = req_id
        status_code: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[self.header_name] = req_id
            await send(message)

        start = time.perf_counter()
        structlog.contextvars.bind_contextvars(request_id=req_id)
        try:
            await self.app(scope, receive, send_with_id)
        except BaseException:
            # Unhandled: the outermost error handler answers 500 after this.
            status_code = status_code or 500
            raise
        finally:
            logger.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                # Until the last byte of the response, streamed answers included.
                elapsed_ms=round((time.perf_counter() - start) * 1000.0, 3),
            )
            structlog.contextvars.clear_contextvars()
