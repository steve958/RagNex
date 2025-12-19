from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://ragnex:ragnex@localhost:5432/ragnex"
    redis_url: str = "redis://localhost:6379/0"
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_verify_certs: bool = False

    # OpenSearch index lifecycle (ISM) for chunk indices (P3-1 deferred)
    opensearch_chunks_policy_id: str = "ragnex-chunks-policy"
    opensearch_chunks_rollover_min_size: str = "5gb"
    opensearch_chunks_rollover_min_age: str = "7d"
    opensearch_chunks_delete_min_age: str = "90d"

    # Celery
    celery_task_always_eager: bool = False
    celery_task_eager_propagates: bool = True

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 30
    refresh_token_expires_days: int = 14

    # API key auth
    api_key_header: str = "X-API-Key"

    # Tenant context
    tenant_header: str = "X-Tenant-ID"

    # Upload limits
    max_upload_size_mb: int = 100

    # Embeddings (P3-2)
    embedding_provider: str = "ollama"  # ollama|openai|vllm
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 32
    embedding_rps: float = 5.0
    embedding_cache_ttl_s: int = 24 * 3600

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str | None = None

    # S3-compatible storage (MinIO)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_secure: bool = False


settings = Settings()
