# PostGIS base with pgrouting + pg_partman added from the PGDG apt repo.
# The plain postgis/postgis image does NOT ship pgrouting, and the
# pgrouting/pgrouting hub image (16-3.4-3.6.1) is broken upstream
# (zero-byte extension/control files), so we install both extensions here.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       postgresql-16-pgrouting \
       postgresql-16-partman \
    && rm -rf /var/lib/apt/lists/*
