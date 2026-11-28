"""Load test for RagNex: simulated users searching, chatting, browsing and uploading.

How to run it, what it measures and the results so far: docs/performance.md.

    locust -f loadtest/locustfile.py --host http://localhost:8000

At the start it signs in once (or registers a throwaway account), creates its own
workspace, knowledge base and API key, uploads the corpus and waits until it's indexed.
The simulated users then use the API key, since sign-in is rate limited. When Locust exits it
deletes what it created, unless --ragnex-keep is given.

Run it as a single Locust process (no --processes / --master): the setup runs once, in
that process. One process drives far more load than one API server can take.
"""

from __future__ import annotations

import json
import random
import secrets
import time
import uuid
from pathlib import Path

import requests
from locust import HttpUser, between, events, tag, task
from locust.runners import WorkerRunner

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[1]

# Questions the default corpus (RagNex's own docs/) answers.
QUESTIONS = [
    "How do I add a new chat model provider?",
    "Which file types can I upload?",
    "How are workspaces kept apart in OpenSearch?",
    "What does the re-ranker do and how do I turn it off for one search?",
    "How do I rotate the encryption key?",
    "What happens when a long chat outgrows the context window?",
    "How do I create an API key with read access?",
    "Why does a document stay in the failed state?",
    "How do I publish a new release?",
    "What does RAGNEX_ENCRYPTION_KEY protect?",
    "How do I run the backend tests?",
    "What are the chunking templates and when should I use paper?",
    "How do I add a member to a workspace?",
    "What does the laws template do with articles?",
    "How do I back up the data?",
    "Which settings are required in production?",
]

# Set up once at test start, read by every simulated user.
setup: dict = {}


@events.init_command_line_parser.add_listener
def _arguments(parser):
    parser.add_argument("--ragnex-email", env_var="RAGNEX_LOADTEST_EMAIL", default="",
                        help="Existing account to sign in with; without it a throwaway account is registered")
    parser.add_argument("--ragnex-password", env_var="RAGNEX_LOADTEST_PASSWORD", default="",
                        is_secret=True)
    parser.add_argument("--ragnex-corpus", env_var="RAGNEX_LOADTEST_CORPUS", default=str(ROOT / "docs"),
                        help="Folder of documents to upload and search (default: RagNex's docs/)")
    parser.add_argument("--ragnex-keep", action="store_true", default=False,
                        help="Keep the workspace and its data after the run")
    parser.add_argument("--ragnex-think-time", default="1,3",
                        help="Seconds each simulated user pauses between requests, as MIN,MAX; "
                             "0 for none, to find the maximum throughput")
    parser.add_argument("--ragnex-index-timeout", type=float, default=900,
                        help="Seconds to wait for the corpus to be indexed")


def _corpus(env) -> list[Path]:
    folder = Path(env.parsed_options.ragnex_corpus)
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise SystemExit(f"No documents in {folder}")
    return files


def _record(env, name: str, started: float, *, request_type: str = "SETUP", exc: Exception | None = None):
    """Report a step that isn't a single HTTP request (setup, ingestion) in Locust's stats."""
    env.events.request.fire(request_type=request_type, name=name,
                            response_time=(time.perf_counter() - started) * 1000,
                            response_length=0, exception=exc, context={})


def _check(r: requests.Response) -> dict | list:
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.url} -> {r.status_code}: {r.text[:500]}")
    return r.json()


@events.init.add_listener
def _set_up(environment, runner=None, **_kw):
    # On init rather than test_start: Locust doesn't wait for test_start listeners, so the
    # run's clock would be counting while the corpus is indexed.
    if isinstance(runner, WorkerRunner) or environment.parsed_options is None or not environment.host:
        return
    opts = environment.parsed_options
    base = environment.host.rstrip("/") + API
    s = requests.Session()

    if opts.ragnex_email:
        tokens = _check(s.post(f"{base}/auth/login",
                               json={"email": opts.ragnex_email, "password": opts.ragnex_password}))
    else:
        email = f"loadtest-{secrets.token_hex(4)}@example.com"
        tokens = _check(s.post(f"{base}/auth/register",
                               json={"email": email, "password": secrets.token_urlsafe(18)}))
    s.headers["Authorization"] = f"Bearer {tokens['access_token']}"

    tenant = _check(s.post(f"{base}/tenants", json={"name": f"Load test {time.strftime('%Y-%m-%d %H:%M')}"}))
    tenant_id = tenant["id"]
    s.headers["X-Tenant-ID"] = tenant_id
    key = _check(s.post(f"{base}/api-keys", json={"name": "load test", "scopes": ["read", "write"]}))
    kb = _check(s.post(f"{base}/knowledgebases", json={"name": "Load test corpus"}))

    started = time.perf_counter()
    files = _corpus(environment)
    doc_ids = []
    for path in files:
        with path.open("rb") as fh:
            doc_ids.append(_check(s.post(f"{base}/knowledgebases/{kb['id']}/documents",
                                         files={"file": (path.name, fh)}))["id"])
    pending = set(doc_ids)
    while pending:
        if time.perf_counter() - started > opts.ragnex_index_timeout:
            raise SystemExit(f"{len(pending)} of {len(doc_ids)} documents not indexed after "
                             f"{opts.ragnex_index_timeout:.0f} s; is the worker running?")
        time.sleep(1)
        for doc_id in list(pending):
            doc = _check(s.get(f"{base}/documents/{doc_id}"))
            if doc["status"] == "failed":
                raise SystemExit(f"{doc['filename']} failed: {doc['error_message']}")
            if doc["status"] == "indexed":
                pending.discard(doc_id)
    chunks = sum(_check(s.get(f"{base}/documents/{d}/chunks", params={"size": 1})).get("total", 0)
                 for d in doc_ids)
    print(f"Indexed {len(files)} documents ({chunks} chunks) in {time.perf_counter() - started:.1f} s")

    setup.update(base=base, session=s, tenant_id=tenant_id, kb_id=kb["id"], doc_ids=doc_ids,
                 files=files, headers={"X-API-Key": key["api_key"], "X-Tenant-ID": tenant_id})


