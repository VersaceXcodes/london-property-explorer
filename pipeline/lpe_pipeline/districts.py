from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .postcodes import postcode_district

GEOJSON_SIZE_LIMIT_BYTES = 500 * 1024
SIMPLIFICATION_TOLERANCES = (0.0, 0.0005, 0.001, 0.002, 0.003, 0.005)
FALLBACK_RADIUS_DEGREES = 0.006


def _features(document: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if document.get("type") == "FeatureCollection":
        yield from document.get("features", [])
    elif document.get("type") == "Feature":
        yield document


Point = tuple[float, float]
Ring = list[Point]
Polygon = list[Ring]
MultiPolygon = list[Polygon]


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    if start == end:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    numerator = abs(
        (end[0] - start[0]) * (start[1] - point[1]) - (start[0] - point[0]) * (end[1] - start[1])
    )
    denominator = math.hypot(end[0] - start[0], end[1] - start[1])
    return numerator / denominator


def _rdp(points: Ring, tolerance: float) -> Ring:
    if len(points) <= 2 or tolerance <= 0:
        return points
    start = points[0]
    end = points[-1]
    distance, index = max(
        ((_point_line_distance(point, start, end), i) for i, point in enumerate(points[1:-1], 1)),
        default=(0.0, 0),
    )
    if distance > tolerance:
        return _rdp(points[: index + 1], tolerance)[:-1] + _rdp(points[index:], tolerance)
    return [start, end]


def _close_ring(points: Ring) -> Ring:
    if not points:
        return points
    if points[0] != points[-1]:
        return [*points, points[0]]
    return points


def _simplify_ring(raw_ring: list[list[float]], tolerance: float) -> list[list[float]]:
    ring = [(float(point[0]), float(point[1])) for point in raw_ring if len(point) >= 2]
    if len(ring) < 4:
        return []
    open_ring = ring[:-1] if ring[0] == ring[-1] else ring
    simplified = _close_ring(_rdp(open_ring, tolerance))
    if len(simplified) < 4:
        simplified = _close_ring(open_ring[:3])
    return [[round(lng, 5), round(lat, 5)] for lng, lat in simplified]


def _simplify_geometry(geometry: dict[str, Any], tolerance: float) -> dict[str, Any]:
    polygons = geometry["coordinates"]
    simplified_polygons = []
    for polygon in polygons:
        rings = [_simplify_ring(ring, tolerance) for ring in polygon]
        rings = [ring for ring in rings if ring]
        if rings:
            simplified_polygons.append(rings)
    return {"type": "MultiPolygon", "coordinates": simplified_polygons}


def _feature_collection(features: dict[str, dict[str, Any]], tolerance: float) -> dict[str, Any]:
    simplified = []
    for code in sorted(features):
        feature = features[code]
        simplified.append(
            {
                "type": "Feature",
                "properties": {"code": code},
                "geometry": _simplify_geometry(feature["geometry"], tolerance),
            }
        )
    return {"type": "FeatureCollection", "features": simplified}


def _fallback_geometry(points: list[Point]) -> dict[str, Any]:
    if not points:
        raise ValueError("fallback district has no points")
    lng = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)
    radius = FALLBACK_RADIUS_DEGREES
    ring = [
        [round(lng - radius, 5), round(lat - radius, 5)],
        [round(lng + radius, 5), round(lat - radius, 5)],
        [round(lng + radius, 5), round(lat + radius, 5)],
        [round(lng - radius, 5), round(lat + radius, 5)],
        [round(lng - radius, 5), round(lat - radius, 5)],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def _write_sized_collection(features: dict[str, dict[str, Any]], output_path: Path) -> None:
    last_payload = ""
    for tolerance in SIMPLIFICATION_TOLERANCES:
        collection = _feature_collection(features, tolerance)
        payload = json.dumps(collection, separators=(",", ":"))
        last_payload = payload
        if len(payload.encode("utf-8")) < GEOJSON_SIZE_LIMIT_BYTES:
            output_path.write_text(payload, encoding="utf-8")
            return
    output_path.write_text(last_payload, encoding="utf-8")


def merge_district_geojson(
    source_paths: list[Path],
    wanted: set[str],
    output_path: Path,
    fallback_points: dict[str, list[Point]] | None = None,
) -> int:
    """Merge already-simplified district files and retain one feature per wanted code."""
    selected: dict[str, dict[str, Any]] = {}
    for path in source_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for feature in _features(document):
            properties = feature.get("properties") or {}
            raw_code = (
                properties.get("code") or properties.get("name") or properties.get("district")
            )
            if not raw_code:
                continue
            try:
                code = postcode_district(f"{raw_code} 1AA")
            except ValueError:
                code = str(raw_code).upper().replace(" ", "")
            if code not in wanted:
                continue
            if code in selected:
                raise ValueError(f"duplicate district polygon: {code}")
            geometry = feature.get("geometry")
            if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                raise ValueError(f"unsupported geometry for {code}")
            if geometry["type"] == "Polygon":
                geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
            selected[code] = {
                "type": "Feature",
                "properties": {"code": code},
                "geometry": geometry,
            }
    if fallback_points:
        for code in sorted(wanted.difference(selected)):
            points = fallback_points.get(code)
            if points:
                selected[code] = {
                    "type": "Feature",
                    "properties": {"code": code},
                    "geometry": _fallback_geometry(points),
                }
    _write_sized_collection(selected, output_path)
    return len(selected)
