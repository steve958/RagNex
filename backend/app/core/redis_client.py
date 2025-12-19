from __future__ import annotations

import asyncio

import redis.asyncio as redis

from backend.app.core.config import settings


_clients_by_loop: dict[int, redis.Redis] = {}


def get_redis() -> redis.Redis:
    """Return an asyncio-redis client scoped to the current event loop."""

    loop_id = id(asyncio.get_running_loop())
    client = _clients_by_loop.get(loop_id)
    if client is None:
        client = redis.from_url(settings.redis_url, decode_responses=False)
        _clients_by_loop[loop_id] = client
    return client


async def close_redis() -> None:
    """Close redis connections for current loop (best-effort)."""

    loop_id = id(asyncio.get_running_loop())
    client = _clients_by_loop.pop(loop_id, None)
    if client is not None:
        await client.aclose()
