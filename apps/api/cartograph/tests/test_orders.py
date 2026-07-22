"""Order CRUD + state machine + ETA integration tests (Phase 4)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.auth.models import Tenant, User
from cartograph.drivers.models import Driver
from cartograph.tests.conftest import grid_node

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

A_LNG, A_LAT = grid_node(0, 0)
B_LNG, B_LAT = grid_node(3, 3)


def order_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pickup": {"lng": A_LNG, "lat": A_LAT},
        "delivery": {"lng": B_LNG, "lat": B_LAT},
        "pickup_address": "Calle Mayor 1, Madrid",
        "delivery_address": "Calle de Alcalá 100, Madrid",
        "promised_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _make_driver(db_session: AsyncSession, tenant: Tenant) -> Driver:
    driver = Driver(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Test Driver",
        phone="+34600000000",
        vehicle_type="bike",
        state="idle",
    )
    db_session.add(driver)
    await db_session.commit()
    return driver


async def test_create_order_computes_eta(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/orders", json=order_payload(), headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "created"
    assert body["eta_seconds"] is not None and 300 < body["eta_seconds"] < 420
    assert body["pickup"] == {"lng": A_LNG, "lat": A_LAT}
    assert body["geofence_meters"] == 200


async def test_create_order_without_road_network_fails_open(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cartograph.orders import router as orders_router_module
    from cartograph.routes.engine import RoadNetworkUnavailable

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RoadNetworkUnavailable("no network")

    monkeypatch.setattr(orders_router_module, "shortest_path_cached", boom)
    resp = await client.post("/api/orders", json=order_payload(), headers=auth_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["eta_seconds"] is None


async def test_order_eta_endpoint(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    resp = await client.get(f"/api/orders/{created['id']}/eta", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eta_seconds"] > 0
    assert body["geometry"]["coordinates"]


async def test_list_orders_filter_by_state(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()

    listing = await client.get("/api/orders", params={"state": "created"}, headers=auth_headers)
    assert created["id"] in [o["id"] for o in listing.json()]

    cancelled = await client.get("/api/orders", params={"state": "cancelled"}, headers=auth_headers)
    assert created["id"] not in [o["id"] for o in cancelled.json()]


async def test_assign_driver_and_lifecycle(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    tenant_user: tuple[Tenant, User, str],
    db_session: AsyncSession,
) -> None:
    tenant, _, _ = tenant_user
    driver = await _make_driver(db_session, tenant)
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()

    assigned = await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": str(driver.id), "state": "assigned"},
        headers=auth_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["state"] == "assigned"
    assert assigned.json()["driver_id"] == str(driver.id)

    picked = await client.patch(
        f"/api/orders/{created['id']}", json={"state": "picked_up"}, headers=auth_headers
    )
    assert picked.status_code == 200
    delivered = await client.patch(
        f"/api/orders/{created['id']}", json={"state": "delivered"}, headers=auth_headers
    )
    assert delivered.status_code == 200


async def test_illegal_transition_rejected(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    resp = await client.patch(
        f"/api/orders/{created['id']}", json={"state": "delivered"}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_assigned_requires_driver(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    resp = await client.patch(
        f"/api/orders/{created['id']}", json={"state": "assigned"}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_foreign_driver_rejected(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    other_tenant = Tenant(slug=f"od-{uuid4().hex[:10]}", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    foreign_driver = await _make_driver(db_session, other_tenant)

    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    resp = await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": str(foreign_driver.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_order_tenant_isolation(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    from cartograph.auth.security import create_access_token

    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()

    other_tenant = Tenant(slug=f"oi-{uuid4().hex[:10]}", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email=f"oi-{uuid4().hex[:10]}@example.com",
        password_hash="x",
    )
    db_session.add(other_user)
    await db_session.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(other_user.id, other_tenant.id)}"
    }

    assert (
        await client.get(f"/api/orders/{created['id']}", headers=other_headers)
    ).status_code == 404


async def test_unassign_driver_with_null(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    tenant_user: tuple[Tenant, User, str],
    db_session: AsyncSession,
) -> None:
    """PATCH driver_id=null unassigns and reverts assigned → created."""
    tenant, _, _ = tenant_user
    driver = await _make_driver(db_session, tenant)
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()

    assigned = await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": str(driver.id), "state": "assigned"},
        headers=auth_headers,
    )
    assert assigned.json()["state"] == "assigned"

    unassigned = await client.patch(
        f"/api/orders/{created['id']}", json={"driver_id": None}, headers=auth_headers
    )
    assert unassigned.status_code == 200, unassigned.text
    body = unassigned.json()
    assert body["driver_id"] is None
    assert body["state"] == "created"

    # Absent driver_id still means "no change".
    noop = await client.patch(f"/api/orders/{created['id']}", json={}, headers=auth_headers)
    assert noop.json()["driver_id"] is None


async def test_unassign_rejected_after_pickup(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    tenant_user: tuple[Tenant, User, str],
    db_session: AsyncSession,
) -> None:
    """Mid-delivery unassignment would orphan a picked-up parcel."""
    tenant, _, _ = tenant_user
    driver = await _make_driver(db_session, tenant)
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": str(driver.id), "state": "assigned"},
        headers=auth_headers,
    )
    await client.patch(
        f"/api/orders/{created['id']}", json={"state": "picked_up"}, headers=auth_headers
    )

    resp = await client.patch(
        f"/api/orders/{created['id']}", json={"driver_id": None}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_unassign_plus_state_combo_cannot_orphan_order(
    road_grid: None,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    tenant_user: tuple[Tenant, User, str],
    db_session: AsyncSession,
) -> None:
    """One PATCH combining driver_id=null with a state advance must not
    produce an in-flight order without a driver."""
    tenant, _, _ = tenant_user
    driver = await _make_driver(db_session, tenant)
    created = (await client.post("/api/orders", json=order_payload(), headers=auth_headers)).json()
    await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": str(driver.id), "state": "assigned"},
        headers=auth_headers,
    )

    combo = await client.patch(
        f"/api/orders/{created['id']}",
        json={"driver_id": None, "state": "picked_up"},
        headers=auth_headers,
    )
    assert combo.status_code == 422

    # Order untouched by the rejected request.
    current = (await client.get(f"/api/orders/{created['id']}", headers=auth_headers)).json()
    assert current["state"] == "assigned"
    assert current["driver_id"] == str(driver.id)
