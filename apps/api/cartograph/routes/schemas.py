from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class EtaResponse(BaseModel):
    eta_seconds: int
    distance_m: int
    geometry: dict[str, Any]  # GeoJSON LineString
    cached: bool


class OptimizedStopOut(BaseModel):
    order_id: UUID
    kind: Literal["pickup", "delivery"]
    lng: float
    lat: float
    arrival_offset_s: int
    cumulative_distance_m: int


class OptimizeResponse(BaseModel):
    route_id: UUID
    stops: list[OptimizedStopOut]
    total_duration_s: int
    total_distance_m: int
