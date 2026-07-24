from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_evidence import (
    _compatibility_index,
    _compatibility_stats,
    _road_stats,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_audit import (
    _deterministic_probe_results,
    _examples_aligned_to_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_models import (
    SafetyEvidenceExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_probe import (
    LinearRiskProbe,
    ShallowRiskProbe,
    decision_rows,
    select_zero_error_threshold,
)


def _example(
    key: str,
    *,
    correct: bool = True,
    anomaly: bool = False,
    hard_unsafe: bool = False,
    proposal_target: str = "USE_RCSD",
) -> SafetyEvidenceExample:
    return SafetyEvidenceExample(
        case_key=f"case:{key}",
        fold=0,
        group_id=f"group:{key}",
        object_id=f"object:{key}",
        proposal_candidate_id=f"proposal:{key}",
        proposal_target=proposal_target,
        truth_candidate_id=f"proposal:{key}" if correct else f"truth:{key}",
        truth_target="USE_RCSD" if correct else "KEEP_SWSD",
        features=(0.0, 1.0),
        candidate_agreement=True,
        hard_unsafe=hard_unsafe,
        proposal_correct=correct,
        anomaly_target=anomaly,
        review_target=proposal_target == "REVIEW_FALLBACK",
    )


def test_zero_error_threshold_uses_inner_unsafe_only() -> None:
    examples = [_example("safe"), _example("wrong", correct=False), _example("anomaly", anomaly=True)]
    threshold = select_zero_error_threshold(examples, [0.10, 0.30, 0.20])
    assert threshold == 0.20
    rows = decision_rows(examples, [0.10, 0.30, 0.20], threshold=threshold)
    assert [row["accepted"] for row in rows] == [True, False, False]


def test_probe_never_reselects_candidate_and_respects_hard_fallback() -> None:
    examples = [
        _example("safe"),
        _example("hard", hard_unsafe=True),
        _example("review", proposal_target="REVIEW_FALLBACK"),
    ]
    rows = decision_rows(examples, [0.01, 0.01, 0.01], threshold=0.10)
    assert rows[0]["proposal_candidate_id"] == examples[0].proposal_candidate_id
    assert rows[0]["accepted"] is True
    assert rows[1]["accepted"] is False
    assert rows[1]["reason"] == "hard_unsafe"
    assert rows[2]["accepted"] is False
    assert rows[2]["reason"] == "review_proposal"


def test_road_graph_evidence_reports_branch_and_imbalance_without_coordinates() -> None:
    graph = _road_stats([("a", "b"), ("b", "c"), ("b", "d")])
    assert graph["nodes"] == {"a", "b", "c", "d"}
    assert len(graph["stats"]) == 10
    assert graph["stats"][5] > 0.0
    assert graph["stats"][8] > 0.0


def test_compatibility_evidence_exposes_shared_opposite_target_pressure() -> None:
    edges = [
        {
            "segment_group_id": "s1",
            "segment_candidate_id": "p1",
            "node_group_id": "n1",
            "required_node_target": "PROPOSAL_NODE",
        },
        {
            "segment_group_id": "s2",
            "segment_candidate_id": "p2",
            "node_group_id": "n1",
            "required_node_target": "T01_NODE",
        },
    ]
    stats = _compatibility_stats(_compatibility_index(edges), "s1", "p1")
    assert len(stats) == 8
    assert stats[4] == 1.0
    assert stats[6] == 1.0


def test_preregistered_probe_parameter_scale_is_below_limit() -> None:
    linear = LinearRiskProbe(256)
    shallow = ShallowRiskProbe(256, 64)
    assert sum(parameter.numel() for parameter in linear.parameters()) < 100_000
    assert sum(parameter.numel() for parameter in shallow.parameters()) < 100_000


def test_global_metric_alignment_follows_decision_group_order() -> None:
    first = _example("first")
    second = _example("second", correct=False)
    rows = [{"group_id": second.group_id}, {"group_id": first.group_id}]
    aligned = _examples_aligned_to_rows([first, second], rows)
    assert [example.group_id for example in aligned] == [second.group_id, first.group_id]


def test_determinism_payload_excludes_training_wall_time() -> None:
    left = [{"probe": "LINEAR", "fold_metrics": [{"held_out_fold": 0, "training_wall_seconds": 1.0}]}]
    right = [{"probe": "LINEAR", "fold_metrics": [{"held_out_fold": 0, "training_wall_seconds": 9.0}]}]
    assert _deterministic_probe_results(left) == _deterministic_probe_results(right)
