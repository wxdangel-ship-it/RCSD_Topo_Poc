from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_joint_gate import (
    JointGateAnchorTarget,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_joint_gate_oof import (
    _anchor_release_evidence,
    _balanced_binary_weights,
    _binary_metrics,
    _masked_weighted_binary_loss,
    _release_result,
    _zero_unsafe_thresholds,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)


def test_joint_gate_binary_metrics_separate_failure_and_pass_recall() -> None:
    metrics = _binary_metrics(
        [
            {"gate_supervised": True, "gate_label": 0, "predicted_pass": False},
            {"gate_supervised": True, "gate_label": 0, "predicted_pass": True},
            {"gate_supervised": True, "gate_label": 1, "predicted_pass": True},
            {"gate_supervised": True, "gate_label": 1, "predicted_pass": False},
            {"gate_supervised": False, "gate_label": 0, "predicted_pass": True},
        ]
    )

    assert metrics["supervised_count"] == 4
    assert metrics["accuracy"] == 0.5
    assert metrics["failure_recall"] == 0.5
    assert metrics["pass_recall"] == 0.5
    assert metrics["false_positive"] == 1


def test_joint_gate_masked_loss_ignores_unknown_labels() -> None:
    logits = torch.tensor(((0.0, 1.0), (10.0, -10.0)), requires_grad=True)
    loss = _masked_weighted_binary_loss(
        logits,
        torch.tensor((1, 1)),
        torch.tensor((True, False)),
        torch.tensor((1.0, 1.0)),
        torch.ones(2),
    )

    loss.backward()

    assert logits.grad is not None
    assert logits.grad[1].abs().sum() == 0


def test_joint_gate_balanced_weights_upweight_failure_class() -> None:
    weights = _balanced_binary_weights([0, 1, 1, 1])

    assert weights[0] > weights[1]


def test_joint_release_threshold_uses_inner_rows_only() -> None:
    calibration = [
        {
            "release_group": "STANDARD",
            "release_score": 0.9,
            "raw_release_candidate": True,
            "proven_safe": True,
        },
        {
            "release_group": "STANDARD",
            "release_score": 0.7,
            "raw_release_candidate": True,
            "proven_safe": False,
        },
    ]
    held_out = [
        {
            "release_group": "STANDARD",
            "release_score": 0.99,
            "raw_release_candidate": True,
            "proven_safe": False,
            "supervised_error_candidate": True,
        }
    ]

    thresholds = _zero_unsafe_thresholds(calibration, held_out)
    result = _release_result(held_out[0], thresholds=thresholds)

    assert thresholds == {"STANDARD": 0.7}
    assert result["release_accepted"] is True
    assert result["release_supervised_error_auto"] is True


def test_anchor_release_separates_confirmed_no_evidence_from_unknown() -> None:
    anchor = JointGateAnchorTarget(
        sample_id="anchor",
        case_key="T10:case",
        anchor_id="a",
        fold=0,
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
        status_supervised=True,
        candidate_supervised=False,
        gate_label=1,
        gate_supervised=True,
        sample_weight=1.0,
    )
    evidence = _anchor_release_evidence(
        {"sample_id": "anchor", "pass_probability": 0.9},
        anchor=anchor,
        base={"predicted": "NO_EVIDENCE"},
    )

    assert evidence["proven_safe"] is True
    assert evidence["supervised_error_candidate"] is False


def test_anchor_release_keeps_unspecified_success_candidate_unverifiable() -> None:
    anchor = JointGateAnchorTarget(
        sample_id="anchor",
        case_key="T10-Error:case",
        anchor_id="621989990",
        fold=4,
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
        status_supervised=True,
        candidate_supervised=False,
        gate_label=1,
        gate_supervised=True,
        sample_weight=1.0,
    )
    evidence = _anchor_release_evidence(
        {"sample_id": "anchor", "pass_probability": 0.9},
        anchor=anchor,
        base={
            "predicted": "SUCCESS",
            "candidate_type": "ROAD",
            "candidate_confidence_score": 0.8,
        },
    )
    result = _release_result(
        evidence,
        thresholds={"SUCCESS:ROAD": 0.5},
    )

    assert evidence["proven_safe"] is False
    assert evidence["supervised_error_candidate"] is False
    assert evidence["release_score"] == 0.8
    assert result["release_unverifiable_auto"] is True
