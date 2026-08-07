from __future__ import annotations

from copy import deepcopy

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_dual_risk_gate import (
    DualRiskGateConfig,
    anchor_risk_features,
    apply_dual_risk_gate,
    fit_cross_fitted_dual_risk_gate,
    plan_risk_features,
    within_scope_percentile_scores,
    zero_unsafe_dual_thresholds,
)


def _ordinary(fold: int, index: int, *, safe: bool) -> dict:
    case_key = f"CASE-{fold}"
    confidence = 0.85 if safe else 0.55
    return {
        "sample_id": f"{case_key}:{index}",
        "case_key": case_key,
        "fold": fold,
        "required_anchor_ids": [f"A-{fold}-{index}"],
        "predicted_decision": "USE_RCSD",
        "base_releasable": True,
        "no_evidence_keep_exception": False,
        "required_anchor_truth_correct": safe,
        "truth_label_ready": True,
        "plan_correct": safe,
        "joint_truth_correct": safe,
        "plan_candidate_count": 3,
        "within_decision_candidate_count": 2,
        "predicted_plan_road_count": 1,
        "predicted_plan_member_count": 1,
        "plan_confidence": confidence,
        "plan_margin": confidence - (1.0 - confidence),
        "plan_normalized_entropy": 0.4,
        "plan_validity_head_present": True,
        "selected_plan_validity_probability": confidence,
        "selected_plan_validity_margin": confidence - 0.5,
        "selected_plan_validity_gap": confidence - (1.0 - confidence),
        "plan_validity_positive_fraction": 0.5,
        "decision_confidence": confidence,
        "decision_margin": confidence - (1.0 - confidence),
        "decision_head_agrees": True,
        "decision_head_confidence": confidence,
        "decision_head_margin": confidence - (1.0 - confidence),
        "decision_head_normalized_entropy": 0.4,
        "decision_validity_head_present": True,
        "selected_decision_validity_probability": confidence,
        "selected_decision_validity_margin": confidence - 0.5,
        "selected_decision_validity_gap": confidence - (1.0 - confidence),
        "decision_validity_positive_fraction": 0.5,
        "within_decision_confidence": confidence,
        "within_decision_margin": confidence - (1.0 - confidence),
        "within_decision_normalized_entropy": 0.4,
    }


def _primary(case_key: str, anchor_id: str, *, safe: bool) -> dict:
    confidence = 0.85 if safe else 0.55
    return {
        "case_key": case_key,
        "anchor_id": anchor_id,
        "candidate_predicted_id": f"NODE:{anchor_id}",
        "candidate_confidence": confidence,
        "candidate_margin": confidence - (1.0 - confidence),
        "candidate_normalized_entropy": 0.4,
        "status_confidence": confidence,
        "status_margin": confidence - (1.0 - confidence),
        "status_normalized_entropy": 0.4,
        "anchor_gate_success_probability": confidence,
        "joint_score": confidence,
    }


def _secondary(case_key: str, anchor_id: str, *, safe: bool) -> dict:
    confidence = 0.85 if safe else 0.55
    predicted_id = f"NODE:{anchor_id}" if safe else f"ROAD:{anchor_id}"
    return {
        "case_key": case_key,
        "anchor_id": anchor_id,
        "candidate_predicted_id": predicted_id,
        "predicted": "SUCCESS",
        "success_probability": confidence,
        "gate_pass_probability": confidence,
        "candidate_probability": confidence,
        "candidate_margin": confidence - (1.0 - confidence),
        "anchor_type_probability": confidence,
        "anchor_type_margin": confidence - (1.0 - confidence),
        "member_inclusion_margin": confidence - 0.5,
        "member_max_excluded_probability": 1.0 - confidence,
        "member_mean_entropy": 1.0 - confidence,
        "member_cardinality_residual": 1.0 - confidence,
        "member_set_mean_log_probability": -(1.0 - confidence),
    }


