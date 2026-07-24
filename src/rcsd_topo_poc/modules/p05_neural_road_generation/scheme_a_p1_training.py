from __future__ import annotations

import copy
import json
import math
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SchemeAP1OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    SchemeACarrierGraphSetScorer,
    expected_calibration_error,
    group_probabilities,
    parameter_count,
    scheme_a_p1_loss,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class P1CandidateExample:
    candidate_id: str
    candidate_target: str
    candidate_tokens: tuple[str, ...]
    numeric_features: tuple[float, ...]


@dataclass(frozen=True)
class P1GroupExample:
    case_key: str
    fold: int
    group_id: str
    object_type: str
    object_id: str
    object_tokens: tuple[str, ...]
    context_tokens: tuple[str, ...]
    candidates: tuple[P1CandidateExample, ...]
    truth_index: int
    truth_target: str
    anomaly_target: bool
    sample_weight: float
    hard_unsafe: bool


@dataclass(frozen=True)
class P1FoldVocabulary:
    candidate_tokens: dict[str, int]
    object_tokens: dict[str, int]
    context_tokens: dict[str, int]
    object_types: dict[str, int]
    numeric_mean: tuple[float, ...]
    numeric_scale: tuple[float, ...]
    train_case_keys: tuple[str, ...]
    inner_validation_case_keys: tuple[str, ...]
    held_out_case_keys: tuple[str, ...]
    dataset_manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "p05-scheme-a-p1-fold-vocabulary-v1",
            "candidate_tokens": self.candidate_tokens,
            "object_tokens": self.object_tokens,
            "context_tokens": self.context_tokens,
            "object_types": self.object_types,
            "numeric_mean": self.numeric_mean,
            "numeric_scale": self.numeric_scale,
            "train_case_keys": self.train_case_keys,
            "inner_validation_case_keys": self.inner_validation_case_keys,
            "held_out_case_keys": self.held_out_case_keys,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
        }
        payload["vocabulary_signature"] = canonical_sha256(payload)
        return payload


@dataclass(frozen=True)
class P1EncodedGroup:
    source_index: int
    candidate_ids: tuple[str, ...]
    candidate_targets: tuple[str, ...]
    candidate_token_ids: tuple[tuple[int, ...], ...]
    candidate_numeric: tuple[tuple[float, ...], ...]
    object_token_ids: tuple[int, ...]
    context_token_ids: tuple[int, ...]
    object_type_id: int
    truth_index: int
    anomaly_target: bool
    weight: float


@dataclass(frozen=True)
class P1EncodedBatch:
    candidate_token_ids: torch.Tensor
    candidate_offsets: torch.Tensor
    object_token_ids: torch.Tensor
    object_offsets: torch.Tensor
    context_token_ids: torch.Tensor
    context_offsets: torch.Tensor
    numeric_features: torch.Tensor
    candidate_group_index: torch.Tensor
    group_type_ids: torch.Tensor
    truth_mask: torch.Tensor
    group_weights: torch.Tensor
    anomaly_targets: torch.Tensor


