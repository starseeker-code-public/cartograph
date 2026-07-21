# Deploy runbook

Target: Hearth (home server) or any small VM with Docker + Compose v2.

## First deploy

```bash
git clone <repo> cartograph && cd cartograph
cp .env.prod.example .env          # fill in DOMAIN, POSTGRES_PASSWORD, SECRET_KEY
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env up -d --build
```

What comes up:

| Service | Role |
|---|---|
| `postgres` | PostGIS 3.4 + pgrouting 3.8 + pg_partman (custom image) |
| `redis` | ETA + tile cache (LRU-capped at 256 MB) |
| `migrate` | one-shot `alembic upgrade head`, gates the API |
| `api` | FastAPI/uvicorn on the internal network |
| `caddy` | TLS termination, SPA static files, `/api` + `/tiles` proxy |
| `maintenance` | nightly `pg_dump` + daily `partman.run_maintenance()` |

Then seed the first dispatcher account:

```bash
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env \
  exec api python -m cartograph.seed dispatcher@yourco.com 'a-strong-password'
```

And load the road network (once; see `osm-refresh.md` for updates):

```bash
just osm-download madrid            # edit scripts/osm/download.sh for your city
PGHOST=localhost just osm-load madrid
```

`osm2pgrouting` needs to reach Postgres — either run it on the host with the
5432 port temporarily published, or install osm2pgrouting in a one-off
container on the compose network.

## Tailscale-only pilots

Default posture: don't expose 80/443 publicly.

1. Install Tailscale on the host (`tailscale up`).
2. Set `DOMAIN` in `.env` to the machine's MagicDNS name
   (e.g. `hearth.tail1234.ts.net`) — Caddy gets a certificate via the
   Tailscale integration, or serve HTTP-only inside the tailnet.
3. Remove the `ports` mapping on `caddy` and bind to the tailnet IP instead:
   `"100.x.y.z:443:443"`.
4. Drivers join the tailnet on their phones and open `https://<magicdns>/`.

## Upgrades

```bash
git pull
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env up -d --build
```

Migrations run automatically via the `migrate` service before the new API
starts. Confirm health afterwards:

```bash
curl -fsS https://$DOMAIN/api/../healthz   # or: docker compose ... exec api python -c ...
docker compose -f infra/compose/docker-compose.prod.yml ps
```

## Rollback

```bash
git checkout <previous-tag>
docker compose -f infra/compose/docker-compose.prod.yml --env-file .env up -d --build
```

Schema rollbacks (`alembic downgrade`) are manual and rarely needed; restore
from backup instead for anything destructive (see `backup-restore.md`).
