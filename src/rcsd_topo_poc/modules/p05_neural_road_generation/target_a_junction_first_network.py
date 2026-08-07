from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    FEATURE_DIM,
    MEMBER_FEATURE_DIM,
    STAGE1_OBJECT_INDICES,
    TASK_CLASSES,
    JunctionFirstBatch,
)


@dataclass(frozen=True)
class JunctionFirstConfig:
    hidden_dim: int = 384
    num_heads: int = 8
    feedforward_dim: int = 1_536
    candidate_layers: int = 3
    member_layers: int = 2
    trunk_layers: int = 2
    dropout: float = 0.10
    cardinality_count: int = 16
    min_parameter_count: int = 10_000_000
    max_parameter_count: int = 20_000_000

    def validate(self) -> None:
        if self.hidden_dim < 64 or self.hidden_dim % self.num_heads:
            raise ValueError("junction hidden dimension must divide by head count")
        if self.feedforward_dim < self.hidden_dim:
            raise ValueError("junction feedforward dimension is too small")
        if min(self.candidate_layers, self.member_layers, self.trunk_layers) < 1:
            raise ValueError("junction encoder layer counts must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("junction dropout is invalid")
        if self.cardinality_count < 13:
            raise ValueError("junction cardinality decoder cannot express current Gold")


class JunctionFirstNetwork(nn.Module):
    """T07-to-T05 hierarchy with isolated T07 decisions and a full object-set decoder."""

    def __init__(self, config: JunctionFirstConfig = JunctionFirstConfig()) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.hidden_dim

        # Step1 is a physically separate DriveZone-only view.
        self.step1_encoder = _stem(len(STAGE1_OBJECT_INDICES), hidden, config.dropout)
        self.step1_head = _head(hidden, len(TASK_CLASSES["t07_step1"]), config.dropout)

        # Step2 is isolated from downstream heads so later losses cannot rewrite it.
        self.step2_encoder = _stem(FEATURE_DIM, hidden, config.dropout)
        self.step1_condition = nn.Linear(len(TASK_CLASSES["t07_step1"]), hidden)
        self.step2_head = _head(hidden, len(TASK_CLASSES["t07_step2"]), config.dropout)

        self.object_encoder = _stem(FEATURE_DIM, hidden, config.dropout)
        self.candidate_stem = _stem(FEATURE_DIM, hidden, config.dropout)
        self.member_stem = _stem(MEMBER_FEATURE_DIM, hidden, config.dropout)
        self.candidate_encoder = _set_encoder(config, config.candidate_layers)
        self.member_encoder = _set_encoder(config, config.member_layers)
        self.candidate_pool_score = nn.Linear(hidden, 1)
        self.member_pool_score = nn.Linear(hidden, 1)

        condition_dim = (
            len(TASK_CLASSES["t07_step1"])
            + len(TASK_CLASSES["t07_step2"])
        )
        self.context_fusion = nn.Sequential(
            nn.Linear(hidden * 3 + condition_dim, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
        )
        self.trunk = nn.ModuleList(
            _residual_block(hidden, config.feedforward_dim, config.dropout)
            for _ in range(config.trunk_layers)
        )
        self.route_head = _head(hidden, len(TASK_CLASSES["route"]), config.dropout)
        self.route_condition = nn.Linear(len(TASK_CLASSES["route"]), hidden)

        self.task_heads = nn.ModuleDict(
            {
                task: _head(hidden, len(TASK_CLASSES[task]), config.dropout)
                for task in (
                    "t07_relation",
                    "t03_surface",
                    "t03_association",
                    "t03_relation",
                    "t04_surface",
                    "t04_relation",
                    "t05_surface_source",
                    "t05_junctionization",
                    "t05_graph",
                    "t05_relation",
                    "anchor_status",
                )
            }
        )
        self.candidate_score = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Linear(hidden, 1),
        )
        self.member_score = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Linear(hidden, 1),
        )
        self.member_type_head = _head(hidden, 2, config.dropout)
        self.member_cardinality_head = _head(
            hidden,
            config.cardinality_count,
            config.dropout,
        )

        count = parameter_count(self)
        if not config.min_parameter_count <= count <= config.max_parameter_count:
            raise ValueError(
                "junction-first parameter count outside frozen range: "
                f"{count:,}"
            )

    def forward(
        self,
        batch: JunctionFirstBatch,
        *,
        teacher_labels: Mapping[str, torch.Tensor] | None = None,
        teacher_masks: Mapping[str, torch.Tensor] | None = None,
        teacher_forcing_ratio: float = 0.0,
    ) -> Mapping[str, torch.Tensor]:
        if not 0.0 <= teacher_forcing_ratio <= 1.0:
            raise ValueError("teacher forcing ratio must be within [0, 1]")
        step1_hidden = self.step1_encoder(batch.stage1_features)
        step1_logits = self.step1_head(step1_hidden)
        step1_value = _condition_value(
            "t07_step1",
            step1_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )

        step2_hidden = self.step2_encoder(batch.object_features)
        step2_hidden = step2_hidden + self.step1_condition(step1_value)
        step2_logits = self.step2_head(step2_hidden)
        step2_value = _condition_value(
            "t07_step2",
            step2_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )

        object_hidden = self.object_encoder(batch.object_features)
        candidate_hidden = _encode_set(
            self.candidate_stem(batch.candidate_features),
            batch.candidate_mask,
            self.candidate_encoder,
        )
        member_hidden = _encode_set(
            self.member_stem(batch.member_features),
            batch.member_mask,
            self.member_encoder,
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
                (object_hidden, candidate_pool, member_pool, step1_value, step2_value),
                dim=-1,
            )
        )
        for block in self.trunk:
            context = context + block(context)
        route_logits = self.route_head(context)
        route_value = _condition_value(
            "route",
            route_logits,
            teacher_labels,
            teacher_masks,
            teacher_forcing_ratio,
        )
        final_context = context + self.route_condition(route_value)

        outputs: dict[str, torch.Tensor] = {
            "t07_step1_logits": step1_logits,
            "t07_step2_logits": step2_logits,
            "route_logits": route_logits,
        }
        for task, head in self.task_heads.items():
            outputs[f"{task}_logits"] = head(final_context)
        expanded = final_context.unsqueeze(1)
        outputs["candidate_logits"] = self.candidate_score(
            torch.cat((candidate_hidden, expanded.expand_as(candidate_hidden)), dim=-1)
        ).squeeze(-1)
        outputs["member_logits"] = self.member_score(
            torch.cat((member_hidden, expanded.expand_as(member_hidden)), dim=-1)
        ).squeeze(-1)
        outputs["member_type_logits"] = self.member_type_head(final_context)
        outputs["member_cardinality_logits"] = self.member_cardinality_head(
            final_context
        )
        return outputs


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


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


def _set_encoder(config: JunctionFirstConfig, layers: int) -> nn.TransformerEncoder:
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


__all__ = [
    "JunctionFirstConfig",
    "JunctionFirstNetwork",
    "parameter_count",
]
