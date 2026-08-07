from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetNetwork,
    compute_end_to_end_ordinary_set_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    ACCESS_COLLECTION_FEATURE_DIM,
    BREAK_CANDIDATE_FEATURE_DIM,
    BREAK_OWNERSHIP_NAMES,
    MAXIMUM_BREAK_COUNT,
    OrdinaryJointAccessBatch,
    OrdinaryJointBreakBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_structured_data import (
    ACCESS_GROUP_INTERNAL,
    ACCESS_GROUP_PADDING,
    OrdinaryJointStructuredPlanBatch,
)


@dataclass(frozen=True)
class TargetAOrdinaryJointMainlineConfig:
    hidden_dim: int
    road_hidden_dim: int
    access_hidden_dim: int = 96
    break_hidden_dim: int = 96
    plan_hidden_dim: int = 192
    set_layers: int = 1
    set_heads: int = 4
    plan_set_layers: int = 1
    plan_set_heads: int = 4
    max_access_cardinality: int = 16
    max_break_cardinality: int = MAXIMUM_BREAK_COUNT
    dropout: float = 0.10
    access_loss_weight: float = 0.50
    break_loss_weight: float = 0.50
    plan_loss_weight: float = 1.00

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.road_hidden_dim,
            self.access_hidden_dim,
            self.break_hidden_dim,
            self.plan_hidden_dim,
            self.set_layers,
            self.set_heads,
            self.plan_set_layers,
            self.plan_set_heads,
            self.max_access_cardinality,
            self.max_break_cardinality,
        ) < 1:
            raise ValueError("ordinary joint mainline dimensions are invalid")
        if (
            self.access_hidden_dim % self.set_heads
            or self.break_hidden_dim % self.set_heads
            or self.plan_hidden_dim % self.plan_set_heads
        ):
            raise ValueError("ordinary joint set heads do not divide hidden dims")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary joint mainline dropout is invalid")
        if min(
            self.access_loss_weight,
            self.break_loss_weight,
            self.plan_loss_weight,
        ) < 0.0:
            raise ValueError("ordinary joint mainline loss weight is invalid")


