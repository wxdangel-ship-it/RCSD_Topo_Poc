from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    HierarchicalTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_dataset import (
    apply_dataset_p1_scope,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_oof import (
    apply_localized_failure,
    build_dataset_p1_context_fallback,
)


def test_dataset_p1_scope_keeps_only_eligible_supervision() -> None:
    eligible = _example("case-a", "segment-a", weight=1.0)
    context = _example("case-a", "segment-b", weight=0.3)
    supervised, contexts, applications = apply_dataset_p1_scope(
        [eligible, context],
        [
            _scope(eligible, label_eligible=True, label_weight=0.7),
            _scope(context, label_eligible=False, context_weight=0.3),
        ],
    )

    assert [row.group.group_id for row in supervised] == [
        eligible.group.group_id
    ]
    assert supervised[0].group.sample_weight == 0.7
    assert [row.group.group_id for row in contexts] == [context.group.group_id]
    assert contexts[0].group.sample_weight == 0.3
    assert sum(row["scorer_metric_eligible"] for row in applications) == 1
    assert applications[1]["label_weight"] is None


def test_dataset_p1_scope_rejects_context_label_weight() -> None:
    context = _example("case-a", "segment-b", weight=0.3)
    row = _scope(
        context,
        label_eligible=False,
        label_weight=0.3,
        context_weight=0.3,
    )

    with pytest.raises(ValueError, match="retains label weight"):
        apply_dataset_p1_scope([context], [row])


def test_dataset_p1_scope_requires_exact_group_identity() -> None:
    example = _example("case-a", "segment-a", weight=1.0)
    row = _scope(example, label_eligible=True, label_weight=0.7)
    row["object_id"] = "different"

    with pytest.raises(ValueError, match="identity mismatch"):
        apply_dataset_p1_scope([example], [row])


def test_context_fallback_is_deterministic_keep_swsd() -> None:
    example = _example("case-a", "segment-a", weight=0.3)

    decision = build_dataset_p1_context_fallback(example, seed=311)

    assert decision["proposal_target"] == "KEEP_SWSD"
    assert decision["accepted"] is False
    assert decision["reason"] == "dataset_p1_context_only_fallback"
    assert decision["seed"] == 311


def test_localized_expected_failure_does_not_cascade() -> None:
    local = {
        "group_id": "local",
        "accepted": True,
        "reason": "hierarchical_carrier_accept",
    }
    neighbor = {
        "group_id": "neighbor",
        "accepted": True,
        "reason": "hierarchical_carrier_accept",
    }

    local_result = apply_localized_failure(local, failure_group_ids={"local"})
    neighbor_result = apply_localized_failure(neighbor, failure_group_ids={"local"})

    assert local_result["accepted"] is False
    assert local_result["reason"] == "dataset_p1_localized_expected_failure"
    assert neighbor_result == neighbor


def _example(case_key: str, object_id: str, *, weight: float) -> HierarchicalTrainingExample:
    candidates = (
        P1CandidateExample(
            candidate_id=f"{object_id}-keep",
            candidate_target="KEEP_SWSD",
            candidate_tokens=("keep",),
            numeric_features=(0.0,) * 8,
        ),
        P1CandidateExample(
            candidate_id=f"{object_id}-use",
            candidate_target="USE_RCSD",
            candidate_tokens=("use",),
            numeric_features=(1.0,) * 8,
        ),
    )
    group = P1GroupExample(
        case_key=case_key,
        fold=0,
        group_id=f"SCHEME_A_P1:SEGMENT:{case_key}:{object_id}",
        object_type="SEGMENT",
        object_id=object_id,
        object_tokens=("segment",),
        context_tokens=("context",),
        candidates=candidates,
        truth_index=0,
        truth_target="KEEP_SWSD",
        anomaly_target=False,
        sample_weight=weight,
        hard_unsafe=False,
    )
    return HierarchicalTrainingExample(
        group=group,
        evidence_features=(0.0, 1.0),
        auxiliary_targets=(False,) * 7,
    )


def _scope(
    example: HierarchicalTrainingExample,
    *,
    label_eligible: bool,
    label_weight: float | None = None,
    context_weight: float | None = None,
) -> dict[str, object]:
    return {
        "case_key": example.group.case_key,
        "fold": example.group.fold,
        "group_id": example.group.group_id,
        "object_id": example.group.object_id,
        "scope_class": (
            "CASE_TRUTH_LABEL" if label_eligible else "CONTEXT_ONLY_MASKED"
        ),
        "label_eligible": label_eligible,
        "scorer_metric_eligible": label_eligible,
        "label_weight": label_weight,
        "context_input_eligible": True,
        "context_input_weight": context_weight,
        "object_failure_localized": False,
    }
