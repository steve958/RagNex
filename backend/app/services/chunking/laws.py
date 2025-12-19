from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from pydantic import BaseModel

from deepdoc.common.token_utils import num_tokens_from_string


class LawsChunkConfig(BaseModel):
    chunk_token_num: int = 512
    delimiter: str = "\\n!?。；！？"
    layout_recognize: str = "DeepDOC"
    tree_depth: int = 2


# --- Bullet / heading detection -------------------------------------------------

_BULLET_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    # depth, regex
    (1, re.compile(r"^\s*(chapter|section|article)\s+\d+\b", re.I)),
    (1, re.compile(r"^\s*(?:[IVXLCDM]+)\.?\s+", re.I)),
    (1, re.compile(r"^\s*\d+\.?\s+")),
    (2, re.compile(r"^\s*\d+\.\d+\.?\s+")),
    (3, re.compile(r"^\s*\d+\.\d+\.\d+\.?\s+")),
    (2, re.compile(r"^\s*\(\d+\)\s+")),
    (3, re.compile(r"^\s*\([a-zA-Z]\)\s+")),
    (3, re.compile(r"^\s*[a-zA-Z]\.\s+")),
]


def bullets_category(line: str) -> int:
    """Return an estimated hierarchy depth for a bullet/heading line.

    This is intentionally heuristic; exact RAGFlow parity is deferred.
    Returns 0 if not a bullet.
    """

    if not line:
        return 0

    s = line.strip()
    for depth, pat in _BULLET_PATTERNS:
        if pat.search(s):
            return depth

    # Chinese numbered headings: "第一条" "第二章"
    if re.search(r"^\s*第[一二三四五六七八九十百千]+[章节条]\b", s):
        return 1

    return 0


def make_colon_as_title(lines: list[str]) -> list[str]:
    """Treat lines that end with ':' as titles by adding a bullet-like prefix."""

    out: list[str] = []
    for ln in lines:
        s = ln.rstrip()
        if s.endswith(":") and bullets_category(s) == 0:
            out.append(f"1. {s}")
        else:
            out.append(ln)
    return out


def remove_contents_table(lines: list[str]) -> list[str]:
    """Remove a table-of-contents block if present near the beginning.

    Heuristic:
    - if we see a TOC marker in the first 200 lines, drop lines until we hit a
      clear heading/bullet (depth>0) after that.
    """

    markers = (
        "table of contents",
        "contents",
        "目录",
    )

    lower = [l.lower() for l in lines]
    start = None
    for i, l in enumerate(lower[:200]):
        if any(m in l for m in markers):
            start = i
            break

    if start is None:
        return lines

    end = None
    for j in range(start + 1, min(len(lines), start + 500)):
        if bullets_category(lines[j]) > 0:
            end = j
            break

    if end is None:
        return lines

    return lines[:start] + lines[end:]


# --- Tree representation --------------------------------------------------------


@dataclass
class Node:
    title: str
    depth: int
    content_lines: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)

    def add_text(self, line: str) -> None:
        if line.strip():
            self.content_lines.append(line.strip())

    def add_child(self, child: "Node") -> None:
        self.children.append(child)


def _iter_lines(sections: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for sec in sections:
        if not sec:
            continue
        # keep original line boundaries
        lines.extend([l for l in str(sec).splitlines()])
    return [l for l in (l.rstrip() for l in lines) if l.strip()]


def _build_tree(lines: list[str], max_depth: int) -> Node:
    root = Node(title="ROOT", depth=0)
    stack: list[Node] = [root]

    for ln in lines:
        d = bullets_category(ln)
        if d == 0 or d > max_depth:
            stack[-1].add_text(ln)
            continue

        # new heading node
        node = Node(title=ln.strip(), depth=d)

        # pop to parent depth
        while stack and stack[-1].depth >= d:
            stack.pop()
        if not stack:
            stack = [root]
        stack[-1].add_child(node)
        stack.append(node)

    return root


def _flatten(node: Node, prefix: str = "") -> list[str]:
    """Flatten node into chunks preserving hierarchy with prefix titles."""

    chunks: list[str] = []

    cur_title = node.title if node.depth > 0 else ""
    new_prefix = prefix
    if cur_title:
        new_prefix = f"{prefix}\n{cur_title}".strip()

    body = "\n".join(node.content_lines).strip()
    if body:
        if new_prefix:
            chunks.append(f"{new_prefix}\n{body}".strip())
        else:
            chunks.append(body)

    for child in node.children:
        chunks.extend(_flatten(child, new_prefix))

    return chunks


def tree_merge(sections: list[str], depth: int = 2) -> list[str]:
    """Build a hierarchy tree and flatten it back into hierarchical text chunks."""

    lines = _iter_lines(sections)
    lines = remove_contents_table(lines)
    lines = make_colon_as_title(lines)

    tree = _build_tree(lines, max_depth=max(1, int(depth)))
    return _flatten(tree)


def docx_question_level(text: str) -> int:
    """Heuristic heading level detection from plain text.

    In ragflow this inspects DOCX styles; here we only have text, so we use bullet depth.
    """

    return bullets_category(text)


def _split_oversize_by_tokens(text: str, chunk_token_num: int) -> list[str]:
    if num_tokens_from_string(text) <= chunk_token_num:
        return [text]

    toks = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    out: list[str] = []
    cur: list[str] = []
    for tok in toks:
        cur.append(tok)
        if len(cur) >= chunk_token_num:
            out.append(" ".join(cur).strip())
            cur = []
    if cur:
        out.append(" ".join(cur).strip())
    return [o for o in out if o]


def chunk_laws_document(parsed_data: dict[str, Any], cfg: LawsChunkConfig) -> list[dict[str, Any]]:
    sections = parsed_data.get("sections") or []

    merged = tree_merge([str(s) for s in sections], depth=cfg.tree_depth)
    if not merged:
        # Fallback: treat all text as one section if hierarchy detection fails.
        merged = ["\n".join(_iter_lines([str(s) for s in sections]))]

    # Enforce token budget by splitting oversized chunks.
    out: list[dict[str, Any]] = []
    for c in merged:
        if num_tokens_from_string(c) <= cfg.chunk_token_num:
            out.append({"content": c, "token_count": num_tokens_from_string(c)})
            continue

        # fallback split by sentences/lines
        parts = re.split(r"(?<=[.!?。；！？])\s+|\n+", c)
        cur = ""
        cur_t = 0
        for p in (p.strip() for p in parts if p and p.strip()):
            # If a single part is too large, split it further.
            for piece in _split_oversize_by_tokens(p, cfg.chunk_token_num):
                t = num_tokens_from_string(piece)
                if cur and cur_t + t > cfg.chunk_token_num:
                    out.append({"content": cur.strip(), "token_count": num_tokens_from_string(cur)})
                    cur = ""
                    cur_t = 0
                cur = f"{cur}\n{piece}".strip() if cur else piece
                cur_t += t
        if cur:
            out.append({"content": cur.strip(), "token_count": num_tokens_from_string(cur)})

    # Drop any empties (defensive)
    return [c for c in out if c.get("content")]
