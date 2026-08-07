from __future__ import annotations

from typing import Any

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryRoadSetDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_role_set_network import (
    TargetAOrdinaryCountAwareSetDecoder,
)


SIDE_SOURCE_SWSD = 0
SIDE_SOURCE_RCSD = 1
SIDE_SOURCE_UNRESOLVED = 2
SIDE_SOURCE_COUNT = 3


class _MaskedSetEncoder(nn.Module):
    def __init__(
        self,
        *,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, output_dim),
            nn.GELU(),
            nn.LayerNorm(output_dim),
        )

    def forward(
        self,
        values: torch.Tensor,
        mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if values.ndim != 3 or values.shape[-1] != self.input_dim:
            raise ValueError("joint set encoder value shape differs")
        if mask.shape != values.shape[:2] or mask.dtype is not torch.bool:
            raise ValueError("joint set encoder mask shape or dtype differs")
        encoded = self.encoder(values)
        mask_values = mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * mask_values).sum(dim=1) / mask_values.sum(
            dim=1
        ).clamp_min(1.0)
        maximum = encoded.masked_fill(
            ~mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).min,
        ).amax(dim=1)
        maximum = torch.where(
            mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        return encoded, torch.cat((mean, maximum), dim=-1)


class TargetAAdvanceRightJointAccessDecoder(nn.Module):
    """Jointly lock ordinary access evidence before decoding AdvanceRight."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        road_feature_dim: int = 40,
        access_feature_dim: int = 64,
        candidate_feature_dim: int = 50,
        hidden_dim: int = 128,
        set_dim: int = 64,
        side_dim: int = 192,
        context_dim: int = 256,
        plan_type_count: int = 5,
        cardinality_count: int = 10,
        road_cardinality_count: int = 65,
        ordinary_decoder_kind: str = "BASE_SET",
        dropout: float = 0.1,
        stop_gradient_between_stages: bool = True,
    ) -> None:
        super().__init__()
        self.object_feature_dim = object_feature_dim
        self.road_feature_dim = road_feature_dim
        self.access_feature_dim = access_feature_dim
        self.candidate_feature_dim = candidate_feature_dim
        self.plan_type_count = plan_type_count
        self.cardinality_count = cardinality_count
        self.road_cardinality_count = road_cardinality_count
        if ordinary_decoder_kind not in {"BASE_SET", "COUNT_AWARE_SET"}:
            raise ValueError("joint ordinary decoder kind differs")
        self.ordinary_decoder_kind = ordinary_decoder_kind
        self.stop_gradient_between_stages = stop_gradient_between_stages
        self.object_encoder = nn.Sequential(
            nn.Linear(object_feature_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        ordinary_model_class = (
            TargetAOrdinaryCountAwareSetDecoder
            if ordinary_decoder_kind == "COUNT_AWARE_SET"
            else TargetAOrdinaryRoadSetDecoder
        )
        self.ordinary_road_decoder = ordinary_model_class(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=road_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=192,
            cardinality_count=road_cardinality_count,
            dropout=dropout,
        )
        self.road_encoder = _MaskedSetEncoder(
            input_dim=road_feature_dim,
            hidden_dim=hidden_dim,
            output_dim=set_dim,
            dropout=dropout,
        )
        self.access_encoder = _MaskedSetEncoder(
            input_dim=access_feature_dim,
            hidden_dim=hidden_dim,
            output_dim=set_dim,
            dropout=dropout,
        )
        self.candidate_encoder = _MaskedSetEncoder(
            input_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            output_dim=hidden_dim,
            dropout=dropout,
        )
        self.side_encoder = nn.Sequential(
            nn.Linear(hidden_dim + 4 * set_dim, side_dim * 2),
            nn.GELU(),
            nn.LayerNorm(side_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(side_dim * 2, side_dim),
            nn.GELU(),
            nn.LayerNorm(side_dim),
        )
        self.side_source_head = nn.Sequential(
            nn.Linear(side_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, SIDE_SOURCE_COUNT),
        )
        self.access_head = nn.Sequential(
            nn.Linear(set_dim + side_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.source_embedding = nn.Embedding(SIDE_SOURCE_COUNT, set_dim)
        self.locked_side_fusion = nn.Sequential(
            nn.Linear(side_dim + 3 * set_dim, side_dim),
            nn.GELU(),
            nn.LayerNorm(side_dim),
        )
        self.graph_context = nn.Sequential(
            nn.Linear(2 * side_dim + 2 * hidden_dim, context_dim * 2),
            nn.GELU(),
            nn.LayerNorm(context_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(context_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
        )
        self.candidate_head = nn.Sequential(
            nn.Linear(hidden_dim + context_dim + candidate_feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.plan_type_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, plan_type_count),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, cardinality_count),
        )
        self.safety_head = nn.Sequential(
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        *,
        candidate_values: torch.Tensor,
        candidate_mask: torch.Tensor,
        source_object_values: torch.Tensor,
        source_road_values: torch.Tensor,
        source_road_mask: torch.Tensor,
        source_access_values: torch.Tensor,
        source_access_mask: torch.Tensor,
        target_object_values: torch.Tensor,
        target_road_values: torch.Tensor,
        target_road_mask: torch.Tensor,
        target_access_values: torch.Tensor,
        target_access_mask: torch.Tensor,
        teacher_source_source: torch.Tensor | None = None,
        teacher_source_road_mask: torch.Tensor | None = None,
        teacher_source_access_mask: torch.Tensor | None = None,
        teacher_target_source: torch.Tensor | None = None,
        teacher_target_road_mask: torch.Tensor | None = None,
        teacher_target_access_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        source = self._encode_side(
            object_values=source_object_values,
            road_values=source_road_values,
            road_mask=source_road_mask,
            access_values=source_access_values,
            access_mask=source_access_mask,
            teacher_source=teacher_source_source,
            teacher_road_mask=teacher_source_road_mask,
            teacher_access_mask=teacher_source_access_mask,
        )
        target = self._encode_side(
            object_values=target_object_values,
            road_values=target_road_values,
            road_mask=target_road_mask,
            access_values=target_access_values,
            access_mask=target_access_mask,
            teacher_source=teacher_target_source,
            teacher_road_mask=teacher_target_road_mask,
            teacher_access_mask=teacher_target_access_mask,
        )
        candidate_encoded, candidate_pool = self.candidate_encoder(
            candidate_values,
            candidate_mask,
        )
        context = self.graph_context(
            torch.cat(
                (
                    source["locked_context"],
                    target["locked_context"],
                    candidate_pool,
                ),
                dim=-1,
            )
        )
        expanded = context.unsqueeze(1).expand(
            -1,
            candidate_values.shape[1],
            -1,
        )
        candidate_logits = self.candidate_head(
            torch.cat((candidate_encoded, expanded, candidate_values), dim=-1)
        ).squeeze(-1)
        candidate_logits = candidate_logits.masked_fill(
            ~candidate_mask,
            float("-inf"),
        )
        outputs = {
            "candidate_logits": candidate_logits,
            "plan_type_logits": self.plan_type_head(context),
            "cardinality_logits": self.cardinality_head(context),
            "safety_logits": self.safety_head(context).squeeze(-1),
            "source_side_source_logits": source["source_logits"],
            "source_side_road_logits": source["road_logits"],
            "source_side_road_cardinality_logits": source[
                "road_cardinality_logits"
            ],
            "source_side_access_logits": source["access_logits"],
            "target_side_source_logits": target["source_logits"],
            "target_side_road_logits": target["road_logits"],
            "target_side_road_cardinality_logits": target[
                "road_cardinality_logits"
            ],
            "target_side_access_logits": target["access_logits"],
            "source_locked_context": source["locked_context"],
            "target_locked_context": target["locked_context"],
        }
        for side_name, side in (("source", source), ("target", target)):
            if "road_cardinality_ordinal_logits" in side:
                outputs[
                    f"{side_name}_side_road_cardinality_ordinal_logits"
                ] = side["road_cardinality_ordinal_logits"]
            if "soft_member_count" in side:
                outputs[f"{side_name}_side_soft_member_count"] = side[
                    "soft_member_count"
                ]
        return outputs

    def load_ordinary_road_state_dict(self, state_dict) -> None:
        """Load the shared ordinary decoder from a base or richer checkpoint."""
        current = self.ordinary_road_decoder.state_dict()
        compatible = {
            key: value
            for key, value in state_dict.items()
            if key in current and value.shape == current[key].shape
        }
        missing = sorted(set(current) - set(compatible))
        if missing:
            raise ValueError(
                "pretrained ordinary decoder misses compatible parameters: "
                + ", ".join(missing)
            )
        self.ordinary_road_decoder.load_state_dict(compatible)

    def load_ordinary_encoder_state_dict(self, state_dict) -> None:
        """Overlay only role-trained object/Road encoders onto the base decoder."""
        prefixes = ("object_encoder.", "candidate_encoder.")
        current = self.ordinary_road_decoder.state_dict()
        expected = {
            key for key in current if key.startswith(prefixes)
        }
        compatible = {
            key: value
            for key, value in state_dict.items()
            if key in expected and value.shape == current[key].shape
        }
        missing = sorted(expected - set(compatible))
        if missing:
            raise ValueError(
                "pretrained ordinary encoder misses compatible parameters: "
                + ", ".join(missing)
            )
        current.update(compatible)
        self.ordinary_road_decoder.load_state_dict(current)

    def _encode_side(
        self,
        *,
        object_values: torch.Tensor,
        road_values: torch.Tensor,
        road_mask: torch.Tensor,
        access_values: torch.Tensor,
        access_mask: torch.Tensor,
        teacher_source: torch.Tensor | None,
        teacher_road_mask: torch.Tensor | None,
        teacher_access_mask: torch.Tensor | None,
    ) -> dict[str, torch.Tensor]:
        if (
            object_values.ndim != 2
            or object_values.shape[-1] != self.object_feature_dim
        ):
            raise ValueError("joint side object feature shape differs")
        ordinary = self.ordinary_road_decoder(
            object_features=object_values,
            candidate_features=road_values,
            candidate_mask=road_mask,
        )
        object_context = (
            self.object_encoder(object_values) + ordinary["graph_context"]
        )
        road_encoded, road_pool = self.road_encoder(road_values, road_mask)
        access_encoded, access_pool = self.access_encoder(
            access_values,
            access_mask,
        )
        side_context = self.side_encoder(
            torch.cat((object_context, road_pool, access_pool), dim=-1)
        )
        source_logits = self.side_source_head(side_context)
        road_logits = ordinary["member_logits"]
        road_cardinality_logits = ordinary["cardinality_logits"]
        access_expanded = side_context.unsqueeze(1).expand(
            -1,
            access_values.shape[1],
            -1,
        )
        access_logits = self.access_head(
            torch.cat((access_encoded, access_expanded), dim=-1)
        ).squeeze(-1)
        access_logits = access_logits.masked_fill(
            ~access_mask,
            float("-inf"),
        )
        source_context = self._locked_source_context(
            source_logits,
            teacher_source,
        )
        road_context = self._locked_road_context(
            road_encoded,
            road_logits,
            road_mask,
            teacher_road_mask,
        )
        access_context = self._locked_access_context(
            access_encoded,
            access_logits,
            access_mask,
            teacher_access_mask,
        )
        locked = self.locked_side_fusion(
            torch.cat(
                (
                    side_context,
                    source_context,
                    road_context,
                    access_context,
                ),
                dim=-1,
            )
        )
        if self.stop_gradient_between_stages:
            locked = locked.detach()
        outputs = {
            "source_logits": source_logits,
            "road_logits": road_logits,
            "road_cardinality_logits": road_cardinality_logits,
            "access_logits": access_logits,
            "locked_context": locked,
        }
        if "cardinality_ordinal_logits" in ordinary:
            outputs["road_cardinality_ordinal_logits"] = ordinary[
                "cardinality_ordinal_logits"
            ]
        if "soft_member_count" in ordinary:
            outputs["soft_member_count"] = ordinary["soft_member_count"]
        return outputs

    def _locked_road_context(
        self,
        encoded: torch.Tensor,
        logits: torch.Tensor,
        mask: torch.Tensor,
        teacher_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        if teacher_mask is not None:
            if teacher_mask.shape != mask.shape:
                raise ValueError("joint teacher Road mask shape differs")
            weights = teacher_mask.to(encoded.dtype)
        else:
            weights = torch.sigmoid(logits) * mask.to(logits.dtype)
            if self.stop_gradient_between_stages:
                weights = weights.detach()
        weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1.0)
        return (encoded * weights.unsqueeze(-1)).sum(dim=1)

    def _locked_source_context(
        self,
        logits: torch.Tensor,
        teacher_source: torch.Tensor | None,
    ) -> torch.Tensor:
        if teacher_source is None:
            weights = torch.softmax(logits, dim=-1)
            if self.stop_gradient_between_stages:
                weights = weights.detach()
        else:
            if teacher_source.shape != logits.shape[:1]:
                raise ValueError("joint teacher source shape differs")
            weights = nn.functional.one_hot(
                teacher_source.clamp(0, SIDE_SOURCE_COUNT - 1),
                num_classes=SIDE_SOURCE_COUNT,
            ).to(logits.dtype)
        return weights @ self.source_embedding.weight

    def _locked_access_context(
        self,
        encoded: torch.Tensor,
        logits: torch.Tensor,
        mask: torch.Tensor,
        teacher_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        if teacher_mask is not None:
            if teacher_mask.shape != mask.shape:
                raise ValueError("joint teacher access mask shape differs")
            weights = teacher_mask.to(encoded.dtype)
            weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1.0)
        else:
            safe_logits = logits.masked_fill(
                ~mask,
                torch.finfo(logits.dtype).min,
            )
            weights = torch.softmax(safe_logits, dim=-1)
            weights = weights * mask.to(weights.dtype)
            weights = weights / weights.sum(
                dim=-1,
                keepdim=True,
            ).clamp_min(1.0)
            if self.stop_gradient_between_stages:
                weights = weights.detach()
        return (encoded * weights.unsqueeze(-1)).sum(dim=1)


def trainable_parameter_count(model: nn.Module) -> int:
    return sum(
        parameter.numel()
        for parameter in model.parameters()
        if parameter.requires_grad
    )


__all__ = [
    "SIDE_SOURCE_COUNT",
    "SIDE_SOURCE_RCSD",
    "SIDE_SOURCE_SWSD",
    "SIDE_SOURCE_UNRESOLVED",
    "TargetAAdvanceRightJointAccessDecoder",
    "trainable_parameter_count",
]
