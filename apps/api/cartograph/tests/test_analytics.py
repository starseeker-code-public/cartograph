"""H3 coverage analytics tests (Phase 8)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import h3
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

# Two clusters ~2.5 km apart: different res-8 cells, same res-7 parent may
# differ — assertions only rely on exact h3 computations, not adjacency.
CLUSTER_A = (-3.7038, 40.4168)
CLUSTER_B = (-3.6800, 40.4300)


async def _order_at(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    pickup: tuple[float, float],
) -> dict[str, Any]:
    resp = await client.post(
        "/api/orders",
        json={
            "pickup": {"lng": pickup[0], "lat": pickup[1]},
            "delivery": {"lng": pickup[0] + 0.01, "lat": pickup[1] + 0.01},
            "pickup_address": "P",
            "delivery_address": "D",
            "promised_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def test_h3_columns_populated_on_create(
    client: httpx.AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    order = await _order_at(client, auth_headers, CLUSTER_A)
    row = (
        await db_session.execute(
            text("SELECT pickup_h3_8, delivery_h3_8 FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )
    ).one()
    assert row.pickup_h3_8 == h3.latlng_to_cell(CLUSTER_A[1], CLUSTER_A[0], 8)
    assert row.delivery_h3_8 == h3.latlng_to_cell(CLUSTER_A[1] + 0.01, CLUSTER_A[0] + 0.01, 8)


async def test_coverage_counts_per_cell(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    for _ in range(3):
        await _order_at(client, auth_headers, CLUSTER_A)
    await _order_at(client, auth_headers, CLUSTER_B)

    resp = await client.get(
        "/api/analytics/coverage", params={"resolution": 8}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolution"] == 8
    assert body["kind"] == "pickup"

    counts = {c["hex"]: c["count"] for c in body["cells"]}
    cell_a = h3.latlng_to_cell(CLUSTER_A[1], CLUSTER_A[0], 8)
    cell_b = h3.latlng_to_cell(CLUSTER_B[1], CLUSTER_B[0], 8)
    assert counts[cell_a] >= 3
    assert counts[cell_b] >= 1
    # Cells sorted by density, densest first.
    assert body["cells"][0]["count"] == max(counts.values())


async def test_coverage_resolutions_7_and_9(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _order_at(client, auth_headers, CLUSTER_A)

    for resolution in (7, 9):
        resp = await client.get(
            "/api/analytics/coverage",
            params={"resolution": resolution},
            headers=auth_headers,
        )
        expected = h3.latlng_to_cell(CLUSTER_A[1], CLUSTER_A[0], resolution)
        hexes = {c["hex"] for c in resp.json()["cells"]}
        assert expected in hexes
        assert all(h3.get_resolution(hx) == resolution for hx in hexes)

    # Out-of-range resolution rejected.
    bad = await client.get(
        "/api/analytics/coverage", params={"resolution": 6}, headers=auth_headers
    )
    assert bad.status_code == 422


async def test_coverage_time_range_filter(
    client: httpx.AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    old = await _order_at(client, auth_headers, CLUSTER_A)
    await db_session.execute(
        text("UPDATE orders SET created_at = now() - interval '30 days' WHERE id = :id"),
        {"id": old["id"]},
    )
    await db_session.commit()
    await _order_at(client, auth_headers, CLUSTER_B)

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    resp = await client.get(
        "/api/analytics/coverage",
        params={"from": since, "resolution": 8},
        headers=auth_headers,
    )
    hexes = {c["hex"] for c in resp.json()["cells"]}
    assert h3.latlng_to_cell(CLUSTER_A[1], CLUSTER_A[0], 8) not in hexes
    assert h3.latlng_to_cell(CLUSTER_B[1], CLUSTER_B[0], 8) in hexes


async def test_coverage_delivery_kind(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _order_at(client, auth_headers, CLUSTER_A)
    resp = await client.get(
        "/api/analytics/coverage",
        params={"kind": "delivery", "resolution": 8},
        headers=auth_headers,
    )
    delivery_cell = h3.latlng_to_cell(CLUSTER_A[1] + 0.01, CLUSTER_A[0] + 0.01, 8)
    assert delivery_cell in {c["hex"] for c in resp.json()["cells"]}


async def test_coverage_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/analytics/coverage")).status_code == 401
