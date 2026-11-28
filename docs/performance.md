# Performance

What limits RagNex's speed, what was measured, and how to run the load test yourself.
In short: **the models set the pace**. RagNex itself handles dozens of searches a second
on a laptop; embedding questions, writing answers and indexing documents take the
embedding and chat models' time, so that's where to spend hardware.

## What limits what

| Work | Limited by | Measured (test machine below) |
|---|---|---|
| Search, question seen before | RagNex: the API and OpenSearch | 58 searches a second, median 320 ms with 20 users sending back to back; 93 ms median at a normal load |
| Search, new question | The embedding model: each new question is embedded first | bge-m3 on CPU: about 75 ms per question, one at a time, so new questions queue under load |
| Chat | The chat model | RagNex adds about 0.3 s per question (embedding it, searching, saving); the rest is the model |
| Indexing | The embedding model | bge-m3 on CPU: about 1.5 s per chunk; 8 documents (60 chunks) took 65 s |
| Lists, history, chunks | RagNex and Postgres | 30–40 ms median |

### Search

A search embeds the question (cached in Redis for 24 hours, so repeated questions skip
this), runs a keyword and a vector query in OpenSearch side by side, and checks the hits'
documents still exist. With the query vector cached, two API processes
(`API_WORKERS=2`) served 58 searches a second, using about two CPU cores, with OpenSearch
using almost as much. More API processes help until OpenSearch or the CPUs are busy.

A new question also waits for the embedding model. Ollama on a CPU embeds one at a
time, so when many new questions arrive together they queue there, not in RagNex.

These numbers are for a small index (60 chunks). Search on a large index costs OpenSearch
more; that wasn't measured.

### Chat

Before the answer starts, RagNex embeds the question, searches and saves it: about 0.3 s
under load. Everything after is the model. A chat model on a CPU is slow for more than one
user: `gemma2:2b` took about a minute per answer on the test machine, and Ollama writes
one answer at a time, so a question queued behind two others waited more than two
minutes and failed with a read timeout (RagNex waits up to 120 s for the model's next
output). For several simultaneous users, run the model on a GPU or use a hosted one.

### Indexing

Each chunk is embedded once; the vectors are cached by text, so reprocessing the same
text is fast (the same 60 chunks took 6 s the second time). On a CPU, bge-m3 takes about
1.5 s per chunk of about 1,500 characters. Sending texts in batches didn't help there (16
chunks: 23.5 s one by one, 25.8 s as one batch).

With Ollama, each chunk is one request, and `EMBEDDING_RPS` (default 5) caps the requests
per second for each document being indexed. On a CPU that cap is never reached; with a
fast model on a GPU it can be the limit, so raise it (or set `0`). The worker indexes
`WORKER_CONCURRENCY` documents at a time.

## Bottlenecks found and fixed

Found with the load test and a profiler (py-spy) on the API under load, in November 2026:

| Problem | Fix |
|---|---|
| Each search created a new database engine to read the workspace's embedding settings: a new Postgres connection per search, set up and torn down | Uses the API's shared connection pool |
| Each search rewrote the OpenSearch index template (a cluster-state change) and checked the index exists | Search only queries; the template is written once per process |
| A new OpenSearch client, with new connections, for every call | One client per process, keeping its connections open |
| The OpenSearch client is synchronous and ran on the API's event loop, so one slow query held up every other request in that process | The two queries run in threads, side by side |
| Search results included each chunk's stored vector: about 455 KB per response instead of 40 KB | Only the fields used are returned |
| Starlette's `BaseHTTPMiddleware` (three middlewares): about a tenth of the API's CPU | Plain ASGI middlewares. This also fixed the request log line, which lacked its request ID, and its timing, which stopped at the response headers for streamed answers |
| Every embedding and re-ranker HTTP client loaded the CA certificate bundle again: about 7% of the API's CPU | Built once per process |

Together, on the same machine and test:

| | Before | After |
|---|---|---|
| Searches a second, question seen before (20 users, no pauses) | 22 | 58 |
| Median search time in that test | 760 ms | 320 ms |
| Postgres CPU in that test | 63% | 22% |
| Mixed load (30 users, about 13 requests a second): search median / 95th percentile | 170 / 720 ms | 93 / 260 ms |
| Same, lists and history: 95th percentile | 210–350 ms | 130–180 ms |

Searches with new questions and chat wait on the models, so their times varied from run to
run with the models' load and aren't compared here.

