from __future__ import annotations

import torch
import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
    _batch_tensors,
    balanced_component_edge_bce,
    balanced_member_bce,
    choose_zero_exact_error_threshold,
    ordinary_road_set_metrics,
    masked_candidate_cross_entropy,
    select_member_indices,
    validate_cardinality_capacity,
)


def test_ordinary_road_set_requires_one_training_view() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        teacher_training_loss_weight=0.0,
        oof_training_loss_weight=0.0,
    )
    with pytest.raises(ValueError, match="training views"):
        config.validate()


def test_ordinary_graph_heads_must_divide_hidden_dimension() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        hidden_dim=15,
        graph_heads=4,
        structured_graph_decoder=True,
    )
    with pytest.raises(ValueError, match="graph heads"):
        config.validate()


def test_ordinary_graph_attention_scope_is_explicit() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        structured_graph_decoder=True,
        graph_attention_scope="UNKNOWN",
    )
    with pytest.raises(ValueError, match="attention scope"):
        config.validate()


def test_cardinality_capacity_covers_complete_road_set() -> None:
    with pytest.raises(ValueError, match="maximum=66, count=66"):
        validate_cardinality_capacity(
            maximum_target_cardinality=66,
            cardinality_count=66,
        )
    validate_cardinality_capacity(
        maximum_target_cardinality=66,
        cardinality_count=67,
    )


def test_anchor_relation_decoder_preserves_anchor_gate_order() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        anchor_relation_decoder=True,
        structured_graph_decoder=False,
    )
    with pytest.raises(ValueError, match="needs graph decoder"):
        config.validate()


def test_road_relation_decoder_requires_graph_structure() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        road_relation_dim=3,
        structured_graph_decoder=False,
    )
    with pytest.raises(ValueError, match="relation decoder"):
        config.validate()


def test_component_edge_decoder_requires_explicit_loss() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        structured_graph_decoder=True,
        anchor_relation_decoder=True,
        ownership_role_decoder=True,
        road_relation_dim=3,
        component_edge_decoder=True,
        component_edge_loss_weight=0.0,
    )
    with pytest.raises(ValueError, match="decoder/loss"):
        config.validate()


def test_batch_road_relations_are_vectorized_into_symmetric_edges() -> None:
    example = OrdinaryRoadSetExample(
        case_key="case",
        segment_id="segment",
        fold=0,
        object_features=(1.0,),
        road_ids=("r0", "r1", "r2"),
        sources=("RCSD", "SWSD", "RCSD"),
        start_node_ids=("a", "c", "e"),
        end_node_ids=("b", "d", "f"),
        anchor_features=((1.0, 0.0, 0.0),),
        teacher_anchor_relations=(
            ((1.0, 0.0, 0.0, 0.0),),
            ((0.0, 1.0, 0.0, 0.0),),
            ((0.0, 0.0, 1.0, 0.0),),
        ),
        oof_anchor_relations=(
            ((1.0, 0.0, 0.0, 0.0),),
            ((0.0, 1.0, 0.0, 0.0),),
            ((0.0, 0.0, 1.0, 0.0),),
        ),
        teacher_features=((1.0,), (2.0,), (3.0,)),
        oof_features=((1.0,), (2.0,), (3.0,)),
        decision=1,
        target_indices=(0, 2),
        ownership_targets=(0, 0, 0),
        ownership_task_mask=(False, False, False),
        business_role_targets=(0, 0, 0),
        business_role_task_mask=(False, False, False),
        sample_weight=0.7,
        oof_anchor_release_ready=True,
        road_relations=(
            (0, 1, (1.0, 0.0, 0.5)),
            (0, 2, (0.25, 1.0, -0.5)),
        ),
        member_sample_weights=(1.0, 0.7, 0.7),
    )
    batch = _batch_tensors(
        [example],
        feature_source="teacher",
        device=torch.device("cpu"),
        cardinality_count=4,
        road_relation_dim=3,
    )
    expected = torch.tensor([0.25, 1.0, -0.5])
    assert torch.equal(batch["road_relations"][0, 0, 2], expected)
    assert torch.equal(batch["road_relations"][0, 2, 0], expected)
    assert bool(batch["adjacency"][0, 0, 2])
    assert bool(batch["adjacency"][0, 2, 0])
    assert bool(batch["adjacency"][0, 0, 1])
    assert not bool(batch["endpoint_adjacency"][0, 0, 1])
    assert not bool(batch["endpoint_adjacency"][0, 0, 2])
    assert not bool(batch["component_adjacency"][0, 0, 1])
    assert bool(batch["component_adjacency"][0, 0, 2])
    assert bool(batch["component_edge_task_mask"][0, 0, 2])
    assert bool(batch["component_edge_targets"][0, 0, 2])
    assert float(batch["member_weight_ratios"][0, 0]) == pytest.approx(
        1.0 / 0.7
    )
    assert float(batch["member_weight_ratios"][0, 1]) == pytest.approx(1.0)


