from __future__ import annotations


def find_codec(binary: bytes) -> str:
    """Best-effort encoding detection.

    Tries `chardet` if available; otherwise defaults to utf-8.
    """

    try:
        import chardet  # type: ignore

        res = chardet.detect(binary)
        enc = res.get("encoding")
        if enc:
            return enc
    except Exception:
        pass

    return "utf-8"
