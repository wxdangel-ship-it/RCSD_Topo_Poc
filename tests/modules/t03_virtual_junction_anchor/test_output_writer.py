from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    CaseSpec,
    NodeRecord,
    ReviewIndexRow,
    RoadRecord,
    SemanticGroup,
    Step1Context,
    Step3CaseResult,
    Step3NegativeMasks,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    CASE_REQUIRED_OUTPUTS,
    REVIEW_INDEX_FIELDNAMES,
    write_case_outputs,
    write_review_index,
    write_summary,
)


def _build_context(case_root: Path, case_id: str = "100001") -> Step1Context:
    case_spec = CaseSpec(
        case_id=case_id,
        mainnodeid=case_id,
        case_root=case_root,
        manifest={},
        size_report={},
        input_paths={},
    )
    representative_node = NodeRecord(
        feature_index=0,
        node_id=case_id,
        mainnodeid=case_id,
        has_evd="yes",
        is_anchor="no",
        kind_2=4,
        grade_2=1,
        geometry=Point(0.0, 0.0),
    )
    road = RoadRecord(
        feature_index=0,
        road_id="road_1",
        snodeid=case_id,
        enodeid="other",
        direction=2,
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
    )
    return Step1Context(
        case_spec=case_spec,
        representative_node=representative_node,
        target_group=SemanticGroup(group_id=case_id, nodes=(representative_node,)),
        all_nodes=(representative_node,),
        foreign_groups=(),
        roads=(road,),
        rcsd_roads=(),
        rcsd_nodes=(),
        drivezone_geometry=box(-40.0, -40.0, 40.0, 40.0),
        target_road_ids=frozenset({"road_1"}),
    )


def _build_case_result(case_id: str = "100001") -> Step3CaseResult:
    return Step3CaseResult(
        case_id=case_id,
        template_class="center_junction",
        step3_state="established",
        step3_established=True,
        reason="step3_established",
        visual_review_class="V1 认可成功",
        root_cause_layer=None,
        root_cause_type=None,
        allowed_space_geometry=box(-5.0, -5.0, 15.0, 5.0),
        allowed_drivezone_geometry=box(-10.0, -10.0, 20.0, 10.0),
        negative_masks=Step3NegativeMasks(
            adjacent_junction_geometry=box(18.0, -2.0, 22.0, 2.0),
            foreign_objects_geometry=box(-22.0, -2.0, -18.0, 2.0),
            foreign_mst_geometry=box(-2.0, 18.0, 2.0, 22.0),
        ),
        key_metrics={"target_group_node_count": 1},
        audit_doc={
            "input_gate": {"passed": True, "reason": None},
            "rules": {key: {"passed": True} for key in "ABCDEFGH"},
            "adjacent_junction_cuts": [],
            "adjacent_junction_cut_suppressed": [],
            "foreign_object_masks": [],
            "foreign_mst_masks": [],
            "growth_limits": [],
            "cleanup_dependency": False,
            "must_cover_result": {"covered_node_ids": [case_id], "missing_node_ids": []},
            "blocked_directions": [],
            "review_signals": [],
            "direction_mode": "t02_direction_plus_bidirectional_junction_trace",
            "growth_order": "hard_bound_first",
            "hard_bound_first": True,
            "post_growth_safety_only": True,
            "frontier_stop_reason": [],
            "selected_road_ids": ["road_1"],
            "excluded_road_ids": [],
            "opposite_road_ids": [],
            "opposite_semantic_node_ids": [],
            "opposite_rcsdroad_ids": [],
            "opposite_side_guard_mode": "not_applicable",
            "corridor_guard_status": "not_applicable",
            "opposite_side_guard_note": None,
            "hard_path_passed": True,
            "cleanup_preview_passed": True,
            "rescue_reason": None,
            "rule_d_fallback_applied": False,
            "rule_d_fallback_distance_m": None,
            "rule_d_fallback_reason": None,
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "not_applicable",
            "double_node_bridge_in_allowed_space": False,
            "shared_two_in_two_out_node_detected": False,
            "shared_two_in_two_out_node_id": None,
            "shared_two_in_two_out_as_through_node": False,
            "frontier_interruption_skipped_by_two_in_two_out": False,
            "through_node_shared_2in2out": False,
            "through_node_break_suppressed": False,
            "allowed_area_m2": 200.0,
            "allowed_inside_drivezone_area_m2": 200.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": True,
        },
        review_signals=(),
        blocked_directions=(),
        extra_status_fields={
            "representative_node_id": case_id,
            "target_group_node_ids": [case_id],
            "foreign_group_ids": [],
            "selected_road_ids": ["road_1"],
            "excluded_road_ids": [],
            "blocked_direction_reasons": [],
            "cleanup_dependency": False,
            "direction_mode": "t02_direction_plus_bidirectional_junction_trace",
            "rule_d_fallback_applied": False,
            "rule_d_fallback_distance_m": None,
            "rule_d_fallback_reason": None,
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "not_applicable",
            "double_node_bridge_in_allowed_space": False,
            "shared_two_in_two_out_node_detected": False,
            "shared_two_in_two_out_node_id": None,
            "shared_two_in_two_out_as_through_node": False,
            "frontier_interruption_skipped_by_two_in_two_out": False,
            "through_node_shared_2in2out": False,
            "through_node_break_suppressed": False,
            "allowed_area_m2": 200.0,
            "allowed_inside_drivezone_area_m2": 200.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": True,
            "visual_review_class": "V1 认可成功",
            "root_cause_layer": None,
            "root_cause_type": None,
        },
    )


