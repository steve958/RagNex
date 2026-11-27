from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

# Tests sign tokens with their own random secret, independent of the developer's .env.
# Set before any backend module is imported (settings are read at import time); environment
# variables take precedence over the .env file.
os.environ["JWT_SECRET"] = secrets.token_hex(32)
# Stored API keys in the shared dev database are encrypted with this key (migration 0006
# runs at session start), so it must stay the same between runs and match the local app:
# the developer's .env key if there is one, otherwise a fixed test-only key.
if "RAGNEX_ENCRYPTION_KEY" not in os.environ:
    from dotenv import dotenv_values

    _env_file = Path(__file__).resolve().parents[2] / ".env"
    if not (dotenv_values(_env_file).get("RAGNEX_ENCRYPTION_KEY") if _env_file.exists() else None):
        os.environ["RAGNEX_ENCRYPTION_KEY"] = base64.b64encode(b"ragnex-test-encryption-key-32byt").decode()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # All test clients share one IP, so per-IP counters (e.g. 10/min on register)
    # would otherwise accumulate across tests and cause spurious 429s.
    # Imported lazily: `backend` becomes importable only after pytest_sessionstart
    # runs Alembic (whose env.py puts the repo root on sys.path).
    from backend.app.core.rate_limit import limiter

    limiter.reset()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _close_db_engine():
    # The app keeps one database engine per event loop (core/db.py), and every async test
    # runs in a new loop. Without closing it, each test leaves a pool of open connections
    # behind until the run ends, and a long run hits Postgres's connection limit
    # ("too many clients already"). Closing it here also stops a later loop that reuses the
    # same id() from being handed an engine bound to a closed loop.
    yield
    import asyncio

    from backend.app.core.db import _ENGINES_BY_LOOP

    engine = _ENGINES_BY_LOOP.pop(id(asyncio.get_running_loop()), None)
    if engine is not None:
        await engine.dispose()


def _require_stack() -> None:
    """With RAGNEX_TESTS_REQUIRE_STACK=1 (set in CI), stop at once if a data store is down.
    Locally, tests that need OpenSearch/MinIO skip when they're unreachable; in CI that
    would let the run pass without testing anything that touches them."""
    if os.environ.get("RAGNEX_TESTS_REQUIRE_STACK") != "1":
        return
    import httpx
    import redis

    from backend.app.core.config import settings

    checks = {
        "OpenSearch": lambda: httpx.get(settings.opensearch_url, timeout=5).raise_for_status(),
        "MinIO": lambda: httpx.get(
            f"{settings.s3_endpoint_url.rstrip('/')}/minio/health/live", timeout=5
        ).raise_for_status(),
        "Redis": lambda: redis.Redis.from_url(settings.redis_url, socket_timeout=5).ping(),
    }
    down = []
    for name, check in checks.items():
        try:
            check()
        except Exception as e:  # noqa: BLE001 - any failure means it's unusable
            down.append(f"{name} ({type(e).__name__})")
    if down:
        pytest.exit(f"RAGNEX_TESTS_REQUIRE_STACK=1 but unreachable: {', '.join(down)}", returncode=1)


def pytest_sessionstart(session):  # pragma: no cover
    # Ensure the DB schema matches current models.
    # Tests run against a dev Postgres (per earlier phases), so we apply migrations up-front.
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_ini = backend_dir / "alembic.ini"

    cfg = Config(str(alembic_ini))
    # Make migration execution independent of current working directory.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(cfg, "head")
    _require_stack()
