"""PDF parsing utilities for DeepDoc (RagNex).

The upstream ragflow version of DeepDoc included a very feature-rich PDF parser
(layout detection, table extraction, vision-LLM, etc.) with heavy dependencies on
ragflow internals.

For RagNex Phase P0-4 we provide a *standalone* PDF parser that:
- extracts text using pypdf (fast path)
- optionally falls back to OCR (DeepDoc OCR models) when enabled

This keeps DeepDoc importable and usable without the rest of ragflow.
"""

from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

logger = logging.getLogger(__name__)


# --- Two-column reading order -----------------------------------------------------------
#
# pypdf returns text in the order it's stored in the file. Most generators (LaTeX, Word)
# store a two-column page column by column, and that reads fine; pypdf also keeps inline
# math and rotated margin text in one piece. Some generators store a page row by row
# across both columns, and then every line mixes the two columns.
#
# So pypdf's text is kept unless it demonstrably mixes the columns. To tell, the page is
# laid out from word positions (pdfplumber): lines are split at gaps wider than word
# spacing, a column gutter is looked for near the middle of the page, and the text is
# ordered left column first, then right, between full-width lines such as titles and
# footers. If pypdf's text switches between the columns line after line, the laid-out
# text is used instead. Rotated text (e.g. margin stamps) is left out of the layout.


@dataclass(frozen=True)
class _Fragment:
    """A run of words on one line, with no gap wider than normal word spacing."""

    x0: float
    x1: float
    top: float
    bottom: float
    text: str


def _fragments(words: list[dict]) -> list[_Fragment]:
    """Group pdfplumber words into line fragments."""
    if not words:
        return []
    heights = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    height = statistics.median(heights) if heights else 10.0
    # Wider than word spacing in justified narrow columns, narrower than a column gutter.
    split_gap = max(1.2 * height, 8.0)

    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= 0.5 * height:
            rows[-1].append(w)
        else:
            rows.append([w])

    out: list[_Fragment] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        run = [row[0]]
        for w in row[1:]:
            if w["x0"] - run[-1]["x1"] > split_gap:
                out.append(_make_fragment(run))
                run = [w]
            else:
                run.append(w)
        out.append(_make_fragment(run))
    return out


def _make_fragment(words: list[dict]) -> _Fragment:
    return _Fragment(
        x0=min(w["x0"] for w in words),
        x1=max(w["x1"] for w in words),
        top=min(w["top"] for w in words),
        bottom=max(w["bottom"] for w in words),
        text=" ".join(w["text"] for w in words),
    )


def _find_gutter(frags: list[_Fragment], page_width: float) -> float | None:
    """x of a column gutter, or None if the page doesn't have two columns side by side."""
    if len(frags) < 6:
        return None
    best_x, best_crossing = None, None
    x = 0.3 * page_width
    while x <= 0.7 * page_width:
        crossing = sum(1 for f in frags if f.x0 < x < f.x1)
        if best_crossing is None or crossing < best_crossing:
            best_x, best_crossing = x, crossing
        x += 2.0
    if best_x is None:
        return None
    left = [f for f in frags if f.x1 <= best_x]
    right = [f for f in frags if f.x0 >= best_x]
    # Most text sits on either side, and both sides have lines at the same heights:
    # two columns, not an indented list or a page with a margin note.
    if best_crossing > 0.25 * len(frags) or len(left) < 3 or len(right) < 3:
        return None
    side_by_side = sum(1 for r in right if any(abs(r.top - l.top) < 0.5 * (r.bottom - r.top + 1) for l in left))
    if side_by_side < 3:
        return None
    # Columns of prose fill their width; a two-column table (names and values) doesn't.
    # A table is read row by row, which is right, so it must not be re-ordered.
    left_width = best_x - min(f.x0 for f in left)
    right_width = max(f.x1 for f in right) - best_x
    if (
        statistics.median(f.x1 - f.x0 for f in left) < 0.6 * left_width
        or statistics.median(f.x1 - f.x0 for f in right) < 0.6 * right_width
    ):
        return None
    return best_x


