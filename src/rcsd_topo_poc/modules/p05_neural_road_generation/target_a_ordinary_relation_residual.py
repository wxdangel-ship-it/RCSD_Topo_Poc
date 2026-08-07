from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_oof import (
    _inner_fold_for_outer,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    OrdinaryAnchorConditionedExample,
    collate_oof_anchor_conditioned_ordinary_batch,
    read_oof_anchor_conditioned_ordinary_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_oof import (
    _conditioned_plan_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    acceptable_set_nll,
    move_training_batch,
    preferred_cross_entropy,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ORDINARY_RELATION_FEATURE_START = 23
ORDINARY_RELATION_FEATURE_END = 36
ORDINARY_RELATION_FEATURE_DIM = (
    ORDINARY_RELATION_FEATURE_END - ORDINARY_RELATION_FEATURE_START
)


@dataclass(frozen=True)
class OrdinaryRelationResidualExample:
    conditioned: OrdinaryAnchorConditionedExample
    base_logits: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.base_logits) != len(self.conditioned.base.candidate_ids):
            raise ValueError("ordinary residual base logit count differs")

    @property
    def sample_id(self) -> str:
        return self.conditioned.sample_id

    @property
    def case_key(self) -> str:
        return self.conditioned.case_key

    @property
    def fold(self) -> int:
        return self.conditioned.fold


@dataclass(frozen=True)
class OrdinaryRelationResidualBatch:
    base_logits: torch.Tensor
    relation_features: torch.Tensor
    candidate_mask: torch.Tensor
    acceptable: torch.Tensor
    preferred: torch.Tensor
    task_mask: torch.Tensor
    sample_weights: torch.Tensor

    def to(self, device: torch.device) -> OrdinaryRelationResidualBatch:
        return OrdinaryRelationResidualBatch(
            **{
                name: value.to(device)
                for name, value in vars(self).items()
            }
        )


class OrdinaryRelationResidual(nn.Module):
    """Bounded relation-only correction over frozen OOF base plan logits."""

    def __init__(self, hidden_dim: int = 64) -> None:
        super().__init__()
        if hidden_dim < 8:
            raise ValueError("ordinary relation residual hidden dim is too small")
        self.hidden_dim = hidden_dim
        self.relation_stem = nn.Sequential(
            nn.Linear(ORDINARY_RELATION_FEATURE_DIM, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.residual_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, 1),
        )
        self.scale_logit = nn.Parameter(torch.tensor(-2.0))

    def forward(
        self,
        base_logits: torch.Tensor,
        relation_features: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if relation_features.shape != (
            *base_logits.shape,
            ORDINARY_RELATION_FEATURE_DIM,
        ):
            raise ValueError("ordinary residual relation shape differs")
        if candidate_mask.shape != base_logits.shape:
            raise ValueError("ordinary residual candidate mask differs")
        encoded = self.relation_stem(relation_features)
        mask_values = candidate_mask.unsqueeze(-1).to(encoded.dtype)
        context = (encoded * mask_values).sum(dim=1) / mask_values.sum(
            dim=1
        ).clamp_min(1.0)
        context = context.unsqueeze(1).expand_as(encoded)
        finite_base = torch.where(
            candidate_mask,
            base_logits,
            torch.zeros_like(base_logits),
        )
        safe_base = finite_base.masked_fill(
            ~candidate_mask,
            torch.finfo(base_logits.dtype).min,
        )
        base_probability = torch.softmax(safe_base, dim=-1)
        inputs = torch.cat(
            (
                encoded,
                context,
                finite_base.unsqueeze(-1),
                base_probability.unsqueeze(-1),
            ),
            dim=-1,
        )
        raw_residual = self.residual_head(inputs).squeeze(-1)
        scale = torch.sigmoid(self.scale_logit)
        bounded_residual = 2.0 * scale * torch.tanh(raw_residual)
        combined = (finite_base + bounded_residual).masked_fill(
            ~candidate_mask,
            float("-inf"),
        )
        return {
            "combined_logits": combined,
            "bounded_residual": bounded_residual,
            "residual_scale": scale,
        }


def collate_ordinary_relation_residual_batch(
    examples: Sequence[OrdinaryRelationResidualExample],
) -> OrdinaryRelationResidualBatch:
    if not examples:
        raise ValueError("cannot collate empty ordinary residual batch")
    candidate_count = max(
        len(example.conditioned.base.candidate_ids)
        for example in examples
    )
    batch_size = len(examples)
    base_logits = torch.zeros((batch_size, candidate_count))
    relation_features = torch.zeros(
        (
            batch_size,
            candidate_count,
            ORDINARY_RELATION_FEATURE_DIM,
        )
    )
    candidate_mask = torch.zeros(
        (batch_size, candidate_count),
        dtype=torch.bool,
    )
    acceptable = torch.zeros_like(candidate_mask)
    preferred = torch.full((batch_size,), -1, dtype=torch.long)
    task_mask = torch.zeros((batch_size,), dtype=torch.bool)
    sample_weights = torch.tensor(
        [
            example.conditioned.base.sample_weight
            for example in examples
        ],
        dtype=torch.float32,
    )
    for batch_index, example in enumerate(examples):
        conditioned = example.conditioned
        count = len(conditioned.base.candidate_ids)
        base_logits[batch_index, :count] = torch.tensor(
            example.base_logits,
            dtype=torch.float32,
        )
        relation_features[batch_index, :count] = torch.tensor(
            [
                features[
                    ORDINARY_RELATION_FEATURE_START:
                    ORDINARY_RELATION_FEATURE_END
                ]
                for features in conditioned.conditioned_candidate_features
            ],
            dtype=torch.float32,
        )
        candidate_mask[batch_index, :count] = torch.tensor(
            conditioned.enabled_candidate_mask,
            dtype=torch.bool,
        )
        for candidate_index in conditioned.conditioned_acceptable_indices:
            acceptable[batch_index, candidate_index] = True
        preferred[batch_index] = conditioned.conditioned_preferred_index
        task_mask[batch_index] = conditioned.conditioned_label_reachable
    return OrdinaryRelationResidualBatch(
        base_logits=base_logits,
        relation_features=relation_features,
        candidate_mask=candidate_mask,
        acceptable=acceptable,
        preferred=preferred,
        task_mask=task_mask,
        sample_weights=sample_weights,
    )


def run_ordinary_relation_residual_strict_nested(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    base_oof_root: Path,
    output_root: Path,
    run_id: str,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
    hidden_dim: int = 64,
    learning_rate: float = 1e-3,
    weight_decay: float = 2e-4,
    max_epochs: int = 40,
    patience: int = 5,
    torch_num_threads: int = 4,
) -> Path:
    started = time.perf_counter()
    if batch_size < 1 or max_epochs < 1 or patience < 1:
        raise ValueError("ordinary residual training limits are invalid")
    if learning_rate <= 0 or weight_decay < 0:
        raise ValueError("ordinary residual optimizer is invalid")
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    preflight = normalize_runtime_path(preflight_root).resolve(strict=True)
    anchor_store = normalize_runtime_path(anchor_store_root).resolve(
        strict=True
    )
    anchor_oof = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    base_root = normalize_runtime_path(base_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    device = _resolve_device(requested_device)
    conditioned = read_oof_anchor_conditioned_ordinary_examples(
        candidate_store_root=candidate_root,
        preflight_root=preflight,
        anchor_store_root=anchor_store,
        anchor_oof_root=anchor_oof,
        include_anchor_plan_relations=True,
    )
    base_logits = _extract_base_oof_logits(
        base_root,
        conditioned,
        batch_size=batch_size,
        device=device,
    )
    examples = [
        OrdinaryRelationResidualExample(
            conditioned=example,
            base_logits=base_logits[example.sample_id],
        )
        for example in conditioned
    ]
    _write_jsonl(
        root / "base_oof_logits.jsonl",
        [
            {
                "sample_id": example.sample_id,
                "case_key": example.case_key,
                "fold": example.fold,
                "candidate_ids": list(
                    example.conditioned.base.candidate_ids
                ),
                "base_logits": [
                    value if math.isfinite(value) else None
                    for value in example.base_logits
                ],
            }
            for example in examples
        ],
    )
    folds = sorted({example.fold for example in examples})
    if len(folds) < 3:
        raise ValueError("ordinary residual requires at least three folds")
    predictions: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for outer_fold in folds:
        inner_fold = _inner_fold_for_outer(folds, outer_fold)
        (
            inner_training,
            inner_validation,
            outer_training,
            outer_validation,
        ) = _strict_nested_split(
            examples,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
        )
        tuning = _train_residual(
            inner_training,
            inner_validation,
            hidden_dim=hidden_dim,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            max_epochs=max_epochs,
            patience=patience,
            batch_size=batch_size,
            seed=seed + outer_fold * 100 + 17,
            torch_num_threads=torch_num_threads,
            device=device,
        )
        final = _train_residual_fixed(
            outer_training,
            hidden_dim=hidden_dim,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            epoch_count=tuning["best_epoch"],
            batch_size=batch_size,
            seed=seed + outer_fold * 100 + 53,
            torch_num_threads=torch_num_threads,
            device=device,
        )
        fold_predictions = _predict_residual(
            final["model"],
            outer_validation,
            batch_size=batch_size,
            device=device,
        )
        for row in fold_predictions:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                }
            )
        predictions.extend(fold_predictions)
        inner_checkpoint = root / (
            f"fold_{outer_fold}_inner_residual.pt"
        )
        outer_checkpoint = root / f"fold_{outer_fold}_residual.pt"
        _save_residual_checkpoint(
            inner_checkpoint,
            tuning["model"],
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 17,
            epoch_count=tuning["best_epoch"],
            hidden_dim=hidden_dim,
        )
        _save_residual_checkpoint(
            outer_checkpoint,
            final["model"],
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=final["epoch_count"],
            hidden_dim=hidden_dim,
        )
        fold_row = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "inner_train_example_count": len(inner_training),
            "inner_validation_example_count": len(inner_validation),
            "outer_train_example_count": len(outer_training),
            "outer_validation_example_count": len(outer_validation),
            "selected_epoch": tuning["best_epoch"],
            "inner_best_validation_loss": tuning[
                "best_validation_loss"
            ],
            "inner_wall_seconds": tuning["wall_seconds"],
            "outer_wall_seconds": final["wall_seconds"],
            "inner_residual_scale": tuning["residual_scale"],
            "outer_residual_scale": final["residual_scale"],
            "inner_checkpoint": str(inner_checkpoint.resolve()),
            "inner_checkpoint_sha256": sha256_file(inner_checkpoint),
            "outer_checkpoint": str(outer_checkpoint.resolve()),
            "outer_checkpoint_sha256": sha256_file(outer_checkpoint),
            "metrics": _conditioned_plan_metrics(fold_predictions),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_row)
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    _write_jsonl(root / "oof_predictions.jsonl", predictions)
    coverage_ok = (
        len(predictions) == len(examples)
        and {row["sample_id"] for row in predictions}
        == {example.sample_id for example in examples}
    )
    unsafe_anchor_bypass_count = sum(
        bool(
            row["anchor_gate_fallback_required"]
            and row["effective_decision"] != "ABSTAIN"
        )
        for row in predictions
    )
    residual_parameter_count = parameter_count(
        OrdinaryRelationResidual(hidden_dim)
    )
    base_summary = _read_json(base_root / "summary.json")
    base_parameter_count = int(
        base_summary["model_contract"]["parameter_count"]
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ANCHOR_RELATION_RESIDUAL_STRICT_NESTED",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "base_oof_summary_sha256": sha256_file(
            base_root / "summary.json"
        ),
        "base_oof_logits_sha256": sha256_file(
            root / "base_oof_logits.jsonl"
        ),
        "candidate_store_manifest_sha256": sha256_file(
            candidate_root / "manifest.json"
        ),
        "preflight_summary_sha256": sha256_file(
            preflight / "summary.json"
        ),
        "anchor_store_manifest_sha256": sha256_file(
            anchor_store / "manifest.json"
        ),
        "anchor_oof_summary_sha256": sha256_file(
            anchor_oof / "summary.json"
        ),
        "example_count": len(examples),
        "conditioned_label_reachable_count": sum(
            example.conditioned.conditioned_label_reachable
            for example in examples
        ),
        "anchor_gate_fallback_required_count": sum(
            example.conditioned.fallback_required
            for example in examples
        ),
        "folds": fold_rows,
        "fold_count": len(folds),
        "oof_metrics": _conditioned_plan_metrics(predictions),
        "oof_coverage_exact": coverage_ok,
        "unsafe_anchor_bypass_count": unsafe_anchor_bypass_count,
        "base_parameter_count": base_parameter_count,
        "residual_parameter_count": residual_parameter_count,
        "combined_parameter_count": (
            base_parameter_count + residual_parameter_count
        ),
        "residual_contract": {
            "relation_feature_start": ORDINARY_RELATION_FEATURE_START,
            "relation_feature_end": ORDINARY_RELATION_FEATURE_END,
            "relation_feature_dim": ORDINARY_RELATION_FEATURE_DIM,
            "hidden_dim": hidden_dim,
            "bounded_logit_delta": 2.0,
            "base_logits_frozen": True,
            "base_logits_are_case_oof": True,
            "raw_id_embedding_count": 0,
            "terminal_feature_count": 0,
        },
        "optimizer": {
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
            "max_epochs": max_epochs,
            "patience": patience,
            "batch_size": batch_size,
            "torch_num_threads": torch_num_threads,
        },
        "release_gate": "NO_GO",
        "scope_statement": (
            "The residual may only make a bounded correction to frozen v35 "
            "case-OOF complete-plan logits. It cannot bypass anchor gating, "
            "create candidates, or count fallback as positive KEEP_SWSD."
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not coverage_ok:
        raise RuntimeError(f"ordinary relation residual coverage differs: {root}")
    if unsafe_anchor_bypass_count:
        raise RuntimeError(f"ordinary relation residual bypassed anchors: {root}")
    return root


def _extract_base_oof_logits(
    base_root: Path,
    examples: Sequence[OrdinaryAnchorConditionedExample],
    *,
    batch_size: int,
    device: torch.device,
) -> dict[str, tuple[float, ...]]:
    result: dict[str, tuple[float, ...]] = {}
    for fold in sorted({example.fold for example in examples}):
        checkpoint = torch.load(
            base_root / f"fold_{fold}_checkpoint.pt",
            map_location=device,
            weights_only=False,
        )
        config = TargetAConfig(**checkpoint["config"])
        model = TargetAJointNetwork(config).to(device)
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        fold_examples = [
            example for example in examples if example.fold == fold
        ]
        with torch.no_grad():
            for start in range(0, len(fold_examples), batch_size):
                source = fold_examples[start : start + batch_size]
                base_source = [
                    replace(
                        example,
                        conditioned_candidate_features=(
                            example.base.candidate_features
                        ),
                    )
                    for example in source
                ]
                batch = move_training_batch(
                    collate_oof_anchor_conditioned_ordinary_batch(
                        base_source
                    ),
                    device,
                )
                logits = model(batch.tensors)[
                    "ordinary_plan_logits"
                ][:, 0, :].detach().cpu()
                for example, row in zip(source, logits, strict=True):
                    count = len(example.base.candidate_ids)
                    result[example.sample_id] = tuple(
                        float(value) for value in row[:count].tolist()
                    )
    if set(result) != {example.sample_id for example in examples}:
        raise ValueError("base OOF logit coverage differs")
    return result


def _train_residual(
    training: Sequence[OrdinaryRelationResidualExample],
    validation: Sequence[OrdinaryRelationResidualExample],
    *,
    hidden_dim: int,
    learning_rate: float,
    weight_decay: float,
    max_epochs: int,
    patience: int,
    batch_size: int,
    seed: int,
    torch_num_threads: int,
    device: torch.device,
) -> dict[str, Any]:
    model = _initialize_residual(hidden_dim, seed, torch_num_threads, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    train_batches = _residual_batches(training, batch_size)
    validation_batches = _residual_batches(validation, batch_size)
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    best_validation_loss = float("inf")
    no_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, max_epochs + 1):
        train_loss = _residual_epoch(
            model,
            train_batches,
            optimizer=optimizer,
            device=device,
            seed=seed * 1000 + epoch,
        )
        validation_loss = _residual_epoch(
            model,
            validation_batches,
            optimizer=None,
            device=device,
            seed=0,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_validation_loss - 1e-6:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            best_validation_loss = validation_loss
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= patience:
                break
    if best_state is None:
        raise RuntimeError("ordinary residual tuning produced no checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_validation_loss,
        "history": history,
        "wall_seconds": time.perf_counter() - started,
        "residual_scale": float(
            torch.sigmoid(model.scale_logit).detach().cpu().item()
        ),
    }


def _train_residual_fixed(
    training: Sequence[OrdinaryRelationResidualExample],
    *,
    hidden_dim: int,
    learning_rate: float,
    weight_decay: float,
    epoch_count: int,
    batch_size: int,
    seed: int,
    torch_num_threads: int,
    device: torch.device,
) -> dict[str, Any]:
    model = _initialize_residual(hidden_dim, seed, torch_num_threads, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    batches = _residual_batches(training, batch_size)
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, epoch_count + 1):
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": _residual_epoch(
                    model,
                    batches,
                    optimizer=optimizer,
                    device=device,
                    seed=seed * 1000 + epoch,
                ),
            }
        )
    model.eval()
    return {
        "model": model,
        "epoch_count": epoch_count,
        "history": history,
        "wall_seconds": time.perf_counter() - started,
        "residual_scale": float(
            torch.sigmoid(model.scale_logit).detach().cpu().item()
        ),
    }


