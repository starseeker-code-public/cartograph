"""Vector-tile tests (Phase 6): layers, auth, caching, invalidation."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import mapbox_vector_tile
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1", reason="DB tests disabled via SKIP_DB_TESTS"
)

CENTER_LNG, CENTER_LAT = -3.7038, 40.4168

SERVICE_AREA_GEOM: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-3.72, 40.40], [-3.68, 40.40], [-3.68, 40.44], [-3.72, 40.44], [-3.72, 40.40]]
    ],
}


def tile_xyz(lng: float, lat: float, z: int) -> tuple[int, int]:
    """Slippy-map tile coordinates containing a lng/lat."""
    n = 1 << z
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


async def _setup_map_data(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/service-areas",
        json={"name": "Centro", "geometry": SERVICE_AREA_GEOM},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    driver = (
        await client.post(
            "/api/drivers",
            json={"name": "Tile Driver", "phone": "+34633333333", "vehicle_type": "bike"},
            headers=headers,
        )
    ).json()
    await client.post(
        f"/api/drivers/{driver['id']}/location",
        json={"lng": CENTER_LNG, "lat": CENTER_LAT},
        headers=headers,
    )

    order = (
        await client.post(
            "/api/orders",
            json={
                "pickup": {"lng": CENTER_LNG, "lat": CENTER_LAT},
                "delivery": {"lng": CENTER_LNG + 0.005, "lat": CENTER_LAT + 0.005},
                "pickup_address": "A",
                "delivery_address": "B",
                "promised_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            headers=headers,
        )
    ).json()
    await client.patch(
        f"/api/orders/{order['id']}",
        json={"driver_id": driver["id"], "state": "assigned"},
        headers=headers,
    )


async def test_tile_contains_all_layers(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _setup_map_data(client, auth_headers)
    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 13)

    resp = await client.get(f"/tiles/13/{x}/{y}.mvt", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert resp.headers["x-tile-cache"] == "MISS"

    decoded = mapbox_vector_tile.decode(resp.content)
    assert "service_areas" in decoded
    assert "drivers" in decoded
    assert "orders" in decoded
    assert "geofences" in decoded

    # Orders layer carries pickup + delivery roles.
    roles = {f["properties"]["role"] for f in decoded["orders"]["features"]}
    assert roles == {"pickup", "delivery"}


async def test_tile_cache_hit_and_stats(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _setup_map_data(client, auth_headers)
    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 14)

    first = await client.get(f"/tiles/14/{x}/{y}.mvt", headers=auth_headers)
    assert first.headers["x-tile-cache"] == "MISS"
    second = await client.get(f"/tiles/14/{x}/{y}.mvt", headers=auth_headers)
    assert second.headers["x-tile-cache"] == "HIT"
    assert second.content == first.content

    stats = (await client.get("/api/tiles/stats", headers=auth_headers)).json()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert 0.0 <= stats["hit_ratio"] <= 1.0


async def test_tile_invalidated_on_service_area_edit(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _setup_map_data(client, auth_headers)
    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 15)

    await client.get(f"/tiles/15/{x}/{y}.mvt", headers=auth_headers)
    warm = await client.get(f"/tiles/15/{x}/{y}.mvt", headers=auth_headers)
    assert warm.headers["x-tile-cache"] == "HIT"

    # Creating a new service area invalidates the tenant's tiles.
    resp = await client.post(
        "/api/service-areas",
        json={"name": "Second", "geometry": SERVICE_AREA_GEOM},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    after = await client.get(f"/tiles/15/{x}/{y}.mvt", headers=auth_headers)
    assert after.headers["x-tile-cache"] == "MISS"


async def test_tile_requires_auth(client: httpx.AsyncClient) -> None:
    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 13)
    assert (await client.get(f"/tiles/13/{x}/{y}.mvt")).status_code == 401


async def test_tile_auth_via_cookie(client: httpx.AsyncClient, tenant_user: Any) -> None:
    _, user, password = tenant_user
    login = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 13)
    resp = await client.get(
        f"/tiles/13/{x}/{y}.mvt", cookies={"access_token": login.json()["access_token"]}
    )
    assert resp.status_code == 200


async def test_empty_tile_far_away(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    # Middle of the Pacific.
    x, y = tile_xyz(-150.0, -20.0, 13)
    resp = await client.get(f"/tiles/13/{x}/{y}.mvt", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.content == b""


async def test_tile_coordinates_out_of_range(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    # x beyond 2^z - 1.
    assert (await client.get("/tiles/3/9/0.mvt", headers=auth_headers)).status_code == 400
    assert (await client.get("/tiles/23/0/0.mvt", headers=auth_headers)).status_code == 422


async def test_tile_tenant_scoping(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: Any,
) -> None:
    """A tenant with no data gets an empty tile even where another has data."""
    from uuid import uuid4

    from cartograph.auth.models import Tenant, User
    from cartograph.auth.security import create_access_token

    await _setup_map_data(client, auth_headers)

    other_tenant = Tenant(slug=f"tt-{uuid4().hex[:10]}", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email=f"tt-{uuid4().hex[:10]}@example.com",
        password_hash="x",
    )
    db_session.add(other_user)
    await db_session.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(other_user.id, other_tenant.id)}"
    }

    x, y = tile_xyz(CENTER_LNG, CENTER_LAT, 13)
    resp = await client.get(f"/tiles/13/{x}/{y}.mvt", headers=other_headers)
    assert resp.status_code == 200
    assert resp.content == b""
