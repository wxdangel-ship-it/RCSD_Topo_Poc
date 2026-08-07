from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_ANCHOR_CONDITION_DIM,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
    TargetABatchTensors,
    TargetAJointNetwork,
    anchor_cardinality_candidate_log_prior,
    anchor_candidate_cardinality_masks,
    compositional_anchor_candidate_logits,
    hierarchical_anchor_selection_logits,
    hierarchical_ordinary_plan_logits,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_COUNT,
    ORDINARY_PLAN_ARM_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
)


def _batch(feature_dim: int = 64) -> TargetABatchTensors:
    batch = 2
    objects = 5
    anchors = 2
    ordinary = 2
    advance = 1
    candidates = 3
    return TargetABatchTensors(
        object_features=torch.randn(batch, objects, feature_dim),
        object_types=torch.zeros(batch, objects, dtype=torch.long),
        object_mask=torch.ones(batch, objects, dtype=torch.bool),
        adjacency=torch.ones(batch, objects, objects, dtype=torch.bool),
        anchor_object_indices=torch.tensor([[0, 1], [0, 1]]),
        anchor_candidate_features=torch.randn(
            batch,
            anchors,
            candidates,
            feature_dim,
        ),
        anchor_candidate_mask=torch.ones(
            batch,
            anchors,
            candidates,
            dtype=torch.bool,
        ),
        ordinary_object_indices=torch.tensor([[2, 3], [2, 3]]),
        ordinary_required_anchor_indices=torch.tensor(
            [[[0, 1], [0, -1]], [[0, 1], [1, -1]]]
        ),
        ordinary_plan_features=torch.randn(
            batch,
            ordinary,
            candidates,
            feature_dim,
        ),
        ordinary_plan_mask=torch.ones(
            batch,
            ordinary,
            candidates,
            dtype=torch.bool,
        ),
        ordinary_plan_decision_indices=torch.tensor(
            [
                [
                    [
                        ORDINARY_DECISION_KEEP_SWSD,
                        ORDINARY_DECISION_USE_RCSD,
                        ORDINARY_DECISION_USE_RCSD,
                    ],
                    [
                        ORDINARY_DECISION_KEEP_SWSD,
                        ORDINARY_DECISION_USE_RCSD,
                        ORDINARY_DECISION_USE_RCSD,
                    ],
                ],
            ]
            * batch,
            dtype=torch.long,
        ),
        ordinary_plan_member_features=torch.randn(
            batch,
            ordinary,
            candidates,
            4,
            ORDINARY_PLAN_MEMBER_FEATURE_DIM,
        ),
        ordinary_plan_member_mask=torch.ones(
            batch,
            ordinary,
            candidates,
            4,
            dtype=torch.bool,
        ),
        ordinary_plan_arm_features=torch.randn(
            batch,
            ordinary,
            candidates,
            ORDINARY_PLAN_ARM_COUNT,
            ORDINARY_PLAN_ARM_FEATURE_DIM,
        ),
        ordinary_plan_arm_mask=torch.ones(
            batch,
            ordinary,
            candidates,
            ORDINARY_PLAN_ARM_COUNT,
            dtype=torch.bool,
        ),
        advance_right_object_indices=torch.tensor([[4], [4]]),
        advance_right_source_indices=torch.tensor([[0], [0]]),
        advance_right_target_indices=torch.tensor([[1], [1]]),
        advance_right_plan_features=torch.randn(
            batch,
            advance,
            candidates,
            feature_dim,
        ),
        advance_right_plan_mask=torch.ones(
            batch,
            advance,
            candidates,
            dtype=torch.bool,
        ),
        teacher_anchor_candidate_indices=torch.zeros(
            batch,
            anchors,
            dtype=torch.long,
        ),
        teacher_anchor_success=torch.ones(
            batch,
            anchors,
            dtype=torch.bool,
        ),
        teacher_ordinary_plan_indices=torch.zeros(
            batch,
            ordinary,
            dtype=torch.long,
        ),
    )


