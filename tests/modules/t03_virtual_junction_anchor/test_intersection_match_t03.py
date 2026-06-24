from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import load_shared_nodes
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_streamed_results import T03StreamedCaseResult
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.t03_batch_closeout import (
    write_t03_relation_evidence,
    write_updated_nodes_outputs,
)


def _accepted_result(case_id: str) -> T03StreamedCaseResult:
    return T03StreamedCaseResult(
        case_id=case_id,
        representative_node_id=case_id,
        representative_mainnodeid=case_id,
        template_class="center_junction",
        association_class="A",
        association_state="established",
        step6_state="established",
        step7_state="accepted",
        visual_class="V1",
        reason="accepted",
        note="",
        root_cause_layer=None,
        root_cause_type=None,
        source_png_path="",
        final_polygon_path="",
    )


def _write_case_status(run_root: Path, case_id: str, rcsd_id: str, x: float) -> None:
    case_dir = run_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "association_status.json").write_text(
        json.dumps(
            {
                "template_class": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": [rcsd_id],
                "required_rcsdroad_ids": [f"{rcsd_id}_road"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_vector(
        case_dir / "association_required_rcsdnode.gpkg",
        [{"properties": {"id": rcsd_id}, "geometry": Point(x, 10.0)}],
        crs_text="EPSG:3857",
    )


def _feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"type": "Feature", "properties": properties, "geometry": mapping(geometry)}


def _write_t07_match(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "CRS84"}},
                "features": [
                    _feature({"target_id": "100001", "base_id": "rc_b", "status": 0}, LineString([(0, 0), (1, 1)])),
                    _feature({"target_id": "100003", "base_id": "rc_c", "status": 0}, LineString([(0, 0), (1, 1)])),
                    _feature({"target_id": "100004", "base_id": "rc_d", "status": 0}, LineString([(0, 0), (1, 1)])),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_intersection_match_t03_suppresses_conflict_without_node_rollback(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "summary.json").write_text(json.dumps({"total_case_count": 3}), encoding="utf-8")
    nodes_path = tmp_path / "nodes.gpkg"
    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100001", "mainnodeid": "100001", "has_evd": "yes", "is_anchor": "no", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": "100002", "mainnodeid": "100002", "has_evd": "yes", "is_anchor": "no", "kind_2": 4}, "geometry": Point(10, 0)},
            {"properties": {"id": "100004", "mainnodeid": "100004", "has_evd": "yes", "is_anchor": "no", "kind_2": 4}, "geometry": Point(20, 0)},
        ],
        crs_text="EPSG:3857",
    )
    _write_case_status(run_root, "100001", "rc_a", 1.0)
    _write_case_status(run_root, "100002", "rc_c", 11.0)
    _write_case_status(run_root, "100004", "rc_d", 21.0)
    t07_path = tmp_path / "intersection_match_t07.geojson"
    _write_t07_match(t07_path)

    outputs = write_updated_nodes_outputs(
        run_root=run_root,
        shared_nodes=load_shared_nodes(nodes_path=nodes_path),
        selected_case_ids=["100001", "100002", "100004"],
        streamed_results={
            "100001": _accepted_result("100001"),
            "100002": _accepted_result("100002"),
            "100004": _accepted_result("100004"),
        },
        failed_case_ids=[],
        input_nodes_path=nodes_path,
        intersection_match_t07_path=t07_path,
    )

    match_payload = json.loads(outputs["intersection_match_t03_path"].read_text(encoding="utf-8"))
    published_targets = {feature["properties"]["target_id"] for feature in match_payload["features"]}
    summary = json.loads(outputs["intersection_match_t03_summary_path"].read_text(encoding="utf-8"))
    errors = json.loads(outputs["intersection_match_t03_cardinality_errors_json_path"].read_text(encoding="utf-8"))
    updated_node_map = _node_anchor_map(outputs["nodes_path"])
    audit = json.loads(outputs["audit_json_path"].read_text(encoding="utf-8"))

    assert published_targets == {"100004"}
    assert summary["relation_cardinality_passed"] is False
    assert summary["one_target_to_many_base_count"] == 1
    assert summary["many_target_to_one_base_count"] == 1
    assert summary["rollback_target_ids"] == []
    assert {row["error_type"] for row in errors["rows"]} == {"one_target_to_many_base", "many_target_to_one_base"}
    assert updated_node_map["100001"] == "yes"
    assert updated_node_map["100002"] == "yes"
    assert updated_node_map["100004"] == "yes"
    assert audit["updated_to_no_count"] == 0


