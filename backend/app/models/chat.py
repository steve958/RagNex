from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


chat_session_knowledge_bases = Table(
    "chat_session_knowledge_bases",
    Base.metadata,
    sa.Column(
        "session_id",
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    sa.Column(
        "kb_id",
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
)


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "chat_sessions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="chat_sessions")
    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )

    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        secondary=chat_session_knowledge_bases,
        lazy="selectin",
    )


class ChatMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


Index("ix_chat_messages_session_created", ChatMessage.session_id, ChatMessage.created_at)
