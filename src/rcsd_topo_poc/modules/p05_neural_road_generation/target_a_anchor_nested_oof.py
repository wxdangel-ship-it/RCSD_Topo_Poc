from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_oof import (
    _balanced_class_weights,
    _balanced_gate_class_weights,
    _classification_metrics,
    _predict_anchor_status,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_graph import (
    anchor_dependency_contract,
    build_anchor_dependency_batches,
    predict_anchor_dependency_graph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_safety import (
    _candidate_confidence_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    train_target_a_fixed_epochs,
    train_target_a_stage,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_anchor_status_strict_nested_oof(
    *,
    store_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
    dependency_graph: bool = False,
) -> Path:
    """Run outer OOF without using outer labels for epoch or threshold choices."""
    started = time.perf_counter()
    config.validate()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source_root = normalize_runtime_path(store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_anchor_pretraining_stores(source_root)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("strict nested OOF requires at least three folds")
    device = _resolve_device(requested_device)
    outer_predictions: list[dict[str, Any]] = []
    calibration_predictions: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for outer_fold in folds:
        inner_fold = _inner_fold_for_outer(folds, outer_fold)
        inner_training, inner_validation, outer_training, outer_validation = (
            _strict_nested_split(
                examples,
                outer_fold=outer_fold,
                inner_fold=inner_fold,
            )
        )
        inner_config = replace(
            config,
            anchor_status_class_weights=_balanced_class_weights(
                inner_training
            ),
            anchor_gate_class_weights=(
                _balanced_gate_class_weights(inner_training)
                if config.learned_anchor_gate
                else ()
            ),
        )
        tuning_result = train_target_a_stage(
            _batches(
                inner_training,
                batch_size,
                dependency_graph=dependency_graph,
                include_candidate_relations=(
                    inner_config.structured_anchor_object_decoder
                ),
            ),
            _batches(
                inner_validation,
                batch_size,
                dependency_graph=dependency_graph,
                include_candidate_relations=(
                    inner_config.structured_anchor_object_decoder
                ),
            ),
            config=inner_config,
            seed=seed + outer_fold * 100 + 17,
            device=device,
        )
        fold_calibration = _predictions_with_confidence(
            tuning_result.model,
            inner_validation,
            batch_size=batch_size,
            device=device,
            dependency_graph=dependency_graph,
        )
        for row in fold_calibration:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                }
            )
        calibration_predictions.extend(fold_calibration)

        outer_config = replace(
            config,
            anchor_status_class_weights=_balanced_class_weights(
                outer_training
            ),
            anchor_gate_class_weights=(
                _balanced_gate_class_weights(outer_training)
                if config.learned_anchor_gate
                else ()
            ),
        )
        final_result = train_target_a_fixed_epochs(
            _batches(
                outer_training,
                batch_size,
                dependency_graph=dependency_graph,
                include_candidate_relations=(
                    outer_config.structured_anchor_object_decoder
                ),
            ),
            config=outer_config,
            seed=seed + outer_fold * 100 + 53,
            device=device,
            epoch_count=tuning_result.best_epoch,
        )
        fold_predictions = _predictions_with_confidence(
            final_result.model,
            outer_validation,
            batch_size=batch_size,
            device=device,
            dependency_graph=dependency_graph,
        )
        for row in fold_predictions:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                }
            )
        outer_predictions.extend(fold_predictions)

        tuning_checkpoint = root / f"fold_{outer_fold}_inner_checkpoint.pt"
        final_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            tuning_checkpoint,
            model=tuning_result.model,
            stage="ANCHOR_STATUS_STRICT_NESTED_INNER",
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 17,
            config=inner_config,
            epoch_count=tuning_result.best_epoch,
        )
        _save_checkpoint(
            final_checkpoint,
            model=final_result.model,
            stage="ANCHOR_STATUS_STRICT_NESTED_OUTER",
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
            config=outer_config,
            epoch_count=final_result.epoch_count,
        )
        fold_row = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "inner_train_example_count": len(inner_training),
            "inner_validation_example_count": len(inner_validation),
            "outer_train_example_count": len(outer_training),
            "outer_validation_example_count": len(outer_validation),
            "selected_epoch": tuning_result.best_epoch,
            "inner_best_validation_loss": tuning_result.best_validation_loss,
            "inner_status_class_weights": list(
                inner_config.anchor_status_class_weights
            ),
            "outer_status_class_weights": list(
                outer_config.anchor_status_class_weights
            ),
            "inner_wall_seconds": tuning_result.wall_seconds,
            "outer_fit_wall_seconds": final_result.wall_seconds,
            "inner_state_signature": tuning_result.state_signature,
            "outer_state_signature": final_result.state_signature,
            "inner_checkpoint": str(tuning_checkpoint.resolve()),
            "inner_checkpoint_sha256": sha256_file(tuning_checkpoint),
            "outer_checkpoint": str(final_checkpoint.resolve()),
            "outer_checkpoint_sha256": sha256_file(final_checkpoint),
            "inner_metrics": _classification_metrics(fold_calibration),
            "outer_metrics": _classification_metrics(fold_predictions),
            "inner_history": tuning_result.history,
            "outer_history": final_result.history,
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_row)

    outer_predictions.sort(key=lambda row: str(row["sample_id"]))
    calibration_predictions.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    _write_jsonl(root / "oof_predictions.jsonl", outer_predictions)
    _write_jsonl(
        root / "inner_calibration_predictions.jsonl",
        calibration_predictions,
    )
    sample_ids = {row.sample_id for row in examples}
    coverage_ok = (
        len(outer_predictions) == len(examples)
        and {str(row["sample_id"]) for row in outer_predictions} == sample_ids
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_STATUS_STRICT_NESTED_OOF",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "config": asdict(config),
        "batch_size": batch_size,
        "batch_size_semantics": (
            "maximum anchors per packed dependency-graph batch; an intact "
            "component may exceed this value"
            if dependency_graph
            else "independent anchor examples"
        ),
        "dependency_graph": dependency_graph,
        "dependency_graph_contract": (
            anchor_dependency_contract(examples)
            if dependency_graph
            else None
        ),
        "parameter_count": parameter_count(TargetAJointNetwork(config)),
        "source_store": str(source_root),
        "source_manifest_sha256": sha256_file(source_root / "manifest.json"),
        "example_count": len(examples),
        "fold_count": len(folds),
        "folds": fold_rows,
        "oof_metrics": _classification_metrics(outer_predictions),
        "oof_coverage_exact": coverage_ok,
        "outer_label_access_during_fit": 0,
        "inner_validation_policy": "NEXT_CASE_FOLD_CYCLIC",
        "epoch_selection": (
            "inner train/validation only; fixed epoch retrain on all "
            "outer-training folds"
        ),
        "safety_threshold_source": (
            "inner_calibration_predictions only; outer labels are evaluation-only"
        ),
        "scope_statement": (
            "This is the first honest outer OOF contract. Earlier diagnostic "
            "runs used the outer fold for early stopping and are not formal OOF."
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not coverage_ok:
        raise RuntimeError(f"strict nested OOF coverage differs: {root}")
    return root


def _strict_nested_split(
    examples: Sequence[AnchorPretrainExample],
    *,
    outer_fold: int,
    inner_fold: int,
) -> tuple[
    list[AnchorPretrainExample],
    list[AnchorPretrainExample],
    list[AnchorPretrainExample],
    list[AnchorPretrainExample],
]:
    if outer_fold == inner_fold:
        raise ValueError("outer and inner validation folds must differ")
    inner_training = [
        row for row in examples if row.fold not in {outer_fold, inner_fold}
    ]
    inner_validation = [row for row in examples if row.fold == inner_fold]
    outer_training = [row for row in examples if row.fold != outer_fold]
    outer_validation = [row for row in examples if row.fold == outer_fold]
    if not all(
        (inner_training, inner_validation, outer_training, outer_validation)
    ):
        raise ValueError("strict nested split contains an empty partition")
    if {row.sample_id for row in outer_validation} & {
        row.sample_id for row in outer_training
    }:
        raise AssertionError("outer validation leaked into outer training")
    if {row.sample_id for row in inner_validation} & {
        row.sample_id for row in inner_training
    }:
        raise AssertionError("inner validation leaked into inner training")
    return (
        inner_training,
        inner_validation,
        outer_training,
        outer_validation,
    )


def _inner_fold_for_outer(folds: Sequence[int], outer_fold: int) -> int:
    ordered = tuple(sorted(set(int(value) for value in folds)))
    if outer_fold not in ordered or len(ordered) < 3:
        raise ValueError("strict nested fold policy is undefined")
    index = ordered.index(outer_fold)
    return ordered[(index + 1) % len(ordered)]


def _batches(
    examples: Sequence[AnchorPretrainExample],
    batch_size: int,
    *,
    dependency_graph: bool = False,
    include_candidate_relations: bool = False,
) -> list[TargetATrainingBatch]:
    if dependency_graph:
        return [
            row.training_batch
            for row in build_anchor_dependency_batches(
                examples,
                max_anchor_count=batch_size,
                include_candidate_relations=include_candidate_relations,
            )
        ]
    return [
        collate_anchor_pretrain_batch(
            examples[index : index + batch_size],
            include_candidate_relations=include_candidate_relations,
        )
        for index in range(0, len(examples), batch_size)
    ]


def _predictions_with_confidence(
    model: TargetAJointNetwork,
    examples: Sequence[AnchorPretrainExample],
    *,
    batch_size: int,
    device: torch.device,
    dependency_graph: bool = False,
) -> list[dict[str, Any]]:
    if dependency_graph:
        graph_rows = predict_anchor_dependency_graph(
            model,
            examples,
            max_anchor_count=batch_size,
            device=device,
        )
        rows: list[dict[str, Any]] = []
        for prediction in graph_rows:
            proven_safe = bool(
                prediction["label"] == "SUCCESS"
                and prediction["candidate_acceptable_exact"] is True
            )
            rows.append(
                {
                    **prediction,
                    "proven_safe_anchor": proven_safe,
                    "raw_unsafe_success": bool(
                        prediction["predicted"] == "SUCCESS"
                        and not proven_safe
                    ),
                }
            )
        return rows
    prediction_rows = {
        str(row["sample_id"]): row
        for row in _predict_anchor_status(
            model,
            examples,
            batch_size=batch_size,
            device=device,
        )
    }
    confidence_rows = {
        str(row["sample_id"]): row
        for row in _candidate_confidence_rows(
            model,
            examples,
            batch_size=batch_size,
            device=device,
        )
    }
    if set(prediction_rows) != set(confidence_rows):
        raise ValueError("strict nested prediction/confidence coverage differs")
    rows: list[dict[str, Any]] = []
    for sample_id in sorted(prediction_rows):
        prediction = prediction_rows[sample_id]
        confidence = confidence_rows[sample_id]
        if (
            int(prediction["predicted_index"])
            != int(confidence["status_predicted_index"])
            or int(prediction["candidate_predicted_index"])
            != int(confidence["candidate_predicted_index"])
        ):
            raise RuntimeError("strict nested confidence rescore differs")
        proven_safe = bool(
            prediction["label"] == "SUCCESS"
            and prediction["candidate_acceptable_exact"] is True
        )
        rows.append(
            {
                **prediction,
                **confidence,
                "proven_safe_anchor": proven_safe,
                "raw_unsafe_success": bool(
                    prediction["predicted"] == "SUCCESS" and not proven_safe
                ),
            }
        )
    return rows


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAJointNetwork,
    stage: str,
    outer_fold: int,
    inner_fold: int,
    seed: int,
    config: TargetAConfig,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": stage,
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "seed": seed,
            "config": asdict(config),
            "epoch_count": epoch_count,
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
            raise RuntimeError("CUDA was requested but is not available")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported Target A device: {requested}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )


__all__ = ["run_anchor_status_strict_nested_oof"]
