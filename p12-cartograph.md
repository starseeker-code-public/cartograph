# P12 Cartograph — geospatial intelligence platform

> **Drop-in agent brief.** Copy this file into a fresh repository as `AGENT.md`. Open Claude Code there. Prompt: *"Read AGENT.md and execute Phase 1."* This document is the single source of truth for bootstrapping the project.

---

## 1. Mission

A geospatial intelligence API for last-mile delivery operations of small-to-medium courier businesses. Customers upload their service area + delivery rules + driver locations + active orders. Cartograph plans routes, computes ETAs, alerts on geo-fence violations, surfaces analytics on coverage gaps. A lightweight Onfleet / Routific competitor scoped to small courier shops (food delivery startups, local florists with delivery, courier collectives).

This is the project's **PostGIS / spatial-database / routing-algorithms** vehicle. Lessons:

- **PostGIS** as the primary store; spatial indexes (GiST), spatial queries, geometry vs geography types.
- **pgrouting** for shortest-path on a road graph loaded from OSM extracts.
- **Routing algorithms** — Dijkstra, A*, and a Christofides-style TSP heuristic (nearest-neighbor + 2-opt) for single-driver multi-stop.
- **Vector tiles** (`MVT`) served from PostGIS via `ST_AsMVT` for browser-side fast rendering.
- **H3** hex grid analytics for coverage + demand visualization.
- **Mapping integration** — MapLibre (default) or Mapbox in the React frontend.

The product's UI is a small React + MapLibre app. The depth comes from the spatial work, not the UI.

---

## 2. Operating mode

**Decide alone, no ask:**

- Internal Python / Go module structure within the chosen stack.
- SRID handling internals (input is always 4326; reprojection to local UTM happens via `ST_Transform`).
- Cache key naming (e.g. `eta:<from_lat>,<from_lng>:<to_lat>,<to_lng>`).
- React component organization in the frontend.
- Test fixtures.
- Commit messages within Conventional Commits.

**Ask first:**

- **Stack** — **Python (FastAPI + GeoAlchemy2 + SQLAlchemy 2.0 async)** (default) vs **Go (chi + pgx with PostGIS bindings)**. Brief assumes Python; Go is a fine alternative.
- Map provider — **MapLibre + OSM tiles** (free, default) vs **Mapbox** (free tier with API key) vs self-hosted MapTiler.
- OSM extract scope — single city (small) vs single country (medium) vs continent (large; not realistic on a Pi). Default: the user's city + 50 km radius.
- Routing engine — **pgrouting** (default, lives in Postgres) vs self-hosted **Valhalla** / **OSRM** (V3 stretch comparison).
- Frontend — single-page or per-tenant subdomain like P3 Atelier.
- Anything that locks long-term direction.
- Tenant model — single-tenant V1 (one courier per deployment) is the default; full multi-tenant is V2+.

**Confirm destructive actions before executing:**

- Drops/recreates of OSM tables (millions of rows; expensive to reload).
- Migrations that drop spatial indexes.
- `pgr_createTopology` on a road graph (long-running; one-shot).
- Force-pushing or rewriting commits on `main`.
- Deletion of historical orders/routes/geo-fence-events (audit data).

---

## 3. Tech stack (exact)

### Backend (default: Python)

- **Python 3.12+**.
- **FastAPI 0.115+**.
- **SQLAlchemy 2.0 async** with **GeoAlchemy2 0.15+**.
- **Alembic 1.13+** with `geoalchemy2` `op.create_index(..., postgresql_using='gist', ...)` patterns.
- **`asyncpg`** driver (faster than psycopg for read-heavy spatial workloads).
- **`shapely 2.x`** for geometry math in the app layer.
- **`h3-py 4.x`** for H3 hex grid operations.
- **`mapbox-vector-tile 2.x`** OR custom `ST_AsMVT` SQL (the brief uses ST_AsMVT — server-side at PostGIS).
- **`pyproj 3.x`** for projection edge cases.
- **`anthropic`** NOT used here (Cartograph has no AI integration in its base brief).
- **`structlog`** + **OpenTelemetry**.

