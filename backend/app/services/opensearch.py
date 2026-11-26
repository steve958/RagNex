from __future__ import annotations

import uuid

from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConflictError, NotFoundError

from backend.app.core.config import settings


class OpenSearchService:
    TEMPLATE_NAME = "ragnex-chunks-template"
    CHUNKS_SCHEMA_VERSION = 1

    def _client(self) -> OpenSearch:
        kwargs: dict = {
            "hosts": [settings.opensearch_url],
            "verify_certs": bool(settings.opensearch_verify_certs),
        }
        if settings.opensearch_username and settings.opensearch_password:
            kwargs["http_auth"] = (settings.opensearch_username, settings.opensearch_password)
        return OpenSearch(**kwargs)

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

    def ensure_chunks_policy(self) -> None:
        """Ensure an ISM policy exists for chunk indices.

        OpenSearch uses ISM (Index State Management) rather than Elasticsearch ILM.
        """

        policy_id = str(getattr(settings, "opensearch_chunks_policy_id", "ragnex-chunks-policy"))

        body = {
            "policy": {
                "description": "RagNex chunk index lifecycle",
                "default_state": "hot",
                "states": [
                    {
                        "name": "hot",
                        "actions": [
                            {
                                "rollover": {
                                    "min_size": str(getattr(settings, "opensearch_chunks_rollover_min_size", "5gb")),
                                    "min_index_age": str(getattr(settings, "opensearch_chunks_rollover_min_age", "7d")),
                                }
                            }
                        ],
                        "transitions": [
                            {
                                "state_name": "delete",
                                "conditions": {
                                    "min_index_age": str(getattr(settings, "opensearch_chunks_delete_min_age", "90d"))
                                },
                            }
                        ],
                    },
                    {"name": "delete", "actions": [{"delete": {}}], "transitions": []},
                ],
                "ism_template": [
                    {
                        "index_patterns": ["chunks_*"],
                        "priority": 100,
                    }
                ],
            }
        }

        client = self._client()
        # Create-if-absent. ISM policy PUT is *not* idempotent: once the policy exists,
        # OpenSearch answers 409 unless if_seq_no/if_primary_term are supplied. Changing
        # rollover/delete settings for an existing policy therefore needs an explicit update.
        try:
            client.transport.perform_request("PUT", f"/_plugins/_ism/policies/{policy_id}", body=body)
        except ConflictError:
            pass

    def ensure_template(self) -> None:
        """Ensure an index template exists for chunk indices."""

        client = self._client()

        policy_id = str(getattr(settings, "opensearch_chunks_policy_id", "ragnex-chunks-policy"))

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
