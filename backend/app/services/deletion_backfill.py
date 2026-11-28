"""Backfill: purge data left behind by deletions.

Before deletion purged data, deleting
  - a document only set its deleted_at: its index entries, chunk rows and file stayed;
  - a knowledge base only set the KB's deleted_at: its documents weren't even marked;
  - a workspace deleted its database rows, but its search indexes and file bucket stayed.
A workspace's indexes or bucket can also outlive it when a document task was still running
as it was deleted.

This backfill:
  1. marks documents of deleted knowledge bases as deleted (using the KB's deletion time);
  2. purges every deleted document that still has data (a stored file or chunk rows),
     using the same idempotent purge as new deletions;
  3. purges search indexes and file buckets whose workspace no longer exists.

Ops-only code, not used on request paths. Dry run by default:

    python -m backend.app.services.deletion_backfill                 # report only
    python -m backend.app.services.deletion_backfill --execute       # purge inline
    python -m backend.app.services.deletion_backfill --execute --enqueue   # via Celery workers

Options: --tenant-id UUID (one tenant), --limit N (at most N document purges per run).
Safe to re-run: purged documents no longer match.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.models.document import Chunk, Document
from backend.app.models.knowledge_base import KnowledgeBase
from backend.app.models.tenant import Tenant


@dataclass
class BackfillReport:
    dry_run: bool
    documents_marked: int = 0  # live documents of deleted KBs (marked, or would be)
    to_purge: int = 0  # deleted documents that still have data
    purged: int = 0
    enqueued: int = 0
    # Deleted workspaces whose search indexes or bucket remain: ID -> what was found.
    orphaned_workspaces: dict[uuid.UUID, dict] = field(default_factory=dict)
    workspaces_purged: int = 0
    workspaces_enqueued: int = 0
    # Set when step 3 couldn't look (OpenSearch or MinIO unreachable).
    orphan_check_error: str | None = None
    failures: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def summary(self) -> str:
        verb = "Would" if self.dry_run else "Did"
        lines = [
            f"{verb} mark {self.documents_marked} document(s) of deleted knowledge bases as deleted.",
            f"{'Would purge' if self.dry_run else 'To purge'}: {self.to_purge} deleted document(s) with leftover data.",
        ]
        if self.orphan_check_error:
            lines.append(f"Could not look for data of deleted workspaces: {self.orphan_check_error}")
        else:
            lines.append(
                f"{'Would purge' if self.dry_run else 'To purge'}: data of {len(self.orphaned_workspaces)} deleted workspace(s)."
            )
            for tid, found in sorted(self.orphaned_workspaces.items()):
                what = [f"{len(found['indexes'])} index(es)"] if found["indexes"] else []
                what += [f"bucket {found['bucket']}"] if found["bucket"] else []
                lines.append(f"  {tid}: {', '.join(what)}")
        if not self.dry_run:
            lines.append(f"Purged: {self.purged}, enqueued: {self.enqueued}, failed: {len(self.failures)}.")
            lines.append(f"Workspaces purged: {self.workspaces_purged}, enqueued: {self.workspaces_enqueued}.")
            lines += [f"  FAILED {doc_id}: {err}" for doc_id, err in self.failures]
        return "\n".join(lines)


def _scope(stmt, model, tenant_id: uuid.UUID | None):
    return stmt.where(model.tenant_id == tenant_id) if tenant_id else stmt


async def run_backfill(
    *,
    execute: bool = False,
    enqueue: bool = False,
    tenant_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> BackfillReport:
    report = BackfillReport(dry_run=not execute)

    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session() as db:
            # 1. Live documents whose knowledge base is deleted.
            orphan_q = _scope(
                sa.select(Document.id, KnowledgeBase.deleted_at)
                .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
                .where(Document.deleted_at.is_(None), KnowledgeBase.deleted_at.is_not(None)),
                Document,
                tenant_id,
            )
            orphans = (await db.execute(orphan_q)).all()
            report.documents_marked = len(orphans)
            if execute and orphans:
                for doc_id, kb_deleted_at in orphans:
                    await db.execute(
                        sa.update(Document)
                        .where(Document.id == doc_id, Document.deleted_at.is_(None))
                        .values(deleted_at=kb_deleted_at)
                    )
                await db.commit()

            # 2. Deleted documents that still have a stored file or chunk rows. (In a dry
            #    run this includes the documents step 1 would mark.)
            has_chunks = sa.exists().where(Chunk.document_id == Document.id)
            leftover_q = _scope(
                sa.select(Document.id, Document.tenant_id)
                .outerjoin(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
                .where(
                    sa.or_(Document.deleted_at.is_not(None), KnowledgeBase.deleted_at.is_not(None)),
                    sa.or_(Document.storage_key.is_not(None), has_chunks),
                )
                .order_by(Document.deleted_at.asc().nulls_last(), Document.id),
                Document,
                tenant_id,
            )
            if limit:
                leftover_q = leftover_q.limit(limit)
            leftovers = (await db.execute(leftover_q)).all()
            report.to_purge = len(leftovers)

            existing = set((await db.execute(sa.select(Tenant.id))).scalars().all())
    finally:
        await eng.dispose()

    # 3. Search indexes and buckets of workspaces that no longer exist.
    try:
        from backend.app.services.workspace_purge import orphaned_workspaces

        found = await asyncio.to_thread(orphaned_workspaces, existing)
        report.orphaned_workspaces = {t: f for t, f in found.items() if tenant_id is None or t == tenant_id}
    except Exception as e:  # noqa: BLE001 - steps 1 and 2 don't depend on it
        report.orphan_check_error = f"{type(e).__name__}: {e}"

    if not execute:
        return report

    # Imported here so a dry run doesn't need Celery configured.
    from backend.app.tasks.purge import _purge, _purge_workspace, purge_document, purge_workspace

    for doc_id, doc_tenant in leftovers:
        if enqueue:
            try:
                purge_document.apply_async(args=[str(doc_id), str(doc_tenant)], priority=3)
                report.enqueued += 1
            except Exception as e:  # noqa: BLE001 - keep going, report at the end
                report.failures.append((doc_id, f"enqueue failed: {type(e).__name__}: {e}"))
            continue
        try:
            result = await _purge(doc_id, doc_tenant)
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            report.failures.append((doc_id, f"{type(e).__name__}: {e}"))
            continue
        if result.get("status") == "purged":
            report.purged += 1
        else:
            report.failures.append((doc_id, f"unexpected purge result: {result}"))

    for tid in sorted(report.orphaned_workspaces):
        try:
            if enqueue:
                purge_workspace.apply_async(args=[str(tid)], priority=3)
                report.workspaces_enqueued += 1
                continue
            # Checks again that the workspace doesn't exist (it may have been created since).
            result = await _purge_workspace(tid)
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            report.failures.append((tid, f"workspace purge: {type(e).__name__}: {e}"))
            continue
        if result.get("status") == "purged":
            report.workspaces_purged += 1
        else:
            report.failures.append((tid, f"unexpected workspace purge result: {result}"))
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true", help="make changes (default: dry run)")
    p.add_argument("--enqueue", action="store_true", help="queue purges for Celery workers instead of running inline")
    p.add_argument("--tenant-id", type=uuid.UUID, default=None, help="limit to one tenant")
    p.add_argument("--limit", type=int, default=None, help="purge at most N documents this run")
    args = p.parse_args(argv)

    if args.enqueue and not args.execute:
        p.error("--enqueue requires --execute")

    report = asyncio.run(
        run_backfill(execute=args.execute, enqueue=args.enqueue, tenant_id=args.tenant_id, limit=args.limit)
    )
    print(report.summary())
    if report.dry_run and (report.documents_marked or report.to_purge or report.orphaned_workspaces):
        print("Dry run: nothing changed. Re-run with --execute to apply.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
