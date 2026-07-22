from typing import Annotated
from uuid import UUID

import h3
from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2.shape import to_shape
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db, get_redis
from cartograph.drivers.models import Driver
from cartograph.orders.models import Order, OrderState
from cartograph.orders.schemas import OrderCreate, OrderOut, OrderUpdate, Point
from cartograph.routes.engine import RoutingError, shortest_path_cached
from cartograph.routes.schemas import EtaResponse
from cartograph.tiles.cache import invalidate_tenant_tiles

router = APIRouter(prefix="/orders", tags=["orders"])

# state → states it may move to
TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED: {OrderState.ASSIGNED, OrderState.CANCELLED},
    OrderState.ASSIGNED: {OrderState.PICKED_UP, OrderState.CREATED, OrderState.CANCELLED},
    OrderState.PICKED_UP: {OrderState.DELIVERED, OrderState.FAILED},
    OrderState.DELIVERED: set(),
    OrderState.FAILED: set(),
    OrderState.CANCELLED: set(),
}


def _point(geom: object) -> Point:
    shp = to_shape(geom)  # type: ignore[arg-type]
    return Point(lng=shp.x, lat=shp.y)


def _to_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        pickup=_point(order.pickup),
        delivery=_point(order.delivery),
        pickup_address=order.pickup_address,
        delivery_address=order.delivery_address,
        promised_at=order.promised_at,
        state=OrderState(order.state),
        driver_id=order.driver_id,
        eta_seconds=order.eta_seconds,
        geofence_meters=order.geofence_meters,
        created_at=order.created_at,
    )


async def _get_owned(
    db: AsyncSession, current: CurrentUser, order_id: UUID, for_update: bool = False
) -> Order:
    query = select(Order).where(Order.id == order_id, Order.tenant_id == current.tenant_id)
    if for_update:
        # Serializes concurrent PATCHes so two writers can't both pass the
        # state-machine check against the same stale state.
        query = query.with_for_update()
    order = (await db.execute(query)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> OrderOut:
    order = Order(
        tenant_id=current.tenant_id,
        pickup=f"SRID=4326;POINT({payload.pickup.lng} {payload.pickup.lat})",
        delivery=f"SRID=4326;POINT({payload.delivery.lng} {payload.delivery.lat})",
        pickup_address=payload.pickup_address,
        delivery_address=payload.delivery_address,
        promised_at=payload.promised_at,
        geofence_meters=payload.geofence_meters,
        # H3 res 8 (~0.7 km hexes) for coverage analytics (Phase 8).
        pickup_h3_8=h3.latlng_to_cell(payload.pickup.lat, payload.pickup.lng, 8),
        delivery_h3_8=h3.latlng_to_cell(payload.delivery.lat, payload.delivery.lng, 8),
    )

    # Best-effort ETA at creation; absent road network must not block intake.
    try:
        route, _ = await shortest_path_cached(
            db,
            redis,
            payload.pickup.lng,
            payload.pickup.lat,
            payload.delivery.lng,
            payload.delivery.lat,
        )
        order.eta_seconds = round(route.duration_s)
    except RoutingError:
        order.eta_seconds = None

    db.add(order)
    await db.commit()
    await db.refresh(order)
    # Tiles embed order pins + geofence rings; drop the tenant's cache so the
    # map reflects the change within a tile refresh, not the 300 s TTL.
    await invalidate_tenant_tiles(redis, current.tenant_id)
    return _to_out(order)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    state: Annotated[OrderState | None, Query()] = None,
    driver_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OrderOut]:
    query = select(Order).where(Order.tenant_id == current.tenant_id)
    if state is not None:
        query = query.where(Order.state == state.value)
    if driver_id is not None:
        query = query.where(Order.driver_id == driver_id)
    query = query.order_by(Order.created_at.desc()).limit(limit).offset(offset)
    orders = (await db.execute(query)).scalars().all()
    return [_to_out(o) for o in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrderOut:
    return _to_out(await _get_owned(db, current, order_id))


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: UUID,
    payload: OrderUpdate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> OrderOut:
    order = await _get_owned(db, current, order_id, for_update=True)

    # Tri-state: absent = keep, null = unassign, uuid = assign.
    if "driver_id" in payload.model_fields_set:
        if payload.driver_id is None:
            # Mid-delivery unassignment would orphan a picked-up parcel.
            if order.state not in (OrderState.CREATED.value, OrderState.ASSIGNED.value):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot unassign a driver from a {order.state} order",
                )
            order.driver_id = None
            # An assigned order with no driver is a contradiction; fall back
            # to created unless the caller also set an explicit state.
            if order.state == OrderState.ASSIGNED.value and payload.state is None:
                order.state = OrderState.CREATED.value
        else:
            driver = (
                await db.execute(
                    select(Driver).where(
                        Driver.id == payload.driver_id, Driver.tenant_id == current.tenant_id
                    )
                )
            ).scalar_one_or_none()
            if driver is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown driver"
                )
            order.driver_id = driver.id

    if payload.state is not None:
        current_state = OrderState(order.state)
        if payload.state != current_state and payload.state not in TRANSITIONS[current_state]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot transition from {current_state.value} to {payload.state.value}",
            )
        if payload.state == OrderState.ASSIGNED and order.driver_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot mark assigned without a driver",
            )
        order.state = payload.state.value

    if payload.geofence_meters is not None:
        order.geofence_meters = payload.geofence_meters

    await db.commit()
    await db.refresh(order)
    await invalidate_tenant_tiles(redis, current.tenant_id)
    return _to_out(order)


@router.get("/{order_id}/eta", response_model=EtaResponse)
async def order_eta(
    order_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> EtaResponse:
    """Route pickup → delivery; refreshes the order's stored eta_seconds."""
    from cartograph.routes.engine import RoadNetworkUnavailable, RouteNotFound

    order = await _get_owned(db, current, order_id)
    pickup, delivery = _point(order.pickup), _point(order.delivery)

    try:
        route, cached = await shortest_path_cached(
            db, redis, pickup.lng, pickup.lat, delivery.lng, delivery.lat
        )
    except RoadNetworkUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except RouteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    order.eta_seconds = round(route.duration_s)
    await db.commit()

    return EtaResponse(
        eta_seconds=round(route.duration_s),
        distance_m=round(route.distance_m),
        geometry=route.geometry,
        cached=cached,
    )
