"""Service-area management tests (Phase 3).

Covers the DoD: lossless round-trip, invalid GeoJSON rejection, containment,
and the geometry matrix (simple polygon, multipolygon, holes, invalid).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from cartograph.auth.models import Tenant, User
from cartograph.auth.security import create_access_token

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

# A ~2 km square in central Madrid.
SIMPLE_POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-3.71, 40.41], [-3.69, 40.41], [-3.69, 40.43], [-3.71, 40.43], [-3.71, 40.41]]
    ],
}

MULTIPOLYGON: dict[str, Any] = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[-3.71, 40.41], [-3.69, 40.41], [-3.69, 40.43], [-3.71, 40.43], [-3.71, 40.41]]],
        [[[-3.68, 40.44], [-3.66, 40.44], [-3.66, 40.46], [-3.68, 40.46], [-3.68, 40.44]]],
    ],
}

POLYGON_WITH_HOLE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-3.72, 40.40], [-3.66, 40.40], [-3.66, 40.46], [-3.72, 40.46], [-3.72, 40.40]],
        [[-3.70, 40.42], [-3.68, 40.42], [-3.68, 40.44], [-3.70, 40.44], [-3.70, 40.42]],
    ],
}

# Bowtie: self-intersecting, must be rejected.
INVALID_POLYGON: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-3.71, 40.41], [-3.69, 40.43], [-3.69, 40.41], [-3.71, 40.43], [-3.71, 40.41]]
    ],
}


async def _create(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    geometry: dict[str, Any],
    name: str = "Area",
) -> httpx.Response:
    return await client.post(
        "/api/service-areas",
        json={"name": name, "geometry": geometry, "rules": {"max_order_value": 50}},
        headers=headers,
    )


async def test_create_and_roundtrip_simple_polygon(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await _create(client, auth_headers, SIMPLE_POLYGON, name="Centro")
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Centro"
    assert created["geometry"]["type"] == "MultiPolygon"

    # Round-trip: fetch and compare coordinates losslessly.
    fetched = (await client.get(f"/api/service-areas/{created['id']}", headers=auth_headers)).json()
    assert fetched["geometry"] == created["geometry"]
    assert fetched["geometry"]["coordinates"][0] == SIMPLE_POLYGON["coordinates"]
    assert fetched["rules"] == {"max_order_value": 50}


async def test_create_multipolygon(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await _create(client, auth_headers, MULTIPOLYGON)
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["geometry"]["coordinates"]) == 2


async def test_create_polygon_with_hole(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await _create(client, auth_headers, POLYGON_WITH_HOLE)
    assert resp.status_code == 201, resp.text
    # Hole preserved: one polygon with two rings.
    assert len(resp.json()["geometry"]["coordinates"][0]) == 2


async def test_create_feature_wrapper(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    feature = {"type": "Feature", "properties": {}, "geometry": SIMPLE_POLYGON}
    resp = await _create(client, auth_headers, feature)
    assert resp.status_code == 201, resp.text


async def test_invalid_polygon_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await _create(client, auth_headers, INVALID_POLYGON)
    assert resp.status_code == 422
    assert "Self-intersection" in resp.json()["detail"]


async def test_non_polygon_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    point = {"type": "Point", "coordinates": [-3.7, 40.42]}
    resp = await _create(client, auth_headers, point)
    assert resp.status_code == 422


async def test_out_of_range_coordinates_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Looks like Web Mercator meters, not lng/lat.
    mercator = {
        "type": "Polygon",
        "coordinates": [
            [[-413000, 4926000], [-411000, 4926000], [-411000, 4928000], [-413000, 4926000]]
        ],
    }
    resp = await _create(client, auth_headers, mercator)
    assert resp.status_code == 422
    assert "EPSG:4326" in resp.json()["detail"]


async def test_contains(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = (await _create(client, auth_headers, SIMPLE_POLYGON)).json()

    inside = await client.get(
        "/api/service-areas/contains",
        params={"lng": -3.703, "lat": 40.417},
        headers=auth_headers,
    )
    assert inside.status_code == 200
    assert created["id"] in inside.json()["service_area_ids"]

    outside = await client.get(
        "/api/service-areas/contains",
        params={"lng": -3.60, "lat": 40.50},
        headers=auth_headers,
    )
    assert created["id"] not in outside.json()["service_area_ids"]


async def test_hole_excluded_from_containment(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await _create(client, auth_headers, POLYGON_WITH_HOLE)).json()
    # Point inside the hole → not contained.
    in_hole = await client.get(
        "/api/service-areas/contains",
        params={"lng": -3.69, "lat": 40.43},
        headers=auth_headers,
    )
    assert created["id"] not in in_hole.json()["service_area_ids"]


async def test_patch_name_rules_geometry(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await _create(client, auth_headers, SIMPLE_POLYGON)).json()
    resp = await client.patch(
        f"/api/service-areas/{created['id']}",
        json={"name": "Renamed", "rules": {"hours": "9-18"}, "geometry": MULTIPOLYGON},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["rules"] == {"hours": "9-18"}
    assert len(body["geometry"]["coordinates"]) == 2


async def test_patch_invalid_geometry_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (await _create(client, auth_headers, SIMPLE_POLYGON)).json()
    resp = await client.patch(
        f"/api/service-areas/{created['id']}",
        json={"geometry": INVALID_POLYGON},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_delete(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = (await _create(client, auth_headers, SIMPLE_POLYGON)).json()
    resp = await client.delete(f"/api/service-areas/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    gone = await client.get(f"/api/service-areas/{created['id']}", headers=auth_headers)
    assert gone.status_code == 404


async def test_tenant_isolation(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: Any,
) -> None:
    """Another tenant must not see or touch this tenant's areas."""
    from uuid import uuid4

    created = (await _create(client, auth_headers, SIMPLE_POLYGON)).json()

    other_tenant = Tenant(slug=f"iso-{uuid4().hex[:10]}", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email=f"iso-{uuid4().hex[:10]}@example.com",
        password_hash="x",
    )
    db_session.add(other_user)
    await db_session.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(other_user.id, other_tenant.id)}"
    }

    assert (
        await client.get(f"/api/service-areas/{created['id']}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.delete(f"/api/service-areas/{created['id']}", headers=other_headers)
    ).status_code == 404
    listing = (await client.get("/api/service-areas", headers=other_headers)).json()
    assert created["id"] not in [a["id"] for a in listing]


async def test_unauthenticated_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/service-areas")).status_code == 401


async def test_adjacent_polygons_are_unioned(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Two valid districts sharing an edge are legitimate input; they must be
    unioned, not rejected as an OGC-invalid MultiPolygon."""
    adjacent = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-3.71, 40.41],
                            [-3.70, 40.41],
                            [-3.70, 40.43],
                            [-3.71, 40.43],
                            [-3.71, 40.41],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-3.70, 40.41],
                            [-3.69, 40.41],
                            [-3.69, 40.43],
                            [-3.70, 40.43],
                            [-3.70, 40.41],
                        ]
                    ],
                },
            },
        ],
    }
    resp = await _create(client, auth_headers, adjacent)
    assert resp.status_code == 201, resp.text
    # Union merges the shared edge into one polygon.
    assert len(resp.json()["geometry"]["coordinates"]) == 1
