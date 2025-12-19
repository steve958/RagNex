from __future__ import annotations

import os
from typing import Any


def parse_document_binary(filename: str, binary: bytes, parser_config: dict | None = None) -> dict[str, Any]:
    """Parse a document binary into normalized sections/tables.

    Returns a JSON-serializable dict:
      {
        "filename": str,
        "ext": str,
        "sections": list[str],
        "tables": list,
      }

    Note: this is *not* chunking. It just extracts/normalizes text and any table-like
    artifacts so Phase P2-3/P2-6 can build on it.
    """

    cfg = parser_config or {}
    ext = os.path.splitext(filename)[1].lower()

    sections: list[str] = []
    tables: list[Any] = []

    from deepdoc import parser as deepdoc_parser

    if ext == ".pdf":
        use_ocr = bool(cfg.get("use_ocr", False))
        from_page = int(cfg.get("from_page", 0))
        to_page = int(cfg.get("to_page", 100000))
        p = deepdoc_parser.PdfParser(use_ocr=use_ocr)
        sec_pairs, tables = p(binary, from_page=from_page, to_page=to_page)
        sections = [t for (t, _style) in sec_pairs]

    elif ext in {".txt"}:
        if deepdoc_parser.TxtParser is None:
            raise RuntimeError("TxtParser not available")
        chunk_token_num = int(cfg.get("chunk_token_num", 512))
        delimiter = str(cfg.get("delimiter", "\\n!?;。；！？"))
        pairs = deepdoc_parser.TxtParser()(None, binary=binary, chunk_token_num=chunk_token_num, delimiter=delimiter)
        sections = [p[0] for p in pairs]

    elif ext in {".md", ".markdown"}:
        if deepdoc_parser.MarkdownParser is None:
            raise RuntimeError("MarkdownParser not available")
        delimiter = str(cfg.get("delimiter", "\\n!?;。；！？"))
        sec_pairs, tables = deepdoc_parser.MarkdownParser()(None, binary=binary, delimiter=delimiter)
        sections = [t for (t, _style) in sec_pairs]

    elif ext in {".html", ".htm"}:
        if deepdoc_parser.HtmlParser is None:
            raise RuntimeError("HtmlParser not available")
        chunk_token_num = int(cfg.get("chunk_token_num", 512))
        # HtmlParser returns (sections: list[str], table_list)
        sections, tables = deepdoc_parser.HtmlParser()(None, binary=binary, chunk_token_num=chunk_token_num)

    elif ext in {".json", ".jsonl"}:
        if deepdoc_parser.JsonParser is None:
            raise RuntimeError("JsonParser not available")
        parts = deepdoc_parser.JsonParser()(None, binary=binary)
        sections = list(parts)

    elif ext in {".docx"}:
        if deepdoc_parser.DocxParser is None:
            raise RuntimeError("DocxParser not available")
        # DocxParser returns a list of (text, style) tuples.
        sec_pairs = deepdoc_parser.DocxParser()(None, binary=binary)
        sections = [t for (t, _style) in sec_pairs]

    elif ext in {".xlsx"}:
        if deepdoc_parser.ExcelParser is None:
            raise RuntimeError("ExcelParser not available")
        sec_pairs = deepdoc_parser.ExcelParser()(None, binary=binary)
        sections = [t for (t, _style) in sec_pairs]

    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Normalize: drop empties and ensure JSON-friendly
    sections = [s for s in (s.strip() for s in sections) if s]

    return {
        "filename": filename,
        "ext": ext,
        "sections": sections,
        "tables": tables,
    }
