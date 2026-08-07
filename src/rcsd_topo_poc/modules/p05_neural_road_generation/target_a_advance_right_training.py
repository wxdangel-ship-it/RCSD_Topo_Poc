from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    TargetAAdvanceRightConditionalDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


PLAN_TYPES = (
    "RCSD_ONLY",
    "SWSD_ONLY",
    "MIXED_SPLICE",
    "SAFE_SWSD_FALLBACK",
    "REVIEW_FALLBACK",
)
PLAN_TYPE_INDEX = {
    value: index for index, value in enumerate(PLAN_TYPES)
}
AUTOMATIC_PLAN_TYPES = {"RCSD_ONLY", "SWSD_ONLY", "MIXED_SPLICE"}
CANDIDATE_FEATURE_DIM = 60
SIDE_FEATURE_DIM = 150
MEMBER_FEATURE_DIM = 24
ARM_FEATURE_DIM = 13
CARDINALITY_COUNT = 10


def run_advance_right_conditional_strict_nested_oof(
    *,
    conditioned_store_root: Path,
    output_root: Path,
    seed: int,
    batch_size: int = 64,
    requested_device: str = "cuda",
    max_epochs: int = 160,
    patience: int = 24,
    learning_rate: float = 3e-4,
    weight_decay: float = 2e-4,
    minimum_acceptance_threshold: float = 0.0,
) -> Path:
    """Train the conditional set encoder and structured Road-set decoder."""
    started = time.perf_counter()
    if min(batch_size, max_epochs, patience) < 1:
        raise ValueError("AdvanceRight training configuration is invalid")
    store = normalize_runtime_path(conditioned_store_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_advance_right_conditioned_examples(store)
    folds = sorted({int(row["fold"]) for row in examples})
    if len(folds) < 3:
        raise ValueError("AdvanceRight strict OOF requires three folds")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)
    predictions = []
    fold_summaries = []
    model_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[
            (folds.index(outer_fold) + 1) % len(folds)
        ]
        inner_training = [
            row
            for row in examples
            if int(row["fold"]) not in {outer_fold, inner_fold}
        ]
        inner_validation = [
            row for row in examples if int(row["fold"]) == inner_fold
        ]
        outer_training = [
            row for row in examples if int(row["fold"]) != outer_fold
        ]
        outer_validation = [
            row for row in examples if int(row["fold"]) == outer_fold
        ]
        _assert_case_disjoint(inner_training, inner_validation)
        _assert_case_disjoint(outer_training, outer_validation)
        tuning = _fit_model(
            inner_training,
            inner_validation,
            seed=seed + outer_fold * 100 + 17,
            batch_size=batch_size,
            device=device,
            max_epochs=max_epochs,
            patience=patience,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
        )
        final = _fit_fixed_epochs(
            outer_training,
            seed=seed + outer_fold * 100 + 53,
            batch_size=batch_size,
            device=device,
            epoch_count=tuning["best_epoch"],
            learning_rate=learning_rate,
            weight_decay=weight_decay,
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_advance_right_examples(
            tuning["model"],
            inner_validation,
            batch_size=batch_size,
            device=device,
        )
        safety_threshold = choose_zero_unsafe_safety_threshold(inner_scores)
        inner_decoded = decode_advance_right_scores(
            inner_scores,
            safety_threshold=safety_threshold,
            acceptance_threshold=0.0,
        )
        acceptance_threshold = max(
            minimum_acceptance_threshold,
            choose_zero_error_acceptance_threshold(inner_decoded),
        )
        outer_scores = score_advance_right_examples(
            final["model"],
            outer_validation,
            batch_size=batch_size,
            device=device,
        )
        outer_decoded = decode_advance_right_scores(
            outer_scores,
            safety_threshold=safety_threshold,
            acceptance_threshold=acceptance_threshold,
        )
        for row in outer_decoded:
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
        predictions.extend(outer_decoded)

        inner_checkpoint = root / f"fold_{outer_fold}_inner_checkpoint.pt"
        outer_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            inner_checkpoint,
            model=tuning["model"],
            fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 17,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            outer_checkpoint,
            model=final["model"],
            fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
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
            "safety_threshold": safety_threshold,
            "acceptance_threshold": acceptance_threshold,
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "metrics": advance_right_metrics(outer_decoded),
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(
            root / f"fold_{outer_fold}_summary.json",
            fold_summary,
        )
    predictions.sort(key=lambda row: (row["case_key"], row["object_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = advance_right_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_CONDITIONAL_STRUCTURED_DECODER_STRICT_OOF",
        "model_scope": (
            "Hierarchical set encoders consume each adjacent ordinary "
            "Segment's locked complete Road plan plus the P12R-R1 candidate "
            "set. The decoder jointly emits formal plan type, RCSD Road "
            "cardinality, full candidate Road set, and safety."
        ),
        "decoder_constraint": (
            "Locked adjacent access sources constrain the automatic plan: "
            "SWSD+SWSD=SWSD_ONLY, RCSD+RCSD=RCSD_ONLY, and mixed sources="
            "MIXED_SPLICE. Learned heads may abstain but cannot change this "
            "source-conditioned business type."
        ),
        "output_scope": {
            "trained": [
                "formal_plan_type",
                "complete_rcsd_candidate_road_set",
                "rcsd_road_cardinality",
                "safety_or_fallback",
            ],
            "not_yet_trained": [
                "attachment_road",
                "split_position",
                "splice_position",
                "generated_node_recipe",
            ],
        },
        "example_count": len(examples),
        "fold_count": len(folds),
        "seed": seed,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "patience": patience,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "minimum_acceptance_threshold": minimum_acceptance_threshold,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "parameter_count": model_parameters,
        "plan_types": list(PLAN_TYPES),
        "cardinality_count": CARDINALITY_COUNT,
        "metrics": metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "multi_solution_loss": (
            "Each final T06 RCSD Road contributes an acceptable candidate set. "
            "The loss requires at least one candidate per set, penalizes Roads "
            "outside every set, and learns the number of final RCSD Roads."
        ),
        "release_gate": "NO_GO",
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "Attachment Road, split/splice position, and Node recipe are not "
            "yet output heads, so complete AdvanceRight business correctness "
            "cannot be claimed from Road-set selection alone."
        ),
        "legacy_comparison": {
            "p13_raw_exact": 0.646907,
            "local_control_5m_exact": 0.680412,
            "comparison_note": (
                "P13 and Local Control score candidate-local Road subsets. "
                "This run additionally requires the formal plan type and a "
                "multi-solution complete Road set under adjacent final state, "
                "so exact values are not definition-identical."
            ),
        },
        "conditioned_store_summary": _input_record(
            store / "summary.json"
        ),
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(examples)
            and {
                (row["case_key"], row["object_id"])
                for row in predictions
            }
            == {
                (row["case_key"], row["object_id"]) for row in examples
            }
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight OOF coverage gate failed")
    return root


def read_advance_right_conditioned_examples(
    root: Path,
) -> list[dict[str, Any]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    features = _read_jsonl(
        store / "advance_right_inference_features.jsonl"
    )
    labels = _read_jsonl(store / "advance_right_training_labels.jsonl")
    label_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in labels
    }
    if len(label_by_key) != len(labels):
        raise ValueError("AdvanceRight labels contain duplicate objects")
    examples = []
    for feature in features:
        key = (str(feature["case_key"]), str(feature["object_id"]))
        label = label_by_key.get(key)
        if label is None:
            raise ValueError(f"AdvanceRight label is missing: {key}")
        formal_plan_type = str(label["truth_plan_type"])
        (
            plan_type,
            acceptable_groups,
            conditional_reason,
        ) = conditional_plan_target(feature, label)
        if plan_type not in PLAN_TYPE_INDEX:
            raise ValueError(f"unsupported AdvanceRight plan type: {plan_type}")
        candidate_ids = {
            str(row["candidate_road_id"])
            for row in feature["candidate_rows"]
        }
        formal_acceptable_groups = [
            [
                candidate_id
                for candidate_id in values
                if candidate_id in candidate_ids
            ]
            for _, values in sorted(
                (
                    str(road_id),
                    [str(value) for value in candidate_values],
                )
                for road_id, candidate_values in label[
                    "acceptable_rcsd_candidate_ids_by_truth_road"
                ].items()
            )
        ]
        if plan_type in {"RCSD_ONLY", "MIXED_SPLICE"}:
            acceptable_groups = formal_acceptable_groups
        else:
            acceptable_groups = []
        candidate_supervised = bool(
            plan_type in AUTOMATIC_PLAN_TYPES
            and feature["adjacent_context_resolved"]
            and (
                plan_type == "SWSD_ONLY"
                or (
                    bool(formal_acceptable_groups)
                    and all(formal_acceptable_groups)
                )
            )
        )
        if candidate_supervised and any(
            not values for values in acceptable_groups
        ):
            raise ValueError(
                f"reachable AdvanceRight has an empty acceptable set: {key}"
            )
        examples.append(
            {
                **feature,
                "formal_truth_plan_type": formal_plan_type,
                "source_condition_plan_type": (
                    source_condition_plan_type(feature)
                ),
                "truth_plan_type": plan_type,
                "plan_type_index": PLAN_TYPE_INDEX[plan_type],
                "acceptable_candidate_groups": acceptable_groups,
                "truth_cardinality": len(acceptable_groups),
                "candidate_supervised": candidate_supervised,
                "safety_target": candidate_supervised,
                "fallback_supervised": (
                    plan_type not in AUTOMATIC_PLAN_TYPES
                ),
                "conditional_target_reason": conditional_reason,
                "label_weight": float(label["label_weight"]),
                "label_only_fields_loaded": True,
            }
        )
    if len(examples) != len(labels):
        raise ValueError("AdvanceRight conditioned feature/label count differs")
    return sorted(examples, key=lambda row: (row["case_key"], row["object_id"]))


def source_condition_plan_type(feature: Mapping[str, Any]) -> str:
    if not bool(feature["adjacent_context_resolved"]):
        return "REVIEW_FALLBACK"
    source = str(feature["source_context"]["data_source"])
    target = str(feature["target_context"]["data_source"])
    if source == "SWSD" and target == "SWSD":
        return "SWSD_ONLY"
    if source == "RCSD" and target == "RCSD":
        return "RCSD_ONLY"
    if {source, target} == {"RCSD", "SWSD"}:
        return "MIXED_SPLICE"
    return "REVIEW_FALLBACK"


def conditional_plan_target(
    feature: Mapping[str, Any],
    label: Mapping[str, Any],
) -> tuple[str, list[list[str]], str]:
    """Recompute the T06 plan target after ordinary OOF final-state locking."""
    formal_plan = str(label["truth_plan_type"])
    groups = [
        [str(value) for value in candidate_values]
        for _, candidate_values in sorted(
            (
                str(road_id),
                values,
            )
            for road_id, values in label[
                "acceptable_rcsd_candidate_ids_by_truth_road"
            ].items()
        )
    ]
    if not bool(feature["adjacent_context_resolved"]):
        return "REVIEW_FALLBACK", [], "ADJACENT_CONTEXT_UNRESOLVED"
    source = str(feature["source_context"]["data_source"])
    target = str(feature["target_context"]["data_source"])
    fixed_swsd = [
        str(value) for value in feature.get("fixed_swsd_road_ids") or ()
    ]
    if source == "SWSD" and target == "SWSD":
        swsd_ready = bool(
            fixed_swsd
            and feature.get("access_valid", True)
            and label.get("swsd_reachable", True)
            and label.get("materializer_ready", True)
        )
        if swsd_ready:
            return "SWSD_ONLY", [], "BOTH_ADJACENT_ACCESS_SWSD"
        return "REVIEW_FALLBACK", [], "FROZEN_SWSD_PLAN_UNSAFE"
    if not bool(label["plan_task_mask"]):
        if formal_plan in {"SAFE_SWSD_FALLBACK", "REVIEW_FALLBACK"}:
            return formal_plan, [], "FORMAL_T06_FALLBACK"
        return "REVIEW_FALLBACK", [], "FORMAL_CANDIDATE_UNREACHABLE"
    if source == "RCSD" and target == "RCSD":
        if groups and all(groups):
            return "RCSD_ONLY", groups, "BOTH_ADJACENT_ACCESS_RCSD"
        return "SAFE_SWSD_FALLBACK", [], "RCSD_ADVANCE_PLAN_UNREACHABLE"
    if {source, target} == {"RCSD", "SWSD"}:
        if fixed_swsd and groups and all(groups):
            return "MIXED_SPLICE", groups, "MIXED_ADJACENT_ACCESS_SOURCE"
        return "SAFE_SWSD_FALLBACK", [], "MIXED_SPLICE_PLAN_UNREACHABLE"
    return "REVIEW_FALLBACK", [], "ADJACENT_SOURCE_INVALID"


def collate_advance_right_batch(
    examples: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("cannot collate an empty AdvanceRight batch")
    batch_size = len(examples)
    candidate_count = max(
        1,
        max(len(row["candidate_rows"]) for row in examples),
    )
    candidate_values = torch.zeros(
        (batch_size, candidate_count, CANDIDATE_FEATURE_DIM),
        dtype=torch.float32,
    )
    candidate_mask = torch.zeros(
        (batch_size, candidate_count),
        dtype=torch.bool,
    )
    source = _collate_sides(examples, "source_context")
    target = _collate_sides(examples, "target_context")
    for index, example in enumerate(examples):
        rows = list(example["candidate_rows"])
        if rows:
            values = torch.tensor(
                [row["feature_values"] for row in rows],
                dtype=torch.float32,
            )
            if values.shape[-1] != CANDIDATE_FEATURE_DIM:
                raise ValueError("AdvanceRight candidate feature dim differs")
            candidate_values[index, : len(rows)] = values
            candidate_mask[index, : len(rows)] = True
    return {
        "candidate_values": candidate_values.to(device),
        "candidate_mask": candidate_mask.to(device),
        "source_side_values": source["side_values"].to(device),
        "source_member_values": source["member_values"].to(device),
        "source_member_mask": source["member_mask"].to(device),
        "source_arm_values": source["arm_values"].to(device),
        "source_arm_mask": source["arm_mask"].to(device),
        "target_side_values": target["side_values"].to(device),
        "target_member_values": target["member_values"].to(device),
        "target_member_mask": target["member_mask"].to(device),
        "target_arm_values": target["arm_values"].to(device),
        "target_arm_mask": target["arm_mask"].to(device),
        "examples": list(examples),
    }


def structured_candidate_exact(
    selected_candidate_ids: Sequence[str],
    acceptable_groups: Sequence[Sequence[str]],
) -> bool:
    selected = tuple(str(value) for value in selected_candidate_ids)
    groups = [set(str(value) for value in group) for group in acceptable_groups]
    if len(selected) != len(groups) or len(set(selected)) != len(selected):
        return False
    if not groups:
        return not selected

    def assign(group_index: int, remaining: set[str]) -> bool:
        if group_index == len(groups):
            return not remaining
        for candidate_id in sorted(groups[group_index] & remaining):
            if assign(group_index + 1, remaining - {candidate_id}):
                return True
        return False

    order = sorted(range(len(groups)), key=lambda index: len(groups[index]))
    ordered = [groups[index] for index in order]
    groups[:] = ordered
    return assign(0, set(selected))


def score_advance_right_examples(
    model: TargetAAdvanceRightConditionalDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source = list(examples[start : start + batch_size])
            batch = collate_advance_right_batch(source, device=device)
            outputs = model(
                **{
                    key: value
                    for key, value in batch.items()
                    if key != "examples"
                }
            )
            candidate_probs = torch.sigmoid(
                outputs["candidate_logits"]
            ).cpu()
            plan_probs = torch.softmax(
                outputs["plan_type_logits"],
                dim=-1,
            ).cpu()
            cardinality_probs = torch.softmax(
                outputs["cardinality_logits"],
                dim=-1,
            ).cpu()
            safety_probs = torch.sigmoid(outputs["safety_logits"]).cpu()
            for index, example in enumerate(source):
                count = len(example["candidate_rows"])
                rows.append(
                    {
                        "case_key": str(example["case_key"]),
                        "object_id": str(example["object_id"]),
                        "fold": int(example["fold"]),
                        "truth_plan_type": str(
                            example["truth_plan_type"]
                        ),
                        "formal_truth_plan_type": str(
                            example["formal_truth_plan_type"]
                        ),
                        "conditional_target_reason": str(
                            example["conditional_target_reason"]
                        ),
                        "source_condition_plan_type": str(
                            example["source_condition_plan_type"]
                        ),
                        "fixed_swsd_road_ids": [
                            str(value)
                            for value in example["fixed_swsd_road_ids"]
                        ],
                        "truth_cardinality": int(
                            example["truth_cardinality"]
                        ),
                        "acceptable_candidate_groups": [
                            list(group)
                            for group in example[
                                "acceptable_candidate_groups"
                            ]
                        ],
                        "candidate_supervised": bool(
                            example["candidate_supervised"]
                        ),
                        "safety_target": bool(example["safety_target"]),
                        "adjacent_context_resolved": bool(
                            example["adjacent_context_resolved"]
                        ),
                        "candidate_road_ids": [
                            str(row["candidate_road_id"])
                            for row in example["candidate_rows"]
                        ],
                        "candidate_probabilities": [
                            float(value)
                            for value in candidate_probs[index, :count]
                        ],
                        "plan_type_probabilities": [
                            float(value) for value in plan_probs[index]
                        ],
                        "cardinality_probabilities": [
                            float(value)
                            for value in cardinality_probs[index]
                        ],
                        "safety_probability": float(safety_probs[index]),
                    }
                )
    return rows


def decode_advance_right_scores(
    rows: Sequence[Mapping[str, Any]],
    *,
    safety_threshold: float,
    acceptance_threshold: float,
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        unconstrained_index = _argmax(row["plan_type_probabilities"])
        unconstrained_plan_type = PLAN_TYPES[unconstrained_index]
        constrained_plan_type = str(row["source_condition_plan_type"])
        plan_type = constrained_plan_type
        plan_index = PLAN_TYPE_INDEX[plan_type]
        cardinality_index = _argmax(row["cardinality_probabilities"])
        candidate_ids = list(row["candidate_road_ids"])
        candidate_probs = [
            float(value) for value in row["candidate_probabilities"]
        ]
        if plan_type == "SWSD_ONLY" or plan_type not in AUTOMATIC_PLAN_TYPES:
            cardinality = 0
        else:
            cardinality = min(
                max(1, cardinality_index),
                len(candidate_ids),
            )
        order = sorted(
            range(len(candidate_ids)),
            key=lambda index: (-candidate_probs[index], candidate_ids[index]),
        )
        selected_indices = order[:cardinality]
        selected_ids = sorted(candidate_ids[index] for index in selected_indices)
        selected_swsd_ids = (
            sorted(str(value) for value in row["fixed_swsd_road_ids"])
            if plan_type in {"SWSD_ONLY", "MIXED_SPLICE"}
            else []
        )
        candidate_exact = structured_candidate_exact(
            selected_ids,
            row["acceptable_candidate_groups"],
        )
        plan_exact = (
            plan_type == row["truth_plan_type"]
            and (
                candidate_exact
                if plan_type in AUTOMATIC_PLAN_TYPES
                else not selected_ids
            )
        )
        candidate_confidence = _candidate_set_confidence(
            candidate_probs,
            selected_indices,
        )
        confidence = min(
            float(row["plan_type_probabilities"][plan_index]),
            float(row["cardinality_probabilities"][cardinality_index]),
            candidate_confidence,
        )
        safety_pass = (
            float(row["safety_probability"]) >= safety_threshold
        )
        confidence_pass = confidence >= acceptance_threshold
        automatic = bool(
            plan_type in AUTOMATIC_PLAN_TYPES
            and safety_pass
            and confidence_pass
        )
        result.append(
            {
                **row,
                "unconstrained_predicted_plan_type": (
                    unconstrained_plan_type
                ),
                "predicted_plan_type": plan_type,
                "predicted_cardinality": cardinality,
                "raw_selected_candidate_road_ids": selected_ids,
                "raw_selected_fixed_swsd_road_ids": selected_swsd_ids,
                "candidate_acceptable_exact": (
                    candidate_exact
                    if bool(row["candidate_supervised"])
                    else None
                ),
                "raw_plan_exact": plan_exact,
                "confidence": confidence,
                "safety_threshold": safety_threshold,
                "acceptance_threshold": acceptance_threshold,
                "safety_pass": safety_pass,
                "confidence_pass": confidence_pass,
                "automatic_decision": automatic,
                "effective_decision": (
                    plan_type if automatic else "ABSTAIN"
                ),
                "unsafe_automatic": bool(
                    automatic
                    and (
                        not bool(row["safety_target"])
                        or not plan_exact
                    )
                ),
                "positive_keep_swsd": bool(
                    automatic and plan_type == "SWSD_ONLY"
                ),
            }
        )
    return result


def choose_zero_unsafe_safety_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["safety_probability"]) for row in rows],
        }
    )
    best = (0, -1.0, 1.000001)
    for threshold in thresholds:
        accepted = [
            row
            for row in rows
            if float(row["safety_probability"]) >= threshold
        ]
        unsafe = sum(not bool(row["safety_target"]) for row in accepted)
        safe = sum(bool(row["safety_target"]) for row in accepted)
        key = (-unsafe, safe, -threshold)
        if unsafe == 0 and key > best:
            best = (0, safe, -threshold)
    return -best[2]


def choose_zero_error_acceptance_threshold(
    decoded_rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["confidence"]) for row in decoded_rows],
        }
    )
    best_threshold = 1.000001
    best_count = -1
    for threshold in thresholds:
        accepted = [
            row
            for row in decoded_rows
            if bool(row["safety_pass"])
            and str(row["predicted_plan_type"]) in AUTOMATIC_PLAN_TYPES
            and float(row["confidence"]) >= threshold
        ]
        wrong = sum(
            not bool(row["safety_target"])
            or not bool(row["raw_plan_exact"])
            for row in accepted
        )
        if wrong == 0 and (
            len(accepted) > best_count
            or (
                len(accepted) == best_count
                and threshold < best_threshold
            )
        ):
            best_threshold = threshold
            best_count = len(accepted)
    return best_threshold


