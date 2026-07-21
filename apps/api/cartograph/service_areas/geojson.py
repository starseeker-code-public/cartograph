"""GeoJSON → validated shapely MultiPolygon.

Accepts a bare Polygon/MultiPolygon geometry, a Feature, or a
FeatureCollection; rejects anything invalid (self-intersections, out-of-range
coordinates) with a message the caller can surface verbatim.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import explain_validity


class GeoJSONError(ValueError):
    pass


def _extract_geometries(doc: dict[str, Any]) -> list[dict[str, Any]]:
    kind = doc.get("type")
    if kind in ("Polygon", "MultiPolygon"):
        return [doc]
    if kind == "Feature":
        geom = doc.get("geometry")
        if not isinstance(geom, dict):
            raise GeoJSONError("Feature has no geometry")
        return _extract_geometries(geom)
    if kind == "FeatureCollection":
        features = doc.get("features")
        if not isinstance(features, list) or not features:
            raise GeoJSONError("FeatureCollection has no features")
        out: list[dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict):
                raise GeoJSONError("FeatureCollection contains a non-object feature")
            out.extend(_extract_geometries(feature))
        return out
    raise GeoJSONError(
        f"Unsupported GeoJSON type {kind!r}; expected Polygon, MultiPolygon, "
        "Feature, or FeatureCollection"
    )


def _check_coordinate_range(geom: Polygon | MultiPolygon) -> None:
    min_x, min_y, max_x, max_y = geom.bounds
    if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
        raise GeoJSONError(
            "Coordinates out of range for EPSG:4326 (expected lng in [-180, 180], "
            f"lat in [-90, 90]; got bounds {geom.bounds})"
        )


def parse_multipolygon(doc: dict[str, Any]) -> MultiPolygon:
    """Parse and validate; always returns a MultiPolygon in EPSG:4326."""
    polygons: list[Polygon] = []
    for geom_doc in _extract_geometries(doc):
        try:
            geom = shape(geom_doc)
        except Exception as exc:
            raise GeoJSONError(f"Malformed GeoJSON geometry: {exc}") from exc
        if isinstance(geom, Polygon):
            polygons.append(geom)
        elif isinstance(geom, MultiPolygon):
            polygons.extend(geom.geoms)
        else:  # pragma: no cover — _extract_geometries filters types already
            raise GeoJSONError(f"Expected polygonal geometry, got {geom.geom_type}")

    if not polygons:
        raise GeoJSONError("No polygon found in GeoJSON input")

    multi = MultiPolygon(polygons)
    if multi.is_empty:
        raise GeoJSONError("Geometry is empty")
    if not multi.is_valid:
        raise GeoJSONError(f"Invalid geometry: {explain_validity(multi)}")
    _check_coordinate_range(multi)
    return multi
