from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from cartograph.geofences.models import GeofenceEventKind
from cartograph.orders.schemas import Point


class GeofenceEventOut(BaseModel):
    id: UUID
    driver_id: UUID
    order_id: UUID | None
    kind: GeofenceEventKind
    location: Point
    occurred_at: datetime