def test_dual_risk_features_do_not_read_truth_fields() -> None:
    row = _ordinary(0, 0, safe=True)
    primary = _primary("CASE-0", "A-0-0", safe=True)
    secondary = _secondary("CASE-0", "A-0-0", safe=True)
    primary_index = {("CASE-0", "A-0-0"): primary}
    secondary_index = {("CASE-0", "A-0-0"): secondary}
    expected_anchor = anchor_risk_features(
        row,
        primary_anchor_by_key=primary_index,
        secondary_anchor_by_key=secondary_index,
    )
    expected_plan = plan_risk_features(row)
    changed_row = deepcopy(row)
    changed_row["required_anchor_truth_correct"] = False
    changed_row["truth_label_ready"] = False
    changed_row["plan_correct"] = False
    changed_primary = deepcopy(primary)
    changed_primary["candidate_correct"] = False
    changed_secondary = deepcopy(secondary)
    changed_secondary["candidate_acceptable_exact"] = False
    assert anchor_risk_features(
        changed_row,
        primary_anchor_by_key={("CASE-0", "A-0-0"): changed_primary},
        secondary_anchor_by_key={
            ("CASE-0", "A-0-0"): changed_secondary
        },
    ) == expected_anchor
    assert plan_risk_features(changed_row) == expected_plan


def test_cross_fitted_dual_risk_gate_keeps_channels_independent() -> None:
    rows = []
    primary = []
    secondary = []
    for fold in range(3):
        for index in range(4):
            safe = index < 2
            case_key = f"CASE-{fold}"
            anchor_id = f"A-{fold}-{index}"
            rows.append(_ordinary(fold, index, safe=safe))
            primary.append(_primary(case_key, anchor_id, safe=safe))
            secondary.append(_secondary(case_key, anchor_id, safe=safe))
    result = fit_cross_fitted_dual_risk_gate(
        rows,
        primary,
        secondary,
        config=DualRiskGateConfig(
            epoch_count=20,
            seed=11,
        ),
    )
    gated = apply_dual_risk_gate(
        rows,
        anchor_scores=result.anchor_scores,
        plan_scores=result.plan_scores,
        anchor_threshold=result.anchor_threshold,
        plan_threshold=result.plan_threshold,
    )
    assert all(
        not row["risk_accepted"] or row["joint_truth_correct"]
        for row in gated
    )
    assert all(
        "anchor_risk_score" in row and "plan_risk_score" in row
        for row in gated
    )


def test_joint_threshold_search_uses_independent_vetoes() -> None:
    safe = _ordinary(0, 0, safe=True)
    anchor_unsafe = {
        **_ordinary(0, 1, safe=False),
        "plan_correct": True,
    }
    plan_unsafe = {
        **_ordinary(0, 2, safe=False),
        "required_anchor_truth_correct": True,
    }
    rows = [safe, anchor_unsafe, plan_unsafe]
    anchor_scores = {
        safe["sample_id"]: 0.9,
        anchor_unsafe["sample_id"]: 1.0,
        plan_unsafe["sample_id"]: 0.4,
    }
    plan_scores = {
        safe["sample_id"]: 0.9,
        anchor_unsafe["sample_id"]: 0.4,
        plan_unsafe["sample_id"]: 1.0,
    }
    thresholds = zero_unsafe_dual_thresholds(
        rows,
        anchor_scores=anchor_scores,
        plan_scores=plan_scores,
    )
    gated = apply_dual_risk_gate(
        rows,
        anchor_scores=anchor_scores,
        plan_scores=plan_scores,
        anchor_threshold=thresholds["anchor_threshold"],
        plan_threshold=thresholds["plan_threshold"],
    )
    accepted = [row for row in gated if row["risk_accepted"]]
    assert [row["sample_id"] for row in accepted] == [safe["sample_id"]]


def test_scope_percentiles_are_scale_invariant_and_preserve_ties() -> None:
    rows = [
        _ordinary(0, 0, safe=True),
        _ordinary(0, 1, safe=True),
        _ordinary(0, 2, safe=False),
    ]
    scores = {
        rows[0]["sample_id"]: 10.0,
        rows[1]["sample_id"]: 10.0,
        rows[2]["sample_id"]: 5.0,
    }
    percentiles = within_scope_percentile_scores(
        rows,
        scores,
        scope_builder=lambda row: (str(row["case_key"]),),
    )
    assert percentiles[rows[0]["sample_id"]] == 1.0
    assert percentiles[rows[1]["sample_id"]] == 1.0
    assert percentiles[rows[2]["sample_id"]] == 1 / 3