**Not changed**, smaller or not shown to matter:

- Ollama embeddings are requested one text per request; batching (Ollama's `/api/embed`)
  showed no gain on a CPU.
- Each API process keeps up to 5 database connections open, plus up to 10 more opened and
  closed when busier (SQLAlchemy's defaults); reopening those was about 2% of the API's
  CPU at full load.
- The chat model's 120 s read timeout isn't configurable.

## Running the load test

The load test (`loadtest/locustfile.py`, using [Locust](https://locust.io)) simulates users
searching, chatting, browsing and uploading. It sets itself up: it signs in once (or
registers a throwaway account), creates a workspace, a knowledge base and an API key,
uploads a corpus and waits until it's indexed. The simulated users use the API key,
because sign-in is rate limited. When Locust exits, it deletes the knowledge base (and so
its search index entries and files) and the workspace.

```bash
uv sync --project backend --active --locked --extra dev --extra deepdoc --extra loadtest

# Against a running RagNex, worker included: docker-compose.prod.yml on :8080, or the
# development setup's API on :8000
locust -f loadtest/locustfile.py --host http://localhost:8080
# then open http://localhost:8089, choose the number of users, start

# Or without the web page, for 2 minutes with 30 users:
locust -f loadtest/locustfile.py --host http://localhost:8080 --headless -u 30 -r 5 -t 2m
```

Run it as one Locust process (no `--processes` or `--master`): the setup runs once, in
that process, and one process creates more load than an API server can take.

**Simulated users.** Locust picks them in proportion to their weight; name classes at the
end of the command to run only those (e.g. `... Searcher`).

| User | Weight | Does |
|---|---|---|
| `Searcher` | 5 | Searches: 3 of 4 times a question seen before (`search: repeated question`), otherwise a new one (`search: new question`) |
| `Chatter` | 1 | Asks questions in a chat, answers streamed. Reports `chat: first answer text` (what a user waits for) and `chat: answer complete` |
| `Reader` | 3 | Lists knowledge bases, documents, a document's chunks and chats |
| `Uploader` | 0 | Uploads a document, waits until it's indexed (`document: upload to indexed`), deletes it. Only when named, e.g. `... Uploader Searcher` |

**Options** (also as environment variables):

| Option | Environment variable | Default | |
|---|---|---|---|
| `--ragnex-email`, `--ragnex-password` | `RAGNEX_LOADTEST_EMAIL`, `RAGNEX_LOADTEST_PASSWORD` | (register a throwaway account) | An existing account to use, e.g. when registration is off |
| `--ragnex-corpus` | `RAGNEX_LOADTEST_CORPUS` | RagNex's `docs/` | Folder of documents to upload and search |
| `--ragnex-think-time` | | `1,3` | Seconds each user pauses between requests (`MIN,MAX`); `0` for none, to find the maximum throughput |
| `--ragnex-keep` | | off | Keep the workspace and its data afterwards |
| `--ragnex-index-timeout` | | `900` | Seconds to wait for the corpus to be indexed |
| `--tags cached` | | | Only searches with a cached question: measures RagNex without the embedding model |

**Measuring RagNex rather than the chat model.** `loadtest/fake_llm.py` is a stand-in chat
model: an OpenAI-compatible endpoint that streams a fixed answer at a set pace. Start it
with `python loadtest/fake_llm.py` (in Docker: `--host 0.0.0.0`) and point RagNex at it with
`LLM_PROVIDER=vllm`, `VLLM_BASE_URL=http://localhost:8099/v1` (in Docker:
`http://host.docker.internal:8099/v1`) and `LLM_MODEL=fake`. Time it on its own too, and
compare: chat time minus the fake model's time is RagNex's.

**Reading the results.** Look at the median and the 95th percentile, not the average.
Measure on hardware like production's: Docker Desktop on a laptop shares the CPUs between
RagNex, the models and Locust itself.

### The test machine

The numbers above: a laptop with an Intel Core i7-1165G7 (4 cores, 8 threads) and 24 GB
of memory, Windows 11 with Docker Desktop (11.5 GB for containers). RagNex ran as
`docker-compose.prod.yml` (2 API processes, worker concurrency 2, through nginx); Ollama
ran on the host on the CPU, with `bge-m3`; chat used the fake model (set to 0.3 s to the
first word, then 50 words a second), except where `gemma2:2b` is named. The corpus was RagNex's
`docs/` (8 documents, 60 chunks).
