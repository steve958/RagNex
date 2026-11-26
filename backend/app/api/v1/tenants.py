from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
import anyio
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db
from backend.app.core.deps import get_current_user
from backend.app.models.tenant import Tenant
from backend.app.models.user import TenantMembership, User
from backend.app.services.opensearch import OpenSearchService
from backend.app.services.model_settings import (
    EmbeddingOverrides,
    LLMOverrides,
    SettingsConflict,
    SettingsError,
    merge_embedding_update,
    merge_llm_update,
    settings_view,
)

router = APIRouter(prefix="/tenants")


class TenantCreateRequest(BaseModel):
    name: str


class TenantUpdateRequest(BaseModel):
    name: str


@router.post("", response_model=dict)
async def create_tenant(
    req: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant = Tenant(name=req.name, owner_user_id=current_user.id)
    db.add(tenant)
    await db.flush()

    membership = TenantMembership(tenant_id=tenant.id, user_id=current_user.id, role="owner")
    db.add(membership)

    await db.commit()

    # Ensure search index exists for this tenant (best-effort).
    try:
        svc = OpenSearchService()
        await anyio.to_thread.run_sync(lambda: svc.ensure_index(tenant.id))
    except Exception:
        pass

    return {"id": tenant.id, "name": tenant.name}


@router.get("", response_model=list[dict])
async def list_tenants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Tenant).join(TenantMembership, TenantMembership.tenant_id == Tenant.id).where(
            TenantMembership.user_id == current_user.id,
            Tenant.deleted_at.is_(None),
        )
    )
    tenants = res.scalars().all()
    return [{"id": t.id, "name": t.name} for t in tenants]


async def _require_membership(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> TenantMembership:
    res = await db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id)
    )
    membership = res.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of tenant")
    return membership


@router.get("/{tenant_id}", response_model=dict)
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(db, tenant_id, current_user.id)
    res = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"id": tenant.id, "name": tenant.name, "owner_user_id": tenant.owner_user_id}


@router.put("/{tenant_id}", response_model=dict)
async def update_tenant(
    tenant_id: uuid.UUID,
    req: TenantUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _require_membership(db, tenant_id, current_user.id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can update tenant")

    res = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.name = req.name
    await db.commit()
    return {"id": tenant.id, "name": tenant.name}


@router.delete("/{tenant_id}", response_model=dict)
async def delete_tenant(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _require_membership(db, tenant_id, current_user.id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can delete tenant")

    res = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Hard delete for now (schema supports soft-delete; can switch later)
    await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await db.commit()
    return {"ok": True}


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: str = "member"  # member | owner


@router.post("/{tenant_id}/members", response_model=dict)
async def add_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cur = await _require_membership(db, tenant_id, current_user.id)
    if cur.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can add members")

    # ensure user exists
    res = await db.execute(select(User).where(User.id == req.user_id, User.deleted_at.is_(None)))
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    # upsert membership
    res = await db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == req.user_id)
    )
    m = res.scalar_one_or_none()
    if m is None:
        m = TenantMembership(tenant_id=tenant_id, user_id=req.user_id, role=req.role)
        db.add(m)
    else:
        m.role = req.role

    await db.commit()
    return {"ok": True}


@router.delete("/{tenant_id}/members/{user_id}", response_model=dict)
async def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cur = await _require_membership(db, tenant_id, current_user.id)
    if cur.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can remove members")

    # prevent removing last owner
    owners = await db.execute(
        select(func.count()).select_from(TenantMembership).where(TenantMembership.tenant_id == tenant_id, TenantMembership.role == "owner")
    )
    owner_count = int(owners.scalar_one())

    res = await db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id)
    )
    m = res.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    if m.role == "owner" and owner_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove last owner")

    await db.execute(delete(TenantMembership).where(TenantMembership.id == m.id))
    await db.commit()
    return {"ok": True}


class UpdateMemberRequest(BaseModel):
    role: str


@router.put("/{tenant_id}/members/{user_id}", response_model=dict)
async def update_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cur = await _require_membership(db, tenant_id, current_user.id)
    if cur.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can update member roles")

    res = await db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id)
    )
    m = res.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    m.role = req.role
    await db.commit()
    return {"ok": True}


# --- Model settings ----------------------------------------------------------------------


class ModelSettingsUpdate(BaseModel):
    """Omit a section to leave it unchanged. See services/model_settings.py for the rules."""

    llm: LLMOverrides | None = None
    embedding: EmbeddingOverrides | None = None


async def _load_live_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/{tenant_id}/model-settings", response_model=dict)
async def get_model_settings(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Effective LLM/embedding settings and the tenant's overrides. API keys are never returned."""
    membership = await _require_membership(db, tenant_id, current_user.id)
    tenant = await _load_live_tenant(db, tenant_id)
    return await settings_view(db, tenant, can_edit=membership.role == "owner")


@router.put("/{tenant_id}/model-settings", response_model=dict)
async def update_model_settings(
    tenant_id: uuid.UUID,
    req: ModelSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _require_membership(db, tenant_id, current_user.id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can change model settings")
    tenant = await _load_live_tenant(db, tenant_id)

    try:
        if req.llm is not None:
            tenant.llm_config = merge_llm_update(tenant.llm_config or {}, req.llm)
        if req.embedding is not None:
            tenant.embedding_config = await merge_embedding_update(
                db, tenant.id, tenant.embedding_config or {}, req.embedding
            )
    except SettingsConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await db.commit()
    await db.refresh(tenant)
    return await settings_view(db, tenant, can_edit=True)
