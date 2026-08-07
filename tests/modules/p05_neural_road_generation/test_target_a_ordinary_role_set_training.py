from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_role_set_training import (
    DEFAULT_ROLE_SET_CONFIG,
    _new_model,
    _role_set_loss_rows,
    collate_role_set_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
)


def test_role_set_pretraining_uses_joint_compatible_base_keys() -> None:
    model = _new_model(
        64,
        40,
        config=DEFAULT_ROLE_SET_CONFIG,
        device=torch.device("cpu"),
        seed=7,
    )
    state = model.state_dict()
    assert "object_encoder.0.weight" in state
    assert "candidate_encoder.0.weight" in state
    assert "graph_context.0.weight" in state
    assert "member_head.7.weight" in state
    assert "ownership_head.0.weight" in state
    assert "business_role_head.0.weight" in state
    assert model.cardinality_count == 67


def test_role_set_collator_omits_unused_graph_tensors_and_backpropagates() -> None:
    example = OrdinaryRoadSetExample(
        case_key="case",
        segment_id="segment",
        fold=0,
        object_features=(0.0,) * 64,
        road_ids=("a", "b"),
        sources=("RCSD", "RCSD"),
        start_node_ids=("n0", "n1"),
        end_node_ids=("n1", "n2"),
        anchor_features=(),
        teacher_anchor_relations=((), ()),
        oof_anchor_relations=((), ()),
        teacher_features=((0.0,) * 40, (1.0,) * 40),
        oof_features=((0.1,) * 40, (0.9,) * 40),
        decision=1,
        target_indices=(0,),
        ownership_targets=(0, 2),
        ownership_task_mask=(True, True),
        business_role_targets=(1, 0),
        business_role_task_mask=(True, True),
        sample_weight=1.0,
        oof_anchor_release_ready=True,
    )
    batch = collate_role_set_batch(
        [example],
        feature_sources="oof",
        device=torch.device("cpu"),
    )
    assert "adjacency" not in batch
    assert "anchor_relations" not in batch
    model = _new_model(
        64,
        40,
        config=DEFAULT_ROLE_SET_CONFIG,
        device=torch.device("cpu"),
        seed=9,
    )
    outputs = model(
        object_features=batch["objects"],
        candidate_features=batch["candidates"],
        candidate_mask=batch["mask"],
    )
    loss = _role_set_loss_rows(
        outputs,
        batch,
        DEFAULT_ROLE_SET_CONFIG,
        cardinality_weights=None,
    ).mean()
    loss.backward()
    assert model.object_encoder[0].weight.grad is not None
    assert model.ownership_head[0].weight.grad is not None


def test_count_aware_role_loss_reaches_count_and_member_heads() -> None:
    example = OrdinaryRoadSetExample(
        case_key="case",
        segment_id="large",
        fold=0,
        object_features=(0.0,) * 64,
        road_ids=tuple(str(index) for index in range(10)),
        sources=("RCSD",) * 10,
        start_node_ids=tuple(f"n{index}" for index in range(10)),
        end_node_ids=tuple(f"n{index + 1}" for index in range(10)),
        anchor_features=(),
        teacher_anchor_relations=((),) * 10,
        oof_anchor_relations=((),) * 10,
        teacher_features=tuple((0.1,) * 40 for _ in range(10)),
        oof_features=tuple((0.2,) * 40 for _ in range(10)),
        decision=1,
        target_indices=tuple(range(8)),
        ownership_targets=(1,) * 8 + (0, 0),
        ownership_task_mask=(True,) * 10,
        business_role_targets=(1,) * 8 + (0, 0),
        business_role_task_mask=(True,) * 10,
        sample_weight=1.0,
        oof_anchor_release_ready=True,
    )
    batch = collate_role_set_batch(
        [example],
        feature_sources="oof",
        device=torch.device("cpu"),
    )
    model = _new_model(
        64,
        40,
        config=DEFAULT_ROLE_SET_CONFIG,
        device=torch.device("cpu"),
        seed=11,
        count_aware=True,
    )
    outputs = model(
        object_features=batch["objects"],
        candidate_features=batch["candidates"],
        candidate_mask=batch["mask"],
    )
    _role_set_loss_rows(
        outputs,
        batch,
        DEFAULT_ROLE_SET_CONFIG,
        cardinality_weights=None,
    ).mean().backward()
    assert model.count_head[0].weight.grad is not None
    assert model.cardinality_ordinal_head[0].weight.grad is not None
    assert model.member_head[7].weight.grad is not None
