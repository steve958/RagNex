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


def pdf(text: str = SENTENCE) -> bytes:
    """Minimal one-page PDF with real (extractable) text in Helvetica."""
    content = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
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
