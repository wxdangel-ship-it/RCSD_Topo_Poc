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
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_joint_network import (
    SIDE_SOURCE_RCSD,
    SIDE_SOURCE_SWSD,
    SIDE_SOURCE_UNRESOLVED,
    TargetAAdvanceRightJointAccessDecoder,
    trainable_parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_teacher_student import (
    read_advance_right_teacher_student_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    AUTOMATIC_PLAN_TYPES,
    CARDINALITY_COUNT,
    PLAN_TYPES,
    _structured_selection_loss,
    decode_advance_right_scores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_SOURCE_INDEX = {
    "SWSD": SIDE_SOURCE_SWSD,
    "RCSD": SIDE_SOURCE_RCSD,
    "UNRESOLVED": SIDE_SOURCE_UNRESOLVED,
}
_SOURCE_NAME_BY_INDEX = {
    value: key for key, value in _SOURCE_INDEX.items()
}
_ROAD_CARDINALITY_ORDINAL_LOSS_WEIGHT = 0.5
_ROAD_MEMBER_MASS_LOSS_WEIGHT = 0.2


def run_advance_right_joint_access_strict_nested_oof(
    *,
    access_set_store_root: Path,
    output_root: Path,
    seed: int,
    ordinary_oof_root: Path | None = None,
    ordinary_encoder_oof_root: Path | None = None,
    freeze_pretrained_ordinary: bool = False,
    batch_size: int = 32,
    requested_device: str = "cuda",
    max_epochs: int = 100,
    patience: int = 15,
    learning_rate: float = 4e-4,
    ordinary_learning_rate_scale: float = 1.0,
    weight_decay: float = 2e-4,
    minimum_acceptance_threshold: float = 0.0,
) -> Path:
    """Train ordinary side access and AdvanceRight as one locked dependency."""
    started = time.perf_counter()
    if min(batch_size, max_epochs, patience) < 1:
        raise ValueError("joint access training configuration is invalid")
    if freeze_pretrained_ordinary and ordinary_oof_root is None:
        raise ValueError("freezing ordinary requires a pretrained OOF root")
    if ordinary_encoder_oof_root is not None and ordinary_oof_root is None:
        raise ValueError(
            "ordinary encoder overlay requires a base pretrained OOF root"
        )
    if not 0.0 < ordinary_learning_rate_scale <= 1.0:
        raise ValueError(
            "ordinary learning-rate scale must be in (0, 1]"
        )
    store = normalize_runtime_path(access_set_store_root).resolve(strict=True)
    ordinary_root = (
        normalize_runtime_path(ordinary_oof_root).resolve(strict=True)
        if ordinary_oof_root is not None
        else None
    )
    ordinary_encoder_root = (
        normalize_runtime_path(ordinary_encoder_oof_root).resolve(strict=True)
        if ordinary_encoder_oof_root is not None
        else None
    )
    ordinary_pretraining_decoder_kind = (
        str(
            json.loads(
                (ordinary_root / "summary.json").read_text(encoding="utf-8")
            ).get("decoder_kind")
            or ""
        )
        if ordinary_root is not None
        else ""
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_advance_right_joint_access_examples(store)
    folds = sorted({int(row["fold"]) for row in examples})
    if len(folds) < 3:
        raise ValueError("joint access strict OOF requires three folds")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)
    predictions: list[dict[str, Any]] = []
    teacher_predictions: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    parameter_count = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
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
            ordinary_learning_rate_scale=ordinary_learning_rate_scale,
            weight_decay=weight_decay,
            ordinary_checkpoint=(
                ordinary_root
                / f"fold_{outer_fold}_inner_checkpoint.pt"
                if ordinary_root is not None
                else None
            ),
            ordinary_encoder_checkpoint=(
                ordinary_encoder_root
                / f"fold_{outer_fold}_inner_checkpoint.pt"
                if ordinary_encoder_root is not None
                else None
            ),
            freeze_pretrained_ordinary=freeze_pretrained_ordinary,
        )
        inner_rows = score_joint_access_examples(
            tuning["model"],
            inner_validation,
            batch_size=batch_size,
            device=device,
            teacher_forcing=False,
        )
        acceptance_threshold = max(
            minimum_acceptance_threshold,
            choose_zero_error_joint_threshold(inner_rows),
        )
        final = _fit_fixed_epochs(
            outer_training,
            seed=seed + outer_fold * 100 + 53,
            batch_size=batch_size,
            device=device,
            epoch_count=tuning["best_epoch"],
            learning_rate=learning_rate,
            ordinary_learning_rate_scale=ordinary_learning_rate_scale,
            weight_decay=weight_decay,
            ordinary_checkpoint=(
                ordinary_root / f"fold_{outer_fold}_checkpoint.pt"
                if ordinary_root is not None
                else None
            ),
            ordinary_encoder_checkpoint=(
                ordinary_encoder_root / f"fold_{outer_fold}_checkpoint.pt"
                if ordinary_encoder_root is not None
                else None
            ),
            freeze_pretrained_ordinary=freeze_pretrained_ordinary,
        )
        parameter_count = trainable_parameter_count(final["model"])
        outer_rows = apply_joint_release(
            score_joint_access_examples(
                final["model"],
                outer_validation,
                batch_size=batch_size,
                device=device,
                teacher_forcing=False,
            ),
            acceptance_threshold=acceptance_threshold,
        )
        teacher_rows = apply_joint_release(
            score_joint_access_examples(
                final["model"],
                outer_validation,
                batch_size=batch_size,
                device=device,
                teacher_forcing=True,
            ),
            acceptance_threshold=acceptance_threshold,
        )
        predictions.extend(outer_rows)
        teacher_predictions.extend(teacher_rows)
        checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            final["model"],
            checkpoint,
            seed=seed,
            outer_fold=outer_fold,
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
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "oof_metrics": joint_access_metrics(outer_rows),
            "teacher_metrics": joint_access_metrics(teacher_rows),
            "checkpoint": _input_record(checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(
            root / f"fold_{outer_fold}_summary.json",
            fold_summary,
        )
    predictions.sort(key=_row_key)
    teacher_predictions.sort(key=_row_key)
    prediction_path = root / "oof_predictions.jsonl"
    teacher_path = root / "teacher_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    _write_jsonl(teacher_path, teacher_predictions)
    metrics = joint_access_metrics(predictions)
    teacher_metrics = joint_access_metrics(teacher_predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_JOINT_ORDINARY_ACCESS_STRICT_NESTED_OOF",
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "torch_version": torch.__version__,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "patience": patience,
        "learning_rate": learning_rate,
        "ordinary_learning_rate_scale": ordinary_learning_rate_scale,
        "weight_decay": weight_decay,
        "fold_count": len(folds),
        "example_count": len(examples),
        "parameter_count": parameter_count,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "stop_gradient_between_stages": False,
        "teacher_forcing_contract": (
            "teacher ordinary source/complete Road set/access is used only "
            "as a scheduled training lock; strict OOF inference uses the "
            "same model's predicted role-separated ordinary state"
        ),
        "ordinary_pretrained": ordinary_root is not None,
        "ordinary_pretraining_decoder_kind": (
            ordinary_pretraining_decoder_kind
        ),
        "ordinary_encoder_overlay": ordinary_encoder_root is not None,
        "ordinary_pretrained_frozen": freeze_pretrained_ordinary,
        "truth_contract": (
            "all sides require an exact complete ordinary Road set; RCSD "
            "sides additionally require the distinct access parent Road"
        ),
        "metrics": metrics,
        "teacher_metrics": teacher_metrics,
        "folds": fold_summaries,
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "Road roles, geometry recipe and RoadGraph decoder validation "
            "remain pending"
            if metrics["unsafe_automatic_count"] == 0
            else "strict OOF automatic decisions contain end-to-end errors"
        ),
        "gate_pass": True,
        "inputs": {
            "access_set_summary": _input_record(store / "summary.json"),
            "features": _input_record(
                store / "advance_right_access_set_features.jsonl"
            ),
            "teacher_conditions": _input_record(
                store / "advance_right_teacher_conditions.jsonl"
            ),
            "labels": _input_record(
                store / "advance_right_training_labels.jsonl"
            ),
            **(
                {"ordinary_oof": _input_record(ordinary_root / "summary.json")}
                if ordinary_root is not None
                else {}
            ),
            **(
                {
                    "ordinary_encoder_oof": _input_record(
                        ordinary_encoder_root / "summary.json"
                    )
                }
                if ordinary_encoder_root is not None
                else {}
            ),
        },
        "outputs": {
            "oof_predictions": _input_record(prediction_path),
            "teacher_predictions": _input_record(teacher_path),
        },
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def read_advance_right_joint_access_examples(
    store_root: Path,
) -> list[dict[str, Any]]:
    root = normalize_runtime_path(store_root).resolve(strict=True)
    teacher, _ = read_advance_right_teacher_student_examples(root)
    base_features = {
        _row_key(row): row
        for row in _read_jsonl(
            root / "advance_right_access_set_features.jsonl"
        )
    }
    teacher_by_key = {_row_key(row): row for row in teacher}
    if set(base_features) != set(teacher_by_key):
        raise ValueError("joint access base/teacher scopes differ")
    examples = []
    for key in sorted(base_features):
        feature = base_features[key]
        if bool(feature.get("feature_uses_truth")):
            raise ValueError("joint access feature uses truth")
        if int(feature.get("terminal_input_count", 0)):
            raise ValueError("joint access feature contains terminal input")
        row = dict(teacher_by_key[key])
        row["base_feature"] = feature
        row["candidate_rows"] = list(feature["candidate_rows"])
        for side_name in ("source", "target"):
            supervision = _side_supervision(
                feature[f"{side_name}_side"],
                row[f"{side_name}_context"],
            )
            row[f"{side_name}_supervision"] = supervision
        row["joint_safety_target"] = bool(
            row["candidate_supervised"]
            and _side_truth_complete(row["source_supervision"])
            and _side_truth_complete(row["target_supervision"])
        )
        examples.append(row)
    return examples


def collate_joint_access_batch(
    examples: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
    teacher_forcing: bool,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("cannot collate empty joint access batch")
    candidate_values, candidate_mask = _collate_candidates(examples)
    source = _collate_side(examples, "source")
    target = _collate_side(examples, "target")
    result: dict[str, Any] = {
        "candidate_values": candidate_values.to(device),
        "candidate_mask": candidate_mask.to(device),
        **{
            f"source_{key}": value.to(device)
            for key, value in source.items()
            if not key.startswith("teacher_")
        },
        **{
            f"target_{key}": value.to(device)
            for key, value in target.items()
            if not key.startswith("teacher_")
        },
        "label_source_access_mask": source[
            "teacher_access_mask"
        ].to(device),
        "label_source_road_mask": source["teacher_road_mask"].to(device),
        "label_target_access_mask": target[
            "teacher_access_mask"
        ].to(device),
        "label_target_road_mask": target["teacher_road_mask"].to(device),
        "examples": list(examples),
    }
    if teacher_forcing:
        result.update(
            {
                "teacher_source_source": source[
                    "teacher_source"
                ].to(device),
                "teacher_source_road_mask": source[
                    "teacher_road_mask"
                ].to(device),
                "teacher_source_access_mask": source[
                    "teacher_access_mask"
                ].to(device),
                "teacher_target_source": target[
                    "teacher_source"
                ].to(device),
                "teacher_target_road_mask": target[
                    "teacher_road_mask"
                ].to(device),
                "teacher_target_access_mask": target[
                    "teacher_access_mask"
                ].to(device),
            }
        )
    return result


def score_joint_access_examples(
    model: TargetAAdvanceRightJointAccessDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
    teacher_forcing: bool,
) -> list[dict[str, Any]]:
    model.eval()
    scored: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source = list(examples[start : start + batch_size])
            batch = collate_joint_access_batch(
                source,
                device=device,
                teacher_forcing=teacher_forcing,
            )
            outputs = model(
                **{
                    key: value
                    for key, value in batch.items()
                    if key != "examples" and not key.startswith("label_")
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
            safety_probs = torch.sigmoid(
                outputs["safety_logits"]
            ).cpu()
            source_source_probs = torch.softmax(
                outputs["source_side_source_logits"],
                dim=-1,
            ).cpu()
            target_source_probs = torch.softmax(
                outputs["target_side_source_logits"],
                dim=-1,
            ).cpu()
            source_road_cardinality_probs = torch.softmax(
                outputs["source_side_road_cardinality_logits"],
                dim=-1,
            ).cpu()
            target_road_cardinality_probs = torch.softmax(
                outputs["target_side_road_cardinality_logits"],
                dim=-1,
            ).cpu()
            for index, example in enumerate(source):
                candidate_count = len(example["candidate_rows"])
                row = {
                    "case_key": str(example["case_key"]),
                    "object_id": str(example["object_id"]),
                    "fold": int(example["fold"]),
                    "truth_plan_type": str(example["truth_plan_type"]),
                    "formal_truth_plan_type": str(
                        example["formal_truth_plan_type"]
                    ),
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
                    "safety_target": bool(
                        example["joint_safety_target"]
                    ),
                    "fixed_swsd_road_ids": list(
                        example["fixed_swsd_road_ids"]
                    ),
                    "candidate_rows": [
                        {
                            "candidate_road_id": str(
                                candidate["candidate_road_id"]
                            )
                        }
                        for candidate in example["candidate_rows"]
                    ],
                    "candidate_road_ids": [
                        str(candidate["candidate_road_id"])
                        for candidate in example["candidate_rows"]
                    ],
                    "candidate_probabilities": [
                        float(value)
                        for value in candidate_probs[
                            index, :candidate_count
                        ]
                    ],
                    "plan_type_probabilities": [
                        float(value) for value in plan_probs[index]
                    ],
                    "cardinality_probabilities": [
                        float(value)
                        for value in cardinality_probs[index]
                    ],
                    "safety_probability": float(safety_probs[index]),
                    "label_weight": float(example["label_weight"]),
                    "teacher_forcing": teacher_forcing,
                }
                row.update(
                    _score_side(
                        example,
                        side_name="source",
                        source_probabilities=source_source_probs[index],
                        road_logits=outputs["source_side_road_logits"][
                            index
                        ],
                        road_cardinality_probabilities=(
                            source_road_cardinality_probs[index]
                        ),
                        access_logits=outputs[
                            "source_side_access_logits"
                        ][index],
                    )
                )
                row.update(
                    _score_side(
                        example,
                        side_name="target",
                        source_probabilities=target_source_probs[index],
                        road_logits=outputs["target_side_road_logits"][
                            index
                        ],
                        road_cardinality_probabilities=(
                            target_road_cardinality_probs[index]
                        ),
                        access_logits=outputs[
                            "target_side_access_logits"
                        ][index],
                    )
                )
                row["source_condition_plan_type"] = (
                    _source_condition_plan_type(
                        (
                            int(row["source_side_truth_source_index"])
                            if teacher_forcing
                            else int(
                                row[
                                    "source_side_predicted_source_index"
                                ]
                            )
                        ),
                        (
                            int(row["target_side_truth_source_index"])
                            if teacher_forcing
                            else int(
                                row[
                                    "target_side_predicted_source_index"
                                ]
                            )
                        ),
                    )
                )
                scored.append(row)
    decoded = decode_advance_right_scores(
        scored,
        safety_threshold=0.0,
        acceptance_threshold=0.0,
    )
    results = []
    for row in decoded:
        side_exact = bool(
            row["source_side_exact"] and row["target_side_exact"]
        )
        source_confidence = float(row["source_side_confidence"])
        target_confidence = float(row["target_side_confidence"])
        joint_confidence = min(
            float(row["confidence"]),
            float(row["safety_probability"]),
            source_confidence,
            target_confidence,
        )
        result = dict(row)
        result.update(
            {
                "ordinary_side_exact": side_exact,
                "raw_end_to_end_exact": bool(
                    side_exact and row["raw_plan_exact"]
                ),
                "joint_confidence": joint_confidence,
                "joint_input_complete": bool(
                    row["source_side_input_complete"]
                    and row["target_side_input_complete"]
                ),
                "automatic_decision": False,
                "unsafe_automatic": False,
                "positive_keep_swsd": False,
            }
        )
        results.append(result)
    return results


def choose_zero_error_joint_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["joint_confidence"]) for row in rows],
        }
    )
    best_count = -1
    best_threshold = 1.000001
    for threshold in thresholds:
        accepted = [
            row
            for row in rows
            if (
                bool(row["joint_input_complete"])
                and str(row["predicted_plan_type"])
                in AUTOMATIC_PLAN_TYPES
                and float(row["joint_confidence"]) >= threshold
            )
        ]
        if any(not bool(row["raw_end_to_end_exact"]) for row in accepted):
            continue
        if len(accepted) > best_count or (
            len(accepted) == best_count and threshold < best_threshold
        ):
            best_count = len(accepted)
            best_threshold = threshold
    return best_threshold


def apply_joint_release(
    rows: Sequence[Mapping[str, Any]],
    *,
    acceptance_threshold: float,
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        automatic = bool(
            row["joint_input_complete"]
            and str(row["predicted_plan_type"]) in AUTOMATIC_PLAN_TYPES
            and float(row["joint_confidence"]) >= acceptance_threshold
        )
        row.update(
            {
                "joint_acceptance_threshold": acceptance_threshold,
                "automatic_decision": automatic,
                "unsafe_automatic": bool(
                    automatic and not row["raw_end_to_end_exact"]
                ),
                "positive_keep_swsd": bool(
                    automatic
                    and str(row["predicted_plan_type"]) == "SWSD_ONLY"
                ),
                "effective_decision": (
                    str(row["predicted_plan_type"])
                    if automatic
                    else "ABSTAIN"
                ),
            }
        )
        result.append(row)
    return result


def joint_access_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("joint access metrics require rows")
    automatic = [row for row in rows if row["automatic_decision"]]
    source_supervised = 2 * len(rows)
    access_supervised = sum(
        bool(row[f"{side}_side_access_supervised"])
        for row in rows
        for side in ("source", "target")
    )
    road_supervised = sum(
        bool(row[f"{side}_side_road_supervised"])
        for row in rows
        for side in ("source", "target")
    )
    per_plan: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counter = per_plan[str(row["truth_plan_type"])]
        counter["support"] += 1
        counter["exact"] += int(bool(row["raw_end_to_end_exact"]))
        counter["automatic"] += int(bool(row["automatic_decision"]))
        counter["unsafe"] += int(bool(row["unsafe_automatic"]))
    return {
        "count": len(rows),
        "side_source_exact": sum(
            bool(row[f"{side}_side_source_exact"])
            for row in rows
            for side in ("source", "target")
        )
        / max(source_supervised, 1),
        "side_access_supervised_count": access_supervised,
        "side_access_exact": (
            sum(
                bool(row[f"{side}_side_access_exact"])
                for row in rows
                for side in ("source", "target")
                if row[f"{side}_side_access_supervised"]
            )
            / access_supervised
            if access_supervised
            else 0.0
        ),
        "side_road_set_supervised_count": road_supervised,
        "side_road_set_exact": (
            sum(
                bool(row[f"{side}_side_road_exact"])
                for row in rows
                for side in ("source", "target")
                if row[f"{side}_side_road_supervised"]
            )
            / road_supervised
            if road_supervised
            else 0.0
        ),
        "ordinary_side_exact": sum(
            bool(row["ordinary_side_exact"]) for row in rows
        )
        / len(rows),
        "raw_plan_exact": sum(
            bool(row["raw_plan_exact"]) for row in rows
        )
        / len(rows),
        "raw_end_to_end_exact": sum(
            bool(row["raw_end_to_end_exact"]) for row in rows
        )
        / len(rows),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / len(rows),
        "automatic_exact": (
            sum(bool(row["raw_end_to_end_exact"]) for row in automatic)
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
            key: {
                "support": values["support"],
                "raw_end_to_end_exact": (
                    values["exact"] / values["support"]
                ),
                "automatic_count": values["automatic"],
                "unsafe_automatic_count": values["unsafe"],
            }
            for key, values in sorted(per_plan.items())
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
    ordinary_learning_rate_scale: float,
    weight_decay: float,
    ordinary_checkpoint: Path | None = None,
    ordinary_encoder_checkpoint: Path | None = None,
    freeze_pretrained_ordinary: bool = False,
) -> dict[str, Any]:
    model = _new_model(
        seed,
        device,
        ordinary_checkpoint=ordinary_checkpoint,
        ordinary_encoder_checkpoint=ordinary_encoder_checkpoint,
        freeze_pretrained_ordinary=freeze_pretrained_ordinary,
    )
    optimizer = _new_optimizer(
        model,
        learning_rate=learning_rate,
        ordinary_learning_rate_scale=ordinary_learning_rate_scale,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    source_weights = _source_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    no_improvement = 0
    history = []
    for epoch in range(1, max_epochs + 1):
        teacher_ratio = max(0.35, 1.0 - 0.65 * epoch / max_epochs)
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            seed=seed * 1000 + epoch,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            source_weights=source_weights,
            safety_negative_weight=safety_negative_weight,
            teacher_forcing_ratio=teacher_ratio,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            source_weights=source_weights,
            safety_negative_weight=safety_negative_weight,
        )
        history.append(
            {
                "epoch": epoch,
                "teacher_forcing_ratio": teacher_ratio,
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
        raise RuntimeError("joint access training produced no checkpoint")
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
    ordinary_learning_rate_scale: float,
    weight_decay: float,
    ordinary_checkpoint: Path | None = None,
    ordinary_encoder_checkpoint: Path | None = None,
    freeze_pretrained_ordinary: bool = False,
) -> dict[str, Any]:
    model = _new_model(
        seed,
        device,
        ordinary_checkpoint=ordinary_checkpoint,
        ordinary_encoder_checkpoint=ordinary_encoder_checkpoint,
        freeze_pretrained_ordinary=freeze_pretrained_ordinary,
    )
    optimizer = _new_optimizer(
        model,
        learning_rate=learning_rate,
        ordinary_learning_rate_scale=ordinary_learning_rate_scale,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    source_weights = _source_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    history = []
    for epoch in range(1, epoch_count + 1):
        teacher_ratio = max(0.35, 1.0 - 0.65 * epoch / epoch_count)
        loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            seed=seed * 1000 + epoch,
            batch_size=batch_size,
            device=device,
            plan_weights=plan_weights,
            source_weights=source_weights,
            safety_negative_weight=safety_negative_weight,
            teacher_forcing_ratio=teacher_ratio,
        )
        history.append(
            {
                "epoch": epoch,
                "teacher_forcing_ratio": teacher_ratio,
                "train_loss": loss,
            }
        )
    model.eval()
    return {"model": model, "history": history}


def _train_epoch(
    model: TargetAAdvanceRightJointAccessDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    optimizer: torch.optim.Optimizer,
    seed: int,
    batch_size: int,
    device: torch.device,
    plan_weights: torch.Tensor,
    source_weights: torch.Tensor,
    safety_negative_weight: float,
    teacher_forcing_ratio: float,
) -> float:
    model.train()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    count = 0
    randomizer = random.Random(seed + 37)
    for start in range(0, len(order), batch_size):
        rows = [examples[index] for index in order[start : start + batch_size]]
        teacher_forcing = randomizer.random() < teacher_forcing_ratio
        optimizer.zero_grad(set_to_none=True)
        loss = _batch_loss(
            model,
            rows,
            device=device,
            plan_weights=plan_weights,
            source_weights=source_weights,
            safety_negative_weight=safety_negative_weight,
            teacher_forcing=teacher_forcing,
        )
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
        optimizer.step()
        total += float(loss.detach().item()) * len(rows)
        count += len(rows)
    return total / max(count, 1)


def _evaluate_loss(
    model: TargetAAdvanceRightJointAccessDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
    plan_weights: torch.Tensor,
    source_weights: torch.Tensor,
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
                source_weights=source_weights,
                safety_negative_weight=safety_negative_weight,
                teacher_forcing=False,
            )
            total += float(loss.item()) * len(rows)
            count += len(rows)
    return total / max(count, 1)


def _batch_loss(
    model: TargetAAdvanceRightJointAccessDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
    plan_weights: torch.Tensor,
    source_weights: torch.Tensor,
    safety_negative_weight: float,
    teacher_forcing: bool,
) -> torch.Tensor:
    batch = collate_joint_access_batch(
        examples,
        device=device,
        teacher_forcing=teacher_forcing,
    )
    outputs = model(
        **{
            key: value
            for key, value in batch.items()
            if key != "examples" and not key.startswith("label_")
        }
    )
    sample_weights = torch.tensor(
        [float(row["label_weight"]) for row in examples],
        dtype=torch.float32,
        device=device,
    )
    sample_weights = sample_weights / sample_weights.mean().clamp_min(1e-6)
    plan_targets = torch.tensor(
        [int(row["plan_type_index"]) for row in examples],
        dtype=torch.long,
        device=device,
    )
    plan_losses = nn.functional.cross_entropy(
        outputs["plan_type_logits"],
        plan_targets,
        weight=plan_weights,
        reduction="none",
    )
    plan_loss = _weighted_mean(plan_losses, sample_weights)
    source_losses = []
    road_losses = []
    road_cardinality_losses = []
    road_cardinality_ordinal_losses = []
    road_member_mass_losses = []
    road_loss_weights = []
    access_losses = []
    for side_name in ("source", "target"):
        targets = torch.tensor(
            [
                int(row[f"{side_name}_supervision"]["source_index"])
                for row in examples
            ],
            dtype=torch.long,
            device=device,
        )
        losses = nn.functional.cross_entropy(
            outputs[f"{side_name}_side_source_logits"],
            targets,
            weight=source_weights,
            reduction="none",
        )
        source_losses.append(_weighted_mean(losses, sample_weights))
        road_supervised = [
            index
            for index, row in enumerate(examples)
            if row[f"{side_name}_supervision"]["road_supervised"]
        ]
        for index in road_supervised:
            road_count = len(
                examples[index]["base_feature"][f"{side_name}_side"][
                    "road_candidates"
                ]
            )
            target_mask = batch[f"label_{side_name}_road_mask"][
                index, :road_count
            ].to(outputs[f"{side_name}_side_road_logits"].dtype)
            positive_count = target_mask.sum().clamp_min(1.0)
            negative_count = (
                torch.tensor(
                    float(road_count),
                    dtype=target_mask.dtype,
                    device=device,
                )
                - positive_count
            )
            road_losses.append(
                nn.functional.binary_cross_entropy_with_logits(
                    outputs[f"{side_name}_side_road_logits"][
                        index, :road_count
                    ],
                    target_mask,
                    pos_weight=(negative_count / positive_count).clamp(
                        min=1.0,
                        max=8.0,
                    ),
                )
            )
            target_count = int(target_mask.sum().item())
            road_cardinality_losses.append(
                nn.functional.cross_entropy(
                    outputs[f"{side_name}_side_road_cardinality_logits"][
                        index
                    ].unsqueeze(0),
                    torch.tensor(
                        [target_count],
                        dtype=torch.long,
                        device=device,
                    ),
                )
            )
            ordinal_key = (
                f"{side_name}_side_road_cardinality_ordinal_logits"
            )
            mass_key = f"{side_name}_side_soft_member_count"
            if ordinal_key in outputs:
                ordinal_logits = outputs[ordinal_key][index]
                thresholds = torch.arange(
                    ordinal_logits.shape[-1],
                    device=device,
                )
                ordinal_target = (
                    target_count > thresholds
                ).to(ordinal_logits.dtype)
                road_cardinality_ordinal_losses.append(
                    nn.functional.binary_cross_entropy_with_logits(
                        ordinal_logits,
                        ordinal_target,
                    )
                )
                road_member_mass_losses.append(
                    nn.functional.smooth_l1_loss(
                        outputs[mass_key][index],
                        torch.tensor(
                            float(target_count),
                            dtype=outputs[mass_key].dtype,
                            device=device,
                        ),
                    )
                )
            road_loss_weights.append(sample_weights[index])
        supervised = [
            index
            for index, row in enumerate(examples)
            if row[f"{side_name}_supervision"]["access_supervised"]
        ]
        for index in supervised:
            acceptable = batch[
                f"label_{side_name}_access_mask"
            ][index]
            log_probabilities = torch.log_softmax(
                outputs[f"{side_name}_side_access_logits"][index],
                dim=-1,
            )
            access_losses.append(
                (
                    -torch.logsumexp(
                        log_probabilities.masked_fill(
                            ~acceptable,
                            torch.finfo(log_probabilities.dtype).min,
                        ),
                        dim=-1,
                    )
                )
                * sample_weights[index]
            )
    source_loss = torch.stack(source_losses).mean()
    if road_losses:
        road_weights = torch.stack(road_loss_weights)
        road_loss = _weighted_mean(
            torch.stack(road_losses),
            road_weights,
        )
        road_cardinality_loss = _weighted_mean(
            torch.stack(road_cardinality_losses),
            road_weights,
        )
        road_cardinality_ordinal_loss = (
            _weighted_mean(
                torch.stack(road_cardinality_ordinal_losses),
                road_weights,
            )
            if road_cardinality_ordinal_losses
            else road_cardinality_loss * 0.0
        )
        road_member_mass_loss = (
            _weighted_mean(
                torch.stack(road_member_mass_losses),
                road_weights,
            )
            if road_member_mass_losses
            else road_cardinality_loss * 0.0
        )
    else:
        road_loss = outputs["safety_logits"].sum() * 0.0
        road_cardinality_loss = road_loss
        road_cardinality_ordinal_loss = road_loss
        road_member_mass_loss = road_loss
    access_loss = (
        torch.stack(access_losses).sum()
        / sample_weights[
            [
                index
                for index, row in enumerate(examples)
                for side_name in ("source", "target")
                if row[f"{side_name}_supervision"]["access_supervised"]
            ]
        ].sum().clamp_min(1e-6)
        if access_losses
        else outputs["safety_logits"].sum() * 0.0
    )
    safety_targets = torch.tensor(
        [float(row["joint_safety_target"]) for row in examples],
        dtype=torch.float32,
        device=device,
    )
    safety_losses = nn.functional.binary_cross_entropy_with_logits(
        outputs["safety_logits"],
        safety_targets,
        reduction="none",
    )
    safety_class_weights = torch.where(
        safety_targets > 0.5,
        torch.ones_like(safety_targets),
        torch.full_like(safety_targets, safety_negative_weight),
    )
    safety_loss = _weighted_mean(
        safety_losses,
        sample_weights * safety_class_weights,
    )
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
        cardinality_losses = nn.functional.cross_entropy(
            outputs["cardinality_logits"][supervised_indices],
            cardinality_targets,
            reduction="none",
        )
        cardinality_loss = _weighted_mean(
            cardinality_losses,
            sample_weights[supervised_indices],
        )
        selection_losses = torch.stack(
            [
                _structured_selection_loss(
                    outputs["candidate_logits"][index],
                    examples[index],
                    device=device,
                )
                for index in supervised_indices
            ]
        )
        selection_loss = _weighted_mean(
            selection_losses,
            sample_weights[supervised_indices],
        )
    else:
        zero = outputs["candidate_logits"].sum() * 0.0
        cardinality_loss = zero
        selection_loss = zero
    return (
        plan_loss
        + 0.8 * source_loss
        + 0.8 * road_loss
        + 0.4 * road_cardinality_loss
        + _ROAD_CARDINALITY_ORDINAL_LOSS_WEIGHT
        * road_cardinality_ordinal_loss
        + _ROAD_MEMBER_MASS_LOSS_WEIGHT * road_member_mass_loss
        + 0.8 * access_loss
        + 0.8 * safety_loss
        + 0.7 * cardinality_loss
        + selection_loss
    )


def _collate_candidates(
    examples: Sequence[Mapping[str, Any]],
) -> tuple[torch.Tensor, torch.Tensor]:
    count = max(1, max(len(row["candidate_rows"]) for row in examples))
    values = torch.zeros((len(examples), count, 50), dtype=torch.float32)
    mask = torch.zeros((len(examples), count), dtype=torch.bool)
    for index, example in enumerate(examples):
        rows = example["candidate_rows"]
        if not rows:
            continue
        features = torch.tensor(
            [row["local_feature_values"] for row in rows],
            dtype=torch.float32,
        )
        if features.shape[-1] != 50:
            raise ValueError("joint AdvanceRight candidate dim differs")
        values[index, : len(rows)] = features
        mask[index, : len(rows)] = True
    return values, mask


def _collate_side(
    examples: Sequence[Mapping[str, Any]],
    side_name: str,
) -> dict[str, torch.Tensor]:
    sides = [row["base_feature"][f"{side_name}_side"] for row in examples]
    road_count = max(1, max(len(side["road_candidates"]) for side in sides))
    access_count = max(
        1,
        max(len(side["access_candidates"]) for side in sides),
    )
    road_values = torch.zeros(
        (len(sides), road_count, 40),
        dtype=torch.float32,
    )
    road_mask = torch.zeros(
        (len(sides), road_count),
        dtype=torch.bool,
    )
    access_values = torch.zeros(
        (len(sides), access_count, 64),
        dtype=torch.float32,
    )
    access_mask = torch.zeros(
        (len(sides), access_count),
        dtype=torch.bool,
    )
    teacher_access_mask = torch.zeros_like(access_mask)
    teacher_road_mask = torch.zeros_like(road_mask)
    for index, (example, side) in enumerate(zip(examples, sides, strict=True)):
        roads = side["road_candidates"]
        accesses = side["access_candidates"]
        if roads:
            road_values[index, : len(roads)] = torch.tensor(
                [row["feature_values"] for row in roads],
                dtype=torch.float32,
            )
            road_mask[index, : len(roads)] = True
        if accesses:
            access_values[index, : len(accesses)] = torch.tensor(
                [row["feature_values"] for row in accesses],
                dtype=torch.float32,
            )
            access_mask[index, : len(accesses)] = True
        acceptable = example[f"{side_name}_supervision"][
            "acceptable_access_indices"
        ]
        for candidate_index in acceptable:
            teacher_access_mask[index, candidate_index] = True
        for candidate_index in example[f"{side_name}_supervision"][
            "acceptable_road_indices"
        ]:
            teacher_road_mask[index, candidate_index] = True
    return {
        "object_values": torch.tensor(
            [side["object_feature_values"] for side in sides],
            dtype=torch.float32,
        ),
        "road_values": road_values,
        "road_mask": road_mask,
        "access_values": access_values,
        "access_mask": access_mask,
        "teacher_source": torch.tensor(
            [
                row[f"{side_name}_supervision"]["source_index"]
                for row in examples
            ],
            dtype=torch.long,
        ),
        "teacher_road_mask": teacher_road_mask,
        "teacher_access_mask": teacher_access_mask,
    }


def _score_side(
    example: Mapping[str, Any],
    *,
    side_name: str,
    source_probabilities: torch.Tensor,
    road_logits: torch.Tensor,
    road_cardinality_probabilities: torch.Tensor,
    access_logits: torch.Tensor,
) -> dict[str, Any]:
    supervision = example[f"{side_name}_supervision"]
    predicted_source = int(source_probabilities.argmax().item())
    source_confidence = float(source_probabilities[predicted_source])
    base_side = example["base_feature"][f"{side_name}_side"]
    road_rows = base_side["road_candidates"]
    road_probabilities = torch.sigmoid(
        road_logits[: len(road_rows)]
    ).cpu()
    predicted_source_name = _SOURCE_NAME_BY_INDEX[predicted_source]
    valid_road_indices = [
        index
        for index, row in enumerate(road_rows)
        if str(row.get("source") or "") == predicted_source_name
    ]
    predicted_road_count = (
        max(
            1,
            min(
                int(road_cardinality_probabilities.argmax().item()),
                len(valid_road_indices),
            ),
        )
        if valid_road_indices
        else 0
    )
    road_order = sorted(
        valid_road_indices,
        key=lambda index: (
            -float(road_probabilities[index]),
            str(road_rows[index]["road_id"]),
        ),
    )
    selected_road_indices = road_order[:predicted_road_count]
    predicted_road_ids = sorted(
        str(road_rows[index]["road_id"]) for index in selected_road_indices
    )
    selected_index_set = set(selected_road_indices)
    road_decision_confidences = [
        (
            float(probability)
            if index in selected_index_set
            else 1.0 - float(probability)
        )
        for index, probability in enumerate(road_probabilities)
        if index in set(valid_road_indices)
    ]
    road_confidence = min(
        [
            float(
                road_cardinality_probabilities[predicted_road_count]
            ),
            *road_decision_confidences,
        ]
    )
    access_rows = base_side["access_candidates"]
    predicted_access_index = -1
    predicted_access_road_id = ""
    access_confidence = 0.0
    if access_rows:
        probabilities = torch.softmax(
            access_logits[: len(access_rows)],
            dim=-1,
        ).cpu()
        predicted_access_index = int(probabilities.argmax().item())
        predicted_access_road_id = str(
            access_rows[predicted_access_index]["road_id"]
        )
        access_confidence = float(probabilities[predicted_access_index])
    source_exact = predicted_source == int(supervision["source_index"])
    road_supervised = bool(supervision["road_supervised"])
    road_exact = (
        predicted_road_ids == list(supervision["acceptable_road_ids"])
        if road_supervised
        else True
    )
    access_supervised = bool(supervision["access_supervised"])
    access_exact = (
        predicted_access_road_id
        in set(supervision["acceptable_access_road_ids"])
        if access_supervised
        else True
    )
    side_exact = bool(
        source_exact
        and predicted_source != SIDE_SOURCE_UNRESOLVED
        and road_supervised
        and road_exact
        and (
            predicted_source != SIDE_SOURCE_RCSD
            or (access_supervised and access_exact)
        )
    )
    input_complete = bool(
        predicted_source != SIDE_SOURCE_UNRESOLVED
        and bool(predicted_road_ids)
        and (
            predicted_source != SIDE_SOURCE_RCSD
            or predicted_access_index >= 0
        )
    )
    confidence = (
        min(source_confidence, road_confidence, access_confidence)
        if predicted_source == SIDE_SOURCE_RCSD
        else min(source_confidence, road_confidence)
    )
    return {
        f"{side_name}_side_truth_source_index": int(
            supervision["source_index"]
        ),
        f"{side_name}_side_predicted_source_index": predicted_source,
        f"{side_name}_side_source_probability": source_confidence,
        f"{side_name}_side_source_exact": source_exact,
        f"{side_name}_side_road_supervised": road_supervised,
        f"{side_name}_side_truth_road_ids": list(
            supervision["acceptable_road_ids"]
        ),
        f"{side_name}_side_predicted_road_ids": predicted_road_ids,
        f"{side_name}_side_predicted_road_count": predicted_road_count,
        f"{side_name}_side_road_probability": road_confidence,
        f"{side_name}_side_road_exact": road_exact,
        f"{side_name}_side_access_supervised": access_supervised,
        f"{side_name}_side_predicted_access_index": predicted_access_index,
        f"{side_name}_side_predicted_access_road_id": (
            predicted_access_road_id
        ),
        f"{side_name}_side_access_probability": access_confidence,
        f"{side_name}_side_access_exact": access_exact,
        f"{side_name}_side_exact": side_exact,
        f"{side_name}_side_input_complete": input_complete,
        f"{side_name}_side_confidence": confidence,
    }


def _side_supervision(
    base_side: Mapping[str, Any],
    teacher_context: Mapping[str, Any],
) -> dict[str, Any]:
    source = str(teacher_context.get("data_source", "UNRESOLVED"))
    if source not in _SOURCE_INDEX:
        raise ValueError(f"unsupported ordinary access source: {source}")
    acceptable_road_ids = tuple(
        sorted(
            {
                str(row["road_id"])
                for row in teacher_context.get("access_rows", ())
                if str(row.get("road_id", ""))
            }
        )
    )
    complete_road_ids = tuple(
        sorted(
            {
                str(row["road_id"])
                for row in teacher_context.get("road_members", ())
                if str(row.get("road_id", ""))
            }
        )
    )
    road_indices = tuple(
        index
        for index, row in enumerate(base_side["road_candidates"])
        if str(row["road_id"]) in set(complete_road_ids)
    )
    road_supervised = bool(
        teacher_context.get("resolved")
        and complete_road_ids
        and len(road_indices) == len(complete_road_ids)
    )
    acceptable_indices = tuple(
        index
        for index, row in enumerate(base_side["access_candidates"])
        if str(row["road_id"]) in set(acceptable_road_ids)
    )
    access_supervised = bool(
        source == "RCSD"
        and teacher_context.get("required_access_resolved")
        and acceptable_road_ids
        and acceptable_indices
    )
    return {
        "source_index": _SOURCE_INDEX[source],
        "source_name": source,
        "acceptable_road_ids": complete_road_ids,
        "acceptable_road_indices": road_indices,
        "road_supervised": road_supervised,
        "acceptable_access_road_ids": acceptable_road_ids,
        "acceptable_access_indices": acceptable_indices,
        "access_supervised": access_supervised,
    }


def _side_truth_complete(supervision: Mapping[str, Any]) -> bool:
    source = int(supervision["source_index"])
    if source == SIDE_SOURCE_SWSD:
        return bool(supervision["road_supervised"])
    if source == SIDE_SOURCE_RCSD:
        return bool(
            supervision["road_supervised"]
            and supervision["access_supervised"]
        )
    return False


def _source_condition_plan_type(
    source: int,
    target: int,
) -> str:
    if SIDE_SOURCE_UNRESOLVED in {source, target}:
        return "REVIEW_FALLBACK"
    if source == target == SIDE_SOURCE_SWSD:
        return "SWSD_ONLY"
    if source == target == SIDE_SOURCE_RCSD:
        return "RCSD_ONLY"
    if {source, target} == {SIDE_SOURCE_SWSD, SIDE_SOURCE_RCSD}:
        return "MIXED_SPLICE"
    return "REVIEW_FALLBACK"


def _new_model(
    seed: int,
    device: torch.device,
    *,
    ordinary_checkpoint: Path | None = None,
    ordinary_encoder_checkpoint: Path | None = None,
    freeze_pretrained_ordinary: bool = False,
) -> TargetAAdvanceRightJointAccessDecoder:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    checkpoint = None
    road_cardinality_count = 65
    ordinary_decoder_kind = "BASE_SET"
    if ordinary_checkpoint is not None:
        checkpoint = torch.load(
            ordinary_checkpoint,
            map_location="cpu",
            weights_only=False,
        )
        road_cardinality_count = int(
            checkpoint.get("config", {}).get("cardinality_count", 65)
        )
        if checkpoint.get("stage") == "ORDINARY_COUNT_AWARE_ROLE_SET_DECODER":
            ordinary_decoder_kind = "COUNT_AWARE_SET"
    model = TargetAAdvanceRightJointAccessDecoder(
        road_cardinality_count=road_cardinality_count,
        ordinary_decoder_kind=ordinary_decoder_kind,
        stop_gradient_between_stages=False,
    )
    if checkpoint is not None:
        if int(checkpoint["object_dim"]) != 64:
            raise ValueError("pretrained ordinary object dimension differs")
        if int(checkpoint["candidate_dim"]) != 40:
            raise ValueError("pretrained ordinary Road dimension differs")
        model.load_ordinary_road_state_dict(checkpoint["state_dict"])
        if ordinary_encoder_checkpoint is not None:
            encoder_checkpoint = torch.load(
                ordinary_encoder_checkpoint,
                map_location="cpu",
                weights_only=False,
            )
            if int(encoder_checkpoint["object_dim"]) != 64:
                raise ValueError(
                    "pretrained ordinary encoder object dimension differs"
                )
            if int(encoder_checkpoint["candidate_dim"]) != 40:
                raise ValueError(
                    "pretrained ordinary encoder Road dimension differs"
                )
            model.load_ordinary_encoder_state_dict(
                encoder_checkpoint["state_dict"]
            )
        if freeze_pretrained_ordinary:
            for parameter in model.ordinary_road_decoder.parameters():
                parameter.requires_grad = False
    elif ordinary_encoder_checkpoint is not None:
        raise ValueError(
            "cannot overlay an ordinary encoder without a base decoder"
        )
    elif freeze_pretrained_ordinary:
        raise ValueError("cannot freeze an uninitialized ordinary decoder")
    return model.to(device)


def _new_optimizer(
    model: TargetAAdvanceRightJointAccessDecoder,
    *,
    learning_rate: float,
    ordinary_learning_rate_scale: float,
    weight_decay: float,
) -> torch.optim.Optimizer:
    ordinary = [
        parameter
        for parameter in model.ordinary_road_decoder.parameters()
        if parameter.requires_grad
    ]
    ordinary_ids = {id(parameter) for parameter in ordinary}
    downstream = [
        parameter
        for parameter in model.parameters()
        if parameter.requires_grad and id(parameter) not in ordinary_ids
    ]
    groups: list[dict[str, Any]] = []
    if downstream:
        groups.append(
            {
                "params": downstream,
                "lr": learning_rate,
            }
        )
    if ordinary:
        groups.append(
            {
                "params": ordinary,
                "lr": learning_rate * ordinary_learning_rate_scale,
            }
        )
    if not groups:
        raise ValueError("joint access optimizer has no trainable parameters")
    return torch.optim.AdamW(
        groups,
        weight_decay=weight_decay,
    )


def _plan_class_weights(
    examples: Sequence[Mapping[str, Any]],
    device: torch.device,
) -> torch.Tensor:
    counts = Counter(
        int(row["plan_type_index"]) for row in examples
    )
    values = [
        1.0 / max(counts[index], 1) ** 0.5
        for index in range(len(PLAN_TYPES))
    ]
    scale = len(values) / sum(values)
    return torch.tensor(
        [value * scale for value in values],
        dtype=torch.float32,
        device=device,
    )


def _source_class_weights(
    examples: Sequence[Mapping[str, Any]],
    device: torch.device,
) -> torch.Tensor:
    counts = Counter(
        int(row[f"{side}_supervision"]["source_index"])
        for row in examples
        for side in ("source", "target")
    )
    values = [
        1.0 / max(counts[index], 1) ** 0.5
        for index in range(3)
    ]
    scale = len(values) / sum(values)
    return torch.tensor(
        [value * scale for value in values],
        dtype=torch.float32,
        device=device,
    )


def _safety_negative_weight(
    examples: Sequence[Mapping[str, Any]],
) -> float:
    positive = sum(bool(row["joint_safety_target"]) for row in examples)
    negative = len(examples) - positive
    return min(8.0, positive / max(negative, 1)) if positive else 1.0


def _weighted_mean(
    values: torch.Tensor,
    weights: torch.Tensor,
) -> torch.Tensor:
    return (values * weights).sum() / weights.sum().clamp_min(1e-6)


def _assert_case_disjoint(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
) -> None:
    overlap = {str(row["case_key"]) for row in left} & {
        str(row["case_key"]) for row in right
    }
    if overlap:
        raise ValueError(f"joint access Case leakage: {sorted(overlap)}")


def _save_checkpoint(
    model: TargetAAdvanceRightJointAccessDecoder,
    path: Path,
    *,
    seed: int,
    outer_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ADVANCE_RIGHT_JOINT_ORDINARY_ACCESS",
            "seed": seed,
            "outer_fold": outer_fold,
            "epoch_count": epoch_count,
            "parameter_count": trainable_parameter_count(model),
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
    raise ValueError(f"unsupported joint access device: {requested}")


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
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


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


__all__ = [
    "apply_joint_release",
    "choose_zero_error_joint_threshold",
    "collate_joint_access_batch",
    "joint_access_metrics",
    "read_advance_right_joint_access_examples",
    "run_advance_right_joint_access_strict_nested_oof",
    "score_joint_access_examples",
]