### Backend (alternative: Go)

- Go 1.23+.
- `chi/v5` router.
- `pgx/v5` driver with `pgxgeometry` (or `peterstace/simplefeatures` for parsing).
- `uber/h3-go/v4`.

### Database

- **PostgreSQL 16+** with extensions:
  - **PostGIS 3.4+**.
  - **pgrouting 3.6+**.
  - **postgis_raster** (for elevation tiles, V3 stretch).
  - **pg_partman** for time-partitioning of `geofence_events` (monthly).
- **Redis 7.x** for caching ETA + tile cache.

### Frontend

- **React 19** + TypeScript 5.5+ + Vite 6 + Tailwind v4 + shadcn/ui.
- **MapLibre GL JS 4.x** (default) OR **Mapbox GL JS** (commercial alternative).
- **`@turf/turf 7.x`** for client-side geometry helpers.
- **TanStack Router/Query**.

### Infra

- **Docker + Compose v2**.
- **Caddy** reverse proxy with auto-HTTPS (per `tools/caddy.md`).
- **Tailscale** for drivers' phones to reach the API privately during pilot deployments.
- **Hearth (P1)** as primary deploy; small VM as fallback.

### Tooling

- **`uv`** Python deps.
- **`ruff` + `mypy --strict` + `black`**.
- **`osm2pgrouting`** OR **`osm2pgsql`** for OSM extract loading.
- **`tippecanoe`** as a stretch alternative to `ST_AsMVT` for vector-tile generation.
- **`pytest` + `pytest-asyncio`**.
- **`just`** for cross-stack tasks.

---

## 4. Repository scaffolding

```bash
mkdir cartograph && cd cartograph
git init && git branch -M main

mkdir -p \
  apps/api/cartograph \
  apps/web \
  infra/{compose,seed,osm} \
  scripts/osm \
  docs/{architecture,runbooks} \
  .github/workflows

# Backend (Python).
cd apps/api
uv venv
uv pip install fastapi uvicorn[standard] sqlalchemy[asyncio] alembic asyncpg \
    geoalchemy2 shapely h3 pyproj redis httpx \
    pydantic pydantic-settings structlog opentelemetry-instrumentation-fastapi
uv pip install --dev pytest pytest-asyncio ruff black mypy

# Frontend.
cd ../web
npm create vite@latest . -- --template react-ts
npm i react@19 react-dom@19 @tanstack/react-router @tanstack/react-query
npm i maplibre-gl @turf/turf
npm i -D tailwindcss@next @tailwindcss/vite@next vitest playwright
npx shadcn@latest init
```

---

## 5. Phase plan summary

| Phase | Goal | Effort |
|---|---|---|
| 1 | Bootstrap: PostGIS in Compose; FastAPI scaffold | 1 weekend |
| 2 | Schema: ServiceArea, Driver, Order, Route, GeofenceEvent | 1 weekend |
| 3 | Service-area management (GeoJSON polygon upload) | 1 weekend |
| 4 | ETA computation via OSM road network + pgrouting | 1-2 weekends |
| 5 | Geo-fences (buffer rings + dwell rules) | 1 weekend |
| 6 | Vector tiles (`GET /tiles/{z}/{x}/{y}.mvt`) | 1 weekend |
| 7 | Single-driver TSP optimizer (nearest-neighbor + 2-opt) | 1-2 weekends |
| 8 | Coverage analytics (H3 hex grid) | 1 weekend |
| 9 | Frontend: tiny React + MapLibre app | 1-2 weekends |
| 10 | Deploy: Compose on Hearth or small VM | 1 weekend |

