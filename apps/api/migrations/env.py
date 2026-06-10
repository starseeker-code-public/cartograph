import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from cartograph.database import Base
from cartograph.settings import settings

# Import every model module so Base.metadata is fully populated.
from cartograph.auth import models as _auth_models  # noqa: F401
from cartograph.service_areas import models as _service_area_models  # noqa: F401
from cartograph.drivers import models as _driver_models  # noqa: F401
from cartograph.orders import models as _order_models  # noqa: F401
from cartograph.routes import models as _route_models  # noqa: F401
from cartograph.geofences import models as _geofence_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(object_, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Skip PostGIS / pgrouting / system tables when autogenerating.
    if type_ == "table" and name in {
        "spatial_ref_sys",
        "geography_columns",
        "geometry_columns",
        "raster_columns",
        "raster_overviews",
    }:
        return False
    return True


def run_migrations_offline() -> None:
    url = settings.database_url.replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
