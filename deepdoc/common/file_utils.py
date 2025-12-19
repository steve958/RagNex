from __future__ import annotations

from pathlib import Path
from typing import Iterable


def get_project_base_directory() -> str:
    """Return a stable base directory for locating DeepDoc resources.

    We default to the repository root (parent of the `deepdoc/` package).
    """

    return str(Path(__file__).resolve().parents[2])


def traversal_files(root: str | Path) -> Iterable[str]:
    """Yield all file paths under `root` (recursive)."""

    root_path = Path(root)
    for p in root_path.rglob("*"):
        if p.is_file():
            yield str(p)
