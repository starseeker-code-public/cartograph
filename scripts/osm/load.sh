#!/usr/bin/env bash
# Load an OSM extract into Postgres via osm2pgrouting.
# Usage: bash scripts/osm/load.sh <city>
# Requires: osm2pgrouting installed and on PATH; Postgres running.
#
# WARNING: This creates/replaces the 'ways' and 'ways_vertices_pgr' tables.
# pgr_createTopology is run internally and is slow on large extracts.
# Always confirm before running against a production DB.

set -euo pipefail

CITY="${1:-madrid}"
PBF="scripts/osm/${CITY}.osm.pbf"
DB_HOST="${PGHOST:-localhost}"
# Local dev postgres is published on 5433 (see infra/compose/docker-compose.dev.yml).
DB_PORT="${PGPORT:-5433}"
DB_USER="${PGUSER:-cartograph}"
DB_NAME="${PGDATABASE:-cartograph}"

if [[ ! -f "$PBF" ]]; then
  echo "ERROR: $PBF not found. Run: bash scripts/osm/download.sh $CITY"
  exit 1
fi

echo "Loading $PBF into $DB_NAME on $DB_HOST:$DB_PORT …"
osm2pgrouting \
  -f "$PBF" \
  -d "$DB_NAME" \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  --clean

echo "Done. Verify with: psql -c 'SELECT count(*) FROM ways;'"
