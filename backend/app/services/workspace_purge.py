"""Remove a deleted workspace's data outside Postgres: its search indexes and file bucket.

Deleting a workspace deletes its database rows (everything it owns cascades), but its
OpenSearch indexes (`chunks_<id>` and the indexes behind that alias) and its MinIO bucket
(`tenant-<id>`) are separate stores. `purge_workspace_storage` removes both; the
`purge_workspace` task (tasks/purge.py) runs it after a workspace is deleted.

`orphaned_workspaces` finds data whose workspace no longer exists: from deletions made
before this purge existed, or written by a document task that was still running when the
workspace was deleted. `deletion_backfill` uses it.

Both are synchronous (the OpenSearch and MinIO clients are); call them in a thread from
async code.
"""

from __future__ import annotations

import logging
import re
import uuid

from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from backend.app.services.opensearch import OpenSearchService
from backend.app.services.storage import StorageService

logger = logging.getLogger(__name__)

# chunks_<32 hex>, chunks_<32 hex>_v1-000001, ...: the hex is a workspace ID.
_INDEX = re.compile(r"^chunks_([0-9a-f]{32})(?:_.*)?$")
_BUCKET = re.compile(r"^tenant-([0-9a-f]{32})$")


def _workspace_indexes(client, tenant_id: uuid.UUID) -> list[str]:
    # Matches only this workspace: the ID has a fixed length, so another workspace's
    # names can't start with this one's.
    pattern = f"{OpenSearchService.get_index_name(tenant_id)}*"
    found = client.indices.get(index=pattern, ignore_unavailable=True, allow_no_indices=True)
    return sorted(found)


def purge_workspace_storage(tenant_id: uuid.UUID) -> dict:
    """Delete the workspace's search indexes and its bucket with every file in it.

    Idempotent: what's already gone is skipped. The caller makes sure the workspace is
    deleted; this doesn't check.
    """
    client = OpenSearchService()._client()  # noqa: SLF001
    indexes = _workspace_indexes(client, tenant_id)
    if indexes:
        # By name, not by wildcard: clusters may refuse wildcard deletes
        # (action.destructive_requires_name).
        client.indices.delete(index=",".join(indexes), ignore_unavailable=True)

    minio = StorageService()._client  # noqa: SLF001
    bucket = StorageService.bucket_for_tenant(tenant_id)
    files = 0
    bucket_removed = False
    try:
        names = [o.object_name for o in minio.list_objects(bucket, recursive=True)]
        files = len(names)
        errors = list(minio.remove_objects(bucket, (DeleteObject(n) for n in names)))
        if errors:
            raise RuntimeError(f"{len(errors)} file(s) not deleted from {bucket}, first: {errors[0]}")
        minio.remove_bucket(bucket)
        bucket_removed = True
    except S3Error as e:
        if e.code != "NoSuchBucket":
            raise
    return {"indexes": indexes, "files": files, "bucket_removed": bucket_removed}


def orphaned_workspaces(existing: set[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Workspace IDs that have search indexes or a bucket but aren't in `existing`, with
    what was found for each."""
    found: dict[uuid.UUID, dict] = {}

    client = OpenSearchService()._client()  # noqa: SLF001
    for name in client.indices.get(index="chunks_*", ignore_unavailable=True, allow_no_indices=True):
        if (m := _INDEX.match(name)) and (tid := uuid.UUID(m.group(1))) not in existing:
            found.setdefault(tid, {"indexes": [], "bucket": None})["indexes"].append(name)

    for bucket in StorageService()._client.list_buckets():  # noqa: SLF001
        if (m := _BUCKET.match(bucket.name)) and (tid := uuid.UUID(m.group(1))) not in existing:
            found.setdefault(tid, {"indexes": [], "bucket": None})["bucket"] = bucket.name

    return found
