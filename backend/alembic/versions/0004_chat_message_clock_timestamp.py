"""Order chat messages by real insert time.

chat_messages.created_at defaulted to now(), which is the transaction start time, so a
question and its answer saved in one transaction got identical timestamps and their order
in history was undefined. clock_timestamp() is evaluated per row at insert time.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("chat_messages", "created_at", server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    op.alter_column("chat_messages", "created_at", server_default=sa.text("now()"))
