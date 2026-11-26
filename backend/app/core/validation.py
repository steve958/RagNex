"""Shared input rules for request models.

Text from clients must not contain NUL bytes (Postgres rejects them, which used to surface
as a 500) or other control characters, and must fit the column it is stored in.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

# C0 controls except tab, newline and carriage return (allowed in longer text), plus DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Bidirectional overrides/isolates and zero-width marks: they can make a name display as
# something else (e.g. "invoice‮fdp.exe" shows as "invoiceexe.pdf").
_INVISIBLE_FORMATTING = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")


def _no_control_chars(value: str) -> str:
    if _CONTROL_CHARS.search(value):
        raise ValueError("must not contain control characters")
    return value


def _single_line(value: str) -> str:
    if "\n" in value or "\r" in value or "\t" in value:
        raise ValueError("must be a single line")
    if _INVISIBLE_FORMATTING.search(value):
        raise ValueError("must not contain invisible formatting characters")
    return value


def Name(max_length: int = 255):  # noqa: N802 - reads like a type
    """A short, single-line, non-empty label (trimmed)."""
    return Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length),
        AfterValidator(_no_control_chars),
        AfterValidator(_single_line),
    ]


def Text(max_length: int):  # noqa: N802
    """Free text (multi-line allowed) without NUL or other control characters."""
    return Annotated[str, StringConstraints(max_length=max_length), AfterValidator(_no_control_chars)]


# Passwords: argon2 input is capped by passlib at 4096 bytes; a generous but bounded limit.
NewPassword = Annotated[str, StringConstraints(min_length=8, max_length=1024)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


def safe_filename(name: str, *, max_length: int = 255) -> str:
    """A display- and storage-safe version of a client-supplied filename.

    Keeps only the final path component (for both / and \\ separators), removes control
    and invisible formatting characters, normalises Unicode, and shortens the stem so the
    whole name fits max_length while keeping the extension.
    """
    name = unicodedata.normalize("NFC", name or "")
    name = _INVISIBLE_FORMATTING.sub("", _CONTROL_CHARS.sub("", name)).replace("\n", "").replace("\r", "")
    name = re.split(r"[\\/]", name)[-1].strip().strip(".")  # last component, no leading/trailing dots
    stem, ext = os.path.splitext(name)
    stem = stem.strip() or "upload"
    ext = ext[:16]
    return stem[: max(1, max_length - len(ext))] + ext
