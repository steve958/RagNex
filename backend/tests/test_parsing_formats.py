"""Every supported upload format, through the same parse + chunk path the worker uses.

Regression: DOCX and XLSX were called with the wrong signature and always failed; CSV
and .doc were accepted at upload but had no parser; PPTX had a parser but no route; TXT
glued words together across lines.
"""

from __future__ import annotations

import re
import time

import pytest

from backend.app.services.chunking.general import GeneralChunkConfig, chunk_parsed_document
from backend.app.services.parsing import SUPPORTED_EXTENSIONS, parse_document_binary

from format_samples import MARKER, SAMPLES, SENTENCE, docx, pptx, xlsx


def _parse(ext: str, data: bytes) -> dict:
    return parse_document_binary(filename=f"sample{ext}", binary=data, parser_config={})


def _chunks(parsed: dict) -> list[str]:
    return [c["content"] for c in chunk_parsed_document(parsed, GeneralChunkConfig())]


def test_every_supported_extension_has_a_sample():
    # Keeps the supported list and this test suite in step.
    assert set(SAMPLES) == set(SUPPORTED_EXTENSIONS)


@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_text_survives_parsing_and_chunking(ext):
    parsed = _parse(ext, SAMPLES[ext])
    assert parsed["ext"] == ext
    assert parsed["sections"], f"{ext}: no sections"

    text = "\n".join(_chunks(parsed))
    assert MARKER in text, f"{ext}: marker lost"
    # Words stay separate tokens: keyword search depends on it.
    for word in ("panels", "cleaning"):
        assert re.search(rf"\b{word}\b", text), f"{ext}: {word!r} glued to a neighbour in {text!r}"


@pytest.mark.parametrize("ext", [".txt", ".md", ".html", ".pptx", ".docx", ".json"])
def test_heading_and_body_are_not_glued_together(ext):
    text = "\n".join(_chunks(_parse(ext, SAMPLES[ext])))
    assert re.search(r"\bcare\b", text) and re.search(rf"\b{MARKER}\b", text), text


def test_txt_keeps_punctuation_and_line_breaks():
    parsed = _parse(".txt", b"First line ends here!\nIs this kept? Yes; it is.\n")
    text = "\n".join(parsed["sections"])
    assert "here!\nIs this kept? Yes; it is." in text


def test_docx_tables_become_searchable_chunks():
    parsed = _parse(".docx", docx(table=True))
    assert parsed["tables"], "table dropped"
    text = "\n".join(_chunks(parsed))
    for cell in ("Component", "Inverter", "Yearly"):
        assert cell in text


def test_spreadsheet_rows_keep_header_labels_across_sheets():
    data = xlsx(sheets={"Sheet": [["Part", "Note"], ["Panel", "clean twice"]], "Inventory": [["Item"], ["Inverter"]]})
    sections = _parse(".xlsx", data)["sections"]
    assert "Part: Panel; Note: clean twice" in sections
    # Rows from a named sheet carry the sheet name so they stay distinguishable.
    assert any("Item: Inverter" in s and "Inventory" in s for s in sections)


def test_pptx_gives_one_section_per_slide():
    sections = _parse(".pptx", pptx(slides=["First slide text", "Second slide text", "Third"]))["sections"]
    assert sections == ["First slide text", "Second slide text", "Third"]


@pytest.mark.parametrize(
    "ext, data",
    [
        (".txt", "Café, naïve façade — Grüße 太阳能电池板 ✓\n".encode()),
        (".md", "# Überblick\n\nPanneaux photovoltaïques: nettoyer 2×/an 🌞\n".encode()),
        (".csv", "Teil,Hinweis\nModul,Zweimal jährlich reinigen\n".encode()),
    ],
)
def test_non_ascii_text_survives(ext, data):
    text = "\n".join(_parse(ext, data)["sections"])
    for word in re.findall(r"\w{4,}", data.decode()):
        assert word in text, f"{ext}: lost {word!r} in {text!r}"


@pytest.mark.parametrize("ext", sorted(SAMPLES))
@pytest.mark.parametrize("data", [b"", b"  \n\t \n"])
def test_empty_files_are_rejected_with_a_clear_message(ext, data):
    with pytest.raises(ValueError, match="empty"):
        _parse(ext, data)


