# RagNex

RagNex is a self-hosted, multi-tenant Retrieval-Augmented Generation (RAG) platform intended to replace the core RAGFlow experience while keeping the scope intentionally focused.

This repository currently tracks the implementation plan and progress for building:
- DeepDoc-based document parsing and OCR
- Template-based chunking (General / Laws / Paper)
- Hybrid retrieval (BM25 + vector search) using Elasticsearch or OpenSearch
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
- **Search**: Elasticsearch or OpenSearch
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
cp .env.prod.example .env.prod          # fill in the four required secrets
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

Before exposing it beyond your machine:
- put TLS in front of the `frontend` port (a reverse proxy or load balancer);
- set `LLM_CONTEXT_WINDOW` to your chat model's real context size;
- keep `EMBEDDING_DIMENSION` matching the embedding model (changing it later requires reindexing).

Upgrading: `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
rebuilds the images and re-runs migrations before the API starts.

### Local development

Requirements: Python 3.13, Node 22, Docker.

```bash
# Data stores (Postgres, Redis, OpenSearch, MinIO) with published ports
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env

# Backend: installs dependencies only; code is imported as `backend.app.*` from the repo root
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -e "./backend[dev,deepdoc]"
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:create_app --factory --reload           # API on :8000
celery -A backend.app.core.celery_app.celery_app worker -Q default,parsing,embedding,indexing --loglevel=info

# Frontend (Vite proxies /api to :8000)
cd frontend && npm install && npm run dev                                  # http://localhost:5173
```

Run all commands from the repo root unless noted. On Windows, add `--pool=solo` to the
Celery command.

### Tests

```bash
cd backend && python -m pytest       # needs the dev data stores; end-to-end tests skip without them
cd frontend && npx vitest run
```

### Maintenance
- `python -m backend.app.services.deletion_backfill`: purges data left behind by deletions
  made before deletion purging existed. Dry run by default; `--execute` applies it.

## License
TBD (will be decided before the first public release).
