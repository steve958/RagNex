from __future__ import annotations

import re


def tokenize(text: str) -> str:
    """Return a whitespace-separated token string (ragflow-compatible shape)."""

    if not text:
        return ""
    # Fall back to a simple split that works for latin + digits; keep unicode letters.
    try:
        tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    except Exception:
        tokens = text.split()
    return " ".join(tokens)


def tag(token: str) -> str:
    """Very small POS tagger stub.

    Ragflow uses this primarily to detect `nr` (person name) in some heuristics.
    We return "" by default.
    """

    return ""


def is_chinese(ch: str) -> bool:
    if not ch:
        return False
    return "\u4e00" <= ch <= "\u9fff"
