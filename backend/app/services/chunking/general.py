from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from deepdoc.common.token_utils import num_tokens_from_string


class GeneralChunkConfig(BaseModel):
    chunk_token_num: int = 512
    delimiter: str = "\\n!?。；！？"
    layout_recognize: str = "DeepDOC"
    analyze_hyperlink: bool = False


def _expand_delimiter(delimiter: str) -> str:
    # Keep compatibility with DeepDoc text parsers.
    return delimiter.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")


def _split_by_delimiters(text: str, delimiter: str) -> list[str]:
    """Split text by a delimiter specification.

    Delimiter format supports inline multi-char tokens wrapped in backticks, e.g.
    "\\n!?`\n\n`".
    """

    if not text:
        return []

    delimiter = _expand_delimiter(delimiter)

    dels: list[str] = []
    s = 0
    for m in re.finditer(r"`([^`]+)`", delimiter, re.I):
        f, t = m.span()
        dels.append(m.group(1))
        dels.extend(list(delimiter[s:f]))
        s = t
    if s < len(delimiter):
        dels.extend(list(delimiter[s:]))

    dels = [d for d in dels if d]
    if not dels:
        return [text]

    pattern = "|".join(re.escape(d) for d in dels)
    parts = re.split(pattern, text)
    return [p for p in (p.strip() for p in parts) if p]


def _split_oversize_by_tokens(text: str, chunk_token_num: int) -> list[str]:
    if num_tokens_from_string(text) <= chunk_token_num:
        return [text]

    toks = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    out: list[str] = []
    cur: list[str] = []

    # IMPORTANT: join tokens with spaces so token boundaries remain visible to
    # num_tokens_from_string (otherwise long runs become a single token).
    for tok in toks:
        cur.append(tok)
        if len(cur) >= chunk_token_num:
            out.append(" ".join(cur).strip())
            cur = []
    if cur:
        out.append(" ".join(cur).strip())
    return [o for o in out if o]


def naive_merge(
    sections: list[tuple[str, str]] | list[str],
    chunk_token_num: int = 512,
    delimiter: str = "\\n!?。；！？",
) -> list[str]:
    """Merge parsed sections into chunks.

    This is a RagNex-friendly port of RAGFlow's `naive_merge` behavior.

    Input can be:
    - list of (text, style) tuples (DeepDoc-style)
    - list of plain strings

    Output is list[str] chunks.
    """

    if chunk_token_num <= 0:
        raise ValueError("chunk_token_num must be > 0")

    # Normalize to list[str]
    norm: list[str] = []
    for s in sections:
        if isinstance(s, tuple):
            norm.append(s[0] or "")
        else:
            norm.append(s or "")

    parts: list[str] = []
    for sec in norm:
        parts.extend(_split_by_delimiters(sec, delimiter=delimiter))

    # Merge parts into chunks
    chunks: list[str] = []
    cur = ""
    cur_tokens = 0

    for p in parts:
        # If a single part is too large, split it further.
        for piece in _split_oversize_by_tokens(p, chunk_token_num):
            t = num_tokens_from_string(piece)
            if cur and cur_tokens + t > chunk_token_num:
                chunks.append(cur.strip())
                cur = ""
                cur_tokens = 0

            if not cur:
                cur = piece
                cur_tokens = t
            else:
                cur = f"{cur}\n{piece}"
                cur_tokens += t

    if cur.strip():
        chunks.append(cur.strip())

    return chunks


def split_table_html(table_html: str, chunk_token_num: int = 512) -> list[str]:
    """Split a HTML table into smaller HTML tables by row count based on token budget."""

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(table_html, "html.parser")
    rows = soup.find_all("tr")
    if not rows:
        return [table_html]

    tables: list[list[Any]] = []
    cur_rows: list[Any] = []
    cur_tokens = 0

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        t = num_tokens_from_string(row_text)
        if cur_rows and cur_tokens + t > chunk_token_num:
            tables.append(cur_rows)
            cur_rows = []
            cur_tokens = 0
        cur_rows.append(row)
        cur_tokens += t

    if cur_rows:
        tables.append(cur_rows)

    out: list[str] = []
    for trs in tables:
        new_table = soup.new_tag("table")
        for tr in trs:
            new_table.append(tr)
        out.append(str(new_table))

    return out


def tokenize_chunks(chunks: list[str]) -> list[dict[str, Any]]:
    return [{"content": c, "token_count": num_tokens_from_string(c)} for c in chunks]


def chunk_parsed_document(parsed_data: dict[str, Any], cfg: GeneralChunkConfig) -> list[dict[str, Any]]:
    sections = parsed_data.get("sections") or []
    tables = parsed_data.get("tables") or []

    merged = naive_merge(sections, chunk_token_num=cfg.chunk_token_num, delimiter=cfg.delimiter)

    # Tables: include as standalone chunks; split if needed
    table_chunks: list[str] = []
    for t in tables:
        if isinstance(t, dict) and "content" in t:
            html = str(t["content"])
        else:
            html = str(t)
        table_chunks.extend(split_table_html(html, chunk_token_num=cfg.chunk_token_num))

    return tokenize_chunks(merged + table_chunks)