**Stretch**: real-time driver-position updates over WebSockets + replay; per-hex demand prediction for capacity planning; multi-driver VRP with time windows; replace pgrouting with self-hosted Valhalla / OSRM and compare.

---

## 6. Phase 1 in detail — bootstrap

**Outcome**: A FastAPI service connected to a PostGIS-enabled Postgres. `GET /healthz` returns 200. `SELECT PostGIS_Full_Version();` works.

### 6.1 Compose

`infra/compose/docker-compose.dev.yml`:

```yaml
services:
  postgres:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: cartograph
      POSTGRES_PASSWORD: cartograph
      POSTGRES_DB: cartograph
    ports: ["5432:5432"]
    volumes:
      - cartograph_pg:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

volumes:
  cartograph_pg: {}
```

`infra/compose/init.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 6.2 Definition of done — Phase 1

- [ ] `docker compose up -d` starts PostGIS + Redis.
- [ ] `psql -c "SELECT PostGIS_Full_Version();"` returns a version string with PostGIS + pgrouting.
- [ ] `uv run uvicorn cartograph.main:app --reload` serves `/healthz`.
- [ ] CI green.

---

## 7. Phase 2 in detail — schema

**Outcome**: SQLAlchemy + GeoAlchemy2 mappers + Alembic migration creating the spatial tables with GiST indexes.

### 7.1 Schema

```python
from geoalchemy2 import Geometry, Geography
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ServiceArea(Base):
    __tablename__ = "service_areas"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    name: Mapped[str]
    geom: Mapped[str] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    rules: Mapped[dict] = mapped_column(JSONB, default=dict)        # min/max order value, hours, vehicle types
    __table_args__ = (Index("ix_service_areas_geom", "geom", postgresql_using="gist"),)


class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    name: Mapped[str]
    phone: Mapped[str]
    vehicle_type: Mapped[str]                              # bike, scooter, car, van
    current_location: Mapped[str | None] = mapped_column(Geography("POINT", srid=4326), nullable=True)
    current_location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str]                                     # offline, idle, en_route
    __table_args__ = (Index("ix_drivers_loc", "current_location", postgresql_using="gist"),)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    pickup: Mapped[str] = mapped_column(Geography("POINT", srid=4326))
    delivery: Mapped[str] = mapped_column(Geography("POINT", srid=4326))
    pickup_address: Mapped[str]
    delivery_address: Mapped[str]
    promised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str]                                     # created, assigned, picked_up, delivered, failed, cancelled
    driver_id: Mapped[UUID | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        Index("ix_orders_pickup", "pickup", postgresql_using="gist"),
        Index("ix_orders_delivery", "delivery", postgresql_using="gist"),
    )


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"))
    order_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID))
    sequence: Mapped[list[int]] = mapped_column(ARRAY(Integer))   # index into order_ids
    geom: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326))
    total_distance_m: Mapped[int]
    total_duration_s: Mapped[int]


class GeofenceEvent(Base):
    __tablename__ = "geofence_events"
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    kind: Mapped[str]                                      # entered, exited, dwell_threshold
    location: Mapped[str] = mapped_column(Geography("POINT", srid=4326))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

### 7.2 SRIDs

- Input + storage in **4326** (WGS84). Standard for GeoJSON, browsers, Mapbox.
- For accurate distance / area, reproject to a local UTM zone via `ST_Transform`. The brief picks UTM at runtime via `ST_UTMzone(geom)` (Postgis function — verify availability; otherwise compute zone from longitude in app).

### 7.3 pg_partman for geofence_events

`geofence_events` is monthly-partitioned. A scheduled job (cron in Compose, CronJob in k8s) creates next-month partitions before the rollover.

### 7.4 Definition of done — Phase 2

- [ ] All tables exist with GiST indexes.
- [ ] Inserting a sample row works.
- [ ] `\d service_areas` shows the `geom` column with type `geometry(MultiPolygon, 4326)`.
- [ ] Partman setup applied.

---

