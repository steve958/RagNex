"""The Anthropic (Claude) chat provider (services/llm_anthropic.py).

The real `anthropic` SDK runs against a mocked HTTP transport that answers with the
Messages API's server-sent events, so request building and response parsing are both
exercised; no request leaves the machine.
"""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest

from backend.app.core.config import settings
from backend.app.services import llm_anthropic
from backend.app.services.llm import LLMConfig, LLMError, LLMMessage, LLMRefusal, create_llm_service

_RealAsyncAnthropic = anthropic.AsyncAnthropic


def _sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _stream_body(texts: list[str], *, stop_reason: str = "end_turn", stop_details: dict | None = None,
                 model: str = "claude-opus-5-5") -> bytes:
    """A streamed Messages API response: a (hidden) thinking block, then text deltas."""
    delta = {"stop_reason": stop_reason, "stop_sequence": None}
    if stop_details is not None:
        delta["stop_details"] = stop_details
    return _sse(
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
                                              "content": [], "stop_reason": None, "stop_sequence": None,
                                              "usage": {"input_tokens": 42, "output_tokens": 1}}},
        # Current models think by default; with display "omitted" the text is empty.
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        *({"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": t}} for t in texts),
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 17}},
        {"type": "message_stop"},
    )


class _Captured(list):
    """Requests the mock received; .reply["body"] is what it answers with."""

    reply: dict


@pytest.fixture
def api(monkeypatch):
    """Route the provider's SDK client to a mock; returns the captured requests."""
    captured = _Captured()
    reply = {"body": _stream_body(["Hello", " there."])}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=reply["body"])

    def client(**kwargs):
        return _RealAsyncAnthropic(
            **kwargs, max_retries=0,
            http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
        )

    monkeypatch.setattr(llm_anthropic.anthropic, "AsyncAnthropic", client)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-server")
    monkeypatch.setattr(settings, "anthropic_refusal_fallback", True)
    captured.reply = reply
    return captured


def _cfg(**kw) -> LLMConfig:
    return LLMConfig(provider="anthropic", model=kw.pop("model", "claude-opus-5-5"), max_tokens=16000, temperature=0.2, **kw)


PROMPT = [
    LLMMessage(role="system", content="Answer from the documents."),
    LLMMessage(role="system", content="Context:\n[1] Vacation: 20 days."),
    LLMMessage(role="user", content="How many vacation days?"),
    LLMMessage(role="assistant", content="20 days."),
    LLMMessage(role="user", content="And carried over?"),
]


def test_factory_returns_the_anthropic_provider():
    assert isinstance(create_llm_service(_cfg()), llm_anthropic.AnthropicLLM)


@pytest.mark.asyncio
async def test_request_shape(api):
    result = await create_llm_service(_cfg()).generate(PROMPT)

    request = api[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/messages"  # beta endpoint path is the same; the header differs
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000 and body["stream"] is True
    # System messages become the top-level system field, in order.
    assert body["system"] == "Answer from the documents.\n\nContext:\n[1] Vacation: 20 days."
    assert body["messages"] == [
        {"role": "user", "content": "How many vacation days?"},
        {"role": "assistant", "content": "20 days."},
        {"role": "user", "content": "And carried over?"},
    ]
    # Current Claude models reject sampling parameters.
    assert "temperature" not in body and "top_p" not in body
    # Refusal fallback is on for this model.
    assert body["fallbacks"] == "default"
    assert llm_anthropic.FALLBACK_BETA in request.headers["anthropic-beta"]
    assert request.headers["authorization"] == "Bearer sk-ant-server"

    # Only text comes back; the thinking block is left out.
    assert result.content == "Hello there."
    assert result.finish_reason == "end_turn" and result.model == "claude-opus-5-5"
    assert result.usage["output_tokens"] == 17


@pytest.mark.asyncio
async def test_streaming_yields_text_as_it_arrives(api):
    api.reply["body"] = _stream_body(["One", ", two", ", three."])
    fragments = [f async for f in create_llm_service(_cfg()).generate_stream(PROMPT)]
    assert fragments == ["One", ", two", ", three."]


@pytest.mark.asyncio
async def test_workspace_key_and_endpoint_are_used(api):
    await create_llm_service(_cfg(api_key="sk-ant-workspace", base_url="https://claude-proxy.example.com")).generate(PROMPT)
    assert api[0].headers["authorization"] == "Bearer sk-ant-workspace"
    assert api[0].url.host == "claude-proxy.example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(("model", "setting", "expected"), [
    ("claude-haiku-5-5", True, False),  # no server-side fallback for this model
    ("claude-opus-5-5", False, False),  # turned off
    ("claude-sonnet-5-5", True, True),
])
async def test_fallback_only_where_supported_and_enabled(api, monkeypatch, model, setting, expected):
    monkeypatch.setattr(settings, "anthropic_refusal_fallback", setting)
    api.reply["body"] = _stream_body(["ok"], model=model)
    await create_llm_service(_cfg(model=model)).generate(PROMPT)
    body = json.loads(api[0].content)
    assert ("fallbacks" in body) is expected
    assert (llm_anthropic.FALLBACK_BETA in api[0].headers.get("anthropic-beta", "")) is expected


