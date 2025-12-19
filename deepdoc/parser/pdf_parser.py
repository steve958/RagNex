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

from io import BytesIO
from typing import Iterable


class PlainParser:
    """Text-only PDF parser using pypdf."""

    def __call__(self, filename: str | bytes, from_page: int = 0, to_page: int = 100000, **kwargs):
        from pypdf import PdfReader

        if isinstance(filename, (bytes, bytearray)):
            reader = PdfReader(BytesIO(filename))
        else:
            reader = PdfReader(filename)

        end = min(len(reader.pages), to_page)
        sections: list[tuple[str, str]] = []
        for i in range(max(0, from_page), end):
            text = reader.pages[i].extract_text() or ""
            # Keep per-page separation for downstream chunking.
            if text.strip():
                sections.append((text, ""))
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