def advance_right_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("AdvanceRight metrics require rows")
    candidate_rows = [
        row for row in rows if bool(row["candidate_supervised"])
    ]
    automatic = [
        row for row in rows if bool(row["automatic_decision"])
    ]
    plan_types: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts = plan_types[str(row["truth_plan_type"])]
        counts["support"] += 1
        counts["type_exact"] += int(
            str(row["predicted_plan_type"])
            == str(row["truth_plan_type"])
        )
        counts["automatic"] += int(bool(row["automatic_decision"]))
        counts["unsafe"] += int(bool(row["unsafe_automatic"]))
    return {
        "count": len(rows),
        "candidate_supervised_count": len(candidate_rows),
        "candidate_acceptable_exact": (
            sum(bool(row["candidate_acceptable_exact"]) for row in candidate_rows)
            / len(candidate_rows)
            if candidate_rows
            else 0.0
        ),
        "plan_type_exact": sum(
            str(row["predicted_plan_type"]) == str(row["truth_plan_type"])
            for row in rows
        )
        / len(rows),
        "raw_plan_exact": sum(bool(row["raw_plan_exact"]) for row in rows)
        / len(rows),
        "safety_target_count": sum(
            bool(row["safety_target"]) for row in rows
        ),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / len(rows),
        "automatic_exact": (
            sum(bool(row["raw_plan_exact"]) for row in automatic)
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_automatic_count": sum(
            bool(row["unsafe_automatic"]) for row in rows
        ),
        "positive_keep_swsd_count": sum(
            bool(row["positive_keep_swsd"]) for row in rows
        ),
        "fallback_count": len(rows) - len(automatic),
        "per_truth_plan_type": {
            plan_type: {
                "support": counts["support"],
                "plan_type_exact": (
                    counts["type_exact"] / counts["support"]
                    if counts["support"]
                    else 0.0
                ),
                "automatic_count": counts["automatic"],
                "unsafe_automatic_count": counts["unsafe"],
            }
            for plan_type, counts in sorted(plan_types.items())
        },
    }


