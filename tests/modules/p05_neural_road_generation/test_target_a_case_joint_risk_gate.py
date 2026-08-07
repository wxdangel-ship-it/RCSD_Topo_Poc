from __future__ import annotations

from copy import deepcopy

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_risk_gate import (
    CaseJointRiskGateConfig,
    apply_case_joint_risk_gate,
    case_joint_risk_features,
    case_joint_risk_metrics,
    fit_cross_fitted_case_joint_risk_gate,
)


def _anchor(case_key: str, anchor_id: str, confidence: float) -> dict:
    return {
        "case_key": case_key,
        "anchor_id": anchor_id,
        "candidate_predicted_id": f"NODE:{anchor_id}",
        "candidate_count": 2,
        "candidate_confidence": confidence,
        "candidate_margin": confidence - (1.0 - confidence),
        "candidate_normalized_entropy": 0.5,
        "status_confidence": confidence,
        "status_margin": confidence - (1.0 - confidence),
        "status_normalized_entropy": 0.4,
        "anchor_gate_success_probability": confidence,
        "anchor_gate_margin": confidence - (1.0 - confidence),
        "joint_score": confidence,
        "no_evidence_probability": 1.0 - confidence,
    }


def _ordinary(
    fold: int,
    index: int,
    *,
    safe: bool,
    decision: str = "KEEP_SWSD",
) -> dict:
    confidence = 0.8 if safe else 0.55
    case_key = f"CASE-{fold}"
    return {
        "sample_id": f"{case_key}:{index}",
        "case_key": case_key,
        "fold": fold,
        "required_anchor_ids": [f"A-{fold}-{index}"],
        "predicted_decision": decision,
        "acceptable_decisions": [decision],
        "base_releasable": True,
        "truth_label_ready": True,
        "required_anchor_truth_ready": True,
        "joint_truth_correct": safe,
        "no_evidence_keep_exception": False,
        "plan_candidate_count": 3,
        "within_decision_candidate_count": 2,
        "predicted_plan_road_count": 1,
        "predicted_plan_member_count": 1,
        "plan_confidence": confidence,
        "plan_margin": confidence - (1.0 - confidence),
        "plan_normalized_entropy": 0.5,
        "decision_confidence": confidence,
        "decision_margin": confidence - (1.0 - confidence),
        "within_decision_confidence": confidence,
        "within_decision_margin": confidence - (1.0 - confidence),
        "within_decision_normalized_entropy": 0.4,
    }


def test_risk_features_ignore_truth_and_supervision_fields() -> None:
    row = _ordinary(0, 0, safe=True)
    anchor = _anchor("CASE-0", "A-0-0", 0.8)
    index = {("CASE-0", "A-0-0"): anchor}
    expected = case_joint_risk_features(row, anchor_by_key=index)
    changed = deepcopy(row)
    changed["truth_label_ready"] = False
    changed["joint_truth_correct"] = False
    changed["acceptable_decisions"] = ["USE_RCSD"]
    changed["preferred_decision"] = "USE_RCSD"
    altered_anchor = deepcopy(anchor)
    altered_anchor["candidate_correct"] = False
    altered_anchor["truth_success"] = False
    actual = case_joint_risk_features(
        changed,
        anchor_by_key={("CASE-0", "A-0-0"): altered_anchor},
    )
    assert actual == expected


def test_cross_fitted_risk_gate_uses_case_disjoint_scores() -> None:
    rows = []
    anchors = []
    for fold in range(3):
        for index in range(4):
            safe = index < 2
            rows.append(_ordinary(fold, index, safe=safe))
            anchors.append(
                _anchor(
                    f"CASE-{fold}",
                    f"A-{fold}-{index}",
                    0.8 if safe else 0.55,
                )
            )
    config = CaseJointRiskGateConfig(
        hidden_dim=4,
        epoch_count=20,
        seed=7,
    )
    result = fit_cross_fitted_case_joint_risk_gate(
        rows,
        anchors,
        config=config,
    )
    assert set(result.cross_fitted_scores) == {
        row["sample_id"] for row in rows
    }
    gated = apply_case_joint_risk_gate(
        rows,
        result.cross_fitted_scores,
        threshold=result.threshold,
    )
    metrics = case_joint_risk_metrics(gated)
    assert metrics["unsafe_auto_count"] == 0
    assert metrics["review_auto_count"] == 0


def test_risk_metrics_count_keep_and_use_separately() -> None:
    keep = {
        **_ordinary(0, 0, safe=True),
        "risk_accepted": True,
    }
    use = {
        **_ordinary(0, 1, safe=True, decision="USE_RCSD"),
        "risk_accepted": True,
    }
    review = {
        **_ordinary(0, 2, safe=False),
        "truth_label_ready": False,
        "risk_accepted": True,
    }
    anchor_unknown = {
        **_ordinary(0, 3, safe=False),
        "required_anchor_truth_ready": False,
        "risk_accepted": True,
    }
    metrics = case_joint_risk_metrics([keep, use, review, anchor_unknown])
    assert metrics["automatic_count"] == 4
    assert metrics["automatic_correct_count"] == 2
    assert metrics["unsafe_auto_count"] == 0
    assert metrics["review_auto_count"] == 2
    assert metrics["automatic_unverified_count"] == 2
    assert metrics["positive_keep_automatic_count"] == 1
    assert metrics["use_automatic_correct_count"] == 1
