from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_road_set_network import (
    AnchorRoadSetConfig,
    AnchorRoadSetNetwork,
    decode_anchor_road_sets,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
)


def _road_feature(value: float) -> tuple[float, ...]:
    row = [0.0] * 64
    row[0] = value
    row[27] = 1.0
    return tuple(row)


def _example(order: tuple[int, ...] = (0, 1, 2)) -> AnchorPretrainExample:
    road_ids = ("r1", "r2", "r3")
    features = (
        _road_feature(0.1),
        _road_feature(0.2),
        _road_feature(0.3),
    )
    arms = (
        ((0.0, 1.0, 0.25, 1.0, 0.0, 0.0, 0.0),),
        ((1.0, 0.0, 0.25, 1.0, 0.0, 0.0, 0.0),),
        ((0.0, -1.0, 0.25, 1.0, 0.0, 0.0, 0.0),),
    )
    local = (
        (1.0, 0.01, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.0, 1.0, 0.2),
        (1.0, 0.02, 1.0, 1.0, 1.0, 1.0, 0.4, 0.4, 0.6, 1.0, 0.0, 0.2),
        (1.0, 0.30, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.5, 0.0, -1.0, 0.2),
    )
    inverse = {source: target for target, source in enumerate(order)}
    return AnchorPretrainExample(
        sample_id="sample",
        case_key="T03:sample",
        anchor_id="anchor",
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=tuple(f"ROAD:{road_ids[index]}" for index in order),
        candidate_features=tuple(features[index] for index in order),
        status_label=0,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=1.0,
        input_hashes=(("input", "digest"),),
        label_reason="road_only_split",
        structural_member_ids=tuple(
            f"ROAD:{road_ids[index]}" for index in order
        ),
        swsd_arm_features=(
            (0.0, 1.0, 0.25, 1.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.25, 1.0, 0.0, 0.0, 0.0),
        ),
        member_arm_features=tuple(arms[index] for index in order),
        member_local_features=tuple(local[index] for index in order),
        member_acceptable_sets=(
            tuple(sorted((inverse[0], inverse[1]))),
        ),
        member_supervised=True,
    )


def _model() -> AnchorRoadSetNetwork:
    return AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
        )
    ).eval()


def test_anchor_road_set_network_decodes_one_nonempty_set() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    outputs = _model()(batch.tensors)
    selection = decode_anchor_road_sets(outputs)

    assert outputs["road_member_logits"].shape == (1, 1, 3)
    assert outputs["road_cardinality_logits"].shape == (1, 1, 3)
    assert torch.isfinite(outputs["road_cardinality_logits"]).all()
    assert int(selection.selected_members.sum().item()) == int(
        selection.cardinality.item()
    )
    assert int(selection.cardinality.item()) >= 1


def test_anchor_road_set_network_is_candidate_order_equivariant() -> None:
    model = _model()
    original = collate_anchor_pretrain_batch((_example(),))
    permuted = collate_anchor_pretrain_batch((_example((2, 0, 1)),))

    original_outputs = model(original.tensors)
    permuted_outputs = model(permuted.tensors)

    original_by_id = dict(
        zip(
            _example().structural_member_ids,
            original_outputs["road_member_logits"][0, 0],
        )
    )
    permuted_by_id = dict(
        zip(
            _example((2, 0, 1)).structural_member_ids,
            permuted_outputs["road_member_logits"][0, 0],
        )
    )
    for member_id in original_by_id:
        assert torch.allclose(
            original_by_id[member_id],
            permuted_by_id[member_id],
            atol=1.0e-6,
        )
    assert torch.allclose(
        original_outputs["road_cardinality_logits"],
        permuted_outputs["road_cardinality_logits"],
        atol=1.0e-6,
    )


def test_anchor_road_set_ordinal_decoder_uses_prefix_boundaries() -> None:
    outputs = {
        "road_member_logits": torch.tensor([[[3.0, 2.0, 1.0, 0.0]]]),
        "road_cardinality_logits": torch.tensor(
            [[[4.0, 2.0, -1.0, -3.0]]]
        ),
        "road_member_mask": torch.ones((1, 1, 4), dtype=torch.bool),
    }

    selection = decode_anchor_road_sets(
        outputs,
        cardinality_mode="ordinal",
    )

    assert int(selection.cardinality.item()) == 2
    assert selection.selected_members.tolist() == [[[True, True, False, False]]]


def test_anchor_road_set_relation_message_branch_is_finite() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
            use_relation_messages=True,
        )
    )

    outputs = model(batch.tensors)

    assert torch.isfinite(outputs["road_member_logits"]).all()
    assert torch.isfinite(outputs["road_cardinality_logits"]).all()


def test_anchor_road_set_two_hop_relation_messages_are_finite() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
            use_relation_messages=True,
            relation_message_layers=2,
        )
    )

    outputs = model(batch.tensors)

    assert torch.isfinite(outputs["road_member_logits"]).all()
    assert torch.isfinite(outputs["road_cardinality_logits"]).all()


def test_anchor_road_set_arm_coverage_boundary_is_finite() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
            use_arm_coverage_boundary=True,
        )
    )

    outputs = model(batch.tensors)

    assert torch.isfinite(outputs["road_member_logits"]).all()
    assert torch.isfinite(outputs["road_cardinality_logits"]).all()


def test_anchor_road_set_geometric_arm_coverage_is_finite() -> None:
    batch = collate_anchor_pretrain_batch((_example(),))
    model = AnchorRoadSetNetwork(
        AnchorRoadSetConfig(
            hidden_dim=32,
            num_heads=4,
            set_layers=1,
            feedforward_dim=64,
            dropout=0.0,
            use_arm_coverage_boundary=True,
            use_geometric_arm_coverage=True,
        )
    )

    outputs = model(batch.tensors)

    assert torch.isfinite(outputs["road_member_logits"]).all()
    assert torch.isfinite(outputs["road_cardinality_logits"]).all()
