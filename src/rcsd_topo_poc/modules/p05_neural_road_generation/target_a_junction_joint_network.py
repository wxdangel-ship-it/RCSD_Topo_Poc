from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_INCIDENCE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    MAX_BREAKS_PER_ROAD,
    TASK_CLASSES,
    JunctionJointBatch,
    relation_candidate_constraints,
    virtual_surface_carrier_candidate_mask,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_structured_decoder import (
    JunctionStructuredSetDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RADIUS_M,
    GEOMETRY_RELATION_DIM,
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    MEMBER_FEATURE_DIM,
    OBJECT_FEATURE_DIM,
    SURFACE_GRID_HALF_EXTENT_M,
    SURFACE_GRID_SIZE,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_one_way_object_branch import (
    JunctionOneWayObjectBranch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_weak_evidence_branch import (
    JunctionWeakEvidenceBranch,
)


@dataclass(frozen=True)
class JunctionJointConfig:
    hidden_dim: int = 320
    num_heads: int = 8
    feedforward_dim: int = 1_280
    object_layers: int = 3
    candidate_layers: int = 1
    member_layers: int = 1
    member_graph_layers: int = 0
    geometry_graph_layers: int = 0
    trunk_layers: int = 2
    dropout: float = 0.10
    object_cardinality_count: int = 16
    surface_object_cardinality_count: int = 4
    virtual_surface_carrier_cardinality_count: int = 9
    structured_virtual_surface_carrier_decoder: bool = False
    structured_virtual_surface_carrier_max_steps: int = 9
    virtual_surface_geometric_coverage_training: bool = False
    structured_surface_decoder: bool = False
    high_resolution_surface_evidence: bool = False
    business_plan_count: int = 0
    structured_member_decoder: bool = False
    structured_member_max_steps: int = 24
    structured_relation_decoder: bool = False
    structured_relation_max_steps: int = 12
    structured_relation_graph_conditioning: bool = False
    one_way_object_branch: bool = False
    one_way_object_hidden_dim: int = 192
    one_way_object_num_heads: int = 6
    weak_evidence_branch: bool = False
    weak_evidence_hidden_dim: int = 192
    weak_evidence_num_heads: int = 6
    min_parameter_count: int = 10_000_000
    max_parameter_count: int = 20_000_000

    def validate(self) -> None:
        if self.hidden_dim < 64 or self.hidden_dim % self.num_heads:
            raise ValueError("junction hidden dimension must divide by head count")
        if self.feedforward_dim < self.hidden_dim:
            raise ValueError("junction feedforward dimension is too small")
        if min(
            self.object_layers,
            self.candidate_layers,
            self.member_layers,
            self.trunk_layers,
        ) < 1:
            raise ValueError("junction hierarchy layer counts must be positive")
        if min(self.member_graph_layers, self.geometry_graph_layers) < 0:
            raise ValueError("junction graph layer count cannot be negative")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("junction dropout is invalid")
        if self.object_cardinality_count < 16:
            raise ValueError("junction object cardinality cannot express current Gold")
        if self.surface_object_cardinality_count < 3:
            raise ValueError(
                "junction surface object cardinality cannot express current Gold"
            )
        if self.virtual_surface_carrier_cardinality_count < 9:
            raise ValueError(
                "virtual surface carrier cardinality cannot express 0..8 objects"
            )
        if self.structured_virtual_surface_carrier_max_steps < 9:
            raise ValueError(
                "structured virtual surface carrier decoder requires 8 plus STOP"
            )
        if self.structured_surface_decoder and self.high_resolution_surface_evidence:
            raise ValueError("junction surface canary decoders are mutually exclusive")
        if self.business_plan_count == 1 or self.business_plan_count < 0:
            raise ValueError("junction business plan count must be zero or at least two")
        if self.structured_member_max_steps < 1:
            raise ValueError("junction structured member step count is invalid")
        if self.structured_relation_max_steps < 12:
            raise ValueError(
                "junction structured relation decoder requires 11 plus STOP"
            )
        if (
            self.structured_relation_graph_conditioning
            and not self.structured_relation_decoder
        ):
            raise ValueError(
                "junction relation graph conditioning requires its decoder"
            )
        if sum(
            bool(value)
            for value in (
                self.structured_member_decoder,
                self.structured_relation_decoder,
                self.one_way_object_branch,
            )
        ) > 1:
            raise ValueError("junction structured object decoders are mutually exclusive")
        if self.one_way_object_branch and not self.business_plan_count:
            raise ValueError("one-way object branch requires business plans")
        if (
            self.one_way_object_hidden_dim < 64
            or self.one_way_object_hidden_dim % self.one_way_object_num_heads
        ):
            raise ValueError("one-way object branch hidden dimension is invalid")
        if (
            self.weak_evidence_hidden_dim < 64
            or self.weak_evidence_hidden_dim % self.weak_evidence_num_heads
        ):
            raise ValueError("weak evidence branch hidden dimension is invalid")


class JunctionJointNetwork(nn.Module):
    """Anchor-first hierarchy over raw evidence with a complete object-set decoder."""

    def __init__(self, config: JunctionJointConfig = JunctionJointConfig()) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.hidden_dim

        # Step1 receives only the physically isolated DriveZone token tensor.
        self.step1_token_stem = _stem(GEOMETRY_TOKEN_DIM, hidden, config.dropout)
        self.step1_pool_score = nn.Linear(hidden, 1)
        self.step1_grid_encoder = nn.Sequential(
            nn.Conv2d(1, 16, 5, stride=2, padding=2),
            nn.GELU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1),
            nn.GELU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),
            nn.GELU(),
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(64, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
        )
        self.step1_head = _head(hidden, len(TASK_CLASSES["t07_step1"]), config.dropout)

        # Step2 receives only raw RCSDIntersection tokens and a detached Step1 state.
        self.step2_token_stem = _stem(GEOMETRY_TOKEN_DIM, hidden, config.dropout)
        self.step2_pool_score = nn.Linear(hidden, 1)
        self.step1_condition = nn.Linear(len(TASK_CLASSES["t07_step1"]), hidden)
        self.step2_head = _head(hidden, len(TASK_CLASSES["t07_step2"]), config.dropout)

        self.geometry_token_stem = _stem(
            GEOMETRY_TOKEN_DIM,
            hidden,
            config.dropout,
        )
        self.geometry_object_fusion = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
        )
        self.geometry_role_embedding = nn.Embedding(len(GEOMETRY_ROLE_INDEX), hidden)
        self.geometry_relation_stem = (
            _stem(GEOMETRY_RELATION_DIM, hidden, config.dropout)
            if config.geometry_graph_layers
            else None
        )
        self.geometry_graph_blocks = nn.ModuleList(
            _SparseObjectGraphBlock(hidden, config.dropout)
            for _ in range(config.geometry_graph_layers)
        )
        self.geometry_object_encoder = _set_encoder(config, config.object_layers)
        self.geometry_pool_score = nn.Linear(hidden, 1)

        self.object_stem = _stem(OBJECT_FEATURE_DIM, hidden, config.dropout)
        self.candidate_stem = _stem(OBJECT_FEATURE_DIM, hidden, config.dropout)
        self.member_stem = _stem(MEMBER_FEATURE_DIM, hidden, config.dropout)
        self.candidate_encoder = _set_encoder(config, config.candidate_layers)
        self.member_encoder = _set_encoder(config, config.member_layers)
        self.member_arm_stem = (
            _stem(ANCHOR_ARM_FEATURE_DIM, hidden, config.dropout)
            if config.member_graph_layers
            else None
        )
        self.member_arm_match_fusion = (
            nn.Sequential(
                nn.Linear(hidden * 4, hidden),
                nn.GELU(),
                nn.LayerNorm(hidden),
            )
            if config.member_graph_layers
            else None
        )
        self.member_relation_stem = (
            _stem(ANCHOR_MEMBER_RELATION_DIM, hidden, config.dropout)
            if config.member_graph_layers
            else None
        )
        self.member_incidence_stem = (
            _stem(ANCHOR_MEMBER_INCIDENCE_DIM, hidden, config.dropout)
            if config.member_graph_layers
            else None
        )
        self.member_graph_blocks = nn.ModuleList(
            _MemberGraphBlock(hidden, config.dropout)
            for _ in range(config.member_graph_layers)
        )
        self.geometry_member_fusion = (
            nn.Sequential(
                nn.Linear(hidden * 2, hidden),
                nn.GELU(),
                nn.LayerNorm(hidden),
            )
            if config.member_graph_layers
            else None
        )
        self.candidate_pool_score = nn.Linear(hidden, 1)
        self.member_pool_score = nn.Linear(hidden, 1)

        condition_dim = len(TASK_CLASSES["t07_step1"]) + len(TASK_CLASSES["t07_step2"])
        self.context_fusion = nn.Sequential(
            nn.Linear(hidden * 4 + condition_dim, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
        )
        self.trunk = nn.ModuleList(
            _residual_block(hidden, config.feedforward_dim, config.dropout)
            for _ in range(config.trunk_layers)
        )

        self.surface_mode_head = _head(
            hidden,
            len(TASK_CLASSES["surface_mode"]),
            config.dropout,
        )
        self.surface_mode_condition = nn.Linear(
            len(TASK_CLASSES["surface_mode"]), hidden
        )
        self.surface_state_head = _head(
            hidden,
            len(TASK_CLASSES["surface_state"]),
            config.dropout,
        )
        self.surface_condition = nn.Linear(
            len(TASK_CLASSES["surface_state"]),
            hidden,
        )
        self.relation_head = _head(
            hidden,
            len(TASK_CLASSES["relation_state"]),
            config.dropout,
        )
        self.relation_condition = nn.Linear(
            len(TASK_CLASSES["relation_state"]),
            hidden,
        )
        self.action_head = _head(
            hidden,
            len(TASK_CLASSES["junctionization_action"]),
            config.dropout,
        )
        self.action_condition = nn.Linear(
            len(TASK_CLASSES["junctionization_action"]),
            hidden,
        )
        self.final_state_head = _head(
            hidden,
            len(TASK_CLASSES["final_state"]),
            config.dropout,
        )
        self.business_plan_head = (
            _head(hidden, config.business_plan_count, config.dropout)
            if config.business_plan_count
            else None
        )
        self.business_plan_condition = (
            nn.Linear(config.business_plan_count, hidden)
            if config.business_plan_count
            else None
        )
        if self.business_plan_condition is not None:
            nn.init.zeros_(self.business_plan_condition.weight)
            nn.init.zeros_(self.business_plan_condition.bias)

        self.surface_token_projection = nn.Linear(hidden, 64)
        self.surface_context_projection = nn.Linear(hidden, 64)
        self.surface_drivezone_projection = nn.Conv2d(1, 64, 1)
        self.surface_decoder = nn.Sequential(
            nn.Conv2d(64, 64, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(64, 64, 3, padding=1),
            nn.GELU(),
            nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1),
            nn.GELU(),
            nn.ConvTranspose2d(32, 1, 4, stride=2, padding=1),
        )
        self.surface_refinement = nn.Sequential(
            nn.Conv2d(2, 32, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(32, 32, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(32, 1, 1),
        )
        nn.init.zeros_(self.surface_refinement[-1].weight)
        nn.init.zeros_(self.surface_refinement[-1].bias)
        self.surface_boundary_decoder = (
            nn.Sequential(
                nn.Conv2d(2, 32, 3, padding=1),
                nn.GELU(),
                nn.Conv2d(32, 32, 3, padding=1),
                nn.GELU(),
                nn.Conv2d(32, 6, 1),
            )
            if config.structured_surface_decoder
            else None
        )
        self.surface_high_resolution_refinement = (
            nn.Sequential(
                nn.Conv2d(2 + len(GEOMETRY_ROLE_INDEX), 48, 3, padding=1),
                nn.GELU(),
                nn.Conv2d(48, 48, 3, padding=2, dilation=2),
                nn.GELU(),
                nn.Conv2d(48, 32, 3, padding=4, dilation=4),
                nn.GELU(),
                nn.Conv2d(32, 1, 1),
            )
            if config.high_resolution_surface_evidence
            else None
        )
        if self.surface_high_resolution_refinement is not None:
            nn.init.zeros_(self.surface_high_resolution_refinement[-1].weight)
            nn.init.zeros_(self.surface_high_resolution_refinement[-1].bias)

        self.surface_object_score = _pair_score(hidden)
        self.surface_object_cardinality_head = _head(
            hidden,
            config.surface_object_cardinality_count,
            config.dropout,
        )
        self.virtual_surface_carrier_score = _pair_score(hidden)
        self.virtual_surface_carrier_cardinality_head = _head(
            hidden,
            config.virtual_surface_carrier_cardinality_count,
            config.dropout,
        )
        self.structured_virtual_surface_carrier_decoder = (
            JunctionStructuredSetDecoder(
                hidden,
                dropout=config.dropout,
                max_steps=config.structured_virtual_surface_carrier_max_steps,
            )
            if config.structured_virtual_surface_carrier_decoder
            else None
        )
        self.object_score = _pair_score(hidden)
        self.action_object_scores = nn.ModuleList(
            _pair_score(hidden)
            for _ in TASK_CLASSES["junctionization_action"]
        )
        self.object_cardinality_head = _head(
            hidden,
            config.object_cardinality_count,
            config.dropout,
        )
        self.object_role_cardinality_head = _head(
            hidden,
            2 * config.object_cardinality_count,
            config.dropout,
        )
        self.candidate_score = _pair_score(hidden)
        self.member_score = _pair_score(hidden)
        self.structured_member_decoder = (
            JunctionStructuredSetDecoder(
                hidden,
                dropout=config.dropout,
                max_steps=config.structured_member_max_steps,
            )
            if config.structured_member_decoder
            else None
        )
        self.structured_relation_decoder = (
            JunctionStructuredSetDecoder(
                hidden,
                dropout=config.dropout,
                max_steps=config.structured_relation_max_steps,
                relation_dim=(
                    GEOMETRY_RELATION_DIM
                    if config.structured_relation_graph_conditioning
                    else 0
                ),
            )
            if config.structured_relation_decoder
            else None
        )
        self.one_way_object_decoder = (
            JunctionOneWayObjectBranch(
                hidden_dim=config.one_way_object_hidden_dim,
                num_heads=config.one_way_object_num_heads,
                dropout=config.dropout,
                business_plan_count=config.business_plan_count,
                cardinality_count=config.object_cardinality_count,
                structured_max_steps=config.structured_member_max_steps,
            )
            if config.one_way_object_branch
            else None
        )
        self.weak_evidence_encoder = (
            JunctionWeakEvidenceBranch(
                hidden_dim=config.weak_evidence_hidden_dim,
                num_heads=config.weak_evidence_num_heads,
                dropout=config.dropout,
            )
            if config.weak_evidence_branch
            else None
        )
        self.weak_evidence_fusion = (
            nn.Sequential(
                nn.Linear(
                    hidden + config.weak_evidence_hidden_dim + 1,
                    hidden,
                ),
                nn.GELU(),
                nn.LayerNorm(hidden),
                nn.Linear(hidden, hidden),
            )
            if config.weak_evidence_branch
            else None
        )
        if self.weak_evidence_fusion is not None:
            nn.init.zeros_(self.weak_evidence_fusion[-1].weight)
            nn.init.zeros_(self.weak_evidence_fusion[-1].bias)

        self.object_main_score = _pair_score(hidden)
        self.break_slot_embeddings = nn.Parameter(
            torch.empty(MAX_BREAKS_PER_ROAD, hidden)
        )
        nn.init.normal_(self.break_slot_embeddings, std=0.02)
        self.break_decoder = nn.Sequential(
            nn.LayerNorm(hidden),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
        )
        self.break_presence_head = nn.Linear(hidden, 1)
        self.break_offset_head = nn.Linear(hidden, 1)
        nn.init.zeros_(self.break_offset_head.weight)
        nn.init.zeros_(self.break_offset_head.bias)
        self.break_main_head = nn.Linear(hidden, 1)

        count = parameter_count(self)
        if not config.min_parameter_count <= count <= config.max_parameter_count:
            raise ValueError(
                "junction joint parameter count outside frozen range: "
                f"{count:,}"
            )

    def forward(
        self,
        batch: JunctionJointBatch,
        *,
        teacher_labels: Mapping[str, torch.Tensor] | None = None,
        teacher_masks: Mapping[str, torch.Tensor] | None = None,
        teacher_forcing_ratio: float = 0.0,
        teacher_member_sets: torch.Tensor | None = None,
        teacher_member_set_mask: torch.Tensor | None = None,
        teacher_member_task_mask: torch.Tensor | None = None,
        teacher_virtual_surface_carrier_sets: torch.Tensor | None = None,
        teacher_virtual_surface_carrier_set_mask: torch.Tensor | None = None,
        teacher_virtual_surface_carrier_task_mask: torch.Tensor | None = None,
        teacher_relation_sets: torch.Tensor | None = None,
        teacher_relation_set_mask: torch.Tensor | None = None,
        teacher_relation_task_mask: torch.Tensor | None = None,
    ) -> Mapping[str, torch.Tensor]:
        if not 0.0 <= teacher_forcing_ratio <= 1.0:
            raise ValueError("teacher forcing ratio must be within [0, 1]")

        step1_hidden = self.step1_token_stem(batch.step1_tokens)
        step1_context = _attention_pool(
            step1_hidden,
            batch.step1_token_mask,
            self.step1_pool_score,
        ) + self.step1_grid_encoder(batch.drivezone_grid)
        step1_logits = self.step1_head(step1_context)
        step1_value = _condition_value(
            "t07_step1",
            step1_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )

        step2_hidden = self.step2_token_stem(batch.step2_tokens)
        step2_context = _attention_pool(
            step2_hidden,
            batch.step2_token_mask,
            self.step2_pool_score,
        ) + self.step1_condition(step1_value)
        step2_logits = self.step2_head(step2_context)
        step2_value = _condition_value(
            "t07_step2",
            step2_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )

        geometry_tokens = self.geometry_token_stem(batch.geometry_tokens)
        geometry_objects = _pool_tokens_by_object(
            geometry_tokens,
            batch.geometry_token_mask,
            batch.geometry_token_object_index,
            batch.geometry_object_mask.shape[1],
            self.geometry_object_fusion,
        )
        safe_roles = batch.geometry_object_roles.clamp_min(0)
        geometry_objects = geometry_objects + self.geometry_role_embedding(safe_roles)
        geometry_objects = self._encode_geometry_graph(geometry_objects, batch)

        object_context = self.object_stem(batch.object_features)
        candidate_hidden = _encode_set(
            self.candidate_stem(batch.candidate_features),
            batch.candidate_mask,
            self.candidate_encoder,
        )
        member_hidden = self.member_stem(batch.member_features)
        member_hidden = self._encode_member_graph(
            member_hidden,
            batch,
        )
        member_hidden = _encode_set(
            member_hidden,
            batch.member_mask,
            self.member_encoder,
        )
        geometry_objects = self._fuse_geometry_members(
            geometry_objects,
            member_hidden,
            batch,
        )
        geometry_objects = _encode_set(
            geometry_objects,
            batch.geometry_object_mask,
            self.geometry_object_encoder,
        )
        geometry_pool = _attention_pool(
            geometry_objects,
            batch.geometry_object_mask,
            self.geometry_pool_score,
        )
        candidate_pool = _attention_pool(
            candidate_hidden,
            batch.candidate_mask,
            self.candidate_pool_score,
        )
        member_pool = _attention_pool(
            member_hidden,
            batch.member_mask,
            self.member_pool_score,
        )
        context = self.context_fusion(
            torch.cat(
                (
                    object_context,
                    geometry_pool,
                    candidate_pool,
                    member_pool,
                    step1_value,
                    step2_value,
                ),
                dim=-1,
            )
        )
        for block in self.trunk:
            context = context + block(context)

        surface_mode_logits = self.surface_mode_head(context)
        surface_mode_value = _condition_value(
            "surface_mode",
            surface_mode_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )
        surface_context = context + self.surface_mode_condition(surface_mode_value)
        surface_state_logits = self.surface_state_head(surface_context)
        surface_value = _condition_value(
            "surface_state",
            surface_state_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )
        relation_context = surface_context + self.surface_condition(surface_value)
        relation_logits = self.relation_head(relation_context)
        relation_value = _condition_value(
            "relation_state",
            relation_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )
        action_context = relation_context + self.relation_condition(relation_value)
        action_logits = self.action_head(action_context)
        action_value = _condition_value(
            "junctionization_action",
            action_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )
        final_context = action_context + self.action_condition(action_value)
        business_plan_logits = None
        decoder_context = final_context
        if self.business_plan_head is not None:
            business_plan_logits = self.business_plan_head(final_context)
            if self.business_plan_condition is None:
                raise AssertionError("junction business plan condition is missing")
            decoder_context = final_context + self.business_plan_condition(
                business_plan_logits.softmax(dim=-1).detach()
            )

        surface_grid = _spatial_token_grid(
            self.surface_token_projection(geometry_tokens),
            batch.geometry_tokens,
            batch.geometry_token_mask,
            grid_size=32,
        )
        surface_grid = surface_grid + self.surface_context_projection(
            surface_context
        ).unsqueeze(-1).unsqueeze(-1)
        drivezone_grid = nn.functional.avg_pool2d(
            batch.drivezone_grid,
            kernel_size=SURFACE_GRID_SIZE // 32,
        )
        surface_grid = surface_grid + self.surface_drivezone_projection(
            drivezone_grid
        )
        surface_logits = self.surface_decoder(surface_grid).squeeze(1)
        if surface_logits.shape[-2:] != (SURFACE_GRID_SIZE, SURFACE_GRID_SIZE):
            raise AssertionError("junction surface decoder grid differs")
        surface_residual = self.surface_refinement(
            torch.cat((surface_logits.unsqueeze(1), batch.drivezone_grid), dim=1)
        ).squeeze(1)
        surface_pixel_logits = surface_logits + surface_residual
        if self.surface_high_resolution_refinement is not None:
            role_grid = _spatial_role_grid(
                batch.geometry_tokens,
                batch.geometry_token_mask,
                grid_size=SURFACE_GRID_SIZE,
            )
            surface_pixel_logits = surface_pixel_logits + (
                self.surface_high_resolution_refinement(
                    torch.cat(
                        (
                            surface_pixel_logits.unsqueeze(1),
                            batch.drivezone_grid,
                            role_grid,
                        ),
                        dim=1,
                    )
                ).squeeze(1)
            )
        surface_boundary_outputs: dict[str, torch.Tensor] = {}
        if self.surface_boundary_decoder is not None:
            boundary_maps = self.surface_boundary_decoder(
                torch.cat(
                    (surface_pixel_logits.unsqueeze(1), batch.drivezone_grid),
                    dim=1,
                )
            )
            surface_logits, surface_boundary_outputs = _structured_surface_logits(
                boundary_maps
            )
        else:
            surface_logits = surface_pixel_logits

        relation_geometry_objects = geometry_objects
        relation_decoder_context = decoder_context
        weak_evidence_outputs: Mapping[str, torch.Tensor] = {}
        if self.weak_evidence_encoder is not None:
            if self.weak_evidence_fusion is None:
                raise AssertionError("weak evidence fusion is missing")
            weak_evidence_outputs = self.weak_evidence_encoder(batch)
            weak_hidden = weak_evidence_outputs[
                "weak_evidence_object_hidden"
            ].detach()
            weak_probability = weak_evidence_outputs[
                "weak_evidence_logits"
            ].sigmoid().detach().unsqueeze(-1)
            evidence_delta = self.weak_evidence_fusion(
                torch.cat(
                    (geometry_objects, weak_hidden, weak_probability),
                    dim=-1,
                )
            ) * batch.geometry_object_mask.unsqueeze(-1).to(
                geometry_objects.dtype
            )
            relation_geometry_objects = geometry_objects + evidence_delta
            relation_decoder_context = decoder_context + (
                evidence_delta.sum(dim=1)
                / batch.geometry_object_mask.sum(dim=1).clamp_min(1).unsqueeze(-1)
            )

        break_hidden = self.break_decoder(
            relation_geometry_objects.unsqueeze(2)
            + relation_decoder_context.unsqueeze(1).unsqueeze(2)
            + self.break_slot_embeddings.unsqueeze(0).unsqueeze(0)
        )

        object_role_cardinality_logits = self.object_role_cardinality_head(
            relation_decoder_context
        ).reshape(
            final_context.shape[0],
            2,
            self.config.object_cardinality_count,
        )
        break_offset_m = 50.0 * torch.tanh(
            self.break_offset_head(break_hidden).squeeze(-1)
        )
        break_fractions = (
            batch.geometry_object_anchor_projection_fraction.unsqueeze(-1)
            + break_offset_m
            / batch.geometry_object_length_m.clamp_min(1.0).unsqueeze(-1)
        ).clamp(0.0, 1.0)
        action_object_logits = torch.stack(
            tuple(
                scorer(relation_geometry_objects, relation_decoder_context)
                for scorer in self.action_object_scores
            ),
            dim=1,
        )
        object_logits = self.object_score(
            relation_geometry_objects,
            relation_decoder_context,
        ) + torch.einsum("ba,bao->bo", action_value, action_object_logits)
        result = {
            "t07_step1_logits": step1_logits,
            "t07_step2_logits": step2_logits,
            "surface_mode_logits": surface_mode_logits,
            "surface_state_logits": surface_state_logits,
            "relation_state_logits": relation_logits,
            "junctionization_action_logits": action_logits,
            "final_state_logits": self.final_state_head(final_context),
            "surface_logits": surface_logits,
            "surface_pixel_logits": surface_pixel_logits,
            "surface_object_logits": self.surface_object_score(
                geometry_objects,
                surface_context,
            ),
            "surface_object_cardinality_logits": (
                self.surface_object_cardinality_head(surface_context)
            ),
            "virtual_surface_carrier_logits": self.virtual_surface_carrier_score(
                geometry_objects,
                surface_context,
            ),
            "virtual_surface_carrier_cardinality_logits": (
                self.virtual_surface_carrier_cardinality_head(surface_context)
            ),
            "action_object_logits": action_object_logits,
            "object_logits": object_logits,
            "object_main_logits": self.object_main_score(
                relation_geometry_objects,
                relation_decoder_context,
            ),
            "object_cardinality_logits": self.object_cardinality_head(
                relation_decoder_context
            ),
            "object_role_cardinality_logits": object_role_cardinality_logits,
            "candidate_logits": self.candidate_score(candidate_hidden, decoder_context),
            "member_logits": self.member_score(member_hidden, decoder_context),
            "break_presence_logits": self.break_presence_head(break_hidden).squeeze(-1),
            "break_fractions": break_fractions,
            "break_main_logits": self.break_main_head(break_hidden).squeeze(-1),
        }
        result.update(
            {
                key: value
                for key, value in weak_evidence_outputs.items()
                if key == "weak_evidence_logits"
            }
        )
        if self.config.virtual_surface_geometric_coverage_training:
            result["virtual_surface_geometric_coverage_logits"] = result[
                "virtual_surface_carrier_logits"
            ]
        if self.structured_virtual_surface_carrier_decoder is not None:
            carrier_mask = virtual_surface_carrier_candidate_mask(batch)
            structured_carrier = (
                self.structured_virtual_surface_carrier_decoder.greedy_decode(
                    geometry_objects,
                    carrier_mask,
                    surface_context,
                )
            )
            result["structured_virtual_surface_carrier_prediction"] = (
                structured_carrier.selected_members
            )
            result["structured_virtual_surface_carrier_stopped"] = (
                structured_carrier.stopped
            )
            result[
                "structured_virtual_surface_carrier_sequence_log_probability"
            ] = structured_carrier.sequence_log_probability
            carrier_teacher_values = (
                teacher_virtual_surface_carrier_sets,
                teacher_virtual_surface_carrier_set_mask,
                teacher_virtual_surface_carrier_task_mask,
            )
            if any(value is not None for value in carrier_teacher_values):
                if any(value is None for value in carrier_teacher_values):
                    raise ValueError(
                        "structured virtual carrier teacher tensors are incomplete"
                    )
                result["structured_virtual_surface_carrier_loss_by_row"] = (
                    self.structured_virtual_surface_carrier_decoder.teacher_forced_loss_by_row(
                        geometry_objects,
                        carrier_mask,
                        surface_context,
                        teacher_virtual_surface_carrier_sets,
                        teacher_virtual_surface_carrier_set_mask,
                        teacher_virtual_surface_carrier_task_mask,
                    )
                )
        if self.structured_relation_decoder is not None:
            relation_mask, minimum, maximum, feasible = (
                relation_candidate_constraints(
                    batch,
                    action_value.argmax(dim=-1),
                )
            )
            structured_relation = self.structured_relation_decoder.greedy_decode(
                relation_geometry_objects,
                relation_mask,
                relation_decoder_context,
                minimum_members=minimum,
                maximum_members=maximum,
                relation_index=(
                    batch.geometry_relation_index
                    if self.config.structured_relation_graph_conditioning
                    else None
                ),
                relation_features=(
                    batch.geometry_relation_features
                    if self.config.structured_relation_graph_conditioning
                    else None
                ),
                relation_mask=(
                    batch.geometry_relation_mask
                    if self.config.structured_relation_graph_conditioning
                    else None
                ),
            )
            result["structured_relation_prediction"] = (
                structured_relation.selected_members
            )
            result["structured_relation_stopped"] = structured_relation.stopped
            result["structured_relation_feasible"] = feasible
            result["structured_relation_sequence_log_probability"] = (
                structured_relation.sequence_log_probability
            )
            relation_teacher_values = (
                teacher_relation_sets,
                teacher_relation_set_mask,
                teacher_relation_task_mask,
            )
            if any(value is not None for value in relation_teacher_values):
                if any(value is None for value in relation_teacher_values):
                    raise ValueError(
                        "junction structured relation teacher tensors are incomplete"
                    )
                result["structured_relation_loss_by_row"] = (
                    self.structured_relation_decoder.teacher_forced_loss_by_row(
                        relation_geometry_objects,
                        batch.selectable_object_mask,
                        relation_decoder_context,
                        teacher_relation_sets,
                        teacher_relation_set_mask,
                        teacher_relation_task_mask,
                        relation_index=(
                            batch.geometry_relation_index
                            if self.config.structured_relation_graph_conditioning
                            else None
                        ),
                        relation_features=(
                            batch.geometry_relation_features
                            if self.config.structured_relation_graph_conditioning
                            else None
                        ),
                        relation_mask=(
                            batch.geometry_relation_mask
                            if self.config.structured_relation_graph_conditioning
                            else None
                        ),
                    )
                )
        if self.structured_member_decoder is not None:
            structured = self.structured_member_decoder.greedy_decode(
                member_hidden,
                batch.member_mask,
                decoder_context,
            )
            result["structured_member_prediction"] = structured.selected_members
            result["structured_member_stopped"] = structured.stopped
            result["structured_member_sequence_log_probability"] = (
                structured.sequence_log_probability
            )
            teacher_values = (
                teacher_member_sets,
                teacher_member_set_mask,
                teacher_member_task_mask,
            )
            if any(value is not None for value in teacher_values):
                if any(value is None for value in teacher_values):
                    raise ValueError(
                        "junction structured member teacher tensors are incomplete"
                    )
                result["structured_member_loss_by_row"] = (
                    self.structured_member_decoder.teacher_forced_loss_by_row(
                        member_hidden,
                        batch.member_mask,
                        decoder_context,
                        teacher_member_sets,
                        teacher_member_set_mask,
                        teacher_member_task_mask,
                    )
                )
        if self.one_way_object_decoder is not None:
            if business_plan_logits is None:
                raise AssertionError("one-way object branch has no business plan")
            result.update(
                self.one_way_object_decoder(
                    batch,
                    business_plan_logits=business_plan_logits,
                    teacher_member_sets=teacher_member_sets,
                    teacher_member_set_mask=teacher_member_set_mask,
                    teacher_member_task_mask=teacher_member_task_mask,
                )
            )
        if business_plan_logits is not None:
            result["business_plan_logits"] = business_plan_logits
        result.update(surface_boundary_outputs)
        return result

    def _encode_member_graph(
        self,
        member_hidden: torch.Tensor,
        batch: JunctionJointBatch,
    ) -> torch.Tensor:
        if not self.config.member_graph_layers:
            return member_hidden
        if (
            self.member_arm_stem is None
            or self.member_arm_match_fusion is None
            or self.member_relation_stem is None
            or self.member_incidence_stem is None
        ):
            raise AssertionError("junction member graph modules are missing")
        swsd_arms = self.member_arm_stem(batch.swsd_arm_features)
        member_arms = self.member_arm_stem(batch.member_arm_features)
        scores = torch.einsum("bmrh,bsh->bmrs", member_arms, swsd_arms) / (
            self.config.hidden_dim**0.5
        )
        arm_pair_mask = (
            batch.member_arm_mask.unsqueeze(-1)
            & batch.swsd_arm_mask.unsqueeze(1).unsqueeze(1)
        )
        weights = _masked_softmax(scores, arm_pair_mask, dim=-1)
        matched_swsd = torch.einsum("bmrs,bsh->bmrh", weights, swsd_arms)
        arm_context = self.member_arm_match_fusion(
            torch.cat(
                (
                    member_arms,
                    matched_swsd,
                    (member_arms - matched_swsd).abs(),
                    member_arms * matched_swsd,
                ),
                dim=-1,
            )
        )
        arm_mask = batch.member_arm_mask.unsqueeze(-1)
        arm_context = (
            arm_context * arm_mask.to(arm_context.dtype)
        ).sum(dim=2) / arm_mask.sum(dim=2).clamp_min(1).to(arm_context.dtype)
        hidden = member_hidden + arm_context
        relation_hidden = self.member_relation_stem(
            batch.member_relation_features
        )
        incidence_hidden = self.member_incidence_stem(
            batch.member_incidence_features
        )
        relation_mask = batch.member_relation_mask
        incidence_mask = batch.member_incidence_mask
        structural_hidden = (
            relation_hidden * relation_mask.unsqueeze(-1).to(relation_hidden.dtype)
            + incidence_hidden
            * incidence_mask.unsqueeze(-1).to(incidence_hidden.dtype)
        )
        structural_mask = relation_mask | incidence_mask
        for block in self.member_graph_blocks:
            hidden = block(
                hidden,
                structural_hidden,
                structural_mask,
                batch.member_mask,
            )
        return hidden * batch.member_mask.unsqueeze(-1).to(hidden.dtype)

    def _encode_geometry_graph(
        self,
        geometry_objects: torch.Tensor,
        batch: JunctionJointBatch,
    ) -> torch.Tensor:
        if not self.config.geometry_graph_layers:
            return geometry_objects
        if self.geometry_relation_stem is None:
            raise AssertionError("junction geometry relation stem is missing")
        relation_hidden = self.geometry_relation_stem(
            batch.geometry_relation_features
        )
        hidden = geometry_objects
        for block in self.geometry_graph_blocks:
            hidden = block(
                hidden,
                batch.geometry_relation_index,
                relation_hidden,
                batch.geometry_relation_mask,
                batch.geometry_object_mask,
            )
        return hidden

    def _fuse_geometry_members(
        self,
        geometry_objects: torch.Tensor,
        member_hidden: torch.Tensor,
        batch: JunctionJointBatch,
    ) -> torch.Tensor:
        if not self.config.member_graph_layers:
            return geometry_objects
        if self.geometry_member_fusion is None:
            raise AssertionError("junction geometry/member fusion is missing")
        safe_index = batch.geometry_object_member_index.clamp_min(0)
        gathered = torch.gather(
            member_hidden,
            1,
            safe_index.unsqueeze(-1).expand(-1, -1, member_hidden.shape[-1]),
        )
        fused = self.geometry_member_fusion(
            torch.cat((geometry_objects, gathered), dim=-1)
        )
        valid = (
            (batch.geometry_object_member_index >= 0)
            & batch.geometry_object_mask
        ).unsqueeze(-1)
        return torch.where(valid, fused, geometry_objects)


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def _structured_surface_logits(
    boundary_maps: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    if boundary_maps.ndim != 4 or boundary_maps.shape[1] != 6:
        raise ValueError("junction surface boundary maps must be Bx6xHxW")
    row_left_logits = boundary_maps[:, 0]
    row_right_logits = boundary_maps[:, 1]
    column_top_logits = boundary_maps[:, 2]
    column_bottom_logits = boundary_maps[:, 3]
    row_presence_logits = boundary_maps[:, 4].mean(dim=-1)
    column_presence_logits = boundary_maps[:, 5].mean(dim=-2)

    row_left_cdf = row_left_logits.softmax(dim=-1).cumsum(dim=-1)
    row_right_survival = torch.flip(
        torch.flip(row_right_logits, dims=(-1,)).softmax(dim=-1).cumsum(dim=-1),
        dims=(-1,),
    )
    row_probability = (
        row_left_cdf
        * row_right_survival
        * row_presence_logits.sigmoid().unsqueeze(-1)
    )
    column_top_cdf = column_top_logits.softmax(dim=-2).cumsum(dim=-2)
    column_bottom_survival = torch.flip(
        torch.flip(column_bottom_logits, dims=(-2,)).softmax(dim=-2).cumsum(dim=-2),
        dims=(-2,),
    )
    column_probability = (
        column_top_cdf
        * column_bottom_survival
        * column_presence_logits.sigmoid().unsqueeze(-2)
    )
    probability = (row_probability * column_probability).clamp(1e-5, 1.0 - 1e-5)
    outputs = {
        "surface_row_left_logits": row_left_logits,
        "surface_row_right_logits": row_right_logits,
        "surface_column_top_logits": column_top_logits,
        "surface_column_bottom_logits": column_bottom_logits,
        "surface_row_presence_logits": row_presence_logits,
        "surface_column_presence_logits": column_presence_logits,
    }
    return torch.logit(probability), outputs


def _condition_value(
    task: str,
    logits: torch.Tensor,
    teacher_labels: Mapping[str, torch.Tensor] | None,
    teacher_masks: Mapping[str, torch.Tensor] | None,
    ratio: float,
) -> torch.Tensor:
    predicted = logits.softmax(dim=-1).detach()
    if ratio <= 0.0 or teacher_labels is None or teacher_masks is None:
        return predicted
    labels = teacher_labels[task]
    masks = teacher_masks[task] & labels.ge(0)
    teacher = nn.functional.one_hot(
        labels.clamp_min(0),
        num_classes=logits.shape[-1],
    ).to(logits.dtype)
    blended = teacher * ratio + predicted * (1.0 - ratio)
    return torch.where(masks.unsqueeze(-1), blended, predicted).detach()


def _pool_tokens_by_object(
    token_hidden: torch.Tensor,
    token_mask: torch.Tensor,
    token_object_index: torch.Tensor,
    object_count: int,
    fusion: nn.Module,
) -> torch.Tensor:
    if token_hidden.shape[:2] != token_mask.shape:
        raise ValueError("junction geometry token shape differs")
    batch, _, hidden = token_hidden.shape
    indices = token_object_index.clamp_min(0).unsqueeze(-1).expand(-1, -1, hidden)
    valid = token_mask & token_object_index.ge(0)
    values = token_hidden * valid.unsqueeze(-1).to(token_hidden.dtype)
    sums = token_hidden.new_zeros(batch, object_count, hidden)
    sums.scatter_add_(1, indices, values)
    counts = token_hidden.new_zeros(batch, object_count, 1)
    counts.scatter_add_(
        1,
        token_object_index.clamp_min(0).unsqueeze(-1),
        valid.unsqueeze(-1).to(token_hidden.dtype),
    )
    means = sums / counts.clamp_min(1.0)
    negative = torch.finfo(token_hidden.dtype).min
    maximum_source = token_hidden.masked_fill(~valid.unsqueeze(-1), negative)
    maxima = token_hidden.new_full((batch, object_count, hidden), negative)
    maxima.scatter_reduce_(1, indices, maximum_source, reduce="amax", include_self=True)
    maxima = torch.where(counts.gt(0), maxima, torch.zeros_like(maxima))
    return fusion(torch.cat((means, maxima), dim=-1))


def _spatial_token_grid(
    token_hidden: torch.Tensor,
    raw_tokens: torch.Tensor,
    token_mask: torch.Tensor,
    *,
    grid_size: int,
) -> torch.Tensor:
    if token_hidden.shape[:2] != raw_tokens.shape[:2] or token_mask.shape != raw_tokens.shape[:2]:
        raise ValueError("junction spatial token grid shape differs")
    normalized = raw_tokens[..., 7:9] * (
        GEOMETRY_RADIUS_M / SURFACE_GRID_HALF_EXTENT_M
    )
    inside = normalized.abs().le(1.0).all(dim=-1) & token_mask
    cells = (((normalized + 1.0) * 0.5) * grid_size).floor().long()
    cells = cells.clamp(0, grid_size - 1)
    flat = cells[..., 1] * grid_size + cells[..., 0]
    batch, _, channels = token_hidden.shape
    index = flat.unsqueeze(-1).expand(-1, -1, channels)
    values = token_hidden * inside.unsqueeze(-1).to(token_hidden.dtype)
    grid = token_hidden.new_zeros(batch, grid_size * grid_size, channels)
    grid.scatter_add_(1, index, values)
    counts = token_hidden.new_zeros(batch, grid_size * grid_size, 1)
    counts.scatter_add_(
        1,
        flat.unsqueeze(-1),
        inside.unsqueeze(-1).to(token_hidden.dtype),
    )
    grid = grid / counts.clamp_min(1.0)
    return grid.transpose(1, 2).reshape(batch, channels, grid_size, grid_size)


def _spatial_role_grid(
    raw_tokens: torch.Tensor,
    token_mask: torch.Tensor,
    *,
    grid_size: int,
) -> torch.Tensor:
    if token_mask.shape != raw_tokens.shape[:2]:
        raise ValueError("junction spatial role grid shape differs")
    normalized = raw_tokens[..., 7:9] * (
        GEOMETRY_RADIUS_M / SURFACE_GRID_HALF_EXTENT_M
    )
    inside = normalized.abs().le(1.0).all(dim=-1) & token_mask
    cells = (((normalized + 1.0) * 0.5) * grid_size).floor().long()
    cells = cells.clamp(0, grid_size - 1)
    flat = cells[..., 1] * grid_size + cells[..., 0]
    roles = raw_tokens[..., : len(GEOMETRY_ROLE_INDEX)]
    values = roles * inside.unsqueeze(-1).to(roles.dtype)
    batch, _, channels = values.shape
    grid = values.new_zeros(batch, grid_size * grid_size, channels)
    grid.scatter_add_(
        1,
        flat.unsqueeze(-1).expand(-1, -1, channels),
        values,
    )
    return grid.clamp_max(1.0).transpose(1, 2).reshape(
        batch,
        channels,
        grid_size,
        grid_size,
    )


def _pair_score(hidden_values: int) -> nn.Module:
    return _PairScore(hidden_values)


class _MemberGraphBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.neighbor = nn.Linear(hidden_dim, hidden_dim)
        self.message_norm = nn.LayerNorm(hidden_dim)
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
        )
        self.output_norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        members: torch.Tensor,
        relations: torch.Tensor,
        relation_mask: torch.Tensor,
        member_mask: torch.Tensor,
    ) -> torch.Tensor:
        if relations.shape[:3] != relation_mask.shape:
            raise ValueError("junction member relation tensor/mask differs")
        if relations.shape[:2] != members.shape[:2]:
            raise ValueError("junction member relation/member scope differs")
        neighbor = self.neighbor(members).unsqueeze(1)
        messages = self.message_norm(torch.nn.functional.gelu(relations + neighbor))
        mask = relation_mask.unsqueeze(-1)
        degree = mask.sum(dim=2).clamp_min(1).to(messages.dtype)
        context = (messages * mask.to(messages.dtype)).sum(dim=2) / degree
        updated = self.output_norm(
            members + self.update(torch.cat((members, context), dim=-1))
        )
        return updated * member_mask.unsqueeze(-1).to(updated.dtype)


class _SparseObjectGraphBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
        )
        self.output_norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        objects: torch.Tensor,
        relation_index: torch.Tensor,
        relation_features: torch.Tensor,
        relation_mask: torch.Tensor,
        object_mask: torch.Tensor,
    ) -> torch.Tensor:
        if relation_index.shape[:2] != relation_mask.shape:
            raise ValueError("junction geometry relation index/mask differs")
        if relation_index.shape[-1] != 2:
            raise ValueError("junction geometry relation index dimension differs")
        if relation_features.shape[:2] != relation_mask.shape:
            raise ValueError("junction geometry relation features/mask differs")
        if objects.shape[:2] != object_mask.shape:
            raise ValueError("junction geometry object tensor/mask differs")

        object_count = objects.shape[1]
        safe_index = relation_index.clamp(0, object_count - 1)
        source_index = safe_index[..., 0]
        target_index = safe_index[..., 1]
        gather_index = source_index.unsqueeze(-1).expand(-1, -1, objects.shape[-1])
        sources = torch.gather(objects, 1, gather_index)
        messages = self.message(torch.cat((sources, relation_features), dim=-1))
        valid = (
            relation_mask
            & torch.gather(object_mask, 1, source_index)
            & torch.gather(object_mask, 1, target_index)
        )
        messages = messages * valid.unsqueeze(-1).to(messages.dtype)

        target_gather = target_index.unsqueeze(-1).expand_as(messages)
        aggregate = torch.zeros_like(objects)
        aggregate.scatter_add_(1, target_gather, messages)
        degree = objects.new_zeros(objects.shape[0], object_count, 1)
        degree.scatter_add_(
            1,
            target_index.unsqueeze(-1),
            valid.unsqueeze(-1).to(objects.dtype),
        )
        context = aggregate / degree.clamp_min(1.0)
        updated = self.output_norm(
            objects + self.update(torch.cat((objects, context), dim=-1))
        )
        has_message = degree.gt(0) & object_mask.unsqueeze(-1)
        result = torch.where(has_message, updated, objects)
        return result * object_mask.unsqueeze(-1).to(result.dtype)


