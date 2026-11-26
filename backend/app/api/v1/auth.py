from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.validation import NewPassword, Password
from backend.app.core.security import PasswordHasher, TokenService
from backend.app.models.user import User
from backend.app.services.accounts import AccountError, create_account, registration_allows

from backend.app.core.rate_limit import limiter

router = APIRouter()

password_hasher = PasswordHasher()
_DUMMY_HASH = password_hasher.hash("timing-equaliser-not-a-real-password")
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


class RegistrationInfo(BaseModel):
    enabled: bool
    # Empty = any address (when enabled).
    email_domains: list[str]


@router.get("/registration", response_model=RegistrationInfo)
async def registration_info() -> RegistrationInfo:
    """Whether self sign-up is open, so the web app can show or hide it. Public."""
    return RegistrationInfo(
        enabled=settings.registration_enabled,
        email_domains=[d.strip().lower().lstrip("@") for d in settings.registration_email_domains if d.strip()],
    )


@router.post("/register", response_model=TokenResponse)
@limiter.limit("10/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    if not settings.registration_enabled:
        raise HTTPException(status_code=403, detail="Sign-up is closed. Ask an administrator for an account.")
    if not registration_allows(req.email):
        raise HTTPException(status_code=403, detail="Sign-up isn't open to this email domain.")
    try:
        user = await create_account(db, req.email, req.password)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    access = token_service.create_access_token(user_id=user.id)
    refresh = token_service.create_refresh_token(user_id=user.id)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    res = await db.execute(select(User).where(User.email == req.email, User.deleted_at.is_(None)))
    user = res.scalar_one_or_none()
    # Verify against a dummy hash for unknown emails too, so response time doesn't reveal
    # which addresses have accounts.
    password_ok = password_hasher.verify(req.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok:
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
