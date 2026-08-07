from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    TASK_CLASSES,
    JunctionFirstExample,
    collate_junction_first,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_network import (
    JunctionFirstConfig,
    JunctionFirstNetwork,
    parameter_count,
)


def test_step1_is_physically_independent_from_later_raw_channels() -> None:
    model = JunctionFirstNetwork(_small_config()).eval()
    first = _example()
    changed = replace(
        first,
        object_features=tuple([*first.object_features[:4], *([9.0] * 60)]),
        candidate_features=((7.0,) * 64,),
    )
    with torch.no_grad():
        left = model(collate_junction_first([first]))["t07_step1_logits"]
        right = model(collate_junction_first([changed]))["t07_step1_logits"]
    assert torch.equal(left, right)


def test_downstream_candidate_gradient_cannot_rewrite_t07_heads() -> None:
    model = JunctionFirstNetwork(_small_config())
    batch = collate_junction_first([_example()])
    outputs = model(batch, teacher_forcing_ratio=0.0)
    outputs["candidate_logits"].sum().backward()
    assert all(parameter.grad is None for parameter in model.step1_head.parameters())
    assert all(parameter.grad is None for parameter in model.step2_head.parameters())
    assert any(parameter.grad is not None for parameter in model.candidate_score.parameters())


def test_frozen_default_network_is_within_parameter_range() -> None:
    model = JunctionFirstNetwork()
    assert 10_000_000 <= parameter_count(model) <= 20_000_000


def _small_config() -> JunctionFirstConfig:
    return JunctionFirstConfig(
        hidden_dim=64,
        num_heads=8,
        feedforward_dim=256,
        candidate_layers=1,
        member_layers=1,
        trunk_layers=1,
        dropout=0.0,
        min_parameter_count=0,
        max_parameter_count=10_000_000,
    )


def _example() -> JunctionFirstExample:
    labels = {task: 0 for task in TASK_CLASSES}
    masks = {task: True for task in TASK_CLASSES}
    return JunctionFirstExample(
        sample_id="anchor:1",
        case_key="T10:case",
        family="T10",
        anchor_id="J1",
        fold=1,
        sample_weight=0.7,
        stage1_features=(0.0,) * 11,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:N1",),
        candidate_features=((0.0,) * 64,),
        member_ids=("NODE:N1",),
        member_features=((0.0,) * 12,),
        task_labels=labels,
        task_masks=masks,
        candidate_acceptable_indices=(0,),
        candidate_supervised=True,
        member_acceptable_sets=((0,),),
        member_supervised=True,
    )
