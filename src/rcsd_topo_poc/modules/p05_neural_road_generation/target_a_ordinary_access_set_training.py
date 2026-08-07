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
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class OrdinaryAccessSetTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    dropout: float = 0.1
    batch_size: int = 64
    max_epochs: int = 80
    patience: int = 12
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    negative_loss_weight: float = 1.0
    cardinality_loss_weight: float = 0.1
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.context_dim,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary access set training dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary access set dropout is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("ordinary access set optimizer config is invalid")
        if (
            self.negative_loss_weight < 0
            or self.cardinality_loss_weight < 0
        ):
            raise ValueError("ordinary access set loss weights are invalid")


@dataclass(frozen=True)
class OrdinaryAccessSetExample:
    case_key: str
    segment_id: str
    junction_id: str
    fold: int
    proposal_ids: tuple[str, ...]
    road_ids: tuple[str, ...]
    operations: tuple[str, ...]
    fractions: tuple[float, ...]
    teacher_features: tuple[tuple[float, ...], ...]
    oof_features: tuple[tuple[float, ...], ...]
    acceptable_index_sets: tuple[tuple[int, ...], ...]
    sample_weight: float
    oof_anchor_release_ready: bool
    upstream_plan_release_blocked: bool


def run_ordinary_access_set_strict_nested_oof(
    *,
    conditioned_store_root: Path,
    collection_label_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryAccessSetTrainingConfig = (
        OrdinaryAccessSetTrainingConfig()
    ),
    requested_device: str = "cuda",
) -> Path:
    """Train a complete Road/Node access-set decoder with strict Case OOF."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(conditioned_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(collection_label_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve(strict=False)
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples, read_summary = read_ordinary_access_set_examples(
        store,
        label_root,
    )
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary access set strict OOF needs three folds")
    feature_dim = len(examples[0].teacher_features[0])
    device = _resolve_device(requested_device)
    predictions: list[dict[str, Any]] = []
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
        inner_probabilities = predict_access_set_probabilities(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        selection_threshold = choose_set_selection_threshold(
            inner_probabilities
        )
        inner_scores = decode_access_set_probabilities(
            inner_probabilities,
            selection_threshold=selection_threshold,
        )
        acceptance_threshold = choose_zero_error_set_threshold(inner_scores)
        teacher_scores = score_ordinary_access_set_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            selection_threshold=selection_threshold,
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_ordinary_access_set_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            selection_threshold=selection_threshold,
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
            row["selection_threshold"] = selection_threshold
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
            selection_threshold=selection_threshold,
        )
        _save_checkpoint(
            outer_checkpoint,
            final["model"],
            config=config,
            feature_dim=feature_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
            selection_threshold=selection_threshold,
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
            "selection_threshold": selection_threshold,
            "acceptance_threshold": acceptance_threshold,
            "metrics": ordinary_access_set_metrics(decoded),
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
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_SET_DECODER_STRICT_NESTED_OOF",
        "model_scope": (
            "For one frozen Junction-Segment relation, score a complete "
            "Road/Node access set. Different final Roads are jointly required; "
            "only exact-cover source explanations are interchangeable."
        ),
        "training_condition": (
            "Teacher forcing uses only independently supervised anchor and "
            "complete carrier conditions. OOF scoring uses only model-derived "
            "upstream conditions."
        ),
        "release_constraint": (
            "The set head cannot repair anchor/carrier decisions. Automatic "
            "release additionally needs safe upstream OOF conditions and an "
            "inner-only zero-error set-confidence threshold."
        ),
        "feature_dim": feature_dim,
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
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "This is the corrected ordinary access-set head; joint ordinary "
            "Road/Node materialization, conditional AdvanceRight, and whole "
            "RoadGraph release are not yet closed."
        ),
        "legacy_single_road_metric": {
            "v93_raw_exact": 0.7778,
            "interpretation": (
                "invalid as complete-access correctness because the old head "
                "selected one Road from a jointly required set"
            ),
        },
        "conditioned_store_summary": _input_record(store / "summary.json"),
        "collection_label_summary": _input_record(
            label_root / "summary.json"
        ),
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(examples)
            and {_score_key(row) for row in predictions}
            == {
                (row.case_key, row.segment_id, row.junction_id)
                for row in examples
            }
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary access set OOF coverage gate failed")
    return root


def read_ordinary_access_set_examples(
    conditioned_root: Path,
    collection_root: Path,
) -> tuple[list[OrdinaryAccessSetExample], dict[str, int]]:
    store = normalize_runtime_path(conditioned_root).resolve(strict=True)
    labels_root = normalize_runtime_path(collection_root).resolve(strict=True)
    source_labels = {
        _source_label_key(row): row
        for row in _read_jsonl(
            store / "ordinary_access_training_labels.jsonl"
        )
    }
    collection_labels = {
        _collection_label_key(row): row
        for row in _read_jsonl(
            labels_root / "ordinary_access_collection_labels.jsonl"
        )
    }
    if set(source_labels) != set(collection_labels):
        raise ValueError("ordinary access source/collection label keys differ")
    examples = []
    counts: Counter[str] = Counter()
    current_key: tuple[str, str, str] | None = None
    current_rows: list[dict[str, Any]] = []
    path = store / "ordinary_access_conditioned_candidates.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (
                str(row["case_key"]),
                str(row["segment_id"]),
                str(row["junc_node_id"]),
            )
            if current_key is not None and key != current_key:
                example = _access_set_example(
                    current_key,
                    current_rows,
                    source_labels[current_key],
                    collection_labels[current_key],
                )
                _count_example(
                    example,
                    source_labels[current_key],
                    collection_labels[current_key],
                    counts,
                )
                if example is not None:
                    examples.append(example)
                current_rows = []
            current_key = key
            current_rows.append(row)
    if current_key is not None:
        example = _access_set_example(
            current_key,
            current_rows,
            source_labels[current_key],
            collection_labels[current_key],
        )
        _count_example(
            example,
            source_labels[current_key],
            collection_labels[current_key],
            counts,
        )
        if example is not None:
            examples.append(example)
    if not examples:
        raise ValueError("ordinary access set training has no usable examples")
    feature_dim = len(examples[0].teacher_features[0])
    if any(
        len(values) != feature_dim
        for row in examples
        for values in (*row.teacher_features, *row.oof_features)
    ):
        raise ValueError("ordinary access set feature dimension differs")
    counts["usable_example"] = len(examples)
    counts["feature_dim"] = feature_dim
    return examples, dict(sorted(counts.items()))


def multi_solution_set_loss(
    logits: torch.Tensor,
    acceptable_index_sets: Sequence[Sequence[int]],
    *,
    negative_loss_weight: float = 1.0,
    cardinality_loss_weight: float = 0.1,
) -> torch.Tensor:
    if logits.ndim != 1 or logits.numel() < 1:
        raise ValueError("ordinary access set logits are invalid")
    losses = []
    for acceptable in acceptable_index_sets:
        indices = sorted({int(value) for value in acceptable})
        if not indices or indices[-1] >= logits.numel() or indices[0] < 0:
            raise ValueError("ordinary access set target indices are invalid")
        positive_mask = torch.zeros_like(logits, dtype=torch.bool)
        positive_mask[indices] = True
        positive = F.softplus(-logits[positive_mask]).mean()
        if (~positive_mask).any():
            negative = F.softplus(logits[~positive_mask]).mean()
        else:
            negative = logits.new_zeros(())
        cardinality = F.smooth_l1_loss(
            torch.sigmoid(logits).sum(),
            logits.new_tensor(float(len(indices))),
        )
        losses.append(
            positive
            + negative_loss_weight * negative
            + cardinality_loss_weight * cardinality
        )
    if not losses:
        raise ValueError("ordinary access set has no acceptable collection")
    return torch.stack(losses).min()


def predict_access_set_probabilities(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("ordinary access set feature source is invalid")
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
            probabilities = torch.sigmoid(model(values, mask))
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
                        "probabilities": [
                            float(value)
                            for value in probabilities[index, :length].tolist()
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


def decode_access_set_probabilities(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_threshold: float,
) -> list[dict[str, Any]]:
    if not 0.0 <= selection_threshold <= 1.0:
        raise ValueError("ordinary access set selection threshold is invalid")
    result = []
    for source in rows:
        probabilities = [float(value) for value in source["probabilities"]]
        selected = [
            index
            for index, value in enumerate(probabilities)
            if value >= selection_threshold
        ]
        if not selected:
            selected = [max(range(len(probabilities)), key=probabilities.__getitem__)]
        predicted = tuple(sorted(selected))
        acceptable = {
            tuple(sorted(int(value) for value in values))
            for values in source["acceptable_index_sets"]
        }
        selected_set = set(predicted)
        set_confidence = min(
            [
                value if index in selected_set else 1.0 - value
                for index, value in enumerate(probabilities)
            ]
        )
        best_f1 = max(
            _set_f1(selected_set, set(values))
            for values in acceptable
        )
        row = dict(source)
        row.update(
            {
                "selection_threshold": selection_threshold,
                "predicted_indices": list(predicted),
                "predicted_proposal_ids": [
                    source["proposal_ids"][index] for index in predicted
                ],
                "predicted_road_ids": [
                    source["road_ids"][index] for index in predicted
                ],
                "raw_set_exact": predicted in acceptable,
                "set_f1": best_f1,
                "set_confidence": set_confidence,
                "predicted_cardinality": len(predicted),
                "acceptable_cardinalities": sorted(
                    {len(values) for values in acceptable}
                ),
                "release_eligible": bool(
                    source["oof_anchor_release_ready"]
                    and not source["upstream_plan_release_blocked"]
                ),
            }
        )
        result.append(row)
    return result


def score_ordinary_access_set_examples(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    feature_source: str,
    selection_threshold: float,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    return decode_access_set_probabilities(
        predict_access_set_probabilities(
            model,
            examples,
            feature_source=feature_source,
            batch_size=batch_size,
            device=device,
        ),
        selection_threshold=selection_threshold,
    )


def choose_set_selection_threshold(
    probability_rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = [value / 20.0 for value in range(2, 19)]
    scored = []
    for threshold in thresholds:
        rows = decode_access_set_probabilities(
            probability_rows,
            selection_threshold=threshold,
        )
        exact = sum(bool(row["raw_set_exact"]) for row in rows)
        mean_f1 = sum(float(row["set_f1"]) for row in rows) / max(
            len(rows), 1
        )
        scored.append((exact, mean_f1, -abs(threshold - 0.5), threshold))
    return max(scored)[-1]


def choose_zero_error_set_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    eligible = [
        row for row in rows if bool(row["release_eligible"])
    ]
    unsafe = [
        float(row["set_confidence"])
        for row in eligible
        if not bool(row["raw_set_exact"])
    ]
    if not eligible or not unsafe:
        return 1.000001
    return min(1.000001, max(unsafe) + 1e-7)


def ordinary_access_set_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    exact = sum(bool(row["raw_set_exact"]) for row in rows)
    automatic = [row for row in rows if bool(row.get("automatic"))]
    unsafe = [row for row in automatic if not bool(row["raw_set_exact"])]
    per_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        per_case.setdefault(str(row["case_key"]), []).append(row)
    case_exact = {
        key: sum(bool(row["raw_set_exact"]) for row in values) / len(values)
        for key, values in per_case.items()
    }
    return {
        "count": count,
        "oof_complete_set_exact": exact / count if count else 0.0,
        "teacher_complete_set_exact": (
            sum(bool(row.get("teacher_exact")) for row in rows) / count
            if count
            else 0.0
        ),
        "mean_set_f1": (
            sum(float(row["set_f1"]) for row in rows) / count
            if count
            else 0.0
        ),
        "release_eligible_count": sum(
            bool(row["release_eligible"]) for row in rows
        ),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / count if count else 0.0,
        "automatic_exact": (
            sum(bool(row["raw_set_exact"]) for row in automatic)
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_automatic_count": len(unsafe),
        "case_count": len(per_case),
        "worst_case_exact": min(case_exact.values()) if case_exact else 0.0,
    }


def _access_set_example(
    key: tuple[str, str, str],
    proposals: Sequence[Mapping[str, Any]],
    source_label: Mapping[str, Any],
    collection_label: Mapping[str, Any],
) -> OrdinaryAccessSetExample | None:
    if not bool(collection_label["collection_task_mask"]):
        return None
    if not bool(source_label.get("teacher_condition_available")):
        return None
    if (
        "teacher_carrier_ready" in source_label
        and not bool(source_label["teacher_carrier_ready"])
    ):
        return None
    proposal_ids = tuple(str(row["proposal_id"]) for row in proposals)
    index_by_id = {
        proposal_id: index for index, proposal_id in enumerate(proposal_ids)
    }
    acceptable_sets = []
    for collection in collection_label["acceptable_access_collections"]:
        values = tuple(
            sorted(
                index_by_id[str(proposal_id)]
                for proposal_id in collection["proposal_ids"]
                if str(proposal_id) in index_by_id
            )
        )
        if len(values) == len(collection["proposal_ids"]) and values:
            acceptable_sets.append(values)
    acceptable_sets = sorted(set(acceptable_sets))
    if not acceptable_sets:
        return None
    base = [
        [
            *[float(value) for value in row["object_feature_values"]],
            *[float(value) for value in row["plan_feature_values"]],
            *[float(value) for value in row["member_feature_values"]],
            *[float(value) for value in row["geometry_feature_values"]],
        ]
        for row in proposals
    ]
    return OrdinaryAccessSetExample(
        case_key=key[0],
        segment_id=key[1],
        junction_id=key[2],
        fold=int(collection_label["fold"]),
        proposal_ids=proposal_ids,
        road_ids=tuple(str(row["road_id"]) for row in proposals),
        operations=tuple(str(row["operation"]) for row in proposals),
        fractions=tuple(float(row["projected_fraction"]) for row in proposals),
        teacher_features=tuple(
            tuple(
                [
                    *values,
                    *[
                        float(value)
                        for value in proposal[
                            "teacher_anchor_feature_values"
                        ]
                    ],
                    *[
                        float(value)
                        for value in proposal.get(
                            "teacher_carrier_feature_values",
                            (),
                        )
                    ],
                ]
            )
            for values, proposal in zip(base, proposals)
        ),
        oof_features=tuple(
            tuple(
                [
                    *values,
                    *[
                        float(value)
                        for value in proposal["oof_anchor_feature_values"]
                    ],
                    *[
                        float(value)
                        for value in proposal.get(
                            "oof_carrier_feature_values",
                            (),
                        )
                    ],
                ]
            )
            for values, proposal in zip(base, proposals)
        ),
        acceptable_index_sets=tuple(acceptable_sets),
        sample_weight=float(collection_label["collection_label_weight"]),
        oof_anchor_release_ready=bool(
            source_label.get("oof_anchor_release_ready")
        ),
        upstream_plan_release_blocked=bool(
            source_label.get("upstream_plan_release_blocked")
        ),
    )


def _count_example(
    example: OrdinaryAccessSetExample | None,
    source_label: Mapping[str, Any],
    collection_label: Mapping[str, Any],
    counts: Counter[str],
) -> None:
    counts["label"] += 1
    counts["collection_task_mask"] += int(
        bool(collection_label["collection_task_mask"])
    )
    counts["teacher_condition_available"] += int(
        bool(source_label.get("teacher_condition_available"))
    )
    counts["teacher_carrier_ready"] += int(
        bool(source_label.get("teacher_carrier_ready", True))
    )
    if example is None:
        if not bool(collection_label["collection_task_mask"]):
            counts["masked_by_collection_label"] += 1
        elif not bool(source_label.get("teacher_condition_available")):
            counts["masked_anchor_object_unknown"] += 1
        elif not bool(source_label.get("teacher_carrier_ready", True)):
            counts["masked_complete_carrier_unknown"] += 1
        else:
            counts["masked_collection_unreachable"] += 1


def _fit_model(
    training: Sequence[OrdinaryAccessSetExample],
    validation: Sequence[OrdinaryAccessSetExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessSetTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
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
    training: Sequence[OrdinaryAccessSetExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessSetTrainingConfig,
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
    config: OrdinaryAccessSetTrainingConfig,
    device: torch.device,
) -> TargetAOrdinaryAccessDecoder:
    return TargetAOrdinaryAccessDecoder(
        feature_dim=feature_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        dropout=config.dropout,
    ).to(device)


def _train_epoch(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: OrdinaryAccessSetTrainingConfig,
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
        values, mask, weights = _batch_tensors(
            rows,
            feature_source="teacher",
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        logits = model(values, mask)
        raw = torch.stack(
            [
                multi_solution_set_loss(
                    logits[index, : len(row.proposal_ids)],
                    row.acceptable_index_sets,
                    negative_loss_weight=config.negative_loss_weight,
                    cardinality_loss_weight=config.cardinality_loss_weight,
                )
                for index, row in enumerate(rows)
            ]
        )
        loss = (raw * weights).sum() / weights.sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * weights).sum().item())
        weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    config: OrdinaryAccessSetTrainingConfig,
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
                feature_source="teacher",
                device=device,
            )
            logits = model(values, mask)
            raw = torch.stack(
                [
                    multi_solution_set_loss(
                        logits[index, : len(row.proposal_ids)],
                        row.acceptable_index_sets,
                        negative_loss_weight=config.negative_loss_weight,
                        cardinality_loss_weight=(
                            config.cardinality_loss_weight
                        ),
                    )
                    for index, row in enumerate(rows)
                ]
            )
            total += float((raw * weights).sum().item())
            weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _batch_tensors(
    examples: Sequence[OrdinaryAccessSetExample],
    *,
    feature_source: str,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    candidate_count = max(len(row.proposal_ids) for row in examples)
    source = [
        row.teacher_features
        if feature_source == "teacher"
        else row.oof_features
        for row in examples
    ]
    feature_dim = len(source[0][0])
    values = torch.zeros(
        len(examples),
        candidate_count,
        feature_dim,
        dtype=torch.float32,
        device=device,
    )
    mask = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    weights = torch.tensor(
        [row.sample_weight for row in examples],
        dtype=torch.float32,
        device=device,
    )
    for row_index, features in enumerate(source):
        length = len(features)
        values[row_index, :length] = torch.tensor(
            features,
            dtype=torch.float32,
            device=device,
        )
        mask[row_index, :length] = True
    return values, mask, weights


def _save_checkpoint(
    path: Path,
    model: TargetAOrdinaryAccessDecoder,
    *,
    config: OrdinaryAccessSetTrainingConfig,
    feature_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
    selection_threshold: float,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_ACCESS_SET_DECODER",
            "config": asdict(config),
            "feature_dim": feature_dim,
            "fold": fold,
            "inner_fold": inner_fold,
            "epoch_count": epoch_count,
            "selection_threshold": selection_threshold,
            "state_dict": {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
            },
        },
        path,
    )


def _set_f1(predicted: set[int], expected: set[int]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    overlap = len(predicted & expected)
    return 2.0 * overlap / (len(predicted) + len(expected))


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _assert_case_disjoint(
    training: Sequence[OrdinaryAccessSetExample],
    validation: Sequence[OrdinaryAccessSetExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(
            f"ordinary access set Case leakage: {sorted(overlap)[:5]}"
        )


def _score_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junction_id"]),
    )


def _source_label_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junc_node_id"]),
    )


def _collection_label_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junction_id"]),
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
    "OrdinaryAccessSetExample",
    "OrdinaryAccessSetTrainingConfig",
    "choose_set_selection_threshold",
    "choose_zero_error_set_threshold",
    "decode_access_set_probabilities",
    "multi_solution_set_loss",
    "ordinary_access_set_metrics",
    "predict_access_set_probabilities",
    "read_ordinary_access_set_examples",
    "run_ordinary_access_set_strict_nested_oof",
    "score_ordinary_access_set_examples",
]
