import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cartograph.auth.router import router as auth_router
from cartograph.orders.router import router as orders_router
from cartograph.routes.router import router as routes_router
from cartograph.service_areas.router import router as service_areas_router
from cartograph.settings import settings

log = structlog.get_logger()

app = FastAPI(
    title="Cartograph",
    description="Geospatial intelligence API for last-mile delivery",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(service_areas_router, prefix=settings.api_prefix)
app.include_router(orders_router, prefix=settings.api_prefix)
app.include_router(routes_router, prefix=settings.api_prefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz() -> dict[str, str]:
    """Checks DB + Redis reachability."""
    from redis.asyncio import Redis
    from sqlalchemy import text

    from cartograph.database import engine

    errors: list[str] = []

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"db: {exc}")

    try:
        r = Redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"redis: {exc}")

    if errors:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail={"errors": errors})

    return {"status": "ok"}