class TargetAOrdinaryJointMainlineNetwork(nn.Module):
    """One-forward ordinary business chain after model-internal anchoring."""

    def __init__(
        self,
        ordinary: TargetAEndToEndOrdinarySetNetwork,
        config: TargetAOrdinaryJointMainlineConfig,
    ) -> None:
        super().__init__()
        config.validate()
        if (
            ordinary.config.hidden_dim != config.hidden_dim
            or ordinary.config.road_hidden_dim != config.road_hidden_dim
        ):
            raise ValueError("ordinary joint mainline base dimensions differ")
        self.ordinary = ordinary
        self.config = config

        self.access_proposal_stem = _stem(
            ACCESS_COLLECTION_FEATURE_DIM,
            config.access_hidden_dim,
            config.dropout,
        )
        self.access_road_fusion = _stem(
            config.road_hidden_dim + 1,
            config.access_hidden_dim,
            config.dropout,
        )
        self.access_set_encoder = _set_encoder(
            config.access_hidden_dim,
            config.set_heads,
            config.set_layers,
            config.dropout,
        )
        access_group_input = config.hidden_dim + 2 * config.access_hidden_dim
        self.access_group_context = _stem(
            access_group_input,
            config.access_hidden_dim,
            config.dropout,
        )
        self.access_member_head = _head(
            2 * config.access_hidden_dim,
            config.access_hidden_dim,
            1,
            config.dropout,
        )
        self.access_cardinality_head = _head(
            config.access_hidden_dim,
            config.access_hidden_dim,
            config.max_access_cardinality + 1,
            config.dropout,
        )

        self.break_candidate_stem = _stem(
            BREAK_CANDIDATE_FEATURE_DIM,
            config.break_hidden_dim,
            config.dropout,
        )
        self.break_set_encoder = _set_encoder(
            config.break_hidden_dim,
            config.set_heads,
            config.set_layers,
            config.dropout,
        )
        break_group_input = (
            config.hidden_dim
            + config.road_hidden_dim
            + 1
            + 2 * config.break_hidden_dim
        )
        self.break_group_context = _stem(
            break_group_input,
            config.break_hidden_dim,
            config.dropout,
        )
        self.break_member_head = _head(
            2 * config.break_hidden_dim,
            config.break_hidden_dim,
            1,
            config.dropout,
        )
        self.break_presence_head = _head(
            config.break_hidden_dim,
            config.break_hidden_dim,
            1,
            config.dropout,
        )
        self.break_cardinality_head = _head(
            config.break_hidden_dim,
            config.break_hidden_dim,
            config.max_break_cardinality + 1,
            config.dropout,
        )
        self.break_ownership_head = _head(
            config.break_hidden_dim,
            config.break_hidden_dim,
            len(BREAK_OWNERSHIP_NAMES),
            config.dropout,
        )
        plan_dynamic_dim = 10
        plan_input_dim = (
            TARGET_A_FEATURE_DIM
            + config.hidden_dim
            + 3 * config.road_hidden_dim
            + plan_dynamic_dim
        )
        self.structured_plan_stem = _stem(
            plan_input_dim,
            config.plan_hidden_dim,
            config.dropout,
        )
        self.structured_plan_set_encoder = _set_encoder(
            config.plan_hidden_dim,
            config.plan_set_heads,
            config.plan_set_layers,
            config.dropout,
        )
        self.structured_plan_head = _head(
            3 * config.plan_hidden_dim,
            config.plan_hidden_dim,
            1,
            config.dropout,
        )

    def forward(
        self,
        batch: TargetABatchTensors,
        ordinary_set: EndToEndOrdinarySetBatch,
        access: OrdinaryJointAccessBatch,
        breaks: OrdinaryJointBreakBatch,
        structured_plan: OrdinaryJointStructuredPlanBatch | None = None,
    ) -> dict[str, torch.Tensor]:
        outputs = self.ordinary(batch, ordinary_set)
        road_encoded = outputs["_ordinary_road_encoded"]
        road_membership = torch.sigmoid(
            outputs["ordinary_side_road_member_logits"]
        )
        side_context = outputs["ordinary_side_context"]
        access_outputs = self._forward_access(
            access,
            road_encoded=road_encoded,
            road_membership=road_membership,
            side_context=side_context,
        )
        break_outputs = self._forward_breaks(
            breaks,
            road_encoded=road_encoded,
            road_membership=road_membership,
            side_context=side_context,
        )
        combined = {**outputs, **access_outputs, **break_outputs}
        if structured_plan is not None:
            combined.update(
                self._forward_structured_plan(
                    structured_plan,
                    ordinary_set=ordinary_set,
                    access=access,
                    breaks=breaks,
                    outputs=combined,
                )
            )
        return combined

    def _forward_access(
        self,
        batch: OrdinaryJointAccessBatch,
        *,
        road_encoded: torch.Tensor,
        road_membership: torch.Tensor,
        side_context: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        proposal_encoded = self.access_proposal_stem(batch.proposal_values)
        proposal_roads = _gather_road_values(
            road_encoded,
            batch.proposal_road_indices,
        )
        proposal_membership = _gather_road_values(
            road_membership.unsqueeze(-1),
            batch.proposal_road_indices,
        )
        valid_road = batch.proposal_road_indices.ge(0).unsqueeze(-1)
        road_context = self.access_road_fusion(
            torch.cat((proposal_roads, proposal_membership), dim=-1)
        ) * valid_road.to(proposal_encoded.dtype)
        proposal_encoded = _encode_masked_set(
            self.access_set_encoder,
            proposal_encoded + road_context,
            batch.proposal_mask,
        )
        proposal_mean, proposal_max = _masked_pool(
            proposal_encoded,
            batch.proposal_mask,
        )
        expanded_side = side_context.unsqueeze(2).expand(
            -1, -1, proposal_mean.shape[2], -1
        )
        group_context = self.access_group_context(
            torch.cat((expanded_side, proposal_mean, proposal_max), dim=-1)
        )
        expanded_group = group_context.unsqueeze(3).expand(
            -1, -1, -1, proposal_encoded.shape[3], -1
        )
        member_logits = self.access_member_head(
            torch.cat((proposal_encoded, expanded_group), dim=-1)
        ).squeeze(-1)
        return {
            "ordinary_access_collection_member_logits": member_logits.masked_fill(
                ~batch.proposal_mask,
                0.0,
            ),
            "ordinary_access_collection_cardinality_logits": (
                self.access_cardinality_head(group_context)
            ),
            "_ordinary_access_collection_context": group_context,
        }

    def _forward_breaks(
        self,
        batch: OrdinaryJointBreakBatch,
        *,
        road_encoded: torch.Tensor,
        road_membership: torch.Tensor,
        side_context: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        parent_roads = _gather_road_values(
            road_encoded,
            batch.parent_road_indices,
        )
        parent_membership = _gather_road_values(
            road_membership.unsqueeze(-1),
            batch.parent_road_indices,
        )
        parent_valid = batch.parent_road_indices.ge(0).unsqueeze(-1)
        parent_roads = parent_roads * parent_valid.to(parent_roads.dtype)
        parent_membership = parent_membership * parent_valid.to(
            parent_membership.dtype
        )
        candidate_encoded = _encode_masked_set(
            self.break_set_encoder,
            self.break_candidate_stem(batch.candidate_values),
            batch.candidate_mask,
        )
        candidate_mean, candidate_max = _masked_pool(
            candidate_encoded,
            batch.candidate_mask,
        )
        expanded_side = side_context.unsqueeze(2).expand(
            -1, -1, parent_roads.shape[2], -1
        )
        group_context = self.break_group_context(
            torch.cat(
                (
                    expanded_side,
                    parent_roads,
                    parent_membership,
                    candidate_mean,
                    candidate_max,
                ),
                dim=-1,
            )
        )
        expanded_group = group_context.unsqueeze(3).expand(
            -1, -1, -1, candidate_encoded.shape[3], -1
        )
        member_logits = self.break_member_head(
            torch.cat((candidate_encoded, expanded_group), dim=-1)
        ).squeeze(-1)
        return {
            "ordinary_break_member_logits": member_logits.masked_fill(
                ~batch.candidate_mask,
                0.0,
            ),
            "ordinary_break_presence_logits": self.break_presence_head(
                group_context
            ).squeeze(-1),
            "ordinary_break_cardinality_logits": self.break_cardinality_head(
                group_context
            ),
            "ordinary_break_ownership_logits": self.break_ownership_head(
                group_context
            ),
            "_ordinary_break_context": group_context,
        }

    def _forward_structured_plan(
        self,
        batch: OrdinaryJointStructuredPlanBatch,
        *,
        ordinary_set: EndToEndOrdinarySetBatch,
        access: OrdinaryJointAccessBatch,
        breaks: OrdinaryJointBreakBatch,
        outputs: Mapping[str, torch.Tensor],
    ) -> dict[str, torch.Tensor]:
        road_encoded = outputs["_ordinary_road_encoded"]
        membership = batch.plan_road_membership
        selected_mean, selected_max = _masked_plan_road_pool(
            road_encoded,
            membership,
        )
        road_mask = ordinary_set.side_road_mask
        if road_mask.shape != membership.shape[:2] + membership.shape[-1:]:
            raise ValueError("ordinary structured plan Road mask differs")
        excluded = road_mask.unsqueeze(2) & ~membership
        excluded_mean, _ = _masked_plan_road_pool(
            road_encoded,
            excluded,
        )
        side_context = outputs["ordinary_side_context"].unsqueeze(2).expand(
            -1,
            -1,
            batch.plan_feature_values.shape[2],
            -1,
        )
        dynamic = self._structured_plan_dynamic_features(
            batch,
            ordinary_set=ordinary_set,
            access=access,
            breaks=breaks,
            outputs=outputs,
        )
        encoded = self.structured_plan_stem(
            torch.cat(
                (
                    batch.plan_feature_values,
                    side_context,
                    selected_mean,
                    selected_max,
                    excluded_mean,
                    dynamic,
                ),
                dim=-1,
            )
        )
        encoded = _encode_masked_set(
            self.structured_plan_set_encoder,
            encoded,
            batch.plan_mask,
        )
        plan_mean, plan_max = _masked_pool(encoded, batch.plan_mask)
        context = torch.cat((plan_mean, plan_max), dim=-1).unsqueeze(2).expand(
            -1, -1, encoded.shape[2], -1
        )
        raw_logits = self.structured_plan_head(
            torch.cat((encoded, context), dim=-1)
        ).squeeze(-1)
        group_decisions = outputs["ordinary_effective_business_decisions"]
        if group_decisions.ndim != 2 or group_decisions.shape[0] != road_mask.shape[0]:
            raise ValueError("ordinary structured plan business gate differs")
        group_indices = ordinary_set.side_group_indices
        valid_group = group_indices.ge(0) & group_indices.lt(
            group_decisions.shape[1]
        )
        safe_group_indices = group_indices.clamp(
            min=0,
            max=max(group_decisions.shape[1] - 1, 0),
        )
        free_run_gate = torch.gather(
            group_decisions,
            1,
            safe_group_indices,
        )
        free_run_gate = torch.where(
            valid_group,
            free_run_gate,
            torch.full_like(free_run_gate, ORDINARY_DECISION_ABSTAIN),
        )
        teacher = batch.teacher_gate_decisions
        gate = torch.where(teacher.ge(0), teacher, free_run_gate)
        allowed = (
            batch.plan_mask
            & batch.plan_hard_valid
            & batch.plan_base_decisions.eq(gate.unsqueeze(-1))
        )
        logits = raw_logits.masked_fill(~allowed, float("-inf"))
        selected = logits.argmax(dim=-1)
        selected_valid = allowed.any(dim=-1)
        return {
            "ordinary_structured_plan_raw_logits": raw_logits.masked_fill(
                ~batch.plan_mask,
                0.0,
            ),
            "ordinary_structured_plan_logits": logits,
            "ordinary_structured_plan_allowed_mask": allowed,
            "ordinary_structured_plan_selected_indices": selected,
            "ordinary_structured_plan_selected_valid": selected_valid,
            "ordinary_structured_plan_gate_decisions": gate,
            "_ordinary_structured_plan_encoded": encoded,
            "_ordinary_structured_plan_dynamic": dynamic,
        }

    @staticmethod
    def _structured_plan_dynamic_features(
        batch: OrdinaryJointStructuredPlanBatch,
        *,
        ordinary_set: EndToEndOrdinarySetBatch,
        access: OrdinaryJointAccessBatch,
        breaks: OrdinaryJointBreakBatch,
        outputs: Mapping[str, torch.Tensor],
    ) -> torch.Tensor:
        decisions = torch.log_softmax(
            outputs["ordinary_side_decision_logits"], dim=-1
        )
        decision_evidence = torch.gather(
            decisions.unsqueeze(2).expand(
                -1, -1, batch.plan_base_decisions.shape[2], -1
            ),
            -1,
            batch.plan_base_decisions.unsqueeze(-1),
        ).squeeze(-1)
        cardinality_logits = torch.log_softmax(
            outputs["ordinary_side_road_cardinality_logits"], dim=-1
        )
        cardinalities = batch.plan_road_membership.sum(dim=-1).clamp_max(
            cardinality_logits.shape[-1] - 1
        )
        cardinality_evidence = torch.gather(
            cardinality_logits.unsqueeze(2).expand(
                -1, -1, cardinalities.shape[2], -1
            ),
            -1,
            cardinalities.unsqueeze(-1),
        ).squeeze(-1)
        member_logits = outputs["ordinary_side_road_member_logits"].unsqueeze(2)
        selected_member = _masked_plan_scalar_mean(
            nn.functional.logsigmoid(member_logits),
            batch.plan_road_membership,
        )
        road_valid = ordinary_set.side_road_mask.unsqueeze(2)
        excluded_mask = road_valid & ~batch.plan_road_membership
        excluded_member = _masked_plan_scalar_mean(
            nn.functional.logsigmoid(-member_logits),
            excluded_mask,
        )
        role_evidence = _plan_target_log_mean(
            outputs["ordinary_side_road_business_role_logits"],
            batch.plan_role_targets,
            batch.plan_road_membership,
        )
        ownership_evidence = _plan_target_log_mean(
            outputs["ordinary_side_road_ownership_logits"],
            batch.plan_ownership_targets,
            batch.plan_road_membership,
        )
        access_compatible = _plan_proposal_compatibility(
            batch.plan_road_membership,
            batch.plan_access_road_membership,
            batch.access_group_arm_indices,
            access.proposal_road_indices,
        ) & access.proposal_mask.unsqueeze(2)
        mapped_access_group = batch.access_group_arm_indices.ne(
            ACCESS_GROUP_PADDING
        ).unsqueeze(2).unsqueeze(-1)
        active_access_proposal = (
            access.proposal_mask.unsqueeze(2) & mapped_access_group
        )
        access_logits = outputs[
            "ordinary_access_collection_member_logits"
        ].unsqueeze(2)
        access_positive = _masked_nested_mean(
            nn.functional.logsigmoid(access_logits),
            access_compatible,
        )
        access_negative = _masked_nested_mean(
            nn.functional.logsigmoid(-access_logits),
            active_access_proposal & ~access_compatible,
        )
        parent_selected = _plan_parent_compatibility(
            batch.plan_road_membership,
            breaks.parent_road_indices,
        ) & breaks.parent_mask.unsqueeze(2)
        presence = outputs["ordinary_break_presence_logits"].unsqueeze(2)
        break_confidence = _masked_plan_scalar_mean(
            torch.maximum(
                nn.functional.logsigmoid(presence),
                nn.functional.logsigmoid(-presence),
            ),
            parent_selected,
        )
        cardinality_normalized = torch.tanh(
            cardinalities.to(decision_evidence.dtype) / 8.0
        )
        values = torch.stack(
            (
                decision_evidence,
                cardinality_evidence,
                selected_member,
                excluded_member,
                role_evidence,
                ownership_evidence,
                access_positive,
                access_negative,
                break_confidence,
                cardinality_normalized,
            ),
            dim=-1,
        )
        return torch.where(torch.isfinite(values), values, torch.zeros_like(values))


def compute_ordinary_joint_mainline_loss(
    outputs: Mapping[str, torch.Tensor],
    ordinary: EndToEndOrdinarySetBatch,
    access: OrdinaryJointAccessBatch,
    breaks: OrdinaryJointBreakBatch,
    structured_plan: OrdinaryJointStructuredPlanBatch | None = None,
    *,
    config: TargetAOrdinaryJointMainlineConfig,
    decision_class_weights: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    ordinary_loss, ordinary_parts = compute_end_to_end_ordinary_set_loss(
        outputs,
        ordinary,
        decision_class_weights=decision_class_weights,
        cardinality_mode="categorical",
    )
    access_loss, access_parts = _access_collection_loss(outputs, access)
    break_loss, break_parts = _break_loss(outputs, breaks)
    if structured_plan is None:
        plan_loss = ordinary_loss * 0.0
        plan_parts: dict[str, torch.Tensor] = {}
    else:
        plan_loss = _structured_plan_loss(outputs, structured_plan)
        plan_parts = {"ordinary_structured_plan_loss": plan_loss}
    total = (
        ordinary_loss
        + config.access_loss_weight * access_loss
        + config.break_loss_weight * break_loss
        + config.plan_loss_weight * plan_loss
    )
    return total, {
        **ordinary_parts,
        **access_parts,
        **break_parts,
        **plan_parts,
        "ordinary_joint_loss": total,
    }


def _access_collection_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: OrdinaryJointAccessBatch,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    logits = outputs["ordinary_access_collection_member_logits"]
    targets = batch.proposal_targets.to(logits.dtype)
    active = batch.proposal_mask & batch.task_mask.unsqueeze(-1)
    positives = (targets * active.to(targets.dtype)).sum(dim=-1)
    negatives = active.sum(dim=-1).to(targets.dtype) - positives
    positive_weight = (negatives / positives.clamp_min(1.0)).clamp(1.0, 8.0)
    losses = nn.functional.binary_cross_entropy_with_logits(
        logits,
        targets,
        reduction="none",
    ) * torch.where(
        targets.gt(0.5),
        positive_weight.unsqueeze(-1),
        torch.ones_like(targets),
    )
    per_group = (losses * active.to(losses.dtype)).sum(dim=-1) / active.sum(
        dim=-1
    ).clamp_min(1)
    member_loss = _masked_group_mean(
        per_group,
        batch.task_mask,
        batch.sample_weights,
    )
    cardinality_losses = nn.functional.cross_entropy(
        outputs["ordinary_access_collection_cardinality_logits"].reshape(
            -1,
            outputs["ordinary_access_collection_cardinality_logits"].shape[-1],
        ),
        batch.cardinality_targets.clamp_max(
            outputs["ordinary_access_collection_cardinality_logits"].shape[-1]
            - 1
        ).reshape(-1),
        reduction="none",
    ).reshape_as(batch.cardinality_targets)
    cardinality_loss = _masked_group_mean(
        cardinality_losses,
        batch.task_mask,
        batch.sample_weights,
    )
    total = member_loss + 0.5 * cardinality_loss
    return total, {
        "ordinary_access_collection_member_loss": member_loss,
        "ordinary_access_collection_cardinality_loss": cardinality_loss,
    }


def _break_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: OrdinaryJointBreakBatch,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    task = batch.task_mask & batch.parent_mask
    presence_losses = nn.functional.binary_cross_entropy_with_logits(
        outputs["ordinary_break_presence_logits"],
        batch.presence_targets.to(
            outputs["ordinary_break_presence_logits"].dtype
        ),
        reduction="none",
    )
    presence_loss = _masked_group_mean(
        presence_losses,
        task,
        batch.sample_weights,
    )
    cardinality_logits = outputs["ordinary_break_cardinality_logits"]
    cardinality_losses = nn.functional.cross_entropy(
        cardinality_logits.reshape(-1, cardinality_logits.shape[-1]),
        batch.cardinality_targets.clamp_max(
            cardinality_logits.shape[-1] - 1
        ).reshape(-1),
        reduction="none",
    ).reshape_as(batch.cardinality_targets)
    cardinality_loss = _masked_group_mean(
        cardinality_losses,
        task,
        batch.sample_weights,
    )
    ownership_logits = outputs["ordinary_break_ownership_logits"]
    ownership_losses = nn.functional.cross_entropy(
        ownership_logits.reshape(-1, ownership_logits.shape[-1]),
        batch.ownership_targets.reshape(-1),
        reduction="none",
    ).reshape_as(batch.ownership_targets)
    ownership_loss = _masked_group_mean(
        ownership_losses,
        task,
        batch.sample_weights,
    )
    member_logits = outputs["ordinary_break_member_logits"]
    member_targets = batch.candidate_targets.to(member_logits.dtype)
    member_active = (
        batch.candidate_mask
        & task.unsqueeze(-1)
        & batch.presence_targets.unsqueeze(-1)
    )
    member_losses = nn.functional.binary_cross_entropy_with_logits(
        member_logits,
        member_targets,
        reduction="none",
    )
    per_parent = (
        member_losses * member_active.to(member_losses.dtype)
    ).sum(dim=-1) / member_active.sum(dim=-1).clamp_min(1)
    member_loss = _masked_group_mean(
        per_parent,
        task & batch.presence_targets,
        batch.sample_weights,
    )
    total = presence_loss + 0.5 * (
        cardinality_loss + ownership_loss + member_loss
    )
    return total, {
        "ordinary_break_presence_loss": presence_loss,
        "ordinary_break_cardinality_loss": cardinality_loss,
        "ordinary_break_ownership_loss": ownership_loss,
        "ordinary_break_member_loss": member_loss,
    }


def _structured_plan_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: OrdinaryJointStructuredPlanBatch,
) -> torch.Tensor:
    logits = outputs["ordinary_structured_plan_logits"]
    allowed = outputs["ordinary_structured_plan_allowed_mask"]
    acceptable = batch.acceptable_plan_mask & allowed
    task = batch.task_mask & acceptable.any(dim=-1) & allowed.any(dim=-1)
    if not bool(task.any()):
        return torch.where(torch.isfinite(logits), logits, torch.zeros_like(logits)).sum() * 0.0
    minimum = torch.finfo(logits.dtype).min
    all_logsumexp = torch.logsumexp(
        logits.masked_fill(~allowed, minimum), dim=-1
    )
    acceptable_logsumexp = torch.logsumexp(
        logits.masked_fill(~acceptable, minimum), dim=-1
    )
    return _masked_group_mean(
        all_logsumexp - acceptable_logsumexp,
        task,
        batch.sample_weights,
    )


def _stem(
    input_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim * 2),
        nn.GELU(),
        nn.LayerNorm(hidden_dim * 2),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
    )


def _head(
    input_dim: int,
    hidden_dim: int,
    output_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, output_dim),
    )


