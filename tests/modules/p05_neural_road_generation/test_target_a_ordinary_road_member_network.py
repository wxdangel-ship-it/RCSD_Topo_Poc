from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryAnchorRoadGraphDecoder,
    TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    TargetAOrdinaryJointRoadGraphDecoder,
    TargetAOrdinaryRoadSetDecoder,
    TargetAOrdinaryUseRoadGraphDecoder,
    parameter_count,
)


def test_road_set_decoder_emits_structured_heads() -> None:
    model = TargetAOrdinaryRoadSetDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        cardinality_count=7,
        dropout=0.0,
    )
    outputs = model(
        object_features=torch.randn(2, 8),
        candidate_features=torch.randn(2, 5, 12),
        candidate_mask=torch.tensor(
            [
                [True, True, True, False, False],
                [True, True, False, False, False],
            ]
        ),
    )
    assert outputs["decision_logits"].shape == (2, 2)
    assert outputs["cardinality_logits"].shape == (2, 7)
    assert outputs["member_logits"].shape == (2, 5)
    assert torch.isfinite(outputs["member_logits"]).all()
    assert parameter_count(model) > 0


def test_use_road_graph_decoder_consumes_endpoint_adjacency() -> None:
    model = TargetAOrdinaryUseRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
    mask = torch.tensor([[True, True, True, False]])
    adjacency = torch.zeros(1, 4, 4, dtype=torch.bool)
    adjacency[:, 0, 1] = True
    adjacency[:, 1, 0] = True
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 4, 12),
        candidate_mask=mask,
        adjacency=adjacency,
    )
    assert outputs["member_logits"].shape == (1, 4)
    assert outputs["cardinality_logits"].shape == (1, 7)


def test_use_road_graph_decoder_consumes_geometric_edge_evidence() -> None:
    model = TargetAOrdinaryUseRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        road_relation_dim=3,
        cardinality_count=7,
        dropout=0.0,
    )
    relations = torch.zeros(1, 3, 3, 3)
    relations[:, 0, 1] = torch.tensor([0.0, 1.0, 0.8])
    relations[:, 1, 0] = relations[:, 0, 1]
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 3, 12),
        candidate_mask=torch.tensor([[True, True, True]]),
        adjacency=torch.tensor(
            [[[False, True, False], [True, False, False], [False] * 3]]
        ),
        road_relations=relations,
    )
    assert outputs["member_logits"].shape == (1, 3)
    assert torch.isfinite(outputs["member_logits"]).all()


def test_joint_road_graph_decoder_adds_keep_use_decision() -> None:
    model = TargetAOrdinaryJointRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        attention_scope="FULL",
        cardinality_count=7,
        dropout=0.0,
    )
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 3, 12),
        candidate_mask=torch.tensor([[True, True, True]]),
        adjacency=torch.ones(1, 3, 3, dtype=torch.bool),
    )
    assert outputs["decision_logits"].shape == (1, 2)
    assert outputs["cardinality_logits"].shape == (1, 7)
    assert outputs["member_logits"].shape == (1, 3)
    assert model.attention_scope == "FULL"


def test_anchor_road_decoder_keeps_required_anchor_identity() -> None:
    model = TargetAOrdinaryAnchorRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        anchor_feature_dim=3,
        anchor_relation_dim=4,
        hidden_dim=16,
        context_dim=24,
        graph_layers=2,
        num_heads=4,
        attention_scope="ENDPOINT_THEN_FULL",
        cardinality_count=7,
        dropout=0.0,
    )
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 3, 12),
        candidate_mask=torch.tensor([[True, True, True]]),
        adjacency=torch.eye(3, dtype=torch.bool).unsqueeze(0),
        anchor_features=torch.tensor(
            [[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]
        ),
        anchor_mask=torch.tensor([[True, True]]),
        anchor_relations=torch.randn(1, 3, 2, 4),
    )
    assert outputs["decision_logits"].shape == (1, 2)
    assert outputs["cardinality_logits"].shape == (1, 7)
    assert outputs["member_logits"].shape == (1, 3)


def test_anchor_road_role_decoder_emits_business_heads() -> None:
    model = TargetAOrdinaryAnchorRoadRoleGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=7,
        ownership_count=3,
        business_role_count=4,
        dropout=0.0,
    )
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 3, 12),
        candidate_mask=torch.tensor([[True, True, False]]),
        adjacency=torch.eye(3, dtype=torch.bool).unsqueeze(0),
        anchor_features=torch.tensor([[[1.0, 0.0, 0.0]]]),
        anchor_mask=torch.tensor([[True]]),
        anchor_relations=torch.randn(1, 3, 1, 4),
    )
    assert outputs["member_logits"].shape == (1, 3)
    assert outputs["ownership_logits"].shape == (1, 3, 3)
    assert outputs["business_role_logits"].shape == (1, 3, 4)


def test_auxiliary_business_heads_do_not_rewrite_member_logits() -> None:
    model = TargetAOrdinaryAnchorRoadRoleGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=7,
        fuse_business_into_membership=False,
        dropout=0.0,
    )
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 2, 12),
        candidate_mask=torch.tensor([[True, True]]),
        adjacency=torch.eye(2, dtype=torch.bool).unsqueeze(0),
        anchor_features=torch.tensor([[[1.0, 0.0, 0.0]]]),
        anchor_mask=torch.tensor([[True]]),
        anchor_relations=torch.randn(1, 2, 1, 4),
    )
    assert torch.equal(
        outputs["member_logits"],
        outputs["base_member_logits"],
    )


def test_component_edge_decoder_emits_symmetric_pair_scores() -> None:
    model = TargetAOrdinaryAnchorRoadRoleGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        road_relation_dim=3,
        cardinality_count=7,
        ownership_count=3,
        business_role_count=4,
        fuse_business_into_membership=False,
        component_edge_decoder=True,
        dropout=0.0,
    )
    relations = torch.zeros(1, 3, 3, 3)
    relations[:, 0, 1] = torch.tensor([0.25, 1.0, -0.5])
    relations[:, 1, 0] = relations[:, 0, 1]
    component_adjacency = torch.tensor(
        [[[False, True, False], [True, False, False], [False] * 3]]
    )
    outputs = model(
        object_features=torch.randn(1, 8),
        candidate_features=torch.randn(1, 3, 12),
        candidate_mask=torch.tensor([[True, True, True]]),
        adjacency=component_adjacency,
        component_adjacency=component_adjacency,
        road_relations=relations,
        anchor_features=torch.tensor([[[1.0, 0.0, 0.0]]]),
        anchor_mask=torch.tensor([[True]]),
        anchor_relations=torch.randn(1, 3, 1, 4),
    )
    assert outputs["component_edge_logits"].shape == (1, 3, 3)
    assert torch.equal(
        outputs["component_edge_logits"],
        outputs["component_edge_logits"].transpose(1, 2),
    )
    assert torch.equal(
        outputs["member_logits"],
        outputs["base_component_member_logits"],
    )
