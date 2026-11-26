"""Creating user accounts, for sign-up and for operators.

When sign-up is closed (REGISTRATION_ENABLED=false), operators create accounts with:

    python -m backend.app.services.accounts create-user alice@example.com
    python -m backend.app.services.accounts create-user bob@example.com --workspace <id> --role member

    python -m backend.app.services.accounts list-workspaces

Without --workspace the new user gets a workspace of their own, as with sign-up. With it,
they join that existing workspace instead. The password is asked for twice, or read from
standard input with --password-stdin (for scripts).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.core.security import PasswordHasher
from backend.app.core.validation import NewPassword
from backend.app.models.tenant import Tenant
from backend.app.models.user import TenantMembership, User


class AccountError(ValueError):
    """The account can't be created; the message says why."""


_hasher = PasswordHasher()
_email = TypeAdapter(EmailStr)
_password = TypeAdapter(NewPassword)


def registration_allows(email: str) -> bool:
    """Whether self sign-up accepts this address under the current settings."""
    if not settings.registration_enabled:
        return False
    domains = {d.strip().lower().lstrip("@") for d in settings.registration_email_domains if d.strip()}
    return not domains or email.rsplit("@", 1)[-1].lower() in domains


async def create_account(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    workspace_id: uuid.UUID | None = None,
    role: str = "member",
) -> User:
    """Create a user and either a workspace they own or a membership in `workspace_id`.
    Commits. Raises AccountError if the email is taken or the workspace doesn't exist."""
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise AccountError("Email already registered")
    if workspace_id is not None:
        found = await db.execute(select(Tenant.id).where(Tenant.id == workspace_id))
        if found.scalar_one_or_none() is None:
            raise AccountError(f"Workspace {workspace_id} not found")

    user = User(email=email, password_hash=_hasher.hash(password))
    db.add(user)
    await db.flush()

    if workspace_id is None:
        tenant = Tenant(name=f"{email}'s tenant", owner_user_id=user.id)
        db.add(tenant)
        await db.flush()
        db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner"))
    else:
        db.add(TenantMembership(tenant_id=workspace_id, user_id=user.id, role=role))

    await db.commit()
    return user


# --- Command line ------------------------------------------------------------------------


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        raise AccountError("Passwords don't match")
    return first


async def _list_workspaces() -> list[tuple[uuid.UUID, str, str | None]]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = await db.execute(
                select(Tenant.id, Tenant.name, User.email)
                .outerjoin(User, User.id == Tenant.owner_user_id)
                .order_by(Tenant.created_at)
            )
            return [tuple(r) for r in rows]
    finally:
        await engine.dispose()


async def _create(email: str, password: str, workspace_id: uuid.UUID | None, role: str) -> User:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await create_account(db, email, password, workspace_id=workspace_id, role=role)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create-user", help="create a user account")
    c.add_argument("email")
    c.add_argument("--workspace", type=uuid.UUID, default=None, help="join this workspace instead of getting a new one")
    c.add_argument("--role", choices=["member", "owner"], default="member", help="role in --workspace (default: member)")
    c.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    sub.add_parser("list-workspaces", help="list workspaces with their IDs and creators")
    args = p.parse_args(argv)

    if args.command == "list-workspaces":
        for workspace_id, name, creator in asyncio.run(_list_workspaces()):
            print(f"{workspace_id}  {name}  (created by {creator or 'unknown'})")
        return 0

    if args.role != "member" and args.workspace is None:
        p.error("--role requires --workspace")
    try:
        email = _email.validate_python(args.email)
        password = _password.validate_python(_read_password(args.password_stdin))
    except ValidationError as e:
        print(f"Error: {e.errors()[0]['msg']}", file=sys.stderr)
        return 1
    except AccountError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        user = asyncio.run(_create(email, password, args.workspace, args.role))
    except AccountError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    where = f"joined workspace {args.workspace} as {args.role}" if args.workspace else "with a new workspace"
    print(f"Created {user.email} ({user.id}), {where}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