def _set_encoder(
    hidden_dim: int,
    heads: int,
    layers: int,
    dropout: float,
) -> nn.TransformerEncoder:
    layer = nn.TransformerEncoderLayer(
        d_model=hidden_dim,
        nhead=heads,
        dim_feedforward=hidden_dim * 4,
        dropout=dropout,
        activation="gelu",
        batch_first=True,
        norm_first=True,
    )
    return nn.TransformerEncoder(
        layer,
        num_layers=layers,
        enable_nested_tensor=False,
    )


def _encode_masked_set(
    encoder: nn.TransformerEncoder,
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    candidate_count = values.shape[-2]
    flat_values = values.reshape(-1, candidate_count, values.shape[-1])
    flat_mask = mask.reshape(-1, candidate_count)
    safe_mask = flat_mask.clone()
    empty = ~safe_mask.any(dim=-1)
    if bool(empty.any()):
        safe_mask[empty, 0] = True
    encoded = encoder(flat_values, src_key_padding_mask=~safe_mask)
    encoded = encoded * flat_mask.unsqueeze(-1).to(encoded.dtype)
    return encoded.reshape_as(values)


def _masked_pool(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    weights = mask.unsqueeze(-1).to(values.dtype)
    mean = (values * weights).sum(dim=-2) / weights.sum(dim=-2).clamp_min(1.0)
    maximum = values.masked_fill(
        ~mask.unsqueeze(-1),
        torch.finfo(values.dtype).min,
    ).amax(dim=-2)
    maximum = torch.where(
        mask.any(dim=-1).unsqueeze(-1),
        maximum,
        torch.zeros_like(maximum),
    )
    return mean, maximum


def _gather_road_values(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if values.ndim + 1 != indices.ndim + 1:
        expected = values.ndim - 2
        if indices.ndim < expected + 1:
            raise ValueError("ordinary joint Road gather rank differs")
    group_shape = indices.shape[2:]
    expanded = values
    for _ in group_shape[:-1]:
        expanded = expanded.unsqueeze(2)
    expanded = expanded.expand(
        values.shape[0],
        values.shape[1],
        *group_shape[:-1],
        values.shape[2],
        values.shape[-1],
    )
    safe = indices.clamp(min=0, max=values.shape[2] - 1)
    gathered = torch.gather(
        expanded,
        -2,
        safe.unsqueeze(-1).expand(*safe.shape, values.shape[-1]),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


def _masked_plan_road_pool(
    roads: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    expanded = roads.unsqueeze(2).expand(
        -1, -1, mask.shape[2], -1, -1
    )
    weights = mask.unsqueeze(-1).to(roads.dtype)
    mean = (expanded * weights).sum(dim=-2) / weights.sum(dim=-2).clamp_min(1.0)
    maximum = expanded.masked_fill(
        ~mask.unsqueeze(-1), torch.finfo(roads.dtype).min
    ).amax(dim=-2)
    maximum = torch.where(
        mask.any(dim=-1).unsqueeze(-1),
        maximum,
        torch.zeros_like(maximum),
    )
    return mean, maximum


def _masked_plan_scalar_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    expanded = values.expand_as(mask)
    weights = mask.to(expanded.dtype)
    return (expanded * weights).sum(dim=-1) / weights.sum(dim=-1).clamp_min(1.0)


def _plan_target_log_mean(
    logits: torch.Tensor,
    targets: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    log_probabilities = torch.log_softmax(logits, dim=-1)
    expanded = log_probabilities.unsqueeze(2).expand(
        -1, -1, targets.shape[2], -1, -1
    )
    selected = torch.gather(
        expanded,
        -1,
        targets.unsqueeze(-1),
    ).squeeze(-1)
    return _masked_plan_scalar_mean(selected, mask)


def _plan_proposal_compatibility(
    plan_roads: torch.Tensor,
    plan_arm_roads: torch.Tensor,
    group_arm_indices: torch.Tensor,
    proposal_road_indices: torch.Tensor,
) -> torch.Tensor:
    batch, sides, plans, arms, roads = plan_arm_roads.shape
    if plan_roads.shape != (batch, sides, plans, roads):
        raise ValueError("ordinary structured plan access Road set differs")
    groups, proposals = proposal_road_indices.shape[2:]
    if group_arm_indices.shape != (batch, sides, groups):
        raise ValueError("ordinary structured plan access arm mapping differs")
    safe_arm = group_arm_indices.clamp(min=0, max=arms - 1)
    expanded_arms = plan_arm_roads.unsqueeze(3).expand(
        batch, sides, plans, groups, arms, roads
    )
    selected_arms = torch.gather(
        expanded_arms,
        -2,
        safe_arm.unsqueeze(2).unsqueeze(-1).unsqueeze(-1).expand(
            batch, sides, plans, groups, 1, roads
        ),
    ).squeeze(-2)
    internal_group = group_arm_indices.eq(ACCESS_GROUP_INTERNAL)
    selected_roads = torch.where(
        internal_group.unsqueeze(2).unsqueeze(-1),
        plan_roads.unsqueeze(3).expand(batch, sides, plans, groups, roads),
        selected_arms,
    )
    safe_road = proposal_road_indices.clamp(min=0, max=roads - 1)
    gathered = torch.gather(
        selected_roads,
        -1,
        safe_road.unsqueeze(2).expand(
            batch, sides, plans, groups, proposals
        ),
    )
    return (
        gathered
        & group_arm_indices.ne(ACCESS_GROUP_PADDING).unsqueeze(2).unsqueeze(-1)
        & proposal_road_indices.ge(0).unsqueeze(2)
    )


def _plan_parent_compatibility(
    plan_roads: torch.Tensor,
    parent_road_indices: torch.Tensor,
) -> torch.Tensor:
    batch, sides, plans, _ = plan_roads.shape
    parents = parent_road_indices.shape[-1]
    safe = parent_road_indices.clamp(min=0, max=plan_roads.shape[-1] - 1)
    return torch.gather(
        plan_roads,
        -1,
        safe.unsqueeze(2).expand(batch, sides, plans, parents),
    ) & parent_road_indices.ge(0).unsqueeze(2)


def _masked_nested_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    expanded = values.expand_as(mask)
    weights = mask.to(expanded.dtype)
    dimensions = tuple(range(3, mask.ndim))
    return (expanded * weights).sum(dim=dimensions) / weights.sum(
        dim=dimensions
    ).clamp_min(1.0)


def _masked_group_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
    weights: torch.Tensor,
) -> torch.Tensor:
    if not bool(mask.any()):
        return values.sum() * 0.0
    normalized = weights / weights[mask].mean().clamp_min(1e-6)
    active = mask.to(values.dtype) * normalized
    return (values * active).sum() / active.sum().clamp_min(1.0)


__all__ = [
    "TargetAOrdinaryJointMainlineConfig",
    "TargetAOrdinaryJointMainlineNetwork",
    "compute_ordinary_joint_mainline_loss",
]
