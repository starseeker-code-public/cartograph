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
    #
    # Data-safe on non-empty databases: rows accumulated in the 0001 default
    # partition are migrated into real monthly partitions (the premade range
    # starts at the oldest existing row), and only then is the default
    # re-attached — attaching a default that still holds rows covered by real
    # partitions would fail Postgres's overlap validation and block the deploy.
    op.execute(
        """
        DO $$
        DECLARE
            first_row     timestamptz;
            covered_until timestamptz;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'pg_partman'
            ) THEN
                CREATE SCHEMA IF NOT EXISTS partman;
                CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;

                -- Detach the default partition so partman can take over.
                ALTER TABLE geofence_events DETACH PARTITION geofence_events_default;

                SELECT min(occurred_at) INTO first_row FROM geofence_events_default;

                -- p_default_table := false: we manage the default partition
                -- ourselves (created in 0001); letting partman create its own
                -- would collide on the geofence_events_default name.
                PERFORM partman.create_parent(
                    p_parent_table    := 'public.geofence_events',
                    p_control         := 'occurred_at',
                    p_type            := 'range',
                    p_interval        := '1 month',
                    p_premake         := 4,
                    p_start_partition := date_trunc('month', COALESCE(first_row, now()))::text,
                    p_default_table   := false
                );

                -- Premade partitions cover [start .. current month + 4].
                covered_until := date_trunc('month', now()) + interval '5 months';

                IF first_row IS NOT NULL THEN
                    INSERT INTO geofence_events
                    SELECT * FROM geofence_events_default
                    WHERE occurred_at < covered_until;

                    DELETE FROM geofence_events_default
                    WHERE occurred_at < covered_until;
                END IF;

                -- Anything left (bogus far-future timestamps) legally stays in
                -- the default partition.
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
