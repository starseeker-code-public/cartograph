# OSM extract refresh runbook

Cadence: quarterly (or after known road-network changes in the service area).

**This replaces the `ways` / `ways_vertices_pgr` tables — millions of rows,
and `pgr_createTopology` inside osm2pgrouting is slow. Do it off-peak and
confirm before running against production.**

## Procedure

1. Download the fresh extract:

   ```bash
   just osm-download madrid        # edit scripts/osm/download.sh for your region
   ```

2. Load it (drops + recreates the routing tables):

   ```bash
   just osm-load madrid
   ```

3. Verify:

   ```bash
   psql -c "SELECT count(*) FROM ways;"                  # roughly the previous count
   psql -c "SELECT count(*) FROM ways_vertices_pgr;"
   curl -fsS "$API/api/eta?from_lng=...&from_lat=...&to_lng=...&to_lat=..." \
     -H "Authorization: Bearer $TOKEN"                    # sane duration/route
   ```

4. **Invalidate the ETA cache** — cached routes reference the old graph:

   ```bash
   redis-cli --scan --pattern 'eta:*' | xargs -r redis-cli del
   ```

   (Tile cache expires on its own within 5 minutes; ETA entries live 1 hour.)

5. Watch the API logs for `RouteNotFound` spikes — a truncated extract or a
   changed bounding box shows up as unroutable orders.

## Rollback

The nightly dump contains the previous `ways` tables. Restore just those:

```bash
pg_restore -U cartograph -d cartograph --no-owner \
  -t ways -t ways_vertices_pgr --clean backups/<previous>.dump
```

Then repeat step 4 (flush `eta:*`).
