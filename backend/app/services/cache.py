from __future__ import annotations

import json
from typing import Any, Optional

from backend.app.core.redis_client import get_redis


class CacheService:
    async def get(self, key: str) -> Optional[Any]:
        r = get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        r = get_redis()
        raw = json.dumps(value).encode("utf-8") if not isinstance(value, (bytes, bytearray)) else bytes(value)
        await r.set(key, raw, ex=int(ttl) if ttl else None)

    async def delete(self, key: str) -> None:
        r = get_redis()
        await r.delete(key)

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete keys matching a glob-style pattern.

        Returns number of deleted keys.
        """

        r = get_redis()
        deleted = 0
        async for k in r.scan_iter(match=pattern, count=500):
            await r.delete(k)
            deleted += 1
        return deleted