def load_scheme_a_p1_groups(
    dataset_run_root: Path, *, strict_hashes: bool = True
) -> tuple[list[P1GroupExample], dict[str, Any]]:
    root = normalize_runtime_path(dataset_run_root).resolve(strict=True)
    manifest_path = root / "scheme_a_p1_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "dataset_passed":
        raise ValueError("Scheme A P1 dataset candidate gate did not pass")
    outputs = dict(manifest.get("outputs") or {})
    feature_path = _verified_output(outputs, "features", strict_hashes=strict_hashes)
    label_path = _verified_output(outputs, "labels", strict_hashes=strict_hashes)
    labels: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(label_path):
        group_id = str(row["group_id"])
        if group_id in labels:
            raise ValueError(f"duplicate P1 label group: {group_id}")
        labels[group_id] = row
    feature_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(feature_path):
        if row.get("feature_uses_truth") or int(row.get("absolute_coordinate_feature_count") or 0):
            raise ValueError("truth or absolute-coordinate feature reached training loader")
        feature_groups[str(row["group_id"])].append(row)
    if set(feature_groups) != set(labels):
        raise ValueError("P1 feature/label group scope differs")
    groups: list[P1GroupExample] = []
    for group_id in sorted(labels):
        label = labels[group_id]
        rows = sorted(feature_groups[group_id], key=lambda item: str(item["candidate_id"]))
        truth_matches = [
            index
            for index, row in enumerate(rows)
            if str(row["candidate_id"]) == str(label["truth_candidate_id"])
        ]
        if len(truth_matches) != 1:
            raise ValueError(f"P1 truth candidate is not unique: {group_id}")
        object_tokens = {tuple(str(value) for value in row["object_tokens"]) for row in rows}
        context_tokens = {tuple(str(value) for value in row["context_tokens"]) for row in rows}
        hard_unsafe = {bool(row["hard_unsafe"]) for row in rows}
        if len(object_tokens) != 1 or len(context_tokens) != 1 or len(hard_unsafe) != 1:
            raise ValueError(f"P1 group-level feature mismatch: {group_id}")
        candidates = tuple(
            P1CandidateExample(
                candidate_id=str(row["candidate_id"]),
                candidate_target=str(row["candidate_target"]),
                candidate_tokens=tuple(str(value) for value in row["candidate_tokens"]),
                numeric_features=tuple(float(value) for value in row["numeric_features"]),
            )
            for row in rows
        )
        groups.append(
            P1GroupExample(
                case_key=str(label["case_key"]),
                fold=int(label["fold"]),
                group_id=group_id,
                object_type=str(label["object_type"]),
                object_id=str(label["object_id"]),
                object_tokens=next(iter(object_tokens)),
                context_tokens=next(iter(context_tokens)),
                candidates=candidates,
                truth_index=truth_matches[0],
                truth_target=str(label["carrier_target"]),
                anomaly_target=bool(label["anomaly_target"]),
                sample_weight=float(label["label_weight"]),
                hard_unsafe=next(iter(hard_unsafe)),
            )
        )
    return groups, {
        "dataset_root": root,
        "dataset_manifest": manifest,
        "dataset_manifest_path": manifest_path,
        "dataset_manifest_sha256": sha256_file(manifest_path),
        "feature_path": feature_path,
        "label_path": label_path,
    }


