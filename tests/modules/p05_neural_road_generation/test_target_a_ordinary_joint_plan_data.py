from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_data import (
    collate_joint_plan_batch,
    merge_current_labels_into_base_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    OrdinaryPlanProposalExample,
    PLAN_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISION_INDEX,
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
)


def _example(
    *,
    target_indices: tuple[int, ...],
    road_relations: tuple[
        tuple[int, int, tuple[float, ...]],
        ...,
    ] = (),
) -> OrdinaryRoadSetExample:
    return OrdinaryRoadSetExample(
        case_key="T10:case",
        segment_id="segment",
        fold=1,
        object_features=(1.0,),
        road_ids=("s0", "r0", "r1"),
        sources=("SWSD", "RCSD", "RCSD"),
        start_node_ids=("a", "b", "c"),
        end_node_ids=("d", "e", "f"),
        anchor_features=((1.0,),),
        teacher_anchor_relations=(((1.0,),),) * 3,
        oof_anchor_relations=(((1.0,),),) * 3,
        teacher_features=((1.0,), (2.0,), (3.0,)),
        oof_features=((1.0,), (2.0,), (3.0,)),
        decision=DECISION_INDEX["USE_RCSD"],
        target_indices=target_indices,
        ownership_targets=(0, 0, 0),
        ownership_task_mask=(False, False, False),
        business_role_targets=(0, 0, 0),
        business_role_task_mask=(False, False, False),
        sample_weight=0.7,
        oof_anchor_release_ready=True,
        road_relations=road_relations,
        member_sample_weights=(0.7, 0.7, 1.0),
    )


def test_current_label_overlay_preserves_checkpoint_feature_contract() -> None:
    old = _example(target_indices=(1,))
    current = _example(
        target_indices=(1, 2),
        road_relations=((1, 2, (1.0,) * 13),),
    )

    merged = merge_current_labels_into_base_features([current], [old])[0]

    assert merged.target_indices == (1, 2)
    assert merged.member_sample_weights == (0.7, 0.7, 1.0)
    assert merged.road_relations == ()
    assert merged.oof_features == old.oof_features


def test_joint_plan_batch_builds_exact_membership_masks() -> None:
    row = _example(target_indices=(1, 2))
    features = (0.0,) * PLAN_PROPOSAL_FEATURE_DIM
    proposal = OrdinaryPlanProposalExample(
        case_key=row.case_key,
        segment_id=row.segment_id,
        fold=row.fold,
        proposal_ids=("abstain", "target"),
        proposal_decisions=("ABSTAIN", "USE_RCSD"),
        proposal_road_ids=((), ("r0", "r1")),
        proposal_features=(features, features),
        acceptable_indices=(1,),
        target_decision="USE_RCSD",
        target_road_ids=("r0", "r1"),
        sample_weight=0.7,
        release_eligible=True,
        target_reachable=True,
    )

    batch = collate_joint_plan_batch(
        [row],
        [proposal],
        base_config=OrdinaryRoadSetTrainingConfig(cardinality_count=4),
        device=torch.device("cpu"),
    )

    assert batch["proposal_membership"].tolist() == [
        [[False, False, False], [False, True, True]]
    ]
    assert batch["proposal_decisions"].tolist() == [[2, 1]]
    assert batch["candidate_sources"].tolist() == [[0, 1, 1]]
    assert batch["proposal_acceptable"].tolist() == [[False, True]]
