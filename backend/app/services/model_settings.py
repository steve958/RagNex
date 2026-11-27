"""Per-tenant LLM and embedding settings.

A tenant stores only its overrides (Tenant.llm_config / Tenant.embedding_config); anything
not overridden falls back to the server settings. Rules enforced on update:

- base_url: only URLs on the server allowlist (settings.tenant_model_base_urls). Arbitrary
  URLs would let a tenant owner make the server call internal addresses (SSRF).
- api_key: write-only; never returned. Stored encrypted (core/encryption.py); only
  stored_api_key() decrypts it. A tenant that switches to OpenAI while the server
  default is another provider must bring its own key, so it can't run on (and bill) the
  operator's key.
- Embeddings: a new embedding model is test-called to check its vector size matches the
  search index, and can't be changed while the tenant has indexed documents (vectors from
  different models aren't comparable, so search would silently degrade).
"""

from __future__ import annotations

import uuid
from typing import Literal

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.encryption import SecretUnavailable, decrypt, encrypt
from backend.app.models.document import Document
from backend.app.models.tenant import Tenant
from backend.app.services.embeddings import EmbeddingConfig, create_embedding_service
from backend.app.services.llm import LLMConfig, default_llm_config

Provider = Literal["ollama", "openai", "vllm"]

LLM_KEYS = ("provider", "model", "temperature", "max_tokens", "context_window", "base_url")
EMBEDDING_KEYS = ("provider", "model", "base_url")
# Room the prompt needs besides the answer; see services/prompt_budget.py.
_MIN_PROMPT_TOKENS = 512


class SettingsError(ValueError):
    """An update that is invalid (422)."""


class SettingsConflict(ValueError):
    """An update that conflicts with existing data (409)."""


class LLMOverrides(BaseModel):
    """Requested LLM overrides. null/omitted fields use the server default.
    api_key: omitted = keep the stored key, null or "" = remove it, string = set it."""

    model_config = ConfigDict(extra="forbid")

    provider: Provider | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=65_536)
    context_window: int | None = Field(default=None, ge=1024, le=2_000_000)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class EmbeddingOverrides(BaseModel):
    """Requested embedding overrides; same conventions as LLMOverrides."""

    model_config = ConfigDict(extra="forbid")

    provider: Provider | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


# --- Effective configuration -------------------------------------------------------------


def stored_api_key(raw: dict) -> str | None:
    """The decrypted API key from a stored config section. Raises SecretUnavailable if it
    can't be decrypted."""
    value = raw.get("api_key")
    return decrypt(value) if value else None


def api_key_readable(raw: dict) -> bool:
    try:
        stored_api_key(raw)
    except SecretUnavailable:
        return False
    return True


def effective_llm_config(raw: dict, *, with_key: bool = True) -> LLMConfig:
    """Server defaults with the tenant's stored overrides applied. with_key=False leaves the
    API key out, for uses that don't call the model (so an unreadable key doesn't block them)."""
    updates = {k: raw[k] for k in LLM_KEYS if raw.get(k) is not None}
    if with_key and raw.get("api_key"):
        updates["api_key"] = stored_api_key(raw)
    return default_llm_config().model_copy(update=updates)


def effective_embedding_config(raw: dict, *, with_key: bool = True) -> EmbeddingConfig:
    """The embedding settings search and indexing use for a tenant's stored overrides."""
    return EmbeddingConfig(
        provider=raw.get("provider") or settings.embedding_provider,  # type: ignore[arg-type]
        model=raw.get("model") or settings.embedding_model,
        base_url=raw.get("base_url"),
        api_key=stored_api_key(raw) if with_key else None,
        timeout_s=float(raw.get("timeout_s") or 60.0),
        batch_size=int(raw.get("batch_size") or settings.embedding_batch_size),
        rps=float(raw.get("rps") or settings.embedding_rps),
        cache_ttl_s=int(raw.get("cache_ttl_s") or settings.embedding_cache_ttl_s),
    )


async def load_tenant_llm_config(db: AsyncSession, tenant_id: uuid.UUID) -> LLMConfig:
    raw = (await db.execute(sa.select(Tenant.llm_config).where(Tenant.id == tenant_id))).scalar_one_or_none()
    return effective_llm_config(raw or {})


# --- Updates -----------------------------------------------------------------------------


def _merge(current: dict, req: BaseModel, keys: tuple[str, ...]) -> dict:
    """New stored overrides: the managed keys come from the request (None = server default);
    other stored keys (e.g. embedding batch_size) are kept; api_key per its convention."""
    merged = {k: v for k in keys if (v := getattr(req, k)) is not None}
    merged |= {k: v for k, v in current.items() if k not in keys and k != "api_key"}
    if "api_key" in req.model_fields_set:
        if req.api_key:  # type: ignore[attr-defined]
            merged["api_key"] = encrypt(req.api_key)  # type: ignore[attr-defined]
    elif current.get("api_key"):
        merged["api_key"] = current["api_key"]
    if isinstance(merged.get("base_url"), str):
        merged["base_url"] = merged["base_url"].strip().rstrip("/")
    return merged


