"""Password hashing (Argon2id) and JWT issuing/verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from cartograph.settings import settings

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: UUID, tenant_id: UUID) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "exp": expires,
    }
    token: str = jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)
    return token


def decode_access_token(token: str) -> tuple[UUID, UUID] | None:
    """Return (user_id, tenant_id) or None if the token is invalid/expired."""
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return UUID(claims["sub"]), UUID(claims["tid"])
    except (JWTError, KeyError, ValueError):
        return None
