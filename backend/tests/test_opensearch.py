from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.main import create_app
from backend.app.services.opensearch import OpenSearchService


def test_index_name_format():
    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert OpenSearchService.get_index_name(tid) == "chunks_12345678123456781234567812345678"


@pytest.mark.asyncio
async def test_create_tenant_calls_ensure_index(monkeypatch):
    app = create_app()

    called = {"n": 0}

    def fake_ensure_index(self, tenant_id):
        called["n"] += 1
        assert isinstance(tenant_id, uuid.UUID)
        return OpenSearchService.get_index_name(tenant_id)

    monkeypatch.setattr("backend.app.api.v1.tenants.OpenSearchService.ensure_index", fake_ensure_index)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": f"u_{uuid.uuid4().hex}@example.com", "password": "test-password-1"},
        )
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]

        r = await client.post(
            "/api/v1/tenants",
            json={"name": "t2"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert r.status_code == 200, r.text
        assert called["n"] == 1


class _FakeISM:
    """Records ISM requests; GET returns `stored` (None = the policy doesn't exist)."""

    def __init__(self, stored=None, put_error=None):
        self.stored = stored
        self.put_error = put_error
        self.calls = []

    def perform_request(self, method, url, params=None, body=None):
        from opensearchpy.exceptions import NotFoundError

        self.calls.append((method, url, params, body))
        if method == "GET":
            if self.stored is None:
                raise NotFoundError(404, "resource_not_found_exception", {})
            return self.stored
        if method == "PUT" and self.put_error:
            raise self.put_error
        return {}


@pytest.fixture
def ism(monkeypatch):
    def install(**kwargs):
        fake = _FakeISM(**kwargs)

        class FakeClient:
            transport = fake

        monkeypatch.setattr(OpenSearchService, "_client", lambda self: FakeClient())
        monkeypatch.setattr(OpenSearchService, "_policy_verified", False)
        return fake

    return install


def _stored(policy_body, seq_no=7, primary_term=1):
    return {"_id": "ragnex-chunks-policy", "_seq_no": seq_no, "_primary_term": primary_term, **policy_body}


def test_chunks_policy_never_deletes_indices():
    """Chunk indices hold whole knowledge bases. A delete state (the old policy deleted every
    index 90 days after creation) drops documents from search while they still show as ready."""
    policy = OpenSearchService()._policy_body()["policy"]
    actions = [a for state in policy["states"] for a in state["actions"]]
    assert not any("delete" in a for a in actions)
    assert all(state["transitions"] == [] for state in policy["states"])
    # Size-based rollover only: a weekly rollover adds a shard per tenant per week until the
    # cluster's shard limit (1000 per node by default) stops all indexing.
    assert actions == [{"rollover": {"min_size": "30gb"}}]


def test_ensure_chunks_policy_creates_missing_policy(ism):
    fake = ism(stored=None)
    OpenSearchService().ensure_chunks_policy()
    assert [(m, u) for m, u, _, _ in fake.calls] == [
        ("GET", "/_plugins/_ism/policies/ragnex-chunks-policy"),
        ("PUT", "/_plugins/_ism/policies/ragnex-chunks-policy"),
    ]


def test_ensure_chunks_policy_tolerates_concurrent_creation(ism):
    """Regression: ISM PUT answers 409 if another process created the policy first; that must
    not fail search/indexing."""
    from opensearchpy.exceptions import ConflictError

    ism(stored=None, put_error=ConflictError(409, "version_conflict_engine_exception", {}))
    OpenSearchService().ensure_chunks_policy()  # must not raise


def test_ensure_chunks_policy_leaves_current_policy_alone_and_checks_once(ism):
    fake = ism(stored=_stored(OpenSearchService()._policy_body()))
    OpenSearchService().ensure_chunks_policy()
    OpenSearchService().ensure_chunks_policy()
    assert [(m, u) for m, u, _, _ in fake.calls] == [("GET", "/_plugins/_ism/policies/ragnex-chunks-policy")]


def test_ensure_chunks_policy_replaces_old_deleting_policy(ism):
    old = {
        "policy": {
            "description": "RagNex chunk index lifecycle",
            "default_state": "hot",
            "states": [
                {"name": "hot", "actions": [{"rollover": {"min_size": "5gb", "min_index_age": "7d"}}],
                 "transitions": [{"state_name": "delete", "conditions": {"min_index_age": "90d"}}]},
                {"name": "delete", "actions": [{"delete": {}}], "transitions": []},
            ],
        }
    }
    fake = ism(stored=_stored(old, seq_no=12, primary_term=3))
    OpenSearchService().ensure_chunks_policy()

    _, url, params, body = fake.calls[1]
    assert (fake.calls[1][0], url) == ("PUT", "/_plugins/_ism/policies/ragnex-chunks-policy")
    assert params == {"if_seq_no": 12, "if_primary_term": 3}  # ISM rejects updates without them
    assert body == OpenSearchService()._policy_body()
    # Existing indices keep the policy version they started with until re-attached.
    assert [(m, u, b) for m, u, _, b in fake.calls[2:]] == [
        ("POST", "/_plugins/_ism/remove/chunks_*", None),
        ("POST", "/_plugins/_ism/add/chunks_*_v*", {"policy_id": "ragnex-chunks-policy"}),
    ]


def test_ensure_chunks_policy_applies_a_changed_rollover_size(ism, monkeypatch):
    fake = ism(stored=_stored(OpenSearchService()._policy_body()))
    monkeypatch.setattr("backend.app.services.opensearch.settings.opensearch_chunks_rollover_min_size", "50gb")
    OpenSearchService().ensure_chunks_policy()
    assert fake.calls[1][3]["policy"]["states"][0]["actions"] == [{"rollover": {"min_size": "50gb"}}]


def test_client_is_reused_within_a_process(monkeypatch):
    """A new client per call opened new connections for every search; one client per process
    keeps them open. A forked process (Celery workers) gets its own, not its parent's sockets."""
    monkeypatch.setattr(OpenSearchService, "_clients", {})
    first = OpenSearchService()._client()
    assert OpenSearchService()._client() is first
    monkeypatch.setattr("backend.app.services.opensearch.os.getpid", lambda: -1)
    assert OpenSearchService()._client() is not first


def test_index_template_is_written_once_per_process(monkeypatch):
    puts = []

    class FakeIndices:
        def put_index_template(self, name, body):
            puts.append(name)

    class FakeClient:
        indices = FakeIndices()

    monkeypatch.setattr(OpenSearchService, "_client", lambda self: FakeClient())
    monkeypatch.setattr(OpenSearchService, "_template_verified", False)
    OpenSearchService().ensure_template()
    OpenSearchService().ensure_template()
    assert puts == [OpenSearchService.TEMPLATE_NAME]
