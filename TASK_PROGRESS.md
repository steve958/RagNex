# RAGFlow Replacement — Task Progress Tracker
Source of truth: `IMPLEMENTATION_TASKS.md`
Last updated: 2025-12-18T11:54:36Z

## How to use
- Mark items complete by changing `[ ]` to `[x]`.
- Add dates/notes under each task when helpful.
- Keep this file focused on status (implementation progress), not design.

---

## Phase 0: Project Setup

### P0-1: Repository Initialization (git tasks ignored for now)
- [ ] Create new Git repository with proper `.gitignore` (ignored)
- [ ] Set up branch protection rules (ignored)
- [ ] Configure PR templates and issue templates (ignored)
- [x] Initialize project structure
  - [x] Create `backend/` folder
  - [x] Create `backend/app/` folder
    - [x] Create `backend/app/api/`
    - [x] Create `backend/app/core/`
    - [x] Create `backend/app/models/`
    - [x] Create `backend/app/services/`
    - [x] Create `backend/app/tasks/`
  - [x] Create `backend/tests/`
  - [x] Create `backend/alembic/`
  - [x] Create `frontend/` folder
    - [x] Create `frontend/src/`
    - [x] Create `frontend/public/`
  - [x] Create `deepdoc/`
  - [x] Create `docker/`
  - [x] Create `docs/`
  - [x] Create `scripts/`
- [x] Create initial README.md with project overview
- [ ] Set up pre-commit hooks (ruff, black, mypy; eslint, prettier)

Notes:
- 2025-12-17: Created initial directory structure only.
- 2025-12-17: Added `README.md` project overview.

### P0-2: Development Environment Setup
- [x] Create `docker-compose.dev.yml` for local development
  - [x] PostgreSQL 15+
  - [x] Elasticsearch 8.x / OpenSearch 2.x
  - [x] Redis 7+
  - [x] MinIO
- [x] Write environment setup scripts
  - [x] `scripts/setup-dev.ps1` (Windows)
  - [x] `scripts/setup-dev.sh` (Linux/Mac)
- [x] Create `.env.example` with all required variables
- [x] Document environment variable descriptions
  - [x] `docs/environment.md`
- [x] Set up Python virtual environment (repo root: `.venv`, Python 3.13)
  - [x] Create `backend/pyproject.toml` dependencies manifest
- [x] Create frontend `package.json` with dependencies
- [x] Smoke-test `docker compose up -d` brings up dev services successfully
- [ ] Backend connects to all services successfully (pending backend implementation)
- [ ] Frontend dev server starts without errors (pending frontend implementation)

Notes:
- 2025-12-17: Added `docker-compose.dev.yml`, `.env.example`, setup scripts, `backend/pyproject.toml`, `frontend/package.json`, and `docs/environment.md`.
- 2025-12-17: Created repo-root `.venv` using Python 3.13.
- 2025-12-17: Verified Postgres/Redis/MinIO/OpenSearch/OpenSearch Dashboards start via Docker Compose.
- 2025-12-17: OpenSearch requires `OPENSEARCH_INITIAL_ADMIN_PASSWORD` at startup; added to `docker-compose.dev.yml` and `.env.example`.
- 2025-12-17: `scripts/setup-dev.ps1` may require `-ExecutionPolicy Bypass` on systems with script execution disabled.
### P0-3: CI/CD Pipeline Setup (aborted for now)
- [ ] Configure CI (aborted)
  - [ ] Lint check (ruff, eslint) (aborted)
  - [ ] Type check (mypy, tsc) (aborted)
  - [ ] Unit tests (pytest, jest) (aborted)
  - [ ] Build verification (aborted)
- [ ] Set up test coverage reporting (Codecov/SonarQube) (aborted)
- [ ] Create Docker build workflow (aborted)
- [ ] Configure staging deployment pipeline (optional) (aborted)
- [ ] Set up dependency vulnerability scanning (Dependabot/Snyk) (aborted)

Notes:
- 2025-12-18: Aborted Phase P0-3 (CI/CD) to focus on core functionality first.

### P0-4: DeepDoc Module Extraction
- [x] Extract DeepDoc from RAGFlow repository
  - [x] `deepdoc/parser/` - All parser implementations
  - [x] `deepdoc/vision/` - OCR and layout models
- [x] Identify and extract dependencies
  - [x] Model weights locations
  - [x] Required Python packages
