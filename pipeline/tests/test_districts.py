import json
from pathlib import Path

from pipeline.lpe_pipeline.districts import merge_district_geojson


def test_merge_district_geojson_normalizes_polygon(tmp_path: Path) -> None:
    source = tmp_path / "districts.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"code": "SW11"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output.geojson"
    assert merge_district_geojson([source], {"SW11"}, output) == 1
    feature = json.loads(output.read_text(encoding="utf-8"))["features"][0]
    assert feature["geometry"]["type"] == "MultiPolygon"


def test_merge_district_geojson_uses_fallback_points(tmp_path: Path) -> None:
    source = tmp_path / "districts.geojson"
    source.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    output = tmp_path / "output.geojson"
    assert merge_district_geojson([source], {"E22"}, output, {"E22": [(-0.02, 51.5)]}) == 1
    feature = json.loads(output.read_text(encoding="utf-8"))["features"][0]
    assert feature["properties"]["code"] == "E22"
    assert feature["geometry"]["type"] == "MultiPolygon"
