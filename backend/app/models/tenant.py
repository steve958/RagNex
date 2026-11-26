from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Per-tenant model overrides; keys not present fall back to server settings.
    # See backend/app/services/model_settings.py. May contain provider API keys, which are
    # never returned by the API.
    embedding_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    llm_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list["TenantMembership"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(back_populates="tenant")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="tenant")
    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="tenant")


Index("ix_tenants_owner_user_id", Tenant.owner_user_id)