- [x] Create standalone DeepDoc package structure
- [x] Write unit tests for each parser
- [x] Document parser interfaces and configurations

Notes:
- 2025-12-18: Copied DeepDoc from local ragflow checkout into this repo (`deepdoc/`).
- 2025-12-18: Removed ragflow-only imports by adding `deepdoc/common` + `deepdoc/nlp` shims and making optional parsers import-safe.
- 2025-12-18: Replaced ragflow-heavy `pdf_parser.py` with a standalone `pypdf`-based parser with optional OCR fallback.
- 2025-12-18: Added pytest smoke tests under `deepdoc/tests/` (parsers + OCR import) and verified: `10 passed`.

---

## Phase 1: Core Infrastructure

### P1-1: Database Schema Design & Implementation
- [x] Design PostgreSQL schema based on PRD data models
- [x] Create SQLAlchemy ORM models
- [x] Create all model files
  - [x] `backend/app/models/user.py` - User, TenantMembership
  - [x] `backend/app/models/tenant.py` - Tenant
  - [x] `backend/app/models/knowledge_base.py` - KnowledgeBase
  - [x] `backend/app/models/document.py` - Document, Chunk
  - [x] `backend/app/models/chat.py` - ChatSession, ChatMessage
  - [x] `backend/app/models/api_key.py` - APIKey
- [x] Set up Alembic for migrations
- [x] Create initial migration
- [x] Add database indexes for common queries
- [x] Implement soft delete for critical entities

Notes:
- 2025-12-18: Added async SQLAlchemy setup (`backend/app/core/db.py`) and settings loader (`backend/app/core/config.py`).
- 2025-12-18: Implemented initial ORM models + relationships and created initial Alembic revision `0001_initial_schema.py`.
- 2025-12-18: Applied migrations successfully against local Postgres via `alembic upgrade head`.
- 2025-12-18: Verified `downgrade base` + `upgrade head` cycle passes cleanly.

### P1-2: Authentication & Authorization System
- [x] Implement password hashing (argon2/bcrypt)
- [x] Create JWT token service
- [x] Implement authentication endpoints
  - [x] `POST /api/v1/auth/register`
  - [x] `POST /api/v1/auth/login`
  - [x] `POST /api/v1/auth/logout` (stateless/no-op)
  - [x] `POST /api/v1/auth/refresh`
  - [x] `GET /api/v1/auth/me`
- [x] Create FastAPI dependency for auth (`get_current_user`)
- [x] Implement API key authentication
  - [x] Generate secure API keys
  - [x] Hash keys before storage
  - [x] Key scoping (read/write permissions)
- [x] Add rate limiting middleware (slowapi)
- [x] Implement tenant context injection

Notes:
- 2025-12-18: Added FastAPI app (`backend/app/main.py`) + routers (`/api/v1/auth/*`, `/api/v1/api-keys*`).
- 2025-12-18: Implemented JWT access/refresh tokens + argon2 password hashing + basic tenant middleware (`X-Tenant-ID`).
- 2025-12-18: Added slowapi rate limiting on auth endpoints (register/login/refresh).
- 2025-12-18: Added API key creation/list/revoke (stores SHA-256 hash only) + API-key auth support in `get_current_user`.
- 2025-12-18: Added basic integration test `backend/tests/test_auth.py`; verified full test suite passes (`11 passed`).

### P1-3: Multi-Tenancy Implementation
- [x] Design tenant isolation strategy
  - [x] Database: tenant_id on all tenant-scoped tables
  - [x] Elasticsearch: index-per-tenant or filtered alias (planned; implemented later with P3-1)
  - [x] MinIO: bucket-per-tenant or prefix isolation (planned; implemented later with P1-4)
- [x] Create tenant management endpoints
  - [x] `POST /api/v1/tenants`
  - [x] `GET /api/v1/tenants`
  - [x] `GET /api/v1/tenants/{id}`
  - [x] `PUT /api/v1/tenants/{id}`
  - [x] `DELETE /api/v1/tenants/{id}`
- [x] Implement tenant membership endpoints
  - [x] `POST /api/v1/tenants/{id}/members`
  - [x] `DELETE /api/v1/tenants/{id}/members/{user_id}`
  - [x] `PUT /api/v1/tenants/{id}/members/{user_id}`
