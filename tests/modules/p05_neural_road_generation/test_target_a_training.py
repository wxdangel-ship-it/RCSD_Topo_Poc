from __future__ import annotations

from dataclasses import replace

import torch
import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    acceptable_member_set_nll,
    acceptable_set_nll,
    anchor_member_supervision,
    balanced_candidate_validity_bce,
    iter_case_group_folds,
    iter_weighted_case_group_folds,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    compute_target_a_loss,
    train_anchor_gate_stage,
)


def test_acceptable_set_loss_accepts_nonpreferred_correct_solution() -> None:
    logits = torch.tensor([[1.0, 2.0, -3.0]])
    acceptable = torch.tensor([[True, True, False]])
    valid = torch.tensor([[True, True, True]])
    loss = acceptable_set_nll(logits, acceptable, valid)
    assert loss.shape == (1,)
    assert 0.0 < float(loss.item()) < 0.02


def test_acceptable_set_must_be_subset_of_valid_candidates() -> None:
    logits = torch.zeros((1, 2))
    acceptable = torch.tensor([[False, True]])
    valid = torch.tensor([[True, False]])
    try:
        acceptable_set_nll(logits, acceptable, valid)
    except ValueError as exc:
        assert "acceptable targets" in str(exc)
    else:
        raise AssertionError("invalid acceptable-set target was not rejected")


def test_unsupervised_empty_candidate_set_returns_finite_zero() -> None:
    logits = torch.tensor([[-float("inf")]], requires_grad=True)
    acceptable = torch.tensor([[False]])
    valid = torch.tensor([[False]])
    loss = acceptable_set_nll(logits, acceptable, valid)
    assert float(loss.item()) == 0.0
    loss.backward()


def test_unsupervised_nonempty_row_stays_zero_beside_supervised_row() -> None:
    logits = torch.tensor(
        [[1.0, 0.0], [2.0, -float("inf")]],
        requires_grad=True,
    )
    acceptable = torch.tensor(
        [[True, False], [False, False]],
    )
    valid = torch.tensor(
        [[True, True], [True, False]],
    )
    loss = acceptable_set_nll(logits, acceptable, valid)
    assert torch.isfinite(loss).all()
    assert float(loss[1].item()) == 0.0
    loss.sum().backward()
    assert torch.isfinite(logits.grad).all()


def test_candidate_validity_loss_balances_positive_and_negative_candidates() -> None:
    logits = torch.tensor([[0.0, 0.0, 0.0]])
    acceptable = torch.tensor([[True, False, False]])
    valid = torch.tensor([[True, True, True]])

    loss = balanced_candidate_validity_bce(logits, acceptable, valid)

    assert loss.shape == (1,)
    assert float(loss.item()) == pytest.approx(0.693147, rel=1e-5)


def test_anchor_member_supervision_preserves_multi_solution_optional_member() -> None:
    candidates = []
    for value in range(3):
        row = [0.0] * 64
        row[0] = float(value)
        candidates.append(tuple(row))
    example = AnchorPretrainExample(
        sample_id="member-set",
        case_key="T10:1",
        anchor_id="a",
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:n1", "NODE:n1|n2", "NODE:n1|n3"),
        candidate_features=tuple(candidates),
        status_label=0,
        candidate_acceptable_indices=(0, 1),
        preferred_candidate_index=0,
        candidate_supervised=True,
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason="multi-solution",
        gate_label=1,
        gate_supervised=True,
    )
    batch = collate_anchor_pretrain_batch((example,))

    targets, mask = anchor_member_supervision(
        batch.targets.anchor_acceptable,
        batch.tensors,
    )

    assert targets.tolist() == [[[True, False, False]]]
    assert mask.tolist() == [[[True, False, True]]]

    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
        cardinality_conditioned_anchor_decoder=True,
        learned_anchor_gate=True,
    )
    outputs = TargetAJointNetwork(config)(batch.tensors)
    total, losses = compute_target_a_loss(outputs, batch, config)
    assert torch.isfinite(total)
    assert "anchor_cardinality" in losses
    assert "anchor_gate" in losses


def test_exact_member_set_loss_accepts_multiple_complete_solutions() -> None:
    logits = torch.tensor([[[3.0, -3.0, 3.0]]])
    member_mask = torch.tensor([[[True, True, True]]])
    member_is_road = torch.tensor([[[True, True, True]]])
    acceptable_sets = torch.tensor(
        [[[[True, False, True], [True, True, False]]]]
    )
    option_mask = torch.tensor([[[True, True]]])

    loss = acceptable_member_set_nll(
        logits,
        member_mask,
        member_is_road,
        acceptable_sets,
        option_mask,
    )

    assert loss.shape == (1, 1)
    assert 0.0 < float(loss.item()) < 0.3


