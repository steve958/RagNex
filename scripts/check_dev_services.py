from __future__ import annotations

import asyncio
import json
import os

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


def env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v else default


DB_URL = env("DATABASE_URL", "postgresql+asyncpg://ragnex:ragnex@localhost:5432/ragnex")
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
OPENSEARCH_URL = env("OPENSEARCH_URL", "http://localhost:9200")
MINIO_URL = env("S3_ENDPOINT_URL", "http://localhost:9000")


async def check_postgres() -> tuple[bool, str]:
    eng = create_async_engine(DB_URL, pool_pre_ping=True)
    try:
        async with eng.connect() as c:
            await c.execute(sa.text("select 1"))
        return True, "OK"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        await eng.dispose()


async def check_redis() -> tuple[bool, str]:
    try:
        import redis

        r = redis.Redis.from_url(REDIS_URL)
        pong = r.ping()
        return bool(pong), "PONG" if pong else "no pong"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def check_http(url: str, path: str = "/") -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url.rstrip("/") + path)
        ct = resp.headers.get("content-type", "")
        ok = resp.status_code < 400
        return ok, f"{resp.status_code} {ct}".strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def main() -> None:
    results = {
        "postgres": await check_postgres(),
        "redis": await check_redis(),
        "opensearch": await check_http(OPENSEARCH_URL, "/"),
        "minio": await check_http(MINIO_URL, "/"),
    }

    print(json.dumps({k: {"ok": ok, "detail": detail} for k, (ok, detail) in results.items()}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
