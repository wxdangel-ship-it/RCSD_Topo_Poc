from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_network import (
    TargetAOrdinarySetExpansionDecoder,
)


def test_set_expansion_scores_next_road_and_stop_for_multiple_states() -> None:
    model = TargetAOrdinarySetExpansionDecoder(
        object_feature_dim=5,
        candidate_feature_dim=7,
        anchor_feature_dim=3,
        anchor_relation_dim=4,
        road_relation_dim=2,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=8,
        dropout=0.0,
    )
    objects = torch.randn(2, 5)
    candidates = torch.randn(2, 4, 7)
    mask = torch.tensor(
        [[True, True, True, False], [True, True, True, True]]
    )
    adjacency = torch.eye(4, dtype=torch.bool).unsqueeze(0).repeat(2, 1, 1)
    anchors = torch.randn(2, 2, 3)
    anchor_mask = torch.ones(2, 2, dtype=torch.bool)
    anchor_relations = torch.randn(2, 4, 2, 4)
    road_relations = torch.zeros(2, 4, 4, 2)
    road_relations[:, 0, 1] = torch.tensor([1.0, 0.5])
    road_relations[:, 1, 0] = torch.tensor([1.0, 0.5])
    encoded = model(
        object_features=objects,
        candidate_features=candidates,
        candidate_mask=mask,
        adjacency=adjacency,
        anchor_features=anchors,
        anchor_mask=anchor_mask,
        anchor_relations=anchor_relations,
        road_relations=road_relations,
    )
    selected = torch.zeros(2, 3, 4, dtype=torch.bool)
    selected[:, 1, 0] = True
    selected[:, 2, :2] = True
    outputs = model.decode_next(
        encoded_outputs=encoded,
        candidate_mask=mask,
        road_relations=road_relations,
        selected_masks=selected,
    )
    assert outputs["next_road_logits"].shape == (2, 3, 4)
    assert outputs["stop_logits"].shape == (2, 3)
    assert outputs["selected_count"].tolist() == [[0, 1, 2], [0, 1, 2]]
    assert outputs["next_road_logits"][0, 1, 0] < -1e20
    assert outputs["next_road_logits"][0, 0, 3] < -1e20
    loss = (
        outputs["next_road_logits"][mask.unsqueeze(1).expand(-1, 3, -1)]
        .clamp_min(-100.0)
        .mean()
        + outputs["stop_logits"].mean()
    )
    loss.backward()
    assert model.next_road_head[-1].weight.grad is not None
    assert model.stop_head[-1].weight.grad is not None


def test_component_action_decoder_separates_frontier_start_and_stop() -> None:
    model = TargetAOrdinarySetExpansionDecoder(
        object_feature_dim=5,
        candidate_feature_dim=7,
        anchor_feature_dim=3,
        anchor_relation_dim=4,
        road_relation_dim=2,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=8,
        component_action_decoder=True,
        dropout=0.0,
    )
    objects = torch.randn(1, 5)
    candidates = torch.randn(1, 4, 7)
    mask = torch.ones(1, 4, dtype=torch.bool)
    adjacency = torch.eye(4, dtype=torch.bool).unsqueeze(0)
    anchors = torch.randn(1, 2, 3)
    anchor_mask = torch.ones(1, 2, dtype=torch.bool)
    anchor_relations = torch.randn(1, 4, 2, 4)
    road_relations = torch.zeros(1, 4, 4, 2)
    road_relations[0, 0, 1, 0] = 1.0
    road_relations[0, 1, 0, 0] = 1.0
    encoded = model(
        object_features=objects,
        candidate_features=candidates,
        candidate_mask=mask,
        adjacency=adjacency,
        anchor_features=anchors,
        anchor_mask=anchor_mask,
        anchor_relations=anchor_relations,
        road_relations=road_relations,
    )
    selected = torch.tensor([[[True, False, False, False]]])
    access_seeds = torch.tensor([[True, False, True, False]])
    outputs = model.decode_next(
        encoded_outputs=encoded,
        candidate_mask=mask,
        road_relations=road_relations,
        selected_masks=selected,
        access_seed_masks=access_seeds,
    )
    assert outputs["frontier_masks"].tolist() == [
        [[False, True, False, False]]
    ]
    assert outputs["start_masks"].tolist() == [
        [[False, False, True, True]]
    ]
    assert outputs["next_road_logits"][0, 0, 3] > -1e20
    probabilities = torch.cat(
        (
            outputs["next_road_logits"][0, 0],
            outputs["stop_logits"][0, 0].unsqueeze(0),
        )
    ).exp()
    assert torch.isclose(probabilities.sum(), torch.tensor(1.0))
    loss = -outputs["stop_logits"].mean()
    loss.backward()
    assert model.component_action_head[-1].weight.grad is not None