def _fit_model(
    training: Sequence[Mapping[str, Any]],
    validation: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    batch_size: int,
    device: torch.device,
    max_epochs: int,
    patience: int,
    learning_rate: float,
    weight_decay: float,
) -> dict[str, Any]:
    model = _new_model(seed, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    no_improvement = 0
    history = []
    for epoch in range(1, max_epochs + 1):
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            seed=seed * 1000 + epoch,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= patience:
                break
    if best_state is None:
        raise RuntimeError("AdvanceRight training produced no checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_fixed_epochs(
    training: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    batch_size: int,
    device: torch.device,
    epoch_count: int,
    learning_rate: float,
    weight_decay: float,
) -> dict[str, Any]:
    model = _new_model(seed, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    history = []
    for epoch in range(1, epoch_count + 1):
        loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            seed=seed * 1000 + epoch,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        history.append({"epoch": epoch, "train_loss": loss})
    model.eval()
    return {"model": model, "history": history}


def _train_epoch(
    model: TargetAAdvanceRightConditionalDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    optimizer: torch.optim.Optimizer,
    seed: int,
    batch_size: int,
    device: torch.device,
    plan_weights: torch.Tensor,
    safety_negative_weight: float,
) -> float:
    model.train()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    count = 0
    for start in range(0, len(order), batch_size):
        rows = [examples[index] for index in order[start : start + batch_size]]
        optimizer.zero_grad(set_to_none=True)
        loss = _batch_loss(
            model,
            rows,
            device=device,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        total += float(loss.item()) * len(rows)
        count += len(rows)
    return total / max(count, 1)


def _evaluate_loss(
    model: TargetAAdvanceRightConditionalDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
    plan_weights: torch.Tensor,
    safety_negative_weight: float,
) -> float:
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = list(examples[start : start + batch_size])
            loss = _batch_loss(
                model,
                rows,
                device=device,
                plan_weights=plan_weights,
                safety_negative_weight=safety_negative_weight,
            )
            total += float(loss.item()) * len(rows)
            count += len(rows)
    return total / max(count, 1)


def _batch_loss(
    model: TargetAAdvanceRightConditionalDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
    plan_weights: torch.Tensor,
    safety_negative_weight: float,
) -> torch.Tensor:
    batch = collate_advance_right_batch(examples, device=device)
    outputs = model(
        **{key: value for key, value in batch.items() if key != "examples"}
    )
    plan_targets = torch.tensor(
        [int(row["plan_type_index"]) for row in examples],
        dtype=torch.long,
        device=device,
    )
    plan_loss = nn.functional.cross_entropy(
        outputs["plan_type_logits"],
        plan_targets,
        weight=plan_weights,
    )
    safety_targets = torch.tensor(
        [float(bool(row["safety_target"])) for row in examples],
        dtype=torch.float32,
        device=device,
    )
    safety_losses = nn.functional.binary_cross_entropy_with_logits(
        outputs["safety_logits"],
        safety_targets,
        reduction="none",
    )
    safety_weights = torch.where(
        safety_targets > 0.5,
        torch.ones_like(safety_targets),
        torch.full_like(safety_targets, safety_negative_weight),
    )
    safety_loss = (safety_losses * safety_weights).mean()
    supervised_indices = [
        index
        for index, row in enumerate(examples)
        if bool(row["candidate_supervised"])
    ]
    if supervised_indices:
        cardinality_targets = torch.tensor(
            [
                min(
                    int(examples[index]["truth_cardinality"]),
                    CARDINALITY_COUNT - 1,
                )
                for index in supervised_indices
            ],
            dtype=torch.long,
            device=device,
        )
        cardinality_loss = nn.functional.cross_entropy(
            outputs["cardinality_logits"][supervised_indices],
            cardinality_targets,
        )
        selection_losses = [
            _structured_selection_loss(
                outputs["candidate_logits"][index],
                examples[index],
                device=device,
            )
            for index in supervised_indices
        ]
        selection_loss = torch.stack(selection_losses).mean()
    else:
        zero = outputs["candidate_logits"].sum() * 0.0
        cardinality_loss = zero
        selection_loss = zero
    return (
        plan_loss
        + 0.8 * safety_loss
        + 0.7 * cardinality_loss
        + selection_loss
    )


def _structured_selection_loss(
    logits: torch.Tensor,
    example: Mapping[str, Any],
    *,
    device: torch.device,
) -> torch.Tensor:
    candidate_ids = [
        str(row["candidate_road_id"]) for row in example["candidate_rows"]
    ]
    index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    real_logits = logits[: len(candidate_ids)]
    probabilities = torch.sigmoid(real_logits)
    losses = []
    positive_indices: set[int] = set()
    for group in example["acceptable_candidate_groups"]:
        indices = [
            index_by_id[candidate_id]
            for candidate_id in group
            if candidate_id in index_by_id
        ]
        if not indices:
            raise ValueError("structured candidate group is unreachable")
        positive_indices.update(indices)
        miss_probability = torch.prod(
            1.0 - probabilities[indices]
        )
        losses.append(-torch.log((1.0 - miss_probability).clamp_min(1e-7)))
    negative_indices = [
        index
        for index in range(len(candidate_ids))
        if index not in positive_indices
    ]
    if negative_indices:
        losses.append(
            nn.functional.binary_cross_entropy_with_logits(
                real_logits[negative_indices],
                torch.zeros(
                    len(negative_indices),
                    dtype=torch.float32,
                    device=device,
                ),
            )
        )
    target_count = torch.tensor(
        float(example["truth_cardinality"]),
        dtype=torch.float32,
        device=device,
    )
    losses.append(
        0.25
        * nn.functional.smooth_l1_loss(
            probabilities.sum(),
            target_count,
        )
    )
    if not losses:
        return logits.sum() * 0.0
    return torch.stack(losses).mean()


def _collate_sides(
    examples: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, torch.Tensor]:
    contexts = [row[key] for row in examples]
    side_values = torch.tensor(
        [
            [
                *[float(value) for value in context["object_features"]],
                *[float(value) for value in context["plan_features"]],
                *[float(value) for value in context["status_features"]],
            ]
            for context in contexts
        ],
        dtype=torch.float32,
    )
    if side_values.shape[-1] != SIDE_FEATURE_DIM:
        raise ValueError("AdvanceRight side context dimension differs")
    max_members = max(
        1,
        max(len(context["road_members"]) for context in contexts),
    )
    max_arms = max(
        1,
        max(len(context["arm_rows"]) for context in contexts),
    )
    member_values = torch.zeros(
        (len(contexts), max_members, MEMBER_FEATURE_DIM),
        dtype=torch.float32,
    )
    member_mask = torch.zeros(
        (len(contexts), max_members),
        dtype=torch.bool,
    )
    arm_values = torch.zeros(
        (len(contexts), max_arms, ARM_FEATURE_DIM),
        dtype=torch.float32,
    )
    arm_mask = torch.zeros(
        (len(contexts), max_arms),
        dtype=torch.bool,
    )
    for index, context in enumerate(contexts):
        members = list(context["road_members"])
        arms = list(context["arm_rows"])
        if members:
            values = torch.tensor(
                [row["features"] for row in members],
                dtype=torch.float32,
            )
            if values.shape[-1] != MEMBER_FEATURE_DIM:
                raise ValueError("AdvanceRight member dimension differs")
            member_values[index, : len(members)] = values
            member_mask[index, : len(members)] = True
        if arms:
            values = torch.tensor(
                [row["features"] for row in arms],
                dtype=torch.float32,
            )
            if values.shape[-1] != ARM_FEATURE_DIM:
                raise ValueError("AdvanceRight arm dimension differs")
            arm_values[index, : len(arms)] = values
            arm_mask[index, : len(arms)] = True
    return {
        "side_values": side_values,
        "member_values": member_values,
        "member_mask": member_mask,
        "arm_values": arm_values,
        "arm_mask": arm_mask,
    }


def _new_model(
    seed: int,
    device: torch.device,
) -> TargetAAdvanceRightConditionalDecoder:
    random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    model = TargetAAdvanceRightConditionalDecoder().to(device)
    return model


def _plan_class_weights(
    examples: Sequence[Mapping[str, Any]],
    device: torch.device,
) -> torch.Tensor:
    counts = Counter(int(row["plan_type_index"]) for row in examples)
    total = len(examples)
    weights = [
        min(6.0, total / (len(PLAN_TYPES) * max(counts[index], 1)))
        for index in range(len(PLAN_TYPES))
    ]
    return torch.tensor(weights, dtype=torch.float32, device=device)


def _safety_negative_weight(
    examples: Sequence[Mapping[str, Any]],
) -> float:
    positive = sum(bool(row["safety_target"]) for row in examples)
    negative = len(examples) - positive
    return min(8.0, max(1.0, positive / max(negative, 1)))


def _candidate_set_confidence(
    probabilities: Sequence[float],
    selected_indices: Sequence[int],
) -> float:
    if not probabilities:
        return 1.0
    selected = set(selected_indices)
    decisions = [
        probability if index in selected else 1.0 - probability
        for index, probability in enumerate(probabilities)
    ]
    return min(decisions)


def _argmax(values: Sequence[float]) -> int:
    if not values:
        raise ValueError("argmax values are empty")
    return max(range(len(values)), key=lambda index: (values[index], -index))


def _assert_case_disjoint(
    training: Sequence[Mapping[str, Any]],
    validation: Sequence[Mapping[str, Any]],
) -> None:
    if {row["case_key"] for row in training} & {
        row["case_key"] for row in validation
    }:
        raise ValueError("AdvanceRight Case leaked across a fold")


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAAdvanceRightConditionalDecoder,
    fold: int,
    inner_fold: int,
    seed: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ADVANCE_RIGHT_CONDITIONAL_STRUCTURED_DECODER",
            "outer_fold": fold,
            "inner_validation_fold": inner_fold,
            "seed": seed,
            "epoch_count": epoch_count,
            "plan_types": list(PLAN_TYPES),
            "parameter_count": parameter_count(model),
            "model_state_dict": {
                key: value.detach().cpu()
                for key, value in sorted(model.state_dict().items())
            },
        },
        path,
    )


def _resolve_device(requested: str) -> torch.device:
    normalized = requested.casefold()
    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but unavailable")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported AdvanceRight device: {requested}")


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "PLAN_TYPES",
    "advance_right_metrics",
    "choose_zero_error_acceptance_threshold",
    "choose_zero_unsafe_safety_threshold",
    "collate_advance_right_batch",
    "conditional_plan_target",
    "decode_advance_right_scores",
    "read_advance_right_conditioned_examples",
    "run_advance_right_conditional_strict_nested_oof",
    "source_condition_plan_type",
    "structured_candidate_exact",
]
