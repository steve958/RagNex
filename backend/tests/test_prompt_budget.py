from __future__ import annotations

from backend.app.services.prompt_budget import answered_exchanges, build_prompt, estimate_tokens
from backend.app.services.search import SearchHit


def _hit(i: int, words: int) -> SearchHit:
    return SearchHit(
        chunk_id=f"c{i}",
        doc_id=f"d{i}",
        kb_id="kb",
        tenant_id="t",
        content=f"chunk{i} " + " ".join(["text"] * words),
        score=1.0 / (i + 1),
        source="hybrid",
    )


def _plan(**overrides):
    args = dict(
        question="What now?",
        hits=[],
        history=[],
        system_prompt=None,
        context_window=8192,
        reserve_for_answer=1024,
    )
    args.update(overrides)
    return build_prompt(**args)


def test_estimate_tokens_is_conservative_for_long_words():
    # One "word" by the word heuristic, but real tokenizers split it into several.
    assert estimate_tokens("Pneumonoultramicroscopicsilicovolcanoconiosis") >= 10
    assert estimate_tokens("") == 0


def test_answered_exchanges_pairs_and_drops_noise():
    history = [
        ("system", "ignored"),
        ("user", "q1"),
        ("assistant", "a1"),
        ("user", "unanswered"),
        ("user", "q2"),
        ("assistant", "  "),  # empty answer: q2 stays pending
        ("assistant", "a2"),
        ("assistant", "orphan answer"),
        ("user", "trailing unanswered"),
    ]
    assert answered_exchanges(history) == [("q1", "a1"), ("q2", "a2")]


def test_everything_fits_in_a_large_window():
    plan = _plan(
        hits=[_hit(0, 10), _hit(1, 10)],
        history=[("user", "q1"), ("assistant", "a1")],
        system_prompt="Be brief.",
    )
    roles = [m.role for m in plan.messages]
    assert roles == ["system", "system", "user", "assistant", "user"]
    assert plan.messages[0].content == "Be brief."
    assert "chunk0" in plan.messages[1].content and "chunk1" in plan.messages[1].content
    assert plan.messages[-1].content == "What now?"
    assert plan.dropped_hits == 0 and plan.dropped_exchanges == 0


def test_lowest_ranked_hits_are_dropped_first():
    # Budget = 0.9*1000 - 100 = 800 tokens; each 200-word hit estimates at ~255
    # (chars/4 dominates), so two fit next to the instructions and question, a third doesn't.
    plan = _plan(hits=[_hit(i, 200) for i in range(4)], context_window=1000, reserve_for_answer=100)
    assert [h.chunk_id for h in plan.used_hits] == ["c0", "c1"]
    assert plan.dropped_hits == 2
    context = plan.messages[0].content
    assert "chunk0" in context and "chunk1" in context and "chunk2" not in context
    assert plan.estimated_tokens <= 800


def test_smaller_lower_ranked_hit_can_fill_remaining_space():
    plan = _plan(hits=[_hit(0, 300), _hit(1, 600), _hit(2, 50)], context_window=1000, reserve_for_answer=100)
    assert [h.chunk_id for h in plan.used_hits] == ["c0", "c2"]


def test_context_has_priority_over_history_and_newest_history_wins():
    history = []
    for i in range(10):
        history += [("user", f"q{i} " + "w " * 40), ("assistant", f"a{i} " + "w " * 40)]
    plan = _plan(hits=[_hit(0, 200)], history=history, context_window=1000, reserve_for_answer=100)

    assert [h.chunk_id for h in plan.used_hits] == ["c0"]
    convo = [m.content.split()[0] for m in plan.messages if m.role != "system"]
    assert convo[-1] == "What"
    kept = convo[:-1]
    n = len(kept) // 2
    assert 0 < n < 10
    assert kept == [x for i in range(10 - n, 10) for x in (f"q{i}", f"a{i}")]
    assert plan.dropped_exchanges == 10 - n
    assert plan.estimated_tokens <= 800


def test_question_is_always_sent_even_when_nothing_else_fits():
    big_question = "word " * 2000
    plan = _plan(
        question=big_question,
        hits=[_hit(0, 50)],
        history=[("user", "q"), ("assistant", "a")],
        context_window=1000,
        reserve_for_answer=100,
    )
    assert plan.messages[-1].content == big_question
    assert plan.used_hits == [] and plan.dropped_exchanges == 1
