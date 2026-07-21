# Production API image.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev || uv sync --no-install-project --no-dev

COPY . .
RUN uv sync --no-dev

FROM python:3.12-slim-bookworm

RUN groupadd -r cartograph && useradd -r -g cartograph cartograph

WORKDIR /app
COPY --from=builder --chown=cartograph:cartograph /app /app

ENV PATH="/app/.venv/bin:$PATH"
USER cartograph
EXPOSE 8000

CMD ["uvicorn", "cartograph.main:app", "--host", "0.0.0.0", "--port", "8000"]
