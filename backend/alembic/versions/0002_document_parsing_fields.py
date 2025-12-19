"""Document parsing fields.

Revision ID: 0002
Revises: 0001
Create Date: 2025-12-18

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("parse_task_id", sa.String(length=255), nullable=True))
    op.add_column(
        "documents",
        sa.Column("parse_progress", sa.Float(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("documents", sa.Column("parse_message", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("parsed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("documents", sa.Column("parse_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("parse_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_documents_parse_task_id", "documents", ["parse_task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_parse_task_id", table_name="documents")
    op.drop_column("documents", "parse_completed_at")
    op.drop_column("documents", "parse_started_at")
    op.drop_column("documents", "parsed_data")
    op.drop_column("documents", "parse_message")
    op.drop_column("documents", "parse_progress")
    op.drop_column("documents", "parse_task_id")
