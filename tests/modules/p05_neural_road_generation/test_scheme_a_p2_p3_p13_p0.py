from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_dataset import (
    FEATURE_NAMES,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_MODEL_GO,
    DECISION_SAFETY_NO_GO,
    DECISION_SELECTION_NO_GO,
    P13P0Config,
    choose_decision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_network import (
    AdvanceRightCandidateSetScorer,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_training import (
    choose_acceptance_threshold,
    choose_prediction_thresholds,
    decode_scores,
    load_deterministic_checkpoint,
    save_deterministic_checkpoint,
)


def _config(tmp_path: Path) -> P13P0Config:
    return P13P0Config(
        r1_run_root=tmp_path / "r1",
        p12r_run_root=tmp_path / "p12r",
        scheme_a_baseline_root=tmp_path / "baseline",
        poc_data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        run_id="test",
    )


def _model() -> AdvanceRightCandidateSetScorer:
    return AdvanceRightCandidateSetScorer(
        feature_dim=len(FEATURE_NAMES),
        encoder_hidden_dim=256,
        embedding_dim=192,
        context_dim=96,
        decoder_hidden_dim=512,
        decoder_bottleneck_dim=256,
        dropout=0.0,
    )


def test_model_parameter_gate_and_candidate_permutation() -> None:
    torch.manual_seed(7)
    model = _model().eval()
    assert 300_000 <= parameter_count(model) <= 1_500_000
    values = torch.randn(1, 3, len(FEATURE_NAMES))
    mask = torch.ones((1, 3), dtype=torch.bool)
    logits, object_logits, safety_logits = model(values, mask)
    order = torch.tensor([2, 0, 1])
    permuted_logits, permuted_object_logits, permuted_safety_logits = model(
        values[:, order],
        mask[:, order],
    )
    assert torch.allclose(
        logits[:, order],
        permuted_logits,
        atol=1e-6,
    )
    assert torch.allclose(
        object_logits,
        permuted_object_logits,
        atol=1e-6,
    )
    assert torch.allclose(
        safety_logits,
        permuted_safety_logits,
        atol=1e-6,
    )


def test_thresholds_are_selected_from_inner_labels_only() -> None:
    rows = [
        {
            "candidate_probabilities": [0.9, 0.1],
            "candidate_road_ids": ["a", "b"],
            "candidate_targets": [True, False],
            "object_probability": 0.9,
            "eligible": True,
            "oracle_reachable": True,
            "review": False,
            "safety_probability": 0.9,
            "safety_supervised": True,
            "supervised": True,
            "truth_candidate_road_ids": ["a"],
            "truth_nonempty": True,
        },
        {
            "candidate_probabilities": [0.2],
            "candidate_road_ids": ["c"],
            "candidate_targets": [False],
            "object_probability": 0.1,
            "eligible": True,
            "oracle_reachable": True,
            "review": False,
            "safety_probability": 0.9,
            "safety_supervised": True,
            "supervised": True,
            "truth_candidate_road_ids": [],
            "truth_nonempty": False,
        },
    ]
    candidate_threshold, object_threshold = choose_prediction_thresholds(rows)
    decoded = decode_scores(
        rows,
        candidate_threshold=candidate_threshold,
        object_threshold=object_threshold,
        safety_threshold=0.5,
    )
    assert all(row["raw_exact"] for row in decoded)
    acceptance_threshold = choose_acceptance_threshold(decoded)
    assert all(
        row["confidence"] >= acceptance_threshold for row in decoded
    )


def test_config_and_decision_contract(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.validate()
    assert choose_decision(
        audit_gate=True,
        selection_gate=True,
        safety_gate=True,
    ) == DECISION_MODEL_GO
    assert choose_decision(
        audit_gate=True,
        selection_gate=False,
        safety_gate=True,
    ) == DECISION_SELECTION_NO_GO
    assert choose_decision(
        audit_gate=True,
        selection_gate=True,
        safety_gate=False,
    ) == DECISION_SAFETY_NO_GO
    assert choose_decision(
        audit_gate=False,
        selection_gate=True,
        safety_gate=True,
    ) == DECISION_AUDIT_NO_GO


def test_invalid_training_shape_is_rejected() -> None:
    model = _model()
    with pytest.raises(ValueError, match="shape differs"):
        model(
            torch.randn(1, 2, len(FEATURE_NAMES) - 1),
            torch.ones((1, 2), dtype=torch.bool),
        )


def test_checkpoint_serialization_is_byte_deterministic(
    tmp_path: Path,
) -> None:
    payload = {
        "config": {"feature_dim": 2},
        "model_state_dict": {
            "layer.bias": torch.tensor([1.0, 2.0]),
            "layer.weight": torch.tensor([[3.0, 4.0]]),
        },
        "training_summary": {"seed": 17},
    }
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    save_deterministic_checkpoint(payload, first)
    save_deterministic_checkpoint(payload, second)
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    loaded = load_deterministic_checkpoint(first)
    assert loaded["config"] == payload["config"]
    assert torch.equal(
        loaded["model_state_dict"]["layer.weight"],
        payload["model_state_dict"]["layer.weight"],
    )
