from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    conditioned_feature_view,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    AUTOMATIC_PLAN_TYPES,
    CARDINALITY_COUNT,
    PLAN_TYPE_INDEX,
    PLAN_TYPES,
    _assert_case_disjoint,
    _input_record,
    _new_model,
    _resolve_device,
    _save_checkpoint,
    _structured_selection_loss,
    _write_json,
    _write_jsonl,
    advance_right_metrics,
    choose_zero_error_acceptance_threshold,
    choose_zero_unsafe_safety_threshold,
    collate_advance_right_batch,
    conditional_plan_target,
    decode_advance_right_scores,
    score_advance_right_examples,
    source_condition_plan_type,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_advance_right_teacher_student_strict_nested_oof(
    *,
    access_set_store_root: Path,
    output_root: Path,
    seed: int,
    batch_size: int = 64,
    requested_device: str = "cuda",
    max_epochs: int = 120,
    patience: int = 18,
    learning_rate: float = 3e-4,
    weight_decay: float = 2e-4,
    minimum_acceptance_threshold: float = 0.0,
    dual_view_training: bool = False,
    oof_early_stopping: bool = False,
    teacher_training_loss_weight: float = 0.5,
    oof_training_loss_weight: float = 1.0,
    safety_negative_loss_weight: float | None = None,
    trust_locked_final_state: bool = False,
) -> Path:
    """Fit the conditional decoder and evaluate strict OOF ordinary state."""
    started = time.perf_counter()
    if min(batch_size, max_epochs, patience) < 1:
        raise ValueError("AdvanceRight teacher-student config is invalid")
    if dual_view_training and (
        min(teacher_training_loss_weight, oof_training_loss_weight) < 0.0
        or teacher_training_loss_weight + oof_training_loss_weight <= 0.0
    ):
        raise ValueError("AdvanceRight dual-view loss weights are invalid")
    if (
        safety_negative_loss_weight is not None
        and safety_negative_loss_weight <= 0.0
    ):
        raise ValueError("AdvanceRight safety negative weight is invalid")
    store = normalize_runtime_path(access_set_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    teacher, oof = read_advance_right_teacher_student_examples(
        store,
        trust_locked_final_state=trust_locked_final_state,
    )
    teacher_by_key = {_object_key(row): row for row in teacher}
    oof_by_key = {_object_key(row): row for row in oof}
    if set(teacher_by_key) != set(oof_by_key):
        raise ValueError("teacher and OOF AdvanceRight scopes differ")
    folds = sorted({int(row["fold"]) for row in teacher})
    if len(folds) < 3:
        raise ValueError("AdvanceRight strict OOF requires three folds")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)
    predictions = []
    teacher_predictions = []
    fold_summaries = []
    model_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
        inner_teacher_training = [
            row
            for row in teacher
            if int(row["fold"]) not in {outer_fold, inner_fold}
        ]
        inner_oof_training = [
            row
            for row in oof
            if int(row["fold"]) not in {outer_fold, inner_fold}
        ]
        inner_teacher_validation = [
            row for row in teacher if int(row["fold"]) == inner_fold
        ]
        inner_oof_calibration = [
            row for row in oof if int(row["fold"]) == inner_fold
        ]
        outer_teacher_training = [
            row for row in teacher if int(row["fold"]) != outer_fold
        ]
        outer_oof_training = [
            row for row in oof if int(row["fold"]) != outer_fold
        ]
        outer_teacher_validation = [
            row for row in teacher if int(row["fold"]) == outer_fold
        ]
        outer_oof_validation = [
            row for row in oof if int(row["fold"]) == outer_fold
        ]
        if dual_view_training:
            inner_training = weighted_training_views(
                inner_teacher_training,
                inner_oof_training,
                teacher_weight=teacher_training_loss_weight,
                oof_weight=oof_training_loss_weight,
            )
            outer_training = weighted_training_views(
                outer_teacher_training,
                outer_oof_training,
                teacher_weight=teacher_training_loss_weight,
                oof_weight=oof_training_loss_weight,
            )
        else:
            inner_training = inner_teacher_training
            outer_training = outer_teacher_training
        inner_early_stop_validation = (
            inner_oof_calibration
            if oof_early_stopping
            else inner_teacher_validation
        )
        _assert_case_disjoint(
            inner_training,
            inner_early_stop_validation,
        )
        _assert_case_disjoint(outer_training, outer_oof_validation)
        tuning = _fit_model(
            inner_training,
            inner_early_stop_validation,
            seed=seed + outer_fold * 100 + 17,
            batch_size=batch_size,
            device=device,
            max_epochs=max_epochs,
            patience=patience,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            safety_negative_loss_weight=safety_negative_loss_weight,
        )
        final = _fit_fixed_epochs(
            outer_training,
            seed=seed + outer_fold * 100 + 53,
            batch_size=batch_size,
            device=device,
            epoch_count=tuning["best_epoch"],
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            safety_negative_loss_weight=safety_negative_loss_weight,
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_advance_right_examples(
            tuning["model"],
            inner_oof_calibration,
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
            outer_oof_validation,
            batch_size=batch_size,
            device=device,
        )
        outer_decoded = decode_advance_right_scores(
            outer_scores,
            safety_threshold=safety_threshold,
            acceptance_threshold=acceptance_threshold,
        )
        teacher_scores = score_advance_right_examples(
            final["model"],
            outer_teacher_validation,
            batch_size=batch_size,
            device=device,
        )
        teacher_decoded = decode_advance_right_scores(
            teacher_scores,
            safety_threshold=safety_threshold,
            acceptance_threshold=acceptance_threshold,
        )
        outer_example_by_key = {
            _object_key(row): row for row in outer_oof_validation
        }
        teacher_example_by_key = {
            _object_key(row): row for row in outer_teacher_validation
        }
        for row in outer_decoded:
            example = outer_example_by_key[_object_key(row)]
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                    "evaluation_condition": "STRICT_OOF_ORDINARY",
                    "upstream_ordinary_road_set_exact": bool(
                        example["upstream_ordinary_road_set_exact"]
                    ),
                    "upstream_ordinary_source_exact": bool(
                        example["upstream_ordinary_source_exact"]
                    ),
                    "upstream_ordinary_access_exact": bool(
                        example["upstream_ordinary_access_exact"]
                    ),
                    "upstream_ordinary_complete_exact": bool(
                        example["upstream_ordinary_complete_exact"]
                    ),
                }
            )
        for row in teacher_decoded:
            example = teacher_example_by_key[_object_key(row)]
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                    "evaluation_condition": "TEACHER_ORDINARY",
                    "upstream_ordinary_road_set_exact": True,
                    "upstream_ordinary_source_exact": True,
                    "upstream_ordinary_access_exact": bool(
                        example["adjacent_access_road_resolved"]
                    ),
                    "upstream_ordinary_complete_exact": bool(
                        example["adjacent_access_road_resolved"]
                    ),
                }
            )
        predictions.extend(outer_decoded)
        teacher_predictions.extend(teacher_decoded)

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
            "dual_view_training": dual_view_training,
            "oof_early_stopping": oof_early_stopping,
            "safety_negative_loss_weight": safety_negative_loss_weight,
            "early_stopping_condition": (
                "STRICT_OOF_ORDINARY"
                if oof_early_stopping
                else "TEACHER_ORDINARY"
            ),
            "inner_training_view_count": len(inner_training),
            "inner_teacher_train_count": len(inner_teacher_training),
            "inner_oof_train_count": (
                len(inner_oof_training) if dual_view_training else 0
            ),
            "inner_teacher_validation_count": len(
                inner_teacher_validation
            ),
            "inner_oof_calibration_count": len(inner_oof_calibration),
            "outer_training_view_count": len(outer_training),
            "outer_teacher_train_count": len(outer_teacher_training),
            "outer_oof_train_count": (
                len(outer_oof_training) if dual_view_training else 0
            ),
            "outer_teacher_validation_count": len(
                outer_teacher_validation
            ),
            "outer_oof_validation_count": len(outer_oof_validation),
            "best_epoch": tuning["best_epoch"],
            "best_validation_loss": tuning["best_validation_loss"],
            "best_teacher_validation_loss": (
                None
                if oof_early_stopping
                else tuning["best_validation_loss"]
            ),
            "best_oof_validation_loss": (
                tuning["best_validation_loss"]
                if oof_early_stopping
                else None
            ),
            "safety_threshold": safety_threshold,
            "acceptance_threshold": acceptance_threshold,
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "oof_metrics": advance_right_metrics(outer_decoded),
            "teacher_metrics": advance_right_metrics(teacher_decoded),
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(
            root / f"fold_{outer_fold}_summary.json",
            fold_summary,
        )

    predictions.sort(key=lambda row: (row["case_key"], row["object_id"]))
    teacher_predictions.sort(
        key=lambda row: (row["case_key"], row["object_id"])
    )
    prediction_path = root / "oof_predictions.jsonl"
    teacher_prediction_path = root / "teacher_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    _write_jsonl(teacher_prediction_path, teacher_predictions)
    metrics = advance_right_metrics(predictions)
    teacher_metrics = advance_right_metrics(teacher_predictions)
    access_counts = Counter(
        "OOF_ACCESS_READY"
        if bool(row["adjacent_access_road_resolved"])
        else "OOF_ACCESS_UNKNOWN"
        for row in oof
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_TEACHER_STUDENT_STRICT_NESTED_OOF",
        "model_scope": (
            "Fit the conditional Road-set decoder with teacher and strict-OOF "
            "ordinary states." if dual_view_training else
            "Fit the conditional Road-set decoder with teacher ordinary "
            "complete Road/access state."
        ) + (
            " Calibrate and evaluate only with strict OOF ordinary state for "
            "the held-out Case."
        ),
        "teacher_forcing_contract": (
            "teacher conditions are stage-only label inputs and never enter "
            "the truth-free base feature file; outer evaluation consumes only "
            "ordinary predictions made without the held-out Case"
        ),
        "access_contract": (
            "a unique source may train the carrier type while an unknown exact "
            "access Road stays masked; complete safety is positive only when "
            "both locked access Roads are exact"
        ),
        "example_count": len(oof),
        "fold_count": len(folds),
        "seed": seed,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "patience": patience,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "minimum_acceptance_threshold": minimum_acceptance_threshold,
        "dual_view_training": dual_view_training,
        "oof_early_stopping": oof_early_stopping,
        "teacher_training_loss_weight": teacher_training_loss_weight,
        "oof_training_loss_weight": oof_training_loss_weight,
        "safety_negative_loss_weight": safety_negative_loss_weight,
        "trust_locked_final_state": trust_locked_final_state,
        "early_stopping_condition": (
            "STRICT_OOF_ORDINARY"
            if oof_early_stopping
            else "TEACHER_ORDINARY"
        ),
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
        "teacher_metrics": teacher_metrics,
        "access_counts": dict(sorted(access_counts.items())),
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "sample_weight_applied_to_loss": True,
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "complete attachment/split/splice and Node recipe heads are not "
            "yet trained; this run only validates teacher-to-OOF carrier and "
            "Road-set transfer under an exact-access release mask"
        ),
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "access_set_store": _input_record(store / "summary.json"),
        "predictions": _input_record(prediction_path),
        "teacher_predictions": _input_record(teacher_prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(oof)
            and len(teacher_predictions) == len(teacher)
            and {_object_key(row) for row in predictions}
            == set(oof_by_key)
            and {_object_key(row) for row in teacher_predictions}
            == set(teacher_by_key)
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight teacher-student OOF gate failed")
    return root


def weighted_training_views(
    teacher_rows: Sequence[Mapping[str, Any]],
    oof_rows: Sequence[Mapping[str, Any]],
    *,
    teacher_weight: float,
    oof_weight: float,
) -> list[dict[str, Any]]:
    """Create independent weighted teacher and strict-OOF training views."""
    if min(teacher_weight, oof_weight) < 0.0:
        raise ValueError("AdvanceRight training-view weights must be nonnegative")
    if teacher_weight + oof_weight <= 0.0:
        raise ValueError("AdvanceRight training-view weights cannot both be zero")
    teacher_by_key = _example_by_key(teacher_rows)
    oof_by_key = _example_by_key(oof_rows)
    if len(teacher_by_key) != len(teacher_rows):
        raise ValueError("teacher training view contains duplicate objects")
    if len(oof_by_key) != len(oof_rows):
        raise ValueError("OOF training view contains duplicate objects")
    if set(teacher_by_key) != set(oof_by_key):
        raise ValueError("teacher and OOF training-view scopes differ")
    combined = []
    for condition, rows, view_weight in (
        ("TEACHER_ORDINARY", teacher_rows, teacher_weight),
        ("STRICT_OOF_ORDINARY", oof_rows, oof_weight),
    ):
        if view_weight <= 0.0:
            continue
        for row in rows:
            weighted = dict(row)
            weighted["label_weight"] = (
                max(0.0, float(row["label_weight"])) * view_weight
            )
            weighted["training_condition"] = condition
            weighted["training_view_loss_weight"] = view_weight
            combined.append(weighted)
    return combined


def read_advance_right_teacher_student_examples(
    root: Path,
    *,
    trust_locked_final_state: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    features = _read_jsonl(
        store / "advance_right_access_set_features.jsonl"
    )
    teacher_conditions = _read_jsonl(
        store / "advance_right_teacher_conditions.jsonl"
    )
    oof_conditions = _read_jsonl(
        store / "advance_right_oof_conditions.jsonl"
    )
    labels = _read_jsonl(store / "advance_right_training_labels.jsonl")
    feature_by_key = {_object_key(row): row for row in features}
    teacher_by_key = {_object_key(row): row for row in teacher_conditions}
    oof_by_key = {_object_key(row): row for row in oof_conditions}
    label_by_key = {_object_key(row): row for row in labels}
    if not (
        len(feature_by_key) == len(features)
        and len(teacher_by_key) == len(teacher_conditions)
        and len(oof_by_key) == len(oof_conditions)
        and len(label_by_key) == len(labels)
    ):
        raise ValueError("AdvanceRight teacher-student inputs contain duplicates")
    keys = set(feature_by_key)
    if keys != set(teacher_by_key) or keys != set(oof_by_key) or keys != set(
        label_by_key
    ):
        raise ValueError("AdvanceRight teacher-student scopes differ")
    teacher = [
        labeled_conditioned_example(
            feature_by_key[key],
            teacher_by_key[key],
            label_by_key[key],
        )
        for key in sorted(keys)
    ]
    raw_oof = [
        labeled_conditioned_example(
            feature_by_key[key],
            oof_by_key[key],
            label_by_key[key],
        )
        for key in sorted(keys)
    ]
    teacher_example_by_key = _example_by_key(teacher)
    oof = [
        apply_oof_upstream_truth(
            row,
            teacher_by_key=teacher_example_by_key,
            trust_locked_final_state=trust_locked_final_state,
        )
        for row in raw_oof
    ]
    return teacher, oof


def labeled_conditioned_example(
    feature: Mapping[str, Any],
    condition: Mapping[str, Any],
    label: Mapping[str, Any],
) -> dict[str, Any]:
    view = conditioned_feature_view(feature, condition)
    (
        plan_type,
        acceptable_groups,
        conditional_reason,
    ) = conditional_plan_target(view, label)
    if plan_type not in PLAN_TYPE_INDEX:
        raise ValueError(f"unsupported AdvanceRight plan type: {plan_type}")
    candidate_ids = {
        str(row["candidate_road_id"]) for row in view["candidate_rows"]
    }
    formal_groups = [
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
        acceptable_groups = formal_groups
    else:
        acceptable_groups = []
    candidate_supervised = bool(
        plan_type in AUTOMATIC_PLAN_TYPES
        and view["adjacent_context_resolved"]
        and (
            plan_type == "SWSD_ONLY"
            or (bool(formal_groups) and all(formal_groups))
        )
    )
    if candidate_supervised and any(
        not values for values in acceptable_groups
    ):
        raise ValueError("reachable AdvanceRight has an empty acceptable set")
    complete_safety = bool(
        candidate_supervised
        and view["required_rcsd_access_resolved"]
    )
    return {
        **view,
        "formal_truth_plan_type": str(label["truth_plan_type"]),
        "source_condition_plan_type": source_condition_plan_type(view),
        "truth_plan_type": plan_type,
        "plan_type_index": PLAN_TYPE_INDEX[plan_type],
        "acceptable_candidate_groups": acceptable_groups,
        "truth_cardinality": len(acceptable_groups),
        "candidate_supervised": candidate_supervised,
        "safety_target": complete_safety,
        "carrier_safety_target": candidate_supervised,
        "complete_safety_target": complete_safety,
        "fallback_supervised": plan_type not in AUTOMATIC_PLAN_TYPES,
        "conditional_target_reason": conditional_reason,
        "label_weight": float(label["label_weight"]),
        "label_only_fields_loaded": True,
    }


def apply_oof_upstream_truth(
    oof_example: Mapping[str, Any],
    *,
    teacher_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    trust_locked_final_state: bool = False,
) -> dict[str, Any]:
    teacher = teacher_by_key.get(_object_key(oof_example))
    if teacher is None:
        raise ValueError("OOF AdvanceRight example lacks teacher counterpart")
    road_exact = True
    source_exact = True
    access_exact = True
    access_truth_known = True
    access_proposal_exact = True
    access_proposal_truth_known = True
    for side_name in ("source", "target"):
        teacher_context = teacher[f"{side_name}_context"]
        oof_context = oof_example[f"{side_name}_context"]
        teacher_road_ids = {
            str(row["road_id"])
            for row in teacher_context.get("road_members") or ()
        }
        oof_road_ids = {
            str(row["road_id"])
            for row in oof_context.get("road_members") or ()
        }
        road_exact = road_exact and bool(teacher_road_ids) and (
            teacher_road_ids == oof_road_ids
        )
        teacher_source = str(teacher_context["data_source"])
        oof_source = str(oof_context["data_source"])
        side_source_exact = (
            teacher_source in {"SWSD", "RCSD"}
            and teacher_source == oof_source
        )
        source_exact = source_exact and side_source_exact
        teacher_access_ids = {
            str(row["road_id"])
            for row in teacher_context.get("access_rows") or ()
        }
        oof_access_ids = {
            str(row["road_id"])
            for row in oof_context.get("access_rows") or ()
        }
        teacher_access_proposal_ids = {
            str(row["proposal_id"])
            for row in teacher_context.get("access_rows") or ()
            if str(row.get("proposal_id") or "")
        }
        oof_access_proposal_ids = {
            str(row["proposal_id"])
            for row in oof_context.get("access_rows") or ()
            if str(row.get("proposal_id") or "")
        }
        side_truth_known = bool(
            teacher_source == "SWSD" or teacher_access_ids
        )
        side_proposal_truth_known = bool(
            teacher_source == "SWSD" or teacher_access_proposal_ids
        )
        access_truth_known = access_truth_known and side_truth_known
        access_proposal_truth_known = (
            access_proposal_truth_known and side_proposal_truth_known
        )
        if teacher_source == "SWSD":
            side_access_exact = side_source_exact
            side_proposal_exact = side_source_exact
        elif teacher_access_proposal_ids:
            side_access_exact = bool(
                side_source_exact
                and oof_access_proposal_ids
                == teacher_access_proposal_ids
            )
            side_proposal_exact = side_access_exact
        else:
            side_access_exact = bool(
                side_source_exact
                and teacher_access_ids
                and oof_access_ids == teacher_access_ids
            )
            side_proposal_exact = False
        access_exact = access_exact and side_access_exact
        access_proposal_exact = (
            access_proposal_exact and side_proposal_exact
        )
    complete = bool(road_exact and source_exact and access_exact)
    final_state_valid = _locked_final_state_valid(oof_example)
    if trust_locked_final_state:
        carrier_safety = bool(
            oof_example["candidate_supervised"] and final_state_valid
        )
        complete_safety = carrier_safety
    else:
        carrier_safety = bool(
            oof_example["candidate_supervised"]
            and road_exact
            and source_exact
        )
        complete_safety = bool(
            oof_example["candidate_supervised"] and complete
        )
    result = dict(oof_example)
    result.update(
        {
            "upstream_ordinary_road_set_exact": bool(road_exact),
            "upstream_ordinary_source_exact": bool(source_exact),
            "upstream_ordinary_access_truth_known": bool(
                access_truth_known
            ),
            "upstream_ordinary_access_exact": bool(access_exact),
            "upstream_ordinary_access_proposal_truth_known": bool(
                access_proposal_truth_known
            ),
            "upstream_ordinary_access_proposal_exact": bool(
                access_proposal_exact
            ),
            "upstream_ordinary_complete_exact": complete,
            "upstream_locked_final_state_valid": final_state_valid,
            "safety_basis": (
                "LOCKED_FINAL_STATE"
                if trust_locked_final_state
                else "FORMAL_TEACHER_EXACT"
            ),
            "carrier_safety_target": carrier_safety,
            "complete_safety_target": complete_safety,
            "safety_target": complete_safety,
        }
    )
    return result


def _locked_final_state_valid(example: Mapping[str, Any]) -> bool:
    for side_name in ("source", "target"):
        context = example[f"{side_name}_context"]
        source = str(context.get("data_source") or "")
        decision = str(context.get("selected_decision") or "")
        source_matches_decision = bool(
            (
                source == "SWSD"
                and decision in {"KEEP_SWSD", "ABSTAIN"}
            )
            or (source == "RCSD" and decision == "USE_RCSD")
        )
        if not (
            source_matches_decision
            and bool(context.get("road_members"))
            and bool(context.get("resolved"))
            and bool(context.get("required_access_resolved"))
        ):
            return False
    return True


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
    safety_negative_loss_weight: float | None,
) -> dict[str, Any]:
    model = _new_model(seed, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = (
        safety_negative_loss_weight
        if safety_negative_loss_weight is not None
        else _safety_negative_weight(training)
    )
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
    safety_negative_loss_weight: float | None,
) -> dict[str, Any]:
    model = _new_model(seed, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = (
        safety_negative_loss_weight
        if safety_negative_loss_weight is not None
        else _safety_negative_weight(training)
    )
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
    model: nn.Module,
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
    model: nn.Module,
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
    model: nn.Module,
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
    weights = torch.tensor(
        [max(0.0, float(row["label_weight"])) for row in examples],
        dtype=torch.float32,
        device=device,
    )
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
    plan_loss = _weighted_mean(plan_losses, weights)
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
    safety_class_weights = torch.where(
        safety_targets > 0.5,
        torch.ones_like(safety_targets),
        torch.full_like(safety_targets, safety_negative_weight),
    )
    safety_loss = _weighted_mean(
        safety_losses,
        weights * safety_class_weights,
    )
    supervised = [
        index
        for index, row in enumerate(examples)
        if bool(row["candidate_supervised"])
        and float(row["label_weight"]) > 0
    ]
    if supervised:
        supervised_weights = weights[supervised]
        cardinality_targets = torch.tensor(
            [
                min(
                    int(examples[index]["truth_cardinality"]),
                    CARDINALITY_COUNT - 1,
                )
                for index in supervised
            ],
            dtype=torch.long,
            device=device,
        )
        cardinality_losses = nn.functional.cross_entropy(
            outputs["cardinality_logits"][supervised],
            cardinality_targets,
            reduction="none",
        )
        cardinality_loss = _weighted_mean(
            cardinality_losses,
            supervised_weights,
        )
        selection_losses = torch.stack(
            [
                _structured_selection_loss(
                    outputs["candidate_logits"][index],
                    examples[index],
                    device=device,
                )
                for index in supervised
            ]
        )
        selection_loss = _weighted_mean(
            selection_losses,
            supervised_weights,
        )
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


def _weighted_mean(
    values: torch.Tensor,
    weights: torch.Tensor,
) -> torch.Tensor:
    denominator = weights.sum().clamp_min(1e-8)
    return (values * weights).sum() / denominator


def _plan_class_weights(
    examples: Sequence[Mapping[str, Any]],
    device: torch.device,
) -> torch.Tensor:
    counts = Counter()
    total = 0.0
    for row in examples:
        weight = max(0.0, float(row["label_weight"]))
        counts[int(row["plan_type_index"])] += weight
        total += weight
    values = [
        min(6.0, total / (len(PLAN_TYPES) * max(counts[index], 1e-6)))
        for index in range(len(PLAN_TYPES))
    ]
    return torch.tensor(values, dtype=torch.float32, device=device)


def _safety_negative_weight(
    examples: Sequence[Mapping[str, Any]],
) -> float:
    positive = sum(
        float(row["label_weight"])
        for row in examples
        if bool(row["safety_target"])
    )
    negative = sum(
        float(row["label_weight"])
        for row in examples
        if not bool(row["safety_target"])
    )
    return min(4.0, max(0.25, positive / max(negative, 1e-6)))


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _example_by_key(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {_object_key(row): row for row in rows}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line]


__all__ = [
    "apply_oof_upstream_truth",
    "labeled_conditioned_example",
    "read_advance_right_teacher_student_examples",
    "run_advance_right_teacher_student_strict_nested_oof",
    "weighted_training_views",
]
