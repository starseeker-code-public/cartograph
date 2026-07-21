"""Redis tile cache: per-tenant keys, hit/miss counters, bulk invalidation."""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

from cartograph.settings import settings


def tile_key(tenant_id: UUID, z: int, x: int, y: int) -> str:
    return f"tile:{tenant_id}:{z}:{x}:{y}"


def _stats_key(tenant_id: UUID, kind: str) -> str:
    # Per-tenant counters: global ones would leak other tenants' traffic
    # volume through /api/tiles/stats.
    return f"tile:stats:{tenant_id}:{kind}"


async def get_cached_tile(redis: Redis, tenant_id: UUID, z: int, x: int, y: int) -> bytes | None:
    cached = await redis.get(tile_key(tenant_id, z, x, y))
    await redis.incr(_stats_key(tenant_id, "hits" if cached is not None else "misses"))
    # The client is created with decode_responses=False, so str never occurs.
    return cached if isinstance(cached, bytes) else None


async def store_tile(redis: Redis, tenant_id: UUID, z: int, x: int, y: int, tile: bytes) -> None:
    await redis.set(tile_key(tenant_id, z, x, y), tile, ex=settings.tile_cache_ttl)


async def invalidate_tenant_tiles(redis: Redis, tenant_id: UUID) -> int:
    """Drop every cached tile for a tenant (e.g. after service-area edits)."""
    keys = [key async for key in redis.scan_iter(match=f"tile:{tenant_id}:*")]
    if keys:
        await redis.delete(*keys)
    return len(keys)


async def cache_stats(redis: Redis, tenant_id: UUID) -> tuple[int, int]:
    hits = await redis.get(_stats_key(tenant_id, "hits"))
    misses = await redis.get(_stats_key(tenant_id, "misses"))
    return int(hits or 0), int(misses or 0)
