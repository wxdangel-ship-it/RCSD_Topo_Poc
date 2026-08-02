from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationContext,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    write_case_outputs as write_step3_case_outputs,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import (
    build_step1_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import (
    classify_step2_template,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import (
    build_step3_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    build_step7_result,
)


REAL_T03_ROOT = Path("/mnt/e/TestData/POC_Data/T03")
REAL_T03_ERROR_ROOT = Path("/mnt/e/TestData/POC_Data/T03_Error")
REAL_QA_T03_ERROR_ROOT = Path("/mnt/e/TestData/POC_QA/T03_Error")


def _run_case(case_root: Path, case_id: str, tmp_path: Path):
    if not (case_root / case_id).is_dir():
        pytest.skip(f"missing real T03 case: {case_root / case_id}")

    specs, _ = load_case_specs(
        case_root=case_root,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    step1_context = build_step1_context(specs[0])
    template_result = classify_step2_template(step1_context)
    step3_result = build_step3_case_result(step1_context, template_result)
    step3_root = tmp_path / "step3"
    write_step3_case_outputs(
        run_root=step3_root,
        context=step1_context,
        case_result=step3_result,
    )

    association_specs, _ = load_association_case_specs(
        case_root=case_root,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(
        case_spec=association_specs[0],
        step3_root=step3_root,
    )
    association_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)
    return step1_context, step3_result, step6_result, step7_result


@pytest.mark.parametrize("case_id", ["954218", "991380"])
def test_shape_metrics_do_not_reject_when_all_hard_constraints_pass(
    case_id: str,
    tmp_path: Path,
) -> None:
    _step1, _step3, step6, step7 = _run_case(
        REAL_T03_ROOT,
        case_id,
        tmp_path,
    )

    validation = step6.audit_doc["validation"]
    assert validation["semantic_junction_cover_ok"] is True
    assert validation["required_rc_cover_ok"] is True
    assert validation["within_legal_space_ok"] is True
    assert validation["within_direction_boundary_ok"] is True
    assert validation["foreign_exclusion_ok"] is True
    assert step6.geometry_established is True
    assert step7.step7_state == "accepted"
    regularization = step6.audit_doc["assembly"]["surface_regularization"]
    assert regularization["applied"] is True
    assert regularization["forced_single_polygon"] is False


def test_alias_pair_straight_chord_is_audit_only_when_real_carrier_is_covered(
    tmp_path: Path,
) -> None:
    _step1, _step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "1189482",
        tmp_path,
    )

    validation = step6.audit_doc["validation"]
    assert validation["required_rc_node_cover_ratio"] == pytest.approx(1.0)
    assert validation["required_rc_line_cover_ratio"] >= 0.999
    assert validation["semantic_intra_rcsdnode_line_count"] == 3
    assert validation["semantic_intra_rcsdnode_line_hard_gate"] is False
    assert validation["semantic_intra_rcsdnode_line_cover_ratio"] < 1.0
    assert step6.geometry_established is True
    assert step7.step7_state == "accepted"
    assert "semantic_alias_chord_not_fully_covered" in step6.review_signals


def test_area_only_numeric_residue_does_not_reject_legal_surface(
    tmp_path: Path,
) -> None:
    _step1, _step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "503529588",
        tmp_path,
    )

    validation = step6.audit_doc["validation"]
    assert validation["legal_escape_area_m2"] > 0.0
    assert (
        validation["legal_escape_area_m2"]
        <= validation["legal_escape_area_tolerance_m2"]
    )
    assert validation["within_legal_space_ok"] is True
    assert step6.geometry_established is True
    assert step7.step7_state == "accepted"


def test_invalid_drivezone_that_blocks_constraints_has_explicit_reason(
    tmp_path: Path,
) -> None:
    step1, _step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "950770",
        tmp_path,
    )

    assert step1.drivezone_input_audit["invalid_feature_count"] > 0
    assert step1.drivezone_input_audit["raw_union_valid"] is True
    assert step1.drivezone_input_audit["normalization_applied"] is False
    assert (
        step1.drivezone_input_audit[
            "invalid_features_absorbed_by_valid_raw_union"
        ]
        is True
    )
    assert step6.geometry_established is False
    assert step6.reason == "step6_input_geometry_invalid_blocks_constraint_validation"
    assert step6.audit_doc["input_geometry"]["silent_fix"] is False
    assert step7.step7_state == "rejected"


