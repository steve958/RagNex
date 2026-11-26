from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.api_keys import hash_api_key
from backend.app.core.tenant import TENANT_HEADER
from backend.app.core.db import get_db
from backend.app.core.security import TokenService
from backend.app.models.api_key import APIKey
from backend.app.models.user import TenantMembership, User


token_service = TokenService()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, description="Bearer <token>"),
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User:
    """Authenticate either via Bearer JWT or API key.

    - Bearer token takes precedence.
    - An API key is recorded on request.state.api_key: it is limited to its own tenant and
      scopes (see require_tenant_membership) and can't manage the account
      (see require_session_user).
    """
    request.state.api_key = None

    if authorization:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = token_service.verify_token(token, expected_type="access")
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid token")

        res = await db.execute(select(User).where(User.id == payload.user_id, User.deleted_at.is_(None)))
        user = res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    if api_key:
        key_hash = hash_api_key(api_key)
        res = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash, APIKey.revoked_at.is_(None)))
        row = res.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        res = await db.execute(select(User).where(User.id == row.user_id, User.deleted_at.is_(None)))
        user = res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        request.state.api_key = row
        return user

    raise HTTPException(status_code=401, detail="Missing credentials")


async def require_session_user(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """For account management (workspaces, members, model settings, API keys): requires a
    signed-in user. An API key can't mint more keys or change who has access."""
    if getattr(request.state, "api_key", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This endpoint requires signing in; API keys can't use it"
        )
    return current_user


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _api_key_allows(request: Request, scopes: list[str], *, read_only: bool) -> bool:
    """`read`: reading requests. `write`: everything (implies read)."""
    granted = set(scopes or [])
    if "write" in granted:
        return True
    return "read" in granted and (read_only or request.method in _SAFE_METHODS)


async def _check_tenant_access(
    request: Request, current_user: User, db: AsyncSession, *, read_only: bool
) -> tuple[uuid.UUID, User]:
    tenant_id: uuid.UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        if request.headers.get(TENANT_HEADER):
            raise HTTPException(status_code=400, detail=f"Invalid {TENANT_HEADER} header (expected a UUID)")
        raise HTTPException(status_code=400, detail=f"Missing {TENANT_HEADER} header")

    key: APIKey | None = getattr(request.state, "api_key", None)
    if key is not None:
        # A key belongs to one tenant, even if its user is a member of others.
        if key.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is not valid for this tenant")
        if not _api_key_allows(request, key.scopes, read_only=read_only):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key scopes {sorted(key.scopes or []) or '(none)'} don't allow this request",
            )

    res = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == current_user.id,
        )
    )
    membership = res.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of tenant")

    return tenant_id, current_user


async def require_tenant_membership(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[uuid.UUID, User]:
    """Tenant from the X-Tenant-ID header, checked against membership and, for API keys, the
    key's tenant and scopes (GET needs `read`; other methods need `write`)."""
    return await _check_tenant_access(request, current_user, db, read_only=False)


async def require_tenant_read(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[uuid.UUID, User]:
    """Like require_tenant_membership, for POST endpoints that only read (e.g. search), so a
    read-scoped API key may call them."""
    return await _check_tenant_access(request, current_user, db, read_only=True)
