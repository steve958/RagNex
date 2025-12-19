from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.api_keys import hash_api_key
from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.core.security import TokenService
from backend.app.models.api_key import APIKey
from backend.app.models.user import TenantMembership, User


token_service = TokenService()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, description="Bearer <token>"),
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User:
    """Authenticate either via Bearer JWT or API key.

    - Bearer token takes precedence.
    - API key authenticates the *user*; tenant context is still enforced separately.
    """

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
        return user

    raise HTTPException(status_code=401, detail="Missing credentials")


async def require_tenant_membership(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[uuid.UUID, User]:
    tenant_id: uuid.UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail=f"Missing {settings.tenant_header} header")

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