- [x] Create tenant context middleware
- [x] Add tenant filtering to all queries
- [x] Test cross-tenant data isolation

Notes:
- 2025-12-18: Added tenant CRUD + membership endpoints (`backend/app/api/v1/tenants.py`).
- 2025-12-18: Enforced membership checks on tenant operations (403 on cross-tenant access).
- 2025-12-18: Added test `backend/tests/test_tenants.py`; verified full test suite passes (`12 passed`).

### P1-4: MinIO Storage Service
- [x] Create MinIO client wrapper
- [x] Implement bucket-per-tenant strategy
- [x] Add file type validation
- [x] Implement chunked upload for large files
- [x] Add cleanup job for orphaned files
- [x] Create storage usage tracking per tenant

Notes:
- 2025-12-18: Implemented `StorageService` in `backend/app/services/storage.py` (upload/download/delete/presign, per-tenant buckets).
- 2025-12-18: Added unit tests in `backend/tests/test_storage.py` and an optional MinIO integration smoke test (run with `RUN_MINIO_TESTS=1`).
- 2025-12-18: Verified test suite passes (`15 passed, 1 skipped`).

### P1-5: Redis Caching & Queue Setup
- [x] Create Redis client wrapper with connection pooling
- [x] Implement caching service (CacheService)
- [x] Set up Celery with Redis broker
- [x] Configure task queues
  - [x] `parsing`
  - [x] `embedding`
  - [x] `indexing`
  - [x] `default`
- [x] Add task result tracking
- [x] Implement task priority system

Notes:
- 2025-12-18: Added Redis async client wrapper (`backend/app/core/redis_client.py`) + `CacheService` (`backend/app/services/cache.py`) with unit tests + optional Redis integration test (run with `RUN_REDIS_TESTS=1`).
- 2025-12-18: Added Celery app config (`backend/app/core/celery_app.py`) using Redis as broker/result backend, with named queues and priority support.
- 2025-12-18: Added placeholder task modules under `backend/app/tasks/` and a task status API endpoint `GET /api/v1/tasks/{task_id}` (unit-tested).
- 2025-12-18: Verified backend test suite passes: `8 passed, 2 skipped` (skips: MinIO + Redis integration unless enabled).

### P1-6: Logging & Monitoring Setup
- [x] Configure structured logging (JSON)
- [x] Add request ID tracking middleware
- [x] Create health check endpoints
  - [x] `GET /health`
  - [x] `GET /health/ready`
  - [x] `GET /health/detailed`
- [ ] Set up Prometheus metrics (ignored)
- [ ] Create Grafana dashboard templates (ignored)
- [ ] Add error tracking (Sentry integration optional) (ignored)

Notes:
- 2025-12-18: Added JSON structured logging via `structlog` (`backend/app/core/logging.py`) + request-id and request logging middleware (`backend/app/core/middleware.py`).
- 2025-12-18: Added root-level health endpoints (`backend/app/api/v1/health.py`) and wired in `backend/app/main.py`.
- 2025-12-18: User requested ignoring Prometheus/Grafana/Sentry tasks for now; no metrics exporter added.
- 2025-12-18: Verified backend test suite passes: `11 passed, 2 skipped`.

---

## Phase 2: Document Processing Pipeline

### P2-1: Document Upload API
- [x] Create document upload endpoint
- [x] Implement file validation
  - [x] Allowed extensions
  - [x] Max file size check
  - [ ] MIME type verification (best-effort only for now)
- [x] Store file metadata in PostgreSQL
- [x] Upload file binary to MinIO
- [x] Queue parsing task
- [x] Return document with status "pending"

Notes:
- 2025-12-18: Added `POST /api/v1/knowledgebases/{kb_id}/documents` (stores Document metadata, uploads to MinIO, enqueues Celery parsing task).
- 2025-12-18: Added `max_upload_size_mb` setting (default 100MB) in `backend/app/core/config.py`.
- 2025-12-18: Added tests `backend/tests/test_documents.py` (MinIO + Celery patched); verified backend test suite passes: `13 passed, 2 skipped`.

### P2-2: Parsing Task Executor
- [x] Create Celery task for document parsing
- [x] Implement progress callback system
- [x] Route to appropriate parser based on file type
- [x] Handle parser errors gracefully
  - [x] Retry logic with exponential backoff
  - [x] Max retries before marking failed
  - [x] Error message capture
