# Cartograph

**A geospatial intelligence API for last-mile delivery operations.** Built for small-to-medium courier businesses — food-delivery startups, local florists, courier collectives — that need real route planning, ETAs, geo-fence alerting, and coverage analytics without paying enterprise pricing for Onfleet or Routific.

PostGIS + pgrouting + FastAPI on the backend. MapLibre + React on the frontend. Everything self-hostable; the pilot deployment target is a single VM or a Raspberry Pi behind Tailscale.

> **Project status**: V1 feature-complete (Phases 1–10). Deploy artifacts ready; production rollout + backup drill pending on the target host. See the [phase plan](#phase-plan) below.

---

## Table of contents

- [What Cartograph does](#what-cartograph-does)
- [Architecture at a glance](#architecture-at-a-glance)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Phase plan](#phase-plan)
- [Repository layout](#repository-layout)
- [Development workflow](#development-workflow)
- [OSM data](#osm-data)
- [Performance budgets](#performance-budgets)
- [Anti-goals](#anti-goals)
- [Deployment](#deployment)
- [Security model](#security-model)
- [Definition of done — V1 / V2 / V3](#definition-of-done)
- [Contributing](#contributing)
- [References](#references)
- [License](#license)

---

## What Cartograph does

A courier shop signs up, uploads a **service-area polygon** (their delivery zone), registers **drivers** with their vehicle types, and starts accepting **orders**. Cartograph:

- **Plans routes** for a single driver visiting multiple pickups + drop-offs (TSP nearest-neighbor + 2-opt; ≤ 20 stops, ≤ 1 s).
- **Computes ETAs** against a real OSM road network via pgrouting, cached in Redis.
- **Alerts on geo-fence violations** — entering, exiting, or dwelling near a delivery point.
- **Surfaces coverage analytics** — H3 hex grids over time windows show demand density and gaps.
- **Serves vector tiles** (`ST_AsMVT`) directly from PostGIS for fast browser rendering with MapLibre.

The product surface is intentionally small. The depth is in the spatial machinery: **PostGIS** as primary store, **pgrouting** for shortest-path, **H3** for analytics, **vector tiles** at the database edge. The frontend is a tiny React app that exists to demo the API, not to be a polished dispatcher UI.

---

## Architecture at a glance

```text
┌──────────────────────────────────────────────────────────────────┐
│                        Browser / Driver phone                     │
│                    React + MapLibre GL JS 4.x                     │
│                    (vector tiles + REST API)                      │
└────────────────────┬─────────────────────────────────────────────┘
                     │  HTTPS via Caddy (auto-TLS)
                     │  Tailscale-only by default
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI (Python 3.12)                       │
│   service_areas │ drivers │ orders │ routes │ geofences          │
│            tiles  │  analytics  │  auth                          │
│                                                                   │
│   SQLAlchemy 2.0 async + GeoAlchemy2 + asyncpg                    │
└────────────┬───────────────────────────────────────┬─────────────┘
             │                                       │
             ▼                                       ▼
   ┌──────────────────────┐                ┌──────────────────────┐
   │  PostgreSQL 16       │                │   Redis 7            │
   │  + PostGIS 3.4       │                │   - ETA cache        │
   │  + pgrouting 3.6     │                │   - Tile cache       │
   │  + pg_partman        │                └──────────────────────┘
   │  + pg_trgm           │
   │                      │
   │  ways / vertices     │  ← osm2pgrouting (Madrid extract)
   │  service_areas       │
   │  drivers / orders    │
   │  geofence_events     │  ← monthly partitions
   └──────────────────────┘
```

- **SRID 4326** everywhere on the wire; reprojected to local UTM via `ST_Transform` for accurate distance / area.
- **Geometry vs Geography**: polygons use `geometry(MULTIPOLYGON, 4326)` (faster, indexed); points used for distance use `geography(POINT, 4326)` (correct across latitudes).
- **Vector tiles** produced server-side with `ST_AsMVT(ST_AsMVTGeom(ST_Transform(geom, 3857), …))` — no tile-generation pipeline needed.
- **Single-tenant V1** (one courier per deployment). Multi-tenant onboarding is a V3 stretch.

---

## Tech stack

### Backend

| Layer | Choice |
| --- | --- |
| Language | Python 3.12+ |
| Web framework | FastAPI 0.115+ |
| ORM / DB | SQLAlchemy 2.0 async, GeoAlchemy2 0.15+, asyncpg, Alembic 1.13+ |
| Geometry | Shapely 2.x, pyproj 3.x |
| H3 | `h3-py` 4.x |
| Vector tiles | `ST_AsMVT` server-side (PostGIS native) |
| Auth | Argon2id + JWT |
| Observability | structlog + OpenTelemetry |

### Database

| Component | Version | Purpose |
| --- | --- | --- |
| PostgreSQL | 16+ | Primary store |
| PostGIS | 3.4+ | Spatial types + indexes |
| pgrouting | 3.6+ | Shortest-path on road graph |
| pg_partman | latest | Monthly time-partitioning of `geofence_events` |
| pg_trgm | builtin | Fuzzy address search (Phase 3+) |
| Redis | 7.x | ETA + tile cache |

### Frontend (Phase 9)

| Layer | Choice |
| --- | --- |
| Framework | React 19 + TypeScript 5.5+ |
| Bundler | Vite 6 |
| Styling | Tailwind v4 (hand-rolled components — shadcn/ui deemed unnecessary for this surface) |
| Map | MapLibre GL JS 4.x (default) — Mapbox / MapTiler are alternatives |
| Routing | TanStack Router + TanStack Query |
| Geo helpers | `h3-js` 4.x (hex boundaries) |

### Infra & tooling

`uv` (deps) · `just` (task runner) · Docker Compose v2 · Caddy (auto-HTTPS) · Tailscale (private API) · `osm2pgrouting` (OSM ingest) · `ruff` + `black` + `mypy --strict` · `pytest` + `pytest-asyncio` · GitHub Actions CI.

> A **Go** alternative stack (chi + pgx + uber/h3-go) is documented in [AGENT.md](AGENT.md) §3 but **not** the default. The Python stack is what ships.

---

## Quick start

**Prerequisites:** Docker Compose v2, [`just`](https://github.com/casey/just), [`uv`](https://docs.astral.sh/uv/), and `psql` on PATH.

```bash
git clone <repo> cartograph && cd cartograph

just up                 # starts PostGIS + Redis
just postgis-version    # → POSTGIS=3.4.x PGSQL=160 …  GEOS=…  PROJ=…

cd apps/api
cp .env.example .env    # adjust SECRET_KEY for non-trivial use
cd ../..
just install-dev        # uv sync --extra dev
just migrate            # alembic upgrade head
just seed               # demo tenant + dispatcher@example.com / cartograph-dev
just dev                # uvicorn --reload on :8000

# In a second terminal — the dispatcher UI:
just web-install
just web-dev            # http://localhost:5173 (proxies /api + /tiles to :8000)
```

Verify:

```bash
curl http://localhost:8000/healthz   # → {"status":"ok"}
curl http://localhost:8000/readyz    # → checks DB + Redis
```

Run the tests:

```bash
just test                       # full integration suite (needs `just up`)
SKIP_DB_TESTS=1 just test       # unit-only
```

---

## Phase plan

Each phase is sized for a weekend or two of focused work. The depth is in phases 4 / 6 / 7 / 8 — the spatial machinery. Everything else is plumbing.

### Phase 1 — Bootstrap ✅ done

PostGIS + Redis in Compose. FastAPI scaffold with `/healthz` and `/readyz`. Alembic configured. CI workflow runs lint + typecheck + tests against a real PostGIS service. `just` task runner with `up / dev / test / lint / migrate / osm-*`.

**Done when:** `docker compose up` brings up PostGIS + Redis, `SELECT PostGIS_Full_Version()` returns a string with PostGIS + pgrouting, `uv run uvicorn cartograph.main:app` serves `/healthz`, CI green.

### Phase 2 — Schema ✅ done

Six tables with GiST indexes:

- `tenants` — slug + name (single-tenant V1, but the column exists for V2+).
- `service_areas` — `MULTIPOLYGON, srid=4326` + JSONB `rules` (max order value, hours, vehicle types).
- `drivers` — `geography(POINT, 4326)` `current_location` + state enum (offline / idle / en_route).
- `orders` — `geography(POINT)` pickup + delivery + state machine + H3 columns for analytics.
- `routes` — `LINESTRING` route geometry + `order_ids[]` + `sequence[]`.
- `geofence_events` — **partitioned monthly** on `occurred_at` via `pg_partman`.

**Done when:** all tables exist with GiST indexes, sample inserts work, `geofence_events.relkind = 'p'`, pg_partman wired (or default partition catches writes when the extension is absent).

### Phase 3 — Service-area management ✅ done

GeoJSON polygon upload. `ST_IsValid` rejection of self-intersecting geometry. Containment query `ST_Contains(geom, ST_SetSRID(ST_MakePoint(lng, lat), 4326))` < 5 ms p95.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/service-areas` | Create from GeoJSON Feature / FeatureCollection |
| GET | `/api/service-areas` | List for current tenant |
| GET | `/api/service-areas/{id}` | Detail |
| PATCH | `/api/service-areas/{id}` | Update name / rules / geometry |
| DELETE | `/api/service-areas/{id}` | Delete |
| GET | `/api/service-areas/contains?lng=&lat=` | Returns matching IDs |

### Phase 4 — ETA via OSM + pgrouting ✅ done

Load the Madrid OSM extract via `osm2pgrouting` (`just osm-download madrid && just osm-load madrid`). Query shortest paths with `pgr_dijkstra` against the `ways` graph. Cache responses in Redis with key `eta:<from_lng>,<from_lat>:<to_lng>,<to_lat>:<vehicle>` (TTL 1 h). V1 uses a single all-vehicles cost model; per-vehicle profiles are V2.

**Done when:** shortest-path < 100 ms p95, cached < 5 ms, routes returned as GeoJSON LineString.

### Phase 5 — Geo-fences ✅ done

Buffer rings around delivery points: `ST_Buffer(delivery::geography, geofence_meters)` (default 200 m). `POST /api/drivers/{id}/location` updates `current_location` and emits events:

- `entered` — driver crossed from outside → inside the ring.
- `exited` — crossed inside → outside (resets dwell timer).
- `dwell_threshold` — still inside after `dwell_threshold_seconds` (default 600).

GPS jitter is debounced via the `accuracy_m` field.

### Phase 6 — Vector tiles ✅ done

`GET /tiles/{z}/{x}/{y}.mvt` returns a Mapbox Vector Tile with four layers (service areas, geofence rings, active orders, driver positions) generated by `ST_AsMVT` + `ST_AsMVTGeom` inside Postgres. Cached in Redis as `tile:<tenant>:<z>:<x>:<y>`; bulk-invalidated on service-area edits.

**Done when:** tile p95 < 100 ms, MapLibre renders, tiles are tenant-auth'd.

### Phase 7 — Single-driver TSP optimizer ✅ done

`POST /api/drivers/{id}/optimize` runs **nearest-neighbor** seeded at the driver's current location, then **2-opt** until no improving swap exists or N iterations / X seconds elapse. Pickup-before-delivery constraint enforced. ≤ 20 stops finishes well under 1 s. Within 5% of brute-force optimum on small (≤ 7) test cases.

### Phase 8 — Coverage analytics (H3) ✅ done

Pickup + delivery H3 hex IDs (resolution 8, ≈ 0.7 km hex) are stored on every order. Aggregation query groups by hex and counts orders over a time range. Frontend renders the H3 boundaries via `h3-js` `cellToBoundary` with a sequential color scale (pale amber → deep red, normalized to the densest cell). Resolution selectable 7–9.

### Phase 9 — Frontend ✅ done

A small React + MapLibre app: login, map view (service area + drivers + orders + geo-fence tile layer), order detail panel, driver detail panel with optimize button, coverage panel. Driver positions update via polling in V1 (WebSockets in V3 stretch). Lighthouse ≥ 85.

### Phase 10 — Deploy ✅ artifacts ready

Compose stack on a small VM (or Hearth — see references). Caddy reverse-proxy with auto-HTTPS. Tailscale-only by default — drivers' phones reach the API over the tailnet during pilot. Nightly `pg_dump` to S3 / Backblaze. Backup-restore drill required before declaring V1 done.

### Stretch — V2 / V3

| Version | Features |
| --- | --- |
| **V2** | Real-time driver positions via WebSockets · per-vehicle routing profiles (bike vs car) · multi-driver VRP with time windows |
| **V3** | Pick from: self-hosted Valhalla or OSRM (benchmarked vs pgrouting) · per-hex demand prediction (small ML model) · native mobile drivers' app · multi-tenant onboarding |

---

## Repository layout

```text
cartograph/
├── AGENT.md                ← Agent operating brief (the bible for Claude Code)
├── README.md               ← This file
├── LICENSE                 ← AGPL-3.0-or-later
├── justfile                ← All cross-stack tasks
├── apps/
│   ├── api/                ← FastAPI backend
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── migrations/     ← Alembic
│   │   ├── cartograph/
│   │   │   ├── main.py
│   │   │   ├── settings.py
│   │   │   ├── database.py
│   │   │   ├── deps.py
│   │   │   ├── auth/       ← Tenant + auth
│   │   │   ├── service_areas/   ← Phase 3
│   │   │   ├── drivers/         ← Phase 5
│   │   │   ├── orders/
│   │   │   ├── routes/          ← Phase 4 / 7
│   │   │   ├── geofences/       ← Phase 5
│   │   │   ├── tiles/           ← Phase 6
│   │   │   ├── analytics/       ← Phase 8
│   │   │   └── tests/
│   │   └── .env.example
│   └── web/                ← React + MapLibre dispatcher app (Phase 9)
├── infra/
│   ├── compose/
│   │   ├── docker-compose.dev.yml
│   │   ├── docker-compose.prod.yml   ← Phase 10
│   │   └── init.sql                  ← PostGIS + pgrouting + pg_trgm extensions
│   ├── seed/
│   └── osm/                ← OSM extract loading docs
├── scripts/
│   └── osm/
│       ├── download.sh     ← Geofabrik fetch (defaults to Madrid)
│       └── load.sh         ← osm2pgrouting import
├── docs/
│   ├── architecture/
│   └── runbooks/
│       ├── pg-partman.md
│       ├── deploy.md
│       ├── backup-restore.md
│       └── osm-refresh.md
└── .github/workflows/ci.yml
```

---

## Development workflow

All workflows go through `just`:

```bash
# Infra
just up                       # docker compose up (PostGIS + Redis)
just down                     # docker compose down
just logs                     # tail logs
just psql                     # interactive psql
just reset                    # nuke volume + restart (DEV ONLY)

# Backend
just install                  # uv sync (prod deps)
just install-dev              # uv sync --extra dev
just dev                      # uvicorn --reload :8000
just test                     # pytest (integration)
just test-cov                 # pytest + coverage report
just lint                     # ruff + black --check
just format                   # ruff --fix + black
just typecheck                # mypy --strict

# Migrations
just migrate                  # alembic upgrade head
just migrate-down             # alembic downgrade -1
just migrate-new "add field"  # alembic revision --autogenerate

# OSM (Phase 4)
just osm-download madrid      # → scripts/osm/madrid.osm.pbf
just osm-load madrid          # → ways + ways_vertices_pgr

# Frontend
just web-install              # npm install
just web-dev                  # vite dev server on :5173 (proxies /api + /tiles)
just web-test                 # vitest
just web-build                # tsc + vite build
```

### What the agent decides without asking

Internal module structure, SRID handling internals, cache key naming, React component organization, test fixtures, commit messages within Conventional Commits.

### What the agent confirms first

OSM extract reloads (hours to regenerate). Migrations that drop spatial indexes. `pgr_createTopology` on the road graph. Force-pushing `main`. Deleting historical orders / routes / geo-fence events.

See [AGENT.md §2](AGENT.md) for the full operating-mode contract.

---

## OSM data

The Madrid extract is the V1 region (city + ~50 km radius).

```bash
just osm-download madrid    # ~100 MB from Geofabrik
just osm-load madrid        # imports into Postgres via osm2pgrouting
```

The `.osm.pbf` is **never** committed (covered by `.gitignore`). Quarterly refresh recommended; see [docs/runbooks/osm-refresh.md](docs/runbooks/osm-refresh.md). To use a different city, add an entry to `URLS` in [scripts/osm/download.sh](scripts/osm/download.sh).

**`pg_partman` rollover** runs daily via cron — see [docs/runbooks/pg-partman.md](docs/runbooks/pg-partman.md).

---

## Performance budgets

These are tested in CI where feasible; otherwise asserted in load tests on the target hardware (small VM or Raspberry Pi 5).

| Operation | Budget |
| --- | --- |
| `GET /tiles/{z}/{x}/{y}.mvt` (p95) | < 100 ms |
| ETA query, cached (p95) | < 5 ms |
| ETA query, uncached (p95) | < 300 ms (target 100 ms on a Pi) |
| Order list (p95) | < 50 ms |
| TSP optimize, 20 stops | < 1 s |
| `ST_Contains` service-area lookup (p95) | < 5 ms |

---

## Anti-goals

What Cartograph **does not** try to do:

- **Don't route across an entire country.** City + 50 km is V1; sharding strategies for nation-scale routing aren't worth it for a courier shop.
- **Don't try to be Onfleet.** The dispatcher UX is intentionally minimal.
- **Don't ship a native mobile app.** Drivers use the web UI on phones via Tailscale. Native apps are V3+.
- **Don't accept raw client geometry without `ST_IsValid`.**
- **Don't store geometries in mixed SRIDs.** 4326 in, transform inside queries when needed.
- **Don't compute distances with `ST_Distance(geometry, geometry)` in degrees.** Use geography or transform to UTM first.
- **Don't real-time-broadcast driver locations in V1.** Polling. WebSockets are V3.
- **Don't bypass the tile cache.** Cache invalidation is a feature; document it.
- **Don't ship the OSM extract in the repo.** Downloaded on demand.
- **Don't bake Mapbox tokens into the frontend bundle.** Env-driven and rotated.

---

## Deployment

Phase 10 deploys to either:

- **A small VM** (DigitalOcean / Hetzner / Backblaze) — Compose stack + Caddy + Tailscale.
- **Hearth (P1)** — the home-server platform if you're running one.

Operational requirements (all wired in `infra/compose/docker-compose.prod.yml`):

- HTTPS via Caddy auto-TLS; the same container serves the built SPA and proxies `/api` + `/tiles`.
- Tailscale-only API access by default — public exposure is opt-in ([docs/runbooks/deploy.md](docs/runbooks/deploy.md)).
- Nightly `pg_dump` with 14-day rotation via the `maintenance` service; off-site sync is one rclone cron line ([docs/runbooks/backup-restore.md](docs/runbooks/backup-restore.md)).
- `partman.run_maintenance()` runs daily in the same service to roll partitions.
- OSM extract refresh quarterly ([docs/runbooks/osm-refresh.md](docs/runbooks/osm-refresh.md)).

---

## Security model

- **Tenant isolation** enforced on every query (tenant ID derived from the session, never from the request body).
- **Argon2id** for password hashing.
- **Driver phone numbers** PII-flagged in structured logs (redacted by default).
- **Rate limiting** on `POST /api/drivers/{id}/location` (per driver — generous, the device is the source of truth).
- **HTTPS** mandatory in production via Caddy.
- **No driver-location sharing across tenants**, ever.
- **Stateless JWTs** (24 h TTL): logout clears the cookie but cannot revoke an already-captured token — there is no server-side denylist in V1. Rotate `SECRET_KEY` to invalidate all sessions.

---

## Definition of done

### V1 — Phases 1–10

A single courier tenant can:

1. Configure a service area (GeoJSON upload).
2. Register drivers (name, phone, vehicle type).
3. Accept orders (pickup + delivery + promised_at).
4. See ETAs computed from the OSM road network.
5. See geo-fence events fire as drivers move.
6. Run TSP optimization for a driver's order set.
7. View H3 coverage analytics.

Deployed with backups + restore drill executed. Frontend Lighthouse ≥ 85. Documentation: README, AGENT.md, runbooks.

### V2 — stretch

WebSocket driver positions · per-vehicle routing profiles · multi-driver VRP with time windows.

### V3 — full stretch (pick one or more)

Self-hosted Valhalla / OSRM benchmarked vs pgrouting · per-hex demand prediction (small ML model) · native mobile driver app · multi-tenant onboarding.

---

## Contributing

Cartograph is built in the open as a learning vehicle for PostGIS / spatial-database / routing-algorithm work. PRs welcome once V1 is complete. Until then, the repo is single-developer.

Commit messages follow **Conventional Commits**: `feat(scope): …`, `fix(scope): …`, `chore: …`, `docs: …`. Scopes match the package layout (`schema`, `service-areas`, `eta`, `geofences`, `tiles`, `tsp`, `analytics`, `web`, `infra`).

---

## References

- **PostGIS docs** — <https://postgis.net/docs/>
- **pgrouting docs** — <https://docs.pgrouting.org/latest/en/index.html>
- **H3 spec** — <https://h3geo.org/>
- **Mapbox Vector Tile spec** — <https://github.com/mapbox/vector-tile-spec>
- **MapLibre GL JS docs** — <https://maplibre.org/maplibre-gl-js/docs/>
- **Geofabrik OSM extracts** — <https://download.geofabrik.de/>

Project-internal references (in [AGENT.md](AGENT.md) §23):
`projects.md` §P12 · `tools/postgres.md` §29-31 · `tools/system-design-architecture.md` §18 · `tools/api-design.md` · `tools/networking.md` · `tools/caddy.md` · `tools/tailscale.md`.

---

## License

Cartograph is licensed under the **GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [LICENSE](LICENSE) for the full text.

The AGPL extends GPL's copyleft to network use: if you run a modified version of Cartograph as a service, you must offer the modified source to its users. This is intentional — the project is built to be improved in the open.

---

## Agent-facing documentation

This README is for humans. **[AGENT.md](AGENT.md)** is the operating brief for Claude Code (or any other coding agent): operating mode (decide-alone / ask-first / confirm-destructive), per-phase implementation detail, anti-goals as enforceable rules, and the "when in doubt" escalation list.

The original briefing document `p12-cartograph.md` is the source from which AGENT.md was derived. All of its content is mirrored in this README + AGENT.md and the briefing file can be deleted at any time without information loss.
