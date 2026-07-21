"""Shared pytest fixtures.

Integration tests use a real PostGIS database; they are marked ``db`` and
require ``DATABASE_URL`` to point at a PostGIS instance with the extensions
already created (see ``infra/compose/init.sql``).

Run ``just up`` first; then ``just test``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cartograph.auth.models import Tenant, User
from cartograph.settings import settings

API_DIR = Path(__file__).resolve().parents[2]


def _alembic_cfg() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    sync_url = settings.database_url.replace("+asyncpg", "")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations() -> None:
    """Apply Alembic migrations once per test session.

    Skipped when ``SKIP_DB_TESTS=1`` so unit-only runs don't require Postgres.
    """
    if os.getenv("SKIP_DB_TESTS") == "1":
        return
    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from cartograph.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def tenant_user(db_session: AsyncSession) -> tuple[Tenant, User, str]:
    """A committed tenant + user; returns (tenant, user, password)."""
    from cartograph.auth.security import hash_password

    password = "test-password-123"
    tenant = Tenant(slug=f"t-{uuid4().hex[:10]}", name="Test Tenant")
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"u-{uuid4().hex[:10]}@example.com",
        password_hash=hash_password(password),
    )
    db_session.add(user)
    await db_session.commit()
    return tenant, user, password


@pytest_asyncio.fixture
async def auth_headers(tenant_user: tuple[Tenant, User, str]) -> dict[str, str]:
    from cartograph.auth.security import create_access_token

    _, user, _ = tenant_user
    token = create_access_token(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}
