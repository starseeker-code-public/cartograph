# pg_partman runbook

`geofence_events` is range-partitioned monthly on `occurred_at`. Partitions
are managed by `pg_partman`. This runbook covers the operational tasks.

## Daily maintenance (cron)

`partman.run_maintenance()` must be called regularly (daily is fine) so
new monthly partitions are pre-created before they're needed and old
partitions can be detached/dropped per retention policy.

Add this to your Compose stack as a sidecar cron or to your host crontab:

```cron
# 03:00 UTC daily
0 3 * * *  docker compose -f /opt/cartograph/infra/compose/docker-compose.prod.yml \
    exec -T postgres psql -U cartograph -d cartograph \
    -c "SELECT partman.run_maintenance(p_analyze := false);"
```

In Compose, this can live in a tiny BusyBox `crond` sidecar — see
`infra/compose/docker-compose.prod.yml` (added in Phase 10).

## Retention

Default: keep 24 months of events. Edit via:

```sql
UPDATE partman.part_config
SET retention = '24 months',
    retention_keep_table = false
WHERE parent_table = 'public.geofence_events';
```

## Verifying partitions

```sql
SELECT
  relname AS partition,
  pg_get_expr(c.relpartbound, c.oid) AS bound
FROM pg_class c
JOIN pg_inherits i ON i.inhrelid = c.oid
WHERE i.inhparent = 'geofence_events'::regclass
ORDER BY relname;
```

## If pg_partman is missing

The migration `0002_pg_partman.py` is a no-op when the extension is
unavailable. All writes land in `geofence_events_default`. This is
acceptable for development but **not** for production — install
pg_partman before the dataset grows.

## Re-running create_parent

`create_parent` is idempotent only insofar as `partman.part_config`
already has an entry. To reset:

```sql
SELECT partman.undo_partition(p_parent_table := 'public.geofence_events');
-- then re-run the 0002_pg_partman migration
```

**Warning**: `undo_partition` moves data; never run on production without a
backup.
