from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_independent_gate import (
    INDEPENDENT_GATE_FEATURE_DIM,
    build_independent_anchor_gate_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


JOINT_GATE_SEGMENT_STRUCTURAL_DIM = 8
JOINT_GATE_SEGMENT_FEATURE_DIM = 64 * 5 + JOINT_GATE_SEGMENT_STRUCTURAL_DIM


@dataclass(frozen=True)
class JointGateConfig:
    hidden_dim: int = 192
    bottleneck_dim: int = 64
    dropout: float = 0.1
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    max_epochs: int = 24
    patience: int = 4
    batch_size: int = 192
    anchor_loss_weight: float = 1.0
    segment_loss_weight: float = 0.25
    pass_threshold: float = 0.5
    soft_min_temperature: float = 0.25
    empty_pass_margin: float = 12.0
    torch_num_threads: int = 8

    def validate(self) -> None:
        if self.hidden_dim < 1 or self.bottleneck_dim < 1:
            raise ValueError("joint gate hidden dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("joint gate dropout is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("joint gate optimizer config is invalid")
        if self.max_epochs < 1 or self.patience < 1 or self.batch_size < 1:
            raise ValueError("joint gate training config is invalid")
        if self.anchor_loss_weight <= 0 or self.segment_loss_weight <= 0:
            raise ValueError("joint gate loss weights are invalid")
        if not 0.0 < self.pass_threshold < 1.0:
            raise ValueError("joint gate threshold is invalid")
        if self.soft_min_temperature <= 0 or self.empty_pass_margin <= 0:
            raise ValueError("joint gate monotone aggregation is invalid")
        if self.torch_num_threads < 1:
            raise ValueError("joint gate torch thread count is invalid")


@dataclass(frozen=True)
class JointGateAnchorTarget:
    sample_id: str
    case_key: str
    anchor_id: str
    fold: int
    status_label: int
    status_supervised: bool
    candidate_supervised: bool
    gate_label: int
    gate_supervised: bool
    sample_weight: float


@dataclass(frozen=True)
class JointGateSegmentExample:
    sample_id: str
    case_key: str
    segment_id: str
    fold: int
    segment_features: tuple[float, ...]
    required_anchor_indices: tuple[int, ...]
    gate_label: int
    gate_supervised: bool
    sample_weight: float

    def __post_init__(self) -> None:
        if len(self.segment_features) != JOINT_GATE_SEGMENT_FEATURE_DIM:
            raise ValueError("joint gate Segment feature dimension differs")
        if self.gate_supervised and self.gate_label not in {0, 1}:
            raise ValueError("joint gate Segment label is invalid")
        if self.sample_weight <= 0:
            raise ValueError("joint gate Segment weight must be positive")


@dataclass(frozen=True)
class JointGateData:
    anchors: tuple[JointGateAnchorTarget, ...]
    anchor_features: torch.Tensor
    segments: tuple[JointGateSegmentExample, ...]

    def __post_init__(self) -> None:
        if self.anchor_features.shape != (
            len(self.anchors),
            INDEPENDENT_GATE_FEATURE_DIM,
        ):
            raise ValueError("joint gate anchor feature shape differs")
        if not bool(torch.isfinite(self.anchor_features).all()):
            raise ValueError("joint gate anchor features are not finite")


@dataclass(frozen=True)
class JointGateSegmentBatch:
    segment_features: torch.Tensor
    anchor_features: torch.Tensor
    anchor_mask: torch.Tensor
    labels: torch.Tensor
    task_mask: torch.Tensor
    sample_weights: torch.Tensor


class JointAnchorSegmentGate(nn.Module):
    """Shared anchor encoder constrained by anchor and Segment gate losses."""

    def __init__(self, config: JointGateConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.anchor_encoder = nn.Sequential(
            nn.Linear(INDEPENDENT_GATE_FEATURE_DIM, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Dropout(config.dropout),
        )
        self.anchor_head = nn.Sequential(
            nn.Linear(config.hidden_dim, config.bottleneck_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.bottleneck_dim, 2),
        )
        self.segment_encoder = nn.Sequential(
            nn.Linear(JOINT_GATE_SEGMENT_FEATURE_DIM, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Dropout(config.dropout),
        )
        self.segment_risk_head = nn.Sequential(
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.bottleneck_dim),
            nn.GELU(),
            nn.Linear(config.bottleneck_dim, 1),
        )

    def encode_anchors(self, features: torch.Tensor) -> torch.Tensor:
        if features.shape[-1] != INDEPENDENT_GATE_FEATURE_DIM:
            raise ValueError("joint gate anchor feature dimension differs")
        return self.anchor_encoder(features)

    def forward_anchor(self, features: torch.Tensor) -> torch.Tensor:
        return self.anchor_head(self.encode_anchors(features))

    def forward_segment(
        self,
        *,
        segment_features: torch.Tensor,
        anchor_features: torch.Tensor,
        anchor_mask: torch.Tensor,
    ) -> torch.Tensor:
        if segment_features.ndim != 2:
            raise ValueError("joint gate Segment features must be rank two")
        if anchor_features.ndim != 3 or anchor_mask.ndim != 2:
            raise ValueError("joint gate anchor set shape differs")
        if anchor_features.shape[:2] != anchor_mask.shape:
            raise ValueError("joint gate anchor set/mask differ")
        segment = self.segment_encoder(segment_features)
        encoded = self.encode_anchors(anchor_features)
        anchor_logits = self.anchor_head(encoded)
        anchor_margins = anchor_logits[..., 1] - anchor_logits[..., 0]
        required_margin = combine_required_anchor_margins(
            anchor_margins,
            anchor_mask,
            temperature=self.config.soft_min_temperature,
            empty_pass_margin=self.config.empty_pass_margin,
        )
        contextual_risk = torch.nn.functional.softplus(
            self.segment_risk_head(segment).squeeze(-1)
        )
        has_required_anchor = anchor_mask.any(dim=1)
        segment_margin = torch.where(
            has_required_anchor,
            required_margin - contextual_risk,
            required_margin,
        )
        return torch.stack((-0.5 * segment_margin, 0.5 * segment_margin), dim=-1)


def combine_required_anchor_margins(
    anchor_margins: torch.Tensor,
    anchor_mask: torch.Tensor,
    *,
    temperature: float,
    empty_pass_margin: float,
) -> torch.Tensor:
    """Conservative soft-min: more/weak required anchors only lower the gate."""
    if anchor_margins.ndim != 2 or anchor_margins.shape != anchor_mask.shape:
        raise ValueError("joint gate anchor margins/mask differ")
    if anchor_margins.shape[1] < 1:
        raise ValueError("joint gate anchor set width is empty")
    if temperature <= 0 or empty_pass_margin <= 0:
        raise ValueError("joint gate monotone aggregation is invalid")
    effective_mask = anchor_mask.clone()
    effective_margins = anchor_margins.masked_fill(~effective_mask, torch.inf)
    empty_rows = ~effective_mask.any(dim=1)
    if bool(empty_rows.any()):
        effective_mask[empty_rows, 0] = True
        effective_margins = effective_margins.clone()
        effective_margins[empty_rows, 0] = 0.0
    conservative_soft_min = -temperature * torch.logsumexp(
        -effective_margins / temperature,
        dim=1,
    )
    return torch.where(
        empty_rows,
        torch.full_like(conservative_soft_min, empty_pass_margin),
        conservative_soft_min,
    )


def read_joint_gate_data(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
) -> JointGateData:
    anchor_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(plan_label_root).resolve(strict=True)
    examples = read_anchor_pretraining_stores(anchor_root)
    anchor_features = build_independent_anchor_gate_features(examples)
    anchors = tuple(
        JointGateAnchorTarget(
            sample_id=row.sample_id,
            case_key=row.case_key,
            anchor_id=row.anchor_id,
            fold=row.fold,
            status_label=row.status_label,
            status_supervised=row.status_supervised,
            candidate_supervised=row.candidate_supervised,
            gate_label=row.gate_label,
            gate_supervised=row.gate_supervised,
            sample_weight=row.sample_weight,
        )
        for row in examples
    )
    anchor_index = {
        (row.case_key, row.anchor_id): index
        for index, row in enumerate(anchors)
    }
    groups = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    }
    labels = _read_jsonl(label_root / "training_plan_labels.jsonl")
    segments: list[JointGateSegmentExample] = []
    for label in labels:
        if not bool(label.get("label_task_mask")):
            continue
        key = (str(label["case_key"]), str(label["segment_id"]))
        group = groups.get(key)
        if group is None:
            raise ValueError(f"joint gate plan group is missing: {key}")
        if str(group.get("segment_type")) != "STANDARD":
            continue
        required_keys = [
            (key[0], str(anchor_id))
            for anchor_id in group["required_anchor_ids"]
        ]
        missing = [anchor_key for anchor_key in required_keys if anchor_key not in anchor_index]
        if missing:
            raise ValueError(
                f"joint gate Segment lacks anchor features: {key} {missing}"
            )
        raw_label = label.get("segment_anchor_gate_label")
        segments.append(
            JointGateSegmentExample(
                sample_id=f"{key[0]}:{key[1]}",
                case_key=key[0],
                segment_id=key[1],
                fold=int(label["fold"]),
                segment_features=build_joint_segment_gate_features(group),
                required_anchor_indices=tuple(
                    anchor_index[anchor_key] for anchor_key in required_keys
                ),
                gate_label=int(raw_label) if raw_label is not None else 0,
                gate_supervised=bool(
                    label.get("segment_anchor_gate_task_mask")
                ),
                sample_weight=float(label.get("label_weight") or 0.0),
            )
        )
    return JointGateData(
        anchors=anchors,
        anchor_features=anchor_features,
        segments=tuple(segments),
    )


def build_joint_segment_gate_features(
    group: Mapping[str, Any],
) -> tuple[float, ...]:
    object_features = torch.tensor(
        group["object_features"],
        dtype=torch.float32,
    )
    candidates = torch.tensor(
        [row["features"] for row in group["candidates"]],
        dtype=torch.float32,
    )
    if object_features.shape != (64,) or candidates.ndim != 2:
        raise ValueError("joint gate plan feature shape differs")
    if candidates.shape[1] != 64 or candidates.shape[0] < 1:
        raise ValueError("joint gate plan candidates are invalid")
    decisions = [str(row["decision"]) for row in group["candidates"]]
    road_counts = [len(row["road_ids"]) for row in group["candidates"]]
    count = len(decisions)
    structural = torch.tensor(
        (
            math.tanh(count / 16.0),
            decisions.count("KEEP_SWSD") / count,
            decisions.count("USE_RCSD") / count,
            decisions.count("ABSTAIN") / count,
            math.tanh(sum(road_counts) / max(count, 1) / 8.0),
            math.tanh(max(road_counts, default=0) / 16.0),
            math.tanh(len(group.get("pair_node_ids") or ()) / 4.0),
            math.tanh(len(group.get("junc_node_ids") or ()) / 8.0),
        ),
        dtype=torch.float32,
    )
    result = torch.cat(
        (
            object_features,
            candidates.mean(dim=0),
            candidates.std(dim=0, unbiased=False),
            candidates.amin(dim=0),
            candidates.amax(dim=0),
            structural,
        )
    )
    if result.shape != (JOINT_GATE_SEGMENT_FEATURE_DIM,):
        raise AssertionError("joint gate Segment feature dimension drifted")
    if not bool(torch.isfinite(result).all()):
        raise ValueError("joint gate Segment features are not finite")
    return tuple(float(value) for value in result)


def collate_joint_segment_gate_batch(
    data: JointGateData,
    indices: Sequence[int],
) -> JointGateSegmentBatch:
    if not indices:
        raise ValueError("joint gate Segment batch is empty")
    rows = [data.segments[index] for index in indices]
    maximum = max(1, max(len(row.required_anchor_indices) for row in rows))
    anchor_features = torch.zeros(
        (len(rows), maximum, INDEPENDENT_GATE_FEATURE_DIM),
        dtype=torch.float32,
    )
    anchor_mask = torch.zeros((len(rows), maximum), dtype=torch.bool)
    for batch_index, row in enumerate(rows):
        count = len(row.required_anchor_indices)
        if count:
            anchor_features[batch_index, :count] = data.anchor_features[
                list(row.required_anchor_indices)
            ]
            anchor_mask[batch_index, :count] = True
    return JointGateSegmentBatch(
        segment_features=torch.tensor(
            [row.segment_features for row in rows],
            dtype=torch.float32,
        ),
        anchor_features=anchor_features,
        anchor_mask=anchor_mask,
        labels=torch.tensor([row.gate_label for row in rows], dtype=torch.long),
        task_mask=torch.tensor(
            [row.gate_supervised for row in rows],
            dtype=torch.bool,
        ),
        sample_weights=torch.tensor(
            [row.sample_weight for row in rows],
            dtype=torch.float32,
        ),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


__all__ = [
    "JOINT_GATE_SEGMENT_FEATURE_DIM",
    "JointAnchorSegmentGate",
    "JointGateConfig",
    "JointGateData",
    "JointGateSegmentExample",
    "build_joint_segment_gate_features",
    "combine_required_anchor_margins",
    "collate_joint_segment_gate_batch",
    "read_joint_gate_data",
]
