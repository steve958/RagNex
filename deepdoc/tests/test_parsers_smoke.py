from __future__ import annotations

from pathlib import Path

import pytest


def test_import_deepdoc_parser_package():
    import deepdoc.parser  # noqa: F401


def test_txt_parser_smoke(tmp_path: Path):
    from deepdoc.parser.txt_parser import RAGFlowTxtParser

    p = tmp_path / "a.txt"
    p.write_text("hello world\nsecond line\n", encoding="utf-8")

    secs = RAGFlowTxtParser()(str(p))
    # txt parser returns list[list[text, style]]
    assert isinstance(secs, list)
    assert secs
    assert isinstance(secs[0][0], str)


def test_json_parser_smoke(tmp_path: Path):
    pytest.importorskip("json")
    from deepdoc.parser.json_parser import RAGFlowJsonParser

    p = tmp_path / "a.json"
    p.write_text('{"a": 1, "b": "x"}', encoding="utf-8")

    sections = RAGFlowJsonParser()(fnm=str(p))
    assert isinstance(sections, list)


def test_markdown_parser_smoke(tmp_path: Path):
    # markdown_parser depends on markdown / bs4; skip if missing
    pytest.importorskip("markdown")
    pytest.importorskip("bs4")

    from deepdoc.parser.markdown_parser import RAGFlowMarkdownParser

    p = tmp_path / "a.md"
    p.write_text("# Title\n\nHello **world**\n", encoding="utf-8")

    secs, tbls = RAGFlowMarkdownParser()(str(p))
    assert isinstance(secs, list)
    assert isinstance(tbls, list)


def test_html_parser_smoke(tmp_path: Path):
    pytest.importorskip("bs4")
    from deepdoc.parser.html_parser import RAGFlowHtmlParser

    p = tmp_path / "a.html"
    p.write_text("<html><body><h1>Title</h1><p>Hello</p></body></html>", encoding="utf-8")

    secs, tbls = RAGFlowHtmlParser()(str(p))
    assert isinstance(secs, list)
    assert isinstance(tbls, list)


def test_docx_parser_importable():
    pytest.importorskip("docx")
    from deepdoc.parser.docx_parser import RAGFlowDocxParser

    assert RAGFlowDocxParser is not None


def test_excel_parser_importable():
    pytest.importorskip("pandas")
    from deepdoc.parser.excel_parser import RAGFlowExcelParser

    assert RAGFlowExcelParser is not None


def test_pdf_parser_importable():
    pytest.importorskip("pypdf")
    from deepdoc.parser.pdf_parser import RAGFlowPdfParser

    assert RAGFlowPdfParser is not None


def test_ppt_parser_importable():
    pytest.importorskip("pptx")
    from deepdoc.parser.ppt_parser import RAGFlowPptParser

    assert RAGFlowPptParser is not None


def test_vision_ocr_importable():
    # Import only; do not run inference (models may not be downloaded).
    pytest.importorskip("onnxruntime")
    pytest.importorskip("cv2")

    from deepdoc.vision import OCR

    assert OCR is not None
