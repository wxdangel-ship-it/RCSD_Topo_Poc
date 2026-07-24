from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_training import (
    score_selection_rows,
)


def _candidate(candidate_id: str, target: str) -> P1CandidateExample:
    return P1CandidateExample(candidate_id, target, (), (0.0,) * 8)


def _group(
    group_id: str,
    object_type: str,
    candidates: tuple[P1CandidateExample, ...],
    truth_index: int,
) -> P1GroupExample:
    return P1GroupExample(
        case_key="T10:fixture",
        fold=0,
        group_id=group_id,
        object_type=object_type,
        object_id=group_id.rsplit(":", 1)[-1],
        object_tokens=(),
        context_tokens=(),
        candidates=candidates,
        truth_index=truth_index,
        truth_target=candidates[truth_index].candidate_target,
        anomaly_target=False,
        sample_weight=1.0,
        hard_unsafe=False,
    )


def _edge(segment_group: str, candidate_id: str, node_group: str, target: str) -> dict[str, object]:
    return {
        "segment_group_id": segment_group,
        "segment_candidate_id": candidate_id,
        "node_group_id": node_group,
        "required_node_target": target,
        "feature_uses_truth": False,
    }


def _thresholds(segment: float = 0.5, node: float = 0.5) -> dict[str, float]:
    return {
        "segment_confidence_threshold": segment,
        "node_confidence_threshold": node,
        "anomaly_threshold": 1.0,
    }


def test_node_selection_is_conditioned_on_selected_road_source() -> None:
    segment_id = "P2P1:SEGMENT:T10:fixture:s1"
    node_id = "P2P1:NODE:T10:fixture:n1"
    groups = (
        _group(
            segment_id,
            "SEGMENT",
            (_candidate("swsd", "KEEP_SWSD"), _candidate("rcsd", "USE_RCSD")),
            1,
        ),
        _group(
            node_id,
            "NODE",
            (
                _candidate("n-t01", "T01_NODE"),
                _candidate("n-proposal", "PROPOSAL_NODE"),
                _candidate("n-omit", "OMIT"),
            ),
            1,
        ),
    )
    edges = (
        _edge(segment_id, "swsd", node_id, "T01_NODE"),
        _edge(segment_id, "rcsd", node_id, "PROPOSAL_NODE"),
    )
    _, selections = score_selection_rows(
        groups,
        ((0.0, 2.0), (0.0, 1.0, 3.0)),
        ((0.1, 0.9), (0.1, 0.2, 0.7)),
        (0.0, 0.0),
        _thresholds(),
        seed=17,
        fold=0,
        model_signature="fixture",
        compatibility_edges=edges,
        junction_by_group={node_id: "junction-1"},
    )
    node = next(row for row in selections if row["object_type"] == "NODE")
    assert node["raw_selected_candidate_id"] == "n-omit"
    assert node["selected_candidate_id"] == "n-proposal"
    assert node["constraint_required_target"] == "PROPOSAL_NODE"
    assert node["confidence"] == 0.9
    assert node["accepted"] is True


def test_shared_source_conflict_forces_whole_junction_to_swsd() -> None:
    segment_a = "P2P1:SEGMENT:T10:fixture:s1"
    segment_b = "P2P1:SEGMENT:T10:fixture:s2"
    node_id = "P2P1:NODE:T10:fixture:n1"
    groups = (
        _group(segment_a, "SEGMENT", (_candidate("a-swsd", "KEEP_SWSD"), _candidate("a-rcsd", "USE_RCSD")), 0),
        _group(segment_b, "SEGMENT", (_candidate("b-swsd", "KEEP_SWSD"), _candidate("b-rcsd", "USE_RCSD")), 0),
        _group(
            node_id,
            "NODE",
            (
                _candidate("n-t01", "T01_NODE"),
                _candidate("n-proposal", "PROPOSAL_NODE"),
                _candidate("n-omit", "OMIT"),
            ),
            0,
        ),
    )
    edges = (
        _edge(segment_a, "a-swsd", node_id, "T01_NODE"),
        _edge(segment_a, "a-rcsd", node_id, "PROPOSAL_NODE"),
        _edge(segment_b, "b-swsd", node_id, "T01_NODE"),
        _edge(segment_b, "b-rcsd", node_id, "PROPOSAL_NODE"),
    )
    _, selections = score_selection_rows(
        groups,
        ((0.0, 2.0), (2.0, 0.0), (0.0, 2.0, 1.0)),
        ((0.1, 0.9), (0.9, 0.1), (0.1, 0.8, 0.1)),
        (0.0, 0.0, 0.0),
        _thresholds(),
        seed=17,
        fold=0,
        model_signature="fixture",
        compatibility_edges=edges,
        junction_by_group={node_id: "junction-1"},
    )
    segment_rows = [row for row in selections if row["object_type"] == "SEGMENT"]
    assert all(row["accepted"] is False for row in segment_rows)
    assert all(row["junction_fallback_applied"] is True for row in segment_rows)
    node = next(row for row in selections if row["object_type"] == "NODE")
    assert node["selected_candidate_id"] == "n-omit"
    assert node["structural_candidate_id"] == "n-t01"
    assert node["constraint_required_target"] == "OMIT"
    assert node["structural_target"] == "T01_NODE"