@pytest.mark.parametrize("ext", [".docx", ".xlsx", ".pptx", ".pdf"])
def test_corrupt_binary_files_fail_fast(ext):
    """A broken file must raise (the task then marks the document failed), not hang or
    silently produce an empty document."""
    started = time.monotonic()
    with pytest.raises(Exception):
        parsed = _parse(ext, b"this is not a real " + ext.encode() + b" file" * 50)
        assert parsed["sections"], "corrupt file parsed to an empty document"
    assert time.monotonic() - started < 10


def test_unsupported_types_are_rejected_by_the_parser():
    for name in ("old.doc", "old.ppt", "old.xls", "noext"):
        with pytest.raises(ValueError, match="Unsupported"):
            parse_document_binary(filename=name, binary=b"x", parser_config={})


def test_sentence_constant_is_what_samples_contain():
    # Guard for the helpers themselves.
    assert SENTENCE in SAMPLES[".txt"].decode()


# --- Uploads: accepted formats match what can be parsed, end to end ----------------------

from test_deletion import Api, _with_api, pipeline  # noqa: E402,F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available  # noqa: E402

needs_stack = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


@needs_stack
@pytest.mark.asyncio
async def test_upload_rejects_unparseable_and_empty_files(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        for name, body, reason in [
            ("legacy.doc", b"\xd0\xcf\x11\xe0 old word", "Unsupported file type .doc"),
            ("legacy.ppt", b"\xd0\xcf\x11\xe0 old ppt", "Unsupported file type .ppt"),
            ("no-extension", b"some text", "Unsupported file type (no extension)"),
            ("empty.txt", b"", "The file is empty"),
        ]:
            r = await api.client.post(
                f"/api/v1/knowledgebases/{kb}/documents", files={"file": (name, body)}, headers=api.headers
            )
            assert r.status_code == 400, (name, r.text)
            assert reason in r.json()["detail"], (name, r.json()["detail"])
        assert pipeline.pending == [], "nothing should have been queued"

    await _with_api(scenario)


@needs_stack
@pytest.mark.asyncio
async def test_office_formats_are_indexed_and_searchable(pipeline):
    """The formats that used to fail every time, through upload, the worker tasks and search."""
    from opensearchpy.exceptions import NotFoundError  # noqa: F401
    from backend.app.services.opensearch import OpenSearchService

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        uploads = {
            "report.docx": docx(),
            "sheet.xlsx": xlsx(),
            "table.csv": SAMPLES[".csv"],
            "deck.pptx": pptx(),
        }
        docs = {name: await api.upload(kb, name, body) for name, body in uploads.items()}
        results = await pipeline.drain()
        assert sorted(r["status"] for r in results) == ["done"] * 4 + ["indexed"] * 4, results

        for name, doc_id in docs.items():
            r = await api.client.get(f"/api/v1/documents/{doc_id}", headers=api.headers)
            assert r.json()["status"] == "indexed", (name, r.json())

        OpenSearchService()._client().indices.refresh(  # noqa: SLF001
            index=OpenSearchService.get_index_name(api.tenant_id)
        )
        r = await api.client.post(
            f"/api/v1/knowledgebases/{kb}/search", json={"query": "photovoltaic panels cleaning", "top_k": 10},
            headers=api.headers,
        )
        assert r.status_code == 200, r.text
        assert {h["doc_id"] for h in r.json()["hits"]} == set(docs.values())

    await _with_api(scenario)


def test_frontend_upload_picker_offers_exactly_the_supported_types():
    from pathlib import Path

    form = Path(__file__).resolve().parents[2] / "frontend/src/components/documents/DocumentUploadForm.tsx"
    match = re.search(r"SUPPORTED_UPLOAD_TYPES\s*=\s*'([^']+)'", form.read_text(encoding="utf-8"))
    assert match, "SUPPORTED_UPLOAD_TYPES not found in the upload form"
    assert set(match.group(1).split(",")) == set(SUPPORTED_EXTENSIONS)
