from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_no_evidence_proof import (
    apply_no_evidence_proof,
    no_evidence_proof_metrics,
    select_zero_false_positive_threshold,
)


def _row(
    *,
    probability: float,
    label: str,
    supervised: bool = True,
) -> dict[str, object]:
    return {
        "predicted": "NO_EVIDENCE",
        "label": label,
        "gate_supervised": supervised,
        "probabilities": {"NO_EVIDENCE": probability},
    }


def test_threshold_ignores_unknown_and_excludes_known_false_proof() -> None:
    threshold = select_zero_false_positive_threshold(
        [
            _row(probability=0.8, label="NO_EVIDENCE"),
            _row(probability=0.7, label="SUCCESS"),
            _row(
                probability=0.99,
                label="ABSTAIN",
                supervised=False,
            ),
        ]
    )

    assert 0.7 < threshold < 0.8


def test_failed_proof_becomes_abstain_not_positive_keep_evidence() -> None:
    result = apply_no_evidence_proof(
        _row(probability=0.6, label="NO_EVIDENCE"),
        threshold=0.8,
    )

    assert result["predicted"] == "ABSTAIN"
    assert not result["gate_passed"]
    assert not result["no_evidence_proof_passed"]


def test_metrics_separate_unknown_from_known_false_proof() -> None:
    metrics = no_evidence_proof_metrics(
        [
            _row(probability=0.9, label="NO_EVIDENCE"),
            _row(probability=0.9, label="SUCCESS"),
            _row(
                probability=0.9,
                label="ABSTAIN",
                supervised=False,
            ),
        ],
        threshold=0.8,
    )

    assert metrics["true_proof_count"] == 1
    assert metrics["false_proof_count"] == 1
    assert metrics["unknown_proof_count"] == 1
