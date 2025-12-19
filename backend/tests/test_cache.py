from __future__ import annotations

import fnmatch
import os

import pytest

from backend.app.services.cache import CacheService


class FakeRedis:
    def __init__(self):
        self._data: dict[bytes, bytes] = {}

    async def get(self, key: str | bytes):
        k = key if isinstance(key, (bytes, bytearray)) else key.encode("utf-8")
        return self._data.get(bytes(k))

    async def set(self, key: str | bytes, value: bytes, ex: int | None = None):
        # TTL ignored for unit tests
        k = key if isinstance(key, (bytes, bytearray)) else key.encode("utf-8")
        self._data[bytes(k)] = bytes(value)

    async def delete(self, key: str | bytes):
        k = key if isinstance(key, (bytes, bytearray)) else key.encode("utf-8")
        self._data.pop(bytes(k), None)

    async def scan_iter(self, match: str, count: int = 500):
        for k in list(self._data.keys()):
            if fnmatch.fnmatch(k.decode("utf-8"), match):
                yield k


@pytest.mark.asyncio
async def test_cache_roundtrip_and_invalidate(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("backend.app.services.cache.get_redis", lambda: fake)

    cache = CacheService()

    await cache.set("a:1", {"x": 1}, ttl=10)
    await cache.set("a:2", {"x": 2}, ttl=10)
    await cache.set("b:1", {"y": 1}, ttl=10)

    assert await cache.get("a:1") == {"x": 1}
    assert await cache.get("missing") is None

    deleted = await cache.invalidate_pattern("a:*")
    assert deleted == 2
    assert await cache.get("a:1") is None
    assert await cache.get("b:1") == {"y": 1}


@pytest.mark.asyncio
async def test_cache_redis_integration_smoke():
    # Only run if explicit env flag is set to avoid interfering with shared Redis.
    if os.getenv("RUN_REDIS_TESTS") != "1":
        pytest.skip("Set RUN_REDIS_TESTS=1 to run Redis integration tests")

    cache = CacheService()

    await cache.set("test:a", {"v": 1}, ttl=60)
    assert await cache.get("test:a") == {"v": 1}

    await cache.set("test:b", {"v": 2}, ttl=60)
    deleted = await cache.invalidate_pattern("test:*")
    assert deleted >= 2
