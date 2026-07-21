"""Geofence evaluation for driver position updates.

Each active order carries an implicit circular geofence of
``order.geofence_meters`` around its delivery point (geography — meters are
accurate at any latitude). The last geofence event per (driver, order) is the
fence state, so detection needs no separate state table:

- last event ``entered``  → currently inside;  emit ``exited`` when the
  distance exceeds radius + hysteresis margin.
- last event ``exited``/none → currently outside; emit ``entered`` when the
  distance drops to the radius or below.
- inside for ≥ ``geofence_dwell_seconds`` since the last ``entered`` with no
  ``dwell_threshold`` yet → emit ``dwell_threshold`` (re-entry resets the
  timer because the clock starts at the newest ``entered``).

The exit margin (max of fix accuracy and 20 m) is the anti-jitter hysteresis:
a fix must leave the ring decisively before an ``exited`` fires, so GPS noise
at the boundary can't ping-pong events. Fixes with accuracy worse than
``geofence_accuracy_max_m`` update the driver's position but never fence state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.drivers.models import Driver
from cartograph.geofences.models import GeofenceEvent, GeofenceEventKind
from cartograph.orders.models import OrderState
from cartograph.settings import settings

# Orders whose delivery geofence is live.
ACTIVE_ORDER_STATES = (OrderState.ASSIGNED.value, OrderState.PICKED_UP.value)

_MIN_EXIT_MARGIN_M = 20.0


async def evaluate_geofences(
    db: AsyncSession,
    driver: Driver,
    lng: float,
    lat: float,
    accuracy_m: float | None,
) -> list[GeofenceEvent]:
    """Emit geofence events for this driver's active orders. Caller commits."""
    if accuracy_m is not None and accuracy_m > settings.geofence_accuracy_max_m:
        return []

    margin = max(accuracy_m or 0.0, _MIN_EXIT_MARGIN_M)
    now = datetime.now(UTC)

    rows = (
        await db.execute(
            text("""
                SELECT
                    o.id,
                    o.geofence_meters,
                    ST_Distance(
                        o.delivery,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                    ) AS dist,
                    last_ev.kind        AS last_kind,
                    last_ev.occurred_at AS last_at,
                    dwell_ev.occurred_at AS dwelled_at
                FROM orders o
                LEFT JOIN LATERAL (
                    SELECT kind, occurred_at
                    FROM geofence_events
                    WHERE order_id = o.id AND driver_id = :driver
                      AND kind IN ('entered', 'exited')
                    ORDER BY occurred_at DESC
                    LIMIT 1
                ) last_ev ON true
                LEFT JOIN LATERAL (
                    SELECT occurred_at
                    FROM geofence_events
                    WHERE order_id = o.id AND driver_id = :driver
                      AND kind = 'dwell_threshold'
                      AND occurred_at >= last_ev.occurred_at
                    ORDER BY occurred_at DESC
                    LIMIT 1
                ) dwell_ev ON true
                WHERE o.driver_id = :driver
                  AND o.tenant_id = :tenant
                  AND o.state IN ('assigned', 'picked_up')
                """),
            {"lng": lng, "lat": lat, "driver": driver.id, "tenant": driver.tenant_id},
        )
    ).all()

    location_ewkt = f"SRID=4326;POINT({lng} {lat})"
    events: list[GeofenceEvent] = []

    def emit(order_id: UUID, kind: GeofenceEventKind) -> None:
        event = GeofenceEvent(
            tenant_id=driver.tenant_id,
            driver_id=driver.id,
            order_id=order_id,
            kind=kind.value,
            location=location_ewkt,
            occurred_at=now,
        )
        db.add(event)
        events.append(event)

    for row in rows:
        radius = float(row.geofence_meters)
        inside_before = row.last_kind == GeofenceEventKind.ENTERED.value

        if not inside_before and row.dist <= radius:
            emit(row.id, GeofenceEventKind.ENTERED)
        elif inside_before and row.dist > radius + margin:
            emit(row.id, GeofenceEventKind.EXITED)
        elif (
            inside_before
            and row.dwelled_at is None
            and (now - row.last_at).total_seconds() >= settings.geofence_dwell_seconds
        ):
            emit(row.id, GeofenceEventKind.DWELL_THRESHOLD)

    return events
