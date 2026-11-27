from __future__ import annotations

import os
import secrets
from pathlib import Path

# Tests sign tokens with their own random secret, independent of the developer's .env.
# Set before any backend module is imported (settings are read at import time); environment
# variables take precedence over the .env file.
os.environ["JWT_SECRET"] = secrets.token_hex(32)

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


def pytest_sessionstart(session):  # pragma: no cover
    # Ensure the DB schema matches current models.
    # Tests run against a dev Postgres (per earlier phases), so we apply migrations up-front.
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_ini = backend_dir / "alembic.ini"

    cfg = Config(str(alembic_ini))
    # Make migration execution independent of current working directory.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(cfg, "head")