def test_case_group_fold_is_deterministic() -> None:
    first = iter_case_group_folds(["T10:1", "T10:2"], fold_count=5)
    second = iter_case_group_folds(["T10:2", "T10:1"], fold_count=5)
    assert first == second


def test_weighted_case_group_fold_keeps_cases_whole_and_balances_large_cases() -> None:
    weights = {
        "T10:large-a": 100.0,
        "T10:large-b": 90.0,
        "T10:small-a": 10.0,
        "T10:small-b": 10.0,
    }
    first = iter_weighted_case_group_folds(weights, fold_count=2)
    second = iter_weighted_case_group_folds(dict(reversed(tuple(weights.items()))), fold_count=2)
    assert first == second
    totals = [
        sum(weights[key] for key, fold in first.items() if fold == index)
        for index in range(2)
    ]
    assert totals == [110.0, 100.0]


def test_hierarchical_anchor_loss_accepts_node_and_road_multi_solution() -> None:
    node = [0.0] * 64
    road = [0.0] * 64
    road[27] = 1.0
    example = AnchorPretrainExample(
        sample_id="mixed",
        case_key="T10:1",
        anchor_id="a",
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:n", "ROAD:r"),
        candidate_features=(tuple(node), tuple(road)),
        status_label=0,
        candidate_acceptable_indices=(0, 1),
        preferred_candidate_index=0,
        candidate_supervised=True,
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason="multi-solution",
    )
    batch = collate_anchor_pretrain_batch(
        (example,),
        include_candidate_relations=True,
    )
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        structured_anchor_object_decoder=True,
    )
    outputs = TargetAJointNetwork(config)(batch.tensors)

    total, losses = compute_target_a_loss(outputs, batch, config)
    weighted_total, weighted_losses = compute_target_a_loss(
        outputs,
        batch,
        replace(config, anchor_type_loss_weight=3.0),
    )

    assert torch.isfinite(total)
    assert "anchor_type" in losses
    assert "anchor_candidate_validity" in losses
    assert losses["anchor_type"] >= 0.0
    assert weighted_losses["anchor_type"] == pytest.approx(
        losses["anchor_type"]
    )
    assert float(weighted_total.item()) == pytest.approx(
        float(total.item()) + 2.0 * losses["anchor_type"],
        rel=1e-5,
    )


def test_anchor_type_loss_weight_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="anchor type loss weight"):
        TargetAConfig(anchor_type_loss_weight=-1.0).validate()


def test_gate_only_stage_does_not_modify_shared_or_candidate_parameters() -> None:
    examples = []
    for index, gate_label in enumerate((0, 1)):
        candidate = [0.0] * 64
        candidate[index] = 1.0
        examples.append(
            AnchorPretrainExample(
                sample_id=f"gate-{index}",
                case_key=f"T10:{index}",
                anchor_id=f"a-{index}",
                fold=index,
                object_features=tuple(candidate),
                candidate_ids=(f"NODE:n-{index}",),
                candidate_features=(tuple(candidate),),
                status_label=3 if gate_label == 0 else 0,
                candidate_acceptable_indices=(),
                preferred_candidate_index=-1,
                candidate_supervised=False,
                sample_weight=0.7,
                input_hashes=(("input", f"hash-{index}"),),
                label_reason="gate-only",
                gate_label=gate_label,
                gate_supervised=True,
            )
        )
    batch = collate_anchor_pretrain_batch(tuple(examples))
    config = TargetAConfig(
        learned_anchor_gate=True,
        anchor_gate_class_weights=(1.0, 1.0),
        max_epochs=2,
        patience=1,
        learning_rate=0.01,
        torch_num_threads=1,
    )
    model = TargetAJointNetwork(config)
    shared_before = {
        key: value.detach().clone()
        for key, value in model.state_dict().items()
        if not key.startswith("anchor_gate_head.")
    }
    gate_before = {
        key: value.detach().clone()
        for key, value in model.anchor_gate_head.state_dict().items()
    }

    result = train_anchor_gate_stage(
        (batch,),
        (batch,),
        model=model,
        config=config,
        seed=17,
        device=torch.device("cpu"),
    )

    assert result.best_epoch >= 1
    for key, expected in shared_before.items():
        assert torch.equal(result.model.state_dict()[key], expected)
    assert any(
        not torch.equal(result.model.anchor_gate_head.state_dict()[key], value)
        for key, value in gate_before.items()
    )
