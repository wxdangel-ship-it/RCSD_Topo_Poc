from __future__ import annotations

import math

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_CARRIER_MODEL_GO_CLUE_BLOCKED,
    DECISION_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED,
    DECISION_PROMOTION_MODEL_NO_GO,
    choose_p9_decision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_source import (
    EncodedSourceRow,
    build_source_fold_transform,
    encode_source_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_training import (
    CarrierSourceResidualAdapter,
    score_source_treatment,
)


def test_source_transform_uses_train_cases_and_unknown_bucket() -> None:
    rows = [
        _source_row("train", "g1", [{"association_class": "A"}]),
        _source_row("held", "g2", [{"association_class": "HELD_ONLY"}]),
    ]
    transform = build_source_fold_transform(
        rows,
        fields=("association_class",),
        train_case_keys=("train",),
    )
    assert "association_class:A" in transform.feature_names
    assert "association_class:HELD_ONLY" not in transform.feature_names
    encoded = {
        row.group_id: row for row in encode_source_rows(rows, transform)
    }
    unknown_index = transform.feature_names.index(
        "association_class:<UNKNOWN>"
    )
    assert encoded["g2"].values[unknown_index] == 1.0


def test_source_encoder_pools_multiple_facts_and_preserves_no_source_zero() -> None:
    rows = [
        _source_row(
            "train",
            "g1",
            [
                {"required_rcsdroad_count": 0},
                {"required_rcsdroad_count": 3},
            ],
        ),
        {
            "case_key": "train",
            "group_id": "g2",
            "source_applicable": False,
            "source_count": 0,
            "source_facts": [],
        },
    ]
    transform = build_source_fold_transform(
        rows,
        fields=("required_rcsdroad_count",),
        train_case_keys=("train",),
    )
    encoded = {
        row.group_id: row for row in encode_source_rows(rows, transform)
    }
    assert transform.fact_dimension == 2
    assert encoded["g1"].values == (
        1.0,
        math.log1p(3.0) / 2.0,
        1.0,
        math.log1p(3.0),
    )
    assert encoded["g2"].values == (0.0, 0.0, 0.0, 0.0)


def test_merge_diverge_context_is_direction_invariant() -> None:
    rows = [
        _source_row("train", "merge", [{"junction_type": "merge"}]),
        _source_row("train", "diverge", [{"junction_type": "diverge"}]),
    ]
    transform = build_source_fold_transform(
        rows,
        fields=("junction_type",),
        train_case_keys=("train",),
    )
    assert transform.feature_names.count(
        "junction_type:MERGE_DIVERGE_CONTEXT"
    ) == 1
    encoded = encode_source_rows(rows, transform)
    assert encoded[0].values == encoded[1].values


def test_no_source_treatment_reuses_control_row_exactly() -> None:
    control = _control_score("g1")
    adapter = CarrierSourceResidualAdapter(
        source_dim=4,
        hidden_dim=8,
        bottleneck_dim=4,
        dropout=0.0,
    )
    source = {
        "g1": EncodedSourceRow(
            group_id="g1",
            case_key="case",
            source_applicable=False,
            values=(0.0, 0.0, 0.0, 0.0),
        )
    }
    treatment = score_source_treatment(
        [control],
        adapter,
        source,
        device=torch.device("cpu"),
    )
    assert treatment == [control]


def test_source_adapter_changes_carrier_only() -> None:
    control = _control_score("g1")
    adapter = CarrierSourceResidualAdapter(
        source_dim=4,
        hidden_dim=8,
        bottleneck_dim=4,
        dropout=0.0,
    )
    source = {
        "g1": EncodedSourceRow(
            group_id="g1",
            case_key="case",
            source_applicable=True,
            values=(1.0, 0.0, 0.0, 1.0),
        )
    }
    treatment = score_source_treatment(
        [control],
        adapter,
        source,
        device=torch.device("cpu"),
    )[0]
    assert treatment["clue_probability"] == control["clue_probability"]
    assert (
        treatment["auxiliary_probabilities"]
        == control["auxiliary_probabilities"]
    )
    assert (
        treatment["candidate_correctness_probabilities"]
        == control["candidate_correctness_probabilities"]
    )
    assert parameter_count(adapter) < 300_000


def test_p9_decision_matrix() -> None:
    assert (
        choose_p9_decision(
            audit_gate=False,
            promotion_gate=True,
            full_carrier_gate=True,
        )
        == DECISION_AUDIT_NO_GO
    )
    assert (
        choose_p9_decision(
            audit_gate=True,
            promotion_gate=False,
            full_carrier_gate=True,
        )
        == DECISION_PROMOTION_MODEL_NO_GO
    )
    assert (
        choose_p9_decision(
            audit_gate=True,
            promotion_gate=True,
            full_carrier_gate=False,
        )
        == DECISION_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED
    )
    assert (
        choose_p9_decision(
            audit_gate=True,
            promotion_gate=True,
            full_carrier_gate=True,
        )
        == DECISION_CARRIER_MODEL_GO_CLUE_BLOCKED
    )


def _source_row(
    case_key: str,
    group_id: str,
    facts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "case_key": case_key,
        "group_id": group_id,
        "source_applicable": True,
        "source_count": len(facts),
        "source_facts": facts,
    }


def _control_score(group_id: str) -> dict[str, object]:
    return {
        "case_key": "case",
        "fold": 0,
        "group_id": group_id,
        "object_id": "segment",
        "candidate_ids": ["keep", "use"],
        "candidate_targets": ["KEEP_SWSD", "USE_RCSD"],
        "candidate_scores": [0.2, 0.1],
        "candidate_probabilities": [0.5249792, 0.4750208],
        "candidate_correctness_probabilities": [0.8, 0.7],
        "candidate_utilities": [0.41998336, 0.33251456],
        "selected_index": 0,
        "selected_candidate_id": "keep",
        "selected_target": "KEEP_SWSD",
        "carrier_confidence": 0.41998336,
        "clue_probability": 0.25,
        "auxiliary_probabilities": [0.1, 0.2],
        "truth_candidate_id": "keep",
        "truth_target": "KEEP_SWSD",
        "clue_target": False,
        "review_target": False,
    }