def _check_common(merged: dict, server_provider: str, what: str) -> None:
    base_url = merged.get("base_url")
    if base_url is not None:
        allowed = {u.strip().rstrip("/") for u in settings.tenant_model_base_urls}
        if base_url not in allowed:
            raise SettingsError(
                f"{what}: base URL {base_url!r} is not allowed. Ask the server administrator to "
                "add it to TENANT_MODEL_BASE_URLS."
            )
    provider = merged.get("provider") or server_provider
    if provider == "openai" and provider != server_provider and not merged.get("api_key"):
        raise SettingsError(f"{what}: an API key is required to use OpenAI with this workspace.")


def merge_llm_update(current: dict, req: LLMOverrides) -> dict:
    merged = _merge(current, req, LLM_KEYS)
    _check_common(merged, settings.llm_provider, "LLM")
    cfg = effective_llm_config(merged, with_key=False)
    if cfg.context_window < cfg.max_tokens + _MIN_PROMPT_TOKENS:
        raise SettingsError(
            f"LLM: context window ({cfg.context_window}) must exceed max answer tokens "
            f"({cfg.max_tokens}) by at least {_MIN_PROMPT_TOKENS}, or no room is left for the prompt."
        )
    return merged


async def _has_indexed_documents(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    q = sa.select(
        sa.exists().where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            Document.status.in_(("indexing", "indexed")),
        )
    )
    return bool((await db.execute(q)).scalar())


async def _probe_dimension(cfg: EmbeddingConfig) -> int:
    try:
        result = await create_embedding_service(cfg, cache=None).embed(["dimension check"])
    except Exception as e:  # noqa: BLE001 - any failure means the model can't be used
        if isinstance(e, httpx.HTTPStatusError):
            reason = f"the provider answered HTTP {e.response.status_code}"
        else:
            reason = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else 'no details'}"
        raise SettingsError(
            f"Embeddings: could not use model {cfg.model!r} ({reason}). Check that it exists and supports embeddings."
        ) from e
    return result.dimension


async def merge_embedding_update(
    db: AsyncSession, tenant_id: uuid.UUID, current: dict, req: EmbeddingOverrides
) -> dict:
    merged = _merge(current, req, EMBEDDING_KEYS)
    _check_common(merged, settings.embedding_provider, "Embeddings")

    before = effective_embedding_config(current, with_key=False)
    after = effective_embedding_config(merged, with_key=False)
    if (before.provider, before.model) != (after.provider, after.model):
        if await _has_indexed_documents(db, tenant_id):
            raise SettingsConflict(
                "Embeddings: the model can't be changed while this workspace has indexed documents; "
                "their vectors were made with the current model and would no longer match searches."
            )
        dim = await _probe_dimension(effective_embedding_config(merged))  # with the key
        if dim != settings.embedding_dimension:
            raise SettingsError(
                f"Embeddings: model {after.model!r} produces {dim}-dimensional vectors, but the "
                f"search index expects {settings.embedding_dimension}."
            )
    return merged


# --- What the API returns ----------------------------------------------------------------


def _section_view(raw: dict, effective: BaseModel, defaults: BaseModel, keys: tuple[str, ...]) -> dict:
    eff = {k: getattr(effective, k) for k in keys}
    # Server endpoints are infrastructure details; only show a base URL the tenant chose.
    eff["base_url"] = raw.get("base_url")
    return {
        "effective": eff,
        # What an empty field falls back to, so a UI can show it.
        "defaults": {k: getattr(defaults, k) for k in keys if k != "base_url"},
        "overrides": {k: raw[k] for k in keys if raw.get(k) is not None},
        "has_api_key": bool(raw.get("api_key")),
        # False when the stored key can't be decrypted (the server's encryption key changed):
        # the owner needs to enter it again.
        "api_key_readable": api_key_readable(raw),
    }


async def settings_view(db: AsyncSession, tenant: Tenant, *, can_edit: bool) -> dict:
    llm_raw, emb_raw = tenant.llm_config or {}, tenant.embedding_config or {}
    embedding = _section_view(
        emb_raw,
        effective_embedding_config(emb_raw, with_key=False),
        effective_embedding_config({}, with_key=False),
        EMBEDDING_KEYS,
    )
    embedding["locked"] = await _has_indexed_documents(db, tenant.id)
    embedding["dimension"] = settings.embedding_dimension
    return {
        "can_edit": can_edit,
        "allowed_base_urls": [u.strip().rstrip("/") for u in settings.tenant_model_base_urls],
        "llm": _section_view(llm_raw, effective_llm_config(llm_raw, with_key=False), default_llm_config(), LLM_KEYS),
        "embedding": embedding,
    }
