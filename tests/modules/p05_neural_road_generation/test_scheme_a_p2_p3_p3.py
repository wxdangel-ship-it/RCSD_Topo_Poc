from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    HierarchicalTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p3_audit import (
    apply_advance_right_access_gate,
    build_access_gate_ledger,
)


def test_invalid_advance_right_access_forces_review_fallback() -> None:
    decision = _decision()
    segment = _segment(access_valid="False")

    result = apply_advance_right_access_gate(decision, segment)

    assert result["accepted"] is False
    assert result["clue_predicted"] is True
    assert result["reason"] == "advance_right_access_invalid"
    assert result["pre_gate_accepted"] is True


def test_valid_access_preserves_decision_object_and_content() -> None:
    decision = _decision()

    result = apply_advance_right_access_gate(
        decision,
        _segment(access_valid="True"),
    )

    assert result is decision


def test_standard_segment_does_not_trigger_advance_right_gate() -> None:
    decision = _decision()
    segment = _segment(access_valid="False")
    segment["segment_type"] = "STANDARD"

    result = apply_advance_right_access_gate(decision, segment)

    assert result is decision


def test_access_gate_rejects_identity_mismatch() -> None:
    segment = _segment(access_valid="False")
    segment["segment_id"] = "other"

    with pytest.raises(ValueError, match="identity mismatch"):
        apply_advance_right_access_gate(_decision(), segment)


def test_access_gate_requires_explicit_access_valid() -> None:
    segment = _segment(access_valid="False")
    del segment["access_valid"]

    with pytest.raises(ValueError, match="lacks access_valid"):
        apply_advance_right_access_gate(_decision(), segment)


def test_gate_ledger_rejects_non_review_invalid_access() -> None:
    example = _example(truth_target="KEEP_SWSD")
    inventory = {("T10:case", "advance_right_1"): _segment(access_valid="False")}

    with pytest.raises(ValueError, match="confirmed Review semantics"):
        build_access_gate_ledger([example], inventory, expected_gate_count=1)


def _decision() -> dict[str, object]:
    return {
        "seed": 311,
        "case_key": "T10:case",
        "fold": 1,
        "group_id": "SCHEME_A_P1:SEGMENT:T10:case:advance_right_1",
        "object_id": "advance_right_1",
        "accepted": True,
        "clue_predicted": False,
        "reason": "hierarchical_carrier_accept",
        "proposal_candidate_id": "candidate-use",
        "proposal_target": "USE_RCSD",
    }


def _segment(*, access_valid: str) -> dict[str, str]:
    return {
        "case_key": "T10:case",
        "segment_id": "advance_right_1",
        "segment_type": "ADVANCE_RIGHT",
        "access_valid": access_valid,
        "independent_road_valid": "True",
    }


def _example(*, truth_target: str) -> HierarchicalTrainingExample:
    candidates = (
        P1CandidateExample(
            candidate_id="candidate-keep",
            candidate_target="KEEP_SWSD",
            candidate_tokens=("keep",),
            numeric_features=(0.0,) * 8,
        ),
        P1CandidateExample(
            candidate_id="candidate-use",
            candidate_target="USE_RCSD",
            candidate_tokens=("use",),
            numeric_features=(1.0,) * 8,
        ),
    )
    group = P1GroupExample(
        case_key="T10:case",
        fold=1,
        group_id="SCHEME_A_P1:SEGMENT:T10:case:advance_right_1",
        object_type="SEGMENT",
        object_id="advance_right_1",
        object_tokens=("advance_right",),
        context_tokens=("context",),
        candidates=candidates,
        truth_index=0,
        truth_target=truth_target,
        anomaly_target=True,
        sample_weight=0.7,
        hard_unsafe=True,
    )
    return HierarchicalTrainingExample(
        group=group,
        evidence_features=(0.0, 1.0),
        auxiliary_targets=(False,) * 7,
    )
