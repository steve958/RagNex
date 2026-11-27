# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Common commands

All commands assume you are in the backend repo root (this directory) unless stated otherwise.

### Python environment & dependencies

- Create virtualenv (PowerShell):
  - `python -m venv .venv`
  - `.\.venv\Scripts\Activate.ps1`
- Install base + dev dependencies:
  - `pip install -e .[dev]`
- To enable DeepDoc-based document parsing and OCR, install optional extras:
  - `pip install -e .[deepdoc,deepdoc-vision]`

Settings are loaded from `.env` in this directory via `app/core/config.py`. If `.env` is missing, defaults are used (Postgres, Redis, OpenSearch, MinIO on localhost).

### Database migrations (Alembic)

Alembic is configured via `alembic.ini` and `alembic/` with async migrations bound to the app settings.

- Upgrade to latest schema (used implicitly by tests as well):
  - `alembic upgrade head`
- Create a new migration after model changes:
  - `alembic revision --autogenerate -m "describe change"`

> Note: `alembic/env.py` expects the `backend` package to be importable (it inserts the repo root into `sys.path` and then imports `backend.app.*`). If you run Alembic from a different working directory, ensure that the directory containing this backend repo is on `PYTHONPATH` or that the project is installed as a package.

### Running the API server (FastAPI / Uvicorn)

The ASGI app factory lives in `app/main.py` (`create_app()`). For local development via Uvicorn:

- From the monorepo root where this repo is importable as the `backend` package (i.e., `backend/app/main.py` is on `PYTHONPATH` under the name `backend`), run:
  - `python -m uvicorn backend.app.main:create_app --factory --reload`

This ensures Uvicorn uses the `create_app` factory and that imports like `backend.app.api.router` work.

If you run from this backend directory directly and the `backend` package is not importable, commands that rely on `backend.app.*` will fail; in that case, add the monorepo root to `PYTHONPATH` or install the project in editable mode.

### Background workers (Celery)

Celery is configured in `app/core/celery_app.py` to use Redis as both broker and result backend.

- Start a worker for all queues (default, parsing, embedding, indexing):
  - `celery -A backend.app.core.celery_app.celery_app worker -Q default,parsing,embedding,indexing --loglevel=info`

There is no eager mode: tasks call `asyncio.run()`, which fails inside the API's event loop, so run a worker (or call a task directly; see `docs/development.md`, Debugging).

### Running tests (pytest)

Tests live under `tests/` and use async FastAPI clients and the real Postgres schema.

- Run full test suite:
  - `pytest`
- Run a single test file:
  - `pytest tests/test_documents.py`
- Run a single test function (example):
  - `pytest tests/test_documents.py::test_upload_document_creates_row_and_enqueues`

Test startup (`tests/conftest.py`) automatically applies Alembic migrations to the database configured in `Settings.database_url` by running `alembic upgrade head` programmatically. Ensure that Postgres is reachable and that the URL in `.env` (or the default) points to a writable database.

### Linting, formatting, type-checking

Configured in `pyproject.toml`:

- Ruff (lint):
  - `ruff check app tests`
- Black (format):
  - `black app tests`
- Mypy (type checking):
  - `mypy app`

Adjust targets as needed if you add new top-level packages.

## High-level architecture

### Overview

This backend is an async FastAPI service with:

- Multi-tenant user/KB model on Postgres (SQLAlchemy + Alembic)
- Document storage on S3-compatible object storage (MinIO)
- Vector + BM25 search on OpenSearch (k-NN plugin)
- Background processing via Celery (Redis broker/backend)
- Embeddings via Ollama/OpenAI/vLLM through an `EmbeddingService` abstraction
- DeepDoc-based document parsing and normalization before chunking

Key directories:

- `app/api` – FastAPI routers and HTTP endpoints
- `app/core` – configuration, DB/session management, logging, middleware, rate limiting, security
- `app/models` – SQLAlchemy models (tenants, users, API keys, documents, chunks, knowledge bases, etc.)
- `app/services` – OpenSearch, embeddings, document parsing, chunking, caching, storage, and search orchestration
- `app/tasks` – Celery tasks for parsing, embedding, and indexing
- `alembic` – schema migrations, driven by `backend.app.models.Base`
- `tests` – async integration-style tests that exercise endpoints, storage, tasks, and search

### Request/response flow (FastAPI)

- The application factory `create_app()` in `app/main.py` wires together:
  - Structlog-based logging (`app/core/logging.py`)
  - Middleware stack:
    - `RequestIdMiddleware` adds and propagates an `X-Request-ID` header and binds it into the structlog context.
    - `RequestLoggingMiddleware` logs every request with method/path/status/latency.
    - `TenantMiddleware` (in `app/core/tenant.py`) attaches tenant context from the `X-Tenant-ID` header.
    - Rate limiting via `setup_rate_limiting(app)` (`app/core/rate_limit.py`).
  - Root-level health endpoints from `app/api/v1/health.py`.
  - Versioned API router from `app/api/router.py`, mounted at `/api/v1`.
- Routers are grouped by domain under `app/api/v1/` (auth, API keys, tenants, tasks, documents, chunks, knowledge bases). They use dependency-injected DB sessions (`app/core/db.get_db`) and security helpers (`app/core/security.py`) for JWT/Bearer and API key auth.

### Persistence and tenancy

