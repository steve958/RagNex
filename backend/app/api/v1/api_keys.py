from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.api_keys import generate_api_key, hash_api_key
from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.core.deps import require_tenant_membership
from backend.app.models.api_key import APIKey

router = APIRouter()


class CreateAPIKeyRequest(BaseModel):
    name: str
    scopes: list[str] = []


class APIKeyCreatedResponse(BaseModel):
    api_key: str
    id: uuid.UUID


@router.post("/api-keys", response_model=APIKeyCreatedResponse)
async def create_api_key(
    req: CreateAPIKeyRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    tenant_id, user = ctx

    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    row = APIKey(tenant_id=tenant_id, user_id=user.id, name=req.name, key_hash=key_hash, scopes=req.scopes)
    db.add(row)
    await db.commit()

    return APIKeyCreatedResponse(api_key=api_key, id=row.id)


@router.get("/api-keys")
async def list_api_keys(
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, user = ctx
    res = await db.execute(select(APIKey).where(APIKey.tenant_id == tenant_id, APIKey.user_id == user.id))
    keys = res.scalars().all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "scopes": k.scopes,
            "revoked_at": k.revoked_at,
            "created_at": k.created_at,
        }
        for k in keys
    ]


class RevokeAPIKeyRequest(BaseModel):
    id: uuid.UUID


@router.post("/api-keys/revoke")
async def revoke_api_key(
    req: RevokeAPIKeyRequest,
    ctx=Depends(require_tenant_membership),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, user = ctx
    res = await db.execute(
        select(APIKey).where(APIKey.id == req.id, APIKey.tenant_id == tenant_id, APIKey.user_id == user.id)
    )
    k = res.scalar_one_or_none()
    if k is None:
        raise HTTPException(status_code=404, detail="API key not found")

    from datetime import datetime, timezone

    k.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


