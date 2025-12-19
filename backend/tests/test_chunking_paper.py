from __future__ import annotations

from backend.app.services.chunking.paper import PaperChunkConfig, chunk_paper_document
from deepdoc.common.token_utils import num_tokens_from_string


def test_paper_extracts_title_authors_abstract():
    parsed = {
        "filename": "paper.pdf",
        "ext": ".pdf",
        "sections": [
            "A Great Paper Title\nJohn Doe, Jane Doe\nAbstract: This is the abstract text. It continues.\n1 Introduction\nIntro text here.",
        ],
        "tables": [],
    }

    out = chunk_paper_document(parsed, PaperChunkConfig(chunk_token_num=100))
    assert out["title"] == "A Great Paper Title"
    assert "John Doe" in (out["authors"] or "")
    assert out["abstract"] is not None and "abstract text" in out["abstract"].lower()

    abs_chunks = [c for c in out["chunks"] if c["kind"] == "abstract"]
    assert len(abs_chunks) == 1


def test_paper_body_chunks_respect_budget():
    parsed = {
        "filename": "paper.pdf",
        "ext": ".pdf",
        "sections": [
            "Title\nAuthor\nAbstract: Short.\n1 Introduction\n" + ("x " * 300),
        ],
        "tables": [],
    }

    cfg = PaperChunkConfig(chunk_token_num=50)
    out = chunk_paper_document(parsed, cfg)

    for ch in out["chunks"]:
        if ch["kind"] == "body":
            assert num_tokens_from_string(ch["content"]) <= 50
