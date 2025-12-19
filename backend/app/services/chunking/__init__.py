from __future__ import annotations

from backend.app.services.chunking.general import GeneralChunkConfig, chunk_parsed_document, naive_merge
from backend.app.services.chunking.laws import LawsChunkConfig, chunk_laws_document, tree_merge
from backend.app.services.chunking.paper import PaperChunkConfig, chunk_paper_document

__all__ = [
    "GeneralChunkConfig",
    "chunk_parsed_document",
    "naive_merge",
    "LawsChunkConfig",
    "chunk_laws_document",
    "tree_merge",
    "PaperChunkConfig",
    "chunk_paper_document",
]
