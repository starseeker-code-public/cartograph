from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cartograph.drivers.models import DriverState, VehicleType
from cartograph.geofences.schemas import GeofenceEventOut
from cartograph.orders.schemas import Point


class DriverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=3, max_length=32)
    vehicle_type: VehicleType


class DriverUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    vehicle_type: VehicleType | None = None
    state: DriverState | None = None


class DriverOut(BaseModel):
    id: UUID
    name: str
    phone: str
    vehicle_type: VehicleType
    state: DriverState
    current_location: Point | None
    current_location_updated_at: datetime | None
    created_at: datetime


class LocationUpdate(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    ts: datetime | None = None
    accuracy_m: float | None = Field(default=None, ge=0)


class LocationUpdateResult(BaseModel):
    driver: DriverOut
    events: list[GeofenceEventOut]