## 8. Phase 3 in detail — service-area management

**Outcome**: Customer uploads a GeoJSON polygon for their service area. The API stores it; queries support "is this point inside any service area?".

### 8.1 Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/service-areas` | Create from GeoJSON |
| GET | `/api/service-areas` | List for current tenant |
| GET | `/api/service-areas/{id}` | Detail |
| PATCH | `/api/service-areas/{id}` | Update name/rules/geometry |
| DELETE | `/api/service-areas/{id}` | Delete |
| GET | `/api/service-areas/contains?lng=&lat=` | Returns matching service-area IDs |

### 8.2 GeoJSON validation

Validate incoming GeoJSON:

- Must be `Feature` or `FeatureCollection` with at least one Polygon/MultiPolygon.
- Coordinates in EPSG:4326.
- `ST_IsValid(geom)` on insert; reject invalid (self-intersecting) polygons with a clear error.

### 8.3 Containment query

```sql
SELECT id
FROM service_areas
WHERE tenant_id = :tenant
  AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326));
```

GiST index handles this efficiently.

### 8.4 Definition of done — Phase 3

- [ ] Upload + retrieve a GeoJSON polygon round-trips losslessly.
- [ ] Invalid GeoJSON rejected with helpful error.
- [ ] Containment query < 5 ms p95.
- [ ] Tests cover: simple polygon, multi-polygon, polygon with holes, invalid geom.

---

## 9. Phase 4 in detail — ETA computation

**Outcome**: For an order, query an OSM road network via pgrouting; compute the shortest path; cache the result. ETA returned in seconds + a route polyline.

### 9.1 OSM extract

```bash
# Download a city extract:
wget https://download.geofabrik.de/europe/spain/madrid-latest.osm.pbf -O scripts/osm/madrid.osm.pbf

# Convert to pgrouting topology:
osm2pgrouting -f scripts/osm/madrid.osm.pbf -d cartograph -h localhost -U cartograph
```

This produces `ways` (linestrings with cost) and `ways_vertices_pgr` (graph nodes). `cost` is travel time in seconds (default heuristic; refine with vehicle profile in V2).

### 9.2 Routing query

```sql
WITH src AS (
  SELECT id FROM ways_vertices_pgr ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:src_lng, :src_lat), 4326) LIMIT 1
), dst AS (
  SELECT id FROM ways_vertices_pgr ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:dst_lng, :dst_lat), 4326) LIMIT 1
)
SELECT seq, edge, cost, agg_cost, ST_AsGeoJSON(the_geom) AS geom
FROM pgr_dijkstra(
  'SELECT gid AS id, source, target, cost FROM ways',
  (SELECT id FROM src),
  (SELECT id FROM dst),
  directed := true
) p
JOIN ways w ON w.gid = p.edge;
```

Aggregate the linestring with `ST_LineMerge(ST_Collect(...))` for the response.

### 9.3 Cache layer

```
GET eta:<from_lng>,<from_lat>:<to_lng>,<to_lat>:<vehicle>
```

TTL 1 hour; invalidate on OSM extract reload.

### 9.4 Vehicle profiles (V1 simplified)

V1: cost is "all-vehicles same speed" minus banned categories (e.g. cars on pedestrian streets).

V2: per-vehicle profiles (bike vs car) by filtering `ways` on `tag_id`.

### 9.5 Definition of done — Phase 4

- [ ] Loading the OSM extract succeeds.
- [ ] Shortest-path query returns sensible results within 100 ms p95 on a Pi.
- [ ] Cached responses < 5 ms.
- [ ] Routes returned as GeoJSON LineString.

---

## 10. Phase 5 in detail — geo-fences

**Outcome**: Configurable buffer rings around delivery points; entering / exiting / dwell events emitted.

### 10.1 Schema additions

`Order.geofence_meters` (default 200 m). The geofence is implicit: `ST_Buffer(delivery::geometry, geofence_meters)`. (Stored as geography for accurate buffering across latitudes.)

