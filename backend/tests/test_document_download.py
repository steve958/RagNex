"""Downloading the original uploaded file. Real dev stack (MinIO)."""

from __future__ import annotations

import uuid
from urllib.parse import unquote

import pytest

from backend.app.api.v1.documents import _attachment
from backend.app.services.storage import StorageService

from test_deletion import Api, _db_state, _with_api, pipeline  # noqa: F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")

BODY = "# Quarterly report\n\nRevenue grew in every region.\n".encode() * 50


def _download(api: Api, doc: str, headers: dict | None = None):
    return api.client.get(f"/api/v1/documents/{doc}/file", headers=headers or api.headers)


def _saved_name(content_disposition: str) -> str:
    """The name a modern browser saves under (the RFC 5987 filename*)."""
    encoded = content_disposition.split("filename*=UTF-8''", 1)[1]
    return unquote(encoded)


@pytest.mark.asyncio
async def test_download_returns_the_exact_uploaded_file(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "Überblick Q3 (final).md", BODY)

        r = await _download(api, doc)
        assert r.status_code == 200, r.text
        assert r.content == BODY
        assert r.headers["content-length"] == str(len(BODY))
        disposition = r.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert _saved_name(disposition) == "Überblick Q3 (final).md"

        # Still downloadable once processed (the pipeline doesn't touch the stored file).
        await pipeline.drain()
        assert (await _download(api, doc)).content == BODY

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_uploaded_html_is_never_rendered_by_the_browser(pipeline):
    """An uploaded HTML file opened in the app's origin would run its scripts with the
    viewer's session. It must always download, and never be sniffed as HTML."""

    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "page.html", b"<html><script>fetch('/api/v1/api-keys')</script></html>")

        r = await _download(api, doc)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["content-disposition"].startswith("attachment;")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-security-policy"].startswith("sandbox")
        assert "no-store" in r.headers["cache-control"]

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_other_workspaces_and_deleted_documents_get_404(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "secret.md", BODY)

        other = Api(api.client)
        await other.register()
        r = await _download(other, doc)
        assert r.status_code == 404  # not 403: don't reveal that the document exists

        # Even naming the owner's workspace doesn't help a non-member.
        r = await _download(other, doc, {**other.headers, "X-Tenant-ID": str(api.tenant_id)})
        assert r.status_code == 403

        assert (await api.client.delete(f"/api/v1/documents/{doc}", headers=api.headers)).status_code == 200
        assert (await _download(api, doc)).status_code == 404
        assert (await _download(api, str(uuid.uuid4()))).status_code == 404

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_read_scoped_api_key_can_download(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "notes.md", BODY)
        r = await api.client.post("/api/v1/api-keys", json={"name": "reader", "scopes": ["read"]}, headers=api.headers)
        assert r.status_code == 200, r.text
        key_headers = {"X-API-Key": r.json()["api_key"], "X-Tenant-ID": str(api.tenant_id)}

        r = await _download(api, doc, key_headers)
        assert r.status_code == 200
        assert r.content == BODY

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_missing_stored_file_is_a_clear_404(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        doc = await api.upload(kb, "gone.md", BODY)
        _rows, key = await _db_state(doc)
        await StorageService().delete_file(api.tenant_id, key)

        r = await _download(api, doc)
        assert r.status_code == 404
        assert r.json()["detail"] == "The original file isn't stored for this document"

    await _with_api(scenario)


@pytest.mark.parametrize(
    ("filename", "fallback", "saved"),
    [
        ("report.pdf", "report.pdf", "report.pdf"),
        ('say "hi".md', "say _hi_.md", 'say "hi".md'),  # quotes can't break out of the header
        ("Überblick.pdf", "_berblick.pdf", "Überblick.pdf"),
        ("../../etc/passwd.md", "passwd.md", "passwd.md"),  # no path components
        ("a\r\nSet-Cookie: x=1.md", None, None),  # no header injection
    ],
)
def test_attachment_header(filename, fallback, saved):
    header = _attachment(filename)
    assert "\r" not in header and "\n" not in header
    if fallback is not None:
        assert header.startswith(f'attachment; filename="{fallback}";')
        assert _saved_name(header) == saved
