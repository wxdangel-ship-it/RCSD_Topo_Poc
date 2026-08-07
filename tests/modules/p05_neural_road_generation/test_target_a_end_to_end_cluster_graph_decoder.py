from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_cluster_graph_decoder import (
    TargetAClusterGraphSetDecoder,
    TargetAClusterGraphSetDecoderConfig,
    build_endpoint_cluster_indices,
    compute_cluster_graph_set_loss,
    decode_cluster_graph_set_proposals,
)


def _inputs() -> dict[str, torch.Tensor]:
    relations = torch.zeros((1, 5, 5, 13), dtype=torch.float32)
    relations[0, 0, 1, 0] = 1.0
    relations[0, 1, 0, 0] = 1.0
    relations[0, 2, 3, 0] = 1.0
    relations[0, 3, 2, 0] = 1.0
    return {
        "candidate_signals": torch.randn(1, 5, 7),
        "road_relations": relations,
        "candidate_sources": torch.tensor([[1, 1, 1, 1, 0]]),
        "candidate_mask": torch.ones((1, 5), dtype=torch.bool),
        "effective_decision": torch.tensor([1]),
    }


def test_endpoint_clusters_are_source_gated_and_disconnected() -> None:
    values = _inputs()
    indices, mask = build_endpoint_cluster_indices(
        road_relations=values["road_relations"],
        candidate_sources=values["candidate_sources"],
        candidate_mask=values["candidate_mask"],
        effective_decision=values["effective_decision"],
    )

    assert indices.tolist() == [[0, 0, 1, 1, -1]]
    assert mask.tolist() == [[True, True]]


def test_cluster_decoder_outputs_road_and_cluster_heads() -> None:
    values = _inputs()
    indices, mask = build_endpoint_cluster_indices(
        road_relations=values["road_relations"],
        candidate_sources=values["candidate_sources"],
        candidate_mask=values["candidate_mask"],
        effective_decision=values["effective_decision"],
    )
    model = TargetAClusterGraphSetDecoder(
        TargetAClusterGraphSetDecoderConfig(
            signal_dim=7,
            hidden_dim=16,
            local_layer_count=1,
            cluster_layer_count=1,
            attention_head_count=4,
            maximum_road_cardinality=5,
            maximum_cluster_cardinality=3,
            dropout=0.0,
        )
    )

    outputs = model(
        **values,
        cluster_indices=indices,
        cluster_mask=mask,
    )

    assert outputs["member_logits"].shape == (1, 5)
    assert outputs["cluster_member_logits"].shape == (1, 2)
    assert outputs["cardinality_logits"].shape == (1, 6)
    assert outputs["cluster_cardinality_logits"].shape == (1, 4)
    assert outputs["allowed_mask"].tolist() == [
        [True, True, True, True, False]
    ]


def test_cluster_loss_masks_target_outside_locked_source() -> None:
    values = _inputs()
    indices, mask = build_endpoint_cluster_indices(
        road_relations=values["road_relations"],
        candidate_sources=values["candidate_sources"],
        candidate_mask=values["candidate_mask"],
        effective_decision=values["effective_decision"],
    )
    model = TargetAClusterGraphSetDecoder(
        TargetAClusterGraphSetDecoderConfig(
            signal_dim=7,
            hidden_dim=16,
            local_layer_count=1,
            cluster_layer_count=1,
            attention_head_count=4,
            maximum_road_cardinality=5,
            maximum_cluster_cardinality=3,
            dropout=0.0,
        )
    )
    outputs = model(
        **values,
        cluster_indices=indices,
        cluster_mask=mask,
    )
    targets = torch.tensor([[True, False, True, False, True]])
    losses = compute_cluster_graph_set_loss(
        outputs,
        member_targets=targets,
        task_mask=torch.tensor([True]),
        sample_weights=torch.tensor([1.0]),
    )

    assert losses["target_outside_source_gate"].tolist() == [True]
    assert losses["effective_task_mask"].tolist() == [False]
    assert torch.isfinite(losses["loss"])


def test_cluster_decoder_proposals_never_select_other_source() -> None:
    values = _inputs()
    indices, mask = build_endpoint_cluster_indices(
        road_relations=values["road_relations"],
        candidate_sources=values["candidate_sources"],
        candidate_mask=values["candidate_mask"],
        effective_decision=values["effective_decision"],
    )
    model = TargetAClusterGraphSetDecoder(
        TargetAClusterGraphSetDecoderConfig(
            signal_dim=7,
            hidden_dim=16,
            local_layer_count=1,
            cluster_layer_count=1,
            attention_head_count=4,
            maximum_road_cardinality=5,
            maximum_cluster_cardinality=3,
            dropout=0.0,
        )
    )
    outputs = model(
        **values,
        cluster_indices=indices,
        cluster_mask=mask,
    )

    proposals = decode_cluster_graph_set_proposals(outputs)

    assert proposals[0]
    assert all(
        4 not in row["selected_indices"] for row in proposals[0]
    )
