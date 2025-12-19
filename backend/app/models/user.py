from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")


class TenantMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


Index("ix_tenant_memberships_tenant_user", TenantMembership.tenant_id, TenantMembership.user_id, unique=True)