- [x] Update document status on completion
- [x] Emit parsing complete event

Notes:
- 2025-12-18: Replaced placeholder parsing task with real Celery task `backend/app/tasks/parsing.py::parse_document` (downloads from MinIO, parses via DeepDoc router, stores result, updates status/progress).
- 2025-12-18: Added normalized parsing router `backend/app/services/parsing.py` and persisted output on `documents.parsed_data`.
- 2025-12-18: Added DB fields + Alembic migration `0002_document_parsing_fields.py` (progress, messages, parsed_data, task id, timestamps).
- 2025-12-18: Added `GET /api/v1/documents/{doc_id}` to query parse progress/status.
- 2025-12-18: Verified backend test suite passes: `14 passed, 2 skipped`.

### P2-3: General Template Chunking (naive.py port)
- [x] Port `naive_merge`
- [x] Port `tokenize_chunks`
- [x] Port table tokenization logic
- [ ] Implement image handling (optional vision enhancement)
- [x] Support all file formats
  - [x] PDF (DeepDoc)
  - [x] DOCX (python-docx + DeepDoc tables)
  - [x] Excel (pandas/openpyxl)
  - [x] TXT/MD/HTML/JSON
- [x] Create chunking configuration schema
- [x] Write comprehensive unit tests
- [ ] Validate output matches RAGFlow behavior (parity tests deferred)

Notes:
- 2025-12-18: Added `backend/app/services/chunking/general.py` implementing `GeneralChunkConfig`, `naive_merge`, `tokenize_chunks`, and HTML table splitting.
- 2025-12-18: Added unit tests `backend/tests/test_chunking_general.py`; verified backend test suite passes: `19 passed, 2 skipped`.

### P2-4: Laws Template Chunking (laws.py port)
- [x] Port `bullets_category`
- [x] Port `remove_contents_table`
- [x] Port `make_colon_as_title`
- [x] Port `tree_merge`
- [x] Port `Node` class
- [x] Port `docx_question_level` for DOCX heading detection
- [x] Support formats: DOCX, PDF, TXT, MD, HTML
- [x] Create configuration schema
- [x] Write unit tests with legal document samples

Notes:
- 2025-12-18: Added `backend/app/services/chunking/laws.py` implementing hierarchical laws chunking (`LawsChunkConfig`, tree-based merging, TOC removal, colon-title handling).
- 2025-12-18: Added unit tests `backend/tests/test_chunking_laws.py`; verified backend test suite passes: `24 passed, 2 skipped`.

### P2-5: Paper Template Chunking (paper.py port)
- [x] Port Paper PDF parser behavior (heuristic)
- [x] Port title/author extraction logic (heuristic)
- [x] Port abstract detection (heuristic)
- [ ] Port two-column layout handling (deferred; requires layout/position-aware extraction)
- [ ] Port `title_frequency` for section pivot detection (deferred)
- [ ] Port figure/table extraction with vision enhancement (deferred)
- [x] PDF-only format enforcement
- [x] Create configuration schema
- [x] Write unit tests with academic paper PDFs (synthetic fixtures)

Notes:
- 2025-12-18: Added `backend/app/services/chunking/paper.py` implementing `PaperChunkConfig` and `chunk_paper_document` (extracts title/authors/abstract/sections and ensures abstract is a single chunk).
- 2025-12-18: Added unit tests `backend/tests/test_chunking_paper.py`; verified backend test suite passes: `26 passed, 2 skipped`.

### P2-6: Chunk Storage & Management
- [x] Create chunk storage service (ChunkService)
- [x] Store chunks in PostgreSQL with required metadata
- [x] Create chunk API endpoints
  - [x] `GET /api/v1/documents/{doc_id}/chunks`
  - [x] `GET /api/v1/chunks/{chunk_id}`
- [x] Implement chunk pagination
- [x] Add chunk search within document

Notes:
- 2025-12-18: Added `ChunkService` (`backend/app/services/chunks.py`) and chunk endpoints (`backend/app/api/v1/chunks.py`).
- 2025-12-18: Integrated chunk creation into parsing task (selects KB template and stores chunks in DB).
- 2025-12-18: Extended parsing task test to validate chunks persisted + API pagination/search; verified backend test suite passes: `26 passed, 2 skipped`.

---

## Phase 3: Search & Retrieval

