"""Integration tests for the spatial schema (Phase 2).

Requires PostGIS — run ``just up`` first.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.auth.models import Tenant
from cartograph.drivers.models import Driver
from cartograph.orders.models import Order
from cartograph.service_areas.models import ServiceArea

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)


async def test_postgis_and_pgrouting_loaded(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT PostGIS_Full_Version()"))
    version = result.scalar_one()
    assert "POSTGIS=" in version

    result = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'pgrouting'")
    )
    assert result.scalar_one_or_none() == "pgrouting"


async def test_tenant_insert(db_session: AsyncSession) -> None:
    tenant = Tenant(id=uuid4(), slug=f"acme-{uuid4().hex[:8]}", name="Acme Couriers")
    db_session.add(tenant)
    await db_session.flush()

    fetched = (await db_session.execute(select(Tenant).where(Tenant.id == tenant.id))).scalar_one()
    assert fetched.name == "Acme Couriers"


async def test_service_area_with_multipolygon(db_session: AsyncSession) -> None:
    tenant = Tenant(id=uuid4(), slug=f"sa-{uuid4().hex[:8]}", name="Test")
    db_session.add(tenant)
    await db_session.flush()

    # A small MultiPolygon around the Puerta del Sol, Madrid.
    multipoly_wkt = (
        "MULTIPOLYGON(((-3.71 40.41, -3.69 40.41, -3.69 40.43, " "-3.71 40.43, -3.71 40.41)))"
    )
    area = ServiceArea(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Centro",
        geom=f"SRID=4326;{multipoly_wkt}",
        rules={"max_order_value": 50},
    )
    db_session.add(area)
    await db_session.flush()

    # GiST index is consulted on this containment query.
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM service_areas WHERE "
            "ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
        ),
        {"lng": -3.703, "lat": 40.417},  # Puerta del Sol
    )
    assert result.scalar_one() >= 1


async def test_driver_geography_point(db_session: AsyncSession) -> None:
    tenant = Tenant(id=uuid4(), slug=f"drv-{uuid4().hex[:8]}", name="Test")
    db_session.add(tenant)
    await db_session.flush()

    driver = Driver(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Lucia",
        phone="+34123456789",
        vehicle_type="bike",
        current_location="SRID=4326;POINT(-3.7038 40.4168)",
        current_location_updated_at=datetime.now(UTC),
        state="idle",
    )
    db_session.add(driver)
    await db_session.flush()

    # Geography distance is in meters.
    result = await db_session.execute(
        text(
            "SELECT ST_Distance(current_location, "
            "ST_SetSRID(ST_MakePoint(-3.7000, 40.4200), 4326)::geography) "
            "FROM drivers WHERE id = :id"
        ),
        {"id": driver.id},
    )
    distance_m = result.scalar_one()
    assert 0 < distance_m < 5000  # well under 5 km


async def test_order_insert(db_session: AsyncSession) -> None:
    tenant = Tenant(id=uuid4(), slug=f"ord-{uuid4().hex[:8]}", name="Test")
    db_session.add(tenant)
    await db_session.flush()

    order = Order(
        id=uuid4(),
        tenant_id=tenant.id,
        pickup="SRID=4326;POINT(-3.7038 40.4168)",
        delivery="SRID=4326;POINT(-3.6900 40.4250)",
        pickup_address="Plaza Mayor, Madrid",
        delivery_address="Retiro Park, Madrid",
        promised_at=datetime.now(UTC) + timedelta(hours=1),
        state="created",
    )
    db_session.add(order)
    await db_session.flush()

    fetched = (await db_session.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fetched.state == "created"
    assert fetched.geofence_meters == 200


async def test_geofence_event_partitioned(db_session: AsyncSession) -> None:
    """Verify geofence_events is a partitioned table."""
    result = await db_session.execute(
        text(
            # relkind is a "char"; cast so asyncpg returns str, not bytes.
            "SELECT relkind::text FROM pg_class WHERE relname = 'geofence_events'"
        )
    )
    # 'p' = partitioned table
    assert result.scalar_one() == "p"


async def test_gist_indexes_exist(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexdef ILIKE '%USING gist%' "
            "ORDER BY indexname"
        )
    )
    names = {row[0] for row in result.all()}
    assert {
        "ix_service_areas_geom",
        "ix_drivers_loc",
        "ix_orders_pickup",
        "ix_orders_delivery",
        "ix_routes_geom",
        "ix_geofence_events_loc",
    }.issubset(names)
