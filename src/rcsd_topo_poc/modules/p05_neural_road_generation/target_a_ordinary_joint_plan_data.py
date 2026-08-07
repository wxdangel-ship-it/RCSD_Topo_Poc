from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    OrdinaryPlanProposalExample,
    PLAN_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_reranker import (
    _assert_base_feature_alignment,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISION_INDEX,
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
    _batch_tensors,
)


PLAN_DECISION_INDEX = {
    "KEEP_SWSD": 0,
    "USE_RCSD": 1,
    "ABSTAIN": 2,
}
CANDIDATE_SOURCE_INDEX = {
    "SWSD": 0,
    "RCSD": 1,
}


def merge_current_labels_into_base_features(
    current: Sequence[OrdinaryRoadSetExample],
    base: Sequence[OrdinaryRoadSetExample],
) -> list[OrdinaryRoadSetExample]:
    """Keep checkpoint-era inputs while applying the current label overlay."""
    base_by_key = {
        (row.case_key, row.segment_id): row for row in base
    }
    _assert_base_feature_alignment(current, base_by_key)
    result = []
    for row in current:
        old = base_by_key[(row.case_key, row.segment_id)]
        result.append(
            replace(
                old,
                decision=row.decision,
                target_indices=row.target_indices,
                ownership_targets=row.ownership_targets,
                ownership_task_mask=row.ownership_task_mask,
                business_role_targets=row.business_role_targets,
                business_role_task_mask=row.business_role_task_mask,
                sample_weight=row.sample_weight,
                oof_anchor_release_ready=(
                    row.oof_anchor_release_ready
                ),
                target_state=row.target_state,
                ownership_sample_weight=row.ownership_sample_weight,
                business_role_sample_weight=(
                    row.business_role_sample_weight
                ),
                member_sample_weights=row.member_sample_weights,
            )
        )
    return result


def collate_joint_plan_batch(
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    base_config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
) -> dict[str, torch.Tensor | Mapping[str, torch.Tensor]]:
    if not rows or len(rows) != len(proposals):
        raise ValueError("ordinary joint plan batch alignment differs")
    for row, proposal in zip(rows, proposals, strict=True):
        if (
            (row.case_key, row.segment_id)
            != (proposal.case_key, proposal.segment_id)
            or row.fold != proposal.fold
            or DECISION_INDEX[proposal.target_decision] != row.decision
            or tuple(
                sorted(
                    row.road_ids[index]
                    for index in row.target_indices
                )
            )
            != proposal.target_road_ids
        ):
            raise ValueError("ordinary joint plan target alignment differs")
    base_batch = _batch_tensors(
        rows,
        feature_source="oof",
        device=device,
        cardinality_count=base_config.cardinality_count,
        road_relation_dim=base_config.road_relation_dim,
    )
    plan_count = max(len(row.proposal_ids) for row in proposals)
    candidate_count = max(len(row.road_ids) for row in rows)
    proposal_features = torch.zeros(
        len(rows),
        plan_count,
        PLAN_PROPOSAL_FEATURE_DIM,
        dtype=torch.float32,
        device=device,
    )
    proposal_valid = torch.zeros(
        len(rows),
        plan_count,
        dtype=torch.bool,
        device=device,
    )
    proposal_acceptable = torch.zeros_like(proposal_valid)
    proposal_membership = torch.zeros(
        len(rows),
        plan_count,
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    proposal_decisions = torch.zeros(
        len(rows),
        plan_count,
        dtype=torch.long,
        device=device,
    )
    proposal_cardinalities = torch.zeros_like(proposal_decisions)
    candidate_sources = torch.full(
        (len(rows), candidate_count),
        -1,
        dtype=torch.long,
        device=device,
    )
    weights = torch.tensor(
        [proposal.sample_weight for proposal in proposals],
        dtype=torch.float32,
        device=device,
    )
    for batch_index, (row, proposal) in enumerate(
        zip(rows, proposals, strict=True)
    ):
        road_index = {
            road_id: index for index, road_id in enumerate(row.road_ids)
        }
        candidate_sources[batch_index, : len(row.sources)] = torch.tensor(
            [CANDIDATE_SOURCE_INDEX[value] for value in row.sources],
            dtype=torch.long,
            device=device,
        )
        length = len(proposal.proposal_ids)
        proposal_features[batch_index, :length] = torch.tensor(
            proposal.proposal_features,
            dtype=torch.float32,
            device=device,
        )
        proposal_valid[batch_index, :length] = True
        proposal_acceptable[
            batch_index,
            list(proposal.acceptable_indices),
        ] = True
        for plan_index, (decision, selected_ids) in enumerate(
            zip(
                proposal.proposal_decisions,
                proposal.proposal_road_ids,
                strict=True,
            )
        ):
            if decision not in PLAN_DECISION_INDEX:
                raise ValueError(
                    "ordinary joint plan decision is unsupported"
                )
            missing = set(selected_ids) - set(road_index)
            if missing:
                raise ValueError(
                    "ordinary joint plan Road is outside candidate pool"
                )
            selected_indices = [
                road_index[road_id] for road_id in selected_ids
            ]
            proposal_membership[
                batch_index,
                plan_index,
                selected_indices,
            ] = True
            proposal_decisions[batch_index, plan_index] = (
                PLAN_DECISION_INDEX[decision]
            )
            proposal_cardinalities[
                batch_index,
                plan_index,
            ] = len(selected_indices)
    return {
        "base_batch": base_batch,
        "proposal_features": proposal_features,
        "proposal_valid": proposal_valid,
        "proposal_acceptable": proposal_acceptable,
        "proposal_membership": proposal_membership,
        "proposal_decisions": proposal_decisions,
        "proposal_cardinalities": proposal_cardinalities,
        "candidate_sources": candidate_sources,
        "weights": weights,
    }


__all__ = [
    "CANDIDATE_SOURCE_INDEX",
    "PLAN_DECISION_INDEX",
    "collate_joint_plan_batch",
    "merge_current_labels_into_base_features",
]