### P3-1: Elasticsearch Index Setup
- [x] Create index template
- [x] Implement index-per-tenant strategy
- [ ] Create index lifecycle management (deferred)
- [x] Add index health monitoring
- [ ] Implement index migration utilities (deferred)

Notes:
- 2025-12-18: Added OpenSearch service `backend/app/services/opensearch.py` (composable template + index-per-tenant naming `chunks_<tenant_uuidhex>`).
- 2025-12-18: Wired tenant creation to ensure the tenant index exists (best-effort).
- 2025-12-18: Added unit tests `backend/tests/test_opensearch.py`; verified backend test suite passes: `28 passed, 2 skipped`.

### P3-2: Embedding Service Integration
- [x] Create embedding service abstraction
- [x] Implement Ollama provider
- [x] Implement vLLM provider
- [x] Implement OpenAI provider
- [x] Add batch processing with rate limiting
- [x] Create embedding configuration per tenant
- [x] Cache embeddings for duplicate content

Notes:
- 2025-12-18: Added embedding service abstraction + providers (Ollama/OpenAI/vLLM/OpenAI-compatible), with batch support + rate limiting and Redis caching.
- 2025-12-18: Verified backend test suite passes: `31 passed, 2 skipped`.

### P3-3: Chunk Indexing Pipeline
- [x] Create indexing Celery task
- [x] Implement bulk indexing
- [x] Generate embeddings for chunk content
- [x] Store vectors in Elasticsearch
- [x] Update document status after indexing
- [x] Handle partial failures (retry failed chunks)

Notes:
- 2025-12-18: Implemented `backend/app/tasks/indexing.py::index_document` (loads chunks, embeds with cache, bulk indexes into tenant OpenSearch index, updates document index progress/status, retries on failure).
- 2025-12-18: Wired parsing task to enqueue indexing after chunk persistence.
- 2025-12-18: Added unit test `backend/tests/test_indexing_task.py`; verified backend test suite passes: `32 passed, 2 skipped`.

### P3-4: Hybrid Search Implementation
- [x] Create search service
- [x] Implement vector search (kNN)
- [x] Implement keyword search (BM25)
- [x] Implement hybrid fusion
- [x] Add knowledge base filtering
- [x] Create search API endpoint
  - [x] `POST /api/v1/knowledgebases/{kb_id}/search`

Notes:
- 2025-12-18: Added `backend/app/services/search.py` (BM25 + kNN + RRF hybrid fusion) scoped by tenant + knowledge base.
- 2025-12-18: Added endpoint `backend/app/api/v1/knowledgebases.py` and registered router.
- 2025-12-18: Added tests `backend/tests/test_search.py`; verified backend test suite passes: `34 passed, 2 skipped`.

### P3-5: Re-ranking Integration (skipped for v1)
- [ ] Create re-ranker abstraction (skipped)
- [ ] Implement cross-encoder re-ranker (optional, skipped)
- [ ] Implement Cohere re-ranker (optional, skipped)
- [ ] Add re-ranking configuration (skipped)
- [ ] Integrate into search pipeline (skipped)

Notes:
- 2026-01-15: Explicitly decided to skip P3-5 re-ranking for the initial release; hybrid BM25 + vector search from P3-4 is considered sufficient.

---

## Phase 4: LLM & Chat Integration

### P4-1: LLM Provider Abstraction
- [x] Create LLM service interface
- [ ] Implement providers using LiteLLM (deferred; using direct HTTP clients for now)
- [x] Support models
- [x] Ollama
- [x] vLLM
- [x] OpenAI
- [ ] Anthropic
- [ ] DeepSeek
- [ ] Create LLM configuration per tenant
- [ ] Add token counting and limit enforcement

Notes:
- 2026-01-15: Added `backend/app/services/llm.py` with `LLMService` abstraction, `OllamaLLM` and `OpenAICompatibleLLM`, plus `LLMConfig`/`LLMMessage`/`LLMResult` and a `create_llm_service` factory.
- 2026-01-15: Introduced LLM defaults in `backend/app/core/config.py` (`llm_provider`, `llm_model`, `llm_temperature`, `llm_max_tokens`) and a `default_llm_config()` helper.
- 2026-01-15: LiteLLM integration and per-tenant LLM configuration remain TODOs for a follow-up task.

