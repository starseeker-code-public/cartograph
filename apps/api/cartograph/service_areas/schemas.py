from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ServiceAreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geometry: dict[str, Any] = Field(
        description="GeoJSON Polygon/MultiPolygon geometry, Feature, or FeatureCollection"
    )
    rules: dict[str, Any] = Field(default_factory=dict)


class ServiceAreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    geometry: dict[str, Any] | None = None
    rules: dict[str, Any] | None = None


class ServiceAreaOut(BaseModel):
    id: UUID
    name: str
    geometry: dict[str, Any]
    rules: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ContainsResponse(BaseModel):
    service_area_ids: list[UUID]
