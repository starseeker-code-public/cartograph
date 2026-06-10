# OSM Data

OSM extract files are **not** committed to the repository (they can be hundreds of MB).

## Download

```bash
just osm-download madrid
```

This calls `scripts/osm/download.sh madrid` which downloads the Madrid extract from Geofabrik.

## Load into Postgres

```bash
just osm-load madrid
```

This calls `scripts/osm/load.sh madrid` which runs `osm2pgrouting` to import the `.osm.pbf` into the `ways` and `ways_vertices_pgr` tables.

**Note**: `pgr_createTopology` runs as part of this import and is slow for large extracts. It is effectively a one-shot operation — confirm before re-running against a live database.

## Refresh cadence

Quarterly refresh recommended. See `docs/runbooks/osm-refresh.md` for the full procedure.
