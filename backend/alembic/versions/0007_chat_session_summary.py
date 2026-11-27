"""Running summary of long chat sessions.

chat_sessions.summary condenses the session's earlier messages; summary_through is the
created_at of the last message it covers. Prompts use the summary in place of those
messages (services/conversation_summary.py).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("chat_sessions", sa.Column("summary_through", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_sessions", "summary_through")
    op.drop_column("chat_sessions", "summary")
