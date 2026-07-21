"""initial schema: tenants, service_areas, drivers, orders, routes, geofence_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-10

"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure spatial + routing extensions exist (idempotent — also in init.sql).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgrouting")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── tenants ───────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # ── service_areas ─────────────────────────────────────────────────────────
    op.create_table(
        "service_areas",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "rules",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_service_areas_geom", "service_areas", ["geom"], postgresql_using="gist"
    )
    op.create_index("ix_service_areas_tenant", "service_areas", ["tenant_id"])

    # ── drivers ───────────────────────────────────────────────────────────────
    op.create_table(
        "drivers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column(
            "current_location",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("current_location_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="offline"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_drivers_loc", "drivers", ["current_location"], postgresql_using="gist")
    op.create_index("ix_drivers_tenant", "drivers", ["tenant_id"])
    op.create_index("ix_drivers_state", "drivers", ["tenant_id", "state"])

    # ── orders ────────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pickup",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "delivery",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("pickup_address", sa.String(500), nullable=False),
        sa.Column("delivery_address", sa.String(500), nullable=False),
        sa.Column("promised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="created"),
        sa.Column(
            "driver_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("eta_seconds", sa.Integer, nullable=True),
        sa.Column("geofence_meters", sa.Integer, nullable=False, server_default="200"),
        sa.Column("pickup_h3_8", sa.String(16), nullable=True),
        sa.Column("delivery_h3_8", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_orders_pickup", "orders", ["pickup"], postgresql_using="gist")
    op.create_index("ix_orders_delivery", "orders", ["delivery"], postgresql_using="gist")
    op.create_index("ix_orders_tenant", "orders", ["tenant_id"])
    op.create_index("ix_orders_driver", "orders", ["driver_id"])
    op.create_index("ix_orders_state", "orders", ["tenant_id", "state"])
    op.create_index("ix_orders_pickup_h3_8", "orders", ["pickup_h3_8"])
    op.create_index("ix_orders_delivery_h3_8", "orders", ["delivery_h3_8"])

    # ── routes ────────────────────────────────────────────────────────────────
    op.create_table(
        "routes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_ids",
            sa.dialects.postgresql.ARRAY(sa.dialects.postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("sequence", sa.dialects.postgresql.ARRAY(sa.Integer), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("total_distance_m", sa.Integer, nullable=False),
        sa.Column("total_duration_s", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_routes_geom", "routes", ["geom"], postgresql_using="gist")
    op.create_index("ix_routes_tenant", "routes", ["tenant_id"])
    op.create_index("ix_routes_driver", "routes", ["driver_id"])

    # ── geofence_events (partitioned monthly) ─────────────────────────────────
    # Cannot use op.create_table because Alembic doesn't emit PARTITION BY.
    op.execute(
        """
        CREATE TABLE geofence_events (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            driver_id uuid NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            order_id  uuid     REFERENCES orders(id)  ON DELETE SET NULL,
            kind varchar(32) NOT NULL,
            location geography(POINT, 4326) NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_geofence_events PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at);
        """
    )
    op.execute(
        "CREATE INDEX ix_geofence_events_loc "
        "ON geofence_events USING gist (location);"
    )
    op.execute(
        "CREATE INDEX ix_geofence_events_driver "
        "ON geofence_events (driver_id, occurred_at);"
    )
    op.execute(
        "CREATE INDEX ix_geofence_events_order "
        "ON geofence_events (order_id, occurred_at);"
    )
    op.execute(
        "CREATE INDEX ix_geofence_events_tenant "
        "ON geofence_events (tenant_id, occurred_at);"
    )

    # Default catch-all partition so unconfigured installs still accept writes.
    # In production, pg_partman should be configured via 0002_pg_partman.py to
    # create monthly partitions and detach this default. See
    # docs/runbooks/pg-partman.md.
    op.execute(
        """
        CREATE TABLE geofence_events_default
        PARTITION OF geofence_events DEFAULT;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS geofence_events_default")
    op.execute("DROP TABLE IF EXISTS geofence_events")
    op.drop_table("routes")
    op.drop_table("orders")
    op.drop_table("drivers")
    op.drop_table("service_areas")
    op.drop_table("tenants")