- `app/core/config.py` defines `Settings` (via `pydantic-settings`) and loads configuration from `.env` at repo root. It includes:
  - `database_url` (asyncpg DSN)
  - `redis_url`
  - `opensearch_*` settings
  - `embedding_*` defaults
  - S3/MinIO settings (`s3_endpoint_url`, access/secret keys, region, secure flag)
- `app/core/db.py` manages an async engine per event loop and yields `AsyncSession` instances, avoiding cross-loop connection reuse (important on Windows and under pytest where loops change).
- SQLAlchemy models under `app/models/` represent tenants, users, knowledge bases, documents, chunks, and related entities. `Base` is imported by Alembic in `alembic/env.py` and used for autogeneration.
- Alembic migrations under `alembic/versions/` evolve the schema; tests apply `upgrade head` before running.

### Document ingestion pipeline

The ingestion flow for a new document roughly looks like:

1. **Upload & validation**
   - `StorageService` in `app/services/storage.py` validates file extensions against `DEFAULT_ALLOWED_EXTENSIONS` and infers buckets per tenant (`tenant-<tenanthex>`).
   - Uploads are streamed to MinIO via the `minio` client, using multipart when size is unknown.
   - API endpoints in `app/api/v1/documents.py` call `StorageService.upload_file`, persist a `Document` row, and enqueue parsing tasks.

2. **Parsing to normalized sections**
   - `app/services/parsing.py` exposes `parse_document_binary` which uses the `deepdoc` stack to convert various filetypes (PDF, TXT, Markdown, HTML, JSON, DOCX, XLSX, etc.) into a normalized dict of `sections` and `tables`.
   - Parser behavior is controlled via an optional `parser_config` dict (e.g. OCR toggles, page ranges, chunk sizes, delimiters).
   - Unsupported extensions raise `ValueError`, which is surfaced by the API layer; tests assert on this behavior.

3. **Chunking and embeddings**
   - Chunking strategies live under `app/services/chunking/` (`general.py`, `laws.py`, `paper.py`), and are used to turn parsed sections into semantically meaningful chunks.
   - `app/services/embeddings.py` defines an `EmbeddingService` abstraction with concrete implementations for:
     - Ollama (`/api/embeddings`)
     - OpenAI-compatible endpoints (`/v1/embeddings`)
     - vLLM (OpenAI-compatible, but requires `vllm_base_url`)
   - Embeddings are cached via `CacheService` (Redis), with per-text cache keys incorporating provider/model and TTL from settings.

4. **Indexing into OpenSearch**
   - `OpenSearchService` in `app/services/opensearch.py` manages:
     - Index naming per tenant (`chunks_<tenanthex>` alias + backing index `chunks_<tenanthex>_v{schema}-000001`).
     - ISM lifecycle policies for rollover and retention, configured from settings.
     - Index templates for chunk documents including k-NN vector mappings.
   - `app/tasks/indexing.py` defines the `index_document` Celery task which:
     - Loads the document and associated chunks for a tenant.
     - Derives per-tenant `EmbeddingConfig` from DB (falling back to server defaults).
     - Embeds chunk texts (using cache and rate limiting).
     - Bulk indexes chunks into the tenant’s OpenSearch index (BM25 + vector fields).
     - Updates document status/progress and handles retries/failures with exponential backoff.

### Search pipeline

- `SearchService` in `app/services/search.py` performs hybrid retrieval:
  - Ensures the tenant’s chunk index exists via `OpenSearchService.ensure_index`.
  - Embeds the user query using the same `EmbeddingService` abstraction and validates embedding dimensions against `Settings.embedding_dimension`.
  - Performs two OpenSearch queries:
    - BM25 query on `content` with tenant + KB filters.
    - k-NN vector search on `content_vector` with the same filters.
  - Converts results into `SearchHit` dataclasses and fuses rankings using reciprocal rank fusion (RRF) with configurable weights and cutoffs.
  - Returns the top-k fused hits with scores and provenance (`bm25`, `vector`, `hybrid`).

### Background tasks (Celery)

- `app/core/celery_app.py` defines a `Celery` instance named `celery_app` with:
  - Redis broker/backend from `Settings.redis_url`.
  - Named queues: `default`, `parsing`, `embedding`, `indexing` with priority support.
  - Task routing configured by name prefix (e.g. `backend.app.tasks.parsing.*` → `parsing` queue).
  - Eager mode flags sourced from settings for local/dev usage.
- Tasks under `app/tasks/` include:
  - `parsing.py` – parse uploaded documents into normalized sections and persist chunks.
  - `embedding.py` – embedding-related background work (if separated from indexing).
  - `indexing.py` – bulk index chunks into OpenSearch as described above.

### Testing strategy

- Tests under `tests/` are primarily async and integration-focused:
  - Use `httpx.AsyncClient` with `ASGITransport` against `create_app()` to hit real FastAPI routes without running Uvicorn.
  - Use real DB connections via `get_engine()` and async sessions to assert on persisted state.
  - Mock external integrations (MinIO uploads, Celery `.apply_async`) where appropriate, while exercising the surrounding logic.
- `tests/conftest.py` calls Alembic’s `upgrade head` once per session to ensure the test database schema matches the current models.

When modifying core flows (auth, documents, chunking, embeddings, search, tasks), prefer to mirror existing test patterns in `tests/` and extend them to cover new behaviors.