from __future__ import annotations

import json
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer

from rcsd_topo_poc.modules.t00_utility_toolbox.road_kind_enrich import (
    RoadKindEnrichConfig,
    run_road_kind_enrich,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.road_patch_join import (
    RoadPatchJoinConfig,
    run_road_patch_join,
)


def _write_feature_collection(
    path: Path,
    features: list[dict[str, object]],
    *,
    crs_name: str | None = "EPSG:3857",
) -> None:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "features": features,
    }
    if crs_name is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_polyline_shapefile(
    path: Path,
    *,
    fields: list[tuple[str, str, int, int]],
    rows: list[tuple[list[list[float]], list[object]]],
    epsg: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with shapefile.Writer(str(path), shapeType=shapefile.POLYLINE) as writer:
        for name, field_type, size, decimal in fields:
            writer.field(name, field_type, size=size, decimal=decimal)
        for line_coordinates, values in rows:
            writer.line([line_coordinates])
            writer.record(*values)

    path.with_suffix(".prj").write_text(CRS.from_epsg(epsg).to_wkt(), encoding="utf-8")


def test_tool4_joins_patch_id_and_allows_multi_patch_assignment(tmp_path: Path) -> None:
    a200_path = tmp_path / "first_layer_road_net_v0" / "A200_road.shp"
    rc_path = tmp_path / "first_layer_road_net_v1_patch" / "rc_patch_road.shp"
    output_path = tmp_path / "first_layer_road_net_v0" / "A200_road_patch.geojson"
    unmatched_path = tmp_path / "first_layer_road_net_v0" / "A200_road_patch_unmatched.geojson"

    _write_polyline_shapefile(
        a200_path,
        fields=[("ID", "C", 20, 0)],
        rows=[
            ([[116.3000, 39.9000], [116.3010, 39.9000]], ["1"]),
            ([[116.3100, 39.9000], [116.3110, 39.9000]], ["2"]),
            ([[116.3200, 39.9000], [116.3210, 39.9000]], ["3"]),
            ([[116.3300, 39.9000], [116.3310, 39.9000]], ["4"]),
        ],
        epsg=4326,
    )
    _write_polyline_shapefile(
        rc_path,
        fields=[("ROAD_ID", "C", 20, 0), ("PATCH_ID", "C", 20, 0)],
        rows=[
            ([[116.3000, 39.9000], [116.3010, 39.9000]], ["1", "1001"]),
            ([[116.3100, 39.9000], [116.3110, 39.9000]], ["2", "1002"]),
            ([[116.3100, 39.9000], [116.3110, 39.9000]], ["2", "1002"]),
            ([[116.3200, 39.9000], [116.3210, 39.9000]], ["3", "1003"]),
            ([[116.3200, 39.9000], [116.3210, 39.9000]], ["3", "1004"]),
        ],
        epsg=4326,
    )

    summary = run_road_patch_join(
        RoadPatchJoinConfig(
            a200_input_path=a200_path,
            rc_patch_road_input_path=rc_path,
            output_path=output_path,
            unmatched_output_path=unmatched_path,
            target_epsg=3857,
            run_id="test_tool4_join",
        )
    )

    output_doc = json.loads(output_path.read_text(encoding="utf-8"))
    unmatched_doc = json.loads(unmatched_path.read_text(encoding="utf-8"))

    assert summary["matched_count"] == 3
    assert summary["unmatched_count"] == 1
    assert summary["duplicate_road_id_count"] == 2
    assert summary["conflicting_patch_id_count"] == 1
    assert summary["multi_patch_assignment_count"] == 1
    assert output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert unmatched_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert [feature["properties"]["patch_id"] for feature in output_doc["features"]] == ["1001", "1002", "1003,1004"]
    assert {
        feature["properties"]["unmatched_reason"] for feature in unmatched_doc["features"]
    } == {"no rc_patch_road match"}
    first_geometry = output_doc["features"][0]["geometry"]["coordinates"][0]
    assert first_geometry[0] > 1_000_000
    assert first_geometry[1] > 1_000_000


def test_tool5_enriches_kind_with_sw_default_4326_and_target_3857(tmp_path: Path) -> None:
    a200_patch_path = tmp_path / "first_layer_road_net_v0" / "A200_road_patch.geojson"
    sw_path = tmp_path / "first_layer_road_net_v0" / "SW" / "A200-2025M12-road.geojson"
    output_path = tmp_path / "first_layer_road_net_v0" / "A200_road_patch_kind.geojson"

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    def to_3857(coordinates: list[list[float]]) -> list[list[float]]:
        return [list(transformer.transform(x, y)) for x, y in coordinates]

    _write_feature_collection(
        a200_patch_path,
        features=[
            {
                "type": "Feature",
                "properties": {"id": "1", "patch_id": "1001"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": to_3857([[116.3000, 39.9000], [116.3001, 39.9001]]),
                },
            },
            {
                "type": "Feature",
                "properties": {"id": "2", "patch_id": "1002"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": to_3857([[116.3100, 39.9000], [116.3101, 39.9001]]),
                },
            },
            {
                "type": "Feature",
                "properties": {"id": "3", "patch_id": "1003"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": to_3857([[116.3200, 39.9000], [116.3201, 39.9001]]),
                },
            },
        ],
        crs_name="EPSG:3857",
    )
    _write_feature_collection(
        sw_path,
        features=[
            {
                "type": "Feature",
                "properties": {"Kind": "1201|1202"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.3000, 39.9000], [116.3001, 39.9001]],
                },
            },
            {
                "type": "Feature",
                "properties": {"kind": "1202|1301"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.30001, 39.90001], [116.30009, 39.90009]],
                },
            },
            {
                "type": "Feature",
                "properties": {"Kind": ""},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.3200, 39.9000], [116.3201, 39.9001]],
                },
            },
        ],
        crs_name=None,
    )

    summary = run_road_kind_enrich(
        RoadKindEnrichConfig(
            a200_patch_input_path=a200_patch_path,
            sw_input_path=sw_path,
            output_path=output_path,
            target_epsg=3857,
            a200_patch_default_crs_text="EPSG:3857",
            sw_default_crs_text="EPSG:4326",
            buffer_distance_meters=1.0,
            spatial_predicate="covers",
            run_id="test_tool5_kind",
        )
    )

    output_doc = json.loads(output_path.read_text(encoding="utf-8"))
    output_features = output_doc["features"]

    assert output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert summary["matched_kind_count"] == 1
    assert summary["unmatched_kind_count"] == 1
    assert summary["empty_kind_count"] == 1
    assert summary["kind_field"] in {"Kind", "kind"}
    assert summary["spatial_predicate"] == "covers"
    assert summary["sw_default_crs_text"] == "EPSG:4326"
    assert set(str(output_features[0]["properties"]["kind"]).split("|")) == {"1201", "1202", "1301"}
    assert output_features[1]["properties"]["kind"] is None
    assert output_features[2]["properties"]["kind"] is None
