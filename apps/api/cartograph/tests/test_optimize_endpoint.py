"""POST /api/drivers/{id}/optimize integration tests (Phase 7)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from cartograph.tests.conftest import grid_node

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)


async def _driver_at(
    client: httpx.AsyncClient, headers: dict[str, str], point: tuple[float, float]
) -> str:
    driver = (
        await client.post(
            "/api/drivers",
            json={"name": "Opt Driver", "phone": "+34644444444", "vehicle_type": "car"},
            headers=headers,
        )
    ).json()
    resp = await client.post(
        f"/api/drivers/{driver['id']}/location",
        json={"lng": point[0], "lat": point[1]},
        headers=headers,
    )
    assert resp.status_code == 200
    return str(driver["id"])


async def _assigned_order(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    driver_id: str,
    pickup: tuple[float, float],
    delivery: tuple[float, float],
) -> dict[str, Any]:
    order = (
        await client.post(
            "/api/orders",
            json={
                "pickup": {"lng": pickup[0], "lat": pickup[1]},
                "delivery": {"lng": delivery[0], "lat": delivery[1]},
                "pickup_address": "P",
                "delivery_address": "D",
                "promised_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            },
            headers=headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/orders/{order['id']}",
        json={"driver_id": driver_id, "state": "assigned"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def test_optimize_three_orders(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id = await _driver_at(client, auth_headers, grid_node(0, 0))
    orders = [
        await _assigned_order(client, auth_headers, driver_id, grid_node(1, 0), grid_node(3, 0)),
        await _assigned_order(client, auth_headers, driver_id, grid_node(0, 2), grid_node(2, 2)),
        await _assigned_order(client, auth_headers, driver_id, grid_node(3, 3), grid_node(1, 3)),
    ]

    resp = await client.post(f"/api/drivers/{driver_id}/optimize", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total_duration_s"] > 0
    assert body["total_distance_m"] > 0
    assert len(body["stops"]) == 6  # 3 pickups + 3 deliveries

    # Every pickup precedes its delivery.
    for order in orders:
        kinds = [s["kind"] for s in body["stops"] if s["order_id"] == order["id"]]
        assert kinds == ["pickup", "delivery"]

    # Cumulative offsets are monotonic.
    offsets = [s["arrival_offset_s"] for s in body["stops"]]
    assert offsets == sorted(offsets)

    # The persisted route is a real row.
    assert body["route_id"]


async def test_optimize_picked_up_order_has_delivery_stop_only(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id = await _driver_at(client, auth_headers, grid_node(0, 0))
    order = await _assigned_order(client, auth_headers, driver_id, grid_node(1, 1), grid_node(3, 3))
    await client.patch(
        f"/api/orders/{order['id']}", json={"state": "picked_up"}, headers=auth_headers
    )

    resp = await client.post(f"/api/drivers/{driver_id}/optimize", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    stops = resp.json()["stops"]
    assert len(stops) == 1
    assert stops[0]["kind"] == "delivery"


async def test_optimize_no_active_orders(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver_id = await _driver_at(client, auth_headers, grid_node(0, 0))
    resp = await client.post(f"/api/drivers/{driver_id}/optimize", headers=auth_headers)
    assert resp.status_code == 422


async def test_optimize_driver_without_location(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    driver = (
        await client.post(
            "/api/drivers",
            json={"name": "No Loc", "phone": "+34655555555", "vehicle_type": "bike"},
            headers=auth_headers,
        )
    ).json()
    await _assigned_order(client, auth_headers, driver["id"], grid_node(1, 1), grid_node(2, 2))
    resp = await client.post(f"/api/drivers/{driver['id']}/optimize", headers=auth_headers)
    assert resp.status_code == 422


async def test_optimize_ten_orders_under_a_second(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """20 stops (10 orders) — DoD perf budget on the optimization call."""
    driver_id = await _driver_at(client, auth_headers, grid_node(0, 0))
    for i in range(10):
        await _assigned_order(
            client,
            auth_headers,
            driver_id,
            grid_node(i % 4, (i * 2) % 4),
            grid_node((i + 1) % 4, (i * 3) % 4),
        )

    started = time.perf_counter()
    resp = await client.post(f"/api/drivers/{driver_id}/optimize", headers=auth_headers)
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["stops"]) == 20
    assert elapsed < 1.0, f"optimize took {elapsed:.2f}s"
