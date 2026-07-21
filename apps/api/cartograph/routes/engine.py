"""Shortest-path routing over the osm2pgrouting road graph.

The ``ways`` / ``ways_vertices_pgr`` tables come from ``just osm-load`` (see
scripts/osm/load.sh). ``cost_s`` / ``reverse_cost_s`` are travel-time seconds;
``length_m`` is meters. Results are cached in Redis under
``eta:<from_lng>,<from_lat>:<to_lng>,<to_lat>:<vehicle>`` and invalidated on
OSM reload (docs/runbooks/osm-refresh.md).

V1 uses a single all-vehicles cost profile; ``vehicle`` only partitions the
cache so per-vehicle costs can slot in later without a cache flush.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.settings import settings

log = structlog.get_logger()


class RoutingError(Exception):
    """Base class for routing failures."""


class RoadNetworkUnavailable(RoutingError):
    """The ways tables don't exist — no OSM extract has been loaded."""


class RouteNotFound(RoutingError):
    """No path connects the two points (disconnected graph or off-network)."""


@dataclass(frozen=True)
class RouteResult:
    duration_s: float
    distance_m: float
    # GeoJSON LineString, or MultiLineString when the merged path has
    # repeated coordinates/discontinuities (common in real OSM imports).
    # Segment direction after ST_LineMerge is arbitrary — render, don't
    # animate along it.
    geometry: dict[str, Any]


def eta_cache_key(
    from_lng: float, from_lat: float, to_lng: float, to_lat: float, vehicle: str
) -> str:
    # 5 decimals ≈ 1.1 m — snaps GPS jitter to the same cache entry.
    return f"eta:{from_lng:.5f},{from_lat:.5f}:{to_lng:.5f},{to_lat:.5f}:{vehicle}"


async def road_network_available(db: AsyncSession) -> bool:
    result = await db.execute(text("SELECT to_regclass('public.ways') IS NOT NULL"))
    return bool(result.scalar_one())


async def _nearest_vertex(db: AsyncSession, lng: float, lat: float) -> int:
    # The KNN `<->` on 4326 geometry ranks by *degree* distance, where
    # longitude is compressed by cos(lat) — it can prefer a metrically
    # farther vertex. Take an index-driven candidate set, then re-rank the
    # candidates by true geodesic meters.
    result = await db.execute(
        text("""
            SELECT id FROM (
                SELECT id, the_geom
                FROM ways_vertices_pgr
                ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                LIMIT 16
            ) candidates
            ORDER BY ST_Distance(
                the_geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )
            LIMIT 1
            """),
        {"lng": lng, "lat": lat},
    )
    vertex_id = result.scalar_one_or_none()
    if vertex_id is None:
        raise RouteNotFound("Road network has no vertices")
    return int(vertex_id)


async def shortest_path(
    db: AsyncSession,
    from_lng: float,
    from_lat: float,
    to_lng: float,
    to_lat: float,
) -> RouteResult:
    """Dijkstra over travel-time costs; returns duration, distance, polyline."""
    if not await road_network_available(db):
        raise RoadNetworkUnavailable(
            "Road network not loaded — run `just osm-download <city> && just osm-load <city>`"
        )

    src = await _nearest_vertex(db, from_lng, from_lat)
    dst = await _nearest_vertex(db, to_lng, to_lat)

    if src == dst:
        # Same nearest node — effectively zero road distance. A degenerate
        # two-point line keeps the GeoJSON valid (RFC 7946 requires >= 2
        # positions); an empty coordinates array is not a legal LineString.
        line = {
            "type": "LineString",
            "coordinates": [[from_lng, from_lat], [to_lng, to_lat]],
        }
        return RouteResult(duration_s=0.0, distance_m=0.0, geometry=line)

    result = await db.execute(
        text("""
            SELECT
                SUM(p.cost)                                        AS duration_s,
                SUM(w.length_m)                                    AS distance_m,
                ST_AsGeoJSON(ST_LineMerge(ST_Collect(w.the_geom))) AS geometry
            FROM pgr_dijkstra(
                'SELECT gid AS id, source, target, '
                'cost_s AS cost, reverse_cost_s AS reverse_cost FROM ways',
                CAST(:src AS bigint), CAST(:dst AS bigint), directed := true
            ) p
            JOIN ways w ON w.gid = p.edge
            """),
        {"src": src, "dst": dst},
    )
    row = result.one()
    if row.duration_s is None:
        raise RouteNotFound(f"No route between vertices {src} and {dst}")

    return RouteResult(
        duration_s=float(row.duration_s),
        distance_m=float(row.distance_m),
        geometry=json.loads(row.geometry),
    )


async def shortest_path_cached(
    db: AsyncSession,
    redis: Redis,
    from_lng: float,
    from_lat: float,
    to_lng: float,
    to_lat: float,
    vehicle: str = "all",
) -> tuple[RouteResult, bool]:
    """Cache-through shortest_path. Returns (result, was_cache_hit).

    A Redis outage degrades to uncached computation — the cache must never
    take routing (or order intake, which calls this best-effort) down with it.
    """
    key = eta_cache_key(from_lng, from_lat, to_lng, to_lat, vehicle)
    try:
        cached = await redis.get(key)
    except RedisError:
        log.warning("eta cache read failed; computing uncached", key=key)
        cached = None
    if cached is not None:
        payload = json.loads(cached)
        return RouteResult(**payload), True

    route = await shortest_path(db, from_lng, from_lat, to_lng, to_lat)
    try:
        await redis.set(key, json.dumps(asdict(route)), ex=settings.eta_cache_ttl)
    except RedisError:
        log.warning("eta cache write failed", key=key)
    return route, False
