"""Maintenance of secrets stored in the database (workspace model API keys).

    python -m backend.app.services.stored_secrets check       # can every stored key be read?
    python -m backend.app.services.stored_secrets reencrypt   # re-encrypt under the current key

To rotate RAGNEX_ENCRYPTION_KEY: set the new key, move the old one to
RAGNEX_ENCRYPTION_PREVIOUS_KEYS, restart, run `reencrypt`, then remove the old key.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.core.encryption import SecretUnavailable, decrypt, reencrypt
from backend.app.models.tenant import Tenant

_SECTIONS = ("llm_config", "embedding_config")


@dataclass
class Report:
    keys: int = 0
    rewritten: int = 0
    # (workspace id, "llm" or "embedding") for keys no configured key can decrypt.
    unreadable: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Stored API keys: {self.keys}, re-encrypted: {self.rewritten}, unreadable: {len(self.unreadable)}"]
        for tenant_id, section in self.unreadable:
            lines.append(f"  workspace {tenant_id}: {section} key can't be decrypted; its owner must enter it again")
        return "\n".join(lines)


async def run(*, rewrite: bool) -> Report:
    report = Report()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            tenants = (await db.execute(sa.select(Tenant))).scalars().all()
            for tenant in tenants:
                for section in _SECTIONS:
                    config = dict(getattr(tenant, section) or {})
                    stored = config.get("api_key")
                    if not stored:
                        continue
                    report.keys += 1
                    try:
                        if rewrite:
                            config["api_key"] = reencrypt(stored)
                            setattr(tenant, section, config)  # a new dict, so the change is saved
                            report.rewritten += 1
                        else:
                            decrypt(stored)
                    except SecretUnavailable:
                        report.unreadable.append((tenant.id, section.removesuffix("_config")))
            if rewrite:
                await db.commit()
    finally:
        await engine.dispose()
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["check", "reencrypt"])
    args = p.parse_args(argv)
    report = asyncio.run(run(rewrite=args.command == "reencrypt"))
    print(report.summary())
    return 1 if report.unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
