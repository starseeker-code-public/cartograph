set dotenv-load

api_dir := "apps/api"

# ── Compose ──────────────────────────────────────────────────────────────────

up:
    docker compose -f infra/compose/docker-compose.dev.yml up -d

down:
    docker compose -f infra/compose/docker-compose.dev.yml down

logs:
    docker compose -f infra/compose/docker-compose.dev.yml logs -f

psql:
    docker compose -f infra/compose/docker-compose.dev.yml exec postgres \
        psql -U cartograph -d cartograph

postgis-version:
    docker compose -f infra/compose/docker-compose.dev.yml exec postgres \
        psql -U cartograph -d cartograph -c "SELECT PostGIS_Full_Version();"

# ── API ───────────────────────────────────────────────────────────────────────

dev:
    cd {{api_dir}} && uv run uvicorn cartograph.main:app --reload --port 8000

install:
    cd {{api_dir}} && uv sync

install-dev:
    cd {{api_dir}} && uv sync --extra dev

lint:
    cd {{api_dir}} && uv run ruff check cartograph && uv run black --check cartograph

format:
    cd {{api_dir}} && uv run ruff check --fix cartograph && uv run black cartograph

typecheck:
    cd {{api_dir}} && uv run mypy cartograph

test:
    cd {{api_dir}} && uv run pytest -v

test-cov:
    cd {{api_dir}} && uv run pytest --cov=cartograph --cov-report=term-missing

# ── Migrations ────────────────────────────────────────────────────────────────

migrate:
    cd {{api_dir}} && uv run alembic upgrade head

migrate-down:
    cd {{api_dir}} && uv run alembic downgrade -1

migrate-new name:
    cd {{api_dir}} && uv run alembic revision --autogenerate -m "{{name}}"

migrate-history:
    cd {{api_dir}} && uv run alembic history

# ── OSM ───────────────────────────────────────────────────────────────────────

osm-download city="madrid":
    bash scripts/osm/download.sh {{city}}

osm-load city="madrid":
    bash scripts/osm/load.sh {{city}}

# ── Full local reset ──────────────────────────────────────────────────────────

reset: down
    docker volume rm cartograph_cartograph_pg || true
    just up