@pytest.mark.asyncio
async def test_refusal_raises_with_its_category(api):
    api.reply["body"] = _stream_body([], stop_reason="refusal",
                                     stop_details={"type": "refusal", "category": "cyber", "explanation": "..."})
    with pytest.raises(LLMRefusal) as err:
        await create_llm_service(_cfg()).generate(PROMPT)
    assert err.value.category == "cyber" and "declined" in str(err.value)

    with pytest.raises(LLMRefusal):
        [f async for f in create_llm_service(_cfg()).generate_stream(PROMPT)]


@pytest.mark.asyncio
async def test_cut_off_answer_is_returned_and_logged(api, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(llm_anthropic.logger, "warning", lambda msg, *a: warnings.append(msg % a))
    api.reply["body"] = _stream_body(["Partial"], stop_reason="max_tokens")
    result = await create_llm_service(_cfg()).generate(PROMPT)
    assert result.content == "Partial" and result.finish_reason == "max_tokens"
    assert "raise LLM_MAX_TOKENS" in warnings[0]


def test_conversation_must_start_with_the_user():
    with pytest.raises(LLMError):
        llm_anthropic.to_anthropic_messages([LLMMessage(role="system", content="s"), LLMMessage(role="assistant", content="a")])


@pytest.mark.asyncio
async def test_api_errors_propagate_as_sdk_errors(monkeypatch):
    def handler(request):
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

    monkeypatch.setattr(llm_anthropic.anthropic, "AsyncAnthropic", lambda **kw: _RealAsyncAnthropic(
        **kw, max_retries=0, http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))))
    with pytest.raises(anthropic.AuthenticationError):
        await create_llm_service(_cfg(api_key="bad")).generate(PROMPT)


# --- Through the app -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_can_choose_claude_with_its_own_key():
    import httpx

    from backend.app.main import create_app
    from test_model_settings import Client

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        owner = await Client(http).register()
        r = await owner.put({"llm": {"provider": "anthropic", "model": "claude-opus-5-5"}})
        assert r.status_code == 422 and "API key is required to use Anthropic" in r.json()["detail"]

        r = await owner.put({"llm": {"provider": "anthropic", "model": "claude-opus-5-5", "api_key": "sk-ant-ws"}})
        assert r.status_code == 200, r.text
        assert r.json()["llm"]["effective"]["provider"] == "anthropic"

        # Claude has no embedding API.
        r = await owner.put({"embedding": {"provider": "anthropic"}})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_explains_a_refusal(monkeypatch):
    import httpx

    from backend.app.api.v1 import chat as chat_module
    from backend.app.main import create_app
    from test_chat_stream import _patch_search, _setup_session

    class Refusing(chat_module.LLMService):
        async def generate(self, messages):
            raise LLMRefusal("cyber")

        async def generate_stream(self, messages):
            raise LLMRefusal("cyber")
            yield ""  # pragma: no cover - makes this an async generator

    _patch_search(monkeypatch, chat_module)
    monkeypatch.setattr(chat_module, "_make_llm_service", lambda cfg: Refusing(cfg))
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, sid = await _setup_session(client)
        r = await client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"content": "q"}, headers=headers)
        assert r.status_code == 422
        assert r.json()["detail"] == "The model declined to answer this request (cyber)"

        r = await client.post(f"/api/v1/chat/sessions/{sid}/messages/stream", json={"content": "q"}, headers=headers)
        assert "event: error" in r.text and "declined to answer this request (cyber)" in r.text
        assert "Generation failed" not in r.text