### 10.2 Driver position update endpoint

`POST /api/drivers/{id}/location` accepts `{ lat, lng, ts, accuracy_m }`:

1. Update `drivers.current_location` and `current_location_updated_at`.
2. For active orders assigned to this driver, run:

   ```sql
   SELECT id, ST_Distance(delivery, :loc::geography) AS dist
   FROM orders
   WHERE driver_id = :driver AND state = 'assigned';
   ```

3. If distance crosses `geofence_meters` from outside → inside, emit `entered` event.
4. If crosses from inside → outside, emit `exited`.
5. Track dwell time via `(SELECT MAX(ts) FROM geofence_events WHERE order_id = X AND kind = 'entered')`. If still inside after `dwell_threshold_seconds` (default 600), emit `dwell_threshold`.

### 10.3 Definition of done — Phase 5

- [ ] Geofence events fire correctly in unit + integration tests.
- [ ] Dwell threshold respects re-entry (resets timer if exited).
- [ ] No duplicate events on jittery GPS (debounce via accuracy filter).

---

## 11. Phase 6 in detail — vector tiles

**Outcome**: `GET /tiles/{z}/{x}/{y}.mvt` returns a Mapbox Vector Tile rendering the user's data (service areas + active orders + driver positions). MapLibre consumes it.

### 11.1 ST_AsMVT query

```sql
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS env
)
SELECT ST_AsMVT(t, 'service_areas', 4096, 'geom') FROM (
  SELECT id, name,
         ST_AsMVTGeom(ST_Transform(geom, 3857), bounds.env, 4096, 64, true) AS geom
  FROM service_areas, bounds
  WHERE tenant_id = :tenant AND geom && ST_Transform(bounds.env, 4326)
) t;
```

Concatenate multiple layers in one tile via successive `ST_AsMVT` calls + `||` concatenation.

### 11.2 Caching

- Tile responses cached in Redis with key `tile:<tenant>:<z>:<x>:<y>`.
- Invalidation on writes that affect that tenant's geometry; bulk-invalidate on service-area edits.

### 11.3 Definition of done — Phase 6

- [ ] MapLibre style references the tile endpoint and renders.
- [ ] Tile p95 < 100 ms.
- [ ] Tiles are auth'd (tenant context via session/cookie).
- [ ] Cache hit ratio visible in metrics.

---

## 12. Phase 7 in detail — single-driver TSP optimizer

**Outcome**: Given a single driver and a set of orders to visit, compute a near-optimal sequence using nearest-neighbor + 2-opt.

### 12.1 Algorithm

1. **Nearest-neighbor**: start from the driver's current location; repeatedly pick the unvisited order whose pickup is closest in road-network distance.
2. **2-opt**: iteratively swap pairs of edges to reduce total length until no improving swap exists.
3. **Bound**: stop after N iterations or X seconds.

For ≤ 20 stops this finishes in well under a second.

### 12.2 Endpoint

`POST /api/drivers/{id}/optimize` returns the ordered sequence + total distance + total ETA.

### 12.3 Definition of done — Phase 7

- [ ] 20-stop optimization < 1 s.
- [ ] Result is within 5% of the brute-force optimum on small (≤ 7) test cases.
- [ ] Pickup-before-delivery constraint respected: every pickup precedes its delivery in the sequence.

---

## 13. Phase 8 in detail — coverage analytics (H3)

**Outcome**: For a tenant, render an H3 hex grid colored by order density / coverage gaps over a time range.

### 13.1 H3 in PostGIS

Use the `h3-pg` extension OR compute hex IDs in Python and store as a column:

```python
import h3
hex_id = h3.latlng_to_cell(lat, lng, resolution=8)   # ~0.7 km hex
```

Add `pickup_h3_8` and `delivery_h3_8` columns to `orders`. Index them.

### 13.2 Coverage query

