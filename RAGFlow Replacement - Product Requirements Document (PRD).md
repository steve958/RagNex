# Product Requirements Document: RAGFlow Replacement System
## 1\. Executive Summary
This document specifies the requirements for a self\-hosted, open\-source, multi\-tenant Retrieval\-Augmented Generation \(RAG\) system that replaces the existing RAGFlow implementation\. The new system focuses on core RAG functionality with DeepDoc\-based document processing, template\-based chunking, hybrid search, and a streamlined web UI\.
## 2\. Project Goals
* Deliver a production\-ready, fully self\-hosted RAG platform
* Maintain feature parity with RAGFlow core functionality \(excluding connectors, agents, manual chunking\)
* Optimize for ease of deployment and maintenance
* Support multi\-tenant operations with tenant\-level isolation
* Provide extensible embedding/LLM integration architecture
## 3\. Scope
### 3\.1 In Scope
* Multi\-tenant user management with team\-based access control
* Document ingestion with DeepDoc parsing only
* Template\-based chunking: General, Laws, Paper
* Hybrid retrieval using Elasticsearch/OpenSearch
* Local embeddings by default \(Ollama, vLLM\) with optional OpenAI
* LLM integration \(local \+ cloud providers\)
* Web UI for knowledge base and chat management
* RESTful API for integration
### 3\.2 Out of Scope
* Connectors \(S3, Confluence, Google Drive, etc\.\)
* Agent/tool orchestration and MCP
* Manual chunking template
* Retrieval Test page in UI
* Alternative parsers \(MinerU, Docling, TCADP\)
## 4\. System Architecture
### 4\.1 Infrastructure Stack
* **Metadata Database**: PostgreSQL
* **Object Storage**: MinIO \(S3\-compatible\)
* **Search Engine**: Elasticsearch or OpenSearch
* **Cache/Queue**: Redis
* **Embeddings**: Local by default \(Ollama/vLLM\), optional OpenAI
* **LLM**: Configurable per tenant \(local or cloud\)
### 4\.2 Component Overview
* **API Server**: RESTful backend service
* **Task Executor**: Async document processing workers
* **Web Frontend**: React\-based SPA
* **DeepDoc Parser**: Document parsing and OCR
## 5\. Functional Requirements
### 5\.1 User Management
**FR\-1\.1** System shall support user registration and authentication  
**FR\-1\.2** System shall support team/tenant creation and membership  
**FR\-1\.3** Each tenant shall have isolated knowledge bases and configurations  
**FR\-1\.4** Users shall be able to configure LLM and embedding models per tenant  
**FR\-1\.5** API key\-based authentication for programmatic access
### 5\.2 Document Ingestion
**FR\-2\.1** Supported file formats: PDF, DOCX, DOC, TXT, MD, HTML, CSV, XLSX, JSON  
**FR\-2\.2** Documents stored in MinIO with metadata in PostgreSQL  
**FR\-2\.3** Asynchronous parsing via task executor with progress callbacks  
**FR\-2\.4** DeepDoc parser for layout recognition and OCR  
**FR\-2\.5** Configurable page ranges for partial document processing
### 5\.3 Chunking Templates
#### 5\.3\.1 General Template
**FR\-3\.1** Naive merge strategy combining successive text sections  
**FR\-3\.2** Configurable token limit per chunk \(default: 512\)  
**FR\-3\.3** Configurable delimiters for section boundaries  
**FR\-3\.4** Table extraction with HTML representation  
**FR\-3\.5** Image handling with optional vision model enhancement  
**FR\-3\.6** Hyperlink extraction and optional follow\-parsing
#### 5\.3\.2 Laws Template
**FR\-3\.7** Hierarchical tree merge based on document structure  
**FR\-3\.8** Bullet/numbering category detection for structure inference  
**FR\-3\.9** Automatic table of contents removal  
**FR\-3\.10** Colon\-based title detection  
**FR\-3\.11** Level\-based section grouping \(configurable depth\)
#### 5\.3\.3 Paper Template
**FR\-3\.12** Academic paper structure detection \(title, authors, abstract, sections\)  
**FR\-3\.13** Abstract preserved as complete chunk  
**FR\-3\.14** Two\-column layout detection and handling  
**FR\-3\.15** Title frequency analysis for section pivot detection  
**FR\-3\.16** Figure and table extraction with vision enhancement  
**FR\-3\.17** PDF\-only format support
### 5\.4 Indexing and Retrieval
**FR\-4\.1** Vector embeddings stored in Elasticsearch/OpenSearch  
**FR\-4\.2** Full\-text BM25 search capability  
**FR\-4\.3** Hybrid retrieval combining vector \+ keyword search  
**FR\-4\.4** Re\-ranking support for result refinement  
**FR\-4\.5** Tenant\-isolated indices \(index per tenant or index aliasing\)  
**FR\-4\.6** Configurable similarity threshold and top\-k retrieval
### 5\.5 Chat/QA Interface
**FR\-5\.1** Chat sessions with message history  
**FR\-5\.2** Citation\-backed answers with source chunks  
**FR\-5\.3** Configurable system prompts per chat assistant  
**FR\-5\.4** Multi\-turn conversation support  
**FR\-5\.5** Streaming response support
### 5\.6 Web UI Requirements
**FR\-6\.1** Knowledge Base management \(create, list, configure, delete\)  
**FR\-6\.2** Document upload with progress indication  
**FR\-6\.3** Chunk visualization and inspection  
**FR\-6\.4** Chat interface with citation display  
**FR\-6\.5** Settings page for LLM/embedding configuration  
**FR\-6\.6** User/team management interface  
**FR\-6\.7** Parsing status and task monitoring  
**Note**: Retrieval Test page is explicitly excluded
## 6\. Non\-Functional Requirements
### 6\.1 Performance
**NFR\-1\.1** Document parsing: < 30 seconds per page average  
**NFR\-1\.2** Query latency: < 500ms for retrieval \(excluding LLM\)  
**NFR\-1\.3** Support 100\+ concurrent users per instance  
**NFR\-1\.4** Handle documents up to 1000 pages
### 6\.2 Scalability
**NFR\-2\.1** Horizontal scaling of task executors  
**NFR\-2\.2** Elasticsearch cluster support  
**NFR\-2\.3** Redis clustering for high availability
### 6\.3 Security
**NFR\-3\.1** Tenant data isolation at all layers  
**NFR\-3\.2** Encrypted API keys storage  
**NFR\-3\.3** HTTPS support for all endpoints  
**NFR\-3\.4** Rate limiting on public endpoints
### 6\.4 Deployment
**NFR\-4\.1** Docker Compose for single\-node deployment  
**NFR\-4\.2** Kubernetes\-ready manifests  
**NFR\-4\.3** GPU support for accelerated OCR/parsing  
**NFR\-4\.4** Configuration via environment variables
## 7\. Data Models
### 7\.1 Core Entities
```warp-runnable-command
User {
  id: UUID
  email: String
  password_hash: String
  created_at: Timestamp
  status: Enum(active, inactive)
}
Tenant {
  id: UUID
  name: String
  owner_id: UUID (FK User)
  llm_config: JSONB
  embedding_config: JSONB
  created_at: Timestamp
}
KnowledgeBase {
  id: UUID
  tenant_id: UUID (FK Tenant)
  name: String
  description: String
  chunk_template: Enum(general, laws, paper)
  parser_config: JSONB
  created_at: Timestamp
}
Document {
  id: UUID
  kb_id: UUID (FK KnowledgeBase)
  filename: String
  storage_path: String (MinIO key)
  status: Enum(pending, parsing, done, failed)
  chunk_count: Integer
  created_at: Timestamp
}
Chunk {
  id: UUID
  doc_id: UUID (FK Document)
  content: Text
  position_info: JSONB
  token_count: Integer
  es_index_id: String
}
ChatSession {
  id: UUID
  tenant_id: UUID
  kb_ids: UUID[] (FK KnowledgeBase)
  system_prompt: Text
  created_at: Timestamp
}
ChatMessage {
  id: UUID
  session_id: UUID (FK ChatSession)
  role: Enum(user, assistant)
  content: Text
  citations: JSONB
  created_at: Timestamp
}
```
### 7\.2 Elasticsearch Index Schema
```warp-runnable-command
chunk_index {
  chunk_id: keyword
  doc_id: keyword
  kb_id: keyword
  tenant_id: keyword
  content: text (with BM25)
  content_vector: dense_vector
  title_tokens: text
  position: object
  created_at: date
}
```
## 8\. API Surface
### 8\.1 Authentication
* `POST /api/v1/auth/register`
* `POST /api/v1/auth/login`
* `POST /api/v1/auth/logout`
* `GET /api/v1/auth/me`
### 8\.2 Knowledge Base
* `GET /api/v1/knowledgebases`
* `POST /api/v1/knowledgebases`
* `GET /api/v1/knowledgebases/{kb_id}`
* `PUT /api/v1/knowledgebases/{kb_id}`
* `DELETE /api/v1/knowledgebases/{kb_id}`
### 8\.3 Documents
* `GET /api/v1/knowledgebases/{kb_id}/documents`
* `POST /api/v1/knowledgebases/{kb_id}/documents` \(multipart upload\)
* `GET /api/v1/documents/{doc_id}`
* `DELETE /api/v1/documents/{doc_id}`
* `GET /api/v1/documents/{doc_id}/chunks`
### 8\.4 Chat
* `POST /api/v1/chat/sessions`
* `GET /api/v1/chat/sessions/{session_id}`
* `POST /api/v1/chat/sessions/{session_id}/messages`
* `GET /api/v1/chat/sessions/{session_id}/messages`
### 8\.5 Retrieval
* `POST /api/v1/knowledgebases/{kb_id}/search`
### 8\.6 Settings
* `GET /api/v1/settings/llm`
* `PUT /api/v1/settings/llm`
* `GET /api/v1/settings/embedding`
* `PUT /api/v1/settings/embedding`
## 9\. Chunking Template Behavior Specification
### 9\.1 General Template \(naive\.py behavior\)
**Input**: Any supported document format  
**Process**:
1. Parse document using DeepDoc \(PDF\) or format\-specific parser
2. Extract text sections with position tags
3. Extract tables as HTML
4. Apply naive\_merge: concatenate sections until token limit reached
5. Split on configured delimiters when token limit exceeded
6. Tokenize chunks with document metadata
**Output**: List of chunks with content, tokens, position info
### 9\.2 Laws Template \(laws\.py behavior\)
**Input**: DOCX, PDF, TXT, MD, HTML  
**Process**:
1. Parse document and extract raw sections
2. Remove table of contents
3. Detect bullet/numbering category
4. Apply colon\-based title detection
5. Build hierarchical tree structure
6. Merge sections using tree\_merge with depth=2
7. Tokenize with document metadata
**Output**: Hierarchically organized chunks preserving legal document structure
### 9\.3 Paper Template \(paper\.py behavior\)
**Input**: PDF only  
**Process**:
1. Parse with DeepDoc PDF parser \(Paper mode\)
2. Extract title, authors from first page
3. Detect and preserve abstract as single chunk
4. Handle two\-column layouts
5. Detect section pivots using title frequency
6. Group content between pivots
7. Extract tables/figures with vision enhancement
**Output**: Structured chunks with paper metadata \(title, authors, abstract flag\)
## 10\. Acceptance Criteria
### 10\.1 Chunking Parity Testing
Derived sample documents from repository:
* **General**: README\.md content \(technical documentation\)
* **Laws**: docs/configurations\.md content \(structured with sections\)
* **Paper**: Use existing academic paper PDFs for validation
**Test Methodology**:
1. Process sample documents through current RAGFlow chunking
2. Capture output chunk boundaries and content
3. Process same documents through new system
4. Verify chunk content matches \(text equivalence\)
5. Verify chunk count is within 10% variance
6. Verify hierarchical structure preserved \(Laws template\)
### 10\.2 System Integration Tests
* End\-to\-end document upload → parse → index → retrieve → answer
* Multi\-tenant isolation verification
* Concurrent parsing load test
* API contract validation
## 11\. Technology Recommendations
### 11\.1 Backend
* Python 3\.10\+ with FastAPI
* SQLAlchemy for PostgreSQL ORM
* Celery/Redis for task queue
* elasticsearch\-py or opensearch\-py client
### 11\.2 Frontend
* React 18\+ with TypeScript
* Tailwind CSS or Ant Design
* React Query for API state
### 11\.3 Embeddings
* Default: Ollama with bge\-m3 or similar
* Alternative: vLLM for high\-throughput
* Optional: OpenAI text\-embedding\-3\-small
### 11\.4 LLM Integration
* LangChain or LiteLLM for provider abstraction
* Support: Ollama, vLLM, OpenAI, Anthropic, DeepSeek
## 12\. Migration Considerations
* Export existing knowledge bases via RAGFlow API
* Transform document metadata to new schema
* Re\-parse documents with new chunking \(recommended for parity\)
* Preserve user accounts and tenant mappings
## 13\. Open Questions
1. Should chunk position data include pixel coordinates or page\-only?
2. Preferred approach for embedding model hot\-swapping?
3. Chat history retention policy per tenant?
4. Maximum file size limits per document?
## 14\. Appendix
### A\. Sample Document Sources for Testing
**General Template Test**:
* Source: Repository README\.md \(lines 73\-135\)
* Content type: Technical documentation with lists, headings, links
**Laws Template Test**:
* Source: docs/configurations\.md \(lines 1\-130\)
* Content type: Structured configuration documentation with sections
**Paper Template Test**:
* Requires sample academic PDF with standard structure
* Must contain: title, authors, abstract, multi\-section body
### B\. Glossary
* **Chunk**: Atomic unit of text for indexing and retrieval
* **DeepDoc**: Document parsing library with OCR and layout recognition
* **Hybrid Search**: Combined vector similarity \+ keyword \(BM25\) retrieval
* **Tenant**: Isolated workspace for a team/organization
* **Knowledge Base**: Collection of documents with shared configuration
