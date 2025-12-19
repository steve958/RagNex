from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def num_tokens_from_string(text: str) -> int:
    """Heuristic token count.

    DeepDoc uses token counts primarily for chunk sizing. For RagNex we keep this
    dependency-free and deterministic.
    """

    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))