def select_inner_validation_cases(
    case_folds: Mapping[str, int], *, held_out_fold: int, seed: int, ratio: float
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    held_out = tuple(sorted(key for key, fold in case_folds.items() if fold == held_out_fold))
    outer_train = sorted(key for key, fold in case_folds.items() if fold != held_out_fold)
    ranked = sorted(
        outer_train,
        key=lambda case_key: (canonical_sha256({"seed": seed, "case": case_key}), case_key),
    )
    inner_count = max(1, min(len(ranked) - 1, int(math.ceil(len(ranked) * ratio))))
    inner = tuple(sorted(ranked[:inner_count]))
    train = tuple(sorted(set(outer_train) - set(inner)))
    if set(train) & set(inner) or (set(train) | set(inner)) & set(held_out):
        raise ValueError("train/inner/held-out Case leakage")
    if set(train) | set(inner) | set(held_out) != set(case_folds):
        raise ValueError("train/inner/held-out Case coverage mismatch")
    return train, inner, held_out


def build_fold_vocabulary(
    groups: Sequence[P1GroupExample],
    *,
    train_case_keys: Sequence[str],
    inner_validation_case_keys: Sequence[str],
    held_out_case_keys: Sequence[str],
    dataset_manifest_sha256: str,
) -> P1FoldVocabulary:
    train_scope = set(train_case_keys)
    candidate_tokens: set[str] = set()
    object_tokens: set[str] = set()
    context_tokens: set[str] = set()
    object_types: set[str] = set()
    numeric_rows: list[tuple[float, ...]] = []
    for group in groups:
        if group.case_key not in train_scope:
            continue
        object_tokens.update(group.object_tokens)
        context_tokens.update(group.context_tokens)
        object_types.add(group.object_type)
        for candidate in group.candidates:
            candidate_tokens.update(candidate.candidate_tokens)
            numeric_rows.append(candidate.numeric_features)
    if not candidate_tokens or not object_tokens or not context_tokens or not numeric_rows:
        raise ValueError("training vocabulary and numeric scope must not be empty")
    numeric_dim = len(numeric_rows[0])
    if any(len(row) != numeric_dim for row in numeric_rows):
        raise ValueError("numeric feature dimensions differ")
    means = tuple(sum(row[index] for row in numeric_rows) / len(numeric_rows) for index in range(numeric_dim))
    scales = tuple(
        max(
            1e-6,
            math.sqrt(
                sum((row[index] - means[index]) ** 2 for row in numeric_rows)
                / len(numeric_rows)
            ),
        )
        for index in range(numeric_dim)
    )
    return P1FoldVocabulary(
        candidate_tokens={token: index for index, token in enumerate(sorted(candidate_tokens), 1)},
        object_tokens={token: index for index, token in enumerate(sorted(object_tokens), 1)},
        context_tokens={token: index for index, token in enumerate(sorted(context_tokens), 1)},
        object_types={token: index for index, token in enumerate(sorted(object_types), 1)},
        numeric_mean=means,
        numeric_scale=scales,
        train_case_keys=tuple(sorted(train_case_keys)),
        inner_validation_case_keys=tuple(sorted(inner_validation_case_keys)),
        held_out_case_keys=tuple(sorted(held_out_case_keys)),
        dataset_manifest_sha256=dataset_manifest_sha256,
    )


def encode_groups(
    groups: Sequence[P1GroupExample], vocabulary: P1FoldVocabulary
) -> list[P1EncodedGroup]:
    result: list[P1EncodedGroup] = []
    for index, group in enumerate(groups):
        result.append(
            P1EncodedGroup(
                source_index=index,
                candidate_ids=tuple(candidate.candidate_id for candidate in group.candidates),
                candidate_targets=tuple(
                    candidate.candidate_target for candidate in group.candidates
                ),
                candidate_token_ids=tuple(
                    tuple(vocabulary.candidate_tokens.get(token, 0) for token in candidate.candidate_tokens)
                    or (0,)
                    for candidate in group.candidates
                ),
                candidate_numeric=tuple(
                    tuple(
                        (value - vocabulary.numeric_mean[numeric_index])
                        / vocabulary.numeric_scale[numeric_index]
                        for numeric_index, value in enumerate(candidate.numeric_features)
                    )
                    for candidate in group.candidates
                ),
                object_token_ids=tuple(
                    vocabulary.object_tokens.get(token, 0) for token in group.object_tokens
                )
                or (0,),
                context_token_ids=tuple(
                    vocabulary.context_tokens.get(token, 0) for token in group.context_tokens
                )
                or (0,),
                object_type_id=vocabulary.object_types.get(group.object_type, 0),
                truth_index=group.truth_index,
                anomaly_target=group.anomaly_target,
                weight=group.sample_weight,
            )
        )
    return result


def collate_groups(
    groups: Sequence[P1EncodedGroup], *, device: torch.device
) -> P1EncodedBatch:
    if not groups:
        raise ValueError("cannot collate an empty group batch")
    candidate_tokens: list[int] = []
    candidate_offsets: list[int] = []
    object_tokens: list[int] = []
    object_offsets: list[int] = []
    context_tokens: list[int] = []
    context_offsets: list[int] = []
    numeric: list[tuple[float, ...]] = []
    group_index: list[int] = []
    type_ids: list[int] = []
    truth_mask: list[bool] = []
    weights: list[float] = []
    anomaly_targets: list[bool] = []
    for group_number, group in enumerate(groups):
        object_offsets.append(len(object_tokens))
        object_tokens.extend(group.object_token_ids)
        context_offsets.append(len(context_tokens))
        context_tokens.extend(group.context_token_ids)
        type_ids.append(group.object_type_id)
        weights.append(group.weight)
        anomaly_targets.append(group.anomaly_target)
        for candidate_number, (token_ids, numeric_row) in enumerate(
            zip(group.candidate_token_ids, group.candidate_numeric, strict=True)
        ):
            candidate_offsets.append(len(candidate_tokens))
            candidate_tokens.extend(token_ids)
            numeric.append(numeric_row)
            group_index.append(group_number)
            truth_mask.append(candidate_number == group.truth_index)
    return P1EncodedBatch(
        candidate_token_ids=torch.tensor(candidate_tokens, dtype=torch.long, device=device),
        candidate_offsets=torch.tensor(candidate_offsets, dtype=torch.long, device=device),
        object_token_ids=torch.tensor(object_tokens, dtype=torch.long, device=device),
        object_offsets=torch.tensor(object_offsets, dtype=torch.long, device=device),
        context_token_ids=torch.tensor(context_tokens, dtype=torch.long, device=device),
        context_offsets=torch.tensor(context_offsets, dtype=torch.long, device=device),
        numeric_features=torch.tensor(numeric, dtype=torch.float32, device=device),
        candidate_group_index=torch.tensor(group_index, dtype=torch.long, device=device),
        group_type_ids=torch.tensor(type_ids, dtype=torch.long, device=device),
        truth_mask=torch.tensor(truth_mask, dtype=torch.bool, device=device),
        group_weights=torch.tensor(weights, dtype=torch.float32, device=device),
        anomaly_targets=torch.tensor(anomaly_targets, dtype=torch.bool, device=device),
    )


def _forward(
    model: SchemeACarrierGraphSetScorer, batch: P1EncodedBatch
) -> tuple[torch.Tensor, torch.Tensor]:
    return model(
        candidate_token_ids=batch.candidate_token_ids,
        candidate_offsets=batch.candidate_offsets,
        object_token_ids=batch.object_token_ids,
        object_offsets=batch.object_offsets,
        context_token_ids=batch.context_token_ids,
        context_offsets=batch.context_offsets,
        numeric_features=batch.numeric_features,
        candidate_group_index=batch.candidate_group_index,
        group_type_ids=batch.group_type_ids,
    )


def _iter_batches(
    groups: Sequence[P1EncodedGroup], *, batch_group_count: int, seed: int | None
) -> Iterable[list[P1EncodedGroup]]:
    indices = list(range(len(groups)))
    if seed is not None:
        random.Random(seed).shuffle(indices)
    for start in range(0, len(indices), batch_group_count):
        yield [groups[index] for index in indices[start : start + batch_group_count]]


def score_encoded_groups(
    model: SchemeACarrierGraphSetScorer,
    groups: Sequence[P1EncodedGroup],
    *,
    batch_group_count: int,
    device: torch.device,
) -> tuple[list[list[float]], list[list[float]], list[float]]:
    model.eval()
    all_scores: list[list[float]] = []
    all_probabilities: list[list[float]] = []
    anomaly_probabilities: list[float] = []
    with torch.no_grad():
        for batch_groups in _iter_batches(
            groups, batch_group_count=batch_group_count, seed=None
        ):
            batch = collate_groups(batch_groups, device=device)
            scores, anomaly_logits = _forward(model, batch)
            probabilities = group_probabilities(
                scores, batch.candidate_group_index, len(batch_groups)
            )
            anomaly_probabilities.extend(torch.sigmoid(anomaly_logits).cpu().tolist())
            cursor = 0
            for group in batch_groups:
                count = len(group.candidate_ids)
                all_scores.append(scores[cursor : cursor + count].cpu().tolist())
                all_probabilities.append(
                    probabilities[cursor : cursor + count].cpu().tolist()
                )
                cursor += count
    return all_scores, all_probabilities, anomaly_probabilities


def selection_metrics(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    *,
    anomaly_threshold: float = 0.5,
) -> dict[str, float]:
    predicted_targets: list[str] = []
    truth_targets: list[str] = []
    candidate_correct: list[bool] = []
    confidences: list[float] = []
    movement_available_correct = 0
    movement_available_count = 0
    anomaly_tp = anomaly_fp = anomaly_fn = 0
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        groups, scores, probabilities, anomaly_probabilities, strict=True
    ):
        selected = max(
            range(len(group_scores)),
            key=lambda index: (float(group_scores[index]), group.candidates[index].candidate_id),
        )
        predicted_targets.append(group.candidates[selected].candidate_target)
        truth_targets.append(group.truth_target)
        is_correct = selected == group.truth_index
        candidate_correct.append(is_correct)
        confidences.append(float(group_probabilities[selected]))
        if group.object_type == "MOVEMENT" and not group.anomaly_target:
            movement_available_count += 1
            movement_available_correct += is_correct
        predicted_anomaly = float(anomaly_probability) >= anomaly_threshold
        anomaly_tp += predicted_anomaly and group.anomaly_target
        anomaly_fp += predicted_anomaly and not group.anomaly_target
        anomaly_fn += (not predicted_anomaly) and group.anomaly_target
    segment_indices = [
        index for index, group in enumerate(groups) if group.object_type == "SEGMENT"
    ]
    macro = _macro_f1(
        [truth_targets[index] for index in segment_indices],
        [predicted_targets[index] for index in segment_indices],
        ("USE_RCSD", "KEEP_SWSD", "REVIEW_FALLBACK"),
    )
    confidence_tensor = torch.tensor(confidences, dtype=torch.float32)
    correctness_tensor = torch.tensor(candidate_correct, dtype=torch.bool)
    anomaly_precision = anomaly_tp / max(1, anomaly_tp + anomaly_fp)
    anomaly_recall = anomaly_tp / max(1, anomaly_tp + anomaly_fn)
    return {
        "candidate_exact_accuracy": sum(candidate_correct) / max(1, len(groups)),
        "segment_macro_f1": macro,
        "movement_available_exact": movement_available_correct
        / max(1, movement_available_count),
        "anomaly_precision": anomaly_precision,
        "anomaly_recall": anomaly_recall,
        "anomaly_f1": 2 * anomaly_precision * anomaly_recall
        / max(1e-12, anomaly_precision + anomaly_recall),
        "ece": expected_calibration_error(confidence_tensor, correctness_tensor),
    }


