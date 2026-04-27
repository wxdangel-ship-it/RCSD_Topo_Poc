from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor import internal_full_input_runner
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_streamed_results import (
    load_closeout_case_results,
    load_streamed_case_results,
    load_terminal_case_records,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    load_shared_nodes,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
    run_t03_internal_full_input,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.t03_batch_closeout import (
    write_updated_nodes_outputs,
    write_virtual_intersection_polygons,
)


def _write_single_case_inputs(inputs_dir: Path) -> tuple[Path, Path, Path, Path, Path]:
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
    return nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path


def _write_resume_retry_inputs(inputs_dir: Path) -> tuple[Path, Path, Path, Path, Path]:
    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {"id": "100001", "mainnodeid": "100001", "has_evd": "yes", "is_anchor": "no", "kind_2": 4, "grade_2": 1},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": "100002", "mainnodeid": "100002", "has_evd": "yes", "is_anchor": "no", "kind_2": 4, "grade_2": 1},
                "geometry": Point(100.0, 0.0),
            },
            {
                "properties": {"id": "100003", "mainnodeid": "100003", "has_evd": "yes", "is_anchor": "no", "kind_2": 4, "grade_2": 1},
                "geometry": Point(200.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road1_h", "snodeid": "100001", "enodeid": "road1_e", "direction": 2},
                "geometry": LineString([(-30.0, 0.0), (30.0, 0.0)]),
            },
            {
                "properties": {"id": "road1_v", "snodeid": "road1_s", "enodeid": "100001", "direction": 2},
                "geometry": LineString([(0.0, -30.0), (0.0, 30.0)]),
            },
            {
                "properties": {"id": "road3_h", "snodeid": "100003", "enodeid": "road3_e", "direction": 2},
                "geometry": LineString([(170.0, 0.0), (230.0, 0.0)]),
            },
            {
                "properties": {"id": "road3_v", "snodeid": "road3_s", "enodeid": "100003", "direction": 2},
                "geometry": LineString([(200.0, -30.0), (200.0, 30.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": box(-80.0, -80.0, 280.0, 80.0)}],
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
            {
                "properties": {"id": "rc_r_4", "snodeid": "rc_d", "enodeid": "rc_n_3", "direction": 2},
                "geometry": LineString([(188.0, 2.0), (212.0, 2.0)]),
            },
            {
                "properties": {"id": "rc_r_5", "snodeid": "rc_n_3", "enodeid": "rc_e", "direction": 2},
                "geometry": LineString([(202.0, -12.0), (202.0, 12.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "rc_n_1", "mainnodeid": "rc_g_1"}, "geometry": Point(2.0, 2.0)},
            {"properties": {"id": "rc_n_3", "mainnodeid": "rc_g_3"}, "geometry": Point(202.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    return nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path


def test_internal_full_input_runner_prepares_case_packages_and_runs_finalization(tmp_path: Path) -> None:
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
    step7_case_dir = artifacts.run_root / "cases" / "100001"
    polygons_path = artifacts.run_root / "virtual_intersection_polygons.gpkg"
    updated_nodes_path = artifacts.run_root / "nodes.gpkg"
    nodes_audit_json_path = artifacts.run_root / "nodes_anchor_update_audit.json"
    nodes_audit_csv_path = artifacts.run_root / "nodes_anchor_update_audit.csv"
    streamed_results_path = artifacts.internal_root / "t03_streamed_case_results.jsonl"
    terminal_record_path = artifacts.internal_root / "terminal_case_records" / "100001.json"
    summary_doc = json.loads((artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    review_summary_doc = json.loads((artifacts.run_root / "t03_review_summary.json").read_text(encoding="utf-8"))
    internal_manifest = json.loads((artifacts.internal_root / "t03_internal_full_input_manifest.json").read_text(encoding="utf-8"))
    internal_progress = json.loads((artifacts.internal_root / "t03_internal_full_input_progress.json").read_text(encoding="utf-8"))
    internal_performance = json.loads((artifacts.internal_root / "t03_internal_full_input_performance.json").read_text(encoding="utf-8"))
    case_progress = json.loads((artifacts.internal_root / "case_progress" / "100001.json").read_text(encoding="utf-8"))
    final_polygon = read_vector_layer(step7_case_dir / "step7_final_polygon.gpkg").features
    polygons = read_vector_layer(polygons_path).features
    updated_nodes = read_vector_layer(updated_nodes_path).features
    nodes_audit_doc = json.loads(nodes_audit_json_path.read_text(encoding="utf-8"))
    streamed_results = load_streamed_case_results(streamed_results_path)
    terminal_records = load_terminal_case_records(artifacts.internal_root)

    assert artifacts.selected_case_ids == ("100001",)
    assert not local_context_path.exists()
    assert (step3_case_dir / "step3_status.json").is_file()
    assert (step7_case_dir / "step7_status.json").is_file()
    assert not (step3_case_dir / "step3_review.png").exists()
    assert not (step7_case_dir / "step7_review.png").exists()
    assert not (step7_case_dir / "t03_case_watch_status.json").exists()
    assert not (artifacts.internal_root / "t03_perf_audit_config.json").exists()
    assert not (artifacts.internal_root / "t03_perf_audit_samples.jsonl").exists()
    assert not (artifacts.internal_root / "t03_perf_audit_summary.json").exists()
    assert polygons_path.is_file()
    assert updated_nodes_path.is_file()
    assert nodes_audit_json_path.is_file()
    assert nodes_audit_csv_path.is_file()
    assert streamed_results_path.is_file()
    assert terminal_record_path.is_file()
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["flat_png_count"] == 0
    assert "visual_v1_count" not in summary_doc
    assert review_summary_doc["visual_class_counts"]["V1 认可成功"] == 1
    assert list(visual_check_dir.glob("*.png")) == []
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
        "step3_reachable_support",
        "step3_negative_masks",
        "step3_cleanup_preview",
        "step3_hard_path_validation",
        "association",
        "step6",
        "step6_mask_prep",
        "step6_directional_cut",
        "step6_finalize",
        "step6_finalize_cleanup",
        "step6_finalize_validation",
        "step6_finalize_status",
        "step7",
        "output_write",
        "visual_copy",
        "root_observability_write",
        "case_observability_write",
        "local_context_snapshot_write",
        "perf_audit_write",
    }
    assert case_progress["state"] == "accepted"
    assert "selected_counts" not in case_progress
    assert internal_manifest["review_mode_requested"] is True
    assert internal_manifest["review_mode_effective"] is False
    assert internal_manifest["render_review_png"] is False
    assert internal_manifest["source_mode"] == "t03_internal_full_input_direct_local_query"
    assert internal_manifest["transitional_case_package_path_retained"] is False
    assert internal_manifest["progress_payload_mode"] == "lightweight_runtime_counters"
    assert internal_manifest["pending_case_prewrite_enabled"] is False
    assert internal_manifest["progress_flush_interval_sec"] == 5.0
    assert internal_manifest["progress_flush_interval_cases"] == 5
    assert internal_manifest["local_context_snapshot_mode"] == "failed_only"
    assert internal_manifest["selected_case_ids"] == ["100001"]
    assert internal_manifest["execution_case_ids"] == ["100001"]
    assert internal_manifest["streamed_case_results_path"] == str(streamed_results_path)
    assert internal_manifest["terminal_case_records_root"] == str(artifacts.internal_root / "terminal_case_records")
    assert internal_manifest["virtual_intersection_polygons_path"] == str(polygons_path)
    assert internal_manifest["nodes_output_path"] == str(updated_nodes_path)
    assert internal_manifest["performance_path"] == str(artifacts.internal_root / "t03_internal_full_input_performance.json")
    assert list(streamed_results) == ["100001"]
    assert streamed_results["100001"].step7_state == "accepted"
    assert streamed_results["100001"].source_png_path == ""
    assert terminal_records["100001"].terminal_state == "accepted"
    assert terminal_records["100001"].final_polygon_path == str(step7_case_dir / "step7_final_polygon.gpkg")
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


@pytest.mark.parametrize(
    ("snapshot_mode", "expect_snapshot"),
    [
        ("all", True),
        ("failed_only", False),
        ("off", False),
    ],
)
def test_internal_full_input_runner_applies_local_context_snapshot_mode_for_success_cases(
    tmp_path: Path,
    snapshot_mode: str,
    expect_snapshot: bool,
) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_single_case_inputs(inputs_dir)

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id=f"snapshot_mode_{snapshot_mode}",
        workers=1,
        max_cases=1,
        debug=False,
        local_context_snapshot_mode=snapshot_mode,
    )

    snapshot_path = artifacts.case_root / "100001.json"
    assert snapshot_path.exists() is expect_snapshot


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
    terminal_records = load_terminal_case_records(artifacts.internal_root)

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
    assert not (artifacts.case_root / "100001.json").exists()
    assert (artifacts.case_root / "100002.json").is_file()
    assert terminal_records["100002"].terminal_state == "runtime_failed"
    assert terminal_records["100002"].reason == "runtime_failed"


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
    terminal_records = load_terminal_case_records(artifacts.internal_root)

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
            "reason": "step7_blocked_by_association",
        }
    ]
    assert polygons == []
    assert terminal_records["100001"].terminal_state == "rejected"


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


def test_internal_full_input_runner_writes_perf_audit_logs_when_enabled(tmp_path: Path) -> None:
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
        run_id="perf_audit_case",
        workers=1,
        max_cases=1,
        debug=False,
        visual_check_dir=visual_check_dir,
        perf_audit=True,
        perf_audit_interval_sec=30,
        perf_audit_max_samples=64,
        perf_audit_max_bytes=100_000,
    )

    config_path = artifacts.internal_root / "t03_perf_audit_config.json"
    samples_path = artifacts.internal_root / "t03_perf_audit_samples.jsonl"
    summary_path = artifacts.internal_root / "t03_perf_audit_summary.json"

    assert config_path.is_file()
    assert samples_path.is_file()
    assert summary_path.is_file()

    config_doc = json.loads(config_path.read_text(encoding="utf-8"))
    sample_rows = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary_doc = json.loads(summary_path.read_text(encoding="utf-8"))
    total_bytes = config_path.stat().st_size + samples_path.stat().st_size + summary_path.stat().st_size

    assert config_doc["enabled"] is True
    assert config_doc["sample_interval_sec"] == 30
    assert config_doc["max_samples"] == 64
    assert config_doc["log_budget_bytes"] == 100_000
    assert sample_rows
    assert set(sample_rows[0]) == {
        "ts",
        "phase",
        "total",
        "completed",
        "running",
        "pending",
        "success",
        "failed",
        "runtime_failed_count",
        "business_rejected_count",
        "elapsed_s",
        "avg_case_s",
        "case_per_min",
        "effective_concurrency_est",
        "top_stage",
        "top_stage_s",
        "run_root_size_mb",
        "internal_root_size_mb",
        "cases_dir_count",
        "visual_png_count",
    }
    assert "selected_case_ids" not in summary_doc
    assert "discovered_case_ids" not in summary_doc
    assert "failed_case_ids" not in summary_doc
    assert summary_doc["sample_count_written"] == len(sample_rows)
    assert summary_doc["total_log_bytes_est"] <= 100_000
    assert total_bytes <= 100_000
    assert set(summary_doc["stage_timer_totals_seconds"]) == {
        "candidate_discovery",
        "shared_preload",
        "local_feature_selection",
        "step3",
        "step3_reachable_support",
        "step3_negative_masks",
        "step3_cleanup_preview",
        "step3_hard_path_validation",
        "step4_or_association",
        "step5_or_foreign_filter",
        "step6",
        "step6_mask_prep",
        "step6_directional_cut",
        "step6_finalize",
        "step6_finalize_cleanup",
        "step6_finalize_validation",
        "step6_finalize_status",
        "step7",
        "output_write",
        "visual_copy",
        "root_observability_write",
        "case_observability_write",
        "local_context_snapshot_write",
        "perf_audit_write",
    }


def test_internal_full_input_runner_gates_root_observability_flushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_resume_retry_inputs(inputs_dir)

    original_write_progress = internal_full_input_runner._write_internal_progress
    original_write_performance = internal_full_input_runner._write_internal_performance

    def _run_and_count(*, run_id: str, flush_interval_sec: float, flush_interval_cases: int) -> dict[str, int]:
        counts = {"progress": 0, "performance": 0}

        def _count_progress(*args, **kwargs):
            counts["progress"] += 1
            return original_write_progress(*args, **kwargs)

        def _count_performance(*args, **kwargs):
            counts["performance"] += 1
            return original_write_performance(*args, **kwargs)

        monkeypatch.setattr(internal_full_input_runner, "_write_internal_progress", _count_progress)
        monkeypatch.setattr(internal_full_input_runner, "_write_internal_performance", _count_performance)
        run_t03_internal_full_input(
            nodes_path=nodes_path,
            roads_path=roads_path,
            drivezone_path=drivezone_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            out_root=out_root,
            run_id=run_id,
            workers=1,
            max_cases=3,
            debug=False,
            progress_flush_interval_sec=flush_interval_sec,
            progress_flush_interval_cases=flush_interval_cases,
        )
        return counts

    gated_counts = _run_and_count(
        run_id="gated_flush_case",
        flush_interval_sec=999.0,
        flush_interval_cases=999,
    )
    eager_counts = _run_and_count(
        run_id="eager_flush_case",
        flush_interval_sec=0.0,
        flush_interval_cases=1,
    )

    assert gated_counts["progress"] == gated_counts["performance"] + 1
    assert eager_counts["progress"] == eager_counts["performance"] + 1
    assert eager_counts["progress"] > gated_counts["progress"]
    assert eager_counts["performance"] > gated_counts["performance"]


def test_internal_full_input_runner_rebuilds_closeout_from_terminal_records(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_single_case_inputs(inputs_dir)

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="streamed_closeout_case",
        workers=1,
        max_cases=1,
        debug=False,
    )

    streamed_results_path = artifacts.internal_root / "t03_streamed_case_results.jsonl"
    streamed_results_path.unlink()
    closeout_results = load_closeout_case_results(
        internal_root=artifacts.internal_root,
        run_root=artifacts.run_root,
        case_ids=list(artifacts.selected_case_ids),
    )
    assert list(closeout_results) == ["100001"]

    (artifacts.run_root / "virtual_intersection_polygons.gpkg").unlink()
    (artifacts.run_root / "nodes.gpkg").unlink()
    (artifacts.run_root / "nodes_anchor_update_audit.csv").unlink()
    (artifacts.run_root / "nodes_anchor_update_audit.json").unlink()

    shared_nodes = load_shared_nodes(nodes_path=nodes_path)
    polygons_path = write_virtual_intersection_polygons(
        run_root=artifacts.run_root,
        shared_nodes=shared_nodes,
        streamed_results=closeout_results,
    )
    nodes_outputs = write_updated_nodes_outputs(
        run_root=artifacts.run_root,
        shared_nodes=shared_nodes,
        selected_case_ids=list(artifacts.selected_case_ids),
        streamed_results=closeout_results,
        failed_case_ids=[],
    )

    polygons = read_vector_layer(polygons_path).features
    updated_nodes = read_vector_layer(nodes_outputs["nodes_path"]).features
    updated_node_map = {str(feature.properties["id"]): feature.properties.get("is_anchor") for feature in updated_nodes}

    assert len(polygons) == 1
    assert polygons[0].properties["mainnodeid"] == "100001"
    assert updated_node_map["100001"] == "yes"
    assert json.loads(nodes_outputs["audit_json_path"].read_text(encoding="utf-8"))["updated_to_yes_count"] == 1


def test_internal_full_input_runner_resume_reconstructs_streamed_results_without_review_png(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_single_case_inputs(inputs_dir)

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="resume_reconstruct_streamed_case",
        workers=1,
        max_cases=1,
        debug=False,
    )

    streamed_results_path = artifacts.internal_root / "t03_streamed_case_results.jsonl"
    streamed_results_path.unlink()

    resumed_artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="resume_reconstruct_streamed_case",
        workers=1,
        max_cases=1,
        debug=False,
        resume=True,
    )

    manifest_doc = json.loads((resumed_artifacts.internal_root / "t03_internal_full_input_manifest.json").read_text(encoding="utf-8"))
    reconstructed_streamed_results = load_streamed_case_results(streamed_results_path)
    terminal_records = load_terminal_case_records(resumed_artifacts.internal_root)

    assert manifest_doc["execution_case_ids"] == []
    assert reconstructed_streamed_results["100001"].step7_state == "accepted"
    assert reconstructed_streamed_results["100001"].source_png_path == ""
    assert terminal_records["100001"].terminal_state == "accepted"


def test_internal_full_input_runner_resume_only_executes_incomplete_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_resume_retry_inputs(inputs_dir)

    original_run_single_case_direct = internal_full_input_runner._run_single_case_direct

    def _fail_100003(*args, **kwargs):
        if kwargs.get("case_id") == "100003":
            raise RuntimeError("synthetic runtime failure")
        return original_run_single_case_direct(*args, **kwargs)

    monkeypatch.setattr(internal_full_input_runner, "_run_single_case_direct", _fail_100003)

    artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="resume_case",
        workers=1,
        max_cases=3,
        debug=False,
    )

    assert (artifacts.internal_root / "terminal_case_records" / "100003.json").is_file()
    (artifacts.internal_root / "case_progress" / "100003.json").unlink(missing_ok=True)
    (artifacts.run_root / "cases" / "100003" / "t03_case_watch_status.json").unlink(missing_ok=True)
    (artifacts.run_root / "summary.json").unlink(missing_ok=True)

    executed_case_ids: list[str] = []

    def _track_second_run(*args, **kwargs):
        executed_case_ids.append(str(kwargs["case_id"]))
        return original_run_single_case_direct(*args, **kwargs)

    monkeypatch.setattr(internal_full_input_runner, "_run_single_case_direct", _track_second_run)

    resumed_artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="resume_case",
        workers=1,
        max_cases=3,
        debug=False,
        resume=True,
    )

    summary_doc = json.loads((resumed_artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    manifest_doc = json.loads((resumed_artifacts.internal_root / "t03_internal_full_input_manifest.json").read_text(encoding="utf-8"))

    assert executed_case_ids == []
    assert manifest_doc["execution_case_ids"] == []
    assert summary_doc["step7_accepted_count"] == 1
    assert summary_doc["step7_rejected_count"] == 1
    assert summary_doc["failed_case_ids"] == ["100003"]


def test_internal_full_input_runner_retry_failed_only_executes_runtime_failed_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_resume_retry_inputs(inputs_dir)

    original_run_single_case_direct = internal_full_input_runner._run_single_case_direct

    def _fail_100003(*args, **kwargs):
        if kwargs.get("case_id") == "100003":
            raise RuntimeError("synthetic runtime failure")
        return original_run_single_case_direct(*args, **kwargs)

    monkeypatch.setattr(internal_full_input_runner, "_run_single_case_direct", _fail_100003)

    run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="retry_failed_case",
        workers=1,
        max_cases=3,
        debug=False,
    )

    retry_internal_root = out_root / "_internal" / "retry_failed_case"
    assert (retry_internal_root / "terminal_case_records" / "100003.json").is_file()
    (retry_internal_root / "case_progress" / "100003.json").unlink(missing_ok=True)
    (out_root / "retry_failed_case" / "cases" / "100003" / "t03_case_watch_status.json").unlink(missing_ok=True)
    (out_root / "retry_failed_case" / "summary.json").unlink(missing_ok=True)
    executed_case_ids: list[str] = []

    def _track_retry_run(*args, **kwargs):
        executed_case_ids.append(str(kwargs["case_id"]))
        return original_run_single_case_direct(*args, **kwargs)

    monkeypatch.setattr(internal_full_input_runner, "_run_single_case_direct", _track_retry_run)

    retried_artifacts = run_t03_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="retry_failed_case",
        workers=1,
        max_cases=3,
        debug=False,
        retry_failed=True,
    )

    summary_doc = json.loads((retried_artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    manifest_doc = json.loads((retried_artifacts.internal_root / "t03_internal_full_input_manifest.json").read_text(encoding="utf-8"))

    assert executed_case_ids == ["100003"]
    assert manifest_doc["execution_case_ids"] == ["100003"]
    assert summary_doc["step7_accepted_count"] == 2
    assert summary_doc["step7_rejected_count"] == 1
    assert summary_doc["failed_case_ids"] == []


def test_internal_full_input_bootstrap_failure_script_writes_atomic_json(tmp_path: Path) -> None:
    placeholder_root = tmp_path / "placeholder_inputs"
    placeholder_root.mkdir(parents=True, exist_ok=True)
    for file_name in ("nodes.gpkg", "roads.gpkg", "drivezone.gpkg", "rcsdroad.gpkg", "rcsdnode.gpkg"):
        (placeholder_root / file_name).write_bytes(b"placeholder")

    fake_repo_root = tmp_path / "fake_repo"
    fake_repo_root.mkdir(parents=True, exist_ok=True)
    out_root = tmp_path / "out"
    run_id = "bootstrap_atomic_failure"
    script_path = Path("/mnt/e/Work/RCSD_Topo_Poc/scripts/t03_run_internal_full_input_8workers.sh")

    env = os.environ.copy()
    env.update(
        {
            "REPO_DIR": str(fake_repo_root),
            "PYTHON_BIN": "python3",
            "NODES_PATH": str(placeholder_root / "nodes.gpkg"),
            "ROADS_PATH": str(placeholder_root / "roads.gpkg"),
            "DRIVEZONE_PATH": str(placeholder_root / "drivezone.gpkg"),
            "RCSDROAD_PATH": str(placeholder_root / "rcsdroad.gpkg"),
            "RCSDNODE_PATH": str(placeholder_root / "rcsdnode.gpkg"),
            "OUT_ROOT": str(out_root),
            "RUN_ID": run_id,
            "WORKERS": "1",
            "DEBUG_FLAG": "--no-debug",
            "REVIEW_MODE": "0",
        }
    )
    completed = subprocess.run(
        ["bash", str(script_path)],
        cwd="/mnt/e/Work/RCSD_Topo_Poc",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    internal_root = out_root / "_internal" / run_id
    progress_path = internal_root / "t03_internal_full_input_progress.json"
    failure_path = internal_root / "t03_internal_full_input_failure.json"
    bootstrap_path = internal_root / "bootstrap_failure.json"

    assert completed.returncode != 0
    for path in (progress_path, failure_path, bootstrap_path):
        assert path.is_file()
        assert path.read_text(encoding="utf-8").strip()
        json.loads(path.read_text(encoding="utf-8"))

    progress_doc = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_doc["status"] == "failed"