def test_raw_evidence_anchor_type_decoder_ignores_graph_context() -> None:
    torch.manual_seed(17)
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        anchor_raw_evidence_type_decoder=True,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=30_000_000,
    )
    model = TargetAJointNetwork(config).eval()
    assert model.anchor_type_head is None
    assert model.anchor_raw_evidence_type_head is not None
    batch = _batch()
    with torch.no_grad():
        expected = model(batch)["anchor_type_logits"]
    changed_features = batch.object_features.clone()
    changed_features[:, 2:] += 100.0
    changed = replace(
        batch,
        object_features=changed_features,
        adjacency=torch.eye(
            batch.object_features.shape[1],
            dtype=torch.bool,
        )
        .unsqueeze(0)
        .expand(batch.object_features.shape[0], -1, -1),
    )
    with torch.no_grad():
        actual = model(changed)["anchor_type_logits"]
    assert torch.equal(actual, expected)


def test_raw_evidence_candidate_decoder_compares_candidate_sets_directly() -> None:
    torch.manual_seed(19)
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        anchor_raw_evidence_candidate_decoder=True,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=30_000_000,
    )
    model = TargetAJointNetwork(config).eval()
    assert model.anchor_type_head is None
    assert model.anchor_raw_evidence_type_head is None
    assert model.anchor_raw_evidence_candidate_head is not None
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 1.0, 1.0], [0.0, 1.0, 1.0]]] * 2
    )
    with torch.no_grad():
        expected = model(batch)
    changed_features = batch.object_features.clone()
    changed_features[:, 2:] += 100.0
    changed = replace(
        batch,
        object_features=changed_features,
        adjacency=torch.eye(
            batch.object_features.shape[1],
            dtype=torch.bool,
        )
        .unsqueeze(0)
        .expand(batch.object_features.shape[0], -1, -1),
    )
    with torch.no_grad():
        actual = model(changed)
    assert torch.equal(
        actual["anchor_candidate_logits"],
        expected["anchor_candidate_logits"],
    )
    assert torch.equal(
        actual["anchor_type_logits"],
        expected["anchor_type_logits"],
    )
    assert torch.isfinite(actual["anchor_type_logits"]).all()


def test_raw_anchor_evidence_decoders_are_mutually_exclusive() -> None:
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        anchor_raw_evidence_type_decoder=True,
        anchor_raw_evidence_candidate_decoder=True,
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        config.validate()


def test_target_a_network_is_in_confirmed_parameter_range() -> None:
    config = TargetAConfig()
    model = TargetAJointNetwork(config)
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count


def test_target_a_network_outputs_all_confirmed_stages() -> None:
    model = TargetAJointNetwork(TargetAConfig())
    model.eval()
    with torch.no_grad():
        result = model(_batch())
    assert result["anchor_status_logits"].shape == (2, 2, 5)
    assert result["anchor_candidate_logits"].shape == (2, 2, 3)
    assert result["ordinary_plan_logits"].shape == (2, 2, 3)
    assert result["clue_logits"].shape == (2, 2, 2)
    assert result["fallback_scope_logits"].shape == (2, 2, 3)
    assert result["advance_right_plan_logits"].shape == (2, 1, 3)
    assert not result["locked_anchor_embeddings"].requires_grad
    assert not result["locked_ordinary_embeddings"].requires_grad


def test_hierarchical_ordinary_decoder_outputs_decision_and_complete_plan() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_decision_loss_weight=1.0,
    )
    model = TargetAJointNetwork(config)
    model.eval()

    with torch.no_grad():
        result = model(_batch())

    assert result["ordinary_decision_logits"].shape == (2, 2, 3)
    assert result["ordinary_plan_logits"].shape == (2, 2, 3)
    assert torch.isfinite(result["ordinary_plan_logits"]).all()


