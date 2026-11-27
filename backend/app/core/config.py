from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://ragnex:ragnex@localhost:5432/ragnex"
    redis_url: str = "redis://localhost:6379/0"
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    # Only matters for https:// URLs. On by default: off would accept any certificate.
    opensearch_verify_certs: bool = True

    # Chunk index lifecycle (OpenSearch ISM). A tenant's chunk index rolls over to a new
    # backing index once it reaches this size; indices are never deleted automatically.
    opensearch_chunks_policy_id: str = "ragnex-chunks-policy"
    opensearch_chunks_rollover_min_size: str = "30gb"

    # Celery
    celery_task_always_eager: bool = False
    celery_task_eager_propagates: bool = True

    # Auth. JWT_SECRET signs every login token: anyone who knows or guesses it can log in as
    # any user. It has no default and must be at least 32 bytes (checked below).
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 30
    refresh_token_expires_days: int = 14

    # Encrypts secrets stored in the database (workspace model API keys); see
    # core/encryption.py. Required: 32 random bytes in base64 (openssl rand -base64 32).
    # Losing it makes stored keys unreadable (owners re-enter them). Previous keys: JSON list
    # of old keys still accepted for decryption, during a rotation.
    ragnex_encryption_key: str = ""
    ragnex_encryption_previous_keys: list[str] = []

    # Self sign-up. Off: only operators create accounts (backend.app.services.accounts).
    # Email domains (JSON list, e.g. ["example.com"]): when set, only addresses at exactly
    # these domains may sign up.
    registration_enabled: bool = True
    registration_email_domains: list[str] = []

    # Browser origins allowed to call the API cross-origin (JSON list in env, e.g.
    # CORS_ORIGINS='["https://app.example.com"]'). Not needed when the frontend is served
    # from the same origin or through the Vite dev proxy.
    cors_origins: list[str] = ["http://localhost:5173"]

    # Upload limits
    max_upload_size_mb: int = 100

    # Embeddings (P3-2)
    embedding_provider: str = "ollama"  # ollama|openai|vllm
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 32
    embedding_rps: float = 5.0
    embedding_cache_ttl_s: int = 24 * 3600

    # OpenAI-compatible HTTP endpoints (embeddings + chat)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str | None = None

    # Base URLs tenant owners may point their LLM/embedding settings at (exact match after
    # trimming a trailing "/"). Empty = tenants can't set a custom base URL and always use
    # the server's endpoints. Letting tenants pick arbitrary URLs would let them make the
    # server send requests to internal addresses (SSRF), so only list trusted endpoints.
    tenant_model_base_urls: list[str] = []

    # LLM defaults (P4-1)
    llm_provider: str = "ollama"  # ollama|openai|vllm (others can be added later)
    llm_model: str = "llama3"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    # Total tokens the model accepts (prompt + answer). Chat prompts are trimmed to fit,
    # keeping llm_max_tokens free for the answer. Set this to the model's real context size.
    llm_context_window: int = 8192

    # S3-compatible storage (MinIO)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_secure: bool = False


    @field_validator("jwt_secret")
    @classmethod
    def _require_strong_jwt_secret(cls, value: str) -> str:
        # HS256 keys shorter than the hash output (32 bytes) can be brute-forced offline from
        # any issued token (RFC 7518 §3.2). "change-me" was the old public default.
        if value in _KNOWN_WEAK_SECRETS or len(value.encode()) < 32:
            raise ValueError(
                "JWT_SECRET must be set to a random value of at least 32 bytes "
                "(generate one with: python -c \"import secrets; print(secrets.token_hex(32))\")."
            )
        return value


    @field_validator("ragnex_encryption_key")
    @classmethod
    def _require_encryption_key(cls, value: str) -> str:
        from backend.app.core.encryption import normalize_key

        if not value.strip():
            raise ValueError(
                "RAGNEX_ENCRYPTION_KEY must be set (generate one with: openssl rand -base64 32)."
            )
        try:
            normalize_key(value)
        except ValueError as e:
            raise ValueError(f"RAGNEX_ENCRYPTION_KEY {e}.") from None
        return value

    @field_validator("ragnex_encryption_previous_keys")
    @classmethod
    def _check_previous_keys(cls, value: list[str]) -> list[str]:
        from backend.app.core.encryption import normalize_key

        for i, key in enumerate(value):
            try:
                normalize_key(key)
            except ValueError as e:
                raise ValueError(f"RAGNEX_ENCRYPTION_PREVIOUS_KEYS entry {i + 1} {e}.") from None
        return value


_KNOWN_WEAK_SECRETS = {"", "change-me", "changeme", "secret"}

settings = Settings()
