from __future__ import annotations

from backend.app.services.chunking.laws import (
    LawsChunkConfig,
    bullets_category,
    chunk_laws_document,
    make_colon_as_title,
    remove_contents_table,
    tree_merge,
)
from deepdoc.common.token_utils import num_tokens_from_string


def test_bullets_category_basic():
    assert bullets_category("1. Scope") == 1
    assert bullets_category("1.1 Definitions") >= 2
    assert bullets_category("(1) Item") >= 2
    assert bullets_category("Appendix") == 0


def test_remove_contents_table_drops_toc_block():
    lines = [
        "TABLE OF CONTENTS",
        "1. Something .... 1",
        "2. Something .... 2",
        "",
        "1. Scope",
        "Text",
    ]
    out = remove_contents_table(lines)
    assert out[0].startswith("1.")
    assert "TABLE OF CONTENTS" not in "\n".join(out)


def test_make_colon_as_title():
    lines = ["Definitions:", "This section defines terms."]
    out = make_colon_as_title(lines)
    assert out[0].startswith("1.")


def test_tree_merge_hierarchy_includes_titles():
    sections = [
        "1. Scope\nThis is scope.",
        "1.1 Definitions\nA means B.",
        "2. Enforcement\nDo the thing.",
    ]
    chunks = tree_merge(sections, depth=2)
    assert any("1. Scope" in c for c in chunks)
    assert any("1.1 Definitions" in c for c in chunks)


def test_chunk_laws_document_respects_token_budget():
    parsed = {
        "filename": "law.txt",
        "ext": ".txt",
        "sections": ["1. Title\n" + ("x " * 200)],
        "tables": [],
    }
    cfg = LawsChunkConfig(chunk_token_num=50, tree_depth=1)
    chunks = chunk_laws_document(parsed, cfg)
    assert chunks
    assert all(num_tokens_from_string(c["content"]) <= 50 for c in chunks)