@events.quitting.add_listener
def _tear_down(environment, **_kw):
    if not setup or environment.parsed_options.ragnex_keep:
        if setup:
            print(f"Kept workspace {setup['tenant_id']}")
        return
    s, base = setup["session"], setup["base"]
    # Delete the knowledge base first: that purges its search index entries and files.
    # Deleting the workspace alone would leave them behind.
    s.delete(f"{base}/knowledgebases/{setup['kb_id']}")
    s.delete(f"{base}/tenants/{setup['tenant_id']}")


class RagNexUser(HttpUser):
    abstract = True

    def wait_time(self):
        lo, _, hi = self.environment.parsed_options.ragnex_think_time.partition(",")
        return random.uniform(float(lo), float(hi or lo))

    def on_start(self):
        self.client.headers.update(setup["headers"])

    @property
    def kb(self) -> str:
        return setup["kb_id"]


class Searcher(RagNexUser):
    """Searches a knowledge base. Repeated questions find their query vector in the
    embedding cache; new ones have to be embedded. `--tags cached` runs only the former,
    which measures RagNex without the embedding model."""

    weight = 5

    def _search(self, query: str, name: str, **extra):
        self.client.post(f"{API}/knowledgebases/{self.kb}/search",
                         json={"query": query, "top_k": 10, **extra}, name=name)

    @tag("cached")
    @task(3)
    def repeated_question(self):
        self._search(random.choice(QUESTIONS), "search: repeated question")

    @tag("uncached")
    @task(1)
    def new_question(self):
        self._search(f"{random.choice(QUESTIONS)} ({uuid.uuid4().hex[:8]})", "search: new question")


class Chatter(RagNexUser):
    """Asks questions in a chat session, with the answer streamed. Reports the time to the
    first answer text (what the user waits for) and to the end of the answer."""

    weight = 1

    def on_start(self):
        super().on_start()
        r = self.client.post(f"{API}/chat/sessions", json={"kb_ids": [self.kb], "name": "load test"},
                             name="chat: new session")
        self.session_id = r.json()["id"]

    @task
    def ask(self):
        question = f"{random.choice(QUESTIONS)} ({uuid.uuid4().hex[:8]})"
        started = time.perf_counter()
        first_text = None
        event = None
        with self.client.post(f"{API}/chat/sessions/{self.session_id}/messages/stream",
                              json={"content": question}, stream=True, catch_response=True,
                              name="chat: answer complete") as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            for line in r.iter_lines(decode_unicode=True):
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "delta" and first_text is None:
                    first_text = time.perf_counter()
                    self.environment.events.request.fire(
                        request_type="SSE", name="chat: first answer text",
                        response_time=(first_text - started) * 1000, response_length=0,
                        exception=None, context={})
                elif line.startswith("data: ") and event == "error":
                    r.failure(json.loads(line[6:]).get("detail", "error event"))
                    return
                elif line.startswith("data: ") and event == "done":
                    # Locust times a streamed response to its headers; report the whole answer.
                    r.request_meta["response_time"] = (time.perf_counter() - started) * 1000
                    r.success()
                    return
            r.failure("stream ended without a done event")


class Reader(RagNexUser):
    """Browses: the cheap reads the web app makes between questions."""

    weight = 3

    @task(2)
    def knowledge_bases(self):
        self.client.get(f"{API}/knowledgebases", name="list knowledge bases")

    @task(2)
    def documents(self):
        self.client.get(f"{API}/knowledgebases/{self.kb}/documents", name="list documents")

    @task(2)
    def chunks(self):
        self.client.get(f"{API}/documents/{random.choice(setup['doc_ids'])}/chunks",
                        params={"page": 1, "size": 20}, name="list a document's chunks")

    @task(1)
    def sessions(self):
        self.client.get(f"{API}/chat/sessions", name="list chat sessions")


class Uploader(RagNexUser):
    """Uploads a document, waits until it's searchable, then deletes it. Reports the time
    from upload to indexed. Off by default (weight 0): pick it explicitly, e.g.
    `locust ... Uploader Searcher`."""

    weight = 0
    wait_time = between(5, 15)

    @task
    def upload(self):
        path = random.choice(setup["files"])
        started = time.perf_counter()
        with path.open("rb") as fh:
            r = self.client.post(f"{API}/knowledgebases/{self.kb}/documents",
                                 files={"file": (f"{uuid.uuid4().hex[:8]}-{path.name}", fh)},
                                 name="upload document")
        if r.status_code != 200:
            return
        doc_id = r.json()["id"]
        status = "pending"
        while status not in ("indexed", "failed") and time.perf_counter() - started < 600:
            time.sleep(1)
            status = self.client.get(f"{API}/documents/{doc_id}", name="poll document status").json()["status"]
        error = None if status == "indexed" else Exception(f"document {status}")
        _record(self.environment, "document: upload to indexed", started, request_type="INGEST", exc=error)
        self.client.delete(f"{API}/documents/{doc_id}", name="delete document")