@dataclass
class _Layout:
    text: str
    # Column text in reading order, as (side, text): side "L" or "R".
    columns: list[tuple[str, str]]


def _two_column_layout(words: list[dict], page_width: float) -> _Layout | None:
    """The page laid out in reading order if it has two columns, otherwise None."""
    frags = _fragments([w for w in words if w.get("upright", True)])
    gutter = _find_gutter(frags, page_width)
    if gutter is None:
        return None
    line_height = statistics.median(f.bottom - f.top for f in frags) or 10.0
    lines: list[str] = []
    columns: list[tuple[str, str]] = []
    band: list[_Fragment] = []

    def blocks(side: list[_Fragment]) -> list[list[_Fragment]]:
        """Runs of lines with normal spacing; a larger gap starts a new block."""
        out: list[list[_Fragment]] = []
        for f in sorted(side, key=lambda f: f.top):
            if out and f.top - out[-1][-1].bottom <= 1.5 * line_height:
                out[-1].append(f)
            else:
                out.append([f])
        return out

    def flush() -> None:
        left = blocks([f for f in band if f.x1 <= gutter])
        right = blocks([f for f in band if f.x1 > gutter])
        band.clear()
        if not left or not right:
            lines.extend(f.text for b in left + right for f in b)
            return
        # Where both columns have text. A block wholly above it is a header (e.g. a
        # right-aligned running head), wholly below it a footer: read those in page order,
        # around the columns. A column that just runs longer stays part of its column.
        start = max(left[0][0].top, right[0][0].top)
        end = min(left[-1][-1].bottom, right[-1][-1].bottom)
        head = [b for b in left + right if b[-1].bottom < start]
        tail = [b for b in left + right if b[0].top > end]
        body_left = [b for b in left if b not in head and b not in tail]
        body_right = [b for b in right if b not in head and b not in tail]
        for group in (sorted(head, key=lambda b: b[0].top), body_left, body_right, sorted(tail, key=lambda b: b[0].top)):
            lines.extend(f.text for b in group for f in b)
        columns.extend(("L", f.text) for b in body_left for f in b)
        columns.extend(("R", f.text) for b in body_right for f in b)

    for f in sorted(frags, key=lambda f: (f.top, f.x0)):
        if f.x0 < gutter < f.x1:  # full width: ends the columns above it
            flush()
            lines.append(f.text)
        else:
            band.append(f)
    flush()
    return _Layout(chr(10).join(lines), columns)


def _normalize(text: str) -> str:
    # NFKC turns ligatures such as "ﬁ" into "fi"; whitespace differs between extractors.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def mixes_columns(plain_text: str, columns: list[tuple[str, str]]) -> bool:
    """Whether plain_text switches between the two columns line after line.

    Each column line is looked up in plain_text; in column order the sides switch about
    once per section, in mixed text on nearly every line. Lines too short to be
    distinctive, or not found (e.g. math the extractors render differently), are ignored.
    """
    plain = _normalize(plain_text)
    found: list[tuple[int, str]] = []
    for side, text in columns:
        needle = _normalize(text)
        if len(needle) >= 8 and (pos := plain.find(needle)) >= 0:
            found.append((pos, side))
    if len(found) < 6:
        return False
    sides = [side for _, side in sorted(found)]
    switches = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    return switches >= max(4, 0.3 * len(sides))


def column_ordered_text(words: list[dict], page_width: float, plain_text: str) -> str | None:
    """Text to use instead of plain_text, if plain_text mixes the columns of a two-column
    page; otherwise None (plain_text is fine)."""
    layout = _two_column_layout(words, page_width)
    if layout is None or not mixes_columns(plain_text, layout.columns):
        return None
    return layout.text


