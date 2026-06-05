from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.nodes_publish import write_t04_nodes_outputs


def _feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"type": "Feature", "properties": properties, "geometry": mapping(geometry)}


def _write_intersection_match(path: Path, features: list[dict[str, Any]]) -> None:
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


def _write_t04_relation_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "target_crs": "EPSG:3857",
                "row_count": 3,
                "rows": [
                    {
                        "target_id": "1001",
                        "case_id": "1001",
                        "junction_type": "diverge",
                        "final_state": "accepted",
                        "surface_candidate_present": 1,
                        "base_id_candidate": "9001",
                        "status_suggested": 0,
                        "relation_state": "success_required_rcsd_junction",
                        "reason": "success_required_rcsd_junction",
                        "level": 2,
                        "is_highway": 1,
                        "swsd_point_x": 0,
                        "swsd_point_y": 0,
                        "rcsd_point_x": 10,
                        "rcsd_point_y": 0,
                    },
                    {
                        "target_id": "2002",
                        "case_id": "2002",
                        "junction_type": "merge",
                        "final_state": "accepted",
                        "surface_candidate_present": 1,
                        "base_id_candidate": "9002",
                        "status_suggested": 0,
                        "relation_state": "success_required_rcsd_junction",
                        "reason": "success_required_rcsd_junction",
                        "level": 2,
                        "is_highway": 0,
                        "swsd_point_x": 20,
                        "swsd_point_y": 0,
                        "rcsd_point_x": 30,
                        "rcsd_point_y": 0,
                    },
                    {
                        "target_id": "3003",
                        "case_id": "3003",
                        "junction_type": "complex_divmerge",
                        "final_state": "accepted",
                        "surface_candidate_present": 1,
                        "base_id_candidate": "9003",
                        "status_suggested": 0,
                        "relation_state": "success_required_rcsd_junction",
                        "reason": "success_required_rcsd_junction",
                        "level": 1,
                        "is_highway": 0,
                        "swsd_point_x": 40,
                        "swsd_point_y": 0,
                        "rcsd_point_x": 50,
                        "rcsd_point_y": 0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_intersection_match_t04_validates_t07_t03_and_rolls_back_one_to_many(tmp_path: Path) -> None:
    pytest.importorskip("fiona")
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_t04_relation_evidence(run_root / "t04_swsd_rcsd_relation_evidence.json")

    input_nodes_path = tmp_path / "input_nodes.gpkg"
    source_features = [
        {"properties": {"id": "1001", "mainnodeid": "1001", "is_anchor": "no"}, "geometry": Point(0, 0)},
        {"properties": {"id": "2002", "mainnodeid": "2002", "is_anchor": "no"}, "geometry": Point(20, 0)},
        {"properties": {"id": "3003", "mainnodeid": "3003", "is_anchor": "no"}, "geometry": Point(40, 0)},
    ]
    write_vector(input_nodes_path, source_features, crs_text="EPSG:3857", layer_name="nodes")

    t07_path = tmp_path / "intersection_match_t07.geojson"
    _write_intersection_match(
        t07_path,
        [
            _feature(
                {"target_id": "1001", "base_id": "9999", "status": 0},
                LineString([(0.0, 0.0), (0.1, 0.1)]),
            )
        ],
    )
    t03_path = tmp_path / "intersection_match_t03.geojson"
    _write_intersection_match(
        t03_path,
        [
            _feature(
                {"target_id": "7777", "base_id": "9003", "status": 0},
                LineString([(0.2, 0.0), (0.3, 0.1)]),
            )
        ],
    )

    outputs = write_t04_nodes_outputs(
        run_root=run_root,
        source_node_features=source_features,
        selected_cases=[
            {"case_id": "1001", "mainnodeid": "1001"},
            {"case_id": "2002", "mainnodeid": "2002"},
            {"case_id": "3003", "mainnodeid": "3003"},
        ],
        artifacts=[
            SimpleNamespace(case_id="1001", final_state="accepted", reject_reasons=()),
            SimpleNamespace(case_id="2002", final_state="accepted", reject_reasons=()),
            SimpleNamespace(case_id="3003", final_state="accepted", reject_reasons=()),
        ],
        input_nodes_path=input_nodes_path,
        intersection_match_t07_path=t07_path,
        intersection_match_t03_path=t03_path,
    )

    match_payload = json.loads((run_root / "intersection_match_t04.geojson").read_text(encoding="utf-8"))
    published_targets = {str(feature["properties"]["target_id"]) for feature in match_payload["features"]}
    summary = json.loads((run_root / "intersection_match_t04_summary.json").read_text(encoding="utf-8"))
    errors = json.loads((run_root / "intersection_match_t04_cardinality_errors.json").read_text(encoding="utf-8"))
    nodes_audit = json.loads((run_root / "nodes_anchor_update_audit.json").read_text(encoding="utf-8"))

    assert match_payload["crs"]["properties"]["name"] == "CRS84"
    assert published_targets == {"2002"}
    assert summary["relation_cardinality_passed"] is False
    assert summary["one_target_to_many_base_count"] == 1
    assert summary["many_target_to_one_base_count"] == 1
    assert summary["rollback_target_ids"] == ["1001"]
    assert {row["error_type"] for row in errors["rows"]} == {"one_target_to_many_base", "many_target_to_one_base"}
    assert outputs["nodes_updated_to_no_count"] == 1
    assert nodes_audit["updated_to_no_count"] == 1
    assert nodes_audit["rows"][-1]["reason"] == "intersection_match_t04_one_target_to_many_base"

    fiona = pytest.importorskip("fiona")
    with fiona.open(run_root / "nodes.gpkg") as src:
        node_state_by_id = {str(row["properties"]["id"]): row["properties"]["is_anchor"] for row in src}
    assert node_state_by_id["1001"] == "no"
    assert node_state_by_id["2002"] == "yes"
    assert node_state_by_id["3003"] == "yes"
