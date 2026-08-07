from __future__ import annotations

from types import SimpleNamespace

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    ACCESS_COLLECTION_FEATURE_DIM,
    BREAK_CANDIDATE_FEATURE_DIM,
    OrdinaryJointAccessBatch,
    OrdinaryJointBreakBatch,
    _ordinary_mainline_side_group_indices,
    _canonical_side_anchor_business_state,
    _prepare_access_groups,
    build_break_candidate_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    AnchorOofBusinessPrediction,
)


def test_ordinary_mainline_padding_side_does_not_join_focal_group() -> None:
    indices = _ordinary_mainline_side_group_indices(3)

    assert indices.tolist() == [[0, -1], [0, -1], [0, -1]]


def test_canonical_anchor_results_form_segment_hard_gate() -> None:
    predictions = {
        ("T10:1", "a"): AnchorOofBusinessPrediction(
            case_key="T10:1",
            anchor_id="a",
            business_state=1,
            candidate_id="ROAD:r1",
        ),
        ("T10:1", "b"): AnchorOofBusinessPrediction(
            case_key="T10:1",
            anchor_id="b",
            business_state=2,
        ),
        ("T10:1", "c"): AnchorOofBusinessPrediction(
            case_key="T10:1",
            anchor_id="c",
            business_state=0,
        ),
    }

    assert _canonical_side_anchor_business_state(
        case_key="T10:1",
        required_anchor_ids=("a",),
        predictions=predictions,
    ) == (1, ("ROAD:r1",))
    assert _canonical_side_anchor_business_state(
        case_key="T10:1",
        required_anchor_ids=("a", "b"),
        predictions=predictions,
    ) == (2, ())
    assert _canonical_side_anchor_business_state(
        case_key="T10:1",
        required_anchor_ids=("a", "c"),
        predictions=predictions,
    ) == (0, ())
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_network import (
    TargetAOrdinaryJointMainlineConfig,
    TargetAOrdinaryJointMainlineNetwork,
    _access_collection_loss,
    _break_loss,
)


def test_break_candidates_exclude_teacher_and_terminal_positions() -> None:
    fractions, values = build_break_candidate_features(
        {
            "PARENT_ENDPOINT": (0.0, 1.0),
            "T01_ANCHOR_PROJECTION": (0.2,),
            "TEACHER_ANCHOR_OBJECT": (0.77,),
            "OOF_PREDICTED_SUCCESS": (0.81,),
            "TERMINAL_BREAK": (0.93,),
        },
        parent_length_m=100.0,
    )

    assert 0.2 in fractions
    assert 0.77 not in fractions
    assert 0.81 not in fractions
    assert 0.93 not in fractions
    assert len(values) == len(fractions)
    assert all(len(row) == BREAK_CANDIDATE_FEATURE_DIM for row in values)


def test_access_multiple_acceptable_collections_are_not_merged() -> None:
    feature = tuple(0.0 for _ in range(40))
    proposals = (
        {
            "road_id": "r1",
            "proposal_id": "p1",
            "geometry_feature_values": [0.0] * 24,
        },
        {
            "road_id": "r2",
            "proposal_id": "p2",
            "geometry_feature_values": [0.0] * 24,
        },
    )
    example = SimpleNamespace(
        joint=SimpleNamespace(
            ordinary_segments=(SimpleNamespace(junc_node_ids=("j1",)),)
        ),
        road_pool=SimpleNamespace(
            road_ids=("r1", "r2"),
            road_feature_values=(feature, feature),
        ),
        access_features_by_junction={"j1": proposals},
        ledger={
            "access_labels": [
                {
                    "junction_id": "j1",
                    "task_mask": True,
                    "label_weight": 1.0,
                    "acceptable_access_collections": [
                        {"proposal_ids": ["p1"]},
                        {"proposal_ids": ["p2"]},
                    ],
                }
            ]
        },
    )

    group = _prepare_access_groups(example)[0]

    assert group["task_mask"] is False
    assert group["target_proposal_ids"] == ()
    assert [row["road_index"] for row in group["proposals"]] == [0, 1]


