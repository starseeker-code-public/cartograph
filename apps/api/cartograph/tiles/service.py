"""Mapbox Vector Tile generation, server-side at PostGIS via ST_AsMVT.

One tile carries four layers, all tenant-scoped:

- ``service_areas`` — MultiPolygons (id, name)
- ``geofences``     — buffer rings around active-order deliveries (id, radius)
- ``orders``        — pickup/delivery points for live orders (id, state, role)
- ``drivers``       — last known driver positions (id, name, state)

Layers are independent ``ST_AsMVT`` aggregates concatenated with ``||``;
an empty layer contributes zero bytes (COALESCE against an empty bytea).

Feature selection uses a tile envelope expanded by the MVT buffer margin
(``margin => buffer/extent``) — filtering on the exact envelope would drop
features that belong in the neighboring tile's buffer skirt, slicing points
and rings at tile seams.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXTENT = 4096
BUFFER = 64

_TILE_SQL = text("""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS env,
               ST_Transform(
                   ST_TileEnvelope(:z, :x, :y, margin => :margin), 4326
               ) AS filter_env
    )
    SELECT
        COALESCE((
            SELECT ST_AsMVT(t, 'service_areas', :extent, 'geom')
            FROM (
                SELECT sa.id, sa.name,
                       ST_AsMVTGeom(
                           ST_Transform(sa.geom, 3857), bounds.env, :extent, :buf, true
                       ) AS geom
                FROM service_areas sa, bounds
                WHERE sa.tenant_id = :tenant AND sa.geom && bounds.filter_env
            ) t
            WHERE t.geom IS NOT NULL
        ), ''::bytea)
        ||
        COALESCE((
            SELECT ST_AsMVT(t, 'geofences', :extent, 'geom')
            FROM (
                SELECT o.id, o.geofence_meters AS radius_m,
                       ST_AsMVTGeom(
                           ST_Transform(ring.geom, 3857),
                           bounds.env, :extent, :buf, true
                       ) AS geom
                FROM orders o
                CROSS JOIN bounds
                CROSS JOIN LATERAL (
                    SELECT ST_Buffer(o.delivery, o.geofence_meters)::geometry AS geom
                ) ring
                WHERE o.tenant_id = :tenant
                  AND o.state IN ('assigned', 'picked_up')
                  AND ring.geom && bounds.filter_env
            ) t
            WHERE t.geom IS NOT NULL
        ), ''::bytea)
        ||
        COALESCE((
            SELECT ST_AsMVT(t, 'orders', :extent, 'geom')
            FROM (
                SELECT o.id, o.state, r.role,
                       ST_AsMVTGeom(
                           ST_Transform(r.pt::geometry, 3857), bounds.env, :extent, :buf, true
                       ) AS geom
                FROM orders o
                CROSS JOIN bounds
                CROSS JOIN LATERAL (
                    VALUES ('pickup', o.pickup), ('delivery', o.delivery)
                ) AS r(role, pt)
                WHERE o.tenant_id = :tenant
                  AND o.state IN ('created', 'assigned', 'picked_up')
                  AND r.pt::geometry && bounds.filter_env
            ) t
            WHERE t.geom IS NOT NULL
        ), ''::bytea)
        ||
        COALESCE((
            SELECT ST_AsMVT(t, 'drivers', :extent, 'geom')
            FROM (
                SELECT d.id, d.name, d.state,
                       ST_AsMVTGeom(
                           ST_Transform(d.current_location::geometry, 3857),
                           bounds.env, :extent, :buf, true
                       ) AS geom
                FROM drivers d, bounds
                WHERE d.tenant_id = :tenant
                  AND d.current_location IS NOT NULL
                  AND d.current_location::geometry && bounds.filter_env
            ) t
            WHERE t.geom IS NOT NULL
        ), ''::bytea) AS tile
    """)


async def render_tile(db: AsyncSession, tenant_id: UUID, z: int, x: int, y: int) -> bytes:
    result = await db.execute(
        _TILE_SQL,
        {
            "z": z,
            "x": x,
            "y": y,
            "tenant": tenant_id,
            "extent": EXTENT,
            "buf": BUFFER,
            "margin": BUFFER / EXTENT,
        },
    )
    tile = result.scalar_one()
    return bytes(tile) if tile is not None else b""