def select_thresholds(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    *,
    max_anomaly_threshold: float = 0.95,
) -> dict[str, float]:
    anomaly_options: list[tuple[tuple[float, ...], float, float, float]] = []
    anomaly_thresholds = sorted(
        {
            max_anomaly_threshold,
            *(
                threshold_index / 40
                for threshold_index in range(2, 39)
                if threshold_index / 40 <= max_anomaly_threshold
            ),
        }
    )
    for threshold in anomaly_thresholds:
        tp = fp = fn = 0
        for group, probability in zip(groups, anomaly_probabilities, strict=True):
            predicted = group.hard_unsafe or float(probability) >= threshold
            tp += predicted and group.anomaly_target
            fp += predicted and not group.anomaly_target
            fn += (not predicted) and group.anomaly_target
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = 2 * precision * recall / max(1e-12, precision + recall)
        satisfies = precision >= 0.80 and recall >= 0.98
        anomaly_options.append(
            ((float(satisfies), f1, recall, precision, -threshold), threshold, precision, recall)
        )
    _, anomaly_threshold, anomaly_precision, anomaly_recall = max(anomaly_options)
    selected_rows: list[tuple[bool, bool, float, float, bool]] = []
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        groups, scores, probabilities, anomaly_probabilities, strict=True
    ):
        selected = max(
            range(len(group_scores)),
            key=lambda index: (float(group_scores[index]), group.candidates[index].candidate_id),
        )
        selected_rows.append(
            (
                selected == group.truth_index,
                group.anomaly_target,
                float(group_probabilities[selected]),
                float(anomaly_probability),
                group.candidates[selected].candidate_target == "REVIEW_FALLBACK"
                or group.hard_unsafe,
            )
        )
    threshold_options: list[tuple[tuple[float, ...], float, float, float, float]] = []
    for threshold_index in range(0, 100):
        confidence_threshold = threshold_index / 100
        accepted = [
            row
            for row in selected_rows
            if not row[4]
            and row[2] >= confidence_threshold
            and row[3] < anomaly_threshold
        ]
        accepted_precision = sum(row[0] for row in accepted) / max(1, len(accepted))
        anomaly_rows = [row for row in selected_rows if row[1]]
        fallback_recall = sum(
            row[4]
            or row[2] < confidence_threshold
            or row[3] >= anomaly_threshold
            for row in anomaly_rows
        ) / max(1, len(anomaly_rows))
        coverage = len(accepted) / max(1, len(selected_rows))
        satisfies = accepted_precision >= 0.95 and fallback_recall >= 0.98
        threshold_options.append(
            (
                (
                    float(satisfies),
                    coverage if satisfies else accepted_precision + fallback_recall,
                    accepted_precision,
                    fallback_recall,
                    -confidence_threshold,
                ),
                confidence_threshold,
                accepted_precision,
                fallback_recall,
                coverage,
            )
        )
    _, confidence_threshold, accepted_precision, fallback_recall, coverage = max(
        threshold_options
    )
    return {
        "confidence_threshold": confidence_threshold,
        "anomaly_threshold": anomaly_threshold,
        "inner_accepted_precision": accepted_precision,
        "inner_fallback_recall": fallback_recall,
        "inner_accepted_coverage": coverage,
        "inner_anomaly_precision": anomaly_precision,
        "inner_anomaly_recall": anomaly_recall,
    }


