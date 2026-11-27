"""Real sample documents for every supported upload format, built in code (no binary
fixtures in the repo). Each contains MARKER, so tests can check the text survived."""

from __future__ import annotations

import io
import json

MARKER = "Photovoltaic"
SENTENCE = f"{MARKER} panels need cleaning twice a year."


def docx(*, table: bool = True) -> bytes:
    import docx as python_docx

    d = python_docx.Document()
    d.add_heading("Solar care", level=1)
    d.add_paragraph(SENTENCE)
    if table:
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Component", "Interval"
        t.cell(1, 0).text, t.cell(1, 1).text = "Inverter", "Yearly"
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def xlsx(*, sheets: dict[str, list[list[str]]] | None = None) -> bytes:
    import openpyxl

    sheets = sheets or {"Sheet": [["Part", "Note"], ["Panel", SENTENCE]]}
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def pptx(*, slides: list[str] | None = None) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    p = Presentation()
    for text in slides or ["Solar care", SENTENCE]:
        s = p.slides.add_slide(p.slide_layouts[6])  # blank
        s.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text_frame.text = text
    b = io.BytesIO()
    p.save(b)
    return b.getvalue()


def _pdf_from_content(content: bytes) -> bytes:
    """A one-page US-letter PDF whose page draws `content` (a content stream, Helvetica as /F1)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def pdf(text: str = SENTENCE) -> bytes:
    """Minimal one-page PDF with real (extractable) text in Helvetica."""
    return _pdf_from_content(f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))


def two_column_pdf(
    title: str,
    left: list[str],
    right: list[str],
    *,
    footer: str | None = None,
    interleaved: bool = True,
    right_offset: float = 0,
    margin_stamp: str | None = None,
) -> bytes:
    """A page with a full-width title, two text columns (left at x=72, right at x=320) and
    an optional full-width footer. Lines of about 42 characters fill a column, like prose.

    interleaved=True stores the text row by row across both columns (left line 1, right
    line 1, left line 2, ...), as some PDF generators do; a parser that follows the
    stored order then mixes the columns. False stores it column by column.
    right_offset lowers the right column by that many points, so its lines don't share a
    baseline with the left column's. margin_stamp adds text rotated 90 degrees in the left
    margin, like the arXiv stamp on preprints."""
    def line(x: float, y: float, text: str, size: int = 10) -> str:
        return f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET"

    left_ops = [line(72, 700 - 14 * i, t) for i, t in enumerate(left)]
    right_ops = [line(320, 700 - 14 * i - right_offset, t) for i, t in enumerate(right)]
    ops = [line(72, 740, title, size=16)]
    if interleaved:
        for i in range(max(len(left_ops), len(right_ops))):
            ops += left_ops[i : i + 1] + right_ops[i : i + 1]
    else:
        ops += left_ops + right_ops
    if footer:
        ops.append(line(72, 700 - 14 * (max(len(left), len(right)) + 2), footer))
    if margin_stamp:
        ops.append(f"BT /F1 10 Tf 0 1 -1 0 40 400 Tm ({margin_stamp}) Tj ET")  # rotated 90 degrees
    return _pdf_from_content(chr(10).join(ops).encode("latin-1"))


# One sample per supported extension.
SAMPLES: dict[str, bytes] = {
    ".txt": f"Solar care\n{SENTENCE}\n".encode(),
    ".md": f"# Solar care\n\n{SENTENCE}\n".encode(),
    ".markdown": f"# Solar care\n\n{SENTENCE}\n".encode(),
    ".html": f"<html><body><h1>Solar care</h1><p>{SENTENCE}</p></body></html>".encode(),
    ".htm": f"<html><body><h1>Solar care</h1><p>{SENTENCE}</p></body></html>".encode(),
    ".json": json.dumps({"topic": "Solar care", "text": SENTENCE}).encode(),
    ".jsonl": (json.dumps({"topic": "Solar care"}) + "\n" + json.dumps({"text": SENTENCE}) + "\n").encode(),
    ".csv": f"Part,Note\nPanel,{SENTENCE}\n".encode(),
    ".xlsx": xlsx(),
    ".docx": docx(),
    ".pptx": pptx(),
    ".pdf": pdf(),
}