def test_t03_relation_evidence_reads_step6_status_without_legacy_association_status(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    shared_nodes = (
        LayerFeature(
            properties={
                "id": "100001",
                "mainnodeid": "100001",
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 2048,
            },
            geometry=Point(0, 0),
        ),
    )
    case_dir = run_root / "cases" / "100001"
    case_dir.mkdir(parents=True)
    (case_dir / "step6_status.json").write_text(
        json.dumps(
            {
                "template_class": "single_sided_t_mouth",
                "association_class": "A",
                "required_rcsdnode_ids": ["200001", "200002"],
                "required_rcsdroad_ids": ["300001"],
                "support_rcsdroad_ids": ["300002"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = write_t03_relation_evidence(
        run_root=run_root,
        shared_nodes=shared_nodes,
        selected_case_ids=["100001"],
        streamed_results={"100001": _accepted_result("100001")},
        failed_case_ids=[],
    )

    payload = json.loads(outputs["relation_evidence_json_path"].read_text(encoding="utf-8"))
    row = payload["rows"][0]
    assert row["required_rcsdnode_ids"] == "200001|200002"
    assert row["required_rcsdroad_ids"] == "300001"
    assert row["support_rcsdroad_ids"] == "300002"
    assert row["base_id_candidate"] == "200001|200002"
    assert row["status_suggested"] == 0
    assert row["relation_state"] == "success_required_rcsd_junction"


def test_intersection_match_t03_accepts_optional_intersection_match_all(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "summary.json").write_text(json.dumps({"total_case_count": 2}), encoding="utf-8")
    nodes_path = tmp_path / "nodes.gpkg"
    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100001", "mainnodeid": "100001", "has_evd": "yes", "is_anchor": "no", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": "100002", "mainnodeid": "100002", "has_evd": "yes", "is_anchor": "no", "kind_2": 4}, "geometry": Point(10, 0)},
        ],
        crs_text="EPSG:3857",
    )
    _write_case_status(run_root, "100001", "rc_a", 1.0)
    _write_case_status(run_root, "100002", "rc_b", 11.0)
    intersection_match_all_path = tmp_path / "intersection_match_all.geojson"
    intersection_match_all_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "CRS84"}},
                "features": [
                    _feature(
                        {"target_id": "100001", "base_id": "rc_x", "status": 0, "source_module": "T05"},
                        LineString([(0, 0), (1, 1)]),
                    )
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    outputs = write_updated_nodes_outputs(
        run_root=run_root,
        shared_nodes=load_shared_nodes(nodes_path=nodes_path),
        selected_case_ids=["100001", "100002"],
        streamed_results={
            "100001": _accepted_result("100001"),
            "100002": _accepted_result("100002"),
        },
        failed_case_ids=[],
        input_nodes_path=nodes_path,
        intersection_match_all_path=intersection_match_all_path,
    )

    match_payload = json.loads(outputs["intersection_match_t03_path"].read_text(encoding="utf-8"))
    published_targets = {feature["properties"]["target_id"] for feature in match_payload["features"]}
    summary = json.loads(outputs["intersection_match_t03_summary_path"].read_text(encoding="utf-8"))
    updated_node_map = _node_anchor_map(outputs["nodes_path"])

    assert published_targets == {"100002"}
    assert summary["relation_validation_source"] == "intersection_match_all"
    assert summary["external_validation_enabled"] is True
    assert summary["t07_validation_enabled"] is False
    assert summary["external_validation_relation_count"] == 1
    assert summary["one_target_to_many_base_count"] == 1
    assert summary["rollback_target_ids"] == []
    assert updated_node_map["100001"] == "yes"
    assert updated_node_map["100002"] == "yes"


def _node_anchor_map(path: Path) -> dict[str, str]:
    with sqlite3.connect(str(path)) as connection:
        table_name = connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name LIMIT 1"
        ).fetchone()[0]
        rows = connection.execute(f'SELECT id, is_anchor FROM "{table_name}"').fetchall()
    return {str(row[0]): row[1] for row in rows}
