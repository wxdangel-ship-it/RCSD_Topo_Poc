from __future__ import annotations

import gc
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_models import (
    JSGP3OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_network import (
    expected_calibration_error,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_training import (
    P3GroupExample,
    train_fold_model,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import write_json


def run_candidate_only_ablation(
    groups: Sequence[P3GroupExample],
    *,
    case_folds: Mapping[str, int],
    seed: int,
    dataset_manifest_sha256: str,
    config: JSGP3OOFConfig,
    output_path: Path,
) -> dict[str, Any]:
    constant_token = "ctx:candidate_only_ablation=true"
    ablation_groups = [
        replace(
            group,
            context_tokens=(constant_token,),
            context_signature=canonical_sha256((constant_token,)),
        )
        for group in groups
    ]
    correct = total = 0
    type_correct: Counter[str] = Counter()
    type_total: Counter[str] = Counter()
    review_truth = review_correct = 0
    review_selected = review_selected_correct = 0
    confidences: list[float] = []
    correctness: list[bool] = []
    fold_summaries: list[dict[str, Any]] = []
    training_wall_seconds = 0.0
    for fold in range(config.expected_fold_count):
        result = train_fold_model(
            ablation_groups,
            case_folds=case_folds,
            held_out_fold=fold,
            seed=seed,
            dataset_manifest_sha256=dataset_manifest_sha256,
            config=config,
        )
        training_wall_seconds += float(result["summary"]["training_wall_seconds"])
        fold_summaries.append(dict(result["summary"]))
        for group, scores, probabilities in zip(
            result["held_out_groups"],
            result["held_out_scores"],
            result["held_out_probabilities"],
            strict=True,
        ):
            if group.domain != "JSG":
                continue
            selected = max(
                range(len(scores)),
                key=lambda index: (float(scores[index]), group.candidate_ids[index]),
            )
            is_correct = selected == group.truth_index
            correct += is_correct
            total += 1
            type_correct[group.object_type] += is_correct
            type_total[group.object_type] += 1
            confidences.append(float(probabilities[selected]))
            correctness.append(is_correct)
            if group.truth_is_review:
                review_truth += 1
                review_correct += is_correct
            if group.candidate_review_mask[selected]:
                review_selected += 1
                review_selected_correct += is_correct
        del result
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    type_accuracy = {
        object_type: type_correct[object_type] / type_total[object_type]
        for object_type in sorted(type_total)
    }
    summary = {
        "schema_version": "p05-jsg-p3-candidate-only-ablation-v1",
        "seed": seed,
        "case_count": len(case_folds),
        "fold_count": config.expected_fold_count,
        "jsg_group_count": total,
        "jsg_top1_accuracy": correct / max(1, total),
        "jsg_semantic_macro_f1": sum(type_accuracy.values()) / max(1, len(type_accuracy)),
        "jsg_type_accuracy": type_accuracy,
        "review_unknown_recall": review_correct / review_truth if review_truth else 1.0,
        "review_unknown_precision": (
            review_selected_correct / review_selected if review_selected else 1.0
        ),
        "jsg_ece_10_bin": expected_calibration_error(
            torch.tensor(confidences, dtype=torch.float32),
            torch.tensor(correctness, dtype=torch.bool),
        ),
        "training_wall_seconds": training_wall_seconds,
        "fold_summaries": fold_summaries,
        "candidate_features_enabled": True,
        "object_context_enabled": False,
        "feature_uses_truth": False,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_path, summary)
    return summary


__all__ = ["run_candidate_only_ablation"]
