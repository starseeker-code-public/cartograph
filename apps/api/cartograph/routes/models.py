from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from cartograph.database import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    driver_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE")
    )
    order_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)))
    sequence: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    geom: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False))
    total_distance_m: Mapped[int] = mapped_column(Integer)
    total_duration_s: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_routes_geom", "geom", postgresql_using="gist"),
        Index("ix_routes_tenant", "tenant_id"),
        Index("ix_routes_driver", "driver_id"),
    )
