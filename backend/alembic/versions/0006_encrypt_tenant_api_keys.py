"""Encrypt workspace model API keys stored in tenants.llm_config / embedding_config.

Needs RAGNEX_ENCRYPTION_KEY (the backend refuses to start without it anyway). Downgrading
decrypts them back to plain text, which needs the same key; a key that can't be decrypted
is left as it is (its owner has to enter it again either way).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from backend.app.core.encryption import SecretUnavailable, decrypt, encrypt, is_encrypted

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_tenants = sa.table(
    "tenants",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("llm_config", postgresql.JSONB),
    sa.column("embedding_config", postgresql.JSONB),
)
_SECTIONS = ("llm_config", "embedding_config")


def _convert(transform) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.select(_tenants.c.id, *(_tenants.c[s] for s in _SECTIONS))).all()
    for row in rows:
        updates = {}
        for section in _SECTIONS:
            config = dict(getattr(row, section) or {})
            key = config.get("api_key")
            if not key:
                continue
            new = transform(key)
            if new != key:
                config["api_key"] = new
                updates[section] = config
        if updates:
            conn.execute(sa.update(_tenants).where(_tenants.c.id == row.id).values(**updates))


def upgrade() -> None:
    _convert(lambda key: key if is_encrypted(key) else encrypt(key))


def _decrypt_if_possible(key: str) -> str:
    try:
        return decrypt(key)
    except SecretUnavailable:
        return key


def downgrade() -> None:
    _convert(_decrypt_if_possible)
