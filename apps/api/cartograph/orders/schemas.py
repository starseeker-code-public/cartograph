from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cartograph.orders.models import OrderState


class Point(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class OrderCreate(BaseModel):
    pickup: Point
    delivery: Point
    pickup_address: str = Field(min_length=1, max_length=500)
    delivery_address: str = Field(min_length=1, max_length=500)
    promised_at: datetime
    geofence_meters: int = Field(default=200, ge=10, le=5000)


class OrderUpdate(BaseModel):
    state: OrderState | None = None
    driver_id: UUID | None = None
    geofence_meters: int | None = Field(default=None, ge=10, le=5000)


class OrderOut(BaseModel):
    id: UUID
    pickup: Point
    delivery: Point
    pickup_address: str
    delivery_address: str
    promised_at: datetime
    state: OrderState
    driver_id: UUID | None
    eta_seconds: int | None
    geofence_meters: int
    created_at: datetime
