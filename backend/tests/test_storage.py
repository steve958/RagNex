from __future__ import annotations

import os
import uuid

import pytest

from backend.app.services.storage import StorageService


def test_bucket_name_format():
    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    b = StorageService.bucket_for_tenant(tid)
    assert b.startswith("tenant-")
    assert b == b.lower()
    assert len(b) <= 63


def test_file_type_validation_allows_pdf():
    StorageService.validate_file_type("a.pdf", "application/pdf")


def test_file_type_validation_rejects_exe():
    with pytest.raises(ValueError):
        StorageService.validate_file_type("a.exe", "application/octet-stream")


@pytest.mark.asyncio
async def test_minio_roundtrip_smoke():
    """Integration smoke test against local MinIO.

    Skips if MinIO is not reachable or credentials not configured.
    """

    # Only run if explicit env flag is set to avoid polluting shared MinIO.
    if os.getenv("RUN_MINIO_TESTS") != "1":
        pytest.skip("Set RUN_MINIO_TESTS=1 to run MinIO integration tests")

    from dotenv import dotenv_values

    env = dotenv_values(".env")
    if not env.get("S3_ENDPOINT_URL"):
        pytest.skip("No MinIO config")

    tenant_id = uuid.uuid4()

    svc = StorageService()

    # Put a small object using internal client for test isolation
    bucket = await svc.ensure_bucket(tenant_id)
    key = f"test/{uuid.uuid4().hex}.txt"

    import anyio
    import io

    def put_sync():
        data = b"hello"
        svc._client.put_object(bucket, key, data=io.BytesIO(data), length=len(data))

    await anyio.to_thread.run_sync(put_sync)

    got = await svc.download_file(tenant_id, key)
    assert got == b"hello"

    size, chunks = await svc.stream_file(tenant_id, key, chunk_size=2)
    assert size == 5
    assert list(chunks) == [b"he", b"ll", b"o"]

    await svc.delete_file(tenant_id, key)


@pytest.mark.parametrize(
    ("endpoint", "s3_secure", "expected"),
    [
        ("https://s3.example.com", False, True),  # the scheme alone turns TLS on
        ("http://minio:9000", False, False),
        ("minio:9000", True, True),
    ],
)
def test_storage_uses_tls_for_https_endpoints(monkeypatch, endpoint, s3_secure, expected):
    from backend.app.services import storage

    seen = {}
    monkeypatch.setattr(storage, "Minio", lambda host, **kw: seen.update(host=host, **kw))
    monkeypatch.setattr(storage.settings, "s3_endpoint_url", endpoint)
    monkeypatch.setattr(storage.settings, "s3_secure", s3_secure)
    storage.StorageService()
    assert seen["secure"] is expected
    assert "://" not in seen["host"]
