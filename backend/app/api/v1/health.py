from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import anyio
import httpx
from fastapi import APIRouter

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.core.redis_client import get_redis
from backend.app.services.storage import StorageService

router = APIRouter()


@dataclass
class ComponentStatus:
    ok: bool
    detail: str
    latency_ms: float


async def _timed(fn, timeout_s: float = 2.0) -> ComponentStatus:
    start = time.perf_counter()
    try:
        with anyio.fail_after(timeout_s):
            detail = await fn()
        ok = True
    except Exception as e:
        ok = False
        detail = f"{type(e).__name__}: {e}"
    latency_ms = (time.perf_counter() - start) * 1000.0
    return ComponentStatus(ok=ok, detail=str(detail), latency_ms=round(latency_ms, 3))


async def check_postgres() -> str:
    from sqlalchemy import text

    eng = get_engine()
    async with eng.begin() as conn:
        await conn.execute(text("select 1"))
    return "OK"


async def check_redis() -> str:
    r = get_redis()
    pong = await r.ping()
    return "PONG" if pong else "no pong"


async def check_minio() -> str:
    svc = StorageService()

    def list_sync() -> int:
        return len(svc._client.list_buckets())

    count = await anyio.to_thread.run_sync(list_sync)
    return f"buckets={count}"


async def check_opensearch() -> str:
    # OpenSearch isn't always enabled early in development. If URL is empty, treat as skipped.
    if not getattr(settings, "opensearch_url", None):
        return "SKIPPED"

    url = settings.opensearch_url.rstrip("/") + "/"
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(url)
    r.raise_for_status()
    return f"{r.status_code}"


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/health/ready")
async def health_ready() -> dict:
    components = {
        "postgres": asdict(await _timed(check_postgres)),
        "redis": asdict(await _timed(check_redis)),
        "minio": asdict(await _timed(check_minio)),
        "opensearch": asdict(await _timed(check_opensearch)),
    }

    # Treat SKIPPED components as ok.
    def comp_ok(c: dict) -> bool:
        return bool(c.get("ok")) or c.get("detail") == "SKIPPED"

    ok = all(comp_ok(c) for c in components.values())
    return {"ok": ok, "components": components}


@router.get("/health/detailed")
async def health_detailed() -> dict:
    # For now, detailed == ready, but keeping separate so we can add richer diagnostics later.
    return await health_ready()
