from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_models import (
    SchemeAP2P2P1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_oof import (
    build_joint_safety_selections,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_training import (
    safety_decision_rows,
    select_safety_threshold,
)


def _candidate(candidate_id: str, target: str) -> P1CandidateExample:
    return P1CandidateExample(candidate_id, target, (f"OPTION:{target}",), (0.0,) * 21)


def _group(
    group_id: str,
    *,
    case_key: str = "T10:test",
    object_type: str = "SEGMENT",
    truth_index: int = 0,
    truth_target: str = "KEEP_SWSD",
    anomaly_target: bool = False,
    candidates: tuple[P1CandidateExample, ...] | None = None,
) -> P1GroupExample:
    values = candidates or (_candidate("keep", "KEEP_SWSD"), _candidate("use", "USE_RCSD"))
    return P1GroupExample(
        case_key=case_key,
        fold=0,
        group_id=group_id,
        object_type=object_type,
        object_id=group_id,
        object_tokens=(f"OBJECT:{object_type}",),
        context_tokens=("CONTEXT:TEST",),
        candidates=values,
        truth_index=truth_index,
        truth_target=truth_target,
        anomaly_target=anomaly_target,
        sample_weight=1.0,
        hard_unsafe=False,
    )


def test_config_rejects_invalid_seed_contract() -> None:
    kwargs = dict(
        dataset_run_root=Path("dataset"),
        base_oof_run_a=Path("a"),
        base_oof_run_b=Path("b"),
        p2_p2_p0_run_root=Path("p0"),
        output_root=Path("out"),
        run_id="run",
    )
    with pytest.raises(ValueError, match="three unique base seeds"):
        SchemeAP2P2P1Config(**kwargs, base_seeds=(17, 29))
    with pytest.raises(ValueError, match="non-empty and unique"):
        SchemeAP2P2P1Config(**kwargs, safety_seeds=(101, 101))


def test_safety_head_can_only_accept_or_abstain() -> None:
    group = _group("segment", truth_index=1, truth_target="USE_RCSD")
    proposals = {
        "segment": {"candidate_id": "use", "candidate_target": "USE_RCSD"}
    }
    decisions, _ = safety_decision_rows(
        [group],
        [[3.0, 1.0]],
        [[0.88, 0.12]],
        [0.05],
        proposals=proposals,
        risk_threshold=0.0,
    )
    row = decisions[0]
    assert row["accepted"] is False
    assert row["reason"] == "safety_candidate_disagreement"
    assert row["proposal_candidate_id"] == "use"
    assert row["safety_candidate_id"] == "keep"
    assert row["decision"] == "FALLBACK"


def test_inner_threshold_rejects_all_observed_unsafe_rows() -> None:
    correct = _group("correct", truth_index=1, truth_target="USE_RCSD")
    wrong = _group("wrong", truth_index=0, truth_target="KEEP_SWSD", anomaly_target=True)
    proposals = {
        "correct": {"candidate_id": "use", "candidate_target": "USE_RCSD"},
        "wrong": {"candidate_id": "use", "candidate_target": "USE_RCSD"},
    }
    threshold = select_safety_threshold(
        [correct, wrong],
        [[0.0, 3.0], [0.0, 2.0]],
        [[0.1, 0.9], [0.3, 0.7]],
        [0.05, 0.10],
        proposals=proposals,
    )
    assert threshold["inner_accepted_wrong_count"] == 0
    assert threshold["inner_unsafe_fallback_recall"] == 1.0
    assert threshold["risk_threshold"] > 0.7


def test_node_truth_is_conditioned_on_effective_segment_carrier() -> None:
    segment = _group("segment", truth_index=1, truth_target="USE_RCSD")
    node = _group(
        "node",
        object_type="NODE",
        truth_index=1,
        truth_target="PROPOSAL_NODE",
        candidates=(
            _candidate("t01", "T01_NODE"),
            _candidate("proposal", "PROPOSAL_NODE"),
            _candidate("omit", "OMIT"),
        ),
    )
    decision = {
        "group_id": "segment",
        "proposal_candidate_id": "use",
        "proposal_target": "USE_RCSD",
        "accepted": False,
        "risk": 0.1,
        "safety_probability": 0.8,
        "anomaly_probability": 0.2,
        "reason": "safety_risk_threshold",
        "model_signature": "model",
    }
    edges = [
        {
            "segment_group_id": "segment",
            "segment_candidate_id": "keep",
            "node_group_id": "node",
            "required_node_target": "T01_NODE",
        },
        {
            "segment_group_id": "segment",
            "segment_candidate_id": "use",
            "node_group_id": "node",
            "required_node_target": "PROPOSAL_NODE",
        },
    ]
    rows, closure = build_joint_safety_selections(
        [segment, node],
        [decision],
        compatibility_edges=edges,
        labels={"node": {"junction_key": "junction"}},
        node_scores={"node": {"t01": 1.0, "proposal": 2.0, "omit": 0.0}},
        seed=101,
    )
    node_row = next(row for row in rows if row["object_type"] == "NODE")
    assert node_row["selected_target"] == "T01_NODE"
    assert node_row["constraint_required_target"] == "T01_NODE"
    assert closure["node_target_mismatch_count"] == 0
    assert closure["node_original_truth_divergence_count"] == 1


def test_missing_required_node_candidate_only_allows_expected_failure() -> None:
    segment = _group("segment")
    node = _group(
        "node",
        object_type="NODE",
        case_key="T10:expected",
        truth_index=0,
        truth_target="OMIT",
        candidates=(_candidate("omit", "OMIT"),),
    )
    decision = {
        "group_id": "segment",
        "proposal_candidate_id": "keep",
        "proposal_target": "KEEP_SWSD",
        "accepted": True,
        "risk": 0.9,
        "safety_probability": 0.9,
        "anomaly_probability": 0.0,
        "reason": "safety_head_passed",
        "model_signature": "model",
    }
    edge = {
        "segment_group_id": "segment",
        "segment_candidate_id": "keep",
        "node_group_id": "node",
        "required_node_target": "T01_NODE",
    }
    with pytest.raises(ValueError, match="required Node candidate remains missing"):
        build_joint_safety_selections(
            [segment, node],
            [decision],
            compatibility_edges=[edge],
            labels={"node": {"junction_key": "junction"}},
            node_scores={"node": {"omit": 0.0}},
            seed=101,
        )
    rows, _ = build_joint_safety_selections(
        [segment, node],
        [decision],
        compatibility_edges=[edge],
        labels={"node": {"junction_key": "junction"}},
        node_scores={"node": {"omit": 0.0}},
        expected_failure_cases={"T10:expected"},
        seed=101,
    )
    assert next(row for row in rows if row["object_type"] == "NODE")["selected_target"] == "OMIT"
