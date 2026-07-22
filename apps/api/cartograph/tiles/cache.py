"""Redis tile cache: per-tenant keys, hit/miss counters, bulk invalidation.

Every operation fails open on Redis errors — a cache outage must degrade to
uncached tile rendering (or a skipped invalidation), never surface as a 500.
The invalidation case matters most: it runs *after* an order/service-area
write has committed, so an exception there would report failure for a write
that actually succeeded.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from cartograph.settings import settings

log = structlog.get_logger()


def tile_key(tenant_id: UUID, z: int, x: int, y: int) -> str:
    return f"tile:{tenant_id}:{z}:{x}:{y}"


def _stats_key(tenant_id: UUID, kind: str) -> str:
    # Per-tenant counters: global ones would leak other tenants' traffic
    # volume through /api/tiles/stats.
    return f"tile:stats:{tenant_id}:{kind}"


async def get_cached_tile(redis: Redis, tenant_id: UUID, z: int, x: int, y: int) -> bytes | None:
    try:
        cached = await redis.get(tile_key(tenant_id, z, x, y))
        await redis.incr(_stats_key(tenant_id, "hits" if cached is not None else "misses"))
    except RedisError:
        log.warning("tile cache read failed; rendering uncached", tenant=str(tenant_id))
        return None
    # The client is created with decode_responses=False, so str never occurs.
    return cached if isinstance(cached, bytes) else None


async def store_tile(redis: Redis, tenant_id: UUID, z: int, x: int, y: int, tile: bytes) -> None:
    try:
        await redis.set(tile_key(tenant_id, z, x, y), tile, ex=settings.tile_cache_ttl)
    except RedisError:
        log.warning("tile cache write failed", tenant=str(tenant_id))


async def invalidate_tenant_tiles(redis: Redis, tenant_id: UUID) -> int:
    """Drop every cached tile for a tenant (e.g. after service-area edits)."""
    try:
        keys = [key async for key in redis.scan_iter(match=f"tile:{tenant_id}:*")]
        if keys:
            await redis.delete(*keys)
        return len(keys)
    except RedisError:
        # Stale tiles expire via TTL anyway; never fail the caller's write.
        log.warning("tile cache invalidation failed", tenant=str(tenant_id))
        return 0


async def cache_stats(redis: Redis, tenant_id: UUID) -> tuple[int, int]:
    try:
        hits = await redis.get(_stats_key(tenant_id, "hits"))
        misses = await redis.get(_stats_key(tenant_id, "misses"))
    except RedisError:
        return 0, 0
    return int(hits or 0), int(misses or 0)
