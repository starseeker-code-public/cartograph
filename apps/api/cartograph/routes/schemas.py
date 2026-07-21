from typing import Any

from pydantic import BaseModel


class EtaResponse(BaseModel):
    eta_seconds: int
    distance_m: int
    geometry: dict[str, Any]  # GeoJSON LineString
    cached: bool
