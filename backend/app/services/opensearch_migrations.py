from __future__ import annotations

import uuid

from backend.app.services.opensearch import OpenSearchService


class OpenSearchMigrationService:
    """Utilities for migrating chunk indices.

    This is intentionally "ops-style" code: it is not called on request paths.
    Prefer running it manually (or via a one-off job) for safety.

    Supported scenarios:
    - Legacy tenant index: concrete index named chunks_<tenanthex>
    - Current tenant index: alias chunks_<tenanthex> -> backing index chunks_<tenanthex>_v{N}-000001
    """

    def __init__(self) -> None:
        self.os = OpenSearchService()

    def migrate_legacy_tenant_index(self, tenant_id: uuid.UUID, *, delete_legacy: bool = False) -> str:
        """Migrate a legacy tenant index (concrete index name equals alias).

        Creates a new backing index and reindexes from the legacy index.

        If delete_legacy=True, deletes the old index after alias cutover.
        """

        client = self.os._client()  # noqa: SLF001
        alias = self.os.get_index_name(tenant_id)

        # If alias already exists, nothing to do.
        try:
            if client.indices.exists_alias(name=alias):
                return alias
        except Exception:
            pass

        if not client.indices.exists(index=alias):
            # Neither alias nor legacy index exists -> create fresh.
            self.os.ensure_index(tenant_id)
            return alias

        # Create new backing index.
        backing = self.os.get_backing_index_name(tenant_id, seq=1)
        client.indices.create(
            index=backing,
            body={
                "settings": {
                    "plugins.index_state_management.rollover_alias": alias,
                },
                "aliases": {alias: {"is_write_index": True}},
            },
        )

        # Reindex from legacy -> new backing.
        client.transport.perform_request(
            "POST",
            "/_reindex",
            body={"source": {"index": alias}, "dest": {"index": backing}},
        )

        # NOTE: We cannot create an alias named `alias` while an index of the same name exists.
        # The alias was attached to the backing index above; now we must remove/rename the legacy
        # index name before the alias can be used. The simplest is delete the legacy index.
        #
        # We default to NOT deleting, unless explicitly requested.
        if delete_legacy:
            client.indices.delete(index=alias)

        return alias

    def ensure_policies_and_templates(self) -> None:
        """Install/refresh the ISM policy and index template."""

        self.os.ensure_chunks_policy()
        self.os.ensure_template()
