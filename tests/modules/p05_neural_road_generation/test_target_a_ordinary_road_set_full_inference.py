from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryAnchorRoadGraphDecoder,
    TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    TargetAOrdinaryJointRoadGraphDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetTrainingConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_set_full_inference import (
    _load_checkpoint,
    ordinary_state_from_prediction,
)


def test_full_inference_state_keeps_joint_decision_and_complete_roads() -> None:
    state = ordinary_state_from_prediction(
        {
            "case_key": "case",
            "segment_id": "segment",
            "fold": 2,
            "predicted_decision": "USE_RCSD",
            "selected_road_ids": ["road-a", "road-b"],
            "decision_confidence": 0.8,
            "confidence": 0.6,
        }
    )
    assert state["raw_carrier_decision"] == "USE_RCSD"
    assert state["complete_road_ids"] == ["road-a", "road-b"]
    assert state["road_set_available"]
    assert not state["hierarchical_release_ready"]
    assert state["access_predictions"] == []
    assert not state["feature_uses_truth"]
    assert state["terminal_input_count"] == 0


def test_full_inference_loads_joint_graph_checkpoint(
    tmp_path: Path,
) -> None:
    config = OrdinaryRoadSetTrainingConfig(
        hidden_dim=16,
        context_dim=24,
        structured_graph_decoder=True,
        graph_layers=1,
        graph_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
    model = TargetAOrdinaryJointRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
    checkpoint = tmp_path / "graph.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "config": asdict(config),
            "object_dim": 8,
            "candidate_dim": 12,
            "state_dict": model.state_dict(),
        },
        checkpoint,
    )
    loaded, loaded_config = _load_checkpoint(
        checkpoint,
        device=torch.device("cpu"),
    )
    assert isinstance(loaded, TargetAOrdinaryJointRoadGraphDecoder)
    assert loaded_config.structured_graph_decoder


def test_full_inference_loads_anchor_road_checkpoint(
    tmp_path: Path,
) -> None:
    config = OrdinaryRoadSetTrainingConfig(
        hidden_dim=16,
        context_dim=24,
        structured_graph_decoder=True,
        anchor_relation_decoder=True,
        graph_layers=1,
        graph_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
    model = TargetAOrdinaryAnchorRoadGraphDecoder(
        object_feature_dim=8,
        candidate_feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
    checkpoint = tmp_path / "anchor-road.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "config": asdict(config),
            "object_dim": 8,
            "candidate_dim": 12,
            "state_dict": model.state_dict(),
        },
        checkpoint,
    )
    loaded, loaded_config = _load_checkpoint(
        checkpoint,
        device=torch.device("cpu"),
    )
    assert isinstance(loaded, TargetAOrdinaryAnchorRoadGraphDecoder)
    assert loaded_config.anchor_relation_decoder


def test_full_inference_loads_anchor_road_role_checkpoint(
    tmp_path: Path,
) -> None:
    config = OrdinaryRoadSetTrainingConfig(
        hidden_dim=16,
        context_dim=24,
        structured_graph_decoder=True,
        anchor_relation_decoder=True,
        ownership_role_decoder=True,
        graph_layers=1,
        graph_heads=4,
        cardinality_count=7,
        dropout=0.0,
    )
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
    checkpoint = tmp_path / "anchor-road-role.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "config": asdict(config),
            "object_dim": 8,
            "candidate_dim": 12,
            "state_dict": model.state_dict(),
        },
        checkpoint,
    )
    loaded, loaded_config = _load_checkpoint(
        checkpoint,
        device=torch.device("cpu"),
    )
    assert isinstance(loaded, TargetAOrdinaryAnchorRoadRoleGraphDecoder)
    assert loaded_config.ownership_role_decoder