def _initialize_residual(
    hidden_dim: int,
    seed: int,
    torch_num_threads: int,
    device: torch.device,
) -> OrdinaryRelationResidual:
    random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(torch_num_threads)
    return OrdinaryRelationResidual(hidden_dim).to(device)


def _residual_epoch(
    model: OrdinaryRelationResidual,
    batches: Sequence[OrdinaryRelationResidualBatch],
    *,
    optimizer: torch.optim.Optimizer | None,
    device: torch.device,
    seed: int,
) -> float:
    model.train(optimizer is not None)
    order = list(range(len(batches)))
    if optimizer is not None:
        random.Random(seed).shuffle(order)
    total = 0.0
    for index in order:
        batch = batches[index].to(device)
        if optimizer is not None:
            optimizer.zero_grad(set_to_none=True)
        outputs = model(
            batch.base_logits,
            batch.relation_features,
            batch.candidate_mask,
        )
        loss = _residual_loss(outputs, batch)
        if optimizer is not None:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
        total += float(loss.detach().item())
    return total / len(batches)


def _residual_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: OrdinaryRelationResidualBatch,
) -> torch.Tensor:
    logits = outputs["combined_logits"]
    set_loss = acceptable_set_nll(
        logits,
        batch.acceptable,
        batch.candidate_mask,
    )
    preferred_loss = preferred_cross_entropy(
        logits,
        batch.preferred,
        batch.candidate_mask,
    )
    weights = batch.sample_weights * batch.task_mask.to(
        batch.sample_weights.dtype
    )
    denominator = weights.sum().clamp_min(1.0)
    plan_loss = (
        (set_loss + 0.1 * preferred_loss) * weights
    ).sum() / denominator
    residual = outputs["bounded_residual"]
    residual_mask = (
        batch.candidate_mask
        & batch.task_mask.unsqueeze(-1)
    ).to(residual.dtype)
    regularization = (
        residual.square() * residual_mask
    ).sum() / residual_mask.sum().clamp_min(1.0)
    return plan_loss + 1e-3 * regularization