def test_access_groups_come_from_inference_junctions_not_terminal_labels() -> None:
    feature = tuple(0.0 for _ in range(40))
    example = SimpleNamespace(
        joint=SimpleNamespace(
            ordinary_segments=(
                SimpleNamespace(junc_node_ids=("j_inference",)),
            )
        ),
        road_pool=SimpleNamespace(
            road_ids=("r1",),
            road_feature_values=(feature,),
        ),
        access_features_by_junction={
            "j_inference": (
                {
                    "road_id": "r1",
                    "proposal_id": "p1",
                    "geometry_feature_values": [0.0] * 24,
                },
            )
        },
        ledger={
            "access_labels": [
                {
                    "junction_id": "j_terminal_only",
                    "task_mask": True,
                    "label_state": "RESOLVED_NO_ACCESS",
                    "label_weight": 1.0,
                }
            ]
        },
    )

    groups = _prepare_access_groups(example)

    assert [row["junction_id"] for row in groups] == ["j_inference"]
    assert groups[0]["task_mask"] is False
    assert [row["proposal_id"] for row in groups[0]["proposals"]] == ["p1"]


class _FakeOrdinaryNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_dim=8, road_hidden_dim=8)

    def forward(self, batch: object, ordinary_set: object) -> dict[str, torch.Tensor]:
        del batch, ordinary_set
        return {
            "_ordinary_road_encoded": torch.arange(
                48, dtype=torch.float32
            ).reshape(1, 2, 3, 8),
            "ordinary_side_road_member_logits": torch.tensor(
                [[[2.0, -2.0, 0.0], [0.0, 0.0, 0.0]]]
            ),
            "ordinary_side_context": torch.ones((1, 2, 8)),
        }


def test_joint_heads_condition_access_and_breaks_on_same_forward_roads() -> None:
    access = OrdinaryJointAccessBatch(
        proposal_values=torch.zeros((1, 2, 1, 2, ACCESS_COLLECTION_FEATURE_DIM)),
        proposal_road_indices=torch.tensor([[[[0, 1]], [[-1, -1]]]]),
        proposal_mask=torch.tensor([[[[True, True]], [[False, False]]]]),
        proposal_targets=torch.tensor([[[[True, False]], [[False, False]]]]),
        task_mask=torch.tensor([[[True], [False]]]),
        cardinality_targets=torch.tensor([[[1], [0]]]),
        sample_weights=torch.tensor([[[1.0], [0.0]]]),
        junction_ids=((('j1',), ()),),
        proposal_ids=(((('p1', 'p2'),), ()),),
    )
    breaks = OrdinaryJointBreakBatch(
        parent_road_indices=torch.tensor([[[0], [-1]]]),
        parent_mask=torch.tensor([[[True], [False]]]),
        candidate_values=torch.zeros((1, 2, 1, 3, BREAK_CANDIDATE_FEATURE_DIM)),
        candidate_fractions=torch.tensor(
            [[[[0.2, 0.5, 0.8]], [[0.0, 0.0, 0.0]]]]
        ),
        candidate_mask=torch.tensor(
            [[[[True, True, True]], [[False, False, False]]]]
        ),
        candidate_targets=torch.tensor(
            [[[[False, True, False]], [[False, False, False]]]]
        ),
        task_mask=torch.tensor([[[True], [False]]]),
        presence_targets=torch.tensor([[[True], [False]]]),
        cardinality_targets=torch.tensor([[[1], [0]]]),
        ownership_targets=torch.tensor([[[1], [0]]]),
        sample_weights=torch.tensor([[[1.0], [0.0]]]),
        parent_road_ids=((('r1',), ()),),
    )
    config = TargetAOrdinaryJointMainlineConfig(
        hidden_dim=8,
        road_hidden_dim=8,
        access_hidden_dim=8,
        break_hidden_dim=8,
        set_heads=2,
        dropout=0.0,
    )
    model = TargetAOrdinaryJointMainlineNetwork(
        _FakeOrdinaryNetwork(),
        config,
    ).eval()

    outputs = model(object(), object(), access, breaks)
    access_loss, _ = _access_collection_loss(outputs, access)
    break_loss, _ = _break_loss(outputs, breaks)

    assert outputs["ordinary_access_collection_member_logits"].shape == (
        1,
        2,
        1,
        2,
    )
    assert outputs["ordinary_break_member_logits"].shape == (1, 2, 1, 3)
    assert torch.isfinite(access_loss)
    assert torch.isfinite(break_loss)