def test_separate_ordinary_validity_head_is_independent_and_masked() -> None:
    config = TargetAConfig(
        ordinary_candidate_validity_loss_weight=0.5,
        separate_ordinary_candidate_validity_head=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()

    with torch.no_grad():
        result = model(_batch())

    assert result["ordinary_plan_validity_logits"].shape == (2, 2, 3)
    assert (
        model.ordinary_plan_validity_head
        is not model.ordinary_plan_head
    )
    assert torch.isfinite(
        result["ordinary_plan_validity_logits"]
    ).all()


def test_separate_ordinary_validity_head_requires_positive_loss() -> None:
    with pytest.raises(ValueError, match="positive validity loss weight"):
        TargetAJointNetwork(
            TargetAConfig(
                separate_ordinary_candidate_validity_head=True,
            )
        )


def test_separate_decision_validity_head_is_independent() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_decision_validity_loss_weight=1.0,
        separate_ordinary_decision_validity_head=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()

    with torch.no_grad():
        result = model(_batch())

    assert result["ordinary_decision_validity_logits"].shape == (2, 2, 3)
    assert (
        model.ordinary_decision_validity_head
        is not model.ordinary_decision_head
    )
    assert torch.isfinite(
        result["ordinary_decision_validity_logits"][..., :2]
    ).all()
    assert torch.isneginf(
        result["ordinary_decision_validity_logits"][..., 2]
    ).all()


def test_separate_decision_validity_head_requires_positive_loss() -> None:
    with pytest.raises(ValueError, match="positive validity loss weight"):
        TargetAJointNetwork(
            TargetAConfig(
                hierarchical_ordinary_plan_decoder=True,
                separate_ordinary_decision_validity_head=True,
            )
        )


def test_ordinary_member_set_encoder_preserves_complete_plan_shape() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_plan_member_encoder=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()

    with torch.no_grad():
        result = model(_batch())

    assert result["ordinary_plan_logits"].shape == (2, 2, 3)
    assert parameter_count(model) <= config.max_parameter_count


def test_decision_local_member_evidence_does_not_change_decision_logits() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_plan_member_encoder=True,
        ordinary_plan_member_within_decision_only=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()
    base = _batch()
    assert base.ordinary_plan_member_features is not None
    changed = replace(
        base,
        ordinary_plan_member_features=(
            base.ordinary_plan_member_features + 10.0
        ),
    )

    with torch.no_grad():
        original = model(base)
        perturbed = model(changed)

    assert torch.equal(
        original["ordinary_decision_logits"],
        perturbed["ordinary_decision_logits"],
    )
    assert not torch.equal(
        original["ordinary_plan_logits"],
        perturbed["ordinary_plan_logits"],
    )


def test_arm_matching_is_a_bounded_cross_state_plan_residual() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_plan_member_encoder=True,
        ordinary_plan_member_within_decision_only=True,
        ordinary_plan_arm_encoder=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()
    base = _batch()
    assert base.ordinary_plan_arm_features is not None
    changed = replace(
        base,
        ordinary_plan_arm_features=base.ordinary_plan_arm_features + 10.0,
    )

    with torch.no_grad():
        original = model(base)
        perturbed = model(changed)

    assert not torch.equal(
        original["ordinary_decision_logits"],
        perturbed["ordinary_decision_logits"],
    )
    assert not torch.equal(
        original["ordinary_plan_logits"],
        perturbed["ordinary_plan_logits"],
    )
    assert parameter_count(model) <= config.max_parameter_count


def test_arm_matching_is_invariant_to_segment_end_storage_order() -> None:
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_plan_arm_encoder=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()
    base = _batch()
    assert base.ordinary_plan_arm_features is not None
    assert base.ordinary_plan_arm_mask is not None
    swapped = replace(
        base,
        ordinary_plan_arm_features=base.ordinary_plan_arm_features.flip(-2),
        ordinary_plan_arm_mask=base.ordinary_plan_arm_mask.flip(-1),
    )

    with torch.no_grad():
        original = model(base)
        perturbed = model(swapped)

    assert torch.equal(
        original["ordinary_decision_logits"],
        perturbed["ordinary_decision_logits"],
    )
    assert torch.equal(
        original["ordinary_plan_logits"],
        perturbed["ordinary_plan_logits"],
    )


def test_hierarchical_ordinary_logits_do_not_reward_more_use_bundles() -> None:
    batch = replace(
        _batch(),
        ordinary_plan_mask=torch.tensor(
            [
                [[True, True, True], [False, False, False]],
                [[False, False, False], [False, False, False]],
            ]
        ),
    )
    bundle_logits = torch.zeros((2, 2, 3))
    decision_logits = torch.tensor(
        [
            [[2.0, 0.0, -float("inf")], [0.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ]
    )

    logits = hierarchical_ordinary_plan_logits(
        bundle_logits,
        decision_logits,
        batch,
    )
    probabilities = torch.softmax(logits[0, 0], dim=-1)

    assert probabilities.argmax().item() == 0
    assert probabilities[1] == probabilities[2]
    assert probabilities[0] > probabilities[1] + probabilities[2]


def test_oof_anchor_condition_only_changes_downstream_business_heads() -> None:
    config = TargetAConfig(
        ordinary_oof_anchor_condition_encoder=True,
    )
    model = TargetAJointNetwork(config)
    model.eval()
    base = _batch()
    zeros = replace(
        base,
        ordinary_anchor_condition_features=torch.zeros(
            2,
            2,
            ORDINARY_ANCHOR_CONDITION_DIM,
        ),
    )
    ones = replace(
        base,
        ordinary_anchor_condition_features=torch.ones(
            2,
            2,
            ORDINARY_ANCHOR_CONDITION_DIM,
        ),
    )

    with torch.no_grad():
        zero_result = model(zeros)
        one_result = model(ones)

    assert torch.equal(
        zero_result["anchor_status_logits"],
        one_result["anchor_status_logits"],
    )
    assert torch.equal(
        zero_result["anchor_candidate_logits"],
        one_result["anchor_candidate_logits"],
    )
    assert not torch.allclose(
        zero_result["ordinary_plan_logits"],
        one_result["ordinary_plan_logits"],
    )


def test_anchor_status_can_condition_on_selected_candidate_context() -> None:
    config = TargetAConfig(anchor_status_use_selected_candidate=True)
    model = TargetAJointNetwork(config)
    model.eval()
    with torch.no_grad():
        result = model(_batch())
    assert result["anchor_status_logits"].shape == (2, 2, 5)
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count


def test_learned_anchor_gate_is_independent_and_hard_vetoes_lock() -> None:
    config = TargetAConfig(learned_anchor_gate=True)
    model = TargetAJointNetwork(config)
    model.eval()
    batch = replace(_batch(), teacher_anchor_success=None)
    with torch.no_grad():
        result = model(batch)
    assert result["anchor_gate_logits"].shape == (2, 2, 2)
    candidates = torch.ones(2, 2, 3, config.hidden_dim)
    status_logits = torch.zeros(2, 2, config.anchor_status_count)
    status_logits[..., 0] = 10.0
    gate_logits = torch.zeros(2, 2, 2)
    gate_logits[..., 0] = 10.0
    locked, selected_indices, anchor_success = model._lock_anchor(
        candidates,
        status_logits,
        gate_logits,
        torch.zeros(2, 2, 3),
        None,
        None,
        batch,
    )
    assert torch.count_nonzero(locked) == 0
    assert selected_indices.shape == (2, 2)
    assert not anchor_success.any()


def test_hierarchical_anchor_type_is_locked_before_candidate_selection() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 1.0, 1.0], [0.0, 1.0, 1.0]]] * 2
    )
    candidate_logits = torch.tensor(
        [[[10.0, 2.0, 1.0], [10.0, 2.0, 1.0]]] * 2
    )
    type_logits = torch.tensor([[[0.0, 5.0], [0.0, 5.0]]] * 2)

    selected = hierarchical_anchor_selection_logits(
        candidate_logits,
        type_logits,
        batch,
    )

    assert torch.isneginf(selected[..., 0]).all()
    assert selected.argmax(dim=-1).eq(1).all()


