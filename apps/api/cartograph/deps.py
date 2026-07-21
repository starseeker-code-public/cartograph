from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.database import get_session
from cartograph.settings import settings

_redis: Redis | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    tenant_id: UUID
    email: str


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    access_token: Annotated[str | None, Cookie()] = None,
) -> CurrentUser:
    """Resolve the authenticated user from a Bearer header or cookie.

    The cookie fallback exists for requests the browser makes without JS
    (MapLibre tile fetches). All queries downstream must scope on
    ``tenant_id`` from the returned identity.
    """
    from cartograph.auth.models import User
    from cartograph.auth.security import decode_access_token

    token = credentials.credentials if credentials is not None else access_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    decoded = decode_access_token(token)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    user_id, tenant_id = decoded

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")

    return CurrentUser(user_id=user.id, tenant_id=user.tenant_id, email=user.email)
