from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor import internal_full_input_runner
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
    run_t03_internal_full_input,
)


def test_internal_full_input_runner_prepares_case_packages_and_runs_step67(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    visual_check_dir = tmp_path / "visual_checks"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100001",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road_h", "snodeid": "100001", "enodeid": "n2", "direction": 2},
                "geometry": LineString([(-30.0, 0.0), (30.0, 0.0)]),
            },
            {
                "properties": {"id": "road_v", "snodeid": "n3", "enodeid": "100001", "direction": 2},
                "geometry": LineString([(0.0, -30.0), (0.0, 30.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": box(-60.0, -60.0, 60.0, 60.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_r_1", "snodeid": "rc_a", "enodeid": "rc_n_1", "direction": 2},
                "geometry": LineString([(-12.0, 2.0), (12.0, 2.0)]),
            },
            {
                "properties": {"id": "rc_r_2", "snodeid": "rc_n_1", "enodeid": "rc_b", "direction": 2},
                "geometry": LineString([(2.0, -12.0), (2.0, 12.0)]),
            },
            {
                "properties": {"id": "rc_r_3", "snodeid": "rc_n_1", "enodeid": "rc_c", "direction": 2},
                "geometry": LineString([(2.0, 2.0), (12.0, 12.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {
                "properties": {"id": "rc_n_1", "mainnodeid": "rc_g_1"},
                "geometry": Point(2.0, 2.0),
            }
        ],
        crs_text="EPSG:3857",
    )

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="internal_full_input_case",
        workers=1,
        max_cases=1,
        debug=False,
        review_mode=True,
        visual_check_dir=visual_check_dir,
    )

    local_context_path = artifacts.case_root / "100001.json"
    step3_case_dir = artifacts.step3_run_root / "cases" / "100001"
    step67_case_dir = artifacts.run_root / "cases" / "100001"
    polygons_path = artifacts.run_root / "virtual_intersection_polygons.gpkg"
    updated_nodes_path = artifacts.run_root / "nodes.gpkg"
    nodes_audit_json_path = artifacts.run_root / "nodes_anchor_update_audit.json"
    nodes_audit_csv_path = artifacts.run_root / "nodes_anchor_update_audit.csv"
    summary_doc = json.loads((artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    review_summary_doc = json.loads((artifacts.run_root / "t03_review_summary.json").read_text(encoding="utf-8"))
    internal_manifest = json.loads((artifacts.internal_root / "t03_internal_full_input_manifest.json").read_text(encoding="utf-8"))
    internal_progress = json.loads((artifacts.internal_root / "t03_internal_full_input_progress.json").read_text(encoding="utf-8"))
    internal_performance = json.loads((artifacts.internal_root / "t03_internal_full_input_performance.json").read_text(encoding="utf-8"))
    case_progress = json.loads((artifacts.internal_root / "case_progress" / "100001.json").read_text(encoding="utf-8"))
    watch_status = json.loads((step67_case_dir / "t03_case_watch_status.json").read_text(encoding="utf-8"))
    final_polygon = read_vector_layer(step67_case_dir / "step67_final_polygon.gpkg").features
    polygons = read_vector_layer(polygons_path).features
    updated_nodes = read_vector_layer(updated_nodes_path).features
    nodes_audit_doc = json.loads(nodes_audit_json_path.read_text(encoding="utf-8"))

    assert artifacts.selected_case_ids == ("100001",)
    assert local_context_path.is_file()
    assert (step3_case_dir / "step3_status.json").is_file()
    assert (step67_case_dir / "step7_status.json").is_file()
    assert (step67_case_dir / "t03_case_watch_status.json").is_file()
    assert polygons_path.is_file()
    assert updated_nodes_path.is_file()
    assert nodes_audit_json_path.is_file()
    assert nodes_audit_csv_path.is_file()
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["flat_png_count"] == 1
    assert "visual_v1_count" not in summary_doc
    assert review_summary_doc["visual_class_counts"]["V1 认可成功"] == 1
    assert sorted(path.name for path in visual_check_dir.glob("*.png")) == [
        "0001_100001_accepted_center_junction.png"
    ]
    assert internal_progress["phase"] == "completed"
    assert internal_progress["status"] == "completed"
    assert internal_progress["execution_mode"] == "direct_shared_handle_local_query"
    assert internal_progress["total_case_count"] == 1
    assert internal_progress["completed_case_count"] == 1
    assert internal_progress["success_case_count"] == 1
    assert internal_progress["failed_case_count"] == 0
    assert internal_progress["entered_case_execution_stage"] is True
    assert "selected_case_ids" not in internal_progress
    assert "discovered_case_ids" not in internal_progress
    assert "default_full_batch_excluded_case_ids" not in internal_progress
    assert "prepared_case_ids" not in internal_progress
    assert internal_performance["phase"] == "completed"
    assert internal_performance["total_case_count"] == 1
    assert internal_performance["selected_case_count"] == 1
    assert internal_performance["completed_case_count"] == 1
    assert set(internal_performance["performance"]["stage_timer_totals_seconds"]) == {
        "candidate_discovery",
        "shared_preload",
        "local_feature_selection",
        "step3",
        "step45",
        "step6",
        "step7",
        "output_write",
        "visual_copy",
        "observability_write",
    }
    assert case_progress["state"] == "accepted"
    assert watch_status["state"] == "accepted"
    assert watch_status["current_stage"] == "completed"
    assert "visual_class" not in watch_status
    assert internal_manifest["review_mode_requested"] is True
    assert internal_manifest["review_mode_effective"] is False
    assert internal_manifest["source_mode"] == "t03_internal_full_input_direct_local_query"
    assert internal_manifest["transitional_case_package_path_retained"] is False
    assert internal_manifest["progress_payload_mode"] == "lightweight_runtime_counters"
    assert internal_manifest["pending_case_prewrite_enabled"] is False
    assert internal_manifest["selected_case_ids"] == ["100001"]
    assert internal_manifest["virtual_intersection_polygons_path"] == str(polygons_path)
    assert internal_manifest["nodes_output_path"] == str(updated_nodes_path)
    assert internal_manifest["performance_path"] == str(artifacts.internal_root / "t03_internal_full_input_performance.json")
    assert len(polygons) == 1
    assert len(final_polygon) == 1
    polygon_properties = polygons[0].properties
    final_polygon_properties = final_polygon[0].properties
    assert set(polygon_properties) == {
        "mainnodeid",
        "kind",
        "kind_source",
        "status",
        "representative_node_id",
        "kind_2",
        "grade_2",
        "success",
        "business_outcome_class",
        "acceptance_class",
        "root_cause_layer",
        "root_cause_type",
        "visual_review_class",
        "official_review_eligible",
        "failure_bucket",
        "source_case_dir",
    }
    assert polygon_properties["mainnodeid"] == "100001"
    assert polygon_properties["representative_node_id"] == "100001"
    assert polygon_properties["success"] is True
    assert polygon_properties["business_outcome_class"] == "success"
    assert polygon_properties["acceptance_class"] == "accepted"
    assert "visual_review_class" not in final_polygon_properties
    assert "visual_audit_class" not in final_polygon_properties
    assert "manual_review_recommended" not in final_polygon_properties
    updated_node_map = {str(feature.properties["id"]): feature.properties.get("is_anchor") for feature in updated_nodes}
    assert updated_node_map["100001"] == "yes"
    assert nodes_audit_doc["updated_to_yes_count"] == 1
    assert nodes_audit_doc["updated_to_fail3_count"] == 0


def test_internal_full_input_runner_writes_nodes_fail3_for_runtime_failed_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100001",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "100002",
                    "mainnodeid": "100002",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(100.0, 0.0),
            },
            {
                "properties": {
                    "id": "100003",
                    "mainnodeid": "100003",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(200.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road1_h", "snodeid": "100001", "enodeid": "n2", "direction": 2},
                "geometry": LineString([(-30.0, 0.0), (30.0, 0.0)]),
            },
            {
                "properties": {"id": "road1_v", "snodeid": "n3", "enodeid": "100001", "direction": 2},
                "geometry": LineString([(0.0, -30.0), (0.0, 30.0)]),
            },
            {
                "properties": {"id": "road2_h", "snodeid": "100002", "enodeid": "n4", "direction": 2},
                "geometry": LineString([(70.0, 0.0), (130.0, 0.0)]),
            },
            {
                "properties": {"id": "road2_v", "snodeid": "n5", "enodeid": "100002", "direction": 2},
                "geometry": LineString([(100.0, -30.0), (100.0, 30.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": box(-60.0, -60.0, 160.0, 60.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_r_1", "snodeid": "rc_a", "enodeid": "rc_n_1", "direction": 2},
                "geometry": LineString([(-12.0, 2.0), (12.0, 2.0)]),
            },
            {
                "properties": {"id": "rc_r_2", "snodeid": "rc_n_1", "enodeid": "rc_b", "direction": 2},
                "geometry": LineString([(2.0, -12.0), (2.0, 12.0)]),
            },
            {
                "properties": {"id": "rc_r_3", "snodeid": "rc_n_1", "enodeid": "rc_c", "direction": 2},
                "geometry": LineString([(2.0, 2.0), (12.0, 12.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {
                "properties": {"id": "rc_n_1", "mainnodeid": "rc_g_1"},
                "geometry": Point(2.0, 2.0),
            }
        ],
        crs_text="EPSG:3857",
    )

    original_run_single_case_direct = internal_full_input_runner._run_single_case_direct

    def _patched_run_single_case_direct(*args, **kwargs):
        if kwargs.get("case_id") == "100002":
            raise RuntimeError("synthetic runtime failure")
        return original_run_single_case_direct(*args, **kwargs)

    monkeypatch.setattr(internal_full_input_runner, "_run_single_case_direct", _patched_run_single_case_direct)

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="runtime_failed_case",
        workers=1,
        max_cases=2,
        debug=False,
    )

    updated_nodes = read_vector_layer(artifacts.run_root / "nodes.gpkg").features
    nodes_audit_doc = json.loads((artifacts.run_root / "nodes_anchor_update_audit.json").read_text(encoding="utf-8"))
    polygons = read_vector_layer(artifacts.run_root / "virtual_intersection_polygons.gpkg").features
    internal_progress = json.loads((artifacts.internal_root / "t03_internal_full_input_progress.json").read_text(encoding="utf-8"))

    updated_node_map = {str(feature.properties["id"]): feature.properties.get("is_anchor") for feature in updated_nodes}
    assert updated_node_map["100001"] == "yes"
    assert updated_node_map["100002"] == "fail3"
    assert updated_node_map["100003"] == "no"
    assert nodes_audit_doc["updated_to_yes_count"] == 1
    assert nodes_audit_doc["updated_to_fail3_count"] == 1
    assert {(row["case_id"], row["new_is_anchor"]) for row in nodes_audit_doc["rows"]} == {
        ("100001", "yes"),
        ("100002", "fail3"),
    }
    assert len(polygons) == 1
    assert polygons[0].properties["mainnodeid"] == "100001"
    assert internal_progress["runtime_failed_case_count"] == 1
    assert internal_progress["failed_case_count"] == 1
    assert "100002" in internal_progress["runtime_failed_case_ids"]


def test_internal_full_input_runner_writes_fail3_for_rejected_case_only_on_representative_node(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100001",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "100001_aux",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "keep_aux",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(5.0, 0.0),
            },
            {
                "properties": {
                    "id": "100002",
                    "mainnodeid": "100002",
                    "has_evd": "no",
                    "is_anchor": "leave_unselected",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(100.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(roads_path, [], crs_text="EPSG:3857")
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": box(-60.0, -60.0, 60.0, 60.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(rcsdroad_path, [], crs_text="EPSG:3857")
    write_vector(rcsdnode_path, [], crs_text="EPSG:3857")

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="rejected_case",
        workers=1,
        max_cases=1,
        debug=False,
    )

    summary_doc = json.loads((artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    step7_status = json.loads((artifacts.run_root / "cases" / "100001" / "step7_status.json").read_text(encoding="utf-8"))
    updated_nodes = read_vector_layer(artifacts.run_root / "nodes.gpkg").features
    nodes_audit_doc = json.loads((artifacts.run_root / "nodes_anchor_update_audit.json").read_text(encoding="utf-8"))
    polygons = read_vector_layer(artifacts.run_root / "virtual_intersection_polygons.gpkg").features

    updated_node_map = {str(feature.properties["id"]): feature.properties.get("is_anchor") for feature in updated_nodes}

    assert summary_doc["step7_accepted_count"] == 0
    assert summary_doc["step7_rejected_count"] == 1
    assert step7_status["step7_state"] == "rejected"
    assert updated_node_map["100001"] == "fail3"
    assert updated_node_map["100001_aux"] == "keep_aux"
    assert updated_node_map["100002"] == "leave_unselected"
    assert nodes_audit_doc["updated_to_yes_count"] == 0
    assert nodes_audit_doc["updated_to_fail3_count"] == 1
    assert nodes_audit_doc["rows"] == [
        {
            "case_id": "100001",
            "representative_node_id": "100001",
            "previous_is_anchor": "no",
            "new_is_anchor": "fail3",
            "step7_state": "rejected",
            "reason": "step67_blocked_by_step45",
        }
    ]
    assert polygons == []


def test_internal_full_input_runner_writes_failure_artifact_on_prepare_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    for file_name in ("nodes.gpkg", "roads.gpkg", "drivezone.gpkg", "rcsdroad.gpkg", "rcsdnode.gpkg"):
        (inputs_dir / file_name).write_bytes(b"placeholder")

    def _raise_prepare_error(**kwargs):
        raise RuntimeError("synthetic prepare failure")

    monkeypatch.setattr(internal_full_input_runner, "_load_shared_nodes", _raise_prepare_error)

    with pytest.raises(RuntimeError, match="synthetic prepare failure"):
        run_t03_internal_full_input(
            nodes_path=inputs_dir / "nodes.gpkg",
            roads_path=inputs_dir / "roads.gpkg",
            drivezone_path=inputs_dir / "drivezone.gpkg",
            rcsdroad_path=inputs_dir / "rcsdroad.gpkg",
            rcsdnode_path=inputs_dir / "rcsdnode.gpkg",
            out_root=out_root,
            run_id="failure_case",
            workers=1,
        )

    internal_root = out_root / "_internal" / "failure_case"
    progress_doc = json.loads((internal_root / "t03_internal_full_input_progress.json").read_text(encoding="utf-8"))
    failure_doc = json.loads((internal_root / "t03_internal_full_input_failure.json").read_text(encoding="utf-8"))

    assert progress_doc["status"] == "failed"
    assert progress_doc["failure"] == "synthetic prepare failure"
    assert failure_doc["failure"] == "synthetic prepare failure"