def test_hierarchical_anchor_type_can_be_a_soft_candidate_prior() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 1.0, 1.0], [0.0, 1.0, 1.0]]] * 2
    )
    candidate_logits = torch.tensor(
        [[[10.0, 2.0, 1.0], [10.0, 2.0, 1.0]]] * 2
    )
    type_logits = torch.tensor([[[0.0, 2.0], [0.0, 2.0]]] * 2)

    selected = hierarchical_anchor_selection_logits(
        candidate_logits,
        type_logits,
        batch,
        hard_type_lock=False,
    )

    assert torch.isfinite(selected).all()
    assert selected.argmax(dim=-1).eq(0).all()
    stronger_type_prior = hierarchical_anchor_selection_logits(
        candidate_logits,
        type_logits,
        batch,
        hard_type_lock=False,
        type_prior_weight=10.0,
    )
    assert stronger_type_prior.argmax(dim=-1).eq(1).all()
    with pytest.raises(ValueError, match="type prior weight"):
        hierarchical_anchor_selection_logits(
            candidate_logits,
            type_logits,
            batch,
            hard_type_lock=False,
            type_prior_weight=-1.0,
        )


def test_hierarchical_anchor_outputs_independent_type_stage() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 1.0, 1.0], [0.0, 1.0, 1.0]]] * 2
    )
    config = TargetAConfig(hierarchical_anchor_decoder=True)
    model = TargetAJointNetwork(config)
    model.eval()

    with torch.no_grad():
        result = model(batch)

    assert result["anchor_type_logits"].shape == (2, 2, 2)
    assert torch.isfinite(result["anchor_type_logits"]).all()
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count


