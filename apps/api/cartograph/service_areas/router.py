from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2.shape import from_shape, to_shape
from redis.asyncio import Redis
from shapely.geometry import mapping
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db, get_redis
from cartograph.service_areas.geojson import GeoJSONError, parse_multipolygon
from cartograph.service_areas.models import ServiceArea
from cartograph.service_areas.schemas import (
    ContainsResponse,
    ServiceAreaCreate,
    ServiceAreaOut,
    ServiceAreaUpdate,
)
from cartograph.tiles.cache import invalidate_tenant_tiles

router = APIRouter(prefix="/service-areas", tags=["service-areas"])


def _to_out(area: ServiceArea) -> ServiceAreaOut:
    return ServiceAreaOut(
        id=area.id,
        name=area.name,
        geometry=mapping(to_shape(area.geom)),
        rules=area.rules,
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


async def _get_owned(db: AsyncSession, current: CurrentUser, area_id: UUID) -> ServiceArea:
    area = (
        await db.execute(
            select(ServiceArea).where(
                ServiceArea.id == area_id, ServiceArea.tenant_id == current.tenant_id
            )
        )
    ).scalar_one_or_none()
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service area not found")
    return area


@router.post("", response_model=ServiceAreaOut, status_code=status.HTTP_201_CREATED)
async def create_service_area(
    payload: ServiceAreaCreate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ServiceAreaOut:
    try:
        multi = parse_multipolygon(payload.geometry)
    except GeoJSONError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    area = ServiceArea(
        tenant_id=current.tenant_id,
        name=payload.name,
        geom=from_shape(multi, srid=4326),
        rules=payload.rules,
    )
    db.add(area)
    await db.commit()
    await db.refresh(area)
    await invalidate_tenant_tiles(redis, current.tenant_id)
    return _to_out(area)


@router.get("", response_model=list[ServiceAreaOut])
async def list_service_areas(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ServiceAreaOut]:
    areas = (
        (
            await db.execute(
                select(ServiceArea)
                .where(ServiceArea.tenant_id == current.tenant_id)
                .order_by(ServiceArea.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(a) for a in areas]


# NB: declared before /{area_id} so "contains" isn't parsed as a UUID.
@router.get("/contains", response_model=ContainsResponse)
async def contains(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
) -> ContainsResponse:
    result = await db.execute(
        text(
            "SELECT id FROM service_areas "
            "WHERE tenant_id = :tenant "
            "AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
        ),
        {"tenant": current.tenant_id, "lng": lng, "lat": lat},
    )
    return ContainsResponse(service_area_ids=[row[0] for row in result.all()])


@router.get("/{area_id}", response_model=ServiceAreaOut)
async def get_service_area(
    area_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceAreaOut:
    return _to_out(await _get_owned(db, current, area_id))


@router.patch("/{area_id}", response_model=ServiceAreaOut)
async def update_service_area(
    area_id: UUID,
    payload: ServiceAreaUpdate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ServiceAreaOut:
    area = await _get_owned(db, current, area_id)

    if payload.name is not None:
        area.name = payload.name
    if payload.rules is not None:
        area.rules = payload.rules
    if payload.geometry is not None:
        try:
            area.geom = from_shape(parse_multipolygon(payload.geometry), srid=4326)
        except GeoJSONError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    await db.commit()
    await db.refresh(area)
    await invalidate_tenant_tiles(redis, current.tenant_id)
    return _to_out(area)


@router.delete("/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_area(
    area_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    area = await _get_owned(db, current, area_id)
    await db.delete(area)
    await db.commit()
    await invalidate_tenant_tiles(redis, current.tenant_id)