def test_ownership_role_decoder_requires_anchor_relations() -> None:
    config = OrdinaryRoadSetTrainingConfig(
        structured_graph_decoder=True,
        ownership_role_decoder=True,
        anchor_relation_decoder=False,
    )
    with pytest.raises(ValueError, match="needs anchor relation"):
        config.validate()


def test_balanced_member_loss_handles_class_imbalance() -> None:
    logits = torch.tensor([[3.0, -2.0, -1.0, -3.0]])
    targets = torch.tensor([[True, False, False, False]])
    valid = torch.tensor([[True, True, True, True]])
    loss = balanced_member_bce(logits, targets, valid)
    assert loss.shape == (1,)
    assert float(loss[0]) > 0.0


def test_balanced_component_loss_uses_positive_and_negative_edges() -> None:
    logits = torch.tensor([[[0.0, 2.0, -2.0]] * 3])
    targets = torch.tensor(
        [[[False, True, False], [False] * 3, [False] * 3]]
    )
    valid = torch.tensor(
        [[[False, True, True], [False] * 3, [False] * 3]]
    )
    loss = balanced_component_edge_bce(logits, targets, valid)
    assert loss.shape == (1,)
    assert 0.0 < float(loss[0]) < 0.2


def test_masked_business_loss_ignores_unknown_roles() -> None:
    loss = masked_candidate_cross_entropy(
        torch.tensor([[[3.0, -1.0], [-1.0, 3.0]]]),
        torch.tensor([[0, 0]]),
        torch.tensor([[True, False]]),
    )
    assert loss.shape == (1,)
    assert float(loss[0]) < 0.1


def test_member_threshold_decodes_multilabel_set_without_cardinality() -> None:
    selected = select_member_indices(
        probabilities=[0.8, 0.7, 0.4, 0.9],
        road_ids=("a", "b", "c", "d"),
        valid_indices=(0, 1, 2),
        predicted_cardinality=1,
        probability_threshold=0.6,
    )
    assert selected == (0, 1)


def test_member_threshold_uses_complete_set_errors() -> None:
    rows = [
        {
            "confidence": 0.7,
            "release_eligible": True,
            "complete_exact": False,
        },
        {
            "confidence": 0.9,
            "release_eligible": False,
            "complete_exact": False,
        },
    ]
    threshold = choose_zero_exact_error_threshold(rows)
    assert 0.7 < threshold < 0.71


def test_member_metrics_require_decision_and_complete_set() -> None:
    rows = [
        {
            "case_key": "c1",
            "decision_exact": True,
            "road_set_exact": True,
            "complete_exact": True,
            "road_f1": 1.0,
            "release_eligible": True,
            "automatic": True,
        },
        {
            "case_key": "c2",
            "decision_exact": True,
            "road_set_exact": False,
            "complete_exact": False,
            "road_f1": 0.5,
            "release_eligible": False,
            "automatic": False,
        },
    ]
    metrics = ordinary_road_set_metrics(rows)
    assert metrics["decision_exact"] == 1.0
    assert metrics["complete_exact"] == 0.5
    assert metrics["road_macro_f1"] == 0.75
    assert metrics["unsafe_automatic_count"] == 0
