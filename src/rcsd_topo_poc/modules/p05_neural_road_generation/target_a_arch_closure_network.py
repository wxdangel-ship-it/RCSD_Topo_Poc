from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureModelInput,
    ArchClosureSegmentContextBatch,
    ArchClosureStructuredPlanInput,
    JUNCTION_CONFIDENCE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ordinary_business_states_from_anchor_state,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetNetwork,
    decode_ordinary_road_cardinality,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_COUNT,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_network import (
    TargetAOrdinaryJointMainlineNetwork,
)


ANCHOR_BUSINESS_STATE_COUNT = 3


@dataclass(frozen=True)
class _StructuredForwardInput:
    plan_feature_values: torch.Tensor
    plan_mask: torch.Tensor
    plan_hard_valid: torch.Tensor
    plan_base_decisions: torch.Tensor
    plan_road_membership: torch.Tensor
    plan_role_targets: torch.Tensor
    plan_ownership_targets: torch.Tensor
    plan_access_road_membership: torch.Tensor
    access_group_arm_indices: torch.Tensor
    teacher_gate_decisions: torch.Tensor


@dataclass(frozen=True)
class TargetAArchClosureConfig:
    junction_embedding_dim: int
    context_set_layers: int = 1
    context_set_heads: int = 4
    detach_junction_embeddings: bool = True

    def validate(self, *, hidden_dim: int) -> None:
        if min(
            self.junction_embedding_dim,
            self.context_set_layers,
            self.context_set_heads,
        ) < 1:
            raise ValueError("architecture-closure context dimensions are invalid")
        if hidden_dim % self.context_set_heads:
            raise ValueError("architecture-closure context heads do not divide hidden dim")


class _SegmentEvidenceEncoder(nn.Module):
    """Encode inference-time Segment/Junction evidence without terminal labels."""

    def __init__(
        self,
        *,
        hidden_dim: int,
        junction_embedding_dim: int,
        set_layers: int,
        set_heads: int,
        dropout: float,
        detach_junction_embeddings: bool,
    ) -> None:
        super().__init__()
        self.detach_junction_embeddings = detach_junction_embeddings
        self.focal_stem = _stem(TARGET_A_FEATURE_DIM, hidden_dim, dropout)
        self.peer_stem = _stem(TARGET_A_FEATURE_DIM, hidden_dim, dropout)
        self.junction_stem = _stem(
            junction_embedding_dim
            + JUNCTION_CONFIDENCE_DIM
            + ANCHOR_BUSINESS_STATE_COUNT,
            hidden_dim,
            dropout,
        )
        self.peer_set_encoder = _set_encoder(
            hidden_dim,
            set_heads,
            set_layers,
            dropout,
        )
        self.junction_peer_fusion = _stem(
            3 * hidden_dim,
            hidden_dim,
            dropout,
        )
        self.junction_set_encoder = _set_encoder(
            hidden_dim,
            set_heads,
            set_layers,
            dropout,
        )
        self.output = _stem(5 * hidden_dim, hidden_dim, dropout)

    def forward(self, batch: ArchClosureSegmentContextBatch) -> torch.Tensor:
        focal = self.focal_stem(batch.focal_feature_values)
        peers = _encode_masked_set(
            self.peer_set_encoder,
            self.peer_stem(batch.peer_feature_values),
            batch.peer_mask,
        )
        peer_mean, peer_maximum = _masked_pool(peers, batch.peer_mask)
        state_one_hot = nn.functional.one_hot(
            batch.junction_state_values,
            num_classes=ANCHOR_BUSINESS_STATE_COUNT,
        ).to(batch.junction_embedding_values.dtype)
        junction_embedding_values = batch.junction_embedding_values
        junction_confidence_values = batch.junction_confidence_values
        if self.detach_junction_embeddings:
            junction_embedding_values = junction_embedding_values.detach()
            junction_confidence_values = junction_confidence_values.detach()
        junctions = self.junction_stem(
            torch.cat(
                (
                    junction_embedding_values,
                    junction_confidence_values,
                    state_one_hot,
                ),
                dim=-1,
            )
        )
        relation = (
            batch.peer_junction_relation_mask
            & batch.peer_mask.unsqueeze(-1)
            & batch.junction_mask.unsqueeze(1)
        )
        weights = relation.to(peers.dtype)
        related_mean = torch.einsum("bpj,bph->bjh", weights, peers) / weights.sum(
            dim=1
        ).clamp_min(1.0).unsqueeze(-1)
        related_maximum = peers.unsqueeze(2).masked_fill(
            ~relation.unsqueeze(-1),
            torch.finfo(peers.dtype).min,
        ).amax(dim=1)
        related_maximum = torch.where(
            relation.any(dim=1).unsqueeze(-1),
            related_maximum,
            torch.zeros_like(related_maximum),
        )
        junctions = self.junction_peer_fusion(
            torch.cat((junctions, related_mean, related_maximum), dim=-1)
        )
        junctions = _encode_masked_set(
            self.junction_set_encoder,
            junctions,
            batch.junction_mask,
        )
        junction_mean, junction_maximum = _masked_pool(
            junctions,
            batch.junction_mask,
        )
        return self.output(
            torch.cat(
                (
                    focal,
                    peer_mean,
                    peer_maximum,
                    junction_mean,
                    junction_maximum,
                ),
                dim=-1,
            )
        )


