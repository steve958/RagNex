from __future__ import annotations

import pytest

from backend.app.services.chunking.general import GeneralChunkConfig, chunk_parsed_document, naive_merge
from deepdoc.common.token_utils import num_tokens_from_string


def test_naive_merge_respects_token_budget():
    # 30 tokens of 'a' and 30 tokens of 'b' with budget 50 should yield 2 chunks.
    sections = ["a " * 30, "b " * 30]
    chunks = naive_merge(sections, chunk_token_num=50, delimiter="\\n")
    assert len(chunks) == 2
    assert all(num_tokens_from_string(c) <= 50 for c in chunks)


def test_naive_merge_splits_oversize_piece():
    sections = ["x " * 120]
    chunks = naive_merge(sections, chunk_token_num=50, delimiter="\\n")
    assert len(chunks) >= 3
    assert all(num_tokens_from_string(c) <= 50 for c in chunks)


def test_chunk_parsed_document_includes_tables():
    parsed = {
        "filename": "a.html",
        "ext": ".html",
        "sections": ["hello world"],
        "tables": [
            "<table><tr><td>r1</td></tr><tr><td>r2</td></tr></table>",
        ],
    }

    cfg = GeneralChunkConfig(chunk_token_num=10)
    chunks = chunk_parsed_document(parsed, cfg)

    # One chunk from sections and at least one from table.
    assert any("hello" in c["content"] for c in chunks)
    assert any("<table" in c["content"] for c in chunks)


@pytest.mark.parametrize(
    "delimiter",
    [
        "\\n!?。；！？",
        "`\\n\\n`",  # multi-char delimiter in backticks
    ],
)
def test_delimiter_formats_do_not_crash(delimiter: str):
    chunks = naive_merge(["a\\n\\n b"], chunk_token_num=50, delimiter=delimiter)
    assert chunks
