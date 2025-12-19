from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parsing progress / results (P2-2)
    parse_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parse_progress: Mapped[float] = mapped_column(sa.Float(), server_default="0", nullable=False)  # type: ignore[name-defined]
    parse_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parse_started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Indexing progress / results (P3-3)
    index_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    index_progress: Mapped[float] = mapped_column(sa.Float(), server_default="0", nullable=False)  # type: ignore[name-defined]
    index_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chunks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")


Index("ix_chunks_document_seq", Chunk.document_id, Chunk.seq, unique=True)
Index("ix_chunks_tenant_document", Chunk.tenant_id, Chunk.document_id)
