from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from cartograph.database import Base


class VehicleType(StrEnum):
    BIKE = "bike"
    SCOOTER = "scooter"
    CAR = "car"
    VAN = "van"


class DriverState(StrEnum):
    OFFLINE = "offline"
    IDLE = "idle"
    EN_ROUTE = "en_route"


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    vehicle_type: Mapped[str] = mapped_column(String(16))
    current_location: Mapped[Any | None] = mapped_column(
        Geography("POINT", srid=4326, spatial_index=False), nullable=True
    )
    current_location_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), default=DriverState.OFFLINE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_drivers_loc", "current_location", postgresql_using="gist"),
        Index("ix_drivers_tenant", "tenant_id"),
        Index("ix_drivers_state", "tenant_id", "state"),
    )
