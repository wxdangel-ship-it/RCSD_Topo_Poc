from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_SIDE_COUNT,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    OrdinaryJointAccessBatch,
    OrdinaryJointMainlineExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    ORDINARY_PLAN_ARM_COUNT,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)


STRUCTURED_PLAN_KEEP_SWSD = 0
STRUCTURED_PLAN_USE_RCSD = 1
STRUCTURED_PLAN_ABSTAIN = 2
STRUCTURED_PLAN_T06_ATTACHED_SWSD = 3
STRUCTURED_PLAN_DECISION_COUNT = 4
ACCESS_GROUP_INTERNAL = -1
ACCESS_GROUP_PADDING = -2

_PLAN_DECISION_INDEX = {
    "KEEP_SWSD": STRUCTURED_PLAN_KEEP_SWSD,
    "USE_RCSD": STRUCTURED_PLAN_USE_RCSD,
    "ABSTAIN": STRUCTURED_PLAN_ABSTAIN,
    "T06_MAIN_RCSD_ATTACHED_SWSD": STRUCTURED_PLAN_T06_ATTACHED_SWSD,
}
_BASE_DECISION_INDEX = {
    STRUCTURED_PLAN_KEEP_SWSD: ORDINARY_DECISION_KEEP_SWSD,
    STRUCTURED_PLAN_USE_RCSD: ORDINARY_DECISION_USE_RCSD,
    STRUCTURED_PLAN_ABSTAIN: ORDINARY_DECISION_ABSTAIN,
    STRUCTURED_PLAN_T06_ATTACHED_SWSD: ORDINARY_DECISION_USE_RCSD,
}
_ROLE_INDEX = {
    value: index for index, value in enumerate(ROAD_BUSINESS_ROLE_LABELS)
}
_OWNERSHIP_INDEX = {
    value: index for index, value in enumerate(ROAD_OWNERSHIP_LABELS)
}


@dataclass(frozen=True)
class OrdinaryJointStructuredPlanBatch:
    plan_feature_values: torch.Tensor
    plan_mask: torch.Tensor
    plan_hard_valid: torch.Tensor
    plan_decisions: torch.Tensor
    plan_base_decisions: torch.Tensor
    plan_road_membership: torch.Tensor
    plan_role_targets: torch.Tensor
    plan_ownership_targets: torch.Tensor
    plan_access_road_membership: torch.Tensor
    access_group_arm_indices: torch.Tensor
    acceptable_plan_mask: torch.Tensor
    task_mask: torch.Tensor
    sample_weights: torch.Tensor
    teacher_gate_decisions: torch.Tensor
    plan_ids: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        if (
            self.plan_feature_values.ndim != 4
            or self.plan_feature_values.shape[-1] != TARGET_A_FEATURE_DIM
        ):
            raise ValueError("ordinary structured plan feature shape differs")
        plan_shape = self.plan_feature_values.shape[:-1]
        for values in (
            self.plan_mask,
            self.plan_hard_valid,
            self.plan_decisions,
            self.plan_base_decisions,
            self.acceptable_plan_mask,
        ):
            if values.shape != plan_shape:
                raise ValueError("ordinary structured plan shape differs")
        road_shape = (*plan_shape, self.plan_road_membership.shape[-1])
        for values in (
            self.plan_road_membership,
            self.plan_role_targets,
            self.plan_ownership_targets,
        ):
            if values.shape != road_shape:
                raise ValueError("ordinary structured plan Road shape differs")
        if self.plan_access_road_membership.shape != (
            *plan_shape,
            ORDINARY_PLAN_ARM_COUNT,
            self.plan_road_membership.shape[-1],
        ):
            raise ValueError("ordinary structured plan access Road shape differs")
        side_shape = plan_shape[:-1]
        for values in (
            self.task_mask,
            self.sample_weights,
            self.teacher_gate_decisions,
        ):
            if values.shape != side_shape:
                raise ValueError("ordinary structured plan side shape differs")
        if self.access_group_arm_indices.shape[:2] != side_shape:
            raise ValueError("ordinary structured plan access group shape differs")