### P4-2: Chat Session Management
- [x] Create chat session endpoints
- [x] `POST /api/v1/chat/sessions`
- [x] `GET /api/v1/chat/sessions`
- [x] `GET /api/v1/chat/sessions/{id}`
- [x] `DELETE /api/v1/chat/sessions/{id}`
- [x] Implement session configuration
- [x] Store session metadata in PostgreSQL
- [ ] Implement session sharing (optional)

Notes:
- 2026-01-15: Added `backend/app/api/v1/chat.py` with chat session CRUD endpoints scoped by tenant (`X-Tenant-ID`) and current user, plus KB associations via `chat_session_knowledge_bases`.
- 2026-01-15: Added tests `backend/tests/test_chat_sessions.py` covering session create/list/get/delete and validation when referencing unknown knowledge base IDs.

### P4-3: RAG Chat Pipeline
- [x] Create chat message endpoint
- [x] Implement RAG pipeline (search -> context -> prompt -> stream)
- [x] Implement citation extraction
- [x] Store messages with citations
- [x] Support conversation history context

Notes:
- 2026-01-15: Added `POST /api/v1/chat/sessions/{session_id}/messages` in `backend/app/api/v1/chat.py`, which performs hybrid search via `SearchService`, builds context, calls the LLM abstraction, and stores both user and assistant messages with citations.
- 2026-01-15: Implemented simple citation extraction by attaching top search hits (`chunk_id`, `doc_id`, `kb_id`, `score`) to assistant messages; full text-level citation parsing can be added later.
- 2026-01-15: Added test `backend/tests/test_chat_messages.py` with patched search + LLM to exercise the RAG pipeline end-to-end without external services.
- 2026-11-26: Fixed the new user message being sent to the LLM twice.
- 2026-11-26: Added streaming: `POST /api/v1/chat/sessions/{id}/messages/stream` (SSE events `meta` → `delta`* → `done`, or `error`). Native streaming in `OllamaLLM` (NDJSON) and `OpenAICompatibleLLM` (SSE). Shared turn setup in `_prepare_turn`. The user message is committed before streaming; on generation failure no assistant message is saved. Frontend `ChatPage` renders tokens live via `streamChatMessage` (fetch + `SseParser`). Verified end-to-end against Ollama `gemma2:2b`, directly and through the Vite proxy.
- 2026-11-26: Fixed `OpenSearchService.ensure_chunks_policy` failing with 409 once the ISM policy exists (it runs on every search and indexing call).
- 2026-11-26: Frontend now sends `X-Tenant-ID` (resolved after login), the backend has CORS, and Vite proxies `/api` in dev. Before this, tenant-scoped calls from the UI could not succeed.
- 2026-11-26: Streamed answers now run in a background task and are saved even if the client disconnects. Answers still being generated when the server restarts are lost.
- 2026-11-26: Multi-KB chat. `SearchService.search` takes `kb_ids`, and a session searches all of its live knowledge bases in one query (`terms` filter on the tenant index), ranked together. Previously it searched only an arbitrary first one. The chat page creates sessions over any checked KBs and shows KB names. Tests: `backend/tests/test_multi_kb.py` (real stack).

### P4-4: Message History & Context Management
- [x] Create message history endpoints
- [x] `GET /api/v1/chat/sessions/{id}/messages`
- [x] Implement context window management
- [ ] Add message summarization for long conversations
- [x] Implement message pagination
- [x] Add message metadata (timestamps, token counts)

Notes:
- 2026-01-15: Added `GET /api/v1/chat/sessions/{session_id}/messages` in `backend/app/api/v1/chat.py` with offset/limit pagination, scoped to the current tenant and user.
- 2026-01-15: Each history item now includes a naive `token_estimate` alongside role/content/citations/timestamps, to support future context window management.
- 2026-01-15: Context window trimming and true summarization are deferred; current RAG pipeline uses full per-session history.
- 2026-11-26: Added `backend/app/services/prompt_budget.py`. Prompts fit `LLM_CONTEXT_WINDOW` (default 8192) minus `LLM_MAX_TOKENS`, using conservative token estimates and filling at most 90% of the window. Priority: system prompt and question, then retrieved chunks by rank, then the newest complete exchanges. Unanswered questions are left out of history. Citations list only the chunks actually sent. Ollama now receives `num_ctx`. Summarizing dropped history is still open.

---

## Phase 5: Web Frontend

