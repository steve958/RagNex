# RAGFlow Replacement - Implementation Tasks

> **Project**: RAGFlow Replacement System  
> **Version**: 1.0  
> **Last Updated**: 2025-12-17  
> **Status**: Planning

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Phase 0: Project Setup](#phase-0-project-setup)
3. [Phase 1: Core Infrastructure](#phase-1-core-infrastructure)
4. [Phase 2: Document Processing Pipeline](#phase-2-document-processing-pipeline)
5. [Phase 3: Search & Retrieval](#phase-3-search--retrieval)
6. [Phase 4: LLM & Chat Integration](#phase-4-llm--chat-integration)
7. [Phase 5: Web Frontend](#phase-5-web-frontend)
8. [Phase 6: Integration & Testing](#phase-6-integration--testing)
9. [Phase 7: Deployment & Documentation](#phase-7-deployment--documentation)
10. [Task Dependencies Graph](#task-dependencies-graph)
11. [Risk Register](#risk-register)

---

## Project Overview

### Timeline Estimate
| Phase | Duration | Parallel Work Possible |
|-------|----------|------------------------|
| Phase 0 | 1 week | No |
| Phase 1 | 2 weeks | Partial |
| Phase 2 | 3 weeks | Yes |
| Phase 3 | 2 weeks | Yes (with Phase 2) |
| Phase 4 | 2 weeks | Yes (with Phase 3) |
| Phase 5 | 3 weeks | Yes (with Phase 3-4) |
| Phase 6 | 2 weeks | No |
| Phase 7 | 1 week | Partial |
| **Total** | **~12-14 weeks** | |

### Team Structure Recommendation
- 2 Backend Engineers
- 1 Frontend Engineer
- 1 DevOps/Infrastructure Engineer
- 1 QA Engineer (part-time, joining Phase 6)

---

## Phase 0: Project Setup

### P0-1: Repository Initialization
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Lead Developer

#### Tasks
- [ ] Create new Git repository with proper `.gitignore`
- [ ] Set up branch protection rules (main, develop)
- [ ] Configure PR templates and issue templates
- [ ] Initialize project structure:
  ```
  project-root/
  ├── backend/
  │   ├── app/
  │   │   ├── api/
  │   │   ├── core/
  │   │   ├── models/
  │   │   ├── services/
  │   │   └── tasks/
  │   ├── tests/
  │   └── alembic/
  ├── frontend/
  │   ├── src/
  │   └── public/
  ├── deepdoc/
  ├── docker/
  ├── docs/
  └── scripts/
  ```
- [ ] Create initial README.md with project overview
- [ ] Set up pre-commit hooks (ruff, black, mypy for Python; eslint, prettier for JS)

#### Acceptance Criteria
- Repository accessible to all team members
- CI pipeline triggers on PR creation
- Pre-commit hooks pass locally

---

### P0-2: Development Environment Setup
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Create `docker-compose.dev.yml` for local development:
  - PostgreSQL 15+
  - Elasticsearch 8.x / OpenSearch 2.x
  - Redis 7+
  - MinIO
- [ ] Write environment setup scripts:
  - `scripts/setup-dev.ps1` (Windows)
  - `scripts/setup-dev.sh` (Linux/Mac)
- [ ] Create `.env.example` with all required variables
- [ ] Document environment variable descriptions
- [ ] Set up Python virtual environment with `uv`:
  ```toml
  # pyproject.toml dependencies
  [project]
  requires-python = ">=3.10"
  dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "asyncpg>=0.29.0",
    "redis>=5.0.0",
    "elasticsearch>=8.0.0",
    "celery>=5.3.0",
    "minio>=7.2.0",
    "pydantic>=2.5.0",
    "python-multipart>=0.0.6",
    "httpx>=0.26.0",
  ]
  ```
- [ ] Create frontend package.json with dependencies

#### Acceptance Criteria
- `docker compose up` starts all services
- Backend connects to all services successfully
- Frontend dev server starts without errors

---

### P0-3: CI/CD Pipeline Setup
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Configure GitHub Actions / GitLab CI:
  - Lint check (ruff, eslint)
  - Type check (mypy, tsc)
  - Unit tests (pytest, jest)
  - Build verification
- [ ] Set up test coverage reporting (Codecov/SonarQube)
- [ ] Create Docker build workflow
- [ ] Configure staging deployment pipeline (optional)
- [ ] Set up dependency vulnerability scanning (Dependabot/Snyk)

#### Acceptance Criteria
- All checks run on every PR
- Failed checks block merge
- Coverage reports generated and visible

---

### P0-4: DeepDoc Module Extraction
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Extract DeepDoc from RAGFlow repository:
  - `deepdoc/parser/` - All parser implementations
  - `deepdoc/vision/` - OCR and layout models
- [ ] Identify and extract dependencies:
  - Model weights locations
  - Required Python packages
- [ ] Create standalone DeepDoc package structure:
  ```
  deepdoc/
  ├── __init__.py
  ├── parser/
  │   ├── __init__.py
  │   ├── pdf_parser.py
  │   ├── docx_parser.py
  │   ├── excel_parser.py
  │   ├── html_parser.py
  │   ├── json_parser.py
  │   ├── markdown_parser.py
  │   └── txt_parser.py
  ├── vision/
  │   ├── __init__.py
  │   ├── ocr.py
  │   ├── layout.py
  │   └── table_detector.py
  └── models/
      └── (model weights or download scripts)
  ```
- [ ] Write unit tests for each parser
- [ ] Document parser interfaces and configurations

#### Acceptance Criteria
- DeepDoc functions independently from RAGFlow
- All parsers pass unit tests
- PDF parsing with OCR works correctly

---

## Phase 1: Core Infrastructure

### P1-1: Database Schema Design & Implementation
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Design PostgreSQL schema based on PRD data models
- [ ] Create SQLAlchemy ORM models:

```python
# backend/app/models/user.py
class User(Base):
    __tablename__ = "users"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    
    tenants: Mapped[list["TenantMembership"]] = relationship(back_populates="user")
```

- [ ] Create all model files:
  - `user.py` - User, TenantMembership
  - `tenant.py` - Tenant
  - `knowledge_base.py` - KnowledgeBase
  - `document.py` - Document, Chunk
  - `chat.py` - ChatSession, ChatMessage
  - `api_key.py` - APIKey
- [ ] Set up Alembic for migrations:
  ```bash
  alembic init alembic
  alembic revision --autogenerate -m "Initial schema"
  ```
- [ ] Create initial migration
- [ ] Add database indexes for common queries
- [ ] Implement soft delete for critical entities

#### Acceptance Criteria
- All models created with proper relationships
- Migrations run successfully on clean database
- Foreign key constraints enforced
- Indexes created for tenant_id, kb_id, email

---

### P1-2: Authentication & Authorization System
**Priority**: Critical  
**Estimate**: 4 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Implement password hashing (argon2/bcrypt)
- [ ] Create JWT token service:
  ```python
  # backend/app/core/security.py
  class TokenService:
      def create_access_token(self, user_id: UUID) -> str: ...
      def create_refresh_token(self, user_id: UUID) -> str: ...
      def verify_token(self, token: str) -> TokenPayload: ...
  ```
- [ ] Implement authentication endpoints:
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/logout`
  - `POST /api/v1/auth/refresh`
  - `GET /api/v1/auth/me`
- [ ] Create FastAPI dependency for auth:
  ```python
  async def get_current_user(
      token: str = Depends(oauth2_scheme),
      db: AsyncSession = Depends(get_db)
  ) -> User: ...
  ```
- [ ] Implement API key authentication:
  - Generate secure API keys
  - Hash keys before storage
  - Key scoping (read/write permissions)
- [ ] Add rate limiting middleware (slowapi)
- [ ] Implement tenant context injection

#### Acceptance Criteria
- Users can register and login
- JWT tokens issued and validated correctly
- API keys work for programmatic access
- Rate limiting prevents abuse
- Invalid tokens return 401

---

### P1-3: Multi-Tenancy Implementation
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Design tenant isolation strategy:
  - Database: tenant_id on all tenant-scoped tables
  - Elasticsearch: index-per-tenant or filtered alias
  - MinIO: bucket-per-tenant or prefix isolation
- [ ] Create tenant management endpoints:
  - `POST /api/v1/tenants` - Create tenant
  - `GET /api/v1/tenants` - List user's tenants
  - `GET /api/v1/tenants/{id}` - Get tenant details
  - `PUT /api/v1/tenants/{id}` - Update tenant
  - `DELETE /api/v1/tenants/{id}` - Delete tenant
- [ ] Implement tenant membership:
  - `POST /api/v1/tenants/{id}/members` - Add member
  - `DELETE /api/v1/tenants/{id}/members/{user_id}` - Remove member
  - `PUT /api/v1/tenants/{id}/members/{user_id}` - Update role
- [ ] Create tenant context middleware:
  ```python
  class TenantMiddleware:
      async def __call__(self, request: Request, call_next):
          tenant_id = extract_tenant_from_request(request)
          request.state.tenant_id = tenant_id
          return await call_next(request)
  ```
- [ ] Add tenant filtering to all queries
- [ ] Test cross-tenant data isolation

#### Acceptance Criteria
- Users can create and manage tenants
- All queries automatically scoped to tenant
- Cross-tenant access returns 403
- Tenant deletion cascades properly

---

### P1-4: MinIO Storage Service
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create MinIO client wrapper:
  ```python
  # backend/app/services/storage.py
  class StorageService:
      async def upload_file(
          self, tenant_id: UUID, file: UploadFile
      ) -> str: ...
      
      async def download_file(
          self, tenant_id: UUID, object_key: str
      ) -> bytes: ...
      
      async def delete_file(
          self, tenant_id: UUID, object_key: str
      ) -> None: ...
      
      async def generate_presigned_url(
          self, tenant_id: UUID, object_key: str, expires: int = 3600
      ) -> str: ...
  ```
- [ ] Implement bucket-per-tenant strategy
- [ ] Add file type validation
- [ ] Implement chunked upload for large files
- [ ] Add cleanup job for orphaned files
- [ ] Create storage usage tracking per tenant

#### Acceptance Criteria
- Files upload and download correctly
- Tenant isolation enforced at storage level
- Large files (>100MB) upload successfully
- Presigned URLs work for temporary access

---

### P1-5: Redis Caching & Queue Setup
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create Redis client wrapper with connection pooling
- [ ] Implement caching service:
  ```python
  class CacheService:
      async def get(self, key: str) -> Optional[Any]: ...
      async def set(self, key: str, value: Any, ttl: int = 3600): ...
      async def delete(self, key: str): ...
      async def invalidate_pattern(self, pattern: str): ...
  ```
- [ ] Set up Celery with Redis broker:
  ```python
  # backend/app/core/celery.py
  celery_app = Celery(
      "ragflow_replacement",
      broker=settings.REDIS_URL,
      backend=settings.REDIS_URL,
  )
  ```
- [ ] Configure task queues:
  - `parsing` - Document parsing tasks
  - `embedding` - Embedding generation
  - `indexing` - Elasticsearch indexing
  - `default` - General tasks
- [ ] Add task result tracking
- [ ] Implement task priority system

#### Acceptance Criteria
- Celery workers connect to Redis
- Tasks execute asynchronously
- Task status queryable via API
- Cache hit/miss working correctly

---

### P1-6: Logging & Monitoring Setup
**Priority**: Medium  
**Estimate**: 2 days  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Configure structured logging (JSON format):
  ```python
  # backend/app/core/logging.py
  import structlog
  
  structlog.configure(
      processors=[
          structlog.processors.TimeStamper(fmt="iso"),
          structlog.processors.JSONRenderer(),
      ]
  )
  ```
- [ ] Add request ID tracking middleware
- [ ] Create health check endpoints:
  - `GET /health` - Basic liveness
  - `GET /health/ready` - Readiness (all deps)
  - `GET /health/detailed` - Component status
- [ ] Set up Prometheus metrics:
  - Request latency histograms
  - Task queue lengths
  - Error rates
  - Active connections
- [ ] Create Grafana dashboard templates
- [ ] Add error tracking (Sentry integration optional)

#### Acceptance Criteria
- All requests logged with correlation IDs
- Health endpoints return accurate status
- Metrics exposed at `/metrics`
- Logs parseable by log aggregators

---

## Phase 2: Document Processing Pipeline

### P2-1: Document Upload API
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create document upload endpoint:
  ```python
  @router.post("/knowledgebases/{kb_id}/documents")
  async def upload_document(
      kb_id: UUID,
      file: UploadFile,
      from_page: int = 0,
      to_page: int = 100000,
      current_user: User = Depends(get_current_user),
  ) -> DocumentResponse: ...
  ```
- [ ] Implement file validation:
  - Allowed extensions: pdf, docx, doc, txt, md, html, csv, xlsx, json
  - Max file size check (configurable, default 100MB)
  - MIME type verification
- [ ] Store file metadata in PostgreSQL
- [ ] Upload file binary to MinIO
- [ ] Queue parsing task
- [ ] Return document with status "pending"

#### Acceptance Criteria
- Multiple file formats upload successfully
- Invalid files rejected with clear error messages
- File stored in MinIO with correct path
- Parsing task queued automatically

---

### P2-2: Parsing Task Executor
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create Celery task for document parsing:
  ```python
  @celery_app.task(bind=True, queue="parsing")
  def parse_document_task(
      self,
      document_id: str,
      tenant_id: str,
      parser_config: dict,
  ) -> dict: ...
  ```
- [ ] Implement progress callback system:
  ```python
  def update_progress(progress: float, message: str):
      # Update document status in DB
      # Publish progress to Redis pub/sub
      pass
  ```
- [ ] Route to appropriate parser based on file type
- [ ] Handle parser errors gracefully:
  - Retry logic with exponential backoff
  - Max retries before marking failed
  - Error message capture
- [ ] Update document status on completion
- [ ] Emit parsing complete event

#### Acceptance Criteria
- Parsing tasks execute in worker process
- Progress updates visible to clients
- Failed documents marked with error details
- Successful documents transition to "done"

---

### P2-3: General Template Chunking (naive.py port)
**Priority**: Critical  
**Estimate**: 4 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Port `naive_merge` function:
  ```python
  def naive_merge(
      sections: list[tuple[str, str]],
      chunk_token_num: int = 512,
      delimiter: str = "\n!?。；！？",
  ) -> list[str]: ...
  ```
- [ ] Port `tokenize_chunks` function
- [ ] Port table tokenization logic
- [ ] Implement image handling (optional vision enhancement)
- [ ] Support all file formats:
  - PDF (DeepDoc)
  - DOCX (python-docx + DeepDoc tables)
  - Excel (pandas/openpyxl)
  - TXT/MD/HTML/JSON
- [ ] Create chunking configuration schema:
  ```python
  class GeneralChunkConfig(BaseModel):
      chunk_token_num: int = 512
      delimiter: str = "\n!?。；！？"
      layout_recognize: str = "DeepDOC"
      analyze_hyperlink: bool = False
  ```
- [ ] Write comprehensive unit tests
- [ ] Validate output matches RAGFlow behavior

#### Acceptance Criteria
- Chunk output matches RAGFlow for test documents
- All supported file formats parse correctly
- Token counts within expected ranges
- Tables extracted as HTML

---

### P2-4: Laws Template Chunking (laws.py port)
**Priority**: High  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Port `bullets_category` function
- [ ] Port `remove_contents_table` function
- [ ] Port `make_colon_as_title` function
- [ ] Port `tree_merge` function:
  ```python
  def tree_merge(
      bull: str,
      sections: list[str],
      depth: int = 2,
  ) -> list[str]: ...
  ```
- [ ] Port `Node` class for tree building
- [ ] Port `docx_question_level` for DOCX heading detection
- [ ] Support formats: DOCX, PDF, TXT, MD, HTML
- [ ] Create configuration schema:
  ```python
  class LawsChunkConfig(BaseModel):
      chunk_token_num: int = 512
      delimiter: str = "\n!?。；！？"
      layout_recognize: str = "DeepDOC"
      tree_depth: int = 2
  ```
- [ ] Write unit tests with legal document samples

#### Acceptance Criteria
- Hierarchical structure preserved in chunks
- Table of contents removed
- Numbered sections grouped correctly
- Output matches RAGFlow for test documents

---

### P2-5: Paper Template Chunking (paper.py port)
**Priority**: High  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Port Paper PDF parser class:
  ```python
  class PaperPdfParser(PdfParser):
      def __call__(self, filename, binary, ...) -> dict:
          return {
              "title": str,
              "authors": str,
              "abstract": str,
              "sections": list[tuple[str, str]],
              "tables": list,
          }
  ```
- [ ] Port title/author extraction logic
- [ ] Port abstract detection
- [ ] Port two-column layout handling
- [ ] Port `title_frequency` for section pivot detection
- [ ] Port figure/table extraction with vision enhancement
- [ ] PDF-only format enforcement
- [ ] Create configuration schema:
  ```python
  class PaperChunkConfig(BaseModel):
      chunk_token_num: int = 512
      layout_recognize: str = "DeepDOC"
  ```
- [ ] Write unit tests with academic paper PDFs

#### Acceptance Criteria
- Title, authors, abstract extracted correctly
- Abstract preserved as single chunk
- Two-column papers parsed correctly
- Section grouping matches RAGFlow behavior

---

### P2-6: Chunk Storage & Management
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create chunk storage service:
  ```python
  class ChunkService:
      async def store_chunks(
          self, document_id: UUID, chunks: list[ChunkData]
      ) -> list[Chunk]: ...
      
      async def get_chunks(
          self, document_id: UUID, page: int, size: int
      ) -> list[Chunk]: ...
      
      async def delete_chunks(
          self, document_id: UUID
      ) -> int: ...
  ```
- [ ] Store chunks in PostgreSQL with:
  - Content text
  - Token count
  - Position info (page, coordinates)
  - Sequence number
- [ ] Create chunk API endpoints:
  - `GET /api/v1/documents/{doc_id}/chunks`
  - `GET /api/v1/chunks/{chunk_id}`
- [ ] Implement chunk pagination
- [ ] Add chunk search within document

#### Acceptance Criteria
- Chunks stored with correct metadata
- Chunks retrievable by document
- Pagination works correctly
- Position info preserved

---

## Phase 3: Search & Retrieval

### P3-1: Elasticsearch Index Setup
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create index template:
  ```json
  {
    "mappings": {
      "properties": {
        "chunk_id": { "type": "keyword" },
        "doc_id": { "type": "keyword" },
        "kb_id": { "type": "keyword" },
        "tenant_id": { "type": "keyword" },
        "content": { 
          "type": "text",
          "analyzer": "standard"
        },
        "content_vector": {
          "type": "dense_vector",
          "dims": 1024,
          "index": true,
          "similarity": "cosine"
        },
        "title_tokens": { "type": "text" },
        "created_at": { "type": "date" }
      }
    }
  }
  ```
- [ ] Implement index-per-tenant strategy:
  ```python
  def get_index_name(tenant_id: UUID) -> str:
      return f"chunks_{tenant_id}"
  ```
- [ ] Create index lifecycle management
- [ ] Add index health monitoring
- [ ] Implement index migration utilities

#### Acceptance Criteria
- Index created automatically for new tenants
- Mappings support vector and text search
- Index naming prevents cross-tenant access

---

### P3-2: Embedding Service Integration
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create embedding service abstraction:
  ```python
  class EmbeddingService(ABC):
      @abstractmethod
      async def embed(self, texts: list[str]) -> list[list[float]]: ...
      
      @abstractmethod
      def dimension(self) -> int: ...
  ```
- [ ] Implement Ollama provider:
  ```python
  class OllamaEmbedding(EmbeddingService):
      def __init__(self, model: str = "bge-m3", base_url: str = "http://localhost:11434"):
          ...
  ```
- [ ] Implement vLLM provider
- [ ] Implement OpenAI provider:
  ```python
  class OpenAIEmbedding(EmbeddingService):
      def __init__(self, model: str = "text-embedding-3-small", api_key: str):
          ...
  ```
- [ ] Add batch processing with rate limiting
- [ ] Create embedding configuration per tenant:
  ```python
  class EmbeddingConfig(BaseModel):
      provider: Literal["ollama", "vllm", "openai"]
      model: str
      api_key: Optional[str]
      base_url: Optional[str]
  ```
- [ ] Cache embeddings for duplicate content

#### Acceptance Criteria
- All three providers work correctly
- Batch embedding efficient
- Tenant-specific configurations respected
- Dimension mismatch errors handled

---

### P3-3: Chunk Indexing Pipeline
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create indexing Celery task:
  ```python
  @celery_app.task(bind=True, queue="indexing")
  def index_chunks_task(
      self,
      document_id: str,
      tenant_id: str,
  ) -> dict: ...
  ```
- [ ] Implement bulk indexing:
  ```python
  async def bulk_index_chunks(
      self, tenant_id: UUID, chunks: list[Chunk]
  ) -> int: ...
  ```
- [ ] Generate embeddings for chunk content
- [ ] Store vectors in Elasticsearch
- [ ] Update document status after indexing
- [ ] Handle partial failures (retry failed chunks)

#### Acceptance Criteria
- Chunks indexed after parsing completes
- Embeddings generated and stored
- Bulk indexing performant (>100 chunks/sec)
- Failed chunks retried

---

### P3-4: Hybrid Search Implementation
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create search service:
  ```python
  class SearchService:
      async def search(
          self,
          tenant_id: UUID,
          kb_ids: list[UUID],
          query: str,
          top_k: int = 10,
          similarity_threshold: float = 0.5,
          search_mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
      ) -> list[SearchResult]: ...
  ```
- [ ] Implement vector search (kNN):
  ```python
  async def vector_search(
      self, query_vector: list[float], ...
  ) -> list[dict]: ...
  ```
- [ ] Implement keyword search (BM25):
  ```python
  async def keyword_search(
      self, query: str, ...
  ) -> list[dict]: ...
  ```
- [ ] Implement hybrid fusion:
  ```python
  def fuse_results(
      vector_results: list[dict],
      keyword_results: list[dict],
      vector_weight: float = 0.7,
  ) -> list[SearchResult]: ...
  ```
- [ ] Add knowledge base filtering
- [ ] Create search API endpoint:
  - `POST /api/v1/knowledgebases/{kb_id}/search`

#### Acceptance Criteria
- Vector search returns semantically similar chunks
- Keyword search finds exact matches
- Hybrid search combines both effectively
- Results filtered by tenant and KB

---

### P3-5: Re-ranking Integration
**Priority**: Medium  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create re-ranker abstraction:
  ```python
  class Reranker(ABC):
      @abstractmethod
      async def rerank(
          self, query: str, documents: list[str], top_k: int
      ) -> list[tuple[int, float]]: ...
  ```
- [ ] Implement cross-encoder re-ranker (optional local model)
- [ ] Implement Cohere re-ranker (optional cloud)
- [ ] Add re-ranking configuration:
  ```python
  class RerankerConfig(BaseModel):
      enabled: bool = False
      provider: Optional[Literal["local", "cohere"]]
      model: Optional[str]
      top_k: int = 5
  ```
- [ ] Integrate into search pipeline

#### Acceptance Criteria
- Re-ranking improves result relevance
- Re-ranking optional per tenant
- Latency acceptable (<500ms additional)

---

## Phase 4: LLM & Chat Integration

### P4-1: LLM Provider Abstraction
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create LLM service interface:
  ```python
  class LLMService(ABC):
      @abstractmethod
      async def generate(
          self, messages: list[Message], **kwargs
      ) -> str: ...
      
      @abstractmethod
      async def generate_stream(
          self, messages: list[Message], **kwargs
      ) -> AsyncIterator[str]: ...
  ```
- [ ] Implement providers using LiteLLM:
  ```python
  class LiteLLMProvider(LLMService):
      def __init__(self, model: str, api_key: Optional[str], base_url: Optional[str]):
          ...
  ```
- [ ] Support models:
  - Ollama (local)
  - vLLM (local)
  - OpenAI (gpt-4, gpt-3.5-turbo)
  - Anthropic (claude-3)
  - DeepSeek
- [ ] Create LLM configuration per tenant:
  ```python
  class LLMConfig(BaseModel):
      provider: str
      model: str
      api_key: Optional[str]
      base_url: Optional[str]
      temperature: float = 0.7
      max_tokens: int = 2048
  ```
- [ ] Add token counting and limit enforcement

#### Acceptance Criteria
- All providers generate responses correctly
- Streaming works for all providers
- Tenant configurations respected
- Token limits enforced

---

### P4-2: Chat Session Management
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create chat session endpoints:
  - `POST /api/v1/chat/sessions` - Create session
  - `GET /api/v1/chat/sessions` - List sessions
  - `GET /api/v1/chat/sessions/{id}` - Get session
  - `DELETE /api/v1/chat/sessions/{id}` - Delete session
- [ ] Implement session configuration:
  ```python
  class CreateSessionRequest(BaseModel):
      kb_ids: list[UUID]
      system_prompt: Optional[str]
      name: Optional[str]
  ```
- [ ] Store session metadata in PostgreSQL
- [ ] Implement session sharing (optional)

#### Acceptance Criteria
- Sessions created with KB associations
- Session list filterable by user
- Session deletion cascades messages

---

### P4-3: RAG Chat Pipeline
**Priority**: Critical  
**Estimate**: 4 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create chat message endpoint:
  ```python
  @router.post("/chat/sessions/{session_id}/messages")
  async def send_message(
      session_id: UUID,
      request: SendMessageRequest,
      current_user: User = Depends(get_current_user),
  ) -> StreamingResponse: ...
  ```
- [ ] Implement RAG pipeline:
  ```python
  async def rag_pipeline(
      session: ChatSession,
      user_message: str,
      llm_service: LLMService,
      search_service: SearchService,
  ) -> AsyncIterator[str]:
      # 1. Search relevant chunks
      chunks = await search_service.search(...)
      
      # 2. Build context
      context = format_chunks_as_context(chunks)
      
      # 3. Build prompt
      messages = build_messages(session, user_message, context)
      
      # 4. Generate response
      async for token in llm_service.generate_stream(messages):
          yield token
  ```
- [ ] Implement citation extraction:
  ```python
  def extract_citations(
      response: str, chunks: list[Chunk]
  ) -> list[Citation]: ...
  ```
- [ ] Store messages with citations
- [ ] Support conversation history context

#### Acceptance Criteria
- User messages trigger retrieval + generation
- Responses include relevant citations
- Streaming responses work in UI
- Conversation history maintained

---

### P4-4: Message History & Context Management
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create message history endpoints:
  - `GET /api/v1/chat/sessions/{id}/messages`
- [ ] Implement context window management:
  ```python
  def build_conversation_context(
      messages: list[ChatMessage],
      max_tokens: int = 4000,
  ) -> list[Message]: ...
  ```
- [ ] Add message summarization for long conversations
- [ ] Implement message pagination
- [ ] Add message metadata (timestamps, token counts)

#### Acceptance Criteria
- Full message history retrievable
- Context window limits respected
- Long conversations handled gracefully

---

## Phase 5: Web Frontend

### P5-1: Frontend Project Setup
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Initialize React project with Vite:
  ```bash
  npm create vite@latest frontend -- --template react-ts
  ```
- [ ] Set up project structure:
  ```
  frontend/src/
  ├── components/
  │   ├── common/
  │   ├── layout/
  │   └── features/
  ├── pages/
  ├── hooks/
  ├── services/
  ├── store/
  ├── types/
  └── utils/
  ```
- [ ] Install core dependencies:
  ```bash
  npm install @tanstack/react-query axios react-router-dom
  npm install -D tailwindcss postcss autoprefixer
  ```
- [ ] Configure Tailwind CSS
- [ ] Set up React Query provider
- [ ] Create API client with interceptors:
  ```typescript
  const apiClient = axios.create({
    baseURL: import.meta.env.VITE_API_URL,
  });
  ```
- [ ] Set up routing structure
- [ ] Create authentication context

#### Acceptance Criteria
- Dev server starts successfully
- Routing works correctly
- API client configured
- Tailwind styles apply

---

### P5-2: Authentication UI
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create Login page:
  - Email/password form
  - Validation
  - Error display
  - "Remember me" option
- [ ] Create Registration page:
  - Email/password/confirm password
  - Terms acceptance
  - Validation
- [ ] Implement auth store/context:
  ```typescript
  interface AuthState {
    user: User | null;
    token: string | null;
    isAuthenticated: boolean;
    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
  }
  ```
- [ ] Add protected route wrapper
- [ ] Implement token refresh logic
- [ ] Create user menu (profile, logout)

#### Acceptance Criteria
- Login flow works end-to-end
- Registration creates account
- Protected routes redirect to login
- Token stored securely

---

### P5-3: Knowledge Base Management UI
**Priority**: Critical  
**Estimate**: 4 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create Knowledge Base list page:
  - Grid/list view toggle
  - Search/filter
  - Create button
  - KB cards with stats
- [ ] Create KB creation modal:
  - Name, description
  - Template selection (General, Laws, Paper)
  - Parser configuration
- [ ] Create KB detail page:
  - Document list
  - Configuration panel
  - Stats (doc count, chunk count)
- [ ] Create KB settings page:
  - Edit name/description
  - Change template (warning for existing docs)
  - Delete KB (confirmation)
- [ ] Implement KB API hooks:
  ```typescript
  const useKnowledgeBases = () => useQuery(['kbs'], fetchKnowledgeBases);
  const useCreateKB = () => useMutation(createKnowledgeBase);
  ```

#### Acceptance Criteria
- KB CRUD operations work
- Template selection affects configuration
- Stats update after document processing
- Delete requires confirmation

---

### P5-4: Document Upload & Management UI
**Priority**: Critical  
**Estimate**: 3 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create document upload component:
  - Drag-and-drop zone
  - File type validation
  - Multiple file support
  - Upload progress bars
- [ ] Create document list component:
  - Status indicators (pending, parsing, done, failed)
  - File type icons
  - Sortable columns
  - Pagination
- [ ] Create document detail modal:
  - File metadata
  - Parsing status/progress
  - Error details (if failed)
  - Chunk count
- [ ] Implement real-time status updates:
  ```typescript
  // WebSocket or polling for parsing progress
  const useDocumentStatus = (docId: string) => {
    // Subscribe to status updates
  };
  ```
- [ ] Create document deletion with confirmation

#### Acceptance Criteria
- Files upload with progress indication
- Status updates in real-time
- Failed documents show error details
- Multiple files uploadable at once

---

### P5-5: Chunk Visualization UI
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create chunk list view:
  - Chunk cards with content preview
  - Token count display
  - Position info
  - Pagination
- [ ] Create chunk detail modal:
  - Full content display
  - Metadata panel
  - Source document link
- [ ] Add chunk search within document
- [ ] Implement chunk highlighting in context

#### Acceptance Criteria
- Chunks displayable for any document
- Content readable with proper formatting
- Search finds chunks by content
- Pagination handles large documents

---

### P5-6: Chat Interface UI
**Priority**: Critical  
**Estimate**: 4 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create chat layout:
  - Session sidebar
  - Message area
  - Input bar
- [ ] Create session list component:
  - Create new session button
  - Session name/date
  - Delete session
- [ ] Create message component:
  - User/assistant styling
  - Markdown rendering
  - Code block highlighting
  - Citation chips
- [ ] Implement streaming message display:
  ```typescript
  const useChatStream = () => {
    // SSE or WebSocket for streaming
  };
  ```
- [ ] Create citation popup/modal:
  - Source chunk content
  - Document name
  - Link to source
- [ ] Add session configuration panel:
  - KB selection
  - System prompt editing

#### Acceptance Criteria
- Messages display with streaming effect
- Citations clickable and show source
- Markdown renders correctly
- Session switching maintains history

---

### P5-7: Settings & Configuration UI
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Create settings layout with tabs/sections
- [ ] Create LLM configuration page:
  - Provider selection
  - Model selection
  - API key input (masked)
  - Base URL (for local)
  - Test connection button
- [ ] Create embedding configuration page:
  - Provider selection
  - Model selection
  - API key (if cloud)
- [ ] Create API key management page:
  - Generate new key
  - List existing keys
  - Revoke keys
- [ ] Create team/tenant management page:
  - Member list
  - Invite member
  - Change roles
  - Remove member

#### Acceptance Criteria
- Settings save successfully
- API key masked in display
- Test connection validates config
- Team management works correctly

---

### P5-8: Responsive Design & Polish
**Priority**: Medium  
**Estimate**: 2 days  
**Assignee**: Frontend Engineer

#### Tasks
- [ ] Implement responsive breakpoints:
  - Mobile: < 768px
  - Tablet: 768px - 1024px
  - Desktop: > 1024px
- [ ] Create mobile navigation (hamburger menu)
- [ ] Optimize chat UI for mobile
- [ ] Add loading states and skeletons
- [ ] Implement error boundaries
- [ ] Add toast notifications
- [ ] Create empty states for lists
- [ ] Add keyboard shortcuts for power users

#### Acceptance Criteria
- UI usable on mobile devices
- Loading states prevent layout shift
- Errors handled gracefully
- Notifications inform users of actions

---

## Phase 6: Integration & Testing

### P6-1: Unit Test Coverage
**Priority**: High  
**Estimate**: 3 days  
**Assignee**: All Engineers

#### Tasks
- [ ] Backend unit tests (target: 80% coverage):
  - Model tests
  - Service tests (mocked dependencies)
  - Utility function tests
  - API endpoint tests
- [ ] Frontend unit tests:
  - Component tests (React Testing Library)
  - Hook tests
  - Utility function tests
- [ ] DeepDoc parser tests
- [ ] Run coverage reports in CI

#### Acceptance Criteria
- Backend coverage >= 80%
- Frontend coverage >= 70%
- All tests pass in CI
- Critical paths covered

---

### P6-2: Integration Tests
**Priority**: High  
**Estimate**: 3 days  
**Assignee**: Backend Engineer + QA

#### Tasks
- [ ] Create integration test fixtures:
  - Test database with sample data
  - Test files for each format
  - Test tenant and users
- [ ] Write API integration tests:
  - Auth flow tests
  - KB CRUD tests
  - Document upload + parse tests
  - Search tests
  - Chat tests
- [ ] Write chunking parity tests:
  - Compare output with RAGFlow
  - Use repo-derived sample documents
  - Validate chunk boundaries
- [ ] Create end-to-end test scenarios:
  - Upload document → Parse → Index → Search → Chat
  - Multi-tenant isolation tests

#### Acceptance Criteria
- All API endpoints have integration tests
- Chunking output matches RAGFlow within 10%
- E2E scenarios pass
- Tests run in isolated environment

---

### P6-3: Performance Testing
**Priority**: Medium  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Create load test scripts (Locust/k6):
  - Document upload load
  - Search query load
  - Chat message load
- [ ] Establish performance baselines:
  - Parse time per page
  - Search latency p50/p95/p99
  - Chat response time (TTFB)
- [ ] Identify and fix bottlenecks
- [ ] Document performance characteristics

#### Acceptance Criteria
- System handles 100 concurrent users
- Search latency < 500ms (p95)
- Parse time < 30s/page average
- No memory leaks under load

---

### P6-4: Security Testing
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: Backend Engineer

#### Tasks
- [ ] Run SAST tools (Bandit, Semgrep)
- [ ] Test authentication:
  - Password requirements
  - Token expiration
  - Session invalidation
- [ ] Test authorization:
  - Cross-tenant access attempts
  - Role-based access control
- [ ] Test input validation:
  - SQL injection attempts
  - XSS attempts
  - File upload exploits
- [ ] Review secret management

#### Acceptance Criteria
- No critical/high SAST findings
- Auth tests pass
- Cross-tenant access blocked
- Input validation comprehensive

---

## Phase 7: Deployment & Documentation

### P7-1: Docker Production Images
**Priority**: Critical  
**Estimate**: 2 days  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Create production Dockerfiles:
  - `Dockerfile.backend` (multi-stage, slim)
  - `Dockerfile.frontend` (nginx-based)
  - `Dockerfile.worker` (Celery workers)
- [ ] Optimize image sizes:
  - Use slim base images
  - Multi-stage builds
  - Remove dev dependencies
- [ ] Create `docker-compose.prod.yml`:
  - All services with production settings
  - Resource limits
  - Restart policies
  - Health checks
- [ ] Set up image registry (Docker Hub/GHCR)
- [ ] Create image tagging strategy

#### Acceptance Criteria
- Images build successfully
- Image sizes minimized
- Production compose starts all services
- Health checks pass

---

### P7-2: Kubernetes Manifests
**Priority**: Medium  
**Estimate**: 2 days  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Create Kubernetes manifests:
  - Deployments for each service
  - Services (ClusterIP, LoadBalancer)
  - ConfigMaps and Secrets
  - PersistentVolumeClaims
  - Ingress configuration
- [ ] Create Helm chart (optional):
  ```
  helm/
  ├── Chart.yaml
  ├── values.yaml
  └── templates/
  ```
- [ ] Document resource requirements:
  - CPU/memory requests and limits
  - Storage requirements
- [ ] Add horizontal pod autoscaling

#### Acceptance Criteria
- Manifests deploy to Kubernetes cluster
- Services communicate correctly
- Secrets properly managed
- Autoscaling works

---

### P7-3: Configuration & Environment Documentation
**Priority**: High  
**Estimate**: 1 day  
**Assignee**: DevOps Engineer

#### Tasks
- [ ] Document all environment variables:
  - Required vs optional
  - Default values
  - Format/examples
- [ ] Create configuration reference:
  ```markdown
  | Variable | Description | Required | Default |
  |----------|-------------|----------|---------|
  | DATABASE_URL | PostgreSQL connection string | Yes | - |
  ```
- [ ] Document secrets management:
  - API keys
  - Database passwords
  - JWT secrets
- [ ] Create deployment checklist

#### Acceptance Criteria
- All env vars documented
- Examples provided
- Checklist covers all steps

---

### P7-4: User Documentation
**Priority**: High  
**Estimate**: 2 days  
**Assignee**: All Engineers

#### Tasks
- [ ] Create getting started guide:
  - Prerequisites
  - Installation steps
  - First knowledge base
  - First chat
- [ ] Document UI features:
  - Screenshots
  - Feature explanations
  - Common workflows
- [ ] Create API documentation:
  - OpenAPI spec (auto-generated)
  - Authentication guide
  - Code examples
- [ ] Create FAQ section
- [ ] Create troubleshooting guide

#### Acceptance Criteria
- New users can self-onboard
- All features documented
- API docs complete
- Common issues addressed

---

### P7-5: Developer Documentation
**Priority**: Medium  
**Estimate**: 1 day  
**Assignee**: Lead Developer

#### Tasks
- [ ] Document architecture overview
- [ ] Create contribution guide:
  - Code style
  - PR process
  - Testing requirements
- [ ] Document extending the system:
  - Adding new parsers
  - Adding LLM providers
  - Adding embedding providers
- [ ] Create debugging guide
- [ ] Document release process

#### Acceptance Criteria
- New developers can contribute
- Extension points documented
- Architecture understandable

---

## Task Dependencies Graph

```
P0-1 ──┬── P0-2 ──┬── P0-3
       │          │
       └── P0-4 ──┘
           │
           ▼
P1-1 ──┬── P1-2 ── P1-3
       │
       ├── P1-4
       │
       ├── P1-5 ── P2-2
       │
       └── P1-6
           │
           ▼
P2-1 ── P2-2 ──┬── P2-3
               │
               ├── P2-4
               │
               └── P2-5
                   │
                   ▼
               P2-6 ── P3-1 ── P3-2 ── P3-3 ── P3-4 ── P3-5
                                                │
                                                ▼
                               P4-1 ── P4-2 ── P4-3 ── P4-4
                                               │
                                               ▼
P5-1 ── P5-2 ──┬── P5-3 ──┬── P5-4 ── P5-5
               │          │
               │          └── P5-6 ──┬── P5-7
               │                     │
               │                     └── P5-8
               │                           │
               └───────────────────────────┘
                           │
                           ▼
P6-1 ──┬── P6-2 ── P6-3 ── P6-4
       │                    │
       │                    ▼
       │              P7-1 ── P7-2
       │                │
       │                ▼
       └────────── P7-3 ── P7-4 ── P7-5
```

---

## Risk Register

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| DeepDoc extraction complexity | High | Medium | Start early, allocate buffer time |
| Embedding model compatibility | Medium | Medium | Test multiple models early |
| Performance issues at scale | High | Low | Load test early, profile critical paths |
| Chunking parity differences | Medium | Medium | Define acceptable variance, document differences |
| LLM provider API changes | Low | Medium | Use abstraction layer, test regularly |
| Elasticsearch version compatibility | Medium | Low | Pin versions, test upgrades |

---

## Appendix: Task ID Reference

| ID | Title | Phase |
|----|-------|-------|
| P0-1 | Repository Initialization | Setup |
| P0-2 | Development Environment Setup | Setup |
| P0-3 | CI/CD Pipeline Setup | Setup |
| P0-4 | DeepDoc Module Extraction | Setup |
| P1-1 | Database Schema Design | Infrastructure |
| P1-2 | Authentication System | Infrastructure |
| P1-3 | Multi-Tenancy Implementation | Infrastructure |
| P1-4 | MinIO Storage Service | Infrastructure |
| P1-5 | Redis Caching & Queue | Infrastructure |
| P1-6 | Logging & Monitoring | Infrastructure |
| P2-1 | Document Upload API | Processing |
| P2-2 | Parsing Task Executor | Processing |
| P2-3 | General Template Chunking | Processing |
| P2-4 | Laws Template Chunking | Processing |
| P2-5 | Paper Template Chunking | Processing |
| P2-6 | Chunk Storage & Management | Processing |
| P3-1 | Elasticsearch Index Setup | Retrieval |
| P3-2 | Embedding Service Integration | Retrieval |
| P3-3 | Chunk Indexing Pipeline | Retrieval |
| P3-4 | Hybrid Search Implementation | Retrieval |
| P3-5 | Re-ranking Integration | Retrieval |
| P4-1 | LLM Provider Abstraction | LLM/Chat |
| P4-2 | Chat Session Management | LLM/Chat |
| P4-3 | RAG Chat Pipeline | LLM/Chat |
| P4-4 | Message History & Context | LLM/Chat |
| P5-1 | Frontend Project Setup | Frontend |
| P5-2 | Authentication UI | Frontend |
| P5-3 | Knowledge Base Management UI | Frontend |
| P5-4 | Document Upload UI | Frontend |
| P5-5 | Chunk Visualization UI | Frontend |
| P5-6 | Chat Interface UI | Frontend |
| P5-7 | Settings UI | Frontend |
| P5-8 | Responsive Design | Frontend |
| P6-1 | Unit Test Coverage | Testing |
| P6-2 | Integration Tests | Testing |
| P6-3 | Performance Testing | Testing |
| P6-4 | Security Testing | Testing |
| P7-1 | Docker Production Images | Deployment |
| P7-2 | Kubernetes Manifests | Deployment |
| P7-3 | Configuration Documentation | Deployment |
| P7-4 | User Documentation | Deployment |
| P7-5 | Developer Documentation | Deployment |