def collate_ordinary_joint_structured_plan_batch(
    examples: Sequence[OrdinaryJointMainlineExample],
    ordinary: EndToEndOrdinarySetBatch,
    access: OrdinaryJointAccessBatch,
    *,
    teacher_forcing: bool,
) -> OrdinaryJointStructuredPlanBatch:
    if not examples:
        raise ValueError("ordinary structured plan examples are empty")
    if ordinary.side_road_mask.shape[0] != len(examples):
        raise ValueError("ordinary structured plan batch identity differs")
    if access.proposal_mask.shape[:2] != ordinary.side_road_mask.shape[:2]:
        raise ValueError("ordinary structured plan access batch differs")
    maximum_plans = max(
        len(row.joint.ordinary_segments[0].candidate_ids) for row in examples
    )
    maximum_roads = ordinary.side_road_mask.shape[-1]
    side_shape = (len(examples), ORDINARY_SET_SIDE_COUNT)
    plan_shape = (*side_shape, maximum_plans)
    road_shape = (*plan_shape, maximum_roads)
    feature_values = torch.zeros((*plan_shape, TARGET_A_FEATURE_DIM))
    plan_mask = torch.zeros(plan_shape, dtype=torch.bool)
    hard_valid = torch.zeros(plan_shape, dtype=torch.bool)
    decisions = torch.full(
        plan_shape,
        STRUCTURED_PLAN_ABSTAIN,
        dtype=torch.long,
    )
    base_decisions = torch.full(
        plan_shape,
        ORDINARY_DECISION_ABSTAIN,
        dtype=torch.long,
    )
    membership = torch.zeros(road_shape, dtype=torch.bool)
    role_targets = torch.zeros(road_shape, dtype=torch.long)
    ownership_targets = torch.zeros(road_shape, dtype=torch.long)
    access_membership = torch.zeros(
        (*plan_shape, ORDINARY_PLAN_ARM_COUNT, maximum_roads),
        dtype=torch.bool,
    )
    access_group_arm_indices = torch.full(
        (*side_shape, access.proposal_mask.shape[2]),
        ACCESS_GROUP_PADDING,
        dtype=torch.long,
    )
    acceptable = torch.zeros(plan_shape, dtype=torch.bool)
    task_mask = torch.zeros(side_shape, dtype=torch.bool)
    sample_weights = torch.zeros(side_shape)
    teacher_gate = torch.full(side_shape, -1, dtype=torch.long)
    plan_ids = []
    for batch_index, example in enumerate(examples):
        source = example.joint.ordinary_segments[0]
        _validate_source_candidate_semantics(source)
        count = len(source.candidate_ids)
        feature_values[batch_index, 0, :count] = torch.tensor(
            source.candidate_features
        )
        road_index = {
            road_id: index
            for index, road_id in enumerate(example.road_pool.road_ids)
        }
        acceptable_ids = set(
            str(value)
            for value in example.ledger["plan_label"].get(
                "acceptable_plan_ids"
            )
            or ()
        )
        arm_index_by_anchor = {
            anchor_id: index
            for index, anchor_id in enumerate(source.arm_anchor_ids)
        }
        for group_index, junction_id in enumerate(
            access.junction_ids[batch_index][0]
        ):
            access_group_arm_indices[batch_index, 0, group_index] = (
                arm_index_by_anchor.get(junction_id, ACCESS_GROUP_INTERNAL)
            )
        for plan_index in range(count):
            plan_id = source.candidate_ids[plan_index]
            decision_name = source.candidate_decisions[plan_index]
            decision = _PLAN_DECISION_INDEX[decision_name]
            decisions[batch_index, 0, plan_index] = decision
            base_decisions[batch_index, 0, plan_index] = _BASE_DECISION_INDEX[
                decision
            ]
            candidate_road_ids = source.candidate_road_ids[plan_index]
            reachable = all(road_id in road_index for road_id in candidate_road_ids)
            plan_mask[batch_index, 0, plan_index] = reachable
            hard_valid[batch_index, 0, plan_index] = bool(
                source.candidate_hard_valid[plan_index]
            )
            if not reachable:
                continue
            selected_indices = [road_index[road_id] for road_id in candidate_road_ids]
            membership[batch_index, 0, plan_index, selected_indices] = True
            role_by_road = dict(source.candidate_road_roles[plan_index])
            for road_id, role in role_by_road.items():
                if road_id not in road_index or role not in _ROLE_INDEX:
                    raise ValueError(
                        f"ordinary structured plan role differs: {plan_id}/{road_id}/{role}"
                    )
                role_targets[
                    batch_index,
                    0,
                    plan_index,
                    road_index[road_id],
                ] = _ROLE_INDEX[role]
            for road_id in source.candidate_owned_road_ids[plan_index]:
                if road_id not in road_index:
                    raise ValueError(
                        f"ordinary structured plan owner Road differs: {plan_id}/{road_id}"
                    )
                ownership_targets[
                    batch_index,
                    0,
                    plan_index,
                    road_index[road_id],
                ] = _OWNERSHIP_INDEX["OWNER_CURRENT_SEGMENT"]
            for arm_index, road_id in enumerate(
                source.candidate_arm_road_ids[plan_index]
            ):
                if road_id not in road_index:
                    raise ValueError(
                        f"ordinary structured plan arm Road differs: {plan_id}/{road_id}"
                    )
                access_membership[
                    batch_index,
                    0,
                    plan_index,
                    arm_index,
                    road_index[road_id],
                ] = True
            candidate_acceptable = plan_id in acceptable_ids
            if candidate_acceptable:
                candidate_acceptable = _matches_known_road_business_labels(
                    example,
                    role_targets[batch_index, 0, plan_index],
                    ownership_targets[batch_index, 0, plan_index],
                )
            acceptable[batch_index, 0, plan_index] = candidate_acceptable
        plan_mask[batch_index, 0] &= hard_valid[batch_index, 0]
        acceptable[batch_index, 0] &= plan_mask[batch_index, 0]
        task_mask[batch_index, 0] = bool(
            example.ledger["plan_label"].get("task_mask")
            and acceptable[batch_index, 0].any()
        )
        sample_weights[batch_index, 0] = float(
            example.ledger["plan_label"].get("label_weight") or 0.0
        )
        if teacher_forcing:
            teacher_gate[batch_index, 0] = ordinary.decision_targets[
                batch_index, 0
            ]
        plan_ids.append((tuple(source.candidate_ids), ()))
    return OrdinaryJointStructuredPlanBatch(
        plan_feature_values=feature_values,
        plan_mask=plan_mask,
        plan_hard_valid=hard_valid,
        plan_decisions=decisions,
        plan_base_decisions=base_decisions,
        plan_road_membership=membership,
        plan_role_targets=role_targets,
        plan_ownership_targets=ownership_targets,
        plan_access_road_membership=access_membership,
        access_group_arm_indices=access_group_arm_indices,
        acceptable_plan_mask=acceptable,
        task_mask=task_mask,
        sample_weights=sample_weights,
        teacher_gate_decisions=teacher_gate,
        plan_ids=tuple(plan_ids),
    )


