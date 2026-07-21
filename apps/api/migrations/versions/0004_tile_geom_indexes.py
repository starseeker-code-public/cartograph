"""functional geometry indexes for tile bbox filters

Revision ID: 0004_tile_geom_indexes
Revises: 0003_users
Create Date: 2026-07-21

The tile SQL filters geography columns via `col::geometry && bbox`; the plain
geography GiST indexes from 0001 can't serve that cast, so every uncached tile
sequentially scanned orders/drivers. These expression indexes cover the cast.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_tile_geom_indexes"
down_revision: str | None = "0003_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_orders_pickup_geom ON orders USING gist ((pickup::geometry))"
    )
    op.execute(
        "CREATE INDEX ix_orders_delivery_geom ON orders USING gist ((delivery::geometry))"
    )
    op.execute(
        "CREATE INDEX ix_drivers_loc_geom ON drivers "
        "USING gist ((current_location::geometry))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_pickup_geom")
    op.execute("DROP INDEX IF EXISTS ix_orders_delivery_geom")
    op.execute("DROP INDEX IF EXISTS ix_drivers_loc_geom")
