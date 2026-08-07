from __future__ import annotations

import copy
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_oof import (
    _inner_fold_for_outer,
    _strict_nested_split,
    _write_json,
    _write_jsonl,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_oof import (
    _classification_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_posthoc_gate import (
    _validate_frozen_prediction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_safety import (
    _safety_summary,
    apply_inner_calibrated_anchor_safety_gate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


INDEPENDENT_GATE_AGGREGATE_COUNT = 4
INDEPENDENT_GATE_STRUCTURAL_COUNT = 7
INDEPENDENT_GATE_FEATURE_DIM = (
    TARGET_A_FEATURE_DIM
    + 2 * INDEPENDENT_GATE_AGGREGATE_COUNT * TARGET_A_FEATURE_DIM
    + INDEPENDENT_GATE_STRUCTURAL_COUNT
)


@dataclass(frozen=True)
class IndependentAnchorGateConfig:
    hidden_dim: int = 192
    bottleneck_dim: int = 64
    dropout: float = 0.1
    learning_rate: float = 1e-3
    weight_decay: float = 2e-4
    max_epochs: int = 24
    patience: int = 4
    batch_size: int = 256
    pass_threshold: float = 0.5
    torch_num_threads: int = 8

    def validate(self) -> None:
        if self.hidden_dim < 1 or self.bottleneck_dim < 1:
            raise ValueError("independent anchor gate hidden dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("independent anchor gate dropout is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("independent anchor gate optimizer config is invalid")
        if self.max_epochs < 1 or self.patience < 1 or self.batch_size < 1:
            raise ValueError("independent anchor gate training config is invalid")
        if not 0.0 < self.pass_threshold < 1.0:
            raise ValueError("independent anchor gate threshold is invalid")
        if self.torch_num_threads < 1:
            raise ValueError("independent anchor gate thread count is invalid")


class IndependentAnchorGate(nn.Module):
    def __init__(self, config: IndependentAnchorGateConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.network = nn.Sequential(
            nn.Linear(INDEPENDENT_GATE_FEATURE_DIM, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.bottleneck_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.bottleneck_dim, 2),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if (
            features.ndim != 2
            or features.shape[-1] != INDEPENDENT_GATE_FEATURE_DIM
        ):
            raise ValueError("independent anchor gate feature shape differs")
        return self.network(features)


def build_independent_anchor_gate_features(
    examples: Sequence[AnchorPretrainExample],
) -> torch.Tensor:
    """Build truth-free focal/candidate/dependency summaries without raw IDs."""
    if not examples:
        raise ValueError("independent anchor gate requires examples")
    by_case: dict[str, dict[str, AnchorPretrainExample]] = {}
    for example in examples:
        case = by_case.setdefault(example.case_key, {})
        if example.anchor_id in case:
            raise ValueError("independent anchor gate has duplicate Case anchor")
        case[example.anchor_id] = example
    rows: list[torch.Tensor] = []
    for example in examples:
        focal = torch.tensor(example.object_features, dtype=torch.float32)
        candidates = torch.tensor(
            example.candidate_features,
            dtype=torch.float32,
        )
        dependencies = [
            by_case[example.case_key][anchor_id]
            for anchor_id in (
                example.dependency_anchor_ids or (example.anchor_id,)
            )
            if anchor_id in by_case[example.case_key]
        ]
        if not dependencies:
            dependencies = [example]
        dependency_features = torch.tensor(
            [row.object_features for row in dependencies],
            dtype=torch.float32,
        )
        member_counts = [
            _candidate_member_count(candidate_id)
            for candidate_id in example.candidate_ids
        ]
        structural = torch.tensor(
            (
                len(example.candidate_ids),
                len(dependencies),
                sum(
                    row[27] > 0.5
                    for row in example.candidate_features
                ),
                sum(
                    row[27] <= 0.5
                    for row in example.candidate_features
                ),
                min(member_counts),
                max(member_counts),
                sum(member_counts) / len(member_counts),
            ),
            dtype=torch.float32,
        )
        rows.append(
            torch.cat(
                (
                    focal,
                    _aggregate_features(candidates),
                    _aggregate_features(dependency_features),
                    structural,
                )
            )
        )
    result = torch.stack(rows)
    if result.shape != (len(examples), INDEPENDENT_GATE_FEATURE_DIM):
        raise AssertionError("independent anchor gate feature dimension drifted")
    if not bool(torch.isfinite(result).all()):
        raise ValueError("independent anchor gate features are not finite")
    return result


def run_independent_anchor_gate_strict_nested_oof(
    *,
    store_root: Path,
    base_oof_root: Path,
    output_root: Path,
    run_id: str,
    config: IndependentAnchorGateConfig,
    seed: int,
) -> Path:
    """Train a strict nested gate independent from the frozen base embedding."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    source_root = normalize_runtime_path(store_root).resolve(strict=True)
    base_root = normalize_runtime_path(base_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_anchor_pretraining_stores(source_root)
    features = build_independent_anchor_gate_features(examples)
    example_index = {
        example.sample_id: index for index, example in enumerate(examples)
    }
    gate_labels = torch.tensor(
        [example.gate_label for example in examples],
        dtype=torch.long,
    )
    gate_masks = torch.tensor(
        [example.gate_supervised for example in examples],
        dtype=torch.bool,
    )
    sample_weights = torch.tensor(
        [example.sample_weight for example in examples],
        dtype=torch.float32,
    )
    base_outer = {
        str(row["sample_id"]): row
        for row in _read_jsonl(base_root / "oof_predictions.jsonl")
    }
    base_inner = {
        (int(row["outer_fold"]), str(row["sample_id"])): row
        for row in _read_jsonl(
            base_root / "inner_calibration_predictions.jsonl"
        )
    }
    if set(base_outer) != set(example_index):
        raise ValueError("independent gate base OOF coverage differs")
    folds = sorted({example.fold for example in examples})
    if len(folds) < 3:
        raise ValueError("independent gate strict nested OOF needs three folds")
    outer_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for outer_fold in folds:
        inner_fold = _inner_fold_for_outer(folds, outer_fold)
        inner_training, inner_validation, outer_training, outer_validation = (
            _strict_nested_split(
                examples,
                outer_fold=outer_fold,
                inner_fold=inner_fold,
            )
        )
        inner = _fit_gate(
            features,
            gate_labels,
            gate_masks,
            sample_weights,
            example_index,
            inner_training,
            inner_validation,
            config=config,
            seed=seed + outer_fold * 100 + 17,
        )
        fold_calibration = _apply_gate(
            inner.model,
            inner.normalizer,
            features,
            example_index,
            inner_validation,
            base_inner,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            config=config,
        )
        calibration_rows.extend(fold_calibration)
        outer = _fit_gate(
            features,
            gate_labels,
            gate_masks,
            sample_weights,
            example_index,
            outer_training,
            outer_validation,
            config=config,
            seed=seed + outer_fold * 100 + 53,
            fixed_epochs=inner.epoch_count,
        )
        fold_predictions = _apply_gate(
            outer.model,
            outer.normalizer,
            features,
            example_index,
            outer_validation,
            base_outer,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            config=config,
        )
        outer_rows.extend(fold_predictions)
        inner_path = root / f"fold_{outer_fold}_inner_gate.pt"
        outer_path = root / f"fold_{outer_fold}_gate.pt"
        _save_gate(
            inner_path,
            result=inner,
            config=config,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            base_checkpoint=(
                base_root / f"fold_{outer_fold}_inner_checkpoint.pt"
            ),
        )
        _save_gate(
            outer_path,
            result=outer,
            config=config,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            base_checkpoint=base_root / f"fold_{outer_fold}_checkpoint.pt",
        )
        fold_row = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "selected_epoch": inner.epoch_count,
            "inner_best_validation_loss": inner.best_validation_loss,
            "inner_history": inner.history,
            "outer_history": outer.history,
            "inner_metrics": _classification_metrics(fold_calibration),
            "outer_metrics": _classification_metrics(fold_predictions),
            "inner_gate_checkpoint": str(inner_path.resolve()),
            "inner_gate_checkpoint_sha256": sha256_file(inner_path),
            "outer_gate_checkpoint": str(outer_path.resolve()),
            "outer_gate_checkpoint_sha256": sha256_file(outer_path),
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_row)
    outer_rows.sort(key=lambda row: str(row["sample_id"]))
    calibration_rows.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    gated, thresholds = apply_inner_calibrated_anchor_safety_gate(
        calibration_rows,
        outer_rows,
    )
    gated.sort(key=lambda row: str(row["sample_id"]))
    _write_jsonl(root / "oof_predictions.jsonl", outer_rows)
    _write_jsonl(
        root / "inner_calibration_predictions.jsonl",
        calibration_rows,
    )
    _write_jsonl(root / "gated_oof_predictions.jsonl", gated)
    summary = {
        "stage": "ANCHOR_INDEPENDENT_GATE_STRICT_NESTED_OOF",
        "run_id": run_id,
        "seed": seed,
        "config": asdict(config),
        "example_count": len(examples),
        "feature_dim": INDEPENDENT_GATE_FEATURE_DIM,
        "feature_contract": (
            "focal object plus candidate-set and direct-dependency "
            "mean/std/min/max plus truth-free structural counts"
        ),
        "terminal_feature_count": 0,
        "raw_id_embedding_count": 0,
        "gate_parameter_count": sum(
            parameter.numel()
            for parameter in IndependentAnchorGate(config).parameters()
        ),
        "frozen_base_oof_root": str(base_root),
        "frozen_base_oof_summary_sha256": sha256_file(
            base_root / "summary.json"
        ),
        "source_store_manifest_sha256": sha256_file(
            source_root / "manifest.json"
        ),
        "oof_coverage_complete": (
            len(outer_rows) == len(examples)
            and {str(row["sample_id"]) for row in outer_rows}
            == set(example_index)
        ),
        "oof_metrics": _classification_metrics(outer_rows),
        "inner_only_thresholds": thresholds,
        "safety": _safety_summary(gated),
        "folds": fold_rows,
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


@dataclass
class _GateFitResult:
    model: IndependentAnchorGate
    normalizer: tuple[torch.Tensor, torch.Tensor]
    epoch_count: int
    best_validation_loss: float
    history: list[dict[str, float]]


def _fit_gate(
    features: torch.Tensor,
    labels: torch.Tensor,
    masks: torch.Tensor,
    weights: torch.Tensor,
    example_index: Mapping[str, int],
    training: Sequence[AnchorPretrainExample],
    validation: Sequence[AnchorPretrainExample],
    *,
    config: IndependentAnchorGateConfig,
    seed: int,
    fixed_epochs: int | None = None,
) -> _GateFitResult:
    train_indices = torch.tensor(
        [example_index[row.sample_id] for row in training],
        dtype=torch.long,
    )
    validation_indices = torch.tensor(
        [example_index[row.sample_id] for row in validation],
        dtype=torch.long,
    )
    mean = features[train_indices].mean(dim=0)
    standard_deviation = (
        features[train_indices]
        .std(dim=0, unbiased=False)
        .clamp_min(1e-4)
    )
    train_features = (
        features[train_indices] - mean
    ) / standard_deviation
    validation_features = (
        features[validation_indices] - mean
    ) / standard_deviation
    supervised_labels = labels[train_indices][masks[train_indices]]
    counts = torch.bincount(supervised_labels, minlength=2).to(torch.float32)
    if int((counts == 0).sum().item()):
        raise ValueError("independent anchor gate split lacks a gate class")
    class_weights = supervised_labels.numel() / (2 * counts)
    random.seed(seed)
    torch.manual_seed(seed)
    model = IndependentAnchorGate(config)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    best_loss = float("inf")
    stale = 0
    history: list[dict[str, float]] = []
    epoch_limit = fixed_epochs or config.max_epochs
    for epoch in range(1, epoch_limit + 1):
        model.train()
        order = torch.randperm(
            len(train_indices),
            generator=torch.Generator().manual_seed(seed * 100 + epoch),
        )
        train_total = 0.0
        batch_count = 0
        for start in range(0, len(order), config.batch_size):
            positions = order[start : start + config.batch_size]
            selected = train_indices[positions]
            supervised = masks[selected]
            if not bool(supervised.any()):
                continue
            logits = model(train_features[positions][supervised])
            raw = nn.functional.cross_entropy(
                logits,
                labels[selected][supervised],
                weight=class_weights,
                reduction="none",
            )
            loss = (
                raw * weights[selected][supervised]
            ).sum() / weights[selected][supervised].sum()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            train_total += float(loss.detach().item())
            batch_count += 1
        row = {
            "epoch": float(epoch),
            "train_loss": train_total / max(1, batch_count),
        }
        if fixed_epochs is None:
            model.eval()
            with torch.no_grad():
                supervised = masks[validation_indices]
                raw = nn.functional.cross_entropy(
                    model(validation_features[supervised]),
                    labels[validation_indices][supervised],
                    weight=class_weights,
                    reduction="none",
                )
                validation_loss = float(
                    (
                        raw * weights[validation_indices][supervised]
                    ).sum()
                    / weights[validation_indices][supervised].sum()
                )
            row["validation_loss"] = validation_loss
            if validation_loss < best_loss - 1e-6:
                best_state = copy.deepcopy(model.state_dict())
                best_epoch = epoch
                best_loss = validation_loss
                stale = 0
            else:
                stale += 1
        history.append(row)
        if fixed_epochs is None and stale >= config.patience:
            break
    if fixed_epochs is None:
        if best_state is None:
            raise RuntimeError("independent anchor gate lacks a checkpoint")
        model.load_state_dict(best_state)
        epoch_count = best_epoch
    else:
        epoch_count = fixed_epochs
        best_loss = float("nan")
    model.eval()
    return _GateFitResult(
        model=model,
        normalizer=(mean, standard_deviation),
        epoch_count=epoch_count,
        best_validation_loss=best_loss,
        history=history,
    )


def _apply_gate(
    model: IndependentAnchorGate,
    normalizer: tuple[torch.Tensor, torch.Tensor],
    features: torch.Tensor,
    example_index: Mapping[str, int],
    examples: Sequence[AnchorPretrainExample],
    base_rows: Mapping[Any, Mapping[str, Any]],
    *,
    outer_fold: int,
    inner_fold: int,
    config: IndependentAnchorGateConfig,
) -> list[dict[str, Any]]:
    indices = torch.tensor(
        [example_index[row.sample_id] for row in examples],
        dtype=torch.long,
    )
    mean, standard_deviation = normalizer
    model.eval()
    with torch.no_grad():
        probabilities = torch.softmax(
            model((features[indices] - mean) / standard_deviation),
            dim=-1,
        )[:, 1]
    result: list[dict[str, Any]] = []
    for probability, example in zip(
        probabilities,
        examples,
        strict=True,
    ):
        base_key: Any = (
            (outer_fold, example.sample_id)
            if (outer_fold, example.sample_id) in base_rows
            else example.sample_id
        )
        base = dict(base_rows[base_key])
        gate_probability = float(probability.item())
        gate_passed = gate_probability >= config.pass_threshold
        raw_status = int(base["raw_status_predicted_index"])
        effective_status = (
            raw_status
            if gate_passed
            else ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
        )
        base.update(
            {
                "outer_fold": outer_fold,
                "inner_validation_fold": inner_fold,
                "gate_label": example.gate_label,
                "gate_supervised": example.gate_supervised,
                "gate_pass_probability": gate_probability,
                "gate_passed": gate_passed,
                "status_predicted_index": effective_status,
                "predicted_index": effective_status,
                "predicted": list(AnchorStatus)[effective_status].value,
            }
        )
        base["candidate_confidence_score"] = min(
            gate_probability,
            float(base["success_probability"]),
            float(base["anchor_type_probability"]),
            max(0.0, float(base["anchor_type_margin"])),
            float(base["anchor_cardinality_probability"]),
            max(0.0, float(base["anchor_cardinality_margin"])),
            float(base["candidate_validity_probability"]),
            float(base["candidate_probability"]),
            max(0.0, float(base["candidate_margin"])),
        )
        base["raw_unsafe_success"] = bool(
            base["predicted"] == "SUCCESS"
            and not bool(base["proven_safe_anchor"])
        )
        _validate_frozen_prediction(base, base_rows[base_key])
        result.append(base)
    return result


def _aggregate_features(features: torch.Tensor) -> torch.Tensor:
    return torch.cat(
        (
            features.mean(dim=0),
            features.std(dim=0, unbiased=False),
            features.amin(dim=0),
            features.amax(dim=0),
        )
    )


def _candidate_member_count(candidate_id: str) -> int:
    members = candidate_id.split(":", 1)[-1]
    return max(1, members.count("|") + 1)


def _save_gate(
    path: Path,
    *,
    result: _GateFitResult,
    config: IndependentAnchorGateConfig,
    outer_fold: int,
    inner_fold: int,
    base_checkpoint: Path,
) -> None:
    mean, standard_deviation = result.normalizer
    torch.save(
        {
            "stage": "ANCHOR_INDEPENDENT_GATE",
            "config": asdict(config),
            "feature_dim": INDEPENDENT_GATE_FEATURE_DIM,
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "epoch_count": result.epoch_count,
            "base_checkpoint": str(base_checkpoint.resolve()),
            "base_checkpoint_sha256": sha256_file(base_checkpoint),
            "feature_mean": mean,
            "feature_standard_deviation": standard_deviation,
            "model_state_dict": {
                key: value.detach().cpu()
                for key, value in result.model.state_dict().items()
            },
        },
        path,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"JSONL row is not an object: {path}")
                rows.append(payload)
    return rows


__all__ = [
    "INDEPENDENT_GATE_FEATURE_DIM",
    "IndependentAnchorGate",
    "IndependentAnchorGateConfig",
    "build_independent_anchor_gate_features",
    "run_independent_anchor_gate_strict_nested_oof",
]
