from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db, get_redis
from cartograph.tiles.cache import cache_stats, get_cached_tile, store_tile
from cartograph.tiles.service import render_tile

# Tile URLs live at /tiles/... (no /api prefix) per the MapLibre source URL.
router = APIRouter(tags=["tiles"])

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"


class TileStats(BaseModel):
    hits: int
    misses: int
    hit_ratio: float


@router.get("/tiles/{z}/{x}/{y}.mvt")
async def tile(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    z: Annotated[int, Path(ge=0, le=22)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
) -> Response:
    """Tenant-scoped MVT: service areas, geofence rings, orders, drivers.

    Authenticated via the httpOnly cookie set at login — MapLibre's tile
    fetches can't attach Authorization headers.
    """
    max_index = (1 << z) - 1
    if x > max_index or y > max_index:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tile x/y out of range for zoom {z}",
        )

    cached = await get_cached_tile(redis, current.tenant_id, z, x, y)
    if cached is not None:
        return Response(
            content=cached,
            media_type=MVT_MEDIA_TYPE,
            headers={"X-Tile-Cache": "HIT", "Cache-Control": "private, max-age=60"},
        )

    tile_bytes = await render_tile(db, current.tenant_id, z, x, y)
    await store_tile(redis, current.tenant_id, z, x, y, tile_bytes)
    return Response(
        content=tile_bytes,
        media_type=MVT_MEDIA_TYPE,
        headers={"X-Tile-Cache": "MISS", "Cache-Control": "private, max-age=60"},
    )


@router.get("/api/tiles/stats", response_model=TileStats)
async def tile_stats(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> TileStats:
    hits, misses = await cache_stats(redis, current.tenant_id)
    total = hits + misses
    return TileStats(hits=hits, misses=misses, hit_ratio=hits / total if total else 0.0)
