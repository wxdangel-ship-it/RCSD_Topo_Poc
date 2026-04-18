from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import (
    ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    ROOT_CAUSE_LAYER_STEP4,
    VISUAL_V1,
    VISUAL_V2,
    VISUAL_V4,
    VISUAL_V5,
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_result,
    build_step6_status_doc,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import Step67Context
from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_center_case_a,
    build_center_case_b,
    build_single_sided_parallel_support_case,
    write_step3_prerequisite,
)


def _run_case(case_root: Path, step3_root: Path, case_id: str) -> tuple[Step67Context, object, object]:
    specs, _ = load_step45_case_specs(
        case_root=case_root,
        case_ids=[case_id],
        exclude_case_ids=["922217", "54265667", "502058682"],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)
    return step67_context, step6_result, step7_result


def _road_covered_length(step67_context: Step67Context, step6_result: object, road_id: str) -> float:
    road = next(
        road
        for road in step67_context.step45_context.step1_context.roads
        if road.road_id == road_id
    )
    geometry = step6_result.output_geometries.polygon_final_geometry
    if geometry is None:
        return 0.0
    return road.geometry.intersection(geometry).length


def test_step67_accepts_case_a_when_step6_is_clean(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")

    step67_context, step6_result, step7_result = _run_case(case_root, step3_root, "100001")

    status_doc = build_step6_status_doc(step67_context, step6_result)
    assert step6_result.geometry_established is True
    assert status_doc["semantic_junction_cover_ok"] is True
    assert status_doc["required_rc_cover_ok"] is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1
    assert step7_result.root_cause_layer is None
    assert step6_result.audit_doc["assembly"]["directional_cut_rule"]["mode"] == "directional_selected_road_cut"
    assert step6_result.audit_doc["assembly"]["direction_boundary_hard_cap_applied"] is True
    assert step6_result.audit_doc["validation"]["required_rc_cover_mode"] == "local_required_rc_within_direction_boundary"
    assert _road_covered_length(step67_context, step6_result, "road_h") <= 38.0
    assert _road_covered_length(step67_context, step6_result, "road_v") <= 38.0


def test_step67_accepts_step45_support_only_cases_after_step6_convergence(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100002")

    _step67_context, step6_result, step7_result = _run_case(case_root, step3_root, "100002")

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1
    assert step7_result.root_cause_layer is None
    assert step7_result.reason == "step67_accepted_after_support_only_convergence"
    branch_rows = step6_result.audit_doc["assembly"]["directional_cut_branches"]
    assert any(row["window_mode"] == "cut_at_20m" for row in branch_rows)
    assert any(row["preserve_candidate_boundary"] for row in branch_rows)
    assert step6_result.extra_status_fields["within_direction_boundary_ok"] is True
    assert _road_covered_length(_step67_context, step6_result, "road_h") <= 41.0
    assert _road_covered_length(_step67_context, step6_result, "road_v") <= 26.0


def test_step67_keeps_visual_v2_as_visual_audit_only_when_geometry_is_risky(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100004")

    step67_context, step6_result, _step7_result = _run_case(case_root, step3_root, "100004")
    risky_step6 = replace(
        step6_result,
        problem_geometry=True,
        review_signals=("polygon_has_holes",),
    )
    risky_step7 = build_step7_result(step67_context, risky_step6)

    assert risky_step7.step7_state == "accepted"
    assert risky_step7.visual_review_class == VISUAL_V2
    assert risky_step7.root_cause_layer == ROOT_CAUSE_LAYER_STEP4 or risky_step7.root_cause_layer == "step6"
    assert risky_step7.reason == "step67_accepted_with_visual_risk"


def test_step67_rejects_cases_blocked_by_upstream_step45(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100003")
    write_step3_prerequisite(
        step3_root,
        "100003",
        template_class="center_junction",
        selected_road_ids=[],
    )

    _step67_context, step6_result, step7_result = _run_case(case_root, step3_root, "100003")

    assert step6_result.geometry_established is False
    assert step7_result.step7_state == "rejected"
    assert step7_result.visual_review_class == VISUAL_V5
    assert step7_result.root_cause_layer == ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT


def test_step67_single_sided_case_applies_directional_cut_before_rejecting(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_single_sided_parallel_support_case(case_root, step3_root, case_id="100006")

    _step67_context, step6_result, step7_result = _run_case(case_root, step3_root, "100006")

    assert step6_result.audit_doc["assembly"]["directional_cut_rule"]["mode"] == "directional_selected_road_cut"
    assert step6_result.audit_doc["assembly"]["directional_cut_rule"]["branch_count"] >= 1
    assert any(
        row["window_mode"] in {"cut_at_20m", "preserve_candidate_boundary"}
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    )
    assert step7_result.step7_state == "rejected"
    assert step7_result.visual_review_class in {VISUAL_V4, VISUAL_V5}
