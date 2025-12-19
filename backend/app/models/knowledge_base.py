from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_bases"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    parser_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list["Document"]] = relationship(back_populates="knowledge_base")


Index("ix_knowledge_bases_tenant_name", KnowledgeBase.tenant_id, KnowledgeBase.name)
