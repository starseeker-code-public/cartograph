"""configure pg_partman for monthly geofence_events partitions

Revision ID: 0002_pg_partman
Revises: 0001_initial
Create Date: 2026-06-10

Requires the pg_partman extension to be installed in the image (it ships
in the postgis/postgis image as of the 16-3.4 tag). If unavailable, this
migration is a no-op and the default partition continues to absorb writes.
A separate cron job (see docs/runbooks/pg-partman.md) calls
partman.run_maintenance() to roll partitions monthly.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_pg_partman"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create the partman schema + extension. Tolerate absence (it's a stretch
    # dependency); the default partition still catches writes.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'pg_partman'
            ) THEN
                CREATE SCHEMA IF NOT EXISTS partman;
                CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;

                -- Detach the default partition so partman can take over.
                ALTER TABLE geofence_events DETACH PARTITION geofence_events_default;

                PERFORM partman.create_parent(
                    p_parent_table   := 'public.geofence_events',
                    p_control        := 'occurred_at',
                    p_type           := 'range',
                    p_interval       := '1 month',
                    p_premake        := 4
                );

                -- Re-attach the default partition for any rows that fall
                -- outside the premade range.
                ALTER TABLE geofence_events ATTACH PARTITION geofence_events_default DEFAULT;
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_partman') THEN
                PERFORM partman.undo_partition(
                    p_parent_table := 'public.geofence_events'
                );
            END IF;
        END;
        $$;
        """
    )