### P5-1: Frontend Project Setup
- [x] Initialize React project with Vite
- [x] Set up project structure
- [x] Install core dependencies
- [x] Configure Tailwind CSS
- [x] Set up React Query provider
- [x] Create API client with interceptors
- [x] Set up routing structure
- [x] Create authentication context

Notes:
- 2026-01-15: Scaffolded `frontend/` as a Vite React+TS app with `index.html`, `tsconfig.json`, `vite.config.ts`, and `src/` structure (`components/`, `pages/`, `services/`, `store/`).
- 2026-01-15: Added React Router skeleton (`App.tsx`, layout header, Login/Register/Dashboard placeholder pages).
- 2026-01-15: Wired React Query provider and axios `apiClient` with `VITE_API_URL` base URL.
- 2026-01-15: Integrated Tailwind CSS (`tailwind.config.js`, `postcss.config.js`, `src/styles.css` with Tailwind directives).
- 2026-01-15: Added initial `AuthProvider` context stub (`src/store/auth.tsx`) to be completed in P5-2.

### P5-2: Authentication UI
- [x] Create Login page
- [x] Create Registration page
- [x] Implement auth store/context
- [x] Add protected route wrapper
- [x] Implement token refresh logic
- [x] Create user menu (profile email + logout)

Notes:
- 2026-01-15: Implemented `LoginPage` and `RegisterPage` with basic Tailwind-styled forms that call the backend `/api/v1/auth/login` and `/api/v1/auth/register` endpoints via the new auth store.
- 2026-01-15: Added `AuthProvider` in `frontend/src/store/auth.tsx` with localStorage persistence, integration with `apiClient` (Authorization header), and simple `login`/`register`/`logout` APIs.
- 2026-01-15: Introduced a `ProtectedRoute` wrapper in `App.tsx` so the dashboard is only accessible when authenticated.
- 2026-01-15: Updated `AppLayout` to show the current user's email and a Logout button instead of Login/Register when authenticated.
- 2026-01-15: Full token refresh flow (`/api/v1/auth/refresh` on expiry) is deferred to a later enhancement; current implementation expects the backend tokens to remain valid during a normal session.
- 2026-11-26: Token refresh on 401. `apiClient` refreshes and retries each request once, and concurrent failures share a single `/auth/refresh` call. A request sent with a token that's already been replaced retries without another refresh. Login, register and refresh are never retried. Streaming chat (`fetch`) gets the same handling. The auth store saves rotated tokens and logs out only if the refresh token is rejected, not on network errors. The handler is registered during render, so the first queries after a reload can refresh. Backend contract test in `test_auth.py`.

### P5-3: Knowledge Base Management UI
- [x] Create Knowledge Base list page
- [x] Create KB creation modal
- [x] Create KB detail page
- [x] Create KB settings page
- [x] Implement KB API hooks

Notes:
- 2026-01-15: Added `KnowledgeBaseList` and `KnowledgeBaseCreateModal` components on the dashboard, backed by React Query and new `kbApi` hooks for listing and creating KBs.
- 2026-01-15: Extended backend knowledge base router to support list/create/get/update/delete for KBs, in addition to the existing search endpoint.
- 2026-01-15: Implemented KB detail (`KnowledgeBaseDetailPage`) and settings (`KnowledgeBaseSettingsPage`) pages with routing and React Query hooks for viewing, editing, and deleting knowledge bases.

### P5-4: Document Upload & Management UI
- [x] Create document upload component
- [x] Create document list component
- [x] Create document detail modal
- [x] Implement real-time status updates
- [x] Create document deletion with confirmation

### P5-5: Chunk Visualization UI
- [x] Create chunk list view
- [x] Create chunk detail modal
- [x] Add chunk search within document
- [x] Implement chunk highlighting in context

### P5-6: Chat Interface UI
- [x] Create chat layout
- [x] Create session list component
- [x] Create message component
- [x] Implement streaming message display
- [x] Create citation popup/modal
- [x] Add session configuration panel

### P5-7: Settings & Configuration UI
- [x] Create settings layout with tabs/sections
- [x] Create LLM configuration page
- [x] Create embedding configuration page
- [x] Create API key management page
- [x] Create team/tenant management page

