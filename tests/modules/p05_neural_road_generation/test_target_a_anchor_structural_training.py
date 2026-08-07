from __future__ import annotations

from types import SimpleNamespace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_decision import (
    TargetAAnchorStructuralJointOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_training import (
    TargetAAnchorStructuralLossConfig,
    TargetAAnchorStructuralTargets,
    compute_anchor_structural_loss,
)


def _output(*, requires_grad: bool = True) -> TargetAAnchorStructuralJointOutput:
    def tensor(shape: tuple[int, ...]) -> torch.Tensor:
        return torch.zeros(shape, requires_grad=requires_grad)

    return TargetAAnchorStructuralJointOutput(
        relation_logits=tensor((1, 1, 3)),
        object_type_logits=tensor((1, 1, 2)),
        cardinality_logits=tensor((1, 1, 4)),
        ordinal_cardinality_logits=tensor((1, 1, 3)),
        member_logits=tensor((1, 1, 3)),
        decision_context=tensor((1, 1, 8)),
    )


def _batch() -> SimpleNamespace:
    return SimpleNamespace(
        anchor_member_mask=torch.tensor([[[True, True, True]]]),
        anchor_member_is_road=torch.tensor([[[False, True, True]]]),
    )


def _targets() -> TargetAAnchorStructuralTargets:
    acceptable = torch.zeros((1, 1, 2, 3), dtype=torch.bool)
    acceptable[0, 0, 0, 1] = True
    acceptable[0, 0, 1, 1:] = True
    return TargetAAnchorStructuralTargets(
        relation_target=torch.tensor([[1]], dtype=torch.long),
        relation_task_mask=torch.tensor([[True]]),
        member_acceptable_sets=acceptable,
        member_acceptable_set_mask=torch.tensor([[[True, True]]]),
        member_task_mask=torch.tensor([[True]]),
        sample_weights=torch.tensor([[0.7]]),
    )


def test_structural_loss_supports_multiple_acceptable_member_sets() -> None:
    output = _output()

    loss, parts = compute_anchor_structural_loss(
        output,
        batch=_batch(),  # type: ignore[arg-type]
        targets=_targets(),
        config=TargetAAnchorStructuralLossConfig(),
    )
    loss.backward()

    assert torch.isfinite(loss)
    assert parts["relation_loss"] > 0.0
    assert parts["object_type_loss"] > 0.0
    assert parts["cardinality_loss"] > 0.0
    assert parts["ordinal_cardinality_loss"] > 0.0
    assert parts["member_loss"] > 0.0
    assert output.relation_logits.grad is not None
    assert output.member_logits.grad is not None


def test_structural_loss_prefers_either_acceptable_cardinality() -> None:
    one_member = _output(requires_grad=False)
    one_member.cardinality_logits[0, 0, 0] = 8.0
    two_members = _output(requires_grad=False)
    two_members.cardinality_logits[0, 0, 1] = 8.0
    invalid_three = _output(requires_grad=False)
    invalid_three.cardinality_logits[0, 0, 2] = 8.0
    config = TargetAAnchorStructuralLossConfig(
        relation_weight=0.0,
        object_type_weight=0.0,
        cardinality_weight=1.0,
        ordinal_cardinality_weight=0.0,
        member_weight=0.0,
    )

    first, _ = compute_anchor_structural_loss(
        one_member,
        batch=_batch(),  # type: ignore[arg-type]
        targets=_targets(),
        config=config,
    )
    second, _ = compute_anchor_structural_loss(
        two_members,
        batch=_batch(),  # type: ignore[arg-type]
        targets=_targets(),
        config=config,
    )
    third, _ = compute_anchor_structural_loss(
        invalid_three,
        batch=_batch(),  # type: ignore[arg-type]
        targets=_targets(),
        config=config,
    )

    assert first.item() < third.item()
    assert second.item() < third.item()


def test_structural_loss_keeps_relation_and_member_masks_independent() -> None:
    targets = _targets()
    targets = TargetAAnchorStructuralTargets(
        relation_target=targets.relation_target,
        relation_task_mask=torch.tensor([[False]]),
        member_acceptable_sets=targets.member_acceptable_sets,
        member_acceptable_set_mask=targets.member_acceptable_set_mask,
        member_task_mask=targets.member_task_mask,
        sample_weights=targets.sample_weights,
    )

    _, parts = compute_anchor_structural_loss(
        _output(),
        batch=_batch(),  # type: ignore[arg-type]
        targets=targets,
        config=TargetAAnchorStructuralLossConfig(),
    )

    assert parts["relation_loss"] == 0.0
    assert parts["member_loss"] > 0.0


def test_inactive_repeated_anchor_may_retain_label_without_member_loss() -> None:
    source = _targets()
    targets = TargetAAnchorStructuralTargets(
        relation_target=source.relation_target,
        relation_task_mask=source.relation_task_mask,
        member_acceptable_sets=source.member_acceptable_sets,
        member_acceptable_set_mask=source.member_acceptable_set_mask,
        member_task_mask=torch.tensor([[False]]),
        sample_weights=source.sample_weights,
    )

    _, parts = compute_anchor_structural_loss(
        _output(),
        batch=_batch(),  # type: ignore[arg-type]
        targets=targets,
        config=TargetAAnchorStructuralLossConfig(),
    )

    assert parts["relation_loss"] > 0.0
    assert parts["object_type_loss"] == 0.0
    assert parts["cardinality_loss"] == 0.0
    assert parts["ordinal_cardinality_loss"] == 0.0
    assert parts["member_loss"] == 0.0


def test_inactive_padded_anchor_may_have_zero_sample_weight() -> None:
    source = _targets()
    acceptable_sets = torch.cat(
        (
            source.member_acceptable_sets,
            torch.zeros_like(source.member_acceptable_sets),
        ),
        dim=1,
    )
    targets = TargetAAnchorStructuralTargets(
        relation_target=torch.tensor([[1, 0]], dtype=torch.long),
        relation_task_mask=torch.tensor([[True, False]]),
        member_acceptable_sets=acceptable_sets,
        member_acceptable_set_mask=torch.tensor(
            [[[True, True], [False, False]]]
        ),
        member_task_mask=torch.tensor([[True, False]]),
        sample_weights=torch.tensor([[0.7, 0.0]]),
    )
    batch = SimpleNamespace(
        anchor_member_mask=torch.tensor(
            [[[True, True, True], [False, False, False]]]
        ),
        anchor_member_is_road=torch.tensor(
            [[[False, True, True], [False, False, False]]]
        ),
    )

    targets.validate(
        batch=batch,  # type: ignore[arg-type]
        max_cardinality=4,
    )
