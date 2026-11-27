# RagNex

RagNex is a self-hosted, multi-tenant Retrieval-Augmented Generation (RAG) platform intended to replace the core RAGFlow experience while keeping the scope intentionally focused.

This repository currently tracks the implementation plan and progress for building:
- DeepDoc-based document parsing and OCR
- Template-based chunking (General / Laws / Paper)
- Hybrid retrieval (BM25 + vector search) using OpenSearch
- Chat with streaming responses and citation-backed answers
- A lightweight web UI for knowledge bases, documents, and chat

## Goals
- Provide a production-oriented, fully self-hosted RAG system.
- Preserve parity with **RAGFlow core** functionality for ingestion → chunking → retrieval → chat.
- Support **multi-tenant isolation** across database, search index, and object storage.
- Make embeddings and LLM providers **pluggable** (local-first, optional cloud).

## Out of scope
The following are explicitly out of scope for this project:
- External connectors (S3, Confluence, Google Drive, etc.)
- Agent/tool orchestration and MCP
- Manual chunking template
- “Retrieval Test” UI page
- Alternative parsing stacks beyond DeepDoc (e.g. MinerU, Docling, TCADP)

## High-level architecture
- **Backend API**: FastAPI (Python)
- **Async workers**: Celery
- **Metadata DB**: PostgreSQL
- **Object storage**: MinIO (S3-compatible)
- **Queue / cache**: Redis
- **Search**: OpenSearch
- **Embeddings**: Local by default (e.g., Ollama / vLLM), optional OpenAI
- **LLM**: Local or cloud (configurable per tenant)
- **Frontend**: React (TypeScript)

## Repository structure
- `backend/`
  - `backend/app/` – API, services, models, tasks
  - `backend/tests/` – backend test suite
  - `backend/alembic/` – database migrations
- `frontend/` – React SPA
- `deepdoc/` – DeepDoc document parsing module
- `docker/` – Dockerfiles, nginx config and container entrypoint
- `docs/` – documentation
- `scripts/` – developer scripts

## Documentation
- [User guide](docs/user-guide.md): getting started, knowledge bases and templates, documents, chat, settings
- [API guide](docs/api.md): signing in, uploading, search and streaming chat; full reference at `/api/docs`
- [Troubleshooting and FAQ](docs/troubleshooting.md)
- [Deployment](docs/deployment.md) and [configuration reference](docs/configuration.md)

## Project status
Work in progress.

If you want to see what’s planned and what’s already done:
- Task list: `IMPLEMENTATION_TASKS.md`
- Requirements: `RAGFlow Replacement - Product Requirements Document (PRD).md`
- Progress tracker: `TASK_PROGRESS.md`

## Getting started

### Models
RagNex needs an LLM and an embedding model. The default is [Ollama](https://ollama.com)
on the same machine:

```bash
ollama pull llama3      # chat model (LLM_MODEL)
ollama pull bge-m3      # embedding model (EMBEDDING_MODEL, 1024 dimensions)
```

OpenAI-compatible endpoints (OpenAI, vLLM) work too; see `LLM_PROVIDER` and
`EMBEDDING_PROVIDER` in `.env.example`.

### Run it with Docker (production-style)

```bash
cp .env.prod.example .env.prod          # fill in the five required secrets
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Open http://localhost:8080 (or `RAGNEX_HTTP_PORT`). This starts:

| Service | Role |
|---|---|
| `frontend` | nginx: serves the web app and proxies `/api` to the API (the only published port) |
| `api` | FastAPI backend |
| `worker` | Celery worker: parses, embeds and indexes uploads; purges deleted documents |
| `migrate` | applies database migrations once, then exits; `api` and `worker` wait for it |
| `postgres`, `redis`, `opensearch`, `minio` | data stores, internal network only |

Images: `docker/backend.Dockerfile` (API, worker and migrations share one image; the
command picks the role: `api`, `worker` or `migrate`) and `docker/frontend.Dockerfile`.

Before exposing it beyond your machine, follow [docs/deployment.md](docs/deployment.md): TLS,
secrets and their rotation, backups, and a go-live checklist. Every setting is described in
[docs/configuration.md](docs/configuration.md).

Upgrading: `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
rebuilds the images and re-runs migrations before the API starts.

### Local development

Requirements: Python 3.13, Node 22, Docker.

```bash
# Data stores (Postgres, Redis, OpenSearch, MinIO) with published ports
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env          # then set JWT_SECRET and RAGNEX_ENCRYPTION_KEY; all settings: docs/configuration.md

# Backend: installs the exact versions in backend/uv.lock into the active venv; code is
# imported as `backend.app.*` from the repo root
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install uv
uv sync --project backend --active --locked --extra dev --extra deepdoc   # add --extra deepdoc-vision for OCR
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:create_app --factory --reload           # API on :8000
celery -A backend.app.core.celery_app.celery_app worker -Q default,parsing,embedding,indexing --loglevel=info

# Frontend (Vite proxies /api to :8000)
cd frontend && npm ci && npm run dev                                       # http://localhost:5173
```

Run all commands from the repo root unless noted. On Windows, add `--pool=solo` to the
Celery command.

### Tests

```bash
cd backend && python -m pytest       # needs the dev data stores; end-to-end tests skip without them
cd frontend && npm test -- --run     # npm test alone starts watch mode

# Coverage (configured in backend/pyproject.toml and frontend/vitest.config.ts)
cd backend && python -m pytest --cov
cd frontend && npm test -- --run --coverage
```

### CI and dependencies

GitHub Actions (`.github/workflows/ci.yml`) runs the backend tests against real Postgres,
Redis, OpenSearch and MinIO, the DeepDoc tests, and the frontend tests and build, on every
pull request and push. Pushes to `master` and version tags then publish both images to
`ghcr.io` ([prebuilt images](docs/deployment.md#prebuilt-images)).

Dependency versions are pinned: `backend/uv.lock` for Python, `frontend/package-lock.json`
for the web app. To add or upgrade a Python dependency, edit `backend/pyproject.toml`, then
run `uv lock` in `backend/` (`uv lock --upgrade-package NAME` to move one package to its
newest version) and commit both files. CI fails if the lockfile doesn't match.

### Maintenance
- `python -m backend.app.services.accounts create-user EMAIL [--workspace ID]`: creates an
  account, for when sign-up is turned off (`REGISTRATION_ENABLED=false`).
- `python -m backend.app.services.deletion_backfill`: purges data left behind by deletions
  made before deletion purging existed. Dry run by default; `--execute` applies it.

## License
RagNex is licensed under the [MIT License](LICENSE).

The `deepdoc/` directory is derived from RAGFlow's DeepDoc and remains under the
[Apache License 2.0](deepdoc/LICENSE). [NOTICE](NOTICE) has the details.
