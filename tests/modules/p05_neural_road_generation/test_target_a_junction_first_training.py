from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    TASK_CLASSES,
    JunctionFirstExample,
    collate_junction_first,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_network import (
    JunctionFirstConfig,
    JunctionFirstNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_training import (
    compute_junction_first_loss,
    decode_member_sets,
    teacher_forcing_ratio,
)


def test_junction_first_loss_is_finite_and_decodes_one_type() -> None:
    batch = collate_junction_first([_example()])
    model = JunctionFirstNetwork(
        JunctionFirstConfig(
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
    )
    outputs = model(
        batch,
        teacher_labels=batch.task_labels,
        teacher_masks=batch.task_masks,
        teacher_forcing_ratio=1.0,
    )
    loss, metrics = compute_junction_first_loss(outputs, batch)
    assert torch.isfinite(loss)
    loss.backward()
    assert metrics["total_loss"] > 0.0
    decoded = decode_member_sets(outputs, batch)
    assert decoded.shape == batch.member_mask.shape
    assert not bool((decoded & ~batch.member_mask).any())


def test_teacher_forcing_schedule_ends_in_free_run() -> None:
    assert teacher_forcing_ratio(1, 12) == 1.0
    assert 0.0 < teacher_forcing_ratio(5, 12) < 1.0
    assert teacher_forcing_ratio(8, 12) == 0.0
    assert teacher_forcing_ratio(12, 12) == 0.0


def _example() -> JunctionFirstExample:
    labels = {task: 0 for task in TASK_CLASSES}
    masks = {task: True for task in TASK_CLASSES}
    return JunctionFirstExample(
        sample_id="anchor:1",
        case_key="T10:case",
        family="T10",
        anchor_id="J1",
        fold=0,
        sample_weight=1.0,
        stage1_features=(0.0,) * 11,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:N1", "ROAD:R1"),
        candidate_features=((0.0,) * 64, (1.0,) * 64),
        member_ids=("NODE:N1", "ROAD:R1"),
        member_features=((0.0,) * 12, (1.0,) * 12),
        task_labels=labels,
        task_masks=masks,
        candidate_acceptable_indices=(0,),
        candidate_supervised=True,
        member_acceptable_sets=((0,),),
        member_supervised=True,
    )
