from __future__ import annotations

import uuid

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

# Fixed, not configurable: the web app and API clients send this exact header.
TENANT_HEADER = "X-Tenant-ID"


class TenantMiddleware:
    """Parse the X-Tenant-ID header into request.state.tenant_id (None if missing or not a
    UUID; the auth dependencies reject requests that need one). Plain ASGI, like
    core/middleware.py."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = Headers(scope=scope).get(TENANT_HEADER)
            tenant_id = None
            if raw:
                try:
                    tenant_id = uuid.UUID(raw)
                except ValueError:
                    pass
            scope.setdefault("state", {})["tenant_id"] = tenant_id
        await self.app(scope, receive, send)
