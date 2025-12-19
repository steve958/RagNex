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
- `deepdoc/` – DeepDoc extraction/standalone module (to be added)
- `docker/` – Docker-related configs
- `docs/` – documentation
- `scripts/` – developer scripts

## Project status
Work in progress.

If you want to see what’s planned and what’s already done:
- Task list: `IMPLEMENTATION_TASKS.md`
- Requirements: `RAGFlow Replacement - Product Requirements Document (PRD).md`
- Progress tracker: `TASK_PROGRESS.md`

## Getting started
This will be filled in as Phase 0 continues (dev environment + compose + env files).

## License
TBD (will be decided before the first public release).
