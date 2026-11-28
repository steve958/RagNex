"""Deleting a workspace removes its search indexes and file bucket, against the real dev
stack. The database rows cascade when the workspace is deleted; these two stores are
separate, and used to be left behind."""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest

from backend.app.services.deletion_backfill import run_backfill
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService
from backend.app.services.workspace_purge import orphaned_workspaces
from backend.app.tasks.purge import _purge_workspace, purge_workspace

from test_deletion import Api, _with_api
from test_deletion import pipeline as _pipeline  # noqa: F401 - a fixture
from test_e2e_pipeline import SOLAR_DOC, _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


@pytest.fixture
def pipeline(_pipeline, monkeypatch):
    """The deletion tests' task queue, capturing the workspace purge too."""
    monkeypatch.setattr(purge_workspace, "apply_async", _pipeline.capture(purge_workspace))
    return _pipeline


def _indexes(tenant_id: uuid.UUID) -> list[str]:
    client = OpenSearchService()._client()  # noqa: SLF001
    pattern = f"{OpenSearchService.get_index_name(tenant_id)}*"
    return sorted(client.indices.get(index=pattern, ignore_unavailable=True, allow_no_indices=True))


def _bucket_exists(tenant_id: uuid.UUID) -> bool:
    return StorageService()._client.bucket_exists(StorageService.bucket_for_tenant(tenant_id))  # noqa: SLF001


def _make_leftovers(tenant_id: uuid.UUID) -> None:
    """Search index and bucket with a file, as a deleted workspace would leave them."""
    OpenSearchService().ensure_index(tenant_id)
    minio = StorageService()._client  # noqa: SLF001
    bucket = StorageService.bucket_for_tenant(tenant_id)
    minio.make_bucket(bucket)
    minio.put_object(bucket, "docs/left.md", io.BytesIO(b"left behind"), length=11)


@pytest.mark.asyncio
async def test_deleting_a_workspace_purges_its_indexes_and_files(pipeline):
    async def scenario(api: Api):
        kb = await api.create_kb("kb")
        await api.upload(kb, "solar.md", SOLAR_DOC)
        await pipeline.drain()
        tenant = api.tenant_id
        assert _indexes(tenant) and _bucket_exists(tenant)

        r = await api.client.delete(f"/api/v1/tenants/{tenant}", headers=api.headers)
        assert r.status_code == 200, r.text
        assert [t.name for t, _ in pipeline.pending] == ["backend.app.tasks.purge.purge_workspace"]

        [result] = await pipeline.drain()
        assert result["status"] == "purged"
        assert result["indexes"] and result["files"] == 1 and result["bucket_removed"] is True
        assert _indexes(tenant) == [] and not _bucket_exists(tenant)

        # Idempotent: running it again is harmless.
        again = (await asyncio.to_thread(purge_workspace.apply, args=[str(tenant)])).get()
        assert again == {"tenant_id": str(tenant), "status": "purged", "indexes": [], "files": 0, "bucket_removed": False}

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_purge_refuses_a_workspace_that_exists():
    async def scenario(api: Api):
        await asyncio.to_thread(_make_leftovers, api.tenant_id)
        assert await _purge_workspace(api.tenant_id) == {"status": "skipped", "reason": "workspace exists"}
        assert _indexes(api.tenant_id) and _bucket_exists(api.tenant_id)

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_backfill_purges_data_of_deleted_workspaces():
    """Workspaces deleted before the purge existed left their indexes and buckets behind;
    the backfill finds and removes them, and leaves existing workspaces' data alone."""
    gone = uuid.uuid4()
    await asyncio.to_thread(_make_leftovers, gone)

    async def scenario(api: Api):
        await asyncio.to_thread(_make_leftovers, api.tenant_id)  # a live workspace's data

        dry = await run_backfill(tenant_id=gone)
        assert dry.orphaned_workspaces[gone]["bucket"] == StorageService.bucket_for_tenant(gone)
        assert dry.orphaned_workspaces[gone]["indexes"]
        assert _indexes(gone) and _bucket_exists(gone), "a dry run changes nothing"
        assert "1 deleted workspace" in dry.summary()

        done = await run_backfill(execute=True, tenant_id=gone)
        assert done.workspaces_purged == 1 and done.failures == []
        assert _indexes(gone) == [] and not _bucket_exists(gone)

        live = await asyncio.to_thread(orphaned_workspaces, {api.tenant_id})
        assert api.tenant_id not in live
        assert _indexes(api.tenant_id) and _bucket_exists(api.tenant_id)

    try:
        await _with_api(scenario)
    finally:
        from test_e2e_pipeline import _cleanup_tenant_data

        await asyncio.to_thread(_cleanup_tenant_data, gone)