### P5-8: Responsive Design & Polish
- [x] Implement responsive breakpoints
- [x] Create mobile navigation
- [x] Optimize chat UI for mobile
- [x] Add loading states and skeletons
- [x] Implement error boundaries
- [x] Add toast notifications
- [x] Create empty states for lists
- [x] Add keyboard shortcuts

---

## Phase 6: Integration & Testing

### P6-1: Unit Test Coverage
- [ ] Backend unit tests (target: 80% coverage)
- [x] Frontend unit tests
- [ ] DeepDoc parser tests
- [ ] Run coverage reports in CI

### P6-2: Integration Tests
- [ ] Create integration test fixtures
- [ ] Write API integration tests
- [ ] Write chunking parity tests
- [x] Create end-to-end test scenarios (upload → answer; more scenarios still to add)

Notes:
- 2026-11-26: Added `backend/tests/test_e2e_pipeline.py`. Through the HTTP API, it covers upload (real MinIO) → parse/chunk → embed/index (real OpenSearch) → hybrid search → streamed chat. It runs the real Celery task code in-process via `.apply()`. Only the embedding model (deterministic hashed bag-of-words) and the LLM are faked. It checks KB isolation, that the retrieved text reaches the prompt, and that citations resolve to real chunks. It auto-skips when OpenSearch/MinIO are unreachable and deletes its OpenSearch indices and MinIO bucket afterwards.
- 2026-11-26: The test found that `StorageService.upload_file` never wrote to MinIO: it returned an un-awaited coroutine, so every upload saved the DB row but no file, and parsing then failed with `NoSuchKey`. Fixed. The test also fails if the ISM 409 fix is reverted.
- 2026-11-26: Deletion works in two phases. Deleting a document or KB marks it deleted, and search, chunk, document and chat endpoints ignore it immediately. A `purge_document` Celery task (`app/tasks/purge.py`, default queue, retries) then removes its OpenSearch entries, chunk rows and MinIO file, and keeps the Document row as a record. Deleting a KB marks all its documents deleted. Parsing and indexing check for deletion before and after writing, so a document deleted mid-pipeline isn't written back. Chats whose KBs are all deleted keep readable history, but new questions get a 400 and the UI shows a banner. Tests: `backend/tests/test_deletion.py` (real stack).
- 2026-11-26: Backfill for deletions made before purging existed: `python -m backend.app.services.deletion_backfill`. It's a dry run by default; use `--execute` to apply, `--enqueue` to use Celery instead of running inline, and `--tenant-id` / `--limit` to scope a run. It marks documents of deleted KBs as deleted, then purges every deleted document that still has a file or chunk rows. Safe to re-run. Tests: `backend/tests/test_deletion_backfill.py`.
- 2026-11-26: Fixed Celery workers registering no tasks: `autodiscover_tasks` looked for a non-existent `backend.app.tasks.tasks` module. Task modules are now listed in `celery_app.conf.include`.

### P6-3: Performance Testing
- [ ] Create load test scripts (Locust/k6)
- [ ] Establish performance baselines
- [ ] Identify and fix bottlenecks
- [ ] Document performance characteristics

### P6-4: Security Testing
- [ ] Run SAST tools (Bandit, Semgrep)
- [ ] Test authentication
- [ ] Test authorization
- [ ] Test input validation
- [ ] Review secret management

---

## Phase 7: Deployment & Documentation

### P7-1: Docker Production Images
- [ ] Create production Dockerfiles
  - [ ] `Dockerfile.backend`
  - [ ] `Dockerfile.frontend`
  - [ ] `Dockerfile.worker`
- [ ] Optimize image sizes
- [ ] Create `docker-compose.prod.yml`
- [ ] Set up image registry
- [ ] Create image tagging strategy

### P7-2: Kubernetes Manifests
- [ ] Create Kubernetes manifests
- [ ] Create Helm chart (optional)
- [ ] Document resource requirements
- [ ] Add horizontal pod autoscaling

### P7-3: Configuration & Environment Documentation
- [ ] Document all environment variables
- [ ] Document secrets management
- [ ] Create deployment checklist

### P7-4: User Documentation
- [ ] Create getting started guide
- [ ] Document UI features
- [ ] Create API documentation
- [ ] Create FAQ section
- [ ] Create troubleshooting guide

### P7-5: Developer Documentation
- [ ] Document architecture overview
- [ ] Create contribution guide
- [ ] Document extending the system
- [ ] Create debugging guide
- [ ] Document release process
