from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryUseRoadGraphDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    balanced_member_bce,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class OrdinaryUseRoadTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    graph_layers: int = 2
    num_heads: int = 4
    cardinality_count: int = 65
    dropout: float = 0.1
    batch_size: int = 32
    max_epochs: int = 120
    patience: int = 18
    learning_rate: float = 3e-4
    weight_decay: float = 2e-4
    cardinality_loss_weight: float = 0.75
    member_loss_weight: float = 2.0
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.context_dim,
            self.graph_layers,
            self.num_heads,
            self.cardinality_count,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary USE Road training config is invalid")
        if self.hidden_dim % self.num_heads:
            raise ValueError("ordinary USE Road heads do not divide hidden dim")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary USE Road dropout is invalid")


@dataclass(frozen=True)
class OrdinaryUseRoadExample:
    case_key: str
    segment_id: str
    fold: int
    object_features: tuple[float, ...]
    road_ids: tuple[str, ...]
    endpoint_ids: tuple[tuple[str, str], ...]
    teacher_features: tuple[tuple[float, ...], ...]
    oof_features: tuple[tuple[float, ...], ...]
    target_indices: tuple[int, ...]
    sample_weight: float
    oof_anchor_release_ready: bool


def run_ordinary_use_road_graph_strict_nested_oof(
    *,
    member_store_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryUseRoadTrainingConfig = OrdinaryUseRoadTrainingConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train the RCSD Road graph decoder conditional on USE_RCSD."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(member_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples, read_summary = read_ordinary_use_road_examples(store)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary USE Road strict OOF needs three folds")
    object_dim = len(examples[0].object_features)
    candidate_dim = len(examples[0].teacher_features[0])
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
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
        )
        final = _fit_fixed_epochs(
            outer_training,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_ordinary_use_road_examples(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        threshold = choose_zero_use_set_error_threshold(inner_scores)
        teacher_scores = score_ordinary_use_road_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_ordinary_use_road_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        teacher_by_key = {
            (row["case_key"], row["segment_id"]): row
            for row in teacher_scores
        }
        decoded = []
        for score in oof_scores:
            teacher = teacher_by_key[
                (score["case_key"], score["segment_id"])
            ]
            row = dict(score)
            row["teacher_road_set_exact"] = bool(
                teacher["road_set_exact"]
            )
            row["teacher_road_f1"] = float(teacher["road_f1"])
            row["acceptance_threshold"] = threshold
            row["conditional_automatic"] = bool(
                row["release_eligible"]
                and row["selected_component_count"] == 1
                and float(row["confidence"]) >= threshold
            )
            row["unsafe_conditional_automatic"] = bool(
                row["conditional_automatic"] and not row["road_set_exact"]
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
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            outer_checkpoint,
            final["model"],
            config=config,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
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
            "acceptance_threshold": threshold,
            "metrics": ordinary_use_road_metrics(decoded),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(
            root / f"fold_{outer_fold}_summary.json",
            fold_summary,
        )
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = ordinary_use_road_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_USE_RCSD_ROAD_GRAPH_DECODER_STRICT_NESTED_OOF",
        "model_scope": (
            "Conditional on a prior USE_RCSD decision, a Road graph encoder "
            "uses shared endpoint adjacency and a structured decoder emits "
            "raw Road cardinality plus the complete RCSD Road set."
        ),
        "keep_contract": (
            "KEEP_SWSD does not enter this model. Its complete Road list is "
            "the frozen T01 Segment Road list and is expanded deterministically."
        ),
        "topology_contract": (
            "Selected Road component count is audited. Conditional automatic "
            "acceptance requires one connected raw-Road component; the global "
            "decoder will later resolve ownerless Junction connectivity Roads."
        ),
        "output_boundary": (
            "Road roles, access/split positions, Node recipes, and final "
            "ownership constraints remain downstream."
        ),
        "object_feature_dim": object_dim,
        "candidate_feature_dim": candidate_dim,
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
        "read_summary": read_summary,
        "example_count": len(examples),
        "fold_count": len(folds),
        "metrics": metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "release_gate": "NO_GO",
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_conditional_automatic_count"] == 0
            and metrics["conditional_automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "This is conditional USE_RCSD Road membership only; upstream "
            "carrier release, roles, access/Node, AdvanceRight, and global "
            "topology are not yet composed."
        ),
        "member_store_summary": _input_record(store / "summary.json"),
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(examples)
            and {
                (row["case_key"], row["segment_id"]) for row in predictions
            }
            == {(row.case_key, row.segment_id) for row in examples}
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary USE Road OOF coverage gate failed")
    return root


def read_ordinary_use_road_examples(
    root: Path,
) -> tuple[list[OrdinaryUseRoadExample], dict[str, int]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(store / "ordinary_road_member_labels.jsonl")
    }
    examples = []
    counts: Counter[str] = Counter()
    with (
        store / "ordinary_road_member_features.jsonl"
    ).open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            feature = json.loads(line)
            key = (str(feature["case_key"]), str(feature["segment_id"]))
            label = labels[key]
            if not bool(label["task_mask"]):
                counts["masked_member_task"] += 1
                continue
            if str(label["preferred_decision"]) != "USE_RCSD":
                counts["masked_keep_swsd"] += 1
                continue
            candidates = [
                row
                for row in feature["candidate_rows"]
                if str(row["source"]) == "RCSD"
            ]
            index_by_id = {
                str(row["road_id"]): index
                for index, row in enumerate(candidates)
            }
            target_indices = tuple(
                sorted(
                    index_by_id[str(road_id)]
                    for road_id in label["acceptable_road_ids"]
                )
            )
            if not target_indices:
                counts["masked_empty_target"] += 1
                continue
            examples.append(
                OrdinaryUseRoadExample(
                    case_key=key[0],
                    segment_id=key[1],
                    fold=int(label["fold"]),
                    object_features=tuple(
                        float(value)
                        for value in feature["object_feature_values"]
                    ),
                    road_ids=tuple(
                        str(row["road_id"]) for row in candidates
                    ),
                    endpoint_ids=tuple(
                        (
                            str(row["start_node_id"]),
                            str(row["end_node_id"]),
                        )
                        for row in candidates
                    ),
                    teacher_features=tuple(
                        tuple(
                            float(value)
                            for value in row["teacher_feature_values"]
                        )
                        for row in candidates
                    ),
                    oof_features=tuple(
                        tuple(
                            float(value)
                            for value in row["oof_feature_values"]
                        )
                        for row in candidates
                    ),
                    target_indices=target_indices,
                    sample_weight=float(label["sample_weight"]),
                    oof_anchor_release_ready=bool(
                        label["oof_anchor_release_ready"]
                    ),
                )
            )
            counts["usable_use_rcsd"] += 1
    if not examples:
        raise ValueError("ordinary USE Road training has no examples")
    counts["usable_example"] = len(examples)
    counts["object_feature_dim"] = len(examples[0].object_features)
    counts["candidate_feature_dim"] = len(
        examples[0].teacher_features[0]
    )
    counts["maximum_candidate_count"] = max(
        len(row.road_ids) for row in examples
    )
    counts["maximum_target_cardinality"] = max(
        len(row.target_indices) for row in examples
    )
    return examples, dict(sorted(counts.items()))


def road_endpoint_adjacency(
    endpoint_ids: Sequence[tuple[str, str]],
) -> torch.Tensor:
    count = len(endpoint_ids)
    result = torch.zeros(count, count, dtype=torch.bool)
    endpoint_sets = [
        {value for value in endpoints if value} for endpoints in endpoint_ids
    ]
    for first in range(count):
        for second in range(first + 1, count):
            if endpoint_sets[first] & endpoint_sets[second]:
                result[first, second] = True
                result[second, first] = True
    return result


def score_ordinary_use_road_examples(
    model: TargetAOrdinaryUseRoadGraphDecoder,
    examples: Sequence[OrdinaryUseRoadExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("ordinary USE Road feature source is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            batch = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
                cardinality_count=model.cardinality_count,
            )
            outputs = model(
                object_features=batch["objects"],
                candidate_features=batch["candidates"],
                candidate_mask=batch["mask"],
                adjacency=batch["adjacency"],
            )
            cardinality_probabilities = torch.softmax(
                outputs["cardinality_logits"], dim=-1
            )
            member_probabilities = torch.sigmoid(outputs["member_logits"])
            for index, row in enumerate(rows):
                cardinality = int(
                    cardinality_probabilities[index].argmax().item()
                )
                cardinality = max(1, min(cardinality, len(row.road_ids)))
                ranked = sorted(
                    range(len(row.road_ids)),
                    key=lambda value: (
                        -float(member_probabilities[index, value].item()),
                        row.road_ids[value],
                    ),
                )
                selected_indices = tuple(sorted(ranked[:cardinality]))
                target = set(row.target_indices)
                selected = set(selected_indices)
                intersection = len(target & selected)
                precision = intersection / len(selected) if selected else 0.0
                recall = intersection / len(target) if target else 0.0
                f1 = (
                    2.0 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0
                )
                selected_min = min(
                    (
                        float(member_probabilities[index, value].item())
                        for value in selected_indices
                    ),
                    default=0.0,
                )
                excluded_max = max(
                    (
                        float(member_probabilities[index, value].item())
                        for value in range(len(row.road_ids))
                        if value not in selected
                    ),
                    default=0.0,
                )
                margin = selected_min - excluded_max
                cardinality_confidence = float(
                    cardinality_probabilities[index, cardinality].item()
                )
                component_count = _component_count(
                    selected,
                    row.endpoint_ids,
                )
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "fold": row.fold,
                        "feature_source": feature_source,
                        "predicted_cardinality": cardinality,
                        "truth_cardinality": len(target),
                        "selected_road_ids": [
                            row.road_ids[value] for value in selected_indices
                        ],
                        "target_road_ids": [
                            row.road_ids[value]
                            for value in row.target_indices
                        ],
                        "road_set_exact": selected == target,
                        "road_precision": precision,
                        "road_recall": recall,
                        "road_f1": f1,
                        "cardinality_exact": cardinality == len(target),
                        "cardinality_confidence": cardinality_confidence,
                        "set_margin": margin,
                        "confidence": cardinality_confidence
                        * max(0.0, margin),
                        "selected_component_count": component_count,
                        "candidate_count": len(row.road_ids),
                        "release_eligible": row.oof_anchor_release_ready,
                    }
                )
    return result


def choose_zero_use_set_error_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    errors = [
        float(row["confidence"])
        for row in rows
        if bool(row["release_eligible"])
        and int(row["selected_component_count"]) == 1
        and not bool(row["road_set_exact"])
    ]
    if not errors:
        return 0.0
    return min(1.000001, max(errors) + 1e-9)


def ordinary_use_road_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    automatic = [
        row for row in rows if bool(row.get("conditional_automatic"))
    ]
    unsafe = [
        row for row in automatic if not bool(row["road_set_exact"])
    ]
    per_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        per_case.setdefault(str(row["case_key"]), []).append(row)
    case_exact = {
        key: sum(bool(row["road_set_exact"]) for row in values) / len(values)
        for key, values in per_case.items()
    }
    return {
        "count": count,
        "road_set_exact": (
            sum(bool(row["road_set_exact"]) for row in rows) / count
            if count
            else 0.0
        ),
        "road_macro_f1": (
            sum(float(row["road_f1"]) for row in rows) / count
            if count
            else 0.0
        ),
        "cardinality_exact": (
            sum(bool(row["cardinality_exact"]) for row in rows) / count
            if count
            else 0.0
        ),
        "single_component_rate": (
            sum(int(row["selected_component_count"]) == 1 for row in rows)
            / count
            if count
            else 0.0
        ),
        "teacher_road_set_exact": (
            sum(bool(row.get("teacher_road_set_exact")) for row in rows)
            / count
            if count
            else 0.0
        ),
        "teacher_road_macro_f1": (
            sum(float(row.get("teacher_road_f1") or 0.0) for row in rows)
            / count
            if count
            else 0.0
        ),
        "conditional_automatic_count": len(automatic),
        "conditional_automatic_coverage": (
            len(automatic) / count if count else 0.0
        ),
        "conditional_automatic_exact": (
            sum(bool(row["road_set_exact"]) for row in automatic)
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_conditional_automatic_count": len(unsafe),
        "case_count": len(per_case),
        "worst_case_road_set_exact": (
            min(case_exact.values()) if case_exact else 0.0
        ),
    }


def _component_count(
    selected: set[int],
    endpoints: Sequence[tuple[str, str]],
) -> int:
    if not selected:
        return 0
    adjacency = road_endpoint_adjacency(endpoints)
    remaining = set(selected)
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            current = stack.pop()
            neighbors = {
                value
                for value in remaining
                if bool(adjacency[current, value])
            }
            remaining -= neighbors
            stack.extend(neighbors)
    return components


def _fit_model(
    training: Sequence[OrdinaryUseRoadExample],
    validation: Sequence[OrdinaryUseRoadExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryUseRoadTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(object_dim, candidate_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state = copy.deepcopy(model.state_dict())
    best_loss = float("inf")
    best_epoch = 1
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
        if validation_loss < best_loss - 1e-8:
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
    training: Sequence[OrdinaryUseRoadExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryUseRoadTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
) -> dict[str, Any]:
    model = _new_model(object_dim, candidate_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history = []
    for epoch in range(1, epoch_count + 1):
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": _train_epoch(
                    model,
                    training,
                    optimizer=optimizer,
                    config=config,
                    device=device,
                    seed=seed + epoch,
                ),
            }
        )
    return {"model": model, "history": history}


def _new_model(
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryUseRoadTrainingConfig,
    device: torch.device,
) -> TargetAOrdinaryUseRoadGraphDecoder:
    return TargetAOrdinaryUseRoadGraphDecoder(
        object_feature_dim=object_dim,
        candidate_feature_dim=candidate_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        graph_layers=config.graph_layers,
        num_heads=config.num_heads,
        cardinality_count=config.cardinality_count,
        dropout=config.dropout,
    ).to(device)


def _train_epoch(
    model: TargetAOrdinaryUseRoadGraphDecoder,
    examples: Sequence[OrdinaryUseRoadExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: OrdinaryUseRoadTrainingConfig,
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
            examples[index] for index in order[start : start + config.batch_size]
        ]
        batch = _batch_tensors(
            rows,
            feature_source="teacher",
            device=device,
            cardinality_count=config.cardinality_count,
        )
        optimizer.zero_grad(set_to_none=True)
        outputs = model(
            object_features=batch["objects"],
            candidate_features=batch["candidates"],
            candidate_mask=batch["mask"],
            adjacency=batch["adjacency"],
        )
        raw = _loss_rows(outputs, batch, config)
        loss = (raw * batch["weights"]).sum() / batch[
            "weights"
        ].sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * batch["weights"]).sum().item())
        weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryUseRoadGraphDecoder,
    examples: Sequence[OrdinaryUseRoadExample],
    *,
    config: OrdinaryUseRoadTrainingConfig,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), config.batch_size):
            rows = examples[start : start + config.batch_size]
            batch = _batch_tensors(
                rows,
                feature_source="teacher",
                device=device,
                cardinality_count=config.cardinality_count,
            )
            outputs = model(
                object_features=batch["objects"],
                candidate_features=batch["candidates"],
                candidate_mask=batch["mask"],
                adjacency=batch["adjacency"],
            )
            raw = _loss_rows(outputs, batch, config)
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _loss_rows(
    outputs: Mapping[str, torch.Tensor],
    batch: Mapping[str, torch.Tensor],
    config: OrdinaryUseRoadTrainingConfig,
) -> torch.Tensor:
    cardinality = nn.functional.cross_entropy(
        outputs["cardinality_logits"],
        batch["cardinalities"],
        reduction="none",
    )
    members = balanced_member_bce(
        outputs["member_logits"],
        batch["targets"],
        batch["mask"],
    )
    return (
        config.cardinality_loss_weight * cardinality
        + config.member_loss_weight * members
    )


def _batch_tensors(
    examples: Sequence[OrdinaryUseRoadExample],
    *,
    feature_source: str,
    device: torch.device,
    cardinality_count: int,
) -> dict[str, torch.Tensor]:
    candidate_count = max(len(row.road_ids) for row in examples)
    feature_rows = [
        row.teacher_features if feature_source == "teacher" else row.oof_features
        for row in examples
    ]
    candidate_dim = len(feature_rows[0][0])
    candidates = torch.zeros(
        len(examples),
        candidate_count,
        candidate_dim,
        dtype=torch.float32,
        device=device,
    )
    mask = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    targets = torch.zeros_like(mask)
    adjacency = torch.zeros(
        len(examples),
        candidate_count,
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    for index, (row, values) in enumerate(zip(examples, feature_rows)):
        length = len(row.road_ids)
        candidates[index, :length] = torch.tensor(
            values,
            dtype=torch.float32,
            device=device,
        )
        mask[index, :length] = True
        targets[index, list(row.target_indices)] = True
        adjacency[index, :length, :length] = road_endpoint_adjacency(
            row.endpoint_ids
        ).to(device)
    return {
        "objects": torch.tensor(
            [row.object_features for row in examples],
            dtype=torch.float32,
            device=device,
        ),
        "candidates": candidates,
        "mask": mask,
        "targets": targets,
        "adjacency": adjacency,
        "cardinalities": torch.tensor(
            [
                min(len(row.target_indices), cardinality_count - 1)
                for row in examples
            ],
            dtype=torch.long,
            device=device,
        ),
        "weights": torch.tensor(
            [row.sample_weight for row in examples],
            dtype=torch.float32,
            device=device,
        ),
    }


def _save_checkpoint(
    path: Path,
    model: TargetAOrdinaryUseRoadGraphDecoder,
    *,
    config: OrdinaryUseRoadTrainingConfig,
    object_dim: int,
    candidate_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_USE_RCSD_ROAD_GRAPH_DECODER",
            "config": asdict(config),
            "object_dim": object_dim,
            "candidate_dim": candidate_dim,
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


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _assert_case_disjoint(
    training: Sequence[OrdinaryUseRoadExample],
    validation: Sequence[OrdinaryUseRoadExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(
            f"ordinary USE Road Case leakage: {sorted(overlap)[:5]}"
        )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "OrdinaryUseRoadExample",
    "OrdinaryUseRoadTrainingConfig",
    "choose_zero_use_set_error_threshold",
    "ordinary_use_road_metrics",
    "read_ordinary_use_road_examples",
    "road_endpoint_adjacency",
    "run_ordinary_use_road_graph_strict_nested_oof",
    "score_ordinary_use_road_examples",
]
