# Development

Working on RagNex: setting up, testing, conventions, debugging and releasing. For how the
system fits together, see [architecture.md](architecture.md); for adding providers,
parsers, templates or endpoints, [extending.md](extending.md).

## Setting up

Requirements: Python 3.13, Node 22, Docker. On Windows, the commands work from Git Bash
or PowerShell.

```bash
# Data stores with published ports: Postgres 5432, Redis 6379, OpenSearch 9200,
# OpenSearch Dashboards 5601, MinIO 9000 (console 9001)
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env      # set JWT_SECRET and RAGNEX_ENCRYPTION_KEY (see the comments)

# Backend: the exact versions in backend/uv.lock, into the active venv
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install uv
uv sync --project backend --active --locked --extra dev --extra deepdoc
alembic -c backend/alembic.ini upgrade head

# Models: pull the chat and embedding models into Ollama (or configure another provider)
ollama pull llama3 && ollama pull bge-m3
```

Run each in its own terminal, from the repository root:

```bash
python -m uvicorn backend.app.main:create_app --factory --reload        # API on :8000
celery -A backend.app.core.celery_app.celery_app worker \
  -Q default,parsing,embedding,indexing --loglevel=info                   # Windows: add --pool=solo
cd frontend && npm ci && npm run dev                                     # http://localhost:5173
```

The Vite dev server forwards `/api` to the API, so the web app, the API and the
interactive API reference (http://localhost:5173/api/docs) share one origin.

## Tests

```bash
cd backend && python -m pytest            # whole backend suite (about 3 minutes)
cd backend && python -m pytest tests/test_rerank.py -k fallback   # one file / matching tests
cd deepdoc && python -m pytest tests      # DeepDoc parser smoke tests
cd frontend && npm test -- --run          # frontend; `npm test` alone starts watch mode
cd frontend && npm run build              # type check + production build
```

- **The backend suite uses the real data stores** from `docker-compose.dev.yml`, applying
  migrations at the start. Tests that need OpenSearch or MinIO skip when they're down;
  set `RAGNEX_TESTS_REQUIRE_STACK=1` to make that an error instead, as CI does.
- **Models are faked**: tests don't call Ollama, OpenAI or Anthropic. Provider tests run
  the real client against a mocked HTTP transport (`tests/test_llm_anthropic.py`,
  `tests/test_rerank.py`).
- **The dev database is shared** with your local app. Tests create their own users and
  workspaces and clean up what would get in the way, but test data accumulates; reset with
  `docker compose -f docker-compose.dev.yml down -v` if it bothers you.
- **Coverage**: `python -m pytest --cov` (backend), `npm test -- --run --coverage`
  (frontend).
- **Docs are tested too**: `tests/test_docs.py` checks that every setting appears in
  `docs/configuration.md` and that links between the docs resolve;
  `tests/test_api_guide.py` runs the examples in `docs/api.md`.

## Conventions

- **Every change comes with tests**, including a test that fails without the change.
  When fixing a bug, write the failing test first.
- **Comments explain why**, not what: the reason for a limit, the bug a check prevents,
  the trade-off taken. Name the case they guard against.
- **Docs change with the code**: settings in `configuration.md`, behaviour users see in
  `user-guide.md`, API changes in `api.md`, operations in `deployment.md`, and progress in
  `TASK_PROGRESS.md`.
- **Dependencies**: edit `backend/pyproject.toml`, run `uv lock` in `backend/`, commit
  both files; CI fails if the lockfile is out of date. Frontend: `npm install <package>`
  and commit `package-lock.json`.
- **Lint**: `python -m ruff check <files you changed>`. The codebase has older findings,
  so CI doesn't enforce lint yet; don't add new ones.
- **Secrets** never go into the repository: `.env` and `.env.*` are ignored, except the
  `*.example` files, which hold no real values.

## Commits and pull requests

- Work on a branch and open a pull request against `master`. CI
  (`.github/workflows/ci.yml`) runs the backend tests against real data stores, the DeepDoc
  tests, and the frontend tests and build; merge only when it's green.
- **Commit messages**: a short summary line in the imperative ("Add re-ranking of search
  results"), then a body saying what changed and why, and what was found along the way.
  The history has many examples.
- One topic per commit, so it can be reviewed and reverted on its own.

## Debugging

**Logs.** The API and worker log JSON lines to stdout (`LOG_LEVEL=DEBUG` for more). Each
API request gets an ID, returned in the `X-Request-ID` response header and attached to
every log line of that request, so you can find the logs of a failed request by its ID.
In Docker: `docker compose -f docker-compose.prod.yml logs -f api worker`.

**Debugging a background task.** Stop the worker and call the task directly from a Python
shell at the repository root (with the dev stack up and `.env` set); it runs in that
process, so breakpoints and `print` work:

```python
from backend.app.tasks.parsing import parse_document
from backend.app.tasks.indexing import index_document
parse_document.run("<document id>", "<workspace id>")   # parse and chunk; queues indexing
index_document.run("<document id>", "<workspace id>")   # embed and index
```

(`.run` calls the task's code without Celery. There is no "eager" mode that runs tasks
inside the API: the tasks use `asyncio.run()`, which fails in the API's event loop.)

**Looking at the data** (dev stack):

| What | How |
|---|---|
| Database | `docker exec -it ragnex-postgres psql -U ragnex -d ragnex`; a document's `status`, `error_message` and `parsed_data` are on its `documents` row |
| A document's chunks | `GET /api/v1/documents/{id}/chunks`, or the document view in the web app |
| Search index | OpenSearch Dashboards at http://localhost:5601, or `curl 'localhost:9200/chunks_<workspace id without dashes>/_search?q=content:solar'` |
| Stored files | MinIO console at http://localhost:9001 (credentials from `.env`); one bucket per workspace, `tenant-<workspace id without dashes>` |
| Data store health | `GET /health/ready` on the API |
| What search returns | `POST /api/v1/knowledgebases/{id}/search`, with `"rerank": false` to compare the order without the re-ranker |

**Common log lines.**

| Log says | Means |
|---|---|
| `Prompt trimmed to fit context window ...` | Passages or earlier messages didn't fit `LLM_CONTEXT_WINDOW` and were left out |
| `Re-ranking failed, using the search order instead` | The re-ranker is unreachable or returned an error |
| `Chat session ...: folded N exchange(s) into its summary` | A long chat's summary was updated |
| `Claude answer cut off at max_tokens` | Raise `LLM_MAX_TOKENS`; thinking counts toward it |
| `PDF layout analysis failed on page N` | Column detection failed on a page; its plain text was used |

## Releasing

1. Make sure `master` is green in CI and deployment notes are up to date
   (`docs/deployment.md`, in particular new required settings and migrations).
2. Tag the release and push the tag:
   ```bash
   git tag v1.2.3 && git push origin v1.2.3
   ```
3. CI builds and publishes `ghcr.io/<owner>/ragnex-backend` and `ragnex-frontend` tagged
   `1.2.3` and `1.2` (pushes to `master` publish `latest`, `master` and `sha-<commit>`).
   Check the run's "Publish" jobs succeeded.
4. Write the release notes on GitHub (Releases → the tag): what changed for users, and for
   operators anything to do before upgrading: new required settings, migrations, changed
   defaults.

Deployments pick a release with `RAGNEX_VERSION` (`docs/deployment.md`); migrations run
automatically before the new API starts. The version numbers in `backend/pyproject.toml`
and `frontend/package.json` (`0.0.1`) aren't used by anything yet; the tag is the version.
