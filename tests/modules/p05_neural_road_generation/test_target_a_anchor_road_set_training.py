from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_road_set_network import (
    AnchorRoadSetConfig,
    AnchorRoadSetNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_road_set_training import (
    AnchorRoadSetLossConfig,
    anchor_road_set_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
)


def _example() -> AnchorPretrainExample:
    features = []
    for index in range(4):
        row = [0.0] * 64
        row[0] = index / 4.0
        row[27] = 1.0
        features.append(tuple(row))
    arm = (0.0, 1.0, 0.25, 1.0, 0.0, 0.0, 0.0)
    local = (1.0, 0.01, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.0, 1.0, 0.2)
    return AnchorPretrainExample(
        sample_id="training-sample",
        case_key="T03:sample",
        anchor_id="anchor",
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("ROAD:r1", "ROAD:r2", "ROAD:r3", "ROAD:r4"),
        candidate_features=tuple(features),
        status_label=0,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=1.0,
        input_hashes=(("input", "digest"),),
        label_reason="road_only_split",
        structural_member_ids=(
            "ROAD:r1",
            "ROAD:r2",
            "ROAD:r3",
            "ROAD:r4",
        ),
        swsd_arm_features=(arm,),
        member_arm_features=((arm,), (arm,), (arm,), (arm,)),
        member_local_features=(local, local, local, local),
        member_acceptable_sets=((0, 1), (0, 2)),
        member_supervised=True,
    )


def test_anchor_road_set_loss_is_finite_and_backpropagates() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
        )
    )
    outputs = model(batch.tensors)
    loss = anchor_road_set_loss(
        outputs,
        batch.targets,
        config=AnchorRoadSetLossConfig(),
    )

    assert loss.supervised_count == 1
    assert torch.isfinite(loss.total)
    assert torch.isfinite(loss.member)
    assert torch.isfinite(loss.cardinality)
    assert torch.isfinite(loss.ranking)
    assert torch.isfinite(loss.count_consistency)
    loss.total.backward()
    assert any(
        parameter.grad is not None
        and bool(torch.isfinite(parameter.grad).all())
        for parameter in model.parameters()
    )


def test_anchor_road_set_ordinal_loss_is_finite() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
            cardinality_mode="ordinal",
        )
    )

    loss = anchor_road_set_loss(
        model(batch.tensors),
        batch.targets,
        config=AnchorRoadSetLossConfig(cardinality_mode="ordinal"),
    )

    assert torch.isfinite(loss.total)
    assert torch.isfinite(loss.cardinality)
