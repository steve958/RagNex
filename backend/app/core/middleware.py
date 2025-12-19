from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.app.core.logging import logger


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach an X-Request-ID to every request and response."""

    def __init__(self, app, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        request.state.request_id = req_id

        # Bind request_id into structlog contextvars so all logs include it.
        import structlog

        structlog.contextvars.bind_contextvars(request_id=req_id)
        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[self.header_name] = req_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log HTTP requests in a structured way."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            status_code = getattr(locals().get("response", None), "status_code", None)
            logger.info(
                "http_request",
                method=request.method,
                path=str(request.url.path),
                status_code=status_code,
                elapsed_ms=round(elapsed_ms, 3),
            )
