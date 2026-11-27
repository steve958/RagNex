"""Running summaries of long chats (services/conversation_summary.py)."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_engine
from backend.app.main import create_app
from backend.app.models.chat import ChatSession
from backend.app.services import conversation_summary as cs
from backend.app.services.llm import LLMConfig, LLMResult, LLMService
from backend.app.services.prompt_budget import build_prompt, summary_message
from backend.app.services.search import SearchHit

from test_chat_stream import _patch_search, _setup_session

FILLER = " ".join(f"detail{i}" for i in range(110))  # ~110+ tokens per answer


def _ex(i: int, *, minutes: int | None = None) -> cs.Exchange:
    at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=minutes if minutes is not None else i)
    return cs.Exchange(f"question {i}", f"answer {i} {FILLER}", at)


# --- Deciding what to fold -----------------------------------------------------------------


def test_nothing_is_folded_while_history_fits():
    assert cs.exchanges_to_fold([_ex(0), _ex(1)], context_window=8192, reserve_for_answer=2048) == 0


def test_oldest_exchanges_are_folded_down_to_half_the_threshold():
    exchanges = [_ex(i) for i in range(8)]
    n = cs.exchanges_to_fold(exchanges, context_window=2048, reserve_for_answer=256)
    space = int(2048 * 0.9) - 256
    kept = sum(cs._cost(e) for e in exchanges[n:])
    assert 0 < n < len(exchanges)
    assert kept <= cs.FOLD_AT * cs.FOLD_TO * space  # well under the threshold: no fold next turn
    assert kept + cs._cost(exchanges[n - 1]) > cs.FOLD_AT * cs.FOLD_TO * space  # but no more than needed


def test_the_newest_exchange_is_never_folded():
    huge = cs.Exchange("q", "a " * 5000, dt.datetime.now(dt.timezone.utc))
    assert cs.exchanges_to_fold([huge], context_window=2048, reserve_for_answer=256) == 0
    assert cs.exchanges_to_fold([huge, huge], context_window=2048, reserve_for_answer=256) == 1


def test_exchanges_after_skips_covered_and_unanswered_messages():
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

    class M:
        def __init__(self, minute, role, content):
            self.created_at, self.role, self.content = t0 + dt.timedelta(minutes=minute), role, content

    messages = [M(0, "user", "old q"), M(1, "assistant", "old a"), M(2, "user", "failed q"),
                M(3, "user", "new q"), M(4, "assistant", "new a"), M(5, "user", "pending")]
    out = cs.exchanges_after(messages, t0 + dt.timedelta(minutes=1))
    assert [(e.question, e.answer) for e in out] == [("new q", "new a")]


def test_fold_prompt_carries_the_previous_summary_and_clips_huge_messages():
    msgs = cs.fold_prompt("Earlier: the user asked about solar panels.", [cs.Exchange("q", "x" * 10_000, dt.datetime.now())], 300)
    text = msgs[1].content
    assert "<current_summary>\nEarlier: the user asked about solar panels.\n</current_summary>" in text
    assert "User: q" in text
    assert len(text) < 5_000 and "[...]" in text
    assert "at most 300 words" in msgs[0].content
    assert "replaces the current summary" in msgs[0].content


@pytest.mark.parametrize(
    ("output", "usable"),
    [
        ("The user asked about vacation days: 20 a year (Article 12).", True),
        ("User: And sick leave?\nAssistant: Sick leave is paid for up to 30 days.", False),  # an echo
        ("Summary so far.\n  assistant: something", False),
        ("   ", False),
        ("The user (a team lead) asked: which policy applies?", True),
    ],
)
def test_transcripts_are_not_accepted_as_summaries(output, usable):
    assert cs.looks_like_summary(output) is usable


# --- In the prompt -------------------------------------------------------------------------


def _hit() -> SearchHit:
    return SearchHit("c1", "d1", "kb", "t", "context chunk", 1.0, "hybrid")


def test_prompt_sends_the_summary_before_the_recent_history():
    plan = build_prompt(
        question="and in 2024?", hits=[_hit()], history=[("user", "recent q"), ("assistant", "recent a")],
        system_prompt=None, context_window=8192, reserve_for_answer=2048, summary="They discussed 2023 revenue.",
    )
    contents = [m.content for m in plan.messages]
    assert plan.used_summary
    assert contents.index(summary_message("They discussed 2023 revenue.")) < contents.index("recent q")
    assert contents[-1] == "and in 2024?"


def test_retrieved_passages_come_before_the_summary_when_space_is_short():
    plan = build_prompt(
        question="q", hits=[SearchHit("c1", "d1", "kb", "t", "word " * 1100, 1.0, "hybrid")], history=[],
        system_prompt=None, context_window=2048, reserve_for_answer=256, summary="s " * 400,
    )
    assert plan.used_hits and not plan.used_summary


# --- End to end ----------------------------------------------------------------------------


class _FakeModel(LLMService):
    """Answers chat questions; recognizes summary requests by their instructions."""

    chat_prompts: list = []
    summary_prompts: list = []

    async def generate(self, messages):
        if messages[0].content.startswith("You keep a running summary"):
            _FakeModel.summary_prompts.append(messages)
            folded = [line[6:] for line in messages[1].content.splitlines() if line.startswith("User: ")]
            return LLMResult(content=f"SUMMARY{len(_FakeModel.summary_prompts)} covers " + ", ".join(folded))
        _FakeModel.chat_prompts.append(messages)
        return LLMResult(content=f"Answer to {messages[-1].content}: {FILLER}")


async def _drain_background(chat_module) -> None:
    while chat_module._generation_tasks:
        await asyncio.gather(*list(chat_module._generation_tasks))


async def _session_row(session_id) -> tuple[str | None, dt.datetime | None]:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        return (await db.execute(
            sa.select(ChatSession.summary, ChatSession.summary_through).where(ChatSession.id == session_id)
        )).one()


@pytest.fixture
def chat(monkeypatch):
    from backend.app.api.v1 import chat as chat_module

    _FakeModel.chat_prompts, _FakeModel.summary_prompts = [], []
    _patch_search(monkeypatch, chat_module)
    monkeypatch.setattr(chat_module, "_make_llm_service", lambda cfg: _FakeModel(cfg))
    return chat_module


async def _small_window_session(client) -> tuple[dict, uuid.UUID]:
    headers, session_id = await _setup_session(client)
    r = await client.put(
        f"/api/v1/tenants/{headers['X-Tenant-ID']}/model-settings",
        json={"llm": {"context_window": 2048, "max_tokens": 256}}, headers=headers,
    )
    assert r.status_code == 200, r.text
    return headers, session_id


@pytest.mark.asyncio
async def test_long_chat_keeps_a_summary_of_what_no_longer_fits(chat):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _small_window_session(client)
        url = f"/api/v1/chat/sessions/{sid}/messages"
        for i in range(4):
            assert (await client.post(url, json={"content": f"question {i}"}, headers=headers)).status_code == 200
            await _drain_background(chat)

        summary, through = await _session_row(sid)
        assert summary and summary.startswith("SUMMARY1 covers question 0")
        assert through is not None and "question 3" not in summary  # newest kept word for word

        # The next prompt has the summary instead of the folded messages, plus recent ones.
        assert (await client.post(url, json={"content": "question 4"}, headers=headers)).status_code == 200
        await _drain_background(chat)
        prompt = [m.content for m in _FakeModel.chat_prompts[-1]]
        assert summary_message(summary) in prompt
        assert "question 0" not in prompt and "question 3" in prompt

        # Keep going: the next fold builds on the previous summary.
        for i in range(5, 9):
            assert (await client.post(url, json={"content": f"question {i}"}, headers=headers)).status_code == 200
            await _drain_background(chat)
        assert len(_FakeModel.summary_prompts) >= 2
        assert "SUMMARY1 covers" in _FakeModel.summary_prompts[1][1].content
        assert len(_FakeModel.summary_prompts) < 9 - 3  # not a summary call every turn

        r = await client.get(f"/api/v1/chat/sessions/{sid}", headers=headers)
        assert r.json()["summary"] == (await _session_row(sid))[0]


@pytest.mark.asyncio
async def test_streamed_answers_update_the_summary_too(chat, monkeypatch):
    class Streaming(_FakeModel):
        async def generate_stream(self, messages):
            _FakeModel.chat_prompts.append(messages)
            yield f"Answer to {messages[-1].content}: {FILLER}"

    monkeypatch.setattr(chat, "_make_llm_service", lambda cfg: Streaming(cfg))
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _small_window_session(client)
        for i in range(4):
            r = await client.post(f"/api/v1/chat/sessions/{sid}/messages/stream", json={"content": f"question {i}"}, headers=headers)
            assert "event: done" in r.text
            await _drain_background(chat)
    assert (await _session_row(sid))[0]


@pytest.mark.asyncio
async def test_summaries_can_be_turned_off(chat, monkeypatch):
    monkeypatch.setattr(settings, "chat_summary_enabled", False)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _small_window_session(client)
        for i in range(5):
            assert (await client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"content": f"q{i}"}, headers=headers)).status_code == 200
            await _drain_background(chat)
    assert await _session_row(sid) == (None, None)
    assert _FakeModel.summary_prompts == []


@pytest.mark.asyncio
async def test_a_failing_summary_call_changes_nothing(chat, monkeypatch):
    class Broken(_FakeModel):
        async def generate(self, messages):
            if messages[0].content.startswith("You keep a running summary"):
                raise RuntimeError("model unavailable")
            return await super().generate(messages)

    monkeypatch.setattr(chat, "_make_llm_service", lambda cfg: Broken(cfg))
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _small_window_session(client)
        for i in range(5):
            r = await client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"content": f"q{i}"}, headers=headers)
            assert r.status_code == 200  # answering is unaffected
            await _drain_background(chat)
    assert await _session_row(sid) == (None, None)


@pytest.mark.asyncio
async def test_a_concurrent_update_is_not_overwritten(chat):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _small_window_session(client)
        settings_backup = settings.chat_summary_enabled
        settings.chat_summary_enabled = False  # build history without folding
        try:
            for i in range(5):
                await client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"content": f"q{i}"}, headers=headers)
                await _drain_background(chat)
        finally:
            settings.chat_summary_enabled = settings_backup

    newer = dt.datetime.now(dt.timezone.utc)

    class Racing(_FakeModel):
        async def generate(self, messages):
            # Another fold saves first, while this one is waiting for the model.
            async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
                await db.execute(sa.update(ChatSession).where(ChatSession.id == sid).values(summary="the other one", summary_through=newer))
                await db.commit()
            return LLMResult(content="late summary")

    cfg = LLMConfig(provider="ollama", model="m", context_window=2048, max_tokens=256)
    saved = await cs.refresh_summary(uuid.UUID(headers["X-Tenant-ID"]), sid, cfg, lambda c: Racing(c))
    assert saved is False
    assert await _session_row(sid) == ("the other one", newer)
