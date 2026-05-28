from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fiona
from shapely.geometry import LineString, Point, mapping, shape

from rcsd_topo_poc.modules.t07_semantic_junction_anchor import run_t07_step3_intersection_match
from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"type": "Feature", "properties": properties, "geometry": mapping(geometry)}


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_crs84_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "CRS84"}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_gpkg(path: Path, features: list[dict[str, Any]]) -> None:
    write_gpkg(
        path,
        (
            {
                "properties": feature["properties"],
                "geometry": shape(feature["geometry"]),
            }
            for feature in features
        ),
        crs_text="EPSG:3857",
    )


def _read_gpkg_properties_by_id(path: Path) -> dict[str, dict[str, Any]]:
    with fiona.open(str(path)) as src:
        return {
            str(dict(feature["properties"])["id"]): dict(feature["properties"])
            for feature in src
        }


def _relation_targets(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(feature["properties"]["target_id"]) for feature in payload["features"]}


def test_step3_anchors_candidates_with_successful_t05_relation_and_existing_rcsdnode(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": None}, Point(0, 0)),
            _feature({"id": 101, "mainnodeid": 1, "kind_2": 0}, Point(1, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 8, "has_evd": "yes", "is_anchor": "no"}, Point(10, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 16, "has_evd": "yes", "is_anchor": "yes"}, Point(20, 0)),
            _feature({"id": 4, "mainnodeid": 4, "kind_2": 2048, "has_evd": "yes", "is_anchor": None}, Point(30, 0)),
            _feature({"id": 5, "mainnodeid": 5, "kind_2": 64, "has_evd": "yes", "is_anchor": "no"}, Point(40, 0)),
            _feature({"id": 6, "mainnodeid": 6, "kind_2": 4, "has_evd": "no", "is_anchor": "no"}, Point(50, 0)),
            _feature({"id": 7, "mainnodeid": 7, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(60, 0)),
            _feature({"id": 8, "mainnodeid": 8, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(70, 0)),
        ],
    )
    _write_geojson(
        relations_path,
        [
            _feature({"target_id": 1, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(0, 0), (0, 1)])),
            _feature({"target_id": 2, "base_id": 901, "status": 0, "level": 1, "is_highway": 0}, LineString([(10, 0), (10, 1)])),
            _feature({"target_id": 3, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(20, 0), (20, 1)])),
            _feature({"target_id": 4, "base_id": 999, "status": 0, "level": 1, "is_highway": 0}, LineString([(30, 0), (30, 1)])),
            _feature({"target_id": 5, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(40, 0), (40, 1)])),
            _feature({"target_id": 7, "base_id": 0, "status": 1, "level": 1, "is_highway": 0}, LineString([(60, 0), (60, 1)])),
        ],
    )
    _write_geojson(
        rcsdnode_path,
        [
            _feature({"id": 900, "mainnodeid": None}, Point(100, 0)),
            _feature({"id": 901, "mainnodeid": 901}, Point(101, 0)),
        ],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"
    assert props["1"]["anchor_reason"] is None
    assert props["101"]["is_anchor"] is None
    assert props["2"]["is_anchor"] == "yes"
    assert props["3"]["is_anchor"] == "yes"
    assert props["4"]["is_anchor"] is None
    assert props["5"]["is_anchor"] == "no"
    assert props["6"]["is_anchor"] == "no"
    assert props["7"]["is_anchor"] == "no"
    assert props["8"]["is_anchor"] == "no"

    assert _relation_targets(artifacts.intersection_match_tool7_path) == {"1", "2"}
    relation_payload = json.loads(artifacts.intersection_match_tool7_path.read_text(encoding="utf-8"))
    assert relation_payload["crs"]["properties"]["name"] == "CRS84"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 5
    assert summary["accepted_count"] == 2
    assert summary["relation_missing_count"] == 1
    assert summary["relation_failure_count"] == 1
    assert summary["rcsd_missing_count"] == 1
    assert summary["skipped_kind2_count"] == 1
    assert summary["crs"]["intersection_match_tool7"] == "CRS84"
    assert "stage_timings" in summary["performance"]
    assert "evaluate_candidates_seconds" in summary["performance"]["stage_timings"]


def test_step3_uses_fast_paths_for_gpkg_nodes_and_crs84_relations(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"
    _write_gpkg(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": None, "anchor_reason": None}, Point(0, 0)),
        ],
    )
    _write_crs84_geojson(
        relations_path,
        [
            _feature(
                {"target_id": 1, "base_id": 900, "status": 0, "level": 1, "is_highway": 0},
                LineString([(120, 30), (120.1, 30.1)]),
            ),
        ],
    )
    _write_gpkg(
        rcsdnode_path,
        [_feature({"id": 900, "mainnodeid": None}, Point(100, 0))],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["output_strategy"]["nodes_write_mode"] == "copy_update_gpkg"
    assert summary["output_strategy"]["relation_write_mode"] == "raw_crs84"

    relation_payload = json.loads(artifacts.intersection_match_tool7_path.read_text(encoding="utf-8"))
    assert relation_payload["features"][0]["geometry"]["coordinates"] == [[120.0, 30.0], [120.1, 30.1]]