def train_scheme_a_p1_fold(
    groups: Sequence[P1GroupExample],
    *,
    case_folds: Mapping[str, int],
    held_out_fold: int,
    seed: int,
    dataset_manifest_sha256: str,
    config: SchemeAP1OOFConfig,
) -> dict[str, Any]:
    train_cases, inner_cases, held_out_cases = select_inner_validation_cases(
        case_folds,
        held_out_fold=held_out_fold,
        seed=seed,
        ratio=config.inner_validation_ratio,
    )
    vocabulary = build_fold_vocabulary(
        groups,
        train_case_keys=train_cases,
        inner_validation_case_keys=inner_cases,
        held_out_case_keys=held_out_cases,
        dataset_manifest_sha256=dataset_manifest_sha256,
    )
    train_source = [group for group in groups if group.case_key in set(train_cases)]
    inner_source = [group for group in groups if group.case_key in set(inner_cases)]
    held_out_source = [group for group in groups if group.case_key in set(held_out_cases)]
    encoded_train = encode_groups(train_source, vocabulary)
    encoded_inner = encode_groups(inner_source, vocabulary)
    encoded_held_out = encode_groups(held_out_source, vocabulary)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(config.torch_num_threads)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
    device = _resolve_device(config.device)
    model = SchemeACarrierGraphSetScorer(
        candidate_vocabulary_size=len(vocabulary.candidate_tokens) + 1,
        object_vocabulary_size=len(vocabulary.object_tokens) + 1,
        context_vocabulary_size=len(vocabulary.context_tokens) + 1,
        object_type_count=len(vocabulary.object_types) + 1,
        numeric_dim=config.numeric_dim,
        embedding_dim=config.embedding_dim,
        hidden_dim=config.hidden_dim,
        type_embedding_dim=config.type_embedding_dim,
        dropout=config.dropout,
    ).to(device)
    parameters = parameter_count(model)
    if not config.min_parameter_count <= parameters <= config.max_parameter_count:
        raise ValueError(f"P1 parameter count outside contract: {parameters}")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    anomaly_positive = sum(group.anomaly_target for group in train_source)
    anomaly_negative = len(train_source) - anomaly_positive
    positive_weight = anomaly_negative / max(1, anomaly_positive)
    history: list[dict[str, Any]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_metric = -math.inf
    best_epoch = 0
    stale_epochs = 0
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        loss_sum = listwise_sum = anomaly_sum = 0.0
        batch_count = 0
        for batch_groups in _iter_batches(
            encoded_train,
            batch_group_count=config.batch_group_count,
            seed=seed * 1000 + epoch,
        ):
            batch = collate_groups(batch_groups, device=device)
            optimizer.zero_grad(set_to_none=True)
            candidate_scores, anomaly_logits = _forward(model, batch)
            loss, parts = scheme_a_p1_loss(
                candidate_scores,
                anomaly_logits,
                batch.candidate_group_index,
                batch.truth_mask,
                batch.group_weights,
                batch.anomaly_targets,
                anomaly_loss_weight=config.anomaly_loss_weight,
                anomaly_positive_weight=positive_weight,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            loss_sum += float(loss.detach().cpu())
            listwise_sum += float(parts["listwise_loss"].detach().cpu())
            anomaly_sum += float(parts["anomaly_loss"].detach().cpu())
            batch_count += 1
        inner_scores, inner_probabilities, inner_anomaly = score_encoded_groups(
            model,
            encoded_inner,
            batch_group_count=config.batch_group_count,
            device=device,
        )
        inner_metrics = selection_metrics(
            inner_source, inner_scores, inner_probabilities, inner_anomaly
        )
        metric = (
            inner_metrics["segment_macro_f1"]
            + 0.25 * inner_metrics["movement_available_exact"]
            + 0.10 * inner_metrics["anomaly_f1"]
            - 0.05 * inner_metrics["ece"]
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": loss_sum / max(1, batch_count),
                "train_listwise_loss": listwise_sum / max(1, batch_count),
                "train_anomaly_loss": anomaly_sum / max(1, batch_count),
                **{f"inner_{key}": value for key, value in inner_metrics.items()},
                "selection_metric": metric,
            }
        )
        if metric > best_metric + 1e-9:
            best_metric = metric
            best_epoch = epoch
            best_state = copy.deepcopy(
                {key: value.detach().cpu() for key, value in model.state_dict().items()}
            )
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("P1 training did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    inner_scores, inner_probabilities, inner_anomaly = score_encoded_groups(
        model,
        encoded_inner,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    thresholds = select_thresholds(
        inner_source,
        inner_scores,
        inner_probabilities,
        inner_anomaly,
        max_anomaly_threshold=config.max_anomaly_threshold,
    )
    held_scores, held_probabilities, held_anomaly = score_encoded_groups(
        model,
        encoded_held_out,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    held_metrics = selection_metrics(
        held_out_source,
        held_scores,
        held_probabilities,
        held_anomaly,
        anomaly_threshold=thresholds["anomaly_threshold"],
    )
    return {
        "model": model,
        "device": device,
        "vocabulary": vocabulary,
        "train_groups": train_source,
        "inner_groups": inner_source,
        "held_out_groups": held_out_source,
        "held_out_encoded": encoded_held_out,
        "held_out_scores": held_scores,
        "held_out_probabilities": held_probabilities,
        "held_out_anomaly_probabilities": held_anomaly,
        "thresholds": thresholds,
        "history": history,
        "summary": {
            "seed": seed,
            "held_out_fold": held_out_fold,
            "best_epoch": best_epoch,
            "best_inner_metric": best_metric,
            "parameter_count": parameters,
            "train_case_count": len(train_cases),
            "inner_validation_case_count": len(inner_cases),
            "held_out_case_count": len(held_out_cases),
            "train_group_count": len(train_source),
            "inner_validation_group_count": len(inner_source),
            "held_out_group_count": len(held_out_source),
            "training_wall_seconds": time.perf_counter() - started,
            "device": str(device),
            **thresholds,
            **{f"held_out_{key}": value for key, value in held_metrics.items()},
        },
    }


def _macro_f1(truth: Sequence[str], predicted: Sequence[str], labels: Sequence[str]) -> float:
    values: list[float] = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, predicted, strict=True))
        fp = sum(a != label and b == label for a, b in zip(truth, predicted, strict=True))
        fn = sum(a == label and b != label for a, b in zip(truth, predicted, strict=True))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        values.append(2 * precision * recall / max(1e-12, precision + recall))
    return sum(values) / max(1, len(values))


def _resolve_device(value: str) -> torch.device:
    if value == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    if value in {"cuda", "auto"} and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _verified_output(
    outputs: Mapping[str, Any], key: str, *, strict_hashes: bool
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"P1 dataset output hash mismatch: {key}")
    return path


__all__ = [
    "P1CandidateExample",
    "P1EncodedGroup",
    "P1FoldVocabulary",
    "P1GroupExample",
    "build_fold_vocabulary",
    "collate_groups",
    "encode_groups",
    "load_scheme_a_p1_groups",
    "score_encoded_groups",
    "select_inner_validation_cases",
    "select_thresholds",
    "selection_metrics",
    "train_scheme_a_p1_fold",
]
