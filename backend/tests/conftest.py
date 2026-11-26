from __future__ import annotations

import os
import secrets
from pathlib import Path

# Tests sign tokens with their own random secret, independent of the developer's .env.
# Set before any backend module is imported (settings are read at import time); environment
# variables take precedence over the .env file.
os.environ["JWT_SECRET"] = secrets.token_hex(32)

import pytest  # noqa: E402
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


def pytest_sessionstart(session):  # pragma: no cover
    # Ensure the DB schema matches current models.
    # Tests run against a dev Postgres (per earlier phases), so we apply migrations up-front.
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_ini = backend_dir / "alembic.ini"

    cfg = Config(str(alembic_ini))
    # Make migration execution independent of current working directory.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(cfg, "head")
