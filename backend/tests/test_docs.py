"""The documentation stays in step with the code.

- Every setting the backend reads is documented in docs/configuration.md.
- Every link between the docs (and from the README) points at a file and heading that
  exist; GitHub-style heading anchors.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
DOCS = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]


def _anchors(path: Path) -> set[str]:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces to dashes."""
    out = set()
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (m := re.match(r"#+\s+(.*)", line)):
            out.add(re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-"))
    return out


def test_every_setting_is_documented():
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")))
    missing = sorted(name.upper() for name in Settings.model_fields if name.upper() not in documented)
    assert missing == [], f"add these to docs/configuration.md: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_links_between_docs_resolve(doc):
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text(encoding="utf-8")):
        if re.match(r"[a-z]+:", target):  # http(s):, mailto:
            continue
        path, _, anchor = target.partition("#")
        file = (doc.parent / path).resolve() if path else doc
        if not file.exists():
            broken.append(f"{target}: no such file")
        elif anchor and file.suffix == ".md" and anchor not in _anchors(file):
            broken.append(f"{target}: no such heading")
    assert broken == []
