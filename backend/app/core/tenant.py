from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.core.config import settings


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_header = settings.tenant_header
        raw = request.headers.get(tenant_header)
        request.state.tenant_id = None
        if raw:
            try:
                request.state.tenant_id = uuid.UUID(raw)
            except Exception:
                # Keep None; auth layer can reject if tenant is required.
                request.state.tenant_id = None
        return await call_next(request)
