from pathlib import Path

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    AUXILIARY_TARGET_NAMES,
    HierarchicalThresholds,
    HierarchicalTrainingExample,
    SchemeAP2P3P0Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_network import (
    SchemeAHierarchicalCarrierClueScorer,
    hierarchical_loss,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_training import (
    decision_from_score,
    select_hierarchical_thresholds,
)


def _config(tmp_path: Path, **overrides: object) -> SchemeAP2P3P0Config:
    values = {
        "dataset_p0_root": tmp_path,
        "dataset_run_root": tmp_path,
        "base_oof_run_a": tmp_path,
        "base_oof_run_b": tmp_path,
        "p2_p2_p0_run_root": tmp_path,
        "p2_p2_p1_run_a": tmp_path,
        "p2_p2_p1_run_b": tmp_path,
        "p2_p2_p2_p0_run_root": tmp_path,
        "p2_p2_p2_p2_run_root": tmp_path,
        "output_root": tmp_path,
        "run_id": "unit",
    }
    values.update(overrides)
    return SchemeAP2P3P0Config(**values)


def _group() -> P1GroupExample:
    return P1GroupExample(
        case_key="T10:1",
        fold=0,
        group_id="segment:1",
        object_type="SEGMENT",
        object_id="1_2",
        object_tokens=("OBJECT:NORMAL",),
        context_tokens=("CONTEXT:DRIVEZONE",),
        candidates=(
            P1CandidateExample("keep", "KEEP_SWSD", ("KEEP",), (0.0,) * 8),
            P1CandidateExample("use", "USE_RCSD", ("USE",), (1.0,) * 8),
        ),
        truth_index=0,
        truth_target="KEEP_SWSD",
        anomaly_target=True,
        sample_weight=1.0,
        hard_unsafe=False,
    )


def test_config_freezes_three_seeds_and_parameter_scale(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config.model_seeds == (311, 313, 317)
    assert config.target_min_parameter_count == 1_000_000
    assert config.target_max_parameter_count == 3_000_000
    with pytest.raises(ValueError, match="three unique model seeds"):
        _config(tmp_path, model_seeds=(1, 2))


def test_hierarchical_example_keeps_auxiliary_labels_separate() -> None:
    example = HierarchicalTrainingExample(
        group=_group(),
        evidence_features=(0.0,) * 202,
        auxiliary_targets=(True, False, False, True, False, True, False),
    )
    assert len(example.evidence_features) == 202
    assert len(example.auxiliary_targets) == len(AUXILIARY_TARGET_NAMES)
    with pytest.raises(ValueError, match="auxiliary target dimension"):
        HierarchicalTrainingExample(
            group=_group(),
            evidence_features=(0.0,) * 202,
            auxiliary_targets=(True,),
        )


def test_network_has_separate_carrier_clue_and_auxiliary_heads() -> None:
    model = SchemeAHierarchicalCarrierClueScorer(
        candidate_vocabulary_size=8,
        object_vocabulary_size=8,
        context_vocabulary_size=8,
        object_type_count=2,
        numeric_dim=8,
        evidence_dim=202,
        auxiliary_dim=len(AUXILIARY_TARGET_NAMES),
        embedding_dim=16,
        hidden_dim=32,
        type_embedding_dim=8,
        evidence_hidden_dim=32,
        dropout=0.0,
    )
    outputs = model(
        candidate_token_ids=torch.tensor([1, 2]),
        candidate_offsets=torch.tensor([0, 1]),
        object_token_ids=torch.tensor([1]),
        object_offsets=torch.tensor([0]),
        context_token_ids=torch.tensor([1]),
        context_offsets=torch.tensor([0]),
        numeric_features=torch.zeros((2, 8)),
        group_evidence=torch.zeros((1, 202)),
        candidate_group_index=torch.tensor([0, 0]),
        group_type_ids=torch.tensor([1]),
    )
    assert [tuple(value.shape) for value in outputs] == [(2,), (2,), (1,), (1, 7)]
    loss, parts = hierarchical_loss(
        *outputs,
        torch.tensor([0, 0]),
        torch.tensor([True, False]),
        torch.tensor([1.0]),
        torch.tensor([True]),
        torch.tensor([[True, False, False, True, False, True, False]]),
        candidate_correctness_loss_weight=0.5,
        clue_loss_weight=1.5,
        auxiliary_loss_weight=0.25,
        clue_positive_weight=1.0,
        auxiliary_positive_weights=torch.ones(7),
    )
    assert torch.isfinite(loss)
    assert set(parts) == {
        "listwise_loss",
        "candidate_correctness_loss",
        "clue_loss",
        "auxiliary_loss",
    }
    assert parameter_count(model) > 0


def test_threshold_selection_is_precision_first() -> None:
    rows = [
        {
            "selected_target": "USE_RCSD",
            "selected_candidate_id": "wrong",
            "truth_candidate_id": "truth-a",
            "carrier_confidence": 0.70,
            "clue_probability": 0.10,
            "clue_target": False,
        },
        {
            "selected_target": "KEEP_SWSD",
            "selected_candidate_id": "truth-b",
            "truth_candidate_id": "truth-b",
            "carrier_confidence": 0.90,
            "clue_probability": 0.80,
            "clue_target": True,
        },
        {
            "selected_target": "KEEP_SWSD",
            "selected_candidate_id": "truth-c",
            "truth_candidate_id": "truth-c",
            "carrier_confidence": 0.80,
            "clue_probability": 0.70,
            "clue_target": True,
        },
    ]
    thresholds = select_hierarchical_thresholds(rows)
    assert thresholds == HierarchicalThresholds(
        carrier_threshold=0.70, clue_threshold=0.70
    )


def test_decision_never_auto_publishes_review_or_clue() -> None:
    base = {
        "case_key": "T10:1",
        "fold": 0,
        "group_id": "segment:1",
        "object_id": "1_2",
        "selected_candidate_id": "candidate",
        "selected_target": "KEEP_SWSD",
        "carrier_confidence": 0.9,
        "clue_probability": 0.1,
    }
    thresholds = HierarchicalThresholds(0.5, 0.5)
    accepted = decision_from_score(base, thresholds, seed=311, model_signature="model")
    assert accepted["accepted"]
    clue = decision_from_score(
        {**base, "clue_probability": 0.8},
        thresholds,
        seed=311,
        model_signature="model",
    )
    assert not clue["accepted"]
    assert clue["reason"] == "reality_change_clue"
    review = decision_from_score(
        {**base, "selected_target": "REVIEW_FALLBACK"},
        thresholds,
        seed=311,
        model_signature="model",
    )
    assert not review["accepted"]
    assert review["reason"] == "review_never_auto_publish"
