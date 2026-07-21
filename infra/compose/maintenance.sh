#!/bin/bash
# Nightly pg_dump (rotating) + daily pg_partman maintenance.
# Runs inside the cartograph-postgres image (has pg_dump + psql).
set -euo pipefail

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

echo "maintenance loop started (keep ${KEEP_DAYS} days of dumps)"

while true; do
  # ── Backup ────────────────────────────────────────────────────────────────
  STAMP="$(date +%Y%m%d-%H%M%S)"
  DUMP="/backups/cartograph-${STAMP}.dump"
  echo "[$(date -Is)] pg_dump → ${DUMP}"
  if pg_dump --format=custom --compress=6 --file="${DUMP}.tmp"; then
    mv "${DUMP}.tmp" "${DUMP}"
    echo "[$(date -Is)] backup ok ($(du -h "${DUMP}" | cut -f1))"
  else
    rm -f "${DUMP}.tmp"
    echo "[$(date -Is)] BACKUP FAILED" >&2
  fi

  # Rotate old dumps.
  find /backups -name 'cartograph-*.dump' -mtime "+${KEEP_DAYS}" -delete

  # ── pg_partman maintenance (creates next months' partitions) ─────────────
  echo "[$(date -Is)] partman.run_maintenance()"
  psql -c "SELECT partman.run_maintenance();" || echo "[$(date -Is)] partman maintenance failed" >&2

  # Once a day.
  sleep 86400
done
