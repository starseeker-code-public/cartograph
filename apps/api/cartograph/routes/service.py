"""Route optimization service: matrix building + persistence around the
pure optimizer in :mod:`cartograph.routes.optimizer`.

``Route.sequence`` encoding: each element is ``order_index * 2`` for that
order's pickup stop or ``order_index * 2 + 1`` for its delivery stop, where
``order_index`` points into ``Route.order_ids``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from geoalchemy2.shape import to_shape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.drivers.models import Driver
from cartograph.orders.models import Order, OrderState
from cartograph.routes.engine import (
    RoadNetworkUnavailable,
    _nearest_vertex,
    road_network_available,
)
from cartograph.routes.models import Route
from cartograph.routes.optimizer import CostMatrix, Stop, optimize_sequence, tour_cost


class NoStopsToOptimize(Exception):
    pass


class DriverHasNoLocation(Exception):
    pass


@dataclass(frozen=True)
class PlannedStop:
    order_id: UUID
    kind: str
    lng: float
    lat: float
    arrival_offset_s: float
    cumulative_distance_m: float


@dataclass(frozen=True)
class OptimizedRoute:
    route: Route
    stops: list[PlannedStop]
    total_duration_s: float
    total_distance_m: float


async def _build_matrices(db: AsyncSession, vertices: list[int]) -> tuple[CostMatrix, CostMatrix]:
    """(duration_s, distance_m) matrices along time-optimal paths."""
    rows = (
        await db.execute(
            text("""
                SELECT p.start_vid, p.end_vid,
                       SUM(p.cost)      AS duration_s,
                       SUM(w.length_m)  AS distance_m
                FROM pgr_dijkstra(
                    'SELECT gid AS id, source, target, '
                    'cost_s AS cost, reverse_cost_s AS reverse_cost FROM ways',
                    CAST(:vids AS bigint[]), CAST(:vids AS bigint[]),
                    directed := true
                ) p
                JOIN ways w ON w.gid = p.edge
                GROUP BY p.start_vid, p.end_vid
                """),
            {"vids": vertices},
        )
    ).all()
    durations: CostMatrix = {}
    distances: CostMatrix = {}
    for row in rows:
        durations[(row.start_vid, row.end_vid)] = float(row.duration_s)
        distances[(row.start_vid, row.end_vid)] = float(row.distance_m)
    return durations, distances


async def optimize_driver_route(db: AsyncSession, driver: Driver) -> OptimizedRoute:
    """Sequence the driver's active stops; persists a Route (caller commits)."""
    if not await road_network_available(db):
        raise RoadNetworkUnavailable(
            "Road network not loaded — run `just osm-download <city> && just osm-load <city>`"
        )
    if driver.current_location is None:
        raise DriverHasNoLocation("Driver has no known location to start from")

    orders = (
        (
            await db.execute(
                select(Order)
                .where(
                    Order.driver_id == driver.id,
                    Order.tenant_id == driver.tenant_id,
                    Order.state.in_([OrderState.ASSIGNED.value, OrderState.PICKED_UP.value]),
                )
                .order_by(Order.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not orders:
        raise NoStopsToOptimize("Driver has no active orders")

    start_point = to_shape(driver.current_location)
    start_vertex = await _nearest_vertex(db, start_point.x, start_point.y)

    stops: list[Stop] = []
    encoded: list[int] = []  # parallel to stops; Route.sequence values
    for order_index, order in enumerate(orders):
        delivery = to_shape(order.delivery)
        if order.state == OrderState.ASSIGNED.value:
            pickup = to_shape(order.pickup)
            stops.append(
                Stop(
                    order_id=order.id,
                    kind="pickup",
                    vertex=await _nearest_vertex(db, pickup.x, pickup.y),
                    lng=pickup.x,
                    lat=pickup.y,
                )
            )
            encoded.append(order_index * 2)
        stops.append(
            Stop(
                order_id=order.id,
                kind="delivery",
                vertex=await _nearest_vertex(db, delivery.x, delivery.y),
                lng=delivery.x,
                lat=delivery.y,
            )
        )
        encoded.append(order_index * 2 + 1)

    vertices = sorted({start_vertex, *(s.vertex for s in stops)})
    durations, distances = await _build_matrices(db, vertices)

    tour = optimize_sequence(durations, stops, start_vertex)
    total_duration = tour_cost(durations, stops, start_vertex, tour)
    total_distance = tour_cost(distances, stops, start_vertex, tour)

    planned: list[PlannedStop] = []
    offset_s = 0.0
    offset_m = 0.0
    prev_vertex = start_vertex
    for stop_index in tour:
        stop = stops[stop_index]
        if stop.vertex != prev_vertex:
            offset_s += durations[(prev_vertex, stop.vertex)]
            offset_m += distances[(prev_vertex, stop.vertex)]
        planned.append(
            PlannedStop(
                order_id=stop.order_id,
                kind=stop.kind,
                lng=stop.lng,
                lat=stop.lat,
                arrival_offset_s=offset_s,
                cumulative_distance_m=offset_m,
            )
        )
        prev_vertex = stop.vertex

    # Straight-line connective geometry: start → stops in visit order. Road
    # polylines per leg are available via /api/eta (cached) when needed.
    points = [(start_point.x, start_point.y)] + [(s.lng, s.lat) for s in planned]
    wkt = "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in points) + ")"

    route = Route(
        tenant_id=driver.tenant_id,
        driver_id=driver.id,
        order_ids=[o.id for o in orders],
        sequence=[encoded[i] for i in tour],
        geom=f"SRID=4326;{wkt}",
        total_distance_m=round(total_distance),
        total_duration_s=round(total_duration),
    )
    db.add(route)

    return OptimizedRoute(
        route=route,
        stops=planned,
        total_duration_s=total_duration,
        total_distance_m=total_distance,
    )