def test_structured_anchor_decoder_consumes_truth_free_candidate_relations() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 1.0, 1.0], [0.0, 1.0, 1.0]]] * 2
    )
    relations = torch.zeros((2, 2, 3, 3, 8))
    relations[..., 0] = 1.0
    for index in range(3):
        relations[:, :, index, index, 1] = 1.0
    batch = replace(batch, anchor_candidate_relations=relations)
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        structured_anchor_object_decoder=True,
    )
    model = TargetAJointNetwork(config)

    result = model(batch)

    assert result["anchor_candidate_logits"].shape == (2, 2, 3)
    assert torch.isfinite(result["anchor_candidate_logits"]).all()
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count


def test_compositional_anchor_decoder_scores_complete_typed_member_sets() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]] * 2
    )
    member_mask = torch.ones((2, 2, 4), dtype=torch.bool)
    member_is_road = torch.tensor(
        [[[False, False, True, True], [False, False, True, True]]] * 2
    )
    membership = torch.tensor(
        [
            [
                [[True, False, False, False],
                 [True, True, False, False],
                 [False, False, True, True]],
                [[True, False, False, False],
                 [True, True, False, False],
                 [False, False, True, True]],
            ]
        ]
        * 2,
        dtype=torch.bool,
    )
    batch = replace(
        batch,
        anchor_member_features=torch.randn(2, 2, 4, 64),
        anchor_member_mask=member_mask,
        anchor_member_is_road=member_is_road,
        anchor_candidate_membership=membership,
    )
    member_logits = torch.tensor(
        [[[5.0, -5.0, 5.0, 5.0], [5.0, -5.0, 5.0, 5.0]]] * 2
    )
    candidate_logits = compositional_anchor_candidate_logits(
        member_logits,
        batch,
    )
    assert (candidate_logits[..., 0] > candidate_logits[..., 1]).all()

    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
    )
    model = TargetAJointNetwork(config)
    result = model(batch)

    assert result["anchor_member_logits"].shape == (2, 2, 4)
    assert result["anchor_composition_logits"].shape == (2, 2, 3)
    assert result["anchor_candidate_logits"].shape == (2, 2, 3)
    assert torch.isfinite(result["anchor_candidate_logits"]).all()
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count

    hybrid_config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
        compositional_anchor_candidate_residual=True,
    )
    hybrid_model = TargetAJointNetwork(hybrid_config)
    hybrid_result = hybrid_model(batch)
    assert hybrid_result["anchor_candidate_logits"].shape == (2, 2, 3)
    hybrid_result["anchor_candidate_logits"][
        batch.anchor_candidate_mask
    ].sum().backward()
    assert all(
        parameter.grad is None
        or torch.isfinite(parameter.grad).all()
        for parameter in hybrid_model.parameters()
    )
    assert parameter_count(hybrid_model) > parameter_count(model)
    assert (
        hybrid_config.min_parameter_count
        <= parameter_count(hybrid_model)
        <= hybrid_config.max_parameter_count
    )

    cardinality_masks = anchor_candidate_cardinality_masks(batch, 32)
    assert cardinality_masks[..., 0].tolist() == [
        [[True, False, False], [True, False, False]],
        [[True, False, False], [True, False, False]],
    ]
    cardinality_logits = torch.full((2, 2, 2, 32), -10.0)
    cardinality_logits[..., 0, 1] = 10.0
    cardinality_logits[..., 1, 1] = 10.0
    cardinality_prior = anchor_cardinality_candidate_log_prior(
        cardinality_logits,
        batch,
    )
    assert (cardinality_prior[..., 1] > cardinality_prior[..., 0]).all()
    type_logits = torch.tensor([[[5.0, 0.0], [5.0, 0.0]]] * 2)
    selection = hierarchical_anchor_selection_logits(
        torch.tensor(
            [[[10.0, 1.0, 0.0], [10.0, 1.0, 0.0]]] * 2
        ),
        type_logits,
        batch,
        cardinality_logits=cardinality_logits,
    )
    assert torch.isneginf(selection[..., 0]).all()
    assert selection.argmax(dim=-1).eq(1).all()

    cardinality_config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
        cardinality_conditioned_anchor_decoder=True,
    )
    cardinality_model = TargetAJointNetwork(cardinality_config)
    cardinality_result = cardinality_model(batch)
    assert cardinality_result["anchor_cardinality_logits"].shape == (
        2,
        2,
        2,
        128,
    )
    assert (
        cardinality_config.min_parameter_count
        <= parameter_count(cardinality_model)
        <= cardinality_config.max_parameter_count
    )
    soft_cardinality_config = replace(
        cardinality_config,
        anchor_cardinality_hard_lock=False,
    )
    soft_cardinality_result = TargetAJointNetwork(
        soft_cardinality_config
    )(batch)
    assert soft_cardinality_result[
        "anchor_candidate_logits"
    ].shape == (2, 2, 3)
    zero_prior_result = TargetAJointNetwork(
        replace(
            soft_cardinality_config,
            anchor_cardinality_prior_weight=0.0,
        )
    )(batch)
    assert zero_prior_result["anchor_candidate_logits"].shape == (2, 2, 3)
    with pytest.raises(ValueError, match="cardinality prior weight"):
        replace(
            soft_cardinality_config,
            anchor_cardinality_prior_weight=-1.0,
        ).validate()