class TargetAArchClosureNetwork(nn.Module):
    """Source-first complete ordinary Segment plan decoder after locked anchoring."""

    def __init__(
        self,
        template: TargetAOrdinaryJointMainlineNetwork,
        config: TargetAArchClosureConfig,
    ) -> None:
        super().__init__()
        ordinary = template.ordinary
        hidden_dim = ordinary.config.hidden_dim
        road_hidden_dim = ordinary.config.road_hidden_dim
        config.validate(hidden_dim=hidden_dim)
        if config.junction_embedding_dim != hidden_dim:
            raise ValueError(
                "Junction embedding dim must match the frozen anchor backbone"
            )
        self.config = config
        self.ordinary_config = ordinary.config
        self.mainline_config = template.config

        self.source_evidence_encoder = _SegmentEvidenceEncoder(
            hidden_dim=hidden_dim,
            junction_embedding_dim=config.junction_embedding_dim,
            set_layers=config.context_set_layers,
            set_heads=config.context_set_heads,
            dropout=ordinary.config.dropout,
            detach_junction_embeddings=config.detach_junction_embeddings,
        )
        self.plan_evidence_encoder = _SegmentEvidenceEncoder(
            hidden_dim=hidden_dim,
            junction_embedding_dim=config.junction_embedding_dim,
            set_layers=config.context_set_layers,
            set_heads=config.context_set_heads,
            dropout=ordinary.config.dropout,
            detach_junction_embeddings=config.detach_junction_embeddings,
        )

        for name in (
            "road_stem",
            "relation_stem",
            "relation_fusion",
            "road_anchor_relation_stem",
            "road_set_encoder",
            "object_stem",
            "decision_head",
            "cardinality_head",
            "member_head",
            "ownership_head",
            "business_role_head",
        ):
            setattr(self, name, deepcopy(getattr(ordinary, name)))
        self.road_anchor_relation_scale = nn.Parameter(
            ordinary.road_anchor_relation_scale.detach().clone()
        )
        self.source_context = _stem(
            2 * hidden_dim + 2 * road_hidden_dim,
            hidden_dim,
            ordinary.config.dropout,
        )
        self.plan_context = _stem(
            2 * hidden_dim + 2 * road_hidden_dim + ORDINARY_DECISION_COUNT,
            hidden_dim,
            ordinary.config.dropout,
        )

        for name in (
            "access_proposal_stem",
            "access_road_fusion",
            "access_set_encoder",
            "access_group_context",
            "access_member_head",
            "access_cardinality_head",
            "break_candidate_stem",
            "break_set_encoder",
            "break_group_context",
            "break_member_head",
            "break_presence_head",
            "break_cardinality_head",
            "break_ownership_head",
            "structured_plan_stem",
            "structured_plan_set_encoder",
            "structured_plan_head",
        ):
            setattr(self, name, deepcopy(getattr(template, name)))

    def forward(
        self,
        inputs: ArchClosureModelInput,
        *,
        teacher_gate_decisions: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        ordinary = inputs.ordinary
        structured = _structured_forward_input(
            inputs.structured,
            teacher_gate_decisions=teacher_gate_decisions,
        )
        road_encoded = TargetAEndToEndOrdinarySetNetwork._encode_roads(
            self,
            ordinary,
            anchor_outputs=None,
        )
        road_mean, road_maximum = _masked_pool(
            road_encoded,
            ordinary.side_road_mask,
        )
        source_evidence = self.source_evidence_encoder(inputs.context)
        plan_evidence = self.plan_evidence_encoder(inputs.context)
        focal_object = self.object_stem(ordinary.side_object_values[:, 0])
        source_context = self.source_context(
            torch.cat(
                (
                    source_evidence,
                    focal_object,
                    road_mean[:, 0].detach(),
                    road_maximum[:, 0].detach(),
                ),
                dim=-1,
            )
        )
        source_logits = self.decision_head(source_context)
        source_probabilities = torch.softmax(source_logits, dim=-1)
        plan_context = self.plan_context(
            torch.cat(
                (
                    plan_evidence,
                    source_context.detach(),
                    source_probabilities.detach(),
                    road_mean[:, 0],
                    road_maximum[:, 0],
                ),
                dim=-1,
            )
        )
        zero_context = torch.zeros_like(plan_context).unsqueeze(1)
        side_context = torch.cat((plan_context.unsqueeze(1), zero_context), dim=1)
        zero_logits = torch.zeros_like(source_logits).unsqueeze(1)
        decision_logits = torch.cat((source_logits.unsqueeze(1), zero_logits), dim=1)
        decision_probabilities = torch.softmax(decision_logits, dim=-1)

        expanded_context = side_context.unsqueeze(2).expand(
            -1, -1, road_encoded.shape[2], -1
        )
        expanded_decisions = decision_probabilities.detach().unsqueeze(2).expand(
            -1, -1, road_encoded.shape[2], -1
        )
        road_business_inputs = torch.cat(
            (road_encoded, expanded_context, expanded_decisions),
            dim=-1,
        )
        member_logits = self.member_head(road_business_inputs).squeeze(-1)
        member_logits = member_logits.masked_fill(~ordinary.side_road_mask, 0.0)
        cardinality_logits = self.cardinality_head(side_context)
        detached_business_inputs = road_business_inputs.detach()
        ownership_logits = self.ownership_head(detached_business_inputs)
        role_logits = self.business_role_head(detached_business_inputs)

        source_business = ordinary_business_states_from_anchor_state(
            ordinary.side_precomputed_anchor_state[:, 0:1],
            decision_probabilities[:, 0:1],
        )
        outputs = {
            "ordinary_side_decision_logits": decision_logits,
            "ordinary_side_decision_probabilities": decision_probabilities,
            "ordinary_side_road_member_logits": member_logits,
            "ordinary_side_road_base_member_logits": member_logits,
            "ordinary_side_road_ownership_logits": ownership_logits.masked_fill(
                ~ordinary.side_road_mask.unsqueeze(-1), 0.0
            ),
            "ordinary_side_road_business_role_logits": role_logits.masked_fill(
                ~ordinary.side_road_mask.unsqueeze(-1), 0.0
            ),
            "ordinary_side_road_cardinality_logits": cardinality_logits,
            "ordinary_side_road_cardinality_predictions": (
                decode_ordinary_road_cardinality(
                    cardinality_logits,
                    mode=self.ordinary_config.cardinality_mode,
                )
            ),
            "ordinary_side_access_logits": torch.zeros(
                ordinary.side_access_mask.shape,
                dtype=road_encoded.dtype,
                device=road_encoded.device,
            ).masked_fill(~ordinary.side_access_mask, float("-inf")),
            "ordinary_side_context": side_context,
            "ordinary_source_context": source_context,
            "ordinary_group_decision_probabilities": decision_probabilities[:, 0:1],
            "ordinary_raw_business_decisions": source_business["raw_decision"],
            "ordinary_effective_business_decisions": source_business[
                "effective_decision"
            ],
            "ordinary_anchor_business_state": source_business["anchor_state"],
            "_ordinary_road_encoded": road_encoded,
        }
        road_membership = torch.sigmoid(member_logits)
        outputs.update(
            TargetAOrdinaryJointMainlineNetwork._forward_access(
                self,
                inputs.access,
                road_encoded=road_encoded,
                road_membership=road_membership,
                side_context=side_context,
            )
        )
        outputs.update(
            TargetAOrdinaryJointMainlineNetwork._forward_breaks(
                self,
                inputs.breaks,
                road_encoded=road_encoded,
                road_membership=road_membership,
                side_context=side_context,
            )
        )
        outputs.update(
            TargetAOrdinaryJointMainlineNetwork._forward_structured_plan(
                self,
                structured,
                ordinary_set=ordinary,
                access=inputs.access,
                breaks=inputs.breaks,
                outputs=outputs,
            )
        )
        return outputs

    @staticmethod
    def _structured_plan_dynamic_features(
        batch: object,
        *,
        ordinary_set: object,
        access: object,
        breaks: object,
        outputs: Mapping[str, torch.Tensor],
    ) -> torch.Tensor:
        detached_outputs = {
            **outputs,
            "ordinary_side_decision_logits": outputs[
                "ordinary_side_decision_logits"
            ].detach(),
        }
        return TargetAOrdinaryJointMainlineNetwork._structured_plan_dynamic_features(
            batch,  # type: ignore[arg-type]
            ordinary_set=ordinary_set,  # type: ignore[arg-type]
            access=access,  # type: ignore[arg-type]
            breaks=breaks,  # type: ignore[arg-type]
            outputs=detached_outputs,
        )


def _structured_forward_input(
    source: ArchClosureStructuredPlanInput,
    *,
    teacher_gate_decisions: torch.Tensor | None,
) -> _StructuredForwardInput:
    if teacher_gate_decisions is None:
        teacher_gate_decisions = torch.full(
            source.plan_mask.shape[:2],
            -1,
            dtype=torch.long,
            device=source.plan_mask.device,
        )
    if teacher_gate_decisions.shape != source.plan_mask.shape[:2]:
        raise ValueError("architecture-closure teacher gate shape differs")
    return _StructuredForwardInput(
        plan_feature_values=source.plan_feature_values,
        plan_mask=source.plan_mask,
        plan_hard_valid=source.plan_hard_valid,
        plan_base_decisions=source.plan_base_decisions,
        plan_road_membership=source.plan_road_membership,
        plan_role_targets=source.plan_role_values,
        plan_ownership_targets=source.plan_ownership_values,
        plan_access_road_membership=source.plan_access_road_membership,
        access_group_arm_indices=source.access_group_arm_indices,
        teacher_gate_decisions=teacher_gate_decisions,
    )


def _stem(input_dim: int, hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim * 2),
        nn.GELU(),
        nn.LayerNorm(hidden_dim * 2),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
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


__all__ = [
    "TargetAArchClosureConfig",
    "TargetAArchClosureNetwork",
]
