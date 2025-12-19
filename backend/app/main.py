from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.api.v1.health import router as health_router
from backend.app.core.logging import configure_logging
from backend.app.core.middleware import RequestIdMiddleware, RequestLoggingMiddleware
from backend.app.core.rate_limit import setup_rate_limiting
from backend.app.core.tenant import TenantMiddleware


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="RagNex API")

    # Correlation + request logs first so downstream middleware/handlers inherit request_id.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    setup_rate_limiting(app)
    app.add_middleware(TenantMiddleware)

    # Root-level health endpoints (per IMPLEMENTATION_TASKS.md)
    app.include_router(health_router)

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