class _PairScore(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.score = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, values: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        expanded = context.unsqueeze(1).expand(-1, values.shape[1], -1)
        return self.score(torch.cat((values, expanded), dim=-1)).squeeze(-1)


def _stem(input_dim: int, hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
    )


def _head(input_dim: int, output_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.LayerNorm(input_dim),
        nn.Dropout(dropout),
        nn.Linear(input_dim, input_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(input_dim, output_dim),
    )


def _residual_block(
    hidden_dim: int,
    feedforward_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.LayerNorm(hidden_dim),
        nn.Linear(hidden_dim, feedforward_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(feedforward_dim, hidden_dim),
        nn.Dropout(dropout),
    )


def _set_encoder(config: JunctionJointConfig, layers: int) -> nn.TransformerEncoder:
    layer = nn.TransformerEncoderLayer(
        d_model=config.hidden_dim,
        nhead=config.num_heads,
        dim_feedforward=config.feedforward_dim,
        dropout=config.dropout,
        activation="gelu",
        batch_first=True,
        norm_first=True,
    )
    return nn.TransformerEncoder(
        layer,
        num_layers=layers,
        enable_nested_tensor=False,
    )


def _encode_set(
    values: torch.Tensor,
    mask: torch.Tensor,
    encoder: nn.TransformerEncoder,
) -> torch.Tensor:
    if values.shape[:2] != mask.shape or mask.dtype is not torch.bool:
        raise ValueError("junction set tensor shape or mask differs")
    safe_mask = mask.clone()
    empty = ~safe_mask.any(dim=1)
    if bool(empty.any()):
        safe_mask[empty, 0] = True
    encoded = encoder(values, src_key_padding_mask=~safe_mask)
    return encoded * mask.unsqueeze(-1).to(encoded.dtype)


def _attention_pool(
    values: torch.Tensor,
    mask: torch.Tensor,
    scorer: nn.Linear,
) -> torch.Tensor:
    logits = scorer(values).squeeze(-1)
    minimum = torch.finfo(logits.dtype).min
    safe_logits = logits.masked_fill(~mask, minimum)
    weights = safe_logits.softmax(dim=-1)
    weights = torch.where(mask, weights, torch.zeros_like(weights))
    denominator = weights.sum(dim=-1, keepdim=True).clamp_min(1e-8)
    return (values * (weights / denominator).unsqueeze(-1)).sum(dim=1)


def _masked_softmax(
    values: torch.Tensor,
    mask: torch.Tensor,
    *,
    dim: int,
) -> torch.Tensor:
    minimum = torch.finfo(values.dtype).min
    masked = values.masked_fill(~mask, minimum)
    weights = masked.softmax(dim=dim)
    weights = torch.where(mask, weights, torch.zeros_like(weights))
    return weights / weights.sum(dim=dim, keepdim=True).clamp_min(1e-8)


__all__ = [
    "JunctionJointConfig",
    "JunctionJointNetwork",
    "parameter_count",
]