def test_anchor_structural_encoder_consumes_arm_relation_and_local_evidence() -> None:
    batch = _batch()
    batch.anchor_candidate_features[..., 27] = torch.tensor(
        [[[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]] * 2
    )
    member_mask = torch.ones((2, 2, 4), dtype=torch.bool)
    membership = torch.tensor(
        [
            [
                [
                    [True, False, False, False],
                    [True, True, False, False],
                    [False, False, True, True],
                ],
                [
                    [True, False, False, False],
                    [True, True, False, False],
                    [False, False, True, True],
                ],
            ]
        ]
        * 2,
        dtype=torch.bool,
    )
    relation_features = torch.zeros((2, 2, 4, 4, 7))
    relation_features[:, :, 2, 3, 0] = 1.0
    relation_features[:, :, 3, 2, 0] = 1.0
    relation_mask = torch.zeros((2, 2, 4, 4), dtype=torch.bool)
    relation_mask[:, :, 2, 3] = True
    relation_mask[:, :, 3, 2] = True
    batch = replace(
        batch,
        anchor_member_features=torch.randn(2, 2, 4, 64),
        anchor_member_mask=member_mask,
        anchor_member_is_road=torch.tensor(
            [[[False, False, True, True], [False, False, True, True]]] * 2
        ),
        anchor_candidate_membership=membership,
        anchor_swsd_arm_features=torch.randn(2, 2, 3, 7),
        anchor_swsd_arm_mask=torch.ones(2, 2, 3, dtype=torch.bool),
        anchor_member_arm_features=torch.randn(2, 2, 4, 2, 7),
        anchor_member_arm_mask=torch.ones(2, 2, 4, 2, dtype=torch.bool),
        anchor_member_local_features=torch.randn(2, 2, 4, 12),
        anchor_member_relation_features=relation_features,
        anchor_member_relation_mask=relation_mask,
    )
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
        cardinality_conditioned_anchor_decoder=True,
        anchor_structural_evidence_encoder=True,
        anchor_structural_member_local_encoder=True,
        compositional_anchor_candidate_residual=True,
        anchor_structural_candidate_residual_context=True,
    )
    model = TargetAJointNetwork(config)

    result = model(batch)

    assert result["anchor_member_structural_context"].shape == (2, 2, 4, 352)
    assert result["anchor_candidate_structural_context"].shape == (
        2,
        2,
        3,
        352,
    )
    assert torch.isfinite(result["anchor_candidate_logits"]).all()
    result["anchor_candidate_logits"][
        batch.anchor_candidate_mask
    ].sum().backward()
    assert all(
        parameter.grad is None
        or torch.isfinite(parameter.grad).all()
        for parameter in model.parameters()
    )
    assert config.min_parameter_count <= parameter_count(model) <= config.max_parameter_count

    isolated_config = replace(
        config,
        anchor_structural_candidate_context_fusion=False,
    )
    isolated_model = TargetAJointNetwork(isolated_config)
    isolated_model.eval()
    changed_batch = replace(
        batch,
        anchor_member_local_features=(
            batch.anchor_member_local_features + 1.0
        ),
    )
    with torch.no_grad():
        isolated = isolated_model(batch)
        changed = isolated_model(changed_batch)
    assert torch.allclose(
        isolated["anchor_status_logits"],
        changed["anchor_status_logits"],
    )
    assert torch.allclose(
        isolated["anchor_type_logits"],
        changed["anchor_type_logits"],
    )
    assert torch.allclose(
        isolated["anchor_cardinality_logits"],
        changed["anchor_cardinality_logits"],
    )
    assert not torch.allclose(
        isolated["anchor_member_structural_context"],
        changed["anchor_member_structural_context"],
    )
    assert not torch.allclose(
        isolated["anchor_candidate_logits"],
        changed["anchor_candidate_logits"],
    )


def test_target_a_masked_candidate_does_not_win() -> None:
    batch = _batch()
    batch.anchor_candidate_mask[:, :, -1] = False
    model = TargetAJointNetwork(TargetAConfig())
    model.eval()
    with torch.no_grad():
        result = model(batch)
    assert torch.isneginf(result["anchor_candidate_logits"][:, :, -1]).all()