def _predict_residual(
    model: OrdinaryRelationResidual,
    examples: Sequence[OrdinaryRelationResidualExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source = examples[start : start + batch_size]
            batch = collate_ordinary_relation_residual_batch(source).to(
                device
            )
            outputs = model(
                batch.base_logits,
                batch.relation_features,
                batch.candidate_mask,
            )
            probabilities = torch.softmax(
                outputs["combined_logits"],
                dim=-1,
            ).detach().cpu()
            residuals = outputs["bounded_residual"].detach().cpu()
            predicted_indices = probabilities.argmax(dim=-1).tolist()
            for example, predicted_index, probability, residual in zip(
                source,
                predicted_indices,
                probabilities.tolist(),
                residuals.tolist(),
                strict=True,
            ):
                conditioned = example.conditioned
                base = conditioned.base
                acceptable = set(
                    conditioned.conditioned_acceptable_indices
                )
                raw_decision = base.candidate_decisions[predicted_index]
                forced_fallback = conditioned.fallback_required
                rows.append(
                    {
                        "sample_id": base.sample_id,
                        "case_key": base.case_key,
                        "segment_id": base.segment_id,
                        "fold": base.fold,
                        "required_anchor_count": len(
                            base.required_anchor_ids
                        ),
                        "anchor_resolved_count": (
                            conditioned.anchor_resolved_count
                        ),
                        "all_required_anchors_resolved": (
                            conditioned.all_required_anchors_resolved
                        ),
                        "missing_anchor_ids": list(
                            conditioned.missing_anchor_ids
                        ),
                        "conditioned_label_reachable": (
                            conditioned.conditioned_label_reachable
                        ),
                        "anchor_gate_fallback_required": forced_fallback,
                        "raw_predicted_plan_id": (
                            base.candidate_ids[predicted_index]
                        ),
                        "raw_predicted_decision": raw_decision,
                        "raw_predicted_probability": float(
                            probability[predicted_index]
                        ),
                        "base_predicted_plan_id": base.candidate_ids[
                            max(
                                range(len(example.base_logits)),
                                key=lambda index: example.base_logits[index],
                            )
                        ],
                        "selected_logit_residual": float(
                            residual[predicted_index]
                        ),
                        "effective_decision": (
                            "ABSTAIN" if forced_fallback else raw_decision
                        ),
                        "automatic_decision": bool(
                            not forced_fallback
                            and raw_decision != "ABSTAIN"
                        ),
                        "acceptable_plan_ids": [
                            base.candidate_ids[index]
                            for index in (
                                conditioned.conditioned_acceptable_indices
                            )
                        ],
                        "acceptable_decisions": sorted(
                            {
                                base.candidate_decisions[index]
                                for index in acceptable
                            }
                        ),
                        "preferred_plan_id": (
                            base.candidate_ids[
                                conditioned.conditioned_preferred_index
                            ]
                            if conditioned.conditioned_preferred_index >= 0
                            else ""
                        ),
                        "preferred_decision": base.preferred_decision,
                        "acceptable_exact": (
                            predicted_index in acceptable
                            if conditioned.conditioned_label_reachable
                            else None
                        ),
                        "preferred_exact": (
                            predicted_index
                            == conditioned.conditioned_preferred_index
                            if conditioned.conditioned_preferred_index >= 0
                            else None
                        ),
                        "fallback_safe_success": forced_fallback,
                    }
                )
    return rows


def _strict_nested_split(
    examples: Sequence[OrdinaryRelationResidualExample],
    *,
    outer_fold: int,
    inner_fold: int,
) -> tuple[
    list[OrdinaryRelationResidualExample],
    list[OrdinaryRelationResidualExample],
    list[OrdinaryRelationResidualExample],
    list[OrdinaryRelationResidualExample],
]:
    inner_training = [
        example
        for example in examples
        if example.fold not in {outer_fold, inner_fold}
    ]
    inner_validation = [
        example for example in examples if example.fold == inner_fold
    ]
    outer_training = [
        example for example in examples if example.fold != outer_fold
    ]
    outer_validation = [
        example for example in examples if example.fold == outer_fold
    ]
    if not all(
        (
            inner_training,
            inner_validation,
            outer_training,
            outer_validation,
        )
    ):
        raise ValueError("ordinary residual split has an empty partition")
    if {row.case_key for row in outer_training} & {
        row.case_key for row in outer_validation
    }:
        raise AssertionError("outer residual Case leaked into training")
    if {row.case_key for row in inner_training} & {
        row.case_key for row in inner_validation
    }:
        raise AssertionError("inner residual Case leaked into training")
    return (
        inner_training,
        inner_validation,
        outer_training,
        outer_validation,
    )


def _residual_batches(
    examples: Sequence[OrdinaryRelationResidualExample],
    batch_size: int,
) -> list[OrdinaryRelationResidualBatch]:
    return [
        collate_ordinary_relation_residual_batch(
            examples[index : index + batch_size]
        )
        for index in range(0, len(examples), batch_size)
    ]


def _save_residual_checkpoint(
    path: Path,
    model: OrdinaryRelationResidual,
    *,
    outer_fold: int,
    inner_fold: int,
    seed: int,
    epoch_count: int,
    hidden_dim: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_ANCHOR_RELATION_RESIDUAL",
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "seed": seed,
            "epoch_count": epoch_count,
            "hidden_dim": hidden_dim,
            "model_state_dict": {
                key: value.detach().cpu()
                for key, value in sorted(model.state_dict().items())
            },
        },
        path,
    )


def _resolve_device(requested: str) -> torch.device:
    if requested.casefold() == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")
        return torch.device("cuda")
    if requested.casefold() == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported ordinary residual device: {requested}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "ORDINARY_RELATION_FEATURE_DIM",
    "OrdinaryRelationResidual",
    "OrdinaryRelationResidualExample",
    "collate_ordinary_relation_residual_batch",
    "run_ordinary_relation_residual_strict_nested",
]
