from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from backend.app.core.config import settings


class PasswordHasher:
    def __init__(self) -> None:
        # Prefer argon2 (no 72-byte bcrypt limit; fewer Windows/passlib/bcrypt edge cases).
        self._ctx = CryptContext(schemes=["argon2"], deprecated="auto")

    def hash(self, password: str) -> str:
        return self._ctx.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._ctx.verify(password, password_hash)


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    token_type: str
    exp: datetime


class TokenService:
    def create_access_token(self, user_id: uuid.UUID) -> str:
        exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expires_minutes)
        return self._encode(user_id=user_id, token_type="access", exp=exp)

    def create_refresh_token(self, user_id: uuid.UUID) -> str:
        exp = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expires_days)
        return self._encode(user_id=user_id, token_type="refresh", exp=exp)

    def verify_token(self, token: str, expected_type: str) -> TokenPayload:
        try:
            data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid token: {e}")

        token_type = data.get("typ")
        if token_type != expected_type:
            raise ValueError("Invalid token type")

        user_id = uuid.UUID(data["sub"])
        exp = datetime.fromtimestamp(float(data["exp"]), tz=timezone.utc)
        return TokenPayload(user_id=user_id, token_type=token_type, exp=exp)

    def _encode(self, user_id: uuid.UUID, token_type: str, exp: datetime) -> str:
        payload = {
            "sub": str(user_id),
            "typ": token_type,
            "exp": int(exp.timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
