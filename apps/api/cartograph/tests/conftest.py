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


# ── Synthetic road graph ──────────────────────────────────────────────────────
# A 4×4 grid over central Madrid mimicking the osm2pgrouting schema, so
# routing tests don't need a real OSM extract. Speeds are a flat 8.33 m/s
# (30 km/h). Node 100 is a connected-to-nothing island for RouteNotFound.

GRID_LNG0 = -3.7100
GRID_LAT0 = 40.4100
GRID_STEP = 0.005
GRID_N = 4
GRID_SPEED_MS = 8.33
ISLAND_LNG, ISLAND_LAT = -3.50, 40.60


def grid_node(col: int, row: int) -> tuple[float, float]:
    """(lng, lat) of a grid node."""
    return GRID_LNG0 + col * GRID_STEP, GRID_LAT0 + row * GRID_STEP


@pytest_asyncio.fixture(scope="session")
async def road_grid() -> AsyncGenerator[None, None]:
    from redis.asyncio import Redis
    from sqlalchemy import text

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS ways, ways_vertices_pgr CASCADE"))
        await conn.execute(
            text(
                "CREATE TABLE ways_vertices_pgr ("
                "id bigint PRIMARY KEY, the_geom geometry(Point, 4326))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE ways ("
                "gid bigserial PRIMARY KEY, source bigint, target bigint, "
                "cost_s double precision, reverse_cost_s double precision, "
                "length_m double precision, the_geom geometry(LineString, 4326))"
            )
        )
        await conn.execute(
            text("CREATE INDEX ways_vertices_geom_idx ON ways_vertices_pgr USING gist (the_geom)")
        )

        for row in range(GRID_N):
            for col in range(GRID_N):
                lng, lat = grid_node(col, row)
                await conn.execute(
                    text(
                        "INSERT INTO ways_vertices_pgr (id, the_geom) "
                        "VALUES (:id, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
                    ),
                    {"id": row * GRID_N + col + 1, "lng": lng, "lat": lat},
                )
        await conn.execute(
            text(
                "INSERT INTO ways_vertices_pgr (id, the_geom) "
                "VALUES (100, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
            ),
            {"lng": ISLAND_LNG, "lat": ISLAND_LAT},
        )

        edge_sql = text(
            "INSERT INTO ways (source, target, the_geom, length_m, cost_s, reverse_cost_s) "
            "SELECT :s, :t, g, ST_Length(g::geography), "
            f"ST_Length(g::geography) / {GRID_SPEED_MS}, "
            f"ST_Length(g::geography) / {GRID_SPEED_MS} "
            "FROM (SELECT ST_SetSRID(ST_MakeLine("
            "ST_MakePoint(:x1, :y1), ST_MakePoint(:x2, :y2)), 4326) AS g) q"
        )
        for row in range(GRID_N):
            for col in range(GRID_N):
                node = row * GRID_N + col + 1
                x1, y1 = grid_node(col, row)
                if col < GRID_N - 1:
                    x2, y2 = grid_node(col + 1, row)
                    await conn.execute(
                        edge_sql, {"s": node, "t": node + 1, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
                    )
                if row < GRID_N - 1:
                    x2, y2 = grid_node(col, row + 1)
                    await conn.execute(
                        edge_sql,
                        {"s": node, "t": node + GRID_N, "x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    )
    await engine.dispose()

    # Stale ETA cache entries would leak results from an older graph.
    redis: Redis = Redis.from_url(settings.redis_url)
    keys = [k async for k in redis.scan_iter(match="eta:*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()

    yield
