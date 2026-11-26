from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Fixed, not configurable: the web app and API clients send this exact header.
TENANT_HEADER = "X-Tenant-ID"


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get(TENANT_HEADER)
        request.state.tenant_id = None
        if raw:
            try:
                request.state.tenant_id = uuid.UUID(raw)
            except Exception:
                # Keep None; auth layer can reject if tenant is required.
                request.state.tenant_id = None
        return await call_next(request)
