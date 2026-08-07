from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    build_segment_joint_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    AdvanceRightRecallExample,
    AdvanceRightRecallPlan,
    EndToEndRecallExample,
    build_advance_right_dependency_subgraphs,
    build_advance_right_recall_examples,
    collate_end_to_end_recall_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from tests.modules.p05_neural_road_generation.test_target_a_case_joint_data import (
    _anchor,
    _ordinary,
)


def _feature(value: float) -> tuple[float, ...]:
    return (value,) + (0.0,) * 63


def test_recall_candidates_group_roads_without_oof_condition_features() -> None:
    rows = [
        {
            "case_key": "T10:1",
            "object_id": "ar-1",
            "fold": 0,
            "truth_plan_type": "RCSD_ONLY",
            "acceptable_candidate_groups": [["r1"], ["r2"]],
            "candidate_supervised": True,
            "label_weight": 0.7,
            "source_context": {"owner_segment_id": "s1"},
            "target_context": {"owner_segment_id": "s2"},
            "base_feature": {
                "feature_uses_truth": False,
                "candidate_rows": [
                    {
                        "bundle_id": "b1",
                        "candidate_road_id": "r1",
                        "local_feature_values": [1.0] * 50,
                        "oof_conditioned_feature_values": [999.0] * 60,
                    },
                    {
                        "bundle_id": "b1",
                        "candidate_road_id": "r2",
                        "local_feature_values": [2.0] * 50,
                        "oof_conditioned_feature_values": [999.0] * 60,
                    },
                ],
            },
        }
    ]

    example = build_advance_right_recall_examples(rows)[0]

    assert example.acceptable_plan_ids == frozenset({"RCSD_SET:r1|r2"})
    assert example.task_mask
    bundle = next(
        row for row in example.plans if row.plan_id == "RCSD_SET:r1|r2"
    )
    assert bundle.road_ids == ("r1", "r2")
    assert 999.0 not in bundle.feature_values


def test_recall_labels_keep_side_truth_outside_inference_features() -> None:
    rows = [
        {
            "case_key": "T10:1",
            "object_id": "ar-1",
            "fold": 0,
            "truth_plan_type": "MIXED_SPLICE",
            "acceptable_candidate_groups": [["r1"]],
            "candidate_supervised": True,
            "label_weight": 0.7,
            "source_context": {
                "owner_segment_id": "s1",
                "data_source": "RCSD",
                "road_members": [{"road_id": "source-main"}],
                "access_rows": [{"road_id": "source-access"}],
            },
            "target_context": {
                "owner_segment_id": "s2",
                "data_source": "SWSD",
                "road_members": [{"road_id": "target-main"}],
                "access_rows": [{"road_id": "target-access"}],
            },
            "base_feature": {
                "feature_uses_truth": False,
                "candidate_rows": [
                    {
                        "bundle_id": "b1",
                        "candidate_road_id": "r1",
                        "local_feature_values": [1.0] * 50,
                    }
                ],
            },
        }
    ]

    example = build_advance_right_recall_examples(rows)[0]

    assert example.source_truth_decision == "USE_RCSD"
    assert example.target_truth_decision == "KEEP_SWSD"
    assert example.source_truth_road_ids == ("source-main",)
    assert example.target_truth_access_road_ids == ("target-access",)
    assert all(len(plan.feature_values) == 64 for plan in example.plans)


def test_advance_right_graph_adds_only_immediate_junction_context() -> None:
    anchors = (
        _anchor("A", dependency_ids=("A", "B")),
        _anchor("B", dependency_ids=("B", "C")),
        _anchor("C", dependency_ids=("C",)),
        _anchor("D", dependency_ids=("D",)),
    )
    ordinary = (
        _ordinary("s1", ("A",)),
        _ordinary("s2", ("D",)),
        _ordinary("neighbor-a", ("A",)),
        _ordinary("neighbor-b", ("B", "C")),
        _ordinary("transitive-c", ("C",)),
    )
    advance = AdvanceRightRecallExample(
        case_key="CASE",
        segment_id="ar-1",
        fold=2,
        source_segment_id="s1",
        target_segment_id="s2",
        plans=(
            AdvanceRightRecallPlan(
                plan_id="SWSD_ONLY",
                road_ids=(),
                feature_values=_feature(0.0),
            ),
        ),
        acceptable_plan_ids=frozenset(),
        preferred_plan_id=None,
        task_mask=False,
        label_weight=0.7,
        truth_plan_type="",
    )

    graph = build_advance_right_dependency_subgraphs(
        anchors,
        ordinary,
        (advance,),
    )[0].dependency_subgraph

    assert [row.anchor_id for row in graph.anchors] == ["A", "B", "D"]
    assert [row.segment_id for row in graph.ordinary_segments] == [
        "neighbor-a",
        "neighbor-b",
        "s1",
        "s2",
    ]


def test_same_forward_locks_predicted_ordinary_before_advance_right() -> None:
    anchors = (_anchor("a1"), _anchor("a2"))
    ordinary = (
        _ordinary("s1", ("a1",)),
        _ordinary("s2", ("a2",)),
    )
    dependency = build_segment_joint_examples(
        anchors,
        ordinary,
    )
    by_segment = {
        row.ordinary_segments[0].segment_id: row
        for row in dependency
    }
    combined = replace(
        by_segment["s1"],
        anchors=anchors,
        ordinary_segments=ordinary,
    )
    plans = (
        AdvanceRightRecallPlan(
            plan_id="SWSD_ONLY",
            road_ids=(),
            feature_values=_feature(0.0),
        ),
        AdvanceRightRecallPlan(
            plan_id="RCSD_SET:r1",
            road_ids=("r1",),
            feature_values=_feature(1.0),
        ),
    )
    advance = AdvanceRightRecallExample(
        case_key=combined.case_key,
        segment_id="ar-1",
        fold=combined.fold,
        source_segment_id="s1",
        target_segment_id="s2",
        plans=plans,
        acceptable_plan_ids=frozenset({"RCSD_SET:r1"}),
        preferred_plan_id="RCSD_SET:r1",
        task_mask=True,
        label_weight=0.7,
        truth_plan_type="RCSD_ONLY",
    )
    batch = collate_end_to_end_recall_batch(
        EndToEndRecallExample(
            dependency_subgraph=combined,
            advance_right=advance,
        ),
        teacher_forcing=False,
        include_candidate_relations=False,
        retain_anchor_structural_evidence=False,
        retain_ordinary_member_evidence=False,
        retain_ordinary_arm_evidence=False,
    )
    config = TargetAConfig(
        feature_dim=64,
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        min_parameter_count=1,
        max_parameter_count=10_000_000,
        stop_gradient_between_stages=False,
    )
    outputs = TargetAJointNetwork(config).eval()(
        batch.training_batch.tensors
    )

    assert outputs["ordinary_plan_logits"].shape[:2] == (1, 2)
    assert outputs["advance_right_plan_logits"].shape == (1, 1, 2)
    assert batch.training_batch.targets.advance_right_acceptable.tolist() == [
        [[False, True]]
    ]
    assert (
        batch.training_batch.tensors.teacher_anchor_candidate_indices is None
    )
    assert batch.training_batch.tensors.teacher_ordinary_plan_indices is None
    ar_object_index = int(
        batch.training_batch.tensors.advance_right_object_indices[0, 0]
    )
    assert (
        batch.training_batch.tensors.adjacency[
            0,
            ar_object_index,
        ].sum().item()
        == 1
    )
    assert torch.isfinite(outputs["advance_right_plan_logits"]).all()
