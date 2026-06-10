from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Index, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from cartograph.database import Base


class GeofenceEventKind(StrEnum):
    ENTERED = "entered"
    EXITED = "exited"
    DWELL_THRESHOLD = "dwell_threshold"


class GeofenceEvent(Base):
    """
    Partitioned by ``occurred_at`` (monthly) via pg_partman. The composite PK
    (id, occurred_at) is required by Postgres because the partition key must
    appear in every unique constraint on the partitioned table.
    """

    __tablename__ = "geofence_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    driver_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE")
    )
    order_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    location: Mapped[Any] = mapped_column(Geography("POINT", srid=4326))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at", name="pk_geofence_events"),
        Index("ix_geofence_events_loc", "location", postgresql_using="gist"),
        Index("ix_geofence_events_driver", "driver_id", "occurred_at"),
        Index("ix_geofence_events_order", "order_id", "occurred_at"),
        Index("ix_geofence_events_tenant", "tenant_id", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )
