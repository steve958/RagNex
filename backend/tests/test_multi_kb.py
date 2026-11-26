"""Chat sessions spanning several knowledge bases, against the real dev stack."""

from __future__ import annotations

import pytest

from test_deletion import BREAD_DOC, SOLAR_DOC, Api, _with_api, pipeline  # noqa: F401 (pipeline is a fixture)
from test_e2e_pipeline import _stack_available

pytestmark = pytest.mark.skipif(not _stack_available(), reason="dev stack (OpenSearch/MinIO) not reachable")


async def _ask(api: Api, session_id: str, question: str) -> list[dict]:
    """Send a question; return the citations of the answer."""
    r = await api.client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": question, "top_k": 3},
        headers=api.headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["citations"]


@pytest.mark.asyncio
async def test_chat_retrieves_from_all_of_its_knowledge_bases(pipeline):
    async def scenario(api: Api):
        energy = await api.create_kb("energy")
        baking = await api.create_kb("baking")
        solar = await api.upload(energy, "solar.md", SOLAR_DOC)
        bread = await api.upload(baking, "bread.md", BREAD_DOC)
        await pipeline.drain()

        r = await api.client.post(
            "/api/v1/chat/sessions", json={"kb_ids": [energy, baking]}, headers=api.headers
        )
        assert r.status_code == 201, r.text
        session_id = r.json()["id"]

        # Each question is answered from whichever KB holds the answer...
        bread_citations = await _ask(api, session_id, "How often should I feed a sourdough starter?")
        assert bread_citations[0]["doc_id"] == bread and bread_citations[0]["kb_id"] == baking
        solar_citations = await _ask(api, session_id, "How should I clean photovoltaic panels?")
        assert solar_citations[0]["doc_id"] == solar and solar_citations[0]["kb_id"] == energy

        # ...and results from both KBs are ranked together, not just the first KB's.
        assert {c["kb_id"] for c in solar_citations} == {energy, baking}

    await _with_api(scenario)


@pytest.mark.asyncio
async def test_chat_keeps_working_when_one_of_its_knowledge_bases_is_deleted(pipeline):
    async def scenario(api: Api):
        energy = await api.create_kb("energy")
        baking = await api.create_kb("baking")
        solar = await api.upload(energy, "solar.md", SOLAR_DOC)
        await api.upload(baking, "bread.md", BREAD_DOC)
        await pipeline.drain()

        r = await api.client.post(
            "/api/v1/chat/sessions", json={"kb_ids": [energy, baking]}, headers=api.headers
        )
        session_id = r.json()["id"]

        r = await api.client.delete(f"/api/v1/knowledgebases/{baking}", headers=api.headers)
        assert r.status_code == 200, r.text

        citations = await _ask(api, session_id, "How often should I feed a sourdough starter?")
        assert citations, "the remaining knowledge base should still be searched"
        assert {c["kb_id"] for c in citations} == {energy}
        assert {c["doc_id"] for c in citations} == {solar}

    await _with_api(scenario)
