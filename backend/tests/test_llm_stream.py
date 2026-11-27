from __future__ import annotations

import json

import httpx
import pytest

from backend.app.services import llm as llm_module
from backend.app.services.llm import LLMConfig, LLMError, LLMMessage, OllamaLLM, OpenAICompatibleLLM

MESSAGES = [LLMMessage(role="user", content="hi")]


def _install_transport(monkeypatch, handler) -> list[httpx.Request]:
    """Route the provider's httpx.AsyncClient through a MockTransport; returns captured requests."""
    captured: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def wrapped(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", factory)
    return captured


async def _collect(service, messages=MESSAGES) -> list[str]:
    return [f async for f in service.generate_stream(messages)]


@pytest.mark.asyncio
async def test_ollama_stream_parses_ndjson(monkeypatch):
    lines = [
        {"message": {"role": "assistant", "content": "Hel"}, "done": False},
        {"message": {"role": "assistant", "content": "lo"}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]
    body = "\n".join(json.dumps(x) for x in lines) + "\n"
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, text=body))

    svc = OllamaLLM(LLMConfig(provider="ollama", model="m", base_url="http://ollama", context_window=16384))
    assert await _collect(svc) == ["Hel", "lo"]

    sent = json.loads(captured[0].content)
    assert captured[0].url == "http://ollama/api/chat"
    assert sent["stream"] is True
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    # Without num_ctx Ollama silently truncates prompts at its own default window.
    assert sent["options"]["num_ctx"] == 16384


@pytest.mark.asyncio
async def test_ollama_stream_error_payload_raises(monkeypatch):
    _install_transport(monkeypatch, lambda req: httpx.Response(200, text='{"error": "model not found"}\n'))
    svc = OllamaLLM(LLMConfig(provider="ollama", model="m", base_url="http://ollama"))
    with pytest.raises(LLMError, match="model not found"):
        await _collect(svc)


@pytest.mark.asyncio
async def test_openai_stream_parses_sse(monkeypatch):
    def chunk(content):
        return {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}

    body = (
        ": keep-alive comment\n\n"
        f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'role': 'assistant'}}]})}\n\n"
        f"data: {json.dumps(chunk('Hi'))}\n\n"
        f"data: {json.dumps(chunk(' there'))}\n\n"
        f"data: {json.dumps({'choices': [], 'usage': {'total_tokens': 3}})}\n\n"
        "data: [DONE]\n\n"
    )
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, text=body))

    svc = OpenAICompatibleLLM(
        LLMConfig(provider="openai", model="gpt", base_url="http://oai/v1", api_key="k")
    )
    assert await _collect(svc) == ["Hi", " there"]

    req = captured[0]
    assert req.url == "http://oai/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer k"
    assert json.loads(req.content)["stream"] is True


@pytest.mark.asyncio
async def test_stream_http_error_raises(monkeypatch):
    _install_transport(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    svc = OpenAICompatibleLLM(LLMConfig(provider="openai", model="gpt", base_url="http://oai/v1"))
    with pytest.raises(httpx.HTTPStatusError):
        await _collect(svc)


@pytest.mark.asyncio
async def test_vllm_uses_vllm_base_url_and_never_the_openai_key(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "vllm_base_url", "http://vllm:8000/v1")
    monkeypatch.setattr(llm_module.settings, "openai_api_key", "sk-openai-secret")
    body = 'data: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n'
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, text=body))

    svc = llm_module.create_llm_service(LLMConfig(provider="vllm", model="m"))
    assert await _collect(svc) == ["ok"]
    assert captured[0].url == "http://vllm:8000/v1/chat/completions"
    assert "Authorization" not in captured[0].headers


@pytest.mark.asyncio
async def test_vllm_without_base_url_fails_instead_of_calling_openai(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "vllm_base_url", None)
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, text=""))

    svc = llm_module.create_llm_service(LLMConfig(provider="vllm", model="m"))
    with pytest.raises(ValueError, match="vllm_base_url"):
        await _collect(svc)
    assert captured == []


@pytest.mark.asyncio
async def test_openai_provider_still_uses_openai_settings(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "openai_base_url", "http://oai/v1")
    monkeypatch.setattr(llm_module.settings, "openai_api_key", "sk-openai")
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, text="data: [DONE]\n\n"))

    await _collect(llm_module.create_llm_service(LLMConfig(provider="openai", model="m")))
    assert captured[0].url == "http://oai/v1/chat/completions"
    assert captured[0].headers["Authorization"] == "Bearer sk-openai"


# --- Non-streaming generate (used by POST /chat/sessions/{id}/messages) --------------------


@pytest.mark.asyncio
async def test_ollama_generate_parses_the_reply(monkeypatch):
    body = {"model": "m", "message": {"role": "assistant", "content": "Hello there"}, "done": True, "done_reason": "stop"}
    captured = _install_transport(monkeypatch, lambda req: httpx.Response(200, json=body))

    result = await OllamaLLM(LLMConfig(provider="ollama", model="m", base_url="http://ollama")).generate(MESSAGES)
    assert (result.content, result.model, result.finish_reason) == ("Hello there", "m", "stop")
    assert json.loads(captured[0].content)["stream"] is False


@pytest.mark.asyncio
async def test_openai_generate_parses_the_reply_and_usage(monkeypatch):
    body = {
        "model": "gpt",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 7},
    }
    _install_transport(monkeypatch, lambda req: httpx.Response(200, json=body))

    svc = OpenAICompatibleLLM(LLMConfig(provider="openai", model="gpt", base_url="http://oai/v1", api_key="k"))
    result = await svc.generate(MESSAGES)
    assert (result.content, result.finish_reason, result.usage) == ("Hi", "stop", {"total_tokens": 7})


@pytest.mark.asyncio
async def test_openai_generate_without_choices_is_an_error(monkeypatch):
    _install_transport(monkeypatch, lambda req: httpx.Response(200, json={"choices": []}))
    svc = OpenAICompatibleLLM(LLMConfig(provider="openai", model="gpt", base_url="http://oai/v1"))
    with pytest.raises(ValueError, match="Empty choices"):
        await svc.generate(MESSAGES)


@pytest.mark.asyncio
async def test_generate_raises_on_http_errors(monkeypatch):
    _install_transport(monkeypatch, lambda req: httpx.Response(503, text="overloaded"))
    with pytest.raises(httpx.HTTPStatusError):
        await OllamaLLM(LLMConfig(provider="ollama", model="m", base_url="http://ollama")).generate(MESSAGES)


def test_unknown_provider_is_rejected():
    cfg = LLMConfig(provider="ollama", model="m").model_copy(update={"provider": "no-such-provider"})
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm_module.create_llm_service(cfg)
