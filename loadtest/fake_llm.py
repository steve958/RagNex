"""A stand-in chat model: an OpenAI-compatible endpoint that streams a fixed answer.

With it, a load test measures RagNex itself (search, prompt building, saving, streaming)
rather than how fast a real model writes. Point the API at it with

    LLM_PROVIDER=vllm  VLLM_BASE_URL=http://localhost:8099/v1  LLM_MODEL=fake

and start it with

    python loadtest/fake_llm.py [--port 8099] [--first-token-ms 300] [--tokens 60] [--token-ms 20]

The defaults behave roughly like a fast hosted model: 0.3 s before the first token, then
60 tokens at 50 per second.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

ANSWER_WORDS = ("According to the documentation, this is configured in the settings "
                "described in the guide, and the change takes effect after a restart. ").split()


def create_app(first_token_ms: float, tokens: int, token_ms: float) -> FastAPI:
    app = FastAPI()

    def words():
        return [ANSWER_WORDS[i % len(ANSWER_WORDS)] + " " for i in range(tokens)]

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        if not body.get("stream"):
            await asyncio.sleep((first_token_ms + tokens * token_ms) / 1000)
            return JSONResponse({
                "id": "fake", "object": "chat.completion", "created": int(time.time()), "model": "fake",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "".join(words())}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": tokens, "total_tokens": tokens},
            })

        async def stream():
            # Each token at a fixed time from the start: sleeping a fixed time per token
            # drifts where timers are coarse (on Windows a 20 ms sleep takes about 30 ms).
            loop = asyncio.get_running_loop()
            start = loop.time()
            for i, word in enumerate(words()):
                await asyncio.sleep(max(0.0, start + (first_token_ms + i * token_ms) / 1000 - loop.time()))
                chunk = {"id": "fake", "object": "chat.completion.chunk", "model": "fake",
                         "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}]}
                yield f"data: {json.dumps(chunk)}\n\n"
            done = {"id": "fake", "object": "chat.completion.chunk", "model": "fake",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 when RagNex runs in Docker and reaches it as host.docker.internal")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--first-token-ms", type=float, default=300)
    p.add_argument("--tokens", type=int, default=60)
    p.add_argument("--token-ms", type=float, default=20)
    a = p.parse_args()
    uvicorn.run(create_app(a.first_token_ms, a.tokens, a.token_ms), host=a.host, port=a.port,
                log_level="warning")
