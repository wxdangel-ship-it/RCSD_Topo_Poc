from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_oof import (
    _batches,
    _inner_fold_for_outer,
    _predictions_with_confidence,
    _strict_nested_split,
    _write_json,
    _write_jsonl,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_oof import (
    _balanced_gate_class_weights,
    _classification_metrics,
    _resolve_device,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_safety import (
    _safety_summary,
    apply_inner_calibrated_anchor_safety_gate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    train_anchor_gate_fixed_epochs,
    train_anchor_gate_stage,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_anchor_posthoc_gate_strict_nested_oof(
    *,
    store_root: Path,
    base_store_root: Path,
    base_oof_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
    dependency_graph: bool = True,
) -> Path:
    """Retune only the anchor hard gate on frozen strict-nested checkpoints."""
    started = time.perf_counter()
    config.validate()
    if not config.learned_anchor_gate:
        raise ValueError("posthoc anchor gate requires learned_anchor_gate")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source_root = normalize_runtime_path(store_root).resolve(strict=True)
    base_source_root = normalize_runtime_path(base_store_root).resolve(strict=True)
    base_root = normalize_runtime_path(base_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    source_manifest = _read_json(source_root / "manifest.json")
    base_manifest = _read_json(base_source_root / "manifest.json")
    feature_sha = str(source_manifest["inference_feature_store"]["sha256"])
    base_feature_sha = str(
        base_manifest["inference_feature_store"]["sha256"]
    )
    if feature_sha != base_feature_sha:
        raise ValueError("posthoc gate feature stores differ from base training")
    examples = read_anchor_pretraining_stores(source_root)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("posthoc strict nested OOF requires at least three folds")
    base_oof_rows = {
        str(row["sample_id"]): row
        for row in _read_jsonl(base_root / "oof_predictions.jsonl")
    }
    base_inner_rows = {
        (int(row["outer_fold"]), str(row["sample_id"])): row
        for row in _read_jsonl(
            base_root / "inner_calibration_predictions.jsonl"
        )
    }
    if set(base_oof_rows) != {row.sample_id for row in examples}:
        raise ValueError("posthoc gate base OOF coverage differs")
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
        inner_base_path = base_root / f"fold_{outer_fold}_inner_checkpoint.pt"
        outer_base_path = base_root / f"fold_{outer_fold}_checkpoint.pt"
        inner_model, inner_base_config = _load_base_model(
            inner_base_path,
            device=device,
        )
        inner_shared_before = _shared_state_signature(inner_model)
        inner_config = _gate_training_config(
            inner_base_config,
            config,
            examples=inner_training,
        )
        tuning = train_anchor_gate_stage(
            _batches(
                inner_training,
                batch_size,
                dependency_graph=dependency_graph,
            ),
            _batches(
                inner_validation,
                batch_size,
                dependency_graph=dependency_graph,
            ),
            model=inner_model,
            config=inner_config,
            seed=seed + outer_fold * 100 + 17,
            device=device,
        )
        if _shared_state_signature(tuning.model) != inner_shared_before:
            raise RuntimeError("posthoc inner gate modified frozen base parameters")
        fold_calibration = _predictions_with_confidence(
            tuning.model,
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
            _validate_frozen_prediction(
                row,
                base_inner_rows[(outer_fold, str(row["sample_id"]))],
            )
        calibration_predictions.extend(fold_calibration)

        outer_model, outer_base_config = _load_base_model(
            outer_base_path,
            device=device,
        )
        outer_shared_before = _shared_state_signature(outer_model)
        outer_config = _gate_training_config(
            outer_base_config,
            config,
            examples=outer_training,
        )
        final = train_anchor_gate_fixed_epochs(
            _batches(
                outer_training,
                batch_size,
                dependency_graph=dependency_graph,
            ),
            model=outer_model,
            config=outer_config,
            seed=seed + outer_fold * 100 + 53,
            device=device,
            epoch_count=tuning.best_epoch,
        )
        if _shared_state_signature(final.model) != outer_shared_before:
            raise RuntimeError("posthoc outer gate modified frozen base parameters")
        fold_predictions = _predictions_with_confidence(
            final.model,
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
            _validate_frozen_prediction(
                row,
                base_oof_rows[str(row["sample_id"])],
            )
        outer_predictions.extend(fold_predictions)

        inner_delta_path = root / f"fold_{outer_fold}_inner_gate.pt"
        outer_delta_path = root / f"fold_{outer_fold}_gate.pt"
        _save_gate_delta(
            inner_delta_path,
            model=tuning.model,
            base_checkpoint=inner_base_path,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning.best_epoch,
            config=inner_config,
        )
        _save_gate_delta(
            outer_delta_path,
            model=final.model,
            base_checkpoint=outer_base_path,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=final.epoch_count,
            config=outer_config,
        )
        fold_row = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "selected_epoch": tuning.best_epoch,
            "inner_best_validation_loss": tuning.best_validation_loss,
            "inner_gate_class_weights": list(
                inner_config.anchor_gate_class_weights
            ),
            "outer_gate_class_weights": list(
                outer_config.anchor_gate_class_weights
            ),
            "inner_wall_seconds": tuning.wall_seconds,
            "outer_fit_wall_seconds": final.wall_seconds,
            "inner_gate_state_signature": tuning.state_signature,
            "outer_gate_state_signature": final.state_signature,
            "inner_gate_delta": str(inner_delta_path.resolve()),
            "inner_gate_delta_sha256": sha256_file(inner_delta_path),
            "outer_gate_delta": str(outer_delta_path.resolve()),
            "outer_gate_delta_sha256": sha256_file(outer_delta_path),
            "inner_metrics": _classification_metrics(fold_calibration),
            "outer_metrics": _classification_metrics(fold_predictions),
            "inner_history": tuning.history,
            "outer_history": final.history,
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_row)

    outer_predictions.sort(key=lambda row: str(row["sample_id"]))
    calibration_predictions.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    gated, thresholds = apply_inner_calibrated_anchor_safety_gate(
        calibration_predictions,
        outer_predictions,
    )
    gated.sort(key=lambda row: str(row["sample_id"]))
    _write_jsonl(root / "oof_predictions.jsonl", outer_predictions)
    _write_jsonl(
        root / "inner_calibration_predictions.jsonl",
        calibration_predictions,
    )
    _write_jsonl(root / "gated_oof_predictions.jsonl", gated)
    sample_ids = {row.sample_id for row in examples}
    coverage_ok = (
        len(outer_predictions) == len(examples)
        and {str(row["sample_id"]) for row in outer_predictions} == sample_ids
    )
    summary = {
        "stage": "ANCHOR_POSTHOC_GATE_STRICT_NESTED_OOF",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "example_count": len(examples),
        "fold_count": len(folds),
        "batch_size": batch_size,
        "dependency_graph": dependency_graph,
        "config": asdict(config),
        "frozen_base_oof_root": str(base_root),
        "frozen_base_oof_summary_sha256": sha256_file(
            base_root / "summary.json"
        ),
        "source_store_manifest_sha256": sha256_file(
            source_root / "manifest.json"
        ),
        "base_store_manifest_sha256": sha256_file(
            base_source_root / "manifest.json"
        ),
        "inference_feature_store_sha256": feature_sha,
        "training_scope": "ANCHOR_GATE_HEAD_ONLY",
        "shared_and_candidate_parameter_updates": 0,
        "gate_delta_only_checkpoints": True,
        "epoch_selection": (
            "matching inner train/validation only; fixed epoch gate-head-only "
            "fit on all outer-training folds"
        ),
        "oof_coverage_complete": coverage_ok,
        "oof_metrics": _classification_metrics(outer_predictions),
        "inner_only_thresholds": thresholds,
        "safety": _safety_summary(gated),
        "folds": fold_rows,
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _gate_training_config(
    base_config: TargetAConfig,
    requested: TargetAConfig,
    *,
    examples: Sequence[AnchorPretrainExample],
) -> TargetAConfig:
    if not base_config.learned_anchor_gate:
        raise ValueError("base checkpoint does not contain a learned gate head")
    architecture_keys = (
        "feature_dim",
        "hidden_dim",
        "feedforward_dim",
        "num_heads",
        "graph_layers",
        "set_layers",
        "hierarchical_anchor_decoder",
        "structured_anchor_object_decoder",
        "compositional_anchor_object_decoder",
        "compositional_anchor_candidate_residual",
        "cardinality_conditioned_anchor_decoder",
        "anchor_cardinality_count",
    )
    for key in architecture_keys:
        if getattr(base_config, key) != getattr(requested, key):
            raise ValueError(f"posthoc gate architecture differs: {key}")
    if (
        base_config.anchor_gate_pass_threshold
        != requested.anchor_gate_pass_threshold
    ):
        raise ValueError("posthoc gate pass threshold differs from base model")
    return replace(
        base_config,
        anchor_gate_class_weights=_balanced_gate_class_weights(examples),
        learning_rate=requested.learning_rate,
        weight_decay=requested.weight_decay,
        max_epochs=requested.max_epochs,
        patience=requested.patience,
        torch_num_threads=requested.torch_num_threads,
    )


def _load_base_model(
    checkpoint_path: Path,
    *,
    device: torch.device,
) -> tuple[TargetAJointNetwork, TargetAConfig]:
    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )
    config = TargetAConfig(**dict(checkpoint["config"]))
    config.validate()
    model = TargetAJointNetwork(config).to(device)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()
    return model, config


def _validate_frozen_prediction(
    current: Mapping[str, Any],
    base: Mapping[str, Any],
) -> None:
    for key in (
        "raw_status_predicted_index",
        "candidate_predicted_index",
        "candidate_predicted_id",
        "candidate_type",
    ):
        if current.get(key) != base.get(key):
            raise RuntimeError(f"posthoc gate changed frozen prediction: {key}")


def _shared_state_signature(model: TargetAJointNetwork) -> str:
    buffer = io.BytesIO()
    torch.save(
        {
            key: value.detach().cpu()
            for key, value in sorted(model.state_dict().items())
            if not key.startswith("anchor_gate_head.")
        },
        buffer,
    )
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _save_gate_delta(
    path: Path,
    *,
    model: TargetAJointNetwork,
    base_checkpoint: Path,
    outer_fold: int,
    inner_fold: int,
    epoch_count: int,
    config: TargetAConfig,
) -> None:
    torch.save(
        {
            "stage": "ANCHOR_POSTHOC_GATE_DELTA",
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "epoch_count": epoch_count,
            "config": asdict(config),
            "base_checkpoint": str(base_checkpoint.resolve()),
            "base_checkpoint_sha256": sha256_file(base_checkpoint),
            "anchor_gate_head_state_dict": {
                key: value.detach().cpu()
                for key, value in model.anchor_gate_head.state_dict().items()
            },
        },
        path,
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"JSONL row is not an object: {path}")
                rows.append(payload)
    return rows


__all__ = ["run_anchor_posthoc_gate_strict_nested_oof"]
