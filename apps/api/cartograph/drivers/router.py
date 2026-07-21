from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2.shape import to_shape
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db, get_redis
from cartograph.drivers.models import Driver, DriverState, VehicleType
from cartograph.drivers.schemas import (
    DriverCreate,
    DriverOut,
    DriverUpdate,
    LocationUpdate,
    LocationUpdateResult,
)
from cartograph.geofences.router import to_event_out
from cartograph.geofences.service import evaluate_geofences
from cartograph.orders.schemas import Point
from cartograph.settings import settings

router = APIRouter(prefix="/drivers", tags=["drivers"])


def _to_out(driver: Driver) -> DriverOut:
    location: Point | None = None
    if driver.current_location is not None:
        shp = to_shape(driver.current_location)
        location = Point(lng=shp.x, lat=shp.y)
    return DriverOut(
        id=driver.id,
        name=driver.name,
        phone=driver.phone,
        vehicle_type=VehicleType(driver.vehicle_type),
        state=DriverState(driver.state),
        current_location=location,
        current_location_updated_at=driver.current_location_updated_at,
        created_at=driver.created_at,
    )


async def _get_owned(db: AsyncSession, current: CurrentUser, driver_id: UUID) -> Driver:
    driver = (
        await db.execute(
            select(Driver).where(Driver.id == driver_id, Driver.tenant_id == current.tenant_id)
        )
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    return driver


@router.post("", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
async def create_driver(
    payload: DriverCreate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DriverOut:
    driver = Driver(
        tenant_id=current.tenant_id,
        name=payload.name,
        phone=payload.phone,
        vehicle_type=payload.vehicle_type.value,
    )
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return _to_out(driver)


@router.get("", response_model=list[DriverOut])
async def list_drivers(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    state: Annotated[DriverState | None, Query()] = None,
) -> list[DriverOut]:
    query = select(Driver).where(Driver.tenant_id == current.tenant_id)
    if state is not None:
        query = query.where(Driver.state == state.value)
    drivers = (await db.execute(query.order_by(Driver.created_at))).scalars().all()
    return [_to_out(d) for d in drivers]


@router.get("/{driver_id}", response_model=DriverOut)
async def get_driver(
    driver_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DriverOut:
    return _to_out(await _get_owned(db, current, driver_id))


@router.patch("/{driver_id}", response_model=DriverOut)
async def update_driver(
    driver_id: UUID,
    payload: DriverUpdate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DriverOut:
    driver = await _get_owned(db, current, driver_id)
    if payload.name is not None:
        driver.name = payload.name
    if payload.phone is not None:
        driver.phone = payload.phone
    if payload.vehicle_type is not None:
        driver.vehicle_type = payload.vehicle_type.value
    if payload.state is not None:
        driver.state = payload.state.value
    await db.commit()
    await db.refresh(driver)
    return _to_out(driver)


async def _check_rate_limit(redis: Redis, driver_id: UUID) -> None:
    """Per-driver fixed-window limiter on location updates."""
    key = f"rl:loc:{driver_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > settings.location_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Location update rate limit exceeded",
        )


@router.post("/{driver_id}/location", response_model=LocationUpdateResult)
async def update_location(
    driver_id: UUID,
    payload: LocationUpdate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> LocationUpdateResult:
    """Update a driver's position and evaluate geofences for active orders."""
    driver = await _get_owned(db, current, driver_id)
    await _check_rate_limit(redis, driver.id)

    driver.current_location = f"SRID=4326;POINT({payload.lng} {payload.lat})"
    driver.current_location_updated_at = payload.ts or datetime.now(UTC)

    events = await evaluate_geofences(db, driver, payload.lng, payload.lat, payload.accuracy_m)
    await db.commit()
    await db.refresh(driver)
    for event in events:
        await db.refresh(event)

    return LocationUpdateResult(driver=_to_out(driver), events=[to_event_out(e) for e in events])
