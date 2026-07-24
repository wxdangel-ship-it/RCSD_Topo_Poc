from __future__ import annotations

import copy
import hashlib
import io
import json
import random
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_models import (
    P13P0Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_network import (
    AdvanceRightCandidateSetScorer,
    parameter_count,
)


@dataclass(frozen=True)
class FeatureTransform:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    def as_dict(self) -> dict[str, list[float]]:
        return {
            "means": list(self.means),
            "scales": list(self.scales),
        }


@dataclass
class P13FoldResult:
    model: AdvanceRightCandidateSetScorer
    transform: FeatureTransform
    candidate_threshold: float
    object_threshold: float
    safety_threshold: float
    acceptance_threshold: float
    training_summary: dict[str, Any]
    held_out_scores: list[dict[str, Any]]


def train_p13_fold(
    examples: Sequence[Mapping[str, Any]],
    *,
    held_out_fold: int,
    seed: int,
    feature_dim: int,
    config: P13P0Config,
) -> P13FoldResult:
    inner_fold = (held_out_fold + 1) % config.expected_fold_count
    train_examples = [
        row
        for row in examples
        if int(row["fold"]) not in {held_out_fold, inner_fold}
        and bool(row["safety_supervised"])
    ]
    inner_examples = [
        row
        for row in examples
        if int(row["fold"]) == inner_fold
        and bool(row["safety_supervised"])
    ]
    held_out_examples = [
        row for row in examples if int(row["fold"]) == held_out_fold
    ]
    if not train_examples or not inner_examples or not held_out_examples:
        raise ValueError("P13 fold lacks train/inner/held-out examples")
    if any(not row["candidates"] for row in train_examples + inner_examples):
        raise ValueError("P13 supervised scorer example has no candidates")

    train_cases = sorted({str(row["case_key"]) for row in train_examples})
    inner_cases = sorted({str(row["case_key"]) for row in inner_examples})
    held_out_cases = sorted(
        {str(row["case_key"]) for row in held_out_examples}
    )
    if set(train_cases).intersection(inner_cases, held_out_cases) or set(
        inner_cases
    ).intersection(held_out_cases):
        raise ValueError("P13 Case split leakage detected")

    transform = build_feature_transform(train_examples, feature_dim)
    initialization_seed = seed * 10_000 + held_out_fold
    random.seed(initialization_seed)
    torch.manual_seed(initialization_seed)
    torch.set_num_threads(config.torch_num_threads)
    torch.use_deterministic_algorithms(True)
    model = AdvanceRightCandidateSetScorer(
        feature_dim=feature_dim,
        encoder_hidden_dim=config.encoder_hidden_dim,
        embedding_dim=config.embedding_dim,
        context_dim=config.context_dim,
        decoder_hidden_dim=config.decoder_hidden_dim,
        decoder_bottleneck_dim=config.decoder_bottleneck_dim,
        dropout=config.dropout,
    ).to(torch.device("cpu"))
    model_parameters = parameter_count(model)
    if not (
        config.min_parameter_count
        <= model_parameters
        <= config.max_parameter_count
    ):
        raise ValueError("P13 model parameter count is outside the gate")

    candidate_positive, candidate_negative = _candidate_target_counts(
        train_examples
    )
    object_positive = sum(
        bool(row["truth_nonempty"])
        for row in train_examples
        if bool(row["supervised"])
    )
    object_negative = (
        sum(bool(row["supervised"]) for row in train_examples)
        - object_positive
    )
    safety_positive = sum(
        bool(row["eligible"]) and bool(row["oracle_reachable"])
        for row in train_examples
    )
    safety_negative = len(train_examples) - safety_positive
    candidate_pos_weight = _class_weight(
        candidate_negative,
        candidate_positive,
    )
    object_pos_weight = _class_weight(object_negative, object_positive)
    safety_negative_weight = _class_weight(
        safety_positive,
        safety_negative,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    best_state: dict[str, torch.Tensor] | None = None
    best_inner_loss = float("inf")
    best_epoch = 0
    no_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        order = list(range(len(train_examples)))
        random.Random(initialization_seed * 1_000 + epoch).shuffle(order)
        train_total = 0.0
        train_weight = 0
        for start in range(0, len(order), config.batch_group_count):
            rows = [
                train_examples[index]
                for index in order[start : start + config.batch_group_count]
            ]
            optimizer.zero_grad(set_to_none=True)
            loss = _loss(
                model,
                rows,
                transform,
                feature_dim=feature_dim,
                candidate_pos_weight=candidate_pos_weight,
                object_pos_weight=object_pos_weight,
                safety_negative_weight=safety_negative_weight,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            train_total += float(loss.item()) * len(rows)
            train_weight += len(rows)

        model.eval()
        with torch.no_grad():
            inner_loss = float(
                _loss(
                    model,
                    inner_examples,
                    transform,
                    feature_dim=feature_dim,
                    candidate_pos_weight=candidate_pos_weight,
                    object_pos_weight=object_pos_weight,
                    safety_negative_weight=safety_negative_weight,
                ).item()
            )
        history.append(
            {
                "epoch": float(epoch),
                "inner_loss": inner_loss,
                "train_loss": train_total / max(1, train_weight),
            }
        )
        if inner_loss < best_inner_loss - 1e-6:
            best_inner_loss = inner_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= config.patience:
                break
    if best_state is None:
        raise ValueError("P13 fold did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.eval()

    inner_raw = score_examples(
        model,
        inner_examples,
        transform,
        feature_dim=feature_dim,
    )
    candidate_threshold, object_threshold = choose_prediction_thresholds(
        inner_raw
    )
    safety_threshold = choose_safety_threshold(inner_raw)
    inner_decoded = decode_scores(
        inner_raw,
        candidate_threshold=candidate_threshold,
        object_threshold=object_threshold,
        safety_threshold=safety_threshold,
    )
    acceptance_threshold = choose_acceptance_threshold(inner_decoded)
    held_out_raw = score_examples(
        model,
        [row for row in held_out_examples if row["candidates"]],
        transform,
        feature_dim=feature_dim,
    )
    held_out_scores = decode_scores(
        held_out_raw,
        candidate_threshold=candidate_threshold,
        object_threshold=object_threshold,
        safety_threshold=safety_threshold,
    )
    wall_seconds = time.perf_counter() - started
    summary = {
        "acceptance_threshold": acceptance_threshold,
        "best_epoch": best_epoch,
        "best_inner_loss": best_inner_loss,
        "candidate_positive_count": candidate_positive,
        "candidate_threshold": candidate_threshold,
        "feature_transform": transform.as_dict(),
        "held_out_case_keys": held_out_cases,
        "held_out_fold": held_out_fold,
        "history": history,
        "initialization_seed": initialization_seed,
        "inner_case_keys": inner_cases,
        "inner_fold": inner_fold,
        "model_state_signature": model_state_signature(model),
        "object_threshold": object_threshold,
        "safety_threshold": safety_threshold,
        "parameter_count": model_parameters,
        "seed": seed,
        "train_case_keys": train_cases,
        "training_wall_seconds": wall_seconds,
    }
    return P13FoldResult(
        model=model,
        transform=transform,
        candidate_threshold=candidate_threshold,
        object_threshold=object_threshold,
        safety_threshold=safety_threshold,
        acceptance_threshold=acceptance_threshold,
        training_summary=summary,
        held_out_scores=held_out_scores,
    )


def build_feature_transform(
    examples: Sequence[Mapping[str, Any]],
    feature_dim: int,
) -> FeatureTransform:
    rows = [
        list(candidate["feature_values"])
        for example in examples
        for candidate in example["candidates"]
    ]
    if not rows or any(len(row) != feature_dim for row in rows):
        raise ValueError("P13 feature rows are empty or malformed")
    tensor = torch.tensor(rows, dtype=torch.float64)
    means = tensor.mean(dim=0)
    scales = tensor.std(dim=0, unbiased=False)
    scales = torch.where(scales < 1e-8, torch.ones_like(scales), scales)
    means[0] = 0.0
    scales[0] = 1.0
    return FeatureTransform(
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
    )


def score_examples(
    model: AdvanceRightCandidateSetScorer,
    examples: Sequence[Mapping[str, Any]],
    transform: FeatureTransform,
    *,
    feature_dim: int,
) -> list[dict[str, Any]]:
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(examples), 128):
            rows = list(examples[start : start + 128])
            values, _, mask = _batch(
                rows,
                transform,
                feature_dim=feature_dim,
                include_targets=False,
            )
            candidate_logits, object_logits, safety_logits = model(
                values,
                mask,
            )
            candidate_probabilities = torch.sigmoid(candidate_logits)
            object_probabilities = torch.sigmoid(object_logits)
            safety_probabilities = torch.sigmoid(safety_logits)
            for index, example in enumerate(rows):
                count = len(example["candidates"])
                result.append(
                    {
                        "access_valid": bool(example["access_valid"]),
                        "candidate_probabilities": [
                            float(value)
                            for value in candidate_probabilities[
                                index, :count
                            ]
                        ],
                        "candidate_road_ids": [
                            str(row["candidate_road_id"])
                            for row in example["candidates"]
                        ],
                        "candidate_targets": [
                            row.get("target")
                            for row in example["candidates"]
                        ],
                        "case_key": str(example["case_key"]),
                        "eligible": bool(example["eligible"]),
                        "fold": int(example["fold"]),
                        "object_id": str(example["object_id"]),
                        "object_probability": float(
                            object_probabilities[index]
                        ),
                        "oracle_reachable": bool(
                            example["oracle_reachable"]
                        ),
                        "review": bool(example["review"]),
                        "safety_probability": float(
                            safety_probabilities[index]
                        ),
                        "safety_supervised": bool(
                            example["safety_supervised"]
                        ),
                        "supervised": bool(example["supervised"]),
                        "truth_candidate_road_ids": list(
                            example["truth_candidate_road_ids"]
                        ),
                        "truth_nonempty": bool(example["truth_nonempty"]),
                    }
                )
    return result


def choose_prediction_thresholds(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[float, float]:
    supervised = [
        row
        for row in rows
        if bool(row["eligible"])
        and bool(row["oracle_reachable"])
        and bool(row["supervised"])
    ]
    if not supervised:
        raise ValueError("P13 inner threshold pool is empty")
    candidate_grid = [value / 20.0 for value in range(1, 20)]
    object_grid = [value / 20.0 for value in range(0, 20)]
    best: tuple[tuple[float, float, float, float], float, float] | None = None
    for candidate_threshold in candidate_grid:
        for object_threshold in object_grid:
            decoded = decode_scores(
                supervised,
                candidate_threshold=candidate_threshold,
                object_threshold=object_threshold,
                safety_threshold=0.0,
            )
            metrics = decoded_metrics(decoded)
            key = (
                metrics["raw_exact_accuracy"],
                metrics["candidate_macro_f1"],
                metrics["object_macro_f1"],
                -abs(candidate_threshold - 0.5)
                - abs(object_threshold - 0.5),
            )
            if best is None or key > best[0]:
                best = (
                    key,
                    candidate_threshold,
                    object_threshold,
                )
    if best is None:
        raise ValueError("P13 threshold search failed")
    return best[1], best[2]


def choose_safety_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    supervised = [row for row in rows if bool(row["safety_supervised"])]
    if not supervised:
        raise ValueError("P13 inner safety threshold pool is empty")
    grid = [value / 20.0 for value in range(0, 21)]
    best: tuple[tuple[int, float, float], float] | None = None
    for threshold in grid:
        review_pass = sum(
            bool(row["review"])
            and float(row["safety_probability"]) >= threshold
            for row in supervised
        )
        eligible = [
            row
            for row in supervised
            if bool(row["eligible"]) and bool(row["oracle_reachable"])
        ]
        eligible_pass = (
            sum(
                float(row["safety_probability"]) >= threshold
                for row in eligible
            )
            / len(eligible)
            if eligible
            else 0.0
        )
        key = (-review_pass, eligible_pass, threshold)
        if best is None or key > best[0]:
            best = (key, threshold)
    if best is None:
        raise ValueError("P13 safety threshold search failed")
    return best[1]


def decode_scores(
    rows: Sequence[Mapping[str, Any]],
    *,
    candidate_threshold: float,
    object_threshold: float,
    safety_threshold: float,
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        probabilities = [
            float(value) for value in row["candidate_probabilities"]
        ]
        candidate_ids = list(row["candidate_road_ids"])
        safety_pass = (
            float(row["safety_probability"]) >= safety_threshold
        )
        if float(row["object_probability"]) < object_threshold:
            raw_selected: list[str] = []
        else:
            raw_selected = [
                road_id
                for road_id, probability in zip(
                    candidate_ids,
                    probabilities,
                )
                if probability >= candidate_threshold
            ]
        selected = list(raw_selected) if safety_pass else []
        selected_set = set(selected)
        raw_selected_set = set(raw_selected)
        decisions = [
            probability if road_id in selected_set else 1.0 - probability
            for road_id, probability in zip(candidate_ids, probabilities)
        ]
        object_confidence = (
            float(row["object_probability"])
            if selected
            else 1.0 - float(row["object_probability"])
        )
        confidence = min(
            [
                float(row["safety_probability"]),
                object_confidence,
                *decisions,
            ]
        )
        exact = (
            raw_selected_set == set(row["truth_candidate_road_ids"])
            if bool(row["supervised"])
            else None
        )
        result.append(
            {
                **row,
                "candidate_threshold": candidate_threshold,
                "confidence": confidence,
                "object_threshold": object_threshold,
                "raw_exact": exact,
                "raw_selected_candidate_road_ids": sorted(raw_selected),
                "safety_pass": safety_pass,
                "safety_threshold": safety_threshold,
                "selected_candidate_road_ids": sorted(selected),
            }
        )
    return result


def choose_acceptance_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    supervised = [row for row in rows if bool(row["supervised"])]
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["confidence"]) for row in supervised],
        }
    )
    best_threshold = 1.000001
    best_coverage = -1.0
    for threshold in thresholds:
        accepted = [
            row
            for row in supervised
            if float(row["confidence"]) >= threshold
        ]
        wrong = sum(not bool(row["raw_exact"]) for row in accepted)
        coverage = len(accepted) / len(supervised)
        if wrong == 0 and (
            coverage > best_coverage
            or (
                math_isclose(coverage, best_coverage)
                and threshold < best_threshold
            )
        ):
            best_threshold = threshold
            best_coverage = coverage
    return best_threshold


def decoded_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    supervised = [row for row in rows if bool(row["supervised"])]
    if not supervised:
        return {
            "candidate_macro_f1": 0.0,
            "object_macro_f1": 0.0,
            "raw_exact_accuracy": 0.0,
        }
    candidate_truth = []
    candidate_pred = []
    object_truth = []
    object_pred = []
    for row in supervised:
        selected = set(row["raw_selected_candidate_road_ids"])
        for road_id, target in zip(
            row["candidate_road_ids"],
            row["candidate_targets"],
        ):
            candidate_truth.append(bool(target))
            candidate_pred.append(road_id in selected)
        object_truth.append(bool(row["truth_nonempty"]))
        object_pred.append(bool(selected))
    return {
        "candidate_macro_f1": binary_macro_f1(
            candidate_truth,
            candidate_pred,
        ),
        "object_macro_f1": binary_macro_f1(
            object_truth,
            object_pred,
        ),
        "raw_exact_accuracy": sum(
            bool(row["raw_exact"]) for row in supervised
        )
        / len(supervised),
    }


def binary_macro_f1(
    truth: Sequence[bool],
    predicted: Sequence[bool],
) -> float:
    if len(truth) != len(predicted) or not truth:
        return 0.0
    scores = []
    for positive in (False, True):
        tp = sum(
            actual is positive and guess is positive
            for actual, guess in zip(truth, predicted)
        )
        fp = sum(
            actual is not positive and guess is positive
            for actual, guess in zip(truth, predicted)
        )
        fn = sum(
            actual is positive and guess is not positive
            for actual, guess in zip(truth, predicted)
        )
        denominator = 2 * tp + fp + fn
        scores.append(2 * tp / denominator if denominator else 1.0)
    return sum(scores) / len(scores)


def model_state_signature(model: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("utf-8"))
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def checkpoint_payload(
    result: P13FoldResult,
    config: P13P0Config,
    *,
    feature_dim: int,
) -> dict[str, Any]:
    return {
        "candidate_threshold": result.candidate_threshold,
        "config": {
            "context_dim": config.context_dim,
            "decoder_bottleneck_dim": config.decoder_bottleneck_dim,
            "decoder_hidden_dim": config.decoder_hidden_dim,
            "dropout": config.dropout,
            "embedding_dim": config.embedding_dim,
            "encoder_hidden_dim": config.encoder_hidden_dim,
            "feature_dim": feature_dim,
        },
        "feature_transform": result.transform.as_dict(),
        "model_state_dict": {
            key: value.detach().cpu()
            for key, value in result.model.state_dict().items()
        },
        "object_threshold": result.object_threshold,
        "safety_threshold": result.safety_threshold,
        "training_summary": {
            key: value
            for key, value in result.training_summary.items()
            if key != "training_wall_seconds"
        },
    }


def save_deterministic_checkpoint(
    payload: Mapping[str, Any],
    path: Path,
) -> None:
    state = payload["model_state_dict"]
    metadata = {
        key: value
        for key, value in payload.items()
        if key != "model_state_dict"
    }
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        _write_zip_member(
            archive,
            "metadata.json",
            (
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        )
        for name, tensor in sorted(state.items()):
            buffer = io.BytesIO()
            np.save(
                buffer,
                tensor.detach().cpu().contiguous().numpy(),
                allow_pickle=False,
            )
            _write_zip_member(
                archive,
                f"tensors/{name}.npy",
                buffer.getvalue(),
            )


def load_deterministic_checkpoint(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, mode="r") as archive:
        payload = json.loads(archive.read("metadata.json"))
        state = {}
        for name in sorted(archive.namelist()):
            if not name.startswith("tensors/") or not name.endswith(".npy"):
                continue
            key = name[len("tensors/") : -len(".npy")]
            array = np.load(io.BytesIO(archive.read(name)), allow_pickle=False)
            state[key] = torch.from_numpy(array.copy())
    payload["model_state_dict"] = state
    return payload


def _write_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    data: bytes,
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)


def _loss(
    model: AdvanceRightCandidateSetScorer,
    rows: Sequence[Mapping[str, Any]],
    transform: FeatureTransform,
    *,
    feature_dim: int,
    candidate_pos_weight: float,
    object_pos_weight: float,
    safety_negative_weight: float,
) -> torch.Tensor:
    values, targets, mask = _batch(
        rows,
        transform,
        feature_dim=feature_dim,
        include_targets=True,
    )
    candidate_logits, object_logits, safety_logits = model(values, mask)
    selection_rows = targets["selection_mask"]
    selection_candidates = mask & selection_rows.unsqueeze(1)
    candidate_loss = nn.functional.binary_cross_entropy_with_logits(
        candidate_logits[selection_candidates],
        targets["candidate"][selection_candidates],
        pos_weight=torch.tensor(candidate_pos_weight),
    )
    object_loss = nn.functional.binary_cross_entropy_with_logits(
        object_logits[selection_rows],
        targets["object"][selection_rows],
        pos_weight=torch.tensor(object_pos_weight),
    )
    safety_rows = targets["safety_mask"]
    safety_targets = targets["safety"][safety_rows]
    safety_losses = nn.functional.binary_cross_entropy_with_logits(
        safety_logits[safety_rows],
        safety_targets,
        reduction="none",
    )
    safety_weights = torch.where(
        safety_targets > 0.5,
        torch.ones_like(safety_targets),
        torch.full_like(safety_targets, safety_negative_weight),
    )
    safety_loss = (safety_losses * safety_weights).mean()
    return candidate_loss + 0.5 * object_loss + 0.5 * safety_loss


def _batch(
    rows: Sequence[Mapping[str, Any]],
    transform: FeatureTransform,
    *,
    feature_dim: int,
    include_targets: bool,
) -> tuple[torch.Tensor, dict[str, torch.Tensor], torch.Tensor]:
    max_candidates = max(len(row["candidates"]) for row in rows)
    values = torch.zeros(
        (len(rows), max_candidates, feature_dim),
        dtype=torch.float32,
    )
    mask = torch.zeros(
        (len(rows), max_candidates),
        dtype=torch.bool,
    )
    candidate_targets = torch.zeros_like(mask, dtype=torch.float32)
    object_targets = torch.zeros(len(rows), dtype=torch.float32)
    safety_targets = torch.zeros(len(rows), dtype=torch.float32)
    selection_mask = torch.zeros(len(rows), dtype=torch.bool)
    safety_mask = torch.zeros(len(rows), dtype=torch.bool)
    means = torch.tensor(transform.means, dtype=torch.float32)
    scales = torch.tensor(transform.scales, dtype=torch.float32)
    for row_index, row in enumerate(rows):
        for candidate_index, candidate in enumerate(row["candidates"]):
            raw = torch.tensor(
                candidate["feature_values"],
                dtype=torch.float32,
            )
            values[row_index, candidate_index] = (raw - means) / scales
            mask[row_index, candidate_index] = True
            if include_targets and bool(row["supervised"]):
                if candidate["target"] is None:
                    raise ValueError("training target is missing")
                candidate_targets[row_index, candidate_index] = float(
                    bool(candidate["target"])
                )
        if include_targets:
            selection_mask[row_index] = bool(row["supervised"])
            safety_mask[row_index] = bool(row["safety_supervised"])
            if bool(row["supervised"]):
                object_targets[row_index] = float(
                    bool(row["truth_nonempty"])
                )
            safety_targets[row_index] = float(
                bool(row["eligible"]) and bool(row["oracle_reachable"])
            )
    return (
        values,
        {
            "candidate": candidate_targets,
            "object": object_targets,
            "safety": safety_targets,
            "safety_mask": safety_mask,
            "selection_mask": selection_mask,
        },
        mask,
    )


def _candidate_target_counts(
    examples: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    values = [
        bool(candidate["target"])
        for row in examples
        if bool(row["supervised"])
        for candidate in row["candidates"]
    ]
    positive = sum(values)
    return positive, len(values) - positive


def _class_weight(negative: int, positive: int) -> float:
    if positive <= 0:
        return 1.0
    return max(1.0, min(8.0, negative / positive))


def math_isclose(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12


__all__ = [
    "FeatureTransform",
    "P13FoldResult",
    "binary_macro_f1",
    "checkpoint_payload",
    "choose_acceptance_threshold",
    "choose_prediction_thresholds",
    "choose_safety_threshold",
    "decode_scores",
    "decoded_metrics",
    "model_state_signature",
    "load_deterministic_checkpoint",
    "save_deterministic_checkpoint",
    "score_examples",
    "train_p13_fold",
]
