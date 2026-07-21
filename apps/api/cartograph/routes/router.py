from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db, get_redis
from cartograph.routes.engine import (
    RoadNetworkUnavailable,
    RouteNotFound,
    shortest_path_cached,
)
from cartograph.routes.schemas import EtaResponse

router = APIRouter(tags=["routing"])


@router.get("/eta", response_model=EtaResponse)
async def eta(
    _current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    from_lng: Annotated[float, Query(ge=-180, le=180)],
    from_lat: Annotated[float, Query(ge=-90, le=90)],
    to_lng: Annotated[float, Query(ge=-180, le=180)],
    to_lat: Annotated[float, Query(ge=-90, le=90)],
    vehicle: Annotated[str, Query(pattern="^(all|bike|scooter|car|van)$")] = "all",
) -> EtaResponse:
    try:
        route, cached = await shortest_path_cached(
            db, redis, from_lng, from_lat, to_lng, to_lat, vehicle
        )
    except RoadNetworkUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except RouteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return EtaResponse(
        eta_seconds=round(route.duration_s),
        distance_m=round(route.distance_m),
        geometry=route.geometry,
        cached=cached,
    )