def test_valid_raw_union_does_not_create_false_repair_dependency(
    tmp_path: Path,
) -> None:
    step1, _step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "30899925",
        tmp_path,
    )

    assert step1.drivezone_input_audit["invalid_feature_count"] == 2
    assert step1.drivezone_input_audit["raw_union_valid"] is True
    assert step1.drivezone_input_audit["normalization_applied"] is False
    assert step6.extra_status_fields["input_geometry_repair_dependency"] is False
    assert step6.geometry_established is True
    assert step6.extra_status_fields["business_connectivity_equivalent"] is True
    assert step7.step7_state == "accepted"


def test_invalid_raw_union_normalization_audits_polygon_component_delta(
    tmp_path: Path,
) -> None:
    step1, _step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "1617284",
        tmp_path,
    )

    audit = step1.drivezone_input_audit
    assert audit["normalization_applied"] is True
    assert audit["raw_union_valid"] is False
    assert audit["normalized_valid"] is True
    assert audit["raw_union_polygon_component_count"] == 1
    assert audit["normalized_polygon_component_count"] == 1
    assert audit["normalization_polygon_component_delta"] == 0
    assert audit["normalization_area_delta_m2"] == pytest.approx(0.0)
    assert audit["source_modified"] is False
    assert audit["silent_fix"] is False
    assert step6.geometry_established is True
    assert step7.step7_state == "accepted"


def test_frozen_step3_bridge_conflict_has_specific_reject_reason(
    tmp_path: Path,
) -> None:
    _step1, step3, step6, step7 = _run_case(
        REAL_T03_ERROR_ROOT,
        "991243",
        tmp_path,
    )

    assert step3.extra_status_fields["two_node_t_bridge_applied"] is True
    assert step6.geometry_established is False
    assert (
        step6.reason
        == "step6_step3_two_node_bridge_not_realizable_in_frozen_allowed_space"
    )
    assert step6.extra_status_fields["target_node_connection_cover_ratio"] < 0.98
    assert step7.step7_state == "rejected"


def test_raw_multi_component_unmatched_support_reject_is_business_rule(
    tmp_path: Path,
) -> None:
    _step1, _step3, step6, step7 = _run_case(
        REAL_T03_ROOT,
        "520394575",
        tmp_path,
    )

    assert step6.geometry_established is False
    assert step6.reason == "step6_blocked_by_association"
    assert step6.extra_status_fields["association_reason"] == (
        "association_raw_multi_component_unmatched_support"
    )
    raw_guard = step6.extra_status_fields["raw_topology_guard_audit"]
    assert raw_guard["blocked"] is True
    assert raw_guard["unmatched_support"] is True
    assert step7.step7_state == "rejected"


@pytest.mark.parametrize(
    "case_id",
    [
        "768683",
        "830724",
        "952797",
        "992932",
        "1049277",
        "520394575",
        "622700016",
    ],
)
def test_qa_snapshot_generalized_false_reject_targets_are_accepted(
    case_id: str,
    tmp_path: Path,
) -> None:
    _step1, step3, step6, step7 = _run_case(
        REAL_QA_T03_ERROR_ROOT,
        case_id,
        tmp_path,
    )

    assert step3.step3_state in {"established", "review"}
    assert step6.geometry_established is True
    assert step7.step7_state == "accepted"


def test_qa_center_junction_uses_confirmed_two_metre_surface_access(
    tmp_path: Path,
) -> None:
    _step1, step3, step6, step7 = _run_case(
        REAL_QA_T03_ERROR_ROOT,
        "952797",
        tmp_path,
    )

    assert step3.extra_status_fields["target_edge_touch_enabled"] is True
    assert step3.extra_status_fields["target_edge_touch_tolerance_m"] == 2.0
    assert step6.extra_status_fields["target_edge_touch_enabled"] is True
    assert step6.extra_status_fields["target_node_access_cover_ratio"] == 1.0
    assert step7.step7_state == "accepted"


@pytest.mark.parametrize(
    "case_id",
    [
        "787617",
        "823840",
        "867264",
        "950770",
        "991243",
        "994202",
        "995764",
        "1056150",
        "1071119",
        "522008569",
        "522806716",
    ],
)
def test_qa_snapshot_residual_reject_targets_remain_rejected(
    case_id: str,
    tmp_path: Path,
) -> None:
    _step1, _step3, step6, step7 = _run_case(
        REAL_QA_T03_ERROR_ROOT,
        case_id,
        tmp_path,
    )

    assert step6.geometry_established is False
    assert step7.step7_state == "rejected"