```sql
SELECT pickup_h3_8 AS hex, COUNT(*) AS orders
FROM orders
WHERE tenant_id = :tenant AND created_at BETWEEN :from AND :to
GROUP BY pickup_h3_8;
```

The frontend turns each `hex` into the H3 boundary GeoJSON via `@turf/h3-grid`.

### 13.3 Definition of done — Phase 8

- [ ] Grid renders for a time range.
- [ ] Resolution selectable (7-9).
- [ ] Color scale documented.

---

## 14. Phase 9 in detail — frontend

**Outcome**: A small React + MapLibre app:

- Login (single tenant V1).
- Map view: service area + drivers + active orders + tile-layer of geo-fences.
- Order detail panel: pickup, delivery, ETA, status.
- Driver detail panel: current location, assigned orders, optimize button.
- Coverage panel: H3 hex grid.

### 14.1 MapLibre style

Custom `style.json` with:

- Base layer: OSM raster tiles (free) or vector tiles from MapTiler (key required).
- Overlay sources from `/tiles/{z}/{x}/{y}.mvt`.
- Driver pins + order pins as separate sources.

### 14.2 Definition of done — Phase 9

- [ ] Map loads.
- [ ] Order pins click → detail panel.
- [ ] Driver position updates live (polling V1; WS in V3 stretch).
- [ ] H3 grid renders.
- [ ] Lighthouse ≥ 85.

---

## 15. Phase 10 in detail — deploy

