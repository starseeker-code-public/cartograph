"""ETA / routing tests (Phase 4), run against the synthetic road grid."""

from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.routes.engine import RouteNotFound, shortest_path
from cartograph.tests.conftest import ISLAND_LAT, ISLAND_LNG, grid_node

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

# Opposite corners of the grid.
A_LNG, A_LAT = grid_node(0, 0)
B_LNG, B_LAT = grid_node(3, 3)


async def test_shortest_path_corner_to_corner(road_grid: None, db_session: AsyncSession) -> None:
    route = await shortest_path(db_session, A_LNG, A_LAT, B_LNG, B_LAT)

    # 3 horizontal (~424 m each) + 3 vertical (~553 m each) hops ≈ 2930 m.
    assert 2700 < route.distance_m < 3200
    # At 8.33 m/s that's ~352 s.
    assert 300 < route.duration_s < 420
    assert route.geometry["type"] in ("LineString", "MultiLineString")
    assert route.geometry["coordinates"]


async def test_shortest_path_same_point(road_grid: None, db_session: AsyncSession) -> None:
    route = await shortest_path(db_session, A_LNG, A_LAT, A_LNG + 0.0001, A_LAT)
    assert route.duration_s == 0.0
    assert route.distance_m == 0.0


async def test_route_not_found_to_island(road_grid: None, db_session: AsyncSession) -> None:
    with pytest.raises(RouteNotFound):
        await shortest_path(db_session, A_LNG, A_LAT, ISLAND_LNG, ISLAND_LAT)


async def test_eta_endpoint_and_cache(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    params: dict[str, float | str] = {
        "from_lng": A_LNG,
        "from_lat": A_LAT,
        "to_lng": B_LNG,
        "to_lat": B_LAT,
        "vehicle": "bike",
    }
    first = await client.get("/api/eta", params=params, headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["eta_seconds"] > 0
    assert body["distance_m"] > 0
    assert body["cached"] is False

    second = await client.get("/api/eta", params=params, headers=auth_headers)
    assert second.status_code == 200
    body2 = second.json()
    assert body2["cached"] is True
    assert body2["eta_seconds"] == body["eta_seconds"]
    assert body2["geometry"] == body["geometry"]


async def test_eta_endpoint_route_not_found(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/eta",
        params={"from_lng": A_LNG, "from_lat": A_LAT, "to_lng": ISLAND_LNG, "to_lat": ISLAND_LAT},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_eta_endpoint_requires_auth(road_grid: None, client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/api/eta",
        params={"from_lng": A_LNG, "from_lat": A_LAT, "to_lng": B_LNG, "to_lat": B_LAT},
    )
    assert resp.status_code == 401


async def test_eta_endpoint_rejects_bad_vehicle(
    road_grid: None, client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/eta",
        params={
            "from_lng": A_LNG,
            "from_lat": A_LAT,
            "to_lng": B_LNG,
            "to_lat": B_LAT,
            "vehicle": "helicopter",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
