# Configuration reference

Every setting RagNex reads, what it does, and what to watch out for when changing it.
For secrets and going live, see [deployment.md](deployment.md).

## How settings are read

- **Backend (API and worker):** from environment variables, or from a `.env` file in the
  repository root. Environment variables win over `.env`. Names are not case-sensitive.
  The API and the worker must have the same settings.
- **Docker (`docker-compose.prod.yml`):** settings come from `.env.prod`, but **only the
  variables listed in the compose file reach the containers.** The "Prod compose" column
  below says which ones are passed through. To set any other backend setting, add it to the
  `x-backend` → `environment` list in `docker-compose.prod.yml`.
- **Lists** (`CORS_ORIGINS`, `TENANT_MODEL_BASE_URLS`) are JSON:
  `TENANT_MODEL_BASE_URLS='["http://gpu-box:11434"]'`.
- **Startup checks:** the backend refuses to start without a strong `JWT_SECRET`. Other
  mistakes (a wrong URL or password) show up as failures on `GET /health`.

## Required

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `JWT_SECRET` | none | required | Signs login tokens. Must be random and at least 32 bytes; known weak values like `change-me` are rejected. Generate one with `openssl rand -hex 32`. Changing it signs everyone out (see [rotation](deployment.md#rotating-secrets)). |
| `RAGNEX_ENCRYPTION_KEY` | none | required | Encrypts the model API keys workspace owners save in Settings. 32 random bytes in base64: generate with `openssl rand -base64 32`. **Keep a copy with your backups:** without it, stored keys can't be decrypted and owners have to enter them again. To change it, see [rotation](deployment.md#rotating-the-encryption-key). |
| `RAGNEX_ENCRYPTION_PREVIOUS_KEYS` | `[]` | yes | Old encryption keys still accepted for reading, as a JSON list, while rotating to a new `RAGNEX_ENCRYPTION_KEY`. Empty otherwise. |
| `POSTGRES_PASSWORD` | none in prod, `ragnex` in dev | required | Database password. It is only applied **when the database volume is first created**; see [rotation](deployment.md#rotating-secrets) to change it later. |
| `MINIO_ROOT_PASSWORD` | none in prod, `minioadmin` in dev | required | Object storage password. Prod compose passes it to the backend as `S3_SECRET_KEY`. |
| `OPENSEARCH_INITIAL_ADMIN_PASSWORD` | none in prod | required | Demanded by the OpenSearch image at first start (8+ characters with upper, lower, digit and symbol, not resembling `admin`, or OpenSearch exits). RagNex doesn't use it: the bundled OpenSearch has its security plugin off and is reachable only on the internal network. |

## Models

The server-wide defaults. Workspace owners can override some of them in **Settings**,
within the limits described under [Workspace model overrides](#workspace-model-overrides).

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `LLM_PROVIDER` | `ollama` | yes | `ollama`, `openai` or `vllm`. `openai` works with any OpenAI-compatible API (for example DeepSeek, with `OPENAI_BASE_URL` set to its endpoint). |
| `LLM_MODEL` | `llama3` | yes | Model name as the provider knows it. For Ollama, pull it first (`ollama pull llama3`). |
| `LLM_CONTEXT_WINDOW` | `8192` | yes | The model's total context size in tokens (prompt plus answer). Chat prompts are trimmed to fit, so **set this to the model's real context size**. Too high and long chats fail; too low and answers use less of your documents than they could. |
| `LLM_MAX_TOKENS` | `2048` | yes | Most tokens an answer may use. This much of the context window is kept free for the answer. |
| `LLM_TEMPERATURE` | `0.2` | yes | 0 to 2. Low values keep answers close to the documents. |
| `EMBEDDING_PROVIDER` | `ollama` | yes | `ollama`, `openai` or `vllm`. |
| `EMBEDDING_MODEL` | `bge-m3` | yes | Model that turns text into vectors for search. |
| `EMBEDDING_DIMENSION` | `1024` | yes | Vector size the model produces (`bge-m3`: 1024, OpenAI `text-embedding-3-small`: 1536). **Must match the model.** It is fixed into the search index when a workspace's index is created, so changing it (or the model) later means deleting the workspaces' indices and reprocessing every document. |
| `EMBEDDING_BATCH_SIZE` | `32` | yes | Texts sent per embedding request. |
| `EMBEDDING_RPS` | `5` | yes | Embedding requests per second, per worker process. `0` means no limit. Lower it if a hosted provider rate-limits you. |
| `EMBEDDING_CACHE_TTL_S` | `86400` | no | How long computed vectors are cached in Redis, in seconds. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | yes (default `http://host.docker.internal:11434`) | Ollama server. In Docker, `host.docker.internal` is the host machine. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | yes | Endpoint for the `openai` provider. |
| `OPENAI_API_KEY` | empty | yes | Key for the `openai` provider. Never sent to vLLM servers. |
| `VLLM_BASE_URL` | empty | yes | Endpoint for the `vllm` provider (OpenAI-compatible, e.g. `http://gpu-box:8000/v1`). Required when a provider is `vllm`. The server has no vLLM key setting: use a vLLM server that doesn't require one, or have the workspace owner set a key in Settings. |

### Re-ranking

Optional. A re-ranker is a second model that reads the question together with each of the
best search candidates and re-scores them, which usually improves which passages an answer
is built from. It runs as a separate service; see [deployment.md](deployment.md#re-ranking).

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `RERANK_PROVIDER` | `none` | yes | `none` (off), `tei` (Hugging Face Text Embeddings Inference, as in the bundled `reranker` service) or `cohere` (the common `/rerank` API served by vLLM, Infinity, Jina and Cohere). |
| `RERANK_BASE_URL` | empty | yes | The service's address; RagNex calls `{RERANK_BASE_URL}/rerank`. For the bundled service: `http://reranker`. Re-ranking stays off while it's empty. |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | yes | Model name sent to `cohere`-style services. TEI serves the one model it was started with (`RERANK_TEI_MODEL` for the bundled service). |
| `RERANK_API_KEY` | empty | yes | Sent as a bearer token, for hosted services. |
| `RERANK_CANDIDATES` | `15` | yes | How many search candidates are re-scored. More can find better passages but takes longer: with the bundled model on 8 CPU cores, about 3 s for 15 and 8 s for 30. |
| `RERANK_TIMEOUT_S` | `30` | no | Seconds to wait for the re-ranker. |
| `RERANK_TEI_MODEL` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | compose only | Model the bundled `reranker` service loads: small, multilingual and practical on CPU. |

If the re-ranker fails or times out, search uses its normal order and logs a warning, so
chat keeps working.

### Workspace model overrides

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `TENANT_MODEL_BASE_URLS` | `[]` | yes | Endpoints workspace owners may point their model settings at, as a JSON list. Matched exactly (a trailing `/` is ignored). Empty means owners can change models and keys but always use the server's endpoints. **List only endpoints you trust:** the server sends requests to any URL listed here on a workspace's behalf. |

Without any server setting, workspace owners can change: chat provider, model,
temperature, answer length, context window; embedding provider and model; and API keys
for these. Limits that always apply:

- A workspace that switches to `openai` while the server default is another provider must
  supply its own API key, so it can't run on (and bill) the server's key.
- The embedding model is test-called to check its vector size matches the search index,
  and can't be changed while the workspace has indexed documents.

## Data stores

Prod compose sets all of these itself, for the bundled containers. Set them only when you
use your own services.

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://ragnex:ragnex@localhost:5432/ragnex` | built from `POSTGRES_*` | Must use the `postgresql+asyncpg://` scheme. |
| `POSTGRES_USER`, `POSTGRES_DB` | `ragnex` | yes | Used by the Postgres container and to build `DATABASE_URL`. Like the password, they only apply when the volume is first created. |
| `REDIS_URL` | `redis://localhost:6379/0` | set to the bundled Redis | Task queue, task results, the embedding cache and rate-limit counts. |
| `OPENSEARCH_URL` | `http://localhost:9200` | set to the bundled OpenSearch | Search engine. Elasticsearch isn't supported: RagNex uses OpenSearch's k-NN and index lifecycle features. |
| `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD` | empty | no | Basic auth, for a cluster with security enabled. |
| `OPENSEARCH_VERIFY_CERTS` | `true` | no | Check the server certificate on `https://` URLs. Turn off only for a test cluster with a self-signed certificate. |
| `OPENSEARCH_CHUNKS_ROLLOVER_MIN_SIZE` | `30gb` | no | A workspace's search index moves on to a new backing index when it reaches this size, keeping each one a healthy size. Indices are never deleted automatically. Takes effect on existing indices at the next backend start. |
| `OPENSEARCH_CHUNKS_POLICY_ID` | `ragnex-chunks-policy` | no | Name of that lifecycle policy in OpenSearch. Only change it if the name clashes with something else in a shared cluster. |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | set to the bundled MinIO | S3-compatible storage for uploaded files. Each workspace gets its own bucket (`tenant-<id>`). An `https://` URL uses TLS. |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | `minioadmin` | from `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Storage credentials. They need permission to create buckets. |
| `S3_REGION` | `us-east-1` | no | Region, for providers that need one. |
| `S3_SECURE` | `false` | no | Force TLS for an endpoint given without a scheme. |
| `MINIO_ROOT_USER` | `ragnex` in prod, `minioadmin` in dev | yes | Bundled MinIO's user, and the backend's `S3_ACCESS_KEY`. |

## Sign-in and access

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `ACCESS_TOKEN_EXPIRES_MINUTES` | `30` | yes | How long a login token lasts. The web app renews it automatically. |
| `REFRESH_TOKEN_EXPIRES_DAYS` | `14` | yes | How long a user stays signed in without logging in again. |
| `REGISTRATION_ENABLED` | `true` | yes | Whether anyone who can reach the site can create an account (each gets a workspace of their own). When off, accounts are created with the `create-user` command ([deployment.md](deployment.md#creating-accounts)). Existing users can always log in. |
| `REGISTRATION_EMAIL_DOMAINS` | `[]` | yes | When set, only addresses at exactly these domains can sign up, as a JSON list (`["example.com"]`). Subdomains aren't included: list them separately. Ignored when sign-up is off. |
| `JWT_ALGORITHM` | `HS256` | no | `HS256`, `HS384` or `HS512`. Algorithms using key pairs (`RS256` and similar) don't work with a shared secret. |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | yes (default `[]`) | Browser origins allowed to call the API from another site, as a JSON list. Not needed when the web app is served through the bundled nginx or the Vite dev proxy. |

The API header names are fixed: `X-Tenant-ID` selects the workspace and `X-API-Key` carries
an API key.

## Uploads

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `MAX_UPLOAD_SIZE_MB` | `100` | yes (also sets nginx's limit) | Largest file accepted. A reverse proxy in front of RagNex needs a limit at least this large too, or it rejects big uploads first. |

## Running the services

| Variable | Default | Prod compose | Notes |
|---|---|---|---|
| `LOG_LEVEL` | `INFO` | yes | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs are JSON lines on stdout. |
| `API_WORKERS` | `2` | yes | API processes. Rate limits (20 logins and 10 registrations a minute per address) are counted in Redis, so they hold however many processes run. If Redis is unreachable, each process counts on its own until it's back. |
| `WORKER_CONCURRENCY` | `2` | yes | Documents processed in parallel by the worker container. Parsing PDFs is CPU- and memory-heavy: raise it with care. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (prod compose: `*`) | set by compose | Which peers the API trusts for the client IP header. Compose trusts all, which is safe only because the API port is internal and nginx rewrites that header. |
| `PORT` | `8000` | no | API port inside its container. |

Prod compose only:

| Variable | Default | Notes |
|---|---|---|
| `RAGNEX_HTTP_PORT` | `8080` | Port the web app is published on. Use `127.0.0.1:8080` to accept connections only from the same machine (for a TLS proxy there). |
| `RAGNEX_TRUSTED_PROXY` | `127.0.0.1/32` (none) | Address or CIDR of your reverse proxy, as seen by the `frontend` container. Only that proxy's `X-Forwarded-For` is believed. See [deployment.md](deployment.md#reverse-proxy-and-tls). |
| `RAGNEX_IMAGE_PREFIX` | empty | Registry path to pull images from, ending in `/` (for example `ghcr.io/OWNER/`, for the images CI publishes). Empty means images built locally with `up --build`. |
| `RAGNEX_VERSION` | `latest` | Image tag: `latest`, a release such as `1.2.3`, or a commit such as `sha-abc1234`. |
| `OPENSEARCH_HEAP` | `1g` | OpenSearch memory. About half the memory you give OpenSearch, and no more than 31g. |

## Web app

| Variable | When | Notes |
|---|---|---|
| `VITE_API_URL` | build time | API origin the web app calls. Empty (default) means the same origin, which is the case behind the bundled nginx. Only set it when the API is on a different origin, and add the web app's origin to `CORS_ORIGINS`. |
| `VITE_API_PROXY_TARGET` | `npm run dev` | Where the dev server forwards `/api` (default `http://localhost:8000`). |
| `RAGNEX_API_UPSTREAM` | frontend container | API address nginx forwards to (default `api:8000`). |
| `RAGNEX_MAX_UPLOAD_MB` | frontend container | nginx's upload limit. Prod compose sets it from `MAX_UPLOAD_SIZE_MB`. |

## Tests only

| Variable | Default | Notes |
|---|---|---|
| `CELERY_TASK_ALWAYS_EAGER` | `false` | Run background tasks inside the API process instead of the worker. For tests; never in production. |
| `CELERY_TASK_EAGER_PROPAGATES` | `true` | With the above, raise task errors in the caller. |