- Compose stack on Hearth or a small VM.
- Caddy reverse proxy with auto-HTTPS.
- Tailscale-only by default (drivers' phones reach the API via the tailnet during pilot).
- Backups: nightly `pg_dump` to S3 / Backblaze.

### Definition of done — Phase 10

- [ ] Deployed and accessible.
- [ ] Backup + restore drill executed.
- [ ] Documentation: README, deployment runbook.

---

## 16. File structure (target)

```
cartograph/
├── AGENT.md
├── README.md
├── justfile
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   ├── cartograph/
│   │   │   ├── main.py
│   │   │   ├── settings.py
│   │   │   ├── deps.py
│   │   │   ├── auth/
│   │   │   ├── service_areas/
│   │   │   ├── drivers/
│   │   │   ├── orders/
│   │   │   ├── routes/
│   │   │   ├── geofences/
│   │   │   ├── tiles/
│   │   │   ├── analytics/
│   │   │   └── tests/
│   │   └── .env.example
│   └── web/
│       ├── package.json
│       ├── vite.config.ts
│       ├── tailwind.config.ts
│       ├── tsconfig.json
│       └── src/
│           ├── routes/
│           ├── components/
│           ├── lib/
│           └── styles/
├── infra/
│   ├── compose/
│   │   ├── docker-compose.dev.yml
│   │   ├── docker-compose.prod.yml
│   │   └── init.sql
│   ├── seed/
│   └── osm/
│       └── README.md
├── scripts/
│   └── osm/
│       ├── download.sh
│       └── load.sh
└── docs/
    ├── architecture/
    └── runbooks/
```

---

## 17. Cross-cutting concerns

### 17.1 Testing

- pytest + pytest-asyncio.
- Spatial tests use a fixture loading a small OSM extract (a single neighborhood).
- Coverage gate ≥ 70% on routing + geofence modules.
- Frontend: vitest + Playwright with MapLibre stubbed for unit tests; real e2e on a dev server.
- Performance regression: ETA queries < 100 ms p95.

### 17.2 Security

- Tenant isolation on every query.
- Driver location sharing only authorized within the tenant.
- HTTPS via Caddy + Tailscale-only by default.
- Argon2id for passwords.
- Rate limiting on `/api/drivers/{id}/location` (per driver, generous; the device is the source).
- Driver phone numbers PII-flagged in logs.

### 17.3 Performance budgets

- Tile p95 < 100 ms.
- ETA p95 < 100 ms (cached) / < 300 ms (uncached).
- Order list p95 < 50 ms.
- Optimization (20 stops) < 1 s.

### 17.4 Operational

- OSM extract refresh quarterly; documented in `docs/runbooks/osm-refresh.md`.
- pg_partman cron creates next-month geofence partitions.
- Backup restic-style nightly.

---

## 18. Anti-goals (do NOT do)

- **Don't try to route across an entire country.** A city + 50 km is the V1 scope; a country requires sharding strategies you don't need for a courier shop.
- **Don't try to build Onfleet.** The dispatcher UX is intentionally minimal.
- **Don't go to mobile.** Drivers use the web UI on phones via Tailscale; native apps are V3+.
- **Don't dump raw geometry from clients without `ST_IsValid`.**
- **Don't store geometries in mixed SRIDs.** 4326 in, transform inside queries when needed.
- **Don't compute distances with `ST_Distance(geometry, geometry)` in degrees.** Use geography or transform to UTM first.
- **Don't try to do real-time stream of driver locations to all browsers in V1.** Polling is fine; WS is V3.
- **Don't bypass the cache for unchanged tiles.** Cache invalidation is a feature; document it.
- **Don't ship the OSM extract in the repo.** It's downloaded on demand via `scripts/osm/download.sh`.
- **Don't bake Mapbox tokens into the frontend bundle.** Env-driven and rotated.
- **Don't generate boilerplate the user did not ask for.** No LICENSE until chosen.

---

## 19. Definition of done — V1 (phases 1–10)

- One tenant can configure a service area, register drivers, accept orders, see ETAs, see geofence events, run TSP optimization, view H3 coverage.
- Deployed on Hearth or a VM with backups.
- Lighthouse ≥ 85.
- Documentation complete.

## 20. Definition of done — V2 (stretch)

- Real-time driver position updates via WebSockets.
- Per-vehicle profiles in routing.
- Multi-driver VRP with time windows.

## 21. Definition of done — V3 (full stretch)

The user picks one or more:

- Self-hosted Valhalla or OSRM compared with pgrouting.
- Per-hex demand prediction with a small ML model.
- Native mobile drivers' app.
- Multi-tenant onboarding.

---

## 22. Open questions for the user

1. License.
2. Stack — Python (default) or Go?
3. Map provider — MapLibre+OSM (default), Mapbox, or MapTiler?
4. OSM extract scope (city, country).
5. Routing engine in V3 stretch — Valhalla, OSRM, or stay on pgrouting?
6. Frontend — single-tenant V1 vs multi-tenant subdomains.
7. Branding visible to users.
8. Domain (`carto.<domain>`).
9. Driver authentication — tenant-issued tokens vs per-driver SSO?
10. Anonymous driver-position simulator for dev?

---

## 23. References

- `projects.md` §P12 (the source).
- `tools/postgres.md` §29-30 (PostGIS), §31.
- `tools/system-design-architecture.md` §18.
- `tools/api-design.md`, `tools/networking.md`.
- `tools/caddy.md`, `tools/tailscale.md`.
- The PostGIS docs.
- The pgrouting docs.
- The H3 docs (`https://h3geo.org/`).
- The Mapbox Vector Tile spec.
- MapLibre GL JS docs.

---

## 24. The agent's first commit

`chore: phase 1 bootstrap` — `AGENT.md`, README, .gitignore, the empty FastAPI skeleton, `infra/compose/docker-compose.dev.yml`, `infra/compose/init.sql` with the PostGIS extensions.

---

## 25. When in doubt

Ask. Especially when the question concerns:

- Anything that touches the OSM extract (regenerating it is hours).
- Anything that drops spatial indexes.
- Adding a new vehicle profile to the routing cost model.
- Going from polling to WebSockets for driver positions.
- Multi-tenancy boundary breaches.
- Sharing driver locations cross-tenant.

Otherwise, proceed.
