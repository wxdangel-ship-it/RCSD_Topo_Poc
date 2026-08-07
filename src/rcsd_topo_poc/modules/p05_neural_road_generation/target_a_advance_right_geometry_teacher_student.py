from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_network import (
    trainable_parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_training import (
    _assert_case_disjoint,
    _fit_geometry_fixed_epochs,
    _fit_geometry_model,
    _input_record,
    _resolve_device,
    _save_checkpoint,
    _write_json,
    _write_jsonl,
    geometry_metrics,
    read_geometry_examples,
    score_geometry_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_teacher_student import (
    read_advance_right_teacher_student_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_advance_right_geometry_teacher_student_strict_nested_oof(
    *,
    access_set_store_root: Path,
    teacher_conditioned_root: Path,
    oof_conditioned_root: Path,
    teacher_geometry_root: Path,
    oof_geometry_root: Path,
    base_oof_root: Path,
    output_root: Path,
    seed: int,
    batch_size: int = 32,
    requested_device: str = "cuda",
    max_epochs: int = 100,
    patience: int = 15,
    learning_rate: float = 5e-4,
    weight_decay: float = 2e-4,
    minimum_geometry_acceptance_threshold: float = 0.0,
    fine_tune_base: bool = False,
    base_loss_weight: float = 0.0,
) -> Path:
    """Fit geometry on teacher state and evaluate strict OOF reachability."""
    started = time.perf_counter()
    if min(batch_size, max_epochs, patience) < 1:
        raise ValueError("geometry teacher-student config is invalid")
    if fine_tune_base != (base_loss_weight > 0.0):
        raise ValueError(
            "fine_tune_base requires a positive base_loss_weight and vice versa"
        )
    access_store = normalize_runtime_path(
        access_set_store_root
    ).resolve(strict=True)
    teacher_conditioned = normalize_runtime_path(
        teacher_conditioned_root
    ).resolve(strict=True)
    oof_conditioned = normalize_runtime_path(
        oof_conditioned_root
    ).resolve(strict=True)
    teacher_geometry = normalize_runtime_path(
        teacher_geometry_root
    ).resolve(strict=True)
    oof_geometry = normalize_runtime_path(oof_geometry_root).resolve(
        strict=True
    )
    base_root = normalize_runtime_path(base_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    teacher_examples = read_geometry_examples(
        teacher_conditioned,
        teacher_geometry,
    )
    oof_examples = read_geometry_examples(
        oof_conditioned,
        oof_geometry,
    )
    strict_teacher, strict_oof = (
        read_advance_right_teacher_student_examples(access_store)
    )
    strict_teacher_by_key = {
        _object_key(row): row for row in strict_teacher
    }
    strict_oof_by_key = {_object_key(row): row for row in strict_oof}
    if (
        {_object_key(row) for row in teacher_examples}
        != set(strict_teacher_by_key)
        or {_object_key(row) for row in oof_examples}
        != set(strict_oof_by_key)
    ):
        raise ValueError("geometry and strict carrier scopes differ")
    folds = sorted({int(row["fold"]) for row in teacher_examples})
    if len(folds) < 3:
        raise ValueError("geometry strict OOF requires three folds")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)

    predictions = []
    teacher_predictions = []
    fold_summaries = []
    model_parameters = 0
    geometry_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
        inner_training = [
            row
            for row in teacher_examples
            if int(row["fold"]) not in {outer_fold, inner_fold}
        ]
        inner_teacher_validation = [
            row
            for row in teacher_examples
            if int(row["fold"]) == inner_fold
        ]
        inner_oof_calibration = [
            row for row in oof_examples if int(row["fold"]) == inner_fold
        ]
        outer_training = [
            row
            for row in teacher_examples
            if int(row["fold"]) != outer_fold
        ]
        outer_teacher_validation = [
            row
            for row in teacher_examples
            if int(row["fold"]) == outer_fold
        ]
        outer_oof_validation = [
            row for row in oof_examples if int(row["fold"]) == outer_fold
        ]
        _assert_case_disjoint(
            inner_training,
            inner_teacher_validation,
        )
        _assert_case_disjoint(outer_training, outer_oof_validation)
        base_fold = _read_json(
            base_root / f"fold_{outer_fold}_summary.json"
        )
        tuning = _fit_geometry_model(
            inner_training,
            inner_teacher_validation,
            base_checkpoint=base_root
            / f"fold_{outer_fold}_inner_checkpoint.pt",
            seed=seed + outer_fold * 100 + 17,
            batch_size=batch_size,
            device=device,
            max_epochs=max_epochs,
            patience=patience,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            fine_tune_base=fine_tune_base,
            base_loss_weight=base_loss_weight,
        )
        final = _fit_geometry_fixed_epochs(
            outer_training,
            base_checkpoint=base_root
            / f"fold_{outer_fold}_checkpoint.pt",
            seed=seed + outer_fold * 100 + 53,
            batch_size=batch_size,
            device=device,
            epoch_count=tuning["best_epoch"],
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            fine_tune_base=fine_tune_base,
            base_loss_weight=base_loss_weight,
        )
        model_parameters = parameter_count(final["model"])
        geometry_parameters = trainable_parameter_count(final["model"])
        inner_rows = score_geometry_examples(
            tuning["model"],
            inner_oof_calibration,
            batch_size=batch_size,
            device=device,
            base_safety_threshold=float(base_fold["safety_threshold"]),
            base_acceptance_threshold=float(
                base_fold["acceptance_threshold"]
            ),
            geometry_acceptance_threshold=0.0,
        )
        inner_rows = apply_strict_geometry_truth(
            inner_rows,
            strict_examples=strict_oof_by_key,
        )
        geometry_threshold = max(
            minimum_geometry_acceptance_threshold,
            choose_zero_error_end_to_end_geometry_threshold(inner_rows),
        )
        outer_rows = score_geometry_examples(
            final["model"],
            outer_oof_validation,
            batch_size=batch_size,
            device=device,
            base_safety_threshold=float(base_fold["safety_threshold"]),
            base_acceptance_threshold=float(
                base_fold["acceptance_threshold"]
            ),
            geometry_acceptance_threshold=geometry_threshold,
        )
        outer_rows = apply_strict_geometry_truth(
            outer_rows,
            strict_examples=strict_oof_by_key,
        )
        teacher_rows = score_geometry_examples(
            final["model"],
            outer_teacher_validation,
            batch_size=batch_size,
            device=device,
            base_safety_threshold=float(base_fold["safety_threshold"]),
            base_acceptance_threshold=float(
                base_fold["acceptance_threshold"]
            ),
            geometry_acceptance_threshold=geometry_threshold,
        )
        teacher_rows = apply_strict_geometry_truth(
            teacher_rows,
            strict_examples=strict_teacher_by_key,
        )
        for row in outer_rows:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                    "evaluation_condition": "STRICT_OOF_ORDINARY",
                }
            )
        for row in teacher_rows:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                    "evaluation_condition": "TEACHER_ORDINARY",
                }
            )
        predictions.extend(outer_rows)
        teacher_predictions.extend(teacher_rows)

        checkpoint_path = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            checkpoint_path,
            model=final["model"],
            base_checkpoint=base_root
            / f"fold_{outer_fold}_checkpoint.pt",
            fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "inner_teacher_train_count": len(inner_training),
            "inner_teacher_validation_count": len(
                inner_teacher_validation
            ),
            "inner_oof_calibration_count": len(inner_oof_calibration),
            "outer_teacher_train_count": len(outer_training),
            "outer_teacher_validation_count": len(
                outer_teacher_validation
            ),
            "outer_oof_validation_count": len(outer_oof_validation),
            "best_epoch": tuning["best_epoch"],
            "best_teacher_validation_loss": tuning[
                "best_validation_loss"
            ],
            "base_safety_threshold": float(
                base_fold["safety_threshold"]
            ),
            "base_acceptance_threshold": float(
                base_fold["acceptance_threshold"]
            ),
            "geometry_acceptance_threshold": geometry_threshold,
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "oof_metrics": strict_geometry_metrics(outer_rows),
            "teacher_metrics": strict_geometry_metrics(teacher_rows),
            "checkpoint": _input_record(checkpoint_path),
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
    metrics = strict_geometry_metrics(predictions)
    teacher_metrics = strict_geometry_metrics(teacher_predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": (
            "ADVANCE_RIGHT_GEOMETRY_TEACHER_STUDENT_STRICT_NESTED_OOF"
        ),
        "model_scope": (
            "The shared carrier encoder and structured geometry decoder are "
            "jointly optimized with teacher ordinary state, then calibrated "
            "and evaluated with strict OOF ordinary Road/access reachability."
            if fine_tune_base
            else (
                "The carrier encoder is frozen. Geometry proposals are fit "
                "with teacher ordinary state and calibrated/evaluated with "
                "strict OOF ordinary Road/access reachability."
            )
        ),
        "truth_contract": (
            "OOF-unreachable teacher geometry remains an explicit unsafe "
            "fallback target; it is never replaced by a new nearest-Road label"
        ),
        "example_count": len(predictions),
        "fold_count": len(folds),
        "seed": seed,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "patience": patience,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "base_loss_weight": base_loss_weight,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "parameter_count": model_parameters,
        "trainable_geometry_parameter_count": geometry_parameters,
        "trainable_parameter_count": geometry_parameters,
        "base_encoder_frozen": not fine_tune_base,
        "metrics": metrics,
        "teacher_metrics": teacher_metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "silent_fix": False,
        "release_gate": "NO_GO",
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "formal T06 geometry action matches are absent for the "
            "counterfactual teacher ordinary states; geometry labels are "
            "weak replay only, and global RoadGraph validation is pending"
        ),
        "inputs": {
            "access_set": _input_record(access_store / "summary.json"),
            "teacher_conditioned": _input_record(
                teacher_conditioned / "summary.json"
            ),
            "oof_conditioned": _input_record(
                oof_conditioned / "summary.json"
            ),
            "teacher_geometry": _input_record(
                teacher_geometry / "summary.json"
            ),
            "oof_geometry": _input_record(oof_geometry / "summary.json"),
            "base_oof": _input_record(base_root / "summary.json"),
        },
        "outputs": {
            "oof_predictions": _input_record(prediction_path),
            "teacher_predictions": _input_record(teacher_prediction_path),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == 474
            and len(teacher_predictions) == 474
            and {_object_key(row) for row in predictions}
            == set(strict_oof_by_key)
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight geometry OOF coverage gate failed")
    return root


def apply_strict_geometry_truth(
    rows: Sequence[Mapping[str, Any]],
    *,
    strict_examples: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        strict = strict_examples.get(_object_key(row))
        if strict is None:
            raise ValueError("geometry row lacks strict carrier truth")
        base_safe = bool(strict["safety_target"])
        end_to_end_exact = bool(
            base_safe and row["raw_complete_plan_geometry_exact"]
        )
        automatic = bool(row["automatic_decision"])
        row.update(
            {
                "strict_base_safety_target": base_safe,
                "upstream_ordinary_road_set_exact": bool(
                    strict.get("upstream_ordinary_road_set_exact", True)
                ),
                "upstream_ordinary_source_exact": bool(
                    strict.get("upstream_ordinary_source_exact", True)
                ),
                "upstream_ordinary_access_exact": bool(
                    strict.get(
                        "upstream_ordinary_access_exact",
                        strict["adjacent_access_road_resolved"],
                    )
                ),
                "raw_end_to_end_complete_exact": end_to_end_exact,
                "unsafe_automatic": bool(
                    automatic and not end_to_end_exact
                ),
            }
        )
        result.append(row)
    return result


def choose_zero_error_end_to_end_geometry_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["geometry_confidence"]) for row in rows],
        }
    )
    best_threshold = 1.000001
    best_count = -1
    for threshold in thresholds:
        accepted = [
            row
            for row in rows
            if bool(row["base_automatic_decision"])
            and not row["missing_geometry_proposal_types"]
            and float(row["geometry_confidence"]) >= threshold
        ]
        wrong = sum(
            not bool(row["raw_end_to_end_complete_exact"])
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


def strict_geometry_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    metrics = geometry_metrics(rows)
    automatic = [row for row in rows if bool(row["automatic_decision"])]
    metrics.update(
        {
            "strict_base_safety_target_count": sum(
                bool(row["strict_base_safety_target"]) for row in rows
            ),
            "raw_end_to_end_complete_exact": sum(
                bool(row["raw_end_to_end_complete_exact"]) for row in rows
            )
            / max(len(rows), 1),
            "automatic_end_to_end_exact": (
                sum(
                    bool(row["raw_end_to_end_complete_exact"])
                    for row in automatic
                )
                / len(automatic)
                if automatic
                else 0.0
            ),
        }
    )
    return metrics


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "apply_strict_geometry_truth",
    "choose_zero_error_end_to_end_geometry_threshold",
    "run_advance_right_geometry_teacher_student_strict_nested_oof",
    "strict_geometry_metrics",
]
