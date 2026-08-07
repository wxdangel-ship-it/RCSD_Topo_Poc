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
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessCardinalityDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_set_training import (
    OrdinaryAccessSetExample,
    _batch_tensors,
    ordinary_access_set_metrics,
    read_ordinary_access_set_examples,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class OrdinaryAccessCardinalityTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    attention_heads: int = 4
    attention_layers: int = 1
    max_cardinality: int = 16
    dropout: float = 0.1
    batch_size: int = 48
    max_epochs: int = 80
    patience: int = 12
    learning_rate: float = 4e-4
    weight_decay: float = 2e-4
    negative_loss_weight: float = 1.0
    cardinality_loss_weight: float = 1.0
    ranking_loss_weight: float = 0.25
    ranking_margin: float = 1.0
    teacher_training_loss_weight: float = 0.5
    oof_training_loss_weight: float = 1.0
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.context_dim,
            self.attention_heads,
            self.attention_layers,
            self.max_cardinality,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("access cardinality training dimensions are invalid")
        if self.hidden_dim % self.attention_heads:
            raise ValueError("access hidden dimension must divide attention heads")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("access cardinality dropout is invalid")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise ValueError("access cardinality optimizer config is invalid")
        if min(
            self.negative_loss_weight,
            self.cardinality_loss_weight,
            self.ranking_loss_weight,
            self.ranking_margin,
            self.teacher_training_loss_weight,
            self.oof_training_loss_weight,
        ) < 0.0:
            raise ValueError("access cardinality loss config is invalid")
        if (
            self.teacher_training_loss_weight
            + self.oof_training_loss_weight
            <= 0.0
        ):
            raise ValueError("access training views cannot both be disabled")


def run_ordinary_access_cardinality_strict_nested_oof(
    *,
    conditioned_store_root: Path,
    collection_label_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryAccessCardinalityTrainingConfig = (
        OrdinaryAccessCardinalityTrainingConfig()
    ),
    requested_device: str = "cuda",
) -> Path:
    """Train explicit cardinality plus top-k member decoding with strict OOF."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(conditioned_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(collection_label_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples, read_summary = read_ordinary_access_set_examples(
        store,
        label_root,
    )
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("access cardinality strict OOF needs three folds")
    target_max = max(
        len(indices)
        for row in examples
        for indices in row.acceptable_index_sets
    )
    if target_max > config.max_cardinality:
        raise ValueError("access target cardinality exceeds model capacity")
    feature_dim = len(examples[0].teacher_features[0])
    device = _resolve_device(requested_device)
    predictions = []
    fold_summaries = []
    model_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
        inner_training = [
            row
            for row in examples
            if row.fold not in {outer_fold, inner_fold}
        ]
        inner_validation = [
            row for row in examples if row.fold == inner_fold
        ]
        outer_training = [
            row for row in examples if row.fold != outer_fold
        ]
        outer_validation = [
            row for row in examples if row.fold == outer_fold
        ]
        _assert_case_disjoint(inner_training, inner_validation)
        _assert_case_disjoint(outer_training, outer_validation)
        tuning = _fit_model(
            inner_training,
            inner_validation,
            feature_dim=feature_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
        )
        final = _fit_fixed_epochs(
            outer_training,
            feature_dim=feature_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_structured_access_examples(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        acceptance_threshold = choose_zero_error_structured_threshold(
            inner_scores
        )
        teacher_scores = score_structured_access_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_structured_access_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        teacher_by_key = {_score_key(row): row for row in teacher_scores}
        decoded = []
        for score in oof_scores:
            teacher = teacher_by_key[_score_key(score)]
            row = dict(score)
            row["teacher_predicted_proposal_ids"] = list(
                teacher["predicted_proposal_ids"]
            )
            row["teacher_exact"] = bool(teacher["raw_set_exact"])
            row["acceptance_threshold"] = acceptance_threshold
            row["automatic"] = bool(
                row["release_eligible"]
                and float(row["set_confidence"]) >= acceptance_threshold
            )
            row["unsafe_automatic"] = bool(
                row["automatic"] and not row["raw_set_exact"]
            )
            row["effective_decision"] = (
                "SELECT_COMPLETE_ACCESS_SET"
                if row["automatic"]
                else "ABSTAIN"
            )
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
            decoded.append(row)
        predictions.extend(decoded)
        inner_checkpoint = root / f"fold_{outer_fold}_inner_checkpoint.pt"
        outer_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            inner_checkpoint,
            tuning["model"],
            config=config,
            feature_dim=feature_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            outer_checkpoint,
            final["model"],
            config=config,
            feature_dim=feature_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "inner_train_count": len(inner_training),
            "inner_validation_count": len(inner_validation),
            "outer_train_count": len(outer_training),
            "outer_validation_count": len(outer_validation),
            "best_epoch": tuning["best_epoch"],
            "best_validation_loss": tuning["best_validation_loss"],
            "acceptance_threshold": acceptance_threshold,
            "metrics": ordinary_access_set_metrics(decoded),
            "cardinality_metrics": cardinality_metrics(decoded),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)

    predictions.sort(key=_score_key)
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = ordinary_access_set_metrics(predictions)
    cardinality = cardinality_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_CARDINALITY_TOPK_STRICT_NESTED_OOF",
        "model_scope": (
            "Set Transformer encodes all candidate Road/Node access proposals. "
            "A cardinality head predicts the required collection size and a "
            "member head ranks proposals; decoding selects exactly top-k."
        ),
        "training_condition": (
            "Training combines independently supervised teacher conditions "
            "with strict OOF model-derived upstream conditions. Early stopping "
            "uses only the OOF condition view."
        ),
        "release_constraint": (
            "The structured access head cannot change anchor or carrier output. "
            "Automatic release needs safe upstream OOF conditions and an "
            "inner-only zero-error confidence threshold."
        ),
        "feature_dim": feature_dim,
        "target_max_cardinality": target_max,
        "parameter_count": model_parameters,
        "config": asdict(config),
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "example_count": len(examples),
        "fold_count": len(folds),
        "read_summary": read_summary,
        "metrics": metrics,
        "cardinality_metrics": cardinality,
        "folds": fold_summaries,
        "conditioned_store_summary": _input_record(store / "summary.json"),
        "collection_label_summary": _input_record(label_root / "summary.json"),
        "oof_predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "strict_case_oof": True,
        "decision": (
            "GO"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def structured_multi_solution_loss(
    member_logits: torch.Tensor,
    cardinality_logits: torch.Tensor,
    acceptable_index_sets: Sequence[Sequence[int]],
    *,
    negative_loss_weight: float = 1.0,
    cardinality_loss_weight: float = 1.0,
    ranking_loss_weight: float = 0.25,
    ranking_margin: float = 1.0,
) -> torch.Tensor:
    if member_logits.ndim != 1 or member_logits.numel() < 1:
        raise ValueError("access member logits are invalid")
    if cardinality_logits.ndim != 1 or cardinality_logits.numel() < 1:
        raise ValueError("access cardinality logits are invalid")
    losses = []
    for acceptable in acceptable_index_sets:
        indices = sorted({int(value) for value in acceptable})
        if not indices or indices[0] < 0 or indices[-1] >= member_logits.numel():
            raise ValueError("access target indices are invalid")
        if len(indices) > cardinality_logits.numel():
            raise ValueError("access target cardinality is invalid")
        positive_mask = torch.zeros_like(member_logits, dtype=torch.bool)
        positive_mask[indices] = True
        positive = F.softplus(-member_logits[positive_mask]).mean()
        if (~positive_mask).any():
            negative = F.softplus(member_logits[~positive_mask]).mean()
            rank_gap = (
                member_logits[positive_mask].min()
                - member_logits[~positive_mask].max()
            )
            ranking = F.softplus(
                member_logits.new_tensor(ranking_margin) - rank_gap
            )
        else:
            negative = member_logits.new_zeros(())
            ranking = member_logits.new_zeros(())
        cardinality = F.cross_entropy(
            cardinality_logits.unsqueeze(0),
            cardinality_logits.new_tensor(
                [len(indices) - 1],
                dtype=torch.long,
            ),
        )
        losses.append(
            positive
            + negative_loss_weight * negative
            + cardinality_loss_weight * cardinality
            + ranking_loss_weight * ranking
        )
    if not losses:
        raise ValueError("access set has no acceptable collection")
    return torch.stack(losses).min()


def predict_structured_access_outputs(
    model: TargetAOrdinaryAccessCardinalityDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("access feature source is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            values, mask, _ = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
            )
            member_logits, cardinality_logits = model(values, mask)
            cardinality_probabilities = torch.softmax(
                cardinality_logits,
                dim=-1,
            )
            member_probabilities = torch.sigmoid(member_logits)
            for index, row in enumerate(rows):
                length = len(row.proposal_ids)
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "junction_id": row.junction_id,
                        "fold": row.fold,
                        "feature_source": feature_source,
                        "proposal_ids": list(row.proposal_ids),
                        "road_ids": list(row.road_ids),
                        "operations": list(row.operations),
                        "fractions": list(row.fractions),
                        "member_logits": [
                            float(value)
                            for value in member_logits[index, :length].tolist()
                        ],
                        "member_probabilities": [
                            float(value)
                            for value in member_probabilities[
                                index, :length
                            ].tolist()
                        ],
                        "cardinality_probabilities": [
                            float(value)
                            for value in cardinality_probabilities[
                                index, : min(length, model.max_cardinality)
                            ].tolist()
                        ],
                        "acceptable_index_sets": [
                            list(values)
                            for values in row.acceptable_index_sets
                        ],
                        "oof_anchor_release_ready": (
                            row.oof_anchor_release_ready
                        ),
                        "upstream_plan_release_blocked": (
                            row.upstream_plan_release_blocked
                        ),
                    }
                )
    return result


def decode_structured_access_outputs(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        member_logits = [float(value) for value in source["member_logits"]]
        member_probabilities = [
            float(value) for value in source["member_probabilities"]
        ]
        cardinality_probabilities = [
            float(value) for value in source["cardinality_probabilities"]
        ]
        cardinality_index = max(
            range(len(cardinality_probabilities)),
            key=cardinality_probabilities.__getitem__,
        )
        cardinality = cardinality_index + 1
        ranked = sorted(
            range(len(member_logits)),
            key=lambda index: (-member_logits[index], index),
        )
        predicted = tuple(sorted(ranked[:cardinality]))
        acceptable = {
            tuple(sorted(int(value) for value in values))
            for values in source["acceptable_index_sets"]
        }
        selected = set(predicted)
        member_confidence = min(
            [
                probability if index in selected else 1.0 - probability
                for index, probability in enumerate(member_probabilities)
            ]
        )
        cardinality_confidence = cardinality_probabilities[
            cardinality_index
        ]
        row = dict(source)
        row.update(
            {
                "predicted_indices": list(predicted),
                "predicted_proposal_ids": [
                    source["proposal_ids"][index] for index in predicted
                ],
                "predicted_road_ids": [
                    source["road_ids"][index] for index in predicted
                ],
                "raw_set_exact": predicted in acceptable,
                "set_f1": max(
                    _set_f1(selected, set(values)) for values in acceptable
                ),
                "set_confidence": min(
                    member_confidence,
                    cardinality_confidence,
                ),
                "member_confidence": member_confidence,
                "cardinality_confidence": cardinality_confidence,
                "predicted_cardinality": cardinality,
                "acceptable_cardinalities": sorted(
                    {len(values) for values in acceptable}
                ),
                "cardinality_exact": cardinality
                in {len(values) for values in acceptable},
                "release_eligible": bool(
                    source["oof_anchor_release_ready"]
                    and not source["upstream_plan_release_blocked"]
                ),
            }
        )
        result.append(row)
    return result


def score_structured_access_examples(
    model: TargetAOrdinaryAccessCardinalityDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    return decode_structured_access_outputs(
        predict_structured_access_outputs(
            model,
            examples,
            feature_source=feature_source,
            batch_size=batch_size,
            device=device,
        )
    )


def choose_zero_error_structured_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    eligible = [row for row in rows if bool(row["release_eligible"])]
    unsafe = [
        float(row["set_confidence"])
        for row in eligible
        if not bool(row["raw_set_exact"])
    ]
    if not eligible or not unsafe:
        return 1.000001
    return min(1.000001, max(unsafe) + 1e-7)


def cardinality_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    exact = sum(bool(row["cardinality_exact"]) for row in rows)
    by_expected: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        cardinalities = [int(value) for value in row["acceptable_cardinalities"]]
        expected = min(cardinalities)
        by_expected.setdefault(expected, []).append(row)
    return {
        "count": count,
        "exact_count": exact,
        "exact_rate": exact / max(count, 1),
        "mean_predicted_cardinality": sum(
            int(row["predicted_cardinality"]) for row in rows
        )
        / max(count, 1),
        "by_expected_cardinality": {
            str(expected): {
                "count": len(values),
                "exact_rate": sum(
                    bool(row["cardinality_exact"]) for row in values
                )
                / len(values),
                "mean_predicted": sum(
                    int(row["predicted_cardinality"]) for row in values
                )
                / len(values),
            }
            for expected, values in sorted(by_expected.items())
        },
    }


def _fit_model(
    training: Sequence[OrdinaryAccessSetExample],
    validation: Sequence[OrdinaryAccessSetExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessCardinalityTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_loss = float("inf")
    best_epoch = 1
    best_state = copy.deepcopy(model.state_dict())
    stale = 0
    history = []
    for epoch in range(1, config.max_epochs + 1):
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            config=config,
            device=device,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
        if stale >= config.patience:
            break
    model.load_state_dict(best_state)
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_fixed_epochs(
    training: Sequence[OrdinaryAccessSetExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessCardinalityTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history = []
    for epoch in range(1, epoch_count + 1):
        loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        history.append({"epoch": float(epoch), "train_loss": loss})
    return {"model": model, "history": history}


def _new_model(
    feature_dim: int,
    config: OrdinaryAccessCardinalityTrainingConfig,
    device: torch.device,
) -> TargetAOrdinaryAccessCardinalityDecoder:
    return TargetAOrdinaryAccessCardinalityDecoder(
        feature_dim=feature_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        attention_heads=config.attention_heads,
        attention_layers=config.attention_layers,
        max_cardinality=config.max_cardinality,
        dropout=config.dropout,
    ).to(device)


def _train_epoch(
    model: TargetAOrdinaryAccessCardinalityDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: OrdinaryAccessCardinalityTrainingConfig,
    device: torch.device,
    seed: int,
) -> float:
    model.train()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    weight_total = 0.0
    for start in range(0, len(order), config.batch_size):
        rows = [
            examples[index]
            for index in order[start : start + config.batch_size]
        ]
        teacher_values, mask, weights = _batch_tensors(
            rows,
            feature_source="teacher",
            device=device,
        )
        oof_values, oof_mask, _ = _batch_tensors(
            rows,
            feature_source="oof",
            device=device,
        )
        if not torch.equal(mask, oof_mask):
            raise ValueError("teacher and OOF access candidate masks differ")
        optimizer.zero_grad(set_to_none=True)
        teacher_raw = _batch_raw_losses(
            model,
            teacher_values,
            mask,
            rows,
            config=config,
        )
        oof_raw = _batch_raw_losses(
            model,
            oof_values,
            mask,
            rows,
            config=config,
        )
        view_weight = (
            config.teacher_training_loss_weight
            + config.oof_training_loss_weight
        )
        raw = (
            config.teacher_training_loss_weight * teacher_raw
            + config.oof_training_loss_weight * oof_raw
        ) / view_weight
        loss = (raw * weights).sum() / weights.sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * weights).sum().item())
        weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryAccessCardinalityDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    config: OrdinaryAccessCardinalityTrainingConfig,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), config.batch_size):
            rows = examples[start : start + config.batch_size]
            values, mask, weights = _batch_tensors(
                rows,
                feature_source="oof",
                device=device,
            )
            raw = _batch_raw_losses(
                model,
                values,
                mask,
                rows,
                config=config,
            )
            total += float((raw * weights).sum().item())
            weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _batch_raw_losses(
    model: TargetAOrdinaryAccessCardinalityDecoder,
    values: torch.Tensor,
    mask: torch.Tensor,
    rows: Sequence[OrdinaryAccessSetExample],
    *,
    config: OrdinaryAccessCardinalityTrainingConfig,
) -> torch.Tensor:
    member_logits, cardinality_logits = model(values, mask)
    return torch.stack(
        [
            structured_multi_solution_loss(
                member_logits[index, : len(row.proposal_ids)],
                cardinality_logits[index],
                row.acceptable_index_sets,
                negative_loss_weight=config.negative_loss_weight,
                cardinality_loss_weight=config.cardinality_loss_weight,
                ranking_loss_weight=config.ranking_loss_weight,
                ranking_margin=config.ranking_margin,
            )
            for index, row in enumerate(rows)
        ]
    )


def _assert_case_disjoint(
    training: Sequence[OrdinaryAccessSetExample],
    validation: Sequence[OrdinaryAccessSetExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(f"strict access Case split overlaps: {sorted(overlap)}")


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if requested == "cuda":
        raise RuntimeError("CUDA was requested but is unavailable")
    return torch.device(requested)


def _score_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junction_id"]),
    )


def _set_f1(predicted: set[int], expected: set[int]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    overlap = len(predicted & expected)
    return 2.0 * overlap / (len(predicted) + len(expected))


def _save_checkpoint(
    path: Path,
    model: TargetAOrdinaryAccessCardinalityDecoder,
    *,
    config: OrdinaryAccessCardinalityTrainingConfig,
    feature_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_ACCESS_CARDINALITY_TOPK_DECODER",
            "config": asdict(config),
            "feature_dim": feature_dim,
            "fold": fold,
            "inner_fold": inner_fold,
            "epoch_count": epoch_count,
            "state_dict": {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
            },
        },
        path,
    )


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "OrdinaryAccessCardinalityTrainingConfig",
    "cardinality_metrics",
    "decode_structured_access_outputs",
    "run_ordinary_access_cardinality_strict_nested_oof",
    "structured_multi_solution_loss",
]
