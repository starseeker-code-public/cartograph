from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db
from cartograph.geofences.models import GeofenceEvent, GeofenceEventKind
from cartograph.geofences.schemas import GeofenceEventOut
from cartograph.orders.schemas import Point

router = APIRouter(prefix="/geofence-events", tags=["geofences"])


def to_event_out(event: GeofenceEvent) -> GeofenceEventOut:
    shp = to_shape(event.location)
    return GeofenceEventOut(
        id=event.id,
        driver_id=event.driver_id,
        order_id=event.order_id,
        kind=GeofenceEventKind(event.kind),
        location=Point(lng=shp.x, lat=shp.y),
        occurred_at=event.occurred_at,
    )


@router.get("", response_model=list[GeofenceEventOut])
async def list_geofence_events(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    order_id: Annotated[UUID | None, Query()] = None,
    driver_id: Annotated[UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GeofenceEventOut]:
    query = select(GeofenceEvent).where(GeofenceEvent.tenant_id == current.tenant_id)
    if order_id is not None:
        query = query.where(GeofenceEvent.order_id == order_id)
    if driver_id is not None:
        query = query.where(GeofenceEvent.driver_id == driver_id)
    if since is not None:
        query = query.where(GeofenceEvent.occurred_at >= since)
    query = query.order_by(GeofenceEvent.occurred_at.desc()).limit(limit)
    events = (await db.execute(query)).scalars().all()
    return [to_event_out(e) for e in events]
