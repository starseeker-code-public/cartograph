# Backup & restore runbook

## What runs automatically

The `maintenance` service dumps the database nightly:

- `pg_dump --format=custom --compress=6` → `${BACKUP_DIR}/cartograph-<stamp>.dump`
- Dumps older than `BACKUP_KEEP_DAYS` (default 14) are deleted.
- The same loop runs `partman.run_maintenance()` so next months'
  `geofence_events` partitions always exist.

Off-site: sync `${BACKUP_DIR}` to S3/Backblaze with restic or rclone from the
host's cron, e.g.

```bash
rclone copy /srv/cartograph/backups b2:cartograph-backups --min-age 1h
```

## Restore drill (run it before you need it)

1. Provision a scratch database:

   ```bash
   docker compose -f infra/compose/docker-compose.prod.yml --env-file .env \
     exec postgres createdb -U cartograph cartograph_restore
   ```

2. Restore the latest dump into it:

   ```bash
   docker compose -f infra/compose/docker-compose.prod.yml --env-file .env \
     exec -T postgres pg_restore -U cartograph -d cartograph_restore \
       --no-owner < backups/cartograph-<stamp>.dump
   ```

3. Sanity-check row counts and PostGIS:

   ```bash
   ... exec postgres psql -U cartograph -d cartograph_restore -c \
     "SELECT (SELECT count(*) FROM orders) AS orders,
             (SELECT count(*) FROM geofence_events) AS events,
             PostGIS_Version();"
   ```

4. Drop the scratch DB: `... exec postgres dropdb -U cartograph cartograph_restore`.

## Full restore (disaster)

```bash
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env stop api
... exec postgres dropdb -U cartograph cartograph && createdb -U cartograph cartograph
... exec postgres psql -U cartograph -d cartograph -c \
  "CREATE EXTENSION postgis; CREATE EXTENSION pgrouting; CREATE EXTENSION pg_trgm;"
... exec -T postgres pg_restore -U cartograph -d cartograph --no-owner < backups/<dump>
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env start api
```

Note: the road network (`ways`, `ways_vertices_pgr`) is in the dump too. If it
was excluded or stale, reload it per `osm-refresh.md` — order data does not
depend on it.
