from __future__ import annotations

import math

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_oof import (
    CaseJointCanaryConfig,
    _probability_statistics,
    apply_case_joint_no_evidence_proof,
    case_joint_metrics,
    zero_false_no_evidence_threshold,
    zero_unsafe_joint_threshold,
)


def test_probability_statistics_reports_margin_and_normalized_entropy() -> None:
    stats = _probability_statistics(torch.tensor([0.6, 0.3, 0.1]))
    assert math.isclose(stats["confidence"], 0.6, rel_tol=1e-6)
    assert math.isclose(stats["margin"], 0.3, rel_tol=1e-6)
    assert 0.0 < stats["normalized_entropy"] < 1.0

    singleton = _probability_statistics(torch.tensor([1.0]))
    assert singleton == {
        "confidence": 1.0,
        "margin": 1.0,
        "normalized_entropy": 0.0,
    }


def _ordinary(
    sample_id: str,
    *,
    score: float,
    ready: bool,
    correct: bool,
    anchor_ready: bool = True,
    releasable: bool = True,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "base_releasable": releasable,
        "predicted_decision": "USE_RCSD",
        "truth_label_ready": ready,
        "required_anchor_truth_ready": anchor_ready,
        "joint_truth_correct": correct,
        "joint_score": score,
        "plan_correct": correct,
    }


def test_zero_unsafe_threshold_treats_unverified_auto_as_unsafe() -> None:
    rows = [
        _ordinary("safe", score=0.7, ready=True, correct=True),
        _ordinary("unsafe", score=0.6, ready=True, correct=False),
        _ordinary("review", score=0.8, ready=False, correct=False),
        _ordinary(
            "blocked",
            score=0.95,
            ready=False,
            correct=False,
            releasable=False,
        ),
    ]
    threshold = zero_unsafe_joint_threshold(rows)
    assert threshold > 0.8
    assert math.isclose(
        threshold,
        math.nextafter(0.8, math.inf),
    )


def test_zero_unsafe_threshold_blocks_unknown_anchor_truth_without_error() -> None:
    rows = [
        _ordinary("safe", score=0.7, ready=True, correct=True),
        _ordinary(
            "anchor-unknown",
            score=0.8,
            ready=True,
            anchor_ready=False,
            correct=False,
        ),
    ]
    threshold = zero_unsafe_joint_threshold(rows)
    assert math.isclose(threshold, math.nextafter(0.8, math.inf))

    metrics = case_joint_metrics(
        {"anchor_rows": [], "ordinary_rows": rows},
        teacher_rows=rows,
        release_threshold=0.75,
    )
    assert metrics["joint_truth_ready_count"] == 1
    assert metrics["unsafe_auto_count"] == 0
    assert metrics["automatic_unverified_count"] == 1


def test_case_joint_metrics_separates_teacher_plan_and_safe_release() -> None:
    ordinary = [
        _ordinary("a", score=0.9, ready=True, correct=True),
        _ordinary("b", score=0.8, ready=True, correct=False),
        _ordinary("c", score=0.95, ready=False, correct=False),
    ]
    teacher = [
        {**ordinary[0], "plan_correct": True},
        {**ordinary[1], "plan_correct": True},
        {**ordinary[2], "plan_correct": False},
    ]
    anchors = [
        {
            "candidate_supervised": True,
            "candidate_correct": True,
            "prediction_inconsistent": False,
        },
        {
            "candidate_supervised": True,
            "candidate_correct": False,
            "prediction_inconsistent": True,
        },
    ]
    metrics = case_joint_metrics(
        {
            "anchor_rows": anchors,
            "ordinary_rows": ordinary,
        },
        teacher_rows=teacher,
        release_threshold=0.85,
    )
    assert metrics["anchor_object_exact"] == 0.5
    assert metrics["anchor_prediction_inconsistency_count"] == 1
    assert metrics["all_plan_exact"] == 1 / 3
    assert metrics["teacher_forced_plan_exact"] == 1.0
    assert metrics["free_plan_exact"] == 0.5
    assert metrics["automatic_count"] == 2
    assert metrics["automatic_correct_count"] == 1
    assert metrics["unsafe_auto_count"] == 0
    assert metrics["review_auto_count"] == 1
    assert math.isclose(metrics["automatic_correct_coverage"], 1 / 3)


def test_no_evidence_threshold_ignores_unknown_and_blocks_known_false() -> None:
    rows = [
        {
            "status_supervised": True,
            "status_prediction": 1,
            "status_truth": 0,
            "no_evidence_probability": 0.72,
            "no_evidence_joint_score": 0.72,
        },
        {
            "status_supervised": False,
            "status_prediction": 1,
            "status_truth": 3,
            "no_evidence_probability": 0.99,
            "no_evidence_joint_score": 0.99,
        },
    ]
    threshold = zero_false_no_evidence_threshold(rows)
    assert threshold > 0.72
    assert threshold < 0.99


def test_no_evidence_proof_releases_keep_but_never_use() -> None:
    anchor = {
        "case_key": "CASE",
        "anchor_id": "A",
        "status_prediction": 1,
        "status_truth": 1,
        "status_supervised": True,
        "no_evidence_probability": 0.9,
        "no_evidence_joint_score": 0.9,
        "base_released": False,
        "truth_success": False,
        "candidate_correct": False,
        "candidate_supervised": False,
        "prediction_inconsistent": False,
        "joint_score": 0.1,
    }
    common = {
        "case_key": "CASE",
        "required_anchor_ids": ["A"],
        "required_anchor_complete": True,
        "required_anchor_truth_ready": True,
        "required_anchor_truth_correct": False,
        "truth_label_ready": True,
        "plan_confidence": 0.95,
        "plan_correct": True,
        "joint_score": 0.1,
        "joint_truth_correct": False,
        "base_releasable": False,
    }
    result = apply_case_joint_no_evidence_proof(
        {
            "anchor_rows": [anchor],
            "ordinary_rows": [
                {
                    **common,
                    "sample_id": "KEEP",
                    "predicted_decision": "KEEP_SWSD",
                },
                {
                    **common,
                    "sample_id": "USE",
                    "predicted_decision": "USE_RCSD",
                },
            ],
        },
        threshold=0.8,
    )
    keep, use = result["ordinary_rows"]
    assert keep["base_releasable"]
    assert keep["required_anchor_truth_ready"]
    assert keep["joint_truth_correct"]
    assert keep["no_evidence_keep_exception"]
    assert math.isclose(keep["joint_score"], 0.9)
    assert not use["base_releasable"]
    assert not use["required_anchor_truth_ready"]
    assert not use["joint_truth_correct"]
    assert not use["no_evidence_keep_exception"]


def test_case_joint_canary_rejects_equal_inner_outer_fold() -> None:
    config = CaseJointCanaryConfig(outer_fold=2, inner_fold=2)
    try:
        config.validate()
    except ValueError as exc:
        assert "folds must differ" in str(exc)
    else:
        raise AssertionError("equal folds must be rejected")


def test_compatibility_auxiliary_loss_requires_compatibility_head() -> None:
    config = CaseJointCanaryConfig(
        compatibility_auxiliary_loss_weight=0.25,
    )
    try:
        config.validate()
    except ValueError as exc:
        assert "requires the compatibility head" in str(exc)
    else:
        raise AssertionError("orphan compatibility loss must be rejected")
