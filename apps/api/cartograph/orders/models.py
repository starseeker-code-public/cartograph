from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from cartograph.database import Base


class OrderState(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    pickup: Mapped[Any] = mapped_column(Geography("POINT", srid=4326))
    delivery: Mapped[Any] = mapped_column(Geography("POINT", srid=4326))
    pickup_address: Mapped[str] = mapped_column(String(500))
    delivery_address: Mapped[str] = mapped_column(String(500))
    promised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default=OrderState.CREATED.value)
    driver_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geofence_meters: Mapped[int] = mapped_column(Integer, default=200)
    # H3 hex IDs (resolution 8 ≈ 0.7 km) — see Phase 8 (coverage analytics).
    pickup_h3_8: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    delivery_h3_8: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_orders_pickup", "pickup", postgresql_using="gist"),
        Index("ix_orders_delivery", "delivery", postgresql_using="gist"),
        Index("ix_orders_tenant", "tenant_id"),
        Index("ix_orders_driver", "driver_id"),
        Index("ix_orders_state", "tenant_id", "state"),
    )