def move_ordinary_joint_structured_plan_batch(
    batch: OrdinaryJointStructuredPlanBatch,
    device: torch.device,
) -> OrdinaryJointStructuredPlanBatch:
    return OrdinaryJointStructuredPlanBatch(
        **{
            key: value.to(device) if isinstance(value, torch.Tensor) else value
            for key, value in batch.__dict__.items()
        }
    )


def _validate_source_candidate_semantics(source: object) -> None:
    candidate_ids = tuple(getattr(source, "candidate_ids"))
    for values, label in (
        (getattr(source, "candidate_road_roles"), "Road roles"),
        (getattr(source, "candidate_owned_road_ids"), "owned Roads"),
        (getattr(source, "candidate_hard_valid"), "hard-valid mask"),
    ):
        if len(values) != len(candidate_ids):
            raise ValueError(
                f"ordinary structured plan lacks inference {label}"
            )


def _matches_known_road_business_labels(
    example: OrdinaryJointMainlineExample,
    candidate_roles: torch.Tensor,
    candidate_ownership: torch.Tensor,
) -> bool:
    pool = example.road_pool
    if pool.road_business_role_task_mask:
        for index, active in enumerate(pool.road_business_role_task_mask):
            if active and int(candidate_roles[index]) != int(
                pool.road_business_role_targets[index]
            ):
                return False
    if pool.road_ownership_task_mask:
        for index, active in enumerate(pool.road_ownership_task_mask):
            if active and int(candidate_ownership[index]) != int(
                pool.road_ownership_targets[index]
            ):
                return False
    return True


__all__ = [
    "ACCESS_GROUP_INTERNAL",
    "ACCESS_GROUP_PADDING",
    "STRUCTURED_PLAN_ABSTAIN",
    "STRUCTURED_PLAN_DECISION_COUNT",
    "STRUCTURED_PLAN_KEEP_SWSD",
    "STRUCTURED_PLAN_T06_ATTACHED_SWSD",
    "STRUCTURED_PLAN_USE_RCSD",
    "OrdinaryJointStructuredPlanBatch",
    "collate_ordinary_joint_structured_plan_batch",
    "move_ordinary_joint_structured_plan_batch",
]