def test_output_writer_keeps_flat_dir_flat_and_fields_stable(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    context = _build_context(tmp_path / "case_root")
    case_result = _build_case_result()

    row = write_case_outputs(run_root=run_root, context=context, case_result=case_result)
    write_review_index(run_root, [row])
    write_summary(
        run_root,
        [row],
        expected_case_ids=["100001"],
        raw_case_count=1,
        default_formal_case_count=1,
        effective_case_ids=["100001"],
        failed_case_ids=[],
        rerun_cleaned_before_write=False,
    )

    case_dir = run_root / "cases" / "100001"
    for rel_path in CASE_REQUIRED_OUTPUTS:
        assert (case_dir / rel_path).is_file()
    assert (case_dir / "step3_review.png").is_file()

    flat_dir = run_root / "step3_review_flat"
    flat_entries = list(flat_dir.iterdir())
    assert flat_dir.is_dir()
    assert flat_entries == [flat_dir / "100001__established.png"]
    assert all(entry.is_file() for entry in flat_entries)
    assert not any(entry.is_dir() for entry in flat_entries)
    assert row.image_name == "100001__established.png"
    assert row.image_path == str(flat_dir / row.image_name)

    with (run_root / "step3_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        header = next(reader)
        csv_rows = list(reader)
    assert header == REVIEW_INDEX_FIELDNAMES
    assert len(csv_rows) == 1
    assert csv_rows[0][0] == "100001"
    assert csv_rows[0][4] == "100001__established.png"
    assert csv_rows[0][5] == str(flat_dir / "100001__established.png")

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary_doc["total_case_count"] == 1
    assert summary_doc["raw_case_count"] == 1
    assert summary_doc["default_formal_case_count"] == 1
    assert summary_doc["expected_case_count"] == 1
    assert summary_doc["effective_case_count"] == 1
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["step3_established_count"] == 1
    assert summary_doc["step3_review_count"] == 0
    assert summary_doc["step3_not_established_count"] == 0
    assert summary_doc["tri_state_sum"] == 1
    assert summary_doc["tri_state_sum_matches_total"] is True
    assert summary_doc["excluded_case_count"] == 0
    assert summary_doc["excluded_case_ids"] == []
    assert summary_doc["missing_case_ids"] == []
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["rerun_cleaned_before_write"] is False
    assert summary_doc["run_root"] == str(run_root)
    assert summary_doc["step3_review_flat_dir"] == str(flat_dir)


def test_output_writer_review_row_names_png_by_state(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    context = _build_context(tmp_path / "case_root", case_id="200002")
    case_result = _build_case_result(case_id="200002")
    case_result = Step3CaseResult(
        **{
            **case_result.__dict__,
            "step3_state": "review",
            "step3_established": False,
            "reason": "rule_b_node_fallback",
            "visual_review_class": "V2 业务正确但几何待修",
            "root_cause_type": "rule_b_node_fallback",
            "extra_status_fields": {
                "visual_review_class": "V2 业务正确但几何待修",
                "root_cause_layer": "step3",
                "root_cause_type": "rule_b_node_fallback",
            },
        }
    )

    row = write_case_outputs(run_root=run_root, context=context, case_result=case_result)
    assert row.image_name == "200002__review.png"


def test_output_writer_can_skip_review_png(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    context = _build_context(tmp_path / "case_root", case_id="300003")
    case_result = _build_case_result(case_id="300003")

    row = write_case_outputs(
        run_root=run_root,
        context=context,
        case_result=case_result,
        render_review_png=False,
    )

    case_dir = run_root / "cases" / "300003"
    assert not (case_dir / "step3_review.png").exists()
    assert not (run_root / "step3_review_flat").exists()
    assert row.image_name == ""
    assert row.image_path == ""
