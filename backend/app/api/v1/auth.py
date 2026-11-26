from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.validation import NewPassword, Password
from backend.app.core.security import PasswordHasher, TokenService
from backend.app.models.tenant import Tenant
from backend.app.models.user import TenantMembership, User

from backend.app.core.rate_limit import limiter

router = APIRouter()

password_hasher = PasswordHasher()
token_service = TokenService()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: NewPassword  # 8-1024 characters


class LoginRequest(BaseModel):
    email: EmailStr
    password: Password  # no minimum, so accounts created before the rule can still log in


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str


@router.post("/register", response_model=TokenResponse)
@limiter.limit("10/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=req.email, password_hash=password_hasher.hash(req.password))
    db.add(user)
    await db.flush()

    # Create a default tenant for the new user.
    tenant = Tenant(name=f"{req.email}'s tenant", owner_user_id=user.id)
    db.add(tenant)
    await db.flush()

    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner")
    db.add(membership)

    await db.commit()

    access = token_service.create_access_token(user_id=user.id)
    refresh = token_service.create_refresh_token(user_id=user.id)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    res = await db.execute(select(User).where(User.email == req.email))
    user = res.scalar_one_or_none()
    if user is None or not password_hasher.verify(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access = token_service.create_access_token(user_id=user.id)
    refresh = token_service.create_refresh_token(user_id=user.id)
    return TokenResponse(access_token=access, refresh_token=refresh)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=4096)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, req: RefreshRequest) -> TokenResponse:
    try:
        payload = token_service.verify_token(req.refresh_token, expected_type="refresh")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    access = token_service.create_access_token(user_id=payload.user_id)
    refresh_tok = token_service.create_refresh_token(user_id=payload.user_id)
    return TokenResponse(access_token=access, refresh_token=refresh_tok)


@router.post("/logout")
async def logout() -> dict:
    # Stateless JWT: logout is a no-op unless we implement a token denylist.
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=current_user.id, email=current_user.email)
