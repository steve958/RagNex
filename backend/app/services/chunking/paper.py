from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from deepdoc.common.token_utils import num_tokens_from_string

from backend.app.services.chunking.general import naive_merge


class PaperChunkConfig(BaseModel):
    chunk_token_num: int = 512
    layout_recognize: str = "DeepDOC"


_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*)\s+\S+|^(abstract|introduction|related work|method|methods|experiments|results|discussion|conclusion|references)\b",
    re.I,
)


def _clean_line(line: str) -> str:
    # Undo common PDF line-break artifacts.
    s = line.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _lines_from_sections(sections: list[str]) -> list[str]:
    lines: list[str] = []
    for sec in sections:
        if not sec:
            continue
        lines.extend(sec.splitlines())
    # Keep non-empty, cleaned.
    return [l for l in (_clean_line(l) for l in lines) if l]


def _extract_title_and_authors(lines: list[str]) -> tuple[str | None, str | None, int]:
    """Return (title, authors, idx_after_header)."""

    if not lines:
        return None, None, 0

    # Title: first reasonably long line.
    title_idx = None
    for i, ln in enumerate(lines[:40]):
        if len(ln) >= 8 and not ln.lower().startswith("arxiv"):
            title_idx = i
            break

    if title_idx is None:
        return None, None, 0

    title = lines[title_idx]

    # Authors: take next 1-3 lines until we hit Abstract/heading.
    author_lines: list[str] = []
    for ln in lines[title_idx + 1 : title_idx + 6]:
        if _HEADING_RE.match(ln):
            break
        # skip affiliations/keywords noise lightly
        if any(k in ln.lower() for k in ["university", "department", "@", "keywords", "doi"]):
            continue
        if len(ln) < 3:
            continue
        author_lines.append(ln)

    authors = " ".join(author_lines).strip() or None
    return title, authors, title_idx + 1


def _extract_abstract(lines: list[str]) -> tuple[str | None, int]:
    """Return (abstract_text, end_index_exclusive)."""

    start = None
    for i, ln in enumerate(lines[:200]):
        if ln.lower().startswith("abstract"):
            start = i
            break

    if start is None:
        return None, 0

    # Remove "Abstract" label.
    first = re.sub(r"^abstract\s*[:\-]?\s*", "", lines[start], flags=re.I).strip()
    out_lines = [first] if first else []

    end = None
    for j in range(start + 1, min(len(lines), start + 200)):
        if _HEADING_RE.match(lines[j]) and not lines[j].lower().startswith("abstract"):
            end = j
            break
        out_lines.append(lines[j])

    if end is None:
        end = min(len(lines), start + 200)

    abstract = " ".join(out_lines).strip() or None
    return abstract, end


def _split_sections_by_headings(lines: list[str], start_idx: int) -> list[tuple[str, str]]:
    """Return list of (heading, body) pairs."""

    cur_title = ""
    cur_lines: list[str] = []
    out: list[tuple[str, str]] = []

    def flush():
        nonlocal cur_title, cur_lines
        body = " ".join(cur_lines).strip()
        if body:
            out.append((cur_title, body))
        cur_title = ""
        cur_lines = []

    for ln in lines[start_idx:]:
        if _HEADING_RE.match(ln):
            flush()
            cur_title = ln
            continue
        cur_lines.append(ln)

    flush()

    # If we never found headings, treat all as one section.
    if not out and lines[start_idx:]:
        out = [("", " ".join(lines[start_idx:]).strip())]
    return out


def chunk_paper_document(parsed_data: dict[str, Any], cfg: PaperChunkConfig) -> dict[str, Any]:
    """Build paper chunks.

    Returns JSON-serializable payload:
      {
        title: str|None,
        authors: str|None,
        abstract: str|None,
        sections: list[{title, content}],
        chunks: list[{content, token_count, kind}]
      }

    abstract is returned as a single chunk (per acceptance criteria).
    """

    sections_in = parsed_data.get("sections") or []
    lines = _lines_from_sections([str(s) for s in sections_in])

    title, authors, _ = _extract_title_and_authors(lines)
    abstract, abs_end = _extract_abstract(lines)

    start_idx = abs_end if abs_end else 0
    section_pairs = _split_sections_by_headings(lines, start_idx=start_idx)

    # Convert to DeepDoc-style (text, style) tuples for naive_merge.
    merge_input: list[tuple[str, str]] = []
    structured_sections: list[dict[str, str]] = []
    for heading, body in section_pairs:
        label = heading.strip()
        if label:
            merge_input.append((label, ""))
        merge_input.append((body, ""))
        structured_sections.append({"title": label, "content": body})

    body_chunks = naive_merge(merge_input, chunk_token_num=cfg.chunk_token_num, delimiter="\n")

    chunks: list[dict[str, Any]] = []
    if abstract:
        chunks.append({"kind": "abstract", "content": abstract, "token_count": num_tokens_from_string(abstract)})

    for c in body_chunks:
        chunks.append({"kind": "body", "content": c, "token_count": num_tokens_from_string(c)})

    # Final safety: enforce chunk size on body chunks.
    fixed: list[dict[str, Any]] = []
    for ch in chunks:
        if ch["token_count"] <= cfg.chunk_token_num or ch["kind"] == "abstract":
            fixed.append(ch)
            continue
        # split body chunk naively
        parts = re.split(r"(?<=[.!?。；！？])\s+|\n+", ch["content"])
        cur = ""
        for p in (p.strip() for p in parts if p and p.strip()):
            if not cur:
                cur = p
                continue
            if num_tokens_from_string(cur + " " + p) > cfg.chunk_token_num:
                fixed.append({"kind": "body", "content": cur, "token_count": num_tokens_from_string(cur)})
                cur = p
            else:
                cur = cur + " " + p
        if cur:
            fixed.append({"kind": "body", "content": cur, "token_count": num_tokens_from_string(cur)})

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "sections": structured_sections,
        "chunks": fixed,
    }
