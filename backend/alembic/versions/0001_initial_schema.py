"""Initial schema.

Revision ID: 0001
Revises: 
Create Date: 2025-12-18

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_tenants_owner_user_id", "tenants", ["owner_user_id"], unique=False)

    op.create_table(
        "tenant_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), server_default=sa.text("'member'"), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"], unique=False)
    op.create_index("ix_tenant_memberships_tenant_user", "tenant_memberships", ["tenant_id", "user_id"], unique=True)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template", sa.String(length=50), server_default=sa.text("'general'"), nullable=False),
        sa.Column("parser_config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"], unique=False)
    op.create_index("ix_knowledge_bases_tenant_name", "knowledge_bases", ["tenant_id", "name"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kb_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"], unique=False)
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"], unique=False)

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("position", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.UniqueConstraint("document_id", "seq", name="uq_chunks_document_seq"),
    )
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"], unique=False)
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("ix_chunks_document_seq", "chunks", ["document_id", "seq"], unique=True)
    op.create_index("ix_chunks_tenant_document", "chunks", ["tenant_id", "document_id"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
    )
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"], unique=False)
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)

    op.create_table(
        "chat_session_knowledge_bases",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kb_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"], unique=False)
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"], unique=False)
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"], unique=False)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)
    op.create_index("ix_api_keys_tenant_user", "api_keys", ["tenant_id", "user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_api_keys_tenant_user", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_table("chat_session_knowledge_bases")

    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("ix_chunks_tenant_document", table_name="chunks")
    op.drop_index("ix_chunks_document_seq", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_chunks_tenant_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_kb_id", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_knowledge_bases_tenant_name", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_tenant_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

    op.drop_index("ix_tenant_memberships_tenant_user", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")

    op.drop_index("ix_tenants_owner_user_id", table_name="tenants")
    op.drop_table("tenants")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
