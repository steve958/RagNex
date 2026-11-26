from __future__ import annotations

import os
from typing import Any

# Every extension parse_document_binary can handle. Uploads accept exactly these (see
# api/v1/documents.py and services/storage.py), so a file is never accepted only to fail
# in parsing. Legacy binary Office formats (.doc, .ppt, .xls) have no parser.
SUPPORTED_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".json", ".jsonl", ".docx", ".xlsx", ".csv", ".pptx"}
)


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
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext or '(no extension)'}")
    if not binary or not binary.strip():
        # Parsers fail on empty input in confusing ways (e.g. trying to open a file path).
        raise ValueError("The file is empty")

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
        # Returns ([(paragraph text, style), ...], [table, ...]); takes the bytes positionally.
        sec_pairs, docx_tables = deepdoc_parser.DocxParser()(binary)
        sections = [t for (t, _style) in sec_pairs]
        for table in docx_tables:
            text = "\n".join(map(str, table)) if isinstance(table, (list, tuple)) else str(table)
            if text.strip():
                tables.append(text)

    elif ext in {".xlsx", ".csv"}:
        if deepdoc_parser.ExcelParser is None:
            raise RuntimeError("ExcelParser not available")
        # One "header: value; ..." line per row; non-spreadsheet input is read as CSV.
        sections = list(deepdoc_parser.ExcelParser()(binary))

    elif ext in {".pptx"}:
        if deepdoc_parser.PptParser is None:
            raise RuntimeError("PptParser not available")
        # One section per slide.
        sections = list(
            deepdoc_parser.PptParser()(
                binary, int(cfg.get("from_page", 0)), int(cfg.get("to_page", 100000))
            )
        )

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
