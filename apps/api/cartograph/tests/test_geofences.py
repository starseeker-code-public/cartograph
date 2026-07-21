"""Geofence tests (Phase 5): enter/exit/dwell, jitter debounce, rate limit.

Geometry: delivery point at Puerta del Sol, 200 m geofence. Points inside/
outside are computed from the ~1.1 m per 0.00001° latitude rule.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.auth.models import Tenant, User
from cartograph.geofences.models import GeofenceEvent

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

DELIVERY_LNG, DELIVERY_LAT = -3.7038, 40.4168
# ~0.00001° latitude ≈ 1.11 m; all points due north of the delivery point.
AT_50M = (DELIVERY_LNG, DELIVERY_LAT + 0.00045)
AT_150M = (DELIVERY_LNG, DELIVERY_LAT + 0.00135)
AT_205M = (DELIVERY_LNG, DELIVERY_LAT + 0.00185)  # inside exit margin band
AT_400M = (DELIVERY_LNG, DELIVERY_LAT + 0.0036)
AT_2KM = (DELIVERY_LNG, DELIVERY_LAT + 0.018)


async def _setup_driver_with_order(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[str, str]:
    driver = (
        await client.post(
            "/api/drivers",
            json={"name": "Geo Driver", "phone": "+34611111111", "vehicle_type": "scooter"},
            headers=headers,
        )
    ).json()
    order = (
        await client.post(
            "/api/orders",
            json={
                "pickup": {"lng": -3.71, "lat": 40.42},
                "delivery": {"lng": DELIVERY_LNG, "lat": DELIVERY_LAT},
                "pickup_address": "A",
                "delivery_address": "B",
                "promised_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            headers=headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/orders/{order['id']}",
        json={"driver_id": driver["id"], "state": "assigned"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return driver["id"], order["id"]


async def _ping(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    driver_id: str,
    point: tuple[float, float],
    accuracy_m: float = 5.0,
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/drivers/{driver_id}/location",
        json={"lng": point[0], "lat": point[1], "accuracy_m": accuracy_m},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _kinds(result: dict[str, Any]) -> list[str]:
    return [e["kind"] for e in result["events"]]


async def test_enter_exit_cycle(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    driver_id, order_id = await _setup_driver_with_order(client, auth_headers)

    # Far outside → no events.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_2KM)) == []
    # Still outside (400 m > 200 m fence).
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_400M)) == []
    # Crossing in.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_150M)) == ["entered"]
    # Moving around inside → no duplicate entered.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == []
    # Out again.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_400M)) == ["exited"]
    # Re-entry emits a fresh entered.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_150M)) == ["entered"]

    events = (
        await client.get(
            "/api/geofence-events", params={"order_id": order_id}, headers=auth_headers
        )
    ).json()
    assert [e["kind"] for e in events] == ["entered", "exited", "entered"][::-1]


async def test_jitter_at_boundary_does_not_pingpong(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id, _ = await _setup_driver_with_order(client, auth_headers)

    assert _kinds(await _ping(client, auth_headers, driver_id, AT_150M)) == ["entered"]
    # 205 m is outside the fence but within the 20 m hysteresis margin → no exit.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_205M)) == []
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_150M)) == []


async def test_poor_accuracy_fix_skips_geofences(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id, _ = await _setup_driver_with_order(client, auth_headers)

    result = await _ping(client, auth_headers, driver_id, AT_50M, accuracy_m=500.0)
    assert result["events"] == []
    # Position still updated.
    assert result["driver"]["current_location"]["lat"] == pytest.approx(AT_50M[1])

    # A good fix afterwards emits the entered normally.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == ["entered"]


async def test_dwell_threshold_and_reset(
    client: httpx.AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    driver_id, order_id = await _setup_driver_with_order(client, auth_headers)

    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == ["entered"]
    # Still inside, timer not elapsed → nothing.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == []

    # Backdate the entered event beyond the dwell threshold.
    await db_session.execute(
        update(GeofenceEvent)
        .where(GeofenceEvent.order_id == UUID(order_id), GeofenceEvent.kind == "entered")
        .values(occurred_at=datetime.now(UTC) - timedelta(seconds=700))
    )
    await db_session.commit()

    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == ["dwell_threshold"]
    # Only once per entry.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == []

    # Exit + re-enter resets the timer: no immediate dwell.
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_400M)) == ["exited"]
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == ["entered"]
    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == []


async def test_no_events_for_unassigned_order_states(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id, order_id = await _setup_driver_with_order(client, auth_headers)
    # Deliver the order; its geofence goes dormant.
    await client.patch(f"/api/orders/{order_id}", json={"state": "picked_up"}, headers=auth_headers)
    await client.patch(f"/api/orders/{order_id}", json={"state": "delivered"}, headers=auth_headers)

    assert _kinds(await _ping(client, auth_headers, driver_id, AT_50M)) == []


async def test_location_rate_limit(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cartograph.settings import settings

    monkeypatch.setattr(settings, "location_rate_limit_per_minute", 3)
    driver_id, _ = await _setup_driver_with_order(client, auth_headers)

    for _ in range(3):
        resp = await client.post(
            f"/api/drivers/{driver_id}/location",
            json={"lng": AT_2KM[0], "lat": AT_2KM[1]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
    resp = await client.post(
        f"/api/drivers/{driver_id}/location",
        json={"lng": AT_2KM[0], "lat": AT_2KM[1]},
        headers=auth_headers,
    )
    assert resp.status_code == 429


async def test_driver_crud_and_isolation(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    from uuid import uuid4

    from cartograph.auth.security import create_access_token

    created = (
        await client.post(
            "/api/drivers",
            json={"name": "Ana", "phone": "+34622222222", "vehicle_type": "van"},
            headers=auth_headers,
        )
    ).json()
    assert created["state"] == "offline"
    assert created["current_location"] is None

    patched = await client.patch(
        f"/api/drivers/{created['id']}", json={"state": "idle"}, headers=auth_headers
    )
    assert patched.json()["state"] == "idle"

    other_tenant = Tenant(slug=f"gd-{uuid4().hex[:10]}", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email=f"gd-{uuid4().hex[:10]}@example.com",
        password_hash="x",
    )
    db_session.add(other_user)
    await db_session.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(other_user.id, other_tenant.id)}"
    }
    assert (
        await client.get(f"/api/drivers/{created['id']}", headers=other_headers)
    ).status_code == 404
    # Foreign tenant cannot push locations either.
    assert (
        await client.post(
            f"/api/drivers/{created['id']}/location",
            json={"lng": 0, "lat": 0},
            headers=other_headers,
        )
    ).status_code == 404


async def test_geofence_events_partition_pruning(db_session: AsyncSession) -> None:
    """Sanity: events land in a partman partition, not only the default."""
    result = await db_session.execute(
        text("SELECT count(*) FROM pg_tables " "WHERE tablename ~ '^geofence_events_p\\d{8}$'")
    )
    assert result.scalar_one() >= 1
