"""GeoJSON → validated shapely MultiPolygon.

Accepts a bare Polygon/MultiPolygon geometry, a Feature, or a
FeatureCollection; rejects anything invalid (self-intersections, out-of-range
coordinates) with a message the caller can surface verbatim.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union
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

    # Each component must be individually valid (self-intersections rejected
    # with a precise message)...
    for polygon in polygons:
        if polygon.is_empty:
            raise GeoJSONError("Geometry contains an empty polygon")
        if not polygon.is_valid:
            raise GeoJSONError(f"Invalid geometry: {explain_validity(polygon)}")

    # ...but polygons that touch or overlap each other are legitimate input
    # (adjacent delivery districts). A raw MultiPolygon of them is OGC-invalid,
    # so union the components instead of rejecting them.
    merged = unary_union(polygons)
    if isinstance(merged, Polygon):
        merged = MultiPolygon([merged])
    if not isinstance(merged, MultiPolygon) or merged.is_empty:
        raise GeoJSONError("Geometry is empty")

    _check_coordinate_range(merged)
    return merged
