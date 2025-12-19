"""Indexing and embedding config fields.

Revision ID: 0003
Revises: 0002
Create Date: 2025-12-18

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenant embedding config (P3-2)
    op.add_column(
        "tenants",
        sa.Column(
            "embedding_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # Document indexing progress / status (P3-3)
    op.add_column("documents", sa.Column("index_task_id", sa.String(length=255), nullable=True))
    op.add_column(
        "documents",
        sa.Column("index_progress", sa.Float(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("documents", sa.Column("index_message", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("index_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("index_completed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_documents_index_task_id", "documents", ["index_task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_index_task_id", table_name="documents")

    op.drop_column("documents", "index_completed_at")
    op.drop_column("documents", "index_started_at")
    op.drop_column("documents", "index_message")
    op.drop_column("documents", "index_progress")
    op.drop_column("documents", "index_task_id")

    op.drop_column("tenants", "embedding_config")
