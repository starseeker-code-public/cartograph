#!/usr/bin/env bash
# Download an OSM extract from Geofabrik.
# Usage: bash scripts/osm/download.sh <city>
# Example: bash scripts/osm/download.sh madrid
#
# Edit EXTRACT_URL to point to your region's .osm.pbf before running.

set -euo pipefail

CITY="${1:-madrid}"
DEST="scripts/osm/${CITY}.osm.pbf"

declare -A URLS
URLS["madrid"]="https://download.geofabrik.de/europe/spain/madrid-latest.osm.pbf"
# Add more city → URL mappings here as needed.

URL="${URLS[$CITY]:-}"
if [[ -z "$URL" ]]; then
  echo "ERROR: No URL configured for city '$CITY'."
  echo "Edit scripts/osm/download.sh and add an entry to URLS[]."
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
echo "Downloading $CITY extract from $URL …"
wget -c "$URL" -O "$DEST"
echo "Saved to $DEST"
