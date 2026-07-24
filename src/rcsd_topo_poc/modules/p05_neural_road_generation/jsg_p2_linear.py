from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import P2LinearModel


def fit_additive_linear_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    held_out_fold: int,
    smoothing: float,
    dataset_manifest_sha256: str,
    all_case_folds: Mapping[str, int],
) -> P2LinearModel:
    positive: dict[str, float] = defaultdict(float)
    negative: dict[str, float] = defaultdict(float)
    total_positive = 0.0
    total_negative = 0.0
    seen_train_cases: set[str] = set()
    for row in rows:
        if int(row["fold"]) == held_out_fold:
            continue
        case_key = str(row["case_key"])
        seen_train_cases.add(case_key)
        weight = float(row.get("sample_weight") or 1.0)
        target = bool(row["truth_equivalent"])
        if target:
            total_positive += weight
        else:
            total_negative += weight
        target_map = positive if target else negative
        for token in sorted(set(row.get("feature_tokens") or [])):
            target_map[str(token)] += weight
    if total_positive <= 0 or total_negative <= 0:
        raise ValueError("training fold must contain positive and negative candidates")
    bias = math.log((total_positive + smoothing) / (total_negative + smoothing))
    feature_weights: dict[str, float] = {}
    for token in sorted(set(positive) | set(negative)):
        token_log_odds = math.log(
            (positive[token] + smoothing) / (negative[token] + smoothing)
        )
        feature_weights[token] = max(-8.0, min(8.0, token_log_odds - bias))
    held_out_cases = sorted(
        case_key for case_key, fold in all_case_folds.items() if int(fold) == held_out_fold
    )
    expected_train = sorted(
        case_key for case_key, fold in all_case_folds.items() if int(fold) != held_out_fold
    )
    if sorted(seen_train_cases) != expected_train:
        raise ValueError("training Case scope differs from fold contract")
    if set(expected_train) & set(held_out_cases):
        raise ValueError("train/held-out Case leakage")
    return P2LinearModel(
        held_out_fold=held_out_fold,
        bias=bias,
        feature_weights=feature_weights,
        smoothing=smoothing,
        train_case_keys=tuple(expected_train),
        held_out_case_keys=tuple(held_out_cases),
        train_weighted_positive=total_positive,
        train_weighted_negative=total_negative,
        dataset_manifest_sha256=dataset_manifest_sha256,
    )


__all__ = ["fit_additive_linear_model"]


def fit_oof_additive_models(
    rows: Iterable[Mapping[str, Any]],
    *,
    fold_count: int,
    smoothing: float,
    dataset_manifest_sha256: str,
    all_case_folds: Mapping[str, int],
) -> dict[int, P2LinearModel]:
    total_positive: dict[str, float] = defaultdict(float)
    total_negative: dict[str, float] = defaultdict(float)
    fold_positive: dict[int, dict[str, float]] = {
        fold: defaultdict(float) for fold in range(fold_count)
    }
    fold_negative: dict[int, dict[str, float]] = {
        fold: defaultdict(float) for fold in range(fold_count)
    }
    total_positive_weight = total_negative_weight = 0.0
    fold_positive_weight = defaultdict(float)
    fold_negative_weight = defaultdict(float)
    seen_cases: set[str] = set()
    for row in rows:
        fold = int(row["fold"])
        if fold not in fold_positive:
            raise ValueError(f"dataset fold outside contract: {fold}")
        seen_cases.add(str(row["case_key"]))
        weight = float(row.get("sample_weight") or 1.0)
        target = bool(row["truth_equivalent"])
        total_map = total_positive if target else total_negative
        fold_map = fold_positive[fold] if target else fold_negative[fold]
        if target:
            total_positive_weight += weight
            fold_positive_weight[fold] += weight
        else:
            total_negative_weight += weight
            fold_negative_weight[fold] += weight
        for token in sorted(set(row.get("feature_tokens") or [])):
            token = str(token)
            total_map[token] += weight
            fold_map[token] += weight
    if seen_cases != set(all_case_folds):
        raise ValueError("dataset Case scope differs from fold contract")
    models: dict[int, P2LinearModel] = {}
    vocabulary = sorted(set(total_positive) | set(total_negative))
    for held_out_fold in range(fold_count):
        train_positive = total_positive_weight - fold_positive_weight[held_out_fold]
        train_negative = total_negative_weight - fold_negative_weight[held_out_fold]
        if train_positive <= 0 or train_negative <= 0:
            raise ValueError("training fold must contain positive and negative candidates")
        bias = math.log((train_positive + smoothing) / (train_negative + smoothing))
        weights: dict[str, float] = {}
        for token in vocabulary:
            positive = total_positive[token] - fold_positive[held_out_fold].get(token, 0.0)
            negative = total_negative[token] - fold_negative[held_out_fold].get(token, 0.0)
            if positive + negative <= 0:
                # A token observed only in the held-out fold is inference-unknown.
                # It must not leak into the fitted vocabulary through the
                # all-fold aggregation used by this optimized OOF path.
                continue
            token_log_odds = math.log((positive + smoothing) / (negative + smoothing))
            weights[token] = max(-8.0, min(8.0, token_log_odds - bias))
        held_out_cases = tuple(
            sorted(case_key for case_key, fold in all_case_folds.items() if fold == held_out_fold)
        )
        train_cases = tuple(
            sorted(case_key for case_key, fold in all_case_folds.items() if fold != held_out_fold)
        )
        if set(train_cases) & set(held_out_cases):
            raise ValueError("train/held-out Case leakage")
        models[held_out_fold] = P2LinearModel(
            held_out_fold=held_out_fold,
            bias=bias,
            feature_weights=weights,
            smoothing=smoothing,
            train_case_keys=train_cases,
            held_out_case_keys=held_out_cases,
            train_weighted_positive=train_positive,
            train_weighted_negative=train_negative,
            dataset_manifest_sha256=dataset_manifest_sha256,
        )
    return models


__all__ = ["fit_additive_linear_model", "fit_oof_additive_models"]
