from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def pytest_sessionstart(session):  # pragma: no cover
    # Ensure the DB schema matches current models.
    # Tests run against a dev Postgres (per earlier phases), so we apply migrations up-front.
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_ini = backend_dir / "alembic.ini"

    cfg = Config(str(alembic_ini))
    # Make migration execution independent of current working directory.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(cfg, "head")
