from __future__ import annotations

import copy
import itertools
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_reranker import (
    _BeamPlanExample,
    _assert_case_disjoint,
    _generate_beam_examples,
    _reranker_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_structured_energy import (
    StructuredEnergyWeights,
    proposal_energy,
    select_structured_energy_weights,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
    _batch_tensors,
    _forward_model,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_beam_audit import (
    _load_model,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    _resolve_device,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class SamePlanAffinityConfig:
    feature_mode: str = "EMBEDDING"
    hidden_dim: int = 128
    batch_size: int = 8
    epochs: int = 24
    patience: int = 5
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    positive_weight_cap: float = 20.0
    beam_width: int = 16
    torch_num_threads: int = 4

    def validate(self) -> None:
        if self.feature_mode not in {"EMBEDDING", "RELATIONAL"}:
            raise ValueError("same-plan affinity feature mode differs")
        if min(
            self.hidden_dim,
            self.batch_size,
            self.epochs,
            self.patience,
            self.learning_rate,
            self.positive_weight_cap,
            self.beam_width,
            self.torch_num_threads,
        ) <= 0:
            raise ValueError("same-plan affinity config differs")
        if self.weight_decay < 0:
            raise ValueError("same-plan affinity weight decay differs")


@dataclass(frozen=True)
class _AffinityView:
    row: OrdinaryRoadSetExample
    candidate_embeddings: torch.Tensor
    candidate_signals: torch.Tensor
    road_relations: torch.Tensor
    same_source: torch.Tensor
    target_mask: torch.Tensor


class SamePlanAffinityHead(nn.Module):
    """Predict symmetric Road-pair co-membership in one complete plan."""

    def __init__(
        self,
        *,
        embedding_dim: int = 128,
        relation_dim: int = 13,
        signal_dim: int = 3,
        hidden_dim: int = 128,
        dropout: float = 0.1,
        feature_mode: str = "EMBEDDING",
    ) -> None:
        super().__init__()
        if feature_mode not in {"EMBEDDING", "RELATIONAL"}:
            raise ValueError("same-plan affinity feature mode differs")
        self.embedding_dim = embedding_dim
        self.relation_dim = relation_dim
        self.signal_dim = signal_dim
        self.feature_mode = feature_mode
        input_dim = relation_dim + signal_dim * 2
        if feature_mode == "EMBEDDING":
            input_dim += embedding_dim * 2
        self.head = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(
        self,
        candidate_embeddings: torch.Tensor,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> torch.Tensor:
        if (
            candidate_embeddings.ndim != 3
            or candidate_embeddings.shape[-1] != self.embedding_dim
            or candidate_signals.shape
            != (
                candidate_embeddings.shape[0],
                candidate_embeddings.shape[1],
                self.signal_dim,
            )
            or road_relations.shape
            != (
                candidate_embeddings.shape[0],
                candidate_embeddings.shape[1],
                candidate_embeddings.shape[1],
                self.relation_dim,
            )
            or candidate_mask.shape != candidate_embeddings.shape[:2]
        ):
            raise ValueError("same-plan affinity input shape differs")
        left = candidate_embeddings.unsqueeze(2)
        right = candidate_embeddings.unsqueeze(1)
        signal_left = candidate_signals.unsqueeze(2)
        signal_right = candidate_signals.unsqueeze(1)
        feature_parts = [
            road_relations,
            ((signal_left + signal_right) / 2.0).expand(
                -1,
                candidate_embeddings.shape[1],
                candidate_embeddings.shape[1],
                -1,
            ),
            (signal_left - signal_right).abs().expand(
                -1,
                candidate_embeddings.shape[1],
                candidate_embeddings.shape[1],
                -1,
            ),
        ]
        if self.feature_mode == "EMBEDDING":
            feature_parts[:0] = [
                (left - right).abs().expand(
                    -1,
                    candidate_embeddings.shape[1],
                    candidate_embeddings.shape[1],
                    -1,
                ),
                (left * right).expand(
                    -1,
                    candidate_embeddings.shape[1],
                    candidate_embeddings.shape[1],
                    -1,
                ),
            ]
        pair_features = torch.cat(feature_parts, dim=-1)
        logits = self.head(pair_features).squeeze(-1)
        valid = candidate_mask.unsqueeze(1) & candidate_mask.unsqueeze(2)
        return logits.masked_fill(~valid, 0.0)


def run_same_plan_affinity_canary(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    seed: int,
    config: SamePlanAffinityConfig = SamePlanAffinityConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train pair affinity and use it only inside complete-plan scoring."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    member_root = normalize_runtime_path(member_store_root).resolve(
        strict=True
    )
    checkpoint_root = normalize_runtime_path(
        expansion_checkpoint_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    rows, read_summary = read_ordinary_road_set_examples(member_root)
    fold_summary = _read_json(
        checkpoint_root / f"fold_{outer_fold}_summary.json"
    )
    inner_fold = int(fold_summary["inner_validation_fold"])
    training_rows = [
        row for row in rows if row.fold not in {outer_fold, inner_fold}
    ]
    validation_rows = [row for row in rows if row.fold == inner_fold]
    outer_rows = [row for row in rows if row.fold == outer_fold]
    _assert_case_disjoint(training_rows, validation_rows)
    _assert_case_disjoint(training_rows, outer_rows)
    _assert_case_disjoint(validation_rows, outer_rows)
    device = _resolve_device(requested_device)
    inner_model, inner_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_inner_checkpoint.pt",
        rows=training_rows,
        device=device,
    )
    outer_model, outer_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_checkpoint.pt",
        rows=outer_rows,
        device=device,
    )
    if inner_config != outer_config:
        raise ValueError("same-plan affinity expansion configs differ")
    training_views = _encode_affinity_views(
        inner_model,
        training_rows,
        batch_size=32,
        device=device,
    )
    validation_views = _encode_affinity_views(
        inner_model,
        validation_rows,
        batch_size=32,
        device=device,
    )
    outer_views = _encode_affinity_views(
        outer_model,
        outer_rows,
        batch_size=32,
        device=device,
    )
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    affinity = SamePlanAffinityHead(
        hidden_dim=config.hidden_dim,
        feature_mode=config.feature_mode,
    ).to(device)
    history = _fit_affinity(
        affinity,
        training_views,
        validation_views=validation_views,
        config=config,
        device=device,
        seed=seed,
    )
    inner_pair_metrics = _pair_metrics(
        affinity,
        validation_views,
        batch_size=config.batch_size,
        device=device,
    )
    outer_pair_metrics = _pair_metrics(
        affinity,
        outer_views,
        batch_size=config.batch_size,
        device=device,
    )
    inner_plans = _generate_beam_examples(
        inner_model,
        validation_rows,
        beam_width=config.beam_width,
        batch_size=32,
        device=device,
        feature_mode="RELATIONAL",
    )
    outer_plans = _generate_beam_examples(
        outer_model,
        outer_rows,
        beam_width=config.beam_width,
        batch_size=32,
        device=device,
        feature_mode="RELATIONAL",
    )
    base_selection = select_structured_energy_weights(inner_plans)
    base_weights = base_selection["weights"]
    inner_probabilities = _affinity_probability_map(
        affinity,
        validation_views,
        batch_size=config.batch_size,
        device=device,
    )
    outer_probabilities = _affinity_probability_map(
        affinity,
        outer_views,
        batch_size=config.batch_size,
        device=device,
    )
    affinity_selection = _select_affinity_energy_weights(
        inner_plans,
        probability_by_key=inner_probabilities,
        base_weights=base_weights,
    )
    pair_weights = affinity_selection["weights"]
    inner_scores = score_affinity_plans(
        inner_plans,
        probability_by_key=inner_probabilities,
        base_weights=base_weights,
        pair_weights=pair_weights,
    )
    threshold = _choose_zero_error_threshold(inner_scores)
    outer_scores = score_affinity_plans(
        outer_plans,
        probability_by_key=outer_probabilities,
        base_weights=base_weights,
        pair_weights=pair_weights,
    )
    for row in outer_scores:
        row["acceptance_threshold"] = threshold
        row["automatic"] = bool(
            row["raw_automatic"]
            and float(row["confidence"]) >= threshold
        )
        row["unsafe_automatic"] = bool(
            row["automatic"] and not row["raw_complete_exact"]
        )
        row["effective_decision"] = (
            row["selected_decision"] if row["automatic"] else "ABSTAIN"
        )
    root.mkdir(parents=True)
    checkpoint_path = root / f"fold_{outer_fold}_affinity.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_SAME_PLAN_AFFINITY",
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "config": asdict(config),
            "base_energy_weights": asdict(base_weights),
            "pair_energy_weights": pair_weights,
            "state_dict": affinity.state_dict(),
        },
        checkpoint_path,
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, outer_scores)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SAME_PLAN_AFFINITY_CANARY",
        "outer_fold": outer_fold,
        "inner_validation_fold": inner_fold,
        "config": asdict(config),
        "training_count": len(training_views),
        "validation_count": len(validation_views),
        "outer_count": len(outer_views),
        "parameter_count": parameter_count(affinity),
        "history": history,
        "inner_pair_metrics": inner_pair_metrics,
        "outer_pair_metrics": outer_pair_metrics,
        "base_energy_weights": asdict(base_weights),
        "pair_energy_weights": pair_weights,
        "pair_weight_selection": affinity_selection["summary"],
        "acceptance_threshold": threshold,
        "inner_metrics": _reranker_metrics(inner_scores),
        "metrics": _reranker_metrics(outer_scores),
        "feature_uses_truth": False,
        "pair_label_contract": (
            "Training labels mark two same-source candidate Roads positive "
            "only when both belong to the complete target Road set. Labels "
            "never enter candidate embeddings, relations or plan features."
        ),
        "business_boundary": (
            "Same-plan affinity is an auxiliary co-membership score, not a "
            "T06 path corridor class or deterministic carrier rule."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "This is one-fold pair-affinity canary; full OOF, two-seed "
            "agreement and final RoadGraph safety are not passed."
        ),
        "read_summary": read_summary,
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "expansion_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "checkpoint": _input_record(checkpoint_path),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _encode_affinity_views(
    model: Any,
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[_AffinityView]:
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            values = rows[start : start + batch_size]
            batch = _batch_tensors(
                values,
                feature_source="oof",
                device=device,
                cardinality_count=model.cardinality_count,
                road_relation_dim=model.road_relation_dim,
            )
            outputs = _forward_model(model, batch)
            signals = torch.stack(
                (
                    torch.sigmoid(outputs["member_logits"]),
                    1.0
                    - torch.softmax(
                        outputs["ownership_logits"],
                        dim=-1,
                    )[..., 0],
                    1.0
                    - torch.softmax(
                        outputs["business_role_logits"],
                        dim=-1,
                    )[..., 0],
                ),
                dim=-1,
            )
            for index, row in enumerate(values):
                length = len(row.road_ids)
                target = torch.zeros(length, dtype=torch.bool)
                target[list(row.target_indices)] = True
                sources = row.sources
                same_source = torch.tensor(
                    [
                        [
                            sources[left] == sources[right]
                            for right in range(length)
                        ]
                        for left in range(length)
                    ],
                    dtype=torch.bool,
                )
                result.append(
                    _AffinityView(
                        row=row,
                        candidate_embeddings=outputs[
                            "candidate_encoded"
                        ][index, :length]
                        .detach()
                        .to("cpu")
                        .contiguous(),
                        candidate_signals=signals[index, :length]
                        .detach()
                        .to("cpu")
                        .contiguous(),
                        road_relations=batch["road_relations"][
                            index, :length, :length
                        ]
                        .detach()
                        .to("cpu")
                        .contiguous(),
                        same_source=same_source,
                        target_mask=target,
                    )
                )
            del batch, outputs
    return result


def _collate_views(
    views: Sequence[_AffinityView],
    *,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    count = max(view.candidate_embeddings.shape[0] for view in views)
    embeddings = torch.zeros(
        len(views), count, 128, dtype=torch.float32, device=device
    )
    signals = torch.zeros(
        len(views), count, 3, dtype=torch.float32, device=device
    )
    relations = torch.zeros(
        len(views), count, count, 13, dtype=torch.float32, device=device
    )
    valid = torch.zeros(
        len(views), count, dtype=torch.bool, device=device
    )
    same_source = torch.zeros(
        len(views), count, count, dtype=torch.bool, device=device
    )
    targets = torch.zeros_like(valid)
    for index, view in enumerate(views):
        length = view.candidate_embeddings.shape[0]
        embeddings[index, :length] = view.candidate_embeddings.to(device)
        signals[index, :length] = view.candidate_signals.to(device)
        relations[index, :length, :length] = view.road_relations.to(device)
        valid[index, :length] = True
        same_source[index, :length, :length] = view.same_source.to(device)
        targets[index, :length] = view.target_mask.to(device)
    pair_valid = (
        valid.unsqueeze(1)
        & valid.unsqueeze(2)
        & same_source
        & torch.triu(
            torch.ones(count, count, dtype=torch.bool, device=device),
            diagonal=1,
        ).unsqueeze(0)
    )
    pair_targets = (
        targets.unsqueeze(1) & targets.unsqueeze(2) & pair_valid
    )
    return {
        "embeddings": embeddings,
        "signals": signals,
        "relations": relations,
        "valid": valid,
        "pair_valid": pair_valid,
        "pair_targets": pair_targets,
        "weights": torch.tensor(
            [view.row.sample_weight for view in views],
            dtype=torch.float32,
            device=device,
        ),
    }


def _positive_weight(views: Sequence[_AffinityView], *, cap: float) -> float:
    positive = 0
    total = 0
    for view in views:
        length = len(view.row.road_ids)
        upper = torch.triu(
            torch.ones(length, length, dtype=torch.bool),
            diagonal=1,
        )
        valid = upper & view.same_source
        target = (
            view.target_mask.unsqueeze(0)
            & view.target_mask.unsqueeze(1)
            & valid
        )
        positive += int(target.sum().item())
        total += int(valid.sum().item())
    if positive < 1:
        raise ValueError("same-plan affinity has no positive pairs")
    return min(cap, (total - positive) / positive)


def _fit_affinity(
    model: SamePlanAffinityHead,
    training: Sequence[_AffinityView],
    *,
    validation_views: Sequence[_AffinityView],
    config: SamePlanAffinityConfig,
    device: torch.device,
    seed: int,
) -> list[dict[str, float]]:
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    positive_weight = _positive_weight(
        training,
        cap=config.positive_weight_cap,
    )
    best_state = copy.deepcopy(model.state_dict())
    best_loss = math.inf
    stale = 0
    history = []
    for epoch in range(1, config.epochs + 1):
        order = list(training)
        random.Random(seed + epoch).shuffle(order)
        model.train()
        total = 0.0
        weight_total = 0.0
        for start in range(0, len(order), config.batch_size):
            views = order[start : start + config.batch_size]
            batch = _collate_views(views, device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(
                batch["embeddings"],
                batch["signals"],
                batch["relations"],
                batch["valid"],
            )
            raw = F.binary_cross_entropy_with_logits(
                logits,
                batch["pair_targets"].to(logits.dtype),
                reduction="none",
                pos_weight=torch.tensor(
                    positive_weight,
                    dtype=logits.dtype,
                    device=device,
                ),
            )
            per_row = (
                raw * batch["pair_valid"]
            ).sum(dim=(1, 2)) / batch["pair_valid"].sum(
                dim=(1, 2)
            ).clamp_min(1)
            loss = (per_row * batch["weights"]).sum() / batch[
                "weights"
            ].sum().clamp_min(1e-6)
            if not bool(torch.isfinite(loss)):
                raise RuntimeError("same-plan affinity loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            total += float(
                (per_row.detach() * batch["weights"]).sum().item()
            )
            weight_total += float(batch["weights"].sum().item())
        train_loss = total / max(weight_total, 1e-9)
        validation_loss = _evaluate_affinity_loss(
            model,
            validation_views,
            positive_weight=positive_weight,
            batch_size=config.batch_size,
            device=device,
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
                "positive_weight": positive_weight,
            }
        )
        if validation_loss < best_loss - 1e-8:
            best_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    return history


def _evaluate_affinity_loss(
    model: SamePlanAffinityHead,
    views: Sequence[_AffinityView],
    *,
    positive_weight: float,
    batch_size: int,
    device: torch.device,
) -> float:
    total = 0.0
    weight_total = 0.0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(views), batch_size):
            values = views[start : start + batch_size]
            batch = _collate_views(values, device=device)
            logits = model(
                batch["embeddings"],
                batch["signals"],
                batch["relations"],
                batch["valid"],
            )
            raw = F.binary_cross_entropy_with_logits(
                logits,
                batch["pair_targets"].to(logits.dtype),
                reduction="none",
                pos_weight=torch.tensor(
                    positive_weight,
                    dtype=logits.dtype,
                    device=device,
                ),
            )
            per_row = (
                raw * batch["pair_valid"]
            ).sum(dim=(1, 2)) / batch["pair_valid"].sum(
                dim=(1, 2)
            ).clamp_min(1)
            total += float((per_row * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _affinity_probability_map(
    model: SamePlanAffinityHead,
    views: Sequence[_AffinityView],
    *,
    batch_size: int,
    device: torch.device,
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    model.eval()
    with torch.no_grad():
        for start in range(0, len(views), batch_size):
            values = views[start : start + batch_size]
            batch = _collate_views(values, device=device)
            probabilities = torch.sigmoid(
                model(
                    batch["embeddings"],
                    batch["signals"],
                    batch["relations"],
                    batch["valid"],
                )
            )
            for index, view in enumerate(values):
                length = len(view.row.road_ids)
                result[(view.row.case_key, view.row.segment_id)] = {
                    "probabilities": probabilities[
                        index, :length, :length
                    ]
                    .detach()
                    .to("cpu"),
                    "sources": view.row.sources,
                }
    return result


def _pair_metrics(
    model: SamePlanAffinityHead,
    views: Sequence[_AffinityView],
    *,
    batch_size: int,
    device: torch.device,
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = true_negative = 0
    probability_map = _affinity_probability_map(
        model,
        views,
        batch_size=batch_size,
        device=device,
    )
    for view in views:
        value = probability_map[(view.row.case_key, view.row.segment_id)]
        probabilities = value["probabilities"]
        length = len(view.row.road_ids)
        valid = torch.triu(
            torch.ones(length, length, dtype=torch.bool),
            diagonal=1,
        ) & view.same_source
        target = (
            view.target_mask.unsqueeze(0)
            & view.target_mask.unsqueeze(1)
            & valid
        )
        predicted = probabilities >= 0.5
        true_positive += int((predicted & target & valid).sum().item())
        false_positive += int((predicted & ~target & valid).sum().item())
        false_negative += int((~predicted & target & valid).sum().item())
        true_negative += int((~predicted & ~target & valid).sum().item())
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": precision,
        "recall": recall,
        "f1": (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        ),
    }


def _select_affinity_energy_weights(
    examples: Sequence[_BeamPlanExample],
    *,
    probability_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    base_weights: StructuredEnergyWeights,
) -> dict[str, Any]:
    candidates = (0.0, 0.5, 1.0, 2.0, 4.0)
    cardinality_gates = (0, 3, 5, 10)
    total_weight = sum(example.row.sample_weight for example in examples)
    long_count = sum(
        len(example.row.target_indices) >= 10 for example in examples
    )
    rows = []
    for inside, boundary, minimum_cardinality in itertools.product(
        candidates,
        candidates,
        cardinality_gates,
    ):
        correct_weight = 0.0
        correct_count = 0
        long_correct = 0
        for example in examples:
            selected = _select_plan_with_affinity(
                example,
                probability_by_key=probability_by_key,
                base_weights=base_weights,
                pair_weights=(
                    inside,
                    boundary,
                    minimum_cardinality,
                ),
            )
            correct = selected in example.acceptable_indices
            correct_weight += correct * example.row.sample_weight
            correct_count += int(correct)
            long_correct += int(
                correct and len(example.row.target_indices) >= 10
            )
        rows.append(
            {
                "inside_weight": inside,
                "boundary_weight": boundary,
                "minimum_selected_cardinality": minimum_cardinality,
                "weighted_accuracy": correct_weight
                / max(total_weight, 1e-9),
                "accuracy": correct_count / len(examples),
                "long_10_plus_accuracy": long_correct / max(long_count, 1),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["weighted_accuracy"],
            -row["long_10_plus_accuracy"],
            -row["accuracy"],
            row["inside_weight"] + row["boundary_weight"],
            -row["minimum_selected_cardinality"],
            row["inside_weight"],
            row["boundary_weight"],
        )
    )
    selected = rows[0]
    return {
        "weights": {
            "inside": float(selected["inside_weight"]),
            "boundary": float(selected["boundary_weight"]),
            "minimum_selected_cardinality": int(
                selected["minimum_selected_cardinality"]
            ),
        },
        "summary": {
            "candidate_count": len(rows),
            "top_candidates": rows[:10],
        },
    }


def score_affinity_plans(
    examples: Sequence[_BeamPlanExample],
    *,
    probability_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    base_weights: StructuredEnergyWeights,
    pair_weights: Mapping[str, float],
) -> list[dict[str, Any]]:
    result = []
    for example in examples:
        energies = _plan_energies(
            example,
            probability_by_key=probability_by_key,
            base_weights=base_weights,
            pair_weights=(
                float(pair_weights["inside"]),
                float(pair_weights["boundary"]),
                int(pair_weights["minimum_selected_cardinality"]),
            ),
        )
        probabilities = torch.softmax(
            torch.tensor(energies, dtype=torch.float64),
            dim=0,
        )
        top_values, top_indices = probabilities.topk(
            min(2, len(energies))
        )
        offset = int(top_indices[0].item())
        selected_index = offset + 1
        margin = (
            float((top_values[0] - top_values[1]).item())
            if len(top_values) > 1
            else float(top_values[0].item())
        )
        confidence = float(top_values[0].item()) * max(0.0, margin)
        decision_index = example.proposal_decisions[selected_index]
        selected = example.proposal_selected_indices[selected_index]
        correct = selected_index in example.acceptable_indices
        result.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": example.row.case_key,
                "segment_id": example.row.segment_id,
                "fold": example.row.fold,
                "truth_decision": DECISIONS[example.row.decision],
                "truth_cardinality": len(example.row.target_indices),
                "target_reachable": example.target_reachable,
                "proposal_count": len(energies),
                "selected_proposal_index": selected_index,
                "selected_decision": DECISIONS[decision_index],
                "selected_road_ids": [
                    example.row.road_ids[index] for index in selected
                ],
                "selected_cardinality": len(selected),
                "selection_label_correct": correct,
                "raw_complete_exact": correct,
                "release_eligible": bool(
                    example.row.oof_anchor_release_ready
                ),
                "raw_automatic": bool(
                    example.row.oof_anchor_release_ready
                ),
                "confidence": confidence,
            }
        )
    return result


def _select_plan_with_affinity(
    example: _BeamPlanExample,
    *,
    probability_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    base_weights: StructuredEnergyWeights,
    pair_weights: tuple[float, float, int],
) -> int:
    energies = _plan_energies(
        example,
        probability_by_key=probability_by_key,
        base_weights=base_weights,
        pair_weights=pair_weights,
    )
    return max(
        range(1, len(example.proposal_features)),
        key=lambda index: (energies[index - 1], -index),
    )


def _plan_energies(
    example: _BeamPlanExample,
    *,
    probability_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    base_weights: StructuredEnergyWeights,
    pair_weights: tuple[float, float, int],
) -> list[float]:
    value = probability_by_key[
        (example.row.case_key, example.row.segment_id)
    ]
    pair_probabilities = value["probabilities"]
    sources = value["sources"]
    result = []
    for index in range(1, len(example.proposal_features)):
        selected = example.proposal_selected_indices[index]
        decision = example.proposal_decisions[index]
        source = "SWSD" if decision == 0 else "RCSD"
        source_indices = [
            candidate
            for candidate, candidate_source in enumerate(sources)
            if candidate_source == source
        ]
        inside, boundary = plan_affinity_terms(
            pair_probabilities,
            selected_indices=selected,
            source_indices=source_indices,
            minimum_selected_cardinality=pair_weights[2],
        )
        result.append(
            proposal_energy(
                example.proposal_features[index],
                weights=base_weights,
            )
            + pair_weights[0] * inside
            + pair_weights[1] * boundary
        )
    return result


def plan_affinity_terms(
    pair_probabilities: torch.Tensor,
    *,
    selected_indices: Sequence[int],
    source_indices: Sequence[int],
    minimum_selected_cardinality: int = 0,
) -> tuple[float, float]:
    selected = list(selected_indices)
    if len(selected) < minimum_selected_cardinality:
        return 0.0, 0.0
    selected_set = set(selected)
    excluded = [
        index for index in source_indices if index not in selected_set
    ]
    inside_values = [
        float(pair_probabilities[left, right])
        for offset, left in enumerate(selected)
        for right in selected[offset + 1 :]
    ]
    boundary_values = [
        1.0 - float(pair_probabilities[left, right])
        for left in selected
        for right in excluded
    ]
    inside = (
        sum(math.log(max(value, 1e-6)) for value in inside_values)
        / len(inside_values)
        if inside_values
        else 0.0
    )
    boundary = (
        sum(math.log(max(value, 1e-6)) for value in boundary_values)
        / len(boundary_values)
        if boundary_values
        else 0.0
    )
    return inside, boundary


def _choose_zero_error_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe = [
        float(row["confidence"])
        for row in rows
        if bool(row["raw_automatic"])
        and not bool(row["raw_complete_exact"])
    ]
    return math.nextafter(max(unsafe), math.inf) if unsafe else 0.0


def _read_json(path: Path) -> dict[str, Any]:
    import json

    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


__all__ = [
    "SamePlanAffinityConfig",
    "SamePlanAffinityHead",
    "plan_affinity_terms",
    "run_same_plan_affinity_canary",
    "score_affinity_plans",
]
