"""Two-column PDFs are read column by column (deepdoc/parser/pdf_parser.py).

pypdf's text is kept unless it mixes the columns; the checks below pin both sides: mixed
pages are re-ordered, everything else (column-ordered pages, tables, single-column pages)
comes out exactly as pypdf gives it.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

import format_samples
from deepdoc.parser import pdf_parser
from deepdoc.parser.pdf_parser import PlainParser, mixes_columns

LEFT = [f"Left column sentence {i} keeps on talking here." for i in range(8)]
RIGHT = [f"Right column sentence {i} is a separate thought." for i in range(8)]
READING_ORDER = ["A Two Column Title", *LEFT, *RIGHT, "Page 3 of 9"]


def _parse(pdf: bytes) -> str:
    sections, _ = PlainParser()(pdf)
    return sections[0][0]


def _pypdf(pdf: bytes) -> str:
    return PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


@pytest.mark.parametrize("right_offset", [0, 4])  # same baseline, or right column a little lower
def test_columns_stored_row_by_row_are_read_column_by_column(right_offset):
    pdf = format_samples.two_column_pdf(
        "A Two Column Title", LEFT, RIGHT, footer="Page 3 of 9", interleaved=True, right_offset=right_offset
    )
    # The problem: following the stored order puts both columns on every line.
    assert "here. Right column sentence 0" in _pypdf(pdf)

    assert _parse(pdf).splitlines() == READING_ORDER


def test_a_column_that_runs_longer_keeps_its_last_lines():
    pdf = format_samples.two_column_pdf("A Two Column Title", LEFT, RIGHT[:5], footer="Page 3 of 9")
    assert _parse(pdf).splitlines() == ["A Two Column Title", *LEFT, *RIGHT[:5], "Page 3 of 9"]


def test_columns_stored_in_order_are_left_exactly_as_pypdf_reads_them():
    """pypdf keeps things the layout can't, such as rotated margin text (and, in real
    papers, inline math); a page it already reads in column order must keep its text."""
    pdf = format_samples.two_column_pdf(
        "A Two Column Title", LEFT, RIGHT, footer="Page 3 of 9", interleaved=False, margin_stamp="arXiv stamp 2026"
    )
    assert _parse(pdf) == _pypdf(pdf)
    assert "arXiv stamp 2026" in _parse(pdf)


def test_a_two_column_table_stays_row_by_row():
    """Names and values side by side are a table, not columns of prose: re-ordering them
    column by column would separate every value from its name."""
    keys = [f"Setting number {i}" for i in range(8)]
    values = [f"Configured value {i}" for i in range(8)]
    pdf = format_samples.two_column_pdf("Configuration", keys, values, interleaved=True)
    assert _parse(pdf) == _pypdf(pdf)
    assert "Setting number 0 Configured value 0" in _parse(pdf)


def test_single_column_pages_are_unchanged():
    pdf = format_samples.pdf()
    assert _parse(pdf) == _pypdf(pdf)


def test_layout_failure_falls_back_to_pypdf(monkeypatch):
    def broken(_filename):
        raise RuntimeError("pdfplumber can't open this")

    monkeypatch.setattr(pdf_parser, "_open_plumber", broken)
    pdf = format_samples.two_column_pdf("A Two Column Title", LEFT, RIGHT, interleaved=True)
    assert _parse(pdf) == _pypdf(pdf)


def test_rotated_text_is_left_out_of_the_layout():
    """Rotated margin text (e.g. an arXiv stamp) is split into reversed pieces by word
    extraction; it must not end up inside the columns."""
    words = []
    for i in range(8):
        words.append({"text": f"left prose line {i} filling the column", "x0": 72, "x1": 290, "top": 100 + 14 * i, "bottom": 110 + 14 * i, "upright": True})
        words.append({"text": f"right prose line {i} filling the column", "x0": 320, "x1": 540, "top": 100 + 14 * i, "bottom": 110 + 14 * i, "upright": True})
    words.append({"text": "5102", "x0": 20, "x1": 30, "top": 130, "bottom": 150, "upright": False})
    layout = pdf_parser._two_column_layout(words, 612)
    assert layout is not None and "5102" not in layout.text


@pytest.mark.parametrize(
    ("order", "mixed"),
    [
        ("LLLLLLRRRRRR", False),  # column order
        ("LLLRRRLLLRRR", False),  # two sections, each in column order
        ("LRLRLRLRLRLR", True),  # row by row
        ("LRLR", False),  # too little to judge: keep pypdf's text
    ],
)
def test_mixes_columns(order, mixed):
    columns = [(side, f"{side} distinctive line number {i}") for i, side in enumerate(order)]
    plain = "\n".join(text for _, text in columns)  # plain text in the given order
    # The check compares positions in the plain text with each line's column.
    left_first = sorted(columns, key=lambda c: c[0])
    assert mixes_columns(plain, left_first) is mixed


def test_upload_pipeline_gets_the_reading_order():
    from backend.app.services.parsing import parse_document_binary

    pdf = format_samples.two_column_pdf("A Two Column Title", LEFT, RIGHT, footer="Page 3 of 9", interleaved=True)
    parsed = parse_document_binary(filename="paper.pdf", binary=pdf, parser_config={})
    text = "\n".join(parsed["sections"])
    assert text.index("Left column sentence 7") < text.index("Right column sentence 0")
