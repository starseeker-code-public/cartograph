#!/bin/bash
# Nightly pg_dump (rotating) + daily pg_partman maintenance, anchored to a
# fixed wall-clock time so the schedule neither drifts by the dump duration
# nor fires immediately on every container restart.
# Runs inside the cartograph-postgres image (has pg_dump + psql).
set -euo pipefail

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
RUN_AT="${MAINTENANCE_RUN_AT:-02:00}"

echo "maintenance loop started (daily at ${RUN_AT} UTC, keep ${KEEP_DAYS} days of dumps)"

while true; do
  # Sleep until the next RUN_AT.
  now=$(date +%s)
  next=$(date -d "today ${RUN_AT}" +%s)
  if (( next <= now )); then
    next=$(date -d "tomorrow ${RUN_AT}" +%s)
  fi
  sleep $(( next - now ))

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
done