def _open_plumber(filename: str | bytes):
    import pdfplumber

    return pdfplumber.open(BytesIO(filename) if isinstance(filename, (bytes, bytearray)) else filename)


class PlainParser:
    """Text-only PDF parser: pypdf, with two-column pages put in reading order."""

    def __call__(self, filename: str | bytes, from_page: int = 0, to_page: int = 100000, **kwargs):
        from pypdf import PdfReader

        if isinstance(filename, (bytes, bytearray)):
            reader = PdfReader(BytesIO(filename))
        else:
            reader = PdfReader(filename)

        try:
            plumber = _open_plumber(filename)
        except Exception as e:  # noqa: BLE001 - layout is an improvement; plain text still works
            logger.warning("PDF layout analysis unavailable, using plain text order: %s", e)
            plumber = None

        end = min(len(reader.pages), to_page)
        sections: list[tuple[str, str]] = []
        try:
            for i in range(max(0, from_page), end):
                text = reader.pages[i].extract_text() or ""
                if plumber is not None and text.strip():
                    try:
                        page = plumber.pages[i]
                        # x_tolerance_ratio: LaTeX PDFs often have no space characters; the default
                        # absolute tolerance merges whole word runs ("KaimingHe").
                        words = page.extract_words(x_tolerance_ratio=0.15, extra_attrs=["upright"])
                        text = column_ordered_text(words, float(page.width), text) or text
                    except Exception as e:  # noqa: BLE001
                        logger.warning("PDF layout analysis failed on page %d: %s", i + 1, e)
                # Keep per-page separation for downstream chunking.
                if text.strip():
                    sections.append((text, ""))
        finally:
            if plumber is not None:
                plumber.close()
        return sections, []


class RAGFlowPdfParser(PlainParser):
    """Compatibility alias.

    In RagNex this is the default parser. OCR can be enabled by setting
    `use_ocr=True`.
    """

    def __init__(self, use_ocr: bool = False, **kwargs):
        self.use_ocr = use_ocr
        self._ocr = None

    def _ensure_ocr(self):
        if self._ocr is not None:
            return
        from deepdoc.vision import OCR

        self._ocr = OCR()

    def _ocr_pages(self, filename: str | bytes, from_page: int, to_page: int) -> Iterable[str]:
        import pdfplumber
        import numpy as np

        # pdfplumber is used only to render pages to images.
        if isinstance(filename, (bytes, bytearray)):
            pdf = pdfplumber.open(BytesIO(filename))
        else:
            pdf = pdfplumber.open(filename)

        try:
            pages = pdf.pages
            end = min(len(pages), to_page)
            for i in range(max(0, from_page), end):
                img = pages[i].to_image(resolution=200).original  # PIL.Image
                # OCR.detect expects np array
                arr = np.array(img)
                dets = self._ocr.detect(arr)
                if not dets:
                    yield ""
                    continue
                # dets entries are (box, (text, score)) in upstream; normalize to crops
                boxes = [d[0] for d in dets]
                crops = [self._ocr.get_rotate_crop_image(arr, b) for b in boxes]
                rec = self._ocr.recognize_batch(crops)
                yield "\n".join([r for r in rec if r])
        finally:
            pdf.close()

    def __call__(self, filename: str | bytes, from_page: int = 0, to_page: int = 100000, **kwargs):
        # First attempt plain extraction
        sections, tbls = super().__call__(filename, from_page=from_page, to_page=to_page, **kwargs)

        if not self.use_ocr:
            return sections, tbls

        # If we got any meaningful text, keep it (common for digital PDFs).
        if any(t.strip() for t, _ in sections):
            return sections, tbls

        self._ensure_ocr()
        ocr_sections = [(t, "") for t in self._ocr_pages(filename, from_page, to_page) if t.strip()]
        return ocr_sections, []


# In RagNex, PdfParser is the main entrypoint used by deepdoc.parser.__init__
PdfParser = RAGFlowPdfParser
