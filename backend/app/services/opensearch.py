from __future__ import annotations

import os
import threading
import uuid
from typing import ClassVar

from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConflictError, NotFoundError

from backend.app.core.config import settings


class OpenSearchService:
    TEMPLATE_NAME = "ragnex-chunks-template"
    CHUNKS_SCHEMA_VERSION = 1

    # One client per process: it keeps a pool of open connections, so reusing it saves a
    # connection setup per request (docs/performance.md). Keyed by process ID because a client created
    # before Celery forks its workers must not share its sockets with them.
    _clients: ClassVar[dict[tuple, OpenSearch]] = {}
    _clients_lock = threading.Lock()

    def _client(self) -> OpenSearch:
        key = (os.getpid(), settings.opensearch_url, settings.opensearch_username,
               settings.opensearch_password, bool(settings.opensearch_verify_certs))
        with OpenSearchService._clients_lock:
            client = OpenSearchService._clients.get(key)
            if client is None:
                kwargs: dict = {
                    "hosts": [settings.opensearch_url],
                    "verify_certs": bool(settings.opensearch_verify_certs),
                    # Search runs its queries in threads; room for that many at once.
                    "maxsize": 32,
                }
                if settings.opensearch_username and settings.opensearch_password:
                    kwargs["http_auth"] = (settings.opensearch_username, settings.opensearch_password)
                client = OpenSearchService._clients[key] = OpenSearch(**kwargs)
            return client

    @staticmethod
    def get_index_name(tenant_id: uuid.UUID) -> str:
        # Tenant write alias (stable)
        return f"chunks_{tenant_id.hex}"

    @classmethod
    def get_backing_index_name(cls, tenant_id: uuid.UUID, *, seq: int = 1) -> str:
        # Backing index for the tenant write alias.
        # Example: chunks_<tenanthex>_v1-000001
        alias = cls.get_index_name(tenant_id)
        return f"{alias}_v{cls.CHUNKS_SCHEMA_VERSION}-{seq:06d}"

    # Set once the policy on the cluster is known to be current, so indexing and search don't
    # check it on every call. Per process; a restart re-checks.
    _policy_verified: bool = False
    # Likewise for the index template: writing it changes the cluster state, which is slow
    # and was done on every search.
    _template_verified: bool = False

    @staticmethod
    def _policy_description() -> str:
        # The description records the settings the policy was built from, so a stored policy
        # built from other settings (or the old 90-day-delete policy) is detected and replaced.
        return (
            "RagNex chunk indices: roll over at "
            f"{settings.opensearch_chunks_rollover_min_size}; never deletes"
        )

    def _policy_body(self) -> dict:
        return {
            "policy": {
                "description": self._policy_description(),
                "default_state": "hot",
                "states": [
                    {
                        "name": "hot",
                        # Size only: chunk indices hold a tenant's whole knowledge base, not
                        # time-series data. There is deliberately no delete state: deleting an
                        # index would drop documents from search while they still show as
                        # ready. Documents are removed only by deleting them in RagNex.
                        "actions": [{"rollover": {"min_size": str(settings.opensearch_chunks_rollover_min_size)}}],
                        "transitions": [],
                    }
                ],
                "ism_template": [{"index_patterns": ["chunks_*"], "priority": 100}],
            }
        }

    def ensure_chunks_policy(self) -> None:
        """Create the ISM lifecycle policy for chunk indices, or replace an outdated one.

        OpenSearch uses ISM (Index State Management) rather than Elasticsearch ILM.
        """

        if OpenSearchService._policy_verified:
            return
        policy_id = settings.opensearch_chunks_policy_id
        url = f"/_plugins/_ism/policies/{policy_id}"
        client = self._client()

        try:
            current = client.transport.perform_request("GET", url)
        except NotFoundError:
            current = None

        if current is None:
            try:
                client.transport.perform_request("PUT", url, body=self._policy_body())
            except ConflictError:
                pass  # created concurrently by another process
        elif (current.get("policy") or {}).get("description") != self._policy_description():
            # Updating needs the stored version (ISM rejects a plain PUT with 409).
            client.transport.perform_request(
                "PUT",
                url,
                params={"if_seq_no": current["_seq_no"], "if_primary_term": current["_primary_term"]},
                body=self._policy_body(),
            )
            # Indices keep the policy version they started with, so re-attach them. Remove and
            # add take effect at once; "change_policy" would wait for the current state to end.
            # Only versioned backing indices: old-layout indices have no rollover alias.
            client.transport.perform_request("POST", "/_plugins/_ism/remove/chunks_*")
            client.transport.perform_request("POST", "/_plugins/_ism/add/chunks_*_v*", body={"policy_id": policy_id})

        OpenSearchService._policy_verified = True

    def ensure_template(self) -> None:
        """Ensure an index template exists for chunk indices (once per process)."""

        if OpenSearchService._template_verified:
            return
        client = self._client()

        policy_id = settings.opensearch_chunks_policy_id

        body = {
            "index_patterns": ["chunks_*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    # OpenSearch k-NN plugin flag
                    "index.knn": True,
                    # Attach lifecycle policy to chunk indices.
                    "plugins.index_state_management.policy_id": policy_id,
                },
                "mappings": {
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "doc_id": {"type": "keyword"},
                        "kb_id": {"type": "keyword"},
                        "tenant_id": {"type": "keyword"},
                        "content": {"type": "text", "analyzer": "standard"},
                        "content_vector": {
                            "type": "knn_vector",
                            "dimension": int(getattr(settings, "embedding_dimension", 1024)),
                        },
                        "title_tokens": {"type": "text"},
                        "created_at": {"type": "date"},
                    }
                },
            },
        }

        # Composable templates (OpenSearch 2.x compatible)
        client.indices.put_index_template(name=self.TEMPLATE_NAME, body=body)
        OpenSearchService._template_verified = True

    def ensure_index(self, tenant_id: uuid.UUID) -> str:
        """Ensure a tenant write alias exists for chunk indexing.

        New layout:
        - alias: chunks_<tenanthex>
        - backing index: chunks_<tenanthex>_v{schema}-000001

        Legacy layout (older dev data):
        - concrete index named chunks_<tenanthex>

        For legacy indices we return the concrete index name (and do not attempt to migrate
        in-place automatically).
        """

        self.ensure_chunks_policy()
        self.ensure_template()
        client = self._client()

        alias = self.get_index_name(tenant_id)

        # Preferred: alias exists.
        try:
            if client.indices.exists_alias(name=alias):
                return alias
        except Exception:
            # Some clusters might not allow exists_alias; fall through.
            pass

        # Legacy: concrete index exists with the alias name.
        if client.indices.exists(index=alias):
            return alias

        # Create first backing index and attach alias as the write index.
        backing = self.get_backing_index_name(tenant_id, seq=1)
        body = {
            "settings": {
                # Required for ISM rollover action.
                "plugins.index_state_management.rollover_alias": alias,
            },
            "aliases": {
                alias: {"is_write_index": True},
            },
        }
        client.indices.create(index=backing, body=body)
        return alias

    def delete_document_chunks(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int:
        """Remove every indexed chunk of a document. Returns the number deleted.

        Idempotent: a tenant with no index yet, or a document with nothing indexed, is a no-op.
        """
        client = self._client()
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": str(tenant_id)}},
                        {"term": {"doc_id": str(document_id)}},
                    ]
                }
            }
        }
        try:
            resp = client.delete_by_query(
                index=self.get_index_name(tenant_id),
                body=body,
                refresh=True,  # make the removal visible to the very next search
                conflicts="proceed",
            )
        except NotFoundError:
            return 0  # tenant has no index yet
        return int(resp.get("deleted", 0))

    def health(self) -> dict:
        client = self._client()
        return client.cluster.health()
