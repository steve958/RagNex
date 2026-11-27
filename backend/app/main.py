from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.encryption import SecretUnavailable
from backend.app.api.router import api_router
from backend.app.api.v1.health import router as health_router
from backend.app.core.config import settings
from backend.app.core.logging import configure_logging
from backend.app.core.middleware import RequestIdMiddleware, RequestLoggingMiddleware
from backend.app.core.rate_limit import setup_rate_limiting
from backend.app.core.tenant import TenantMiddleware

logger = logging.getLogger(__name__)


def _sqlstate(exc: BaseException) -> str | None:
    """The Postgres SQLSTATE behind a SQLAlchemy error. The asyncpg driver wraps data errors
    as a generic DBAPIError, so look through the wrapped exceptions."""
    seen: BaseException | None = exc
    for _ in range(5):
        if seen is None:
            return None
        code = getattr(seen, "sqlstate", None) or getattr(seen, "pgcode", None)
        if isinstance(code, str):
            return code
        seen = getattr(seen, "orig", None) or seen.__cause__
    return None


async def _invalid_input(request: Request, exc: DBAPIError) -> JSONResponse:
    # SQLSTATE class 22 = "data exception": value too long (22001), invalid character such
    # as NUL (22021), and similar. Anything else is a real server error.
    if not (_sqlstate(exc) or "").startswith("22"):
        raise exc
    logger.warning("Database rejected input on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid input: a value is too long or contains characters that can't be stored."},
    )


async def _secret_unavailable(request: Request, exc: SecretUnavailable) -> JSONResponse:
    # A workspace's stored API key can't be decrypted (the server's encryption key changed).
    logger.error("Stored secret unreadable on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="RagNex API",
        version="0.1",
        description="Knowledge bases, documents, search and chat. Guide: docs/api.md.",
        # Under /api/ so the reference is reachable through the bundled nginx and the
        # Vite dev proxy, which forward only /api.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # Correlation + request logs first so downstream middleware/handlers inherit request_id.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    setup_rate_limiting(app)
    app.add_middleware(TenantMiddleware)

    # Added last so it is the outermost middleware and answers preflight (OPTIONS)
    # requests before auth/tenant handling sees them.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Content-Disposition"],
        )

    # Safety net: a value the database rejects (too long for its column, or containing a
    # NUL byte) is bad input, not a server error. Request models validate the common
    # cases with clearer messages; this catches anything that slips through.
    app.add_exception_handler(DBAPIError, _invalid_input)
    app.add_exception_handler(SecretUnavailable, _secret_unavailable)

    # Root-level health endpoints (per IMPLEMENTATION_TASKS.md)
    app.include_router(health_router)

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
