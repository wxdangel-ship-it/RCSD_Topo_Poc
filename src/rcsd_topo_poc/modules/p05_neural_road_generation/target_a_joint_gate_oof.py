from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_joint_gate import (
    JointAnchorSegmentGate,
    JointGateAnchorTarget,
    JointGateConfig,
    JointGateData,
    JointGateSegmentExample,
    collate_joint_segment_gate_batch,
    read_joint_gate_data,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_joint_gate_strict_nested_oof(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
    base_anchor_oof_root: Path,
    output_root: Path,
    run_id: str,
    config: JointGateConfig,
    seed: int,
    requested_device: str = "cuda",
) -> Path:
    """Train one shared encoder with anchor and Segment gate supervision."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    anchor_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(plan_label_root).resolve(strict=True)
    base_root = normalize_runtime_path(base_anchor_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    data = read_joint_gate_data(
        anchor_store_root=anchor_root,
        candidate_store_root=candidate_root,
        plan_label_root=label_root,
    )
    base_rows = {
        str(row["sample_id"]): row
        for row in _read_jsonl(base_root / "oof_predictions.jsonl")
    }
    base_calibration_rows = {
        (int(row["outer_fold"]), str(row["sample_id"])): row
        for row in _read_jsonl(
            base_root / "inner_calibration_predictions.jsonl"
        )
    }
    if set(base_rows) != {row.sample_id for row in data.anchors}:
        raise ValueError("joint gate base anchor OOF coverage differs")
    folds = sorted(
        {row.fold for row in data.anchors}
        | {row.fold for row in data.segments}
    )
    if len(folds) < 3:
        raise ValueError("joint gate strict nested OOF needs three folds")
    device = _resolve_device(requested_device)
    anchor_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    anchor_calibration_rows: list[dict[str, Any]] = []
    segment_calibration_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for outer_fold in folds:
        inner_fold = _inner_fold_for_outer(folds, outer_fold)
        anchor_inner_train = _indices_excluding_folds(
            data.anchors,
            {outer_fold, inner_fold},
        )
        anchor_inner_validation = _indices_for_fold(
            data.anchors,
            inner_fold,
        )
        segment_inner_train = _indices_excluding_folds(
            data.segments,
            {outer_fold, inner_fold},
        )
        segment_inner_validation = _indices_for_fold(
            data.segments,
            inner_fold,
        )
        tuning = _fit_with_early_stopping(
            data,
            anchor_training_indices=anchor_inner_train,
            segment_training_indices=segment_inner_train,
            anchor_validation_indices=anchor_inner_validation,
            segment_validation_indices=segment_inner_validation,
            config=config,
            seed=seed + outer_fold * 100 + 17,
            device=device,
        )
        anchor_outer_train = _indices_excluding_folds(
            data.anchors,
            {outer_fold},
        )
        segment_outer_train = _indices_excluding_folds(
            data.segments,
            {outer_fold},
        )
        final = _fit_fixed_epochs(
            data,
            anchor_training_indices=anchor_outer_train,
            segment_training_indices=segment_outer_train,
            config=config,
            seed=seed + outer_fold * 100 + 53,
            device=device,
            epochs=tuning["best_epoch"],
        )
        outer_anchor_indices = _indices_for_fold(data.anchors, outer_fold)
        outer_segment_indices = _indices_for_fold(data.segments, outer_fold)
        fold_anchor_rows = _predict_anchors(
            final["model"],
            data,
            outer_anchor_indices,
            config=config,
            device=device,
        )
        fold_segment_rows = _predict_segments(
            final["model"],
            data,
            outer_segment_indices,
            config=config,
            device=device,
        )
        fold_anchor_calibration = _with_outer_fold(
            _predict_anchors(
                tuning["model"],
                data,
                anchor_inner_validation,
                config=config,
                device=device,
            ),
            outer_fold=outer_fold,
        )
        fold_segment_calibration = _with_outer_fold(
            _predict_segments(
                tuning["model"],
                data,
                segment_inner_validation,
                config=config,
                device=device,
            ),
            outer_fold=outer_fold,
        )
        anchor_rows.extend(fold_anchor_rows)
        segment_rows.extend(fold_segment_rows)
        anchor_calibration_rows.extend(fold_anchor_calibration)
        segment_calibration_rows.extend(fold_segment_calibration)
        checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        torch.save(
            {
                "state_dict": {
                    key: value.detach().cpu()
                    for key, value in final["model"].state_dict().items()
                },
                "config": asdict(config),
                "seed": seed,
                "outer_fold": outer_fold,
                "best_epoch": tuning["best_epoch"],
            },
            checkpoint,
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "best_epoch": tuning["best_epoch"],
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_validation": _joint_metrics(
                fold_anchor_calibration,
                fold_segment_calibration,
            ),
            "outer_validation": _joint_metrics(
                fold_anchor_rows,
                fold_segment_rows,
            ),
            "checkpoint": str(checkpoint.resolve()),
            "checkpoint_sha256": sha256_file(checkpoint),
        }
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)
        fold_rows.append(fold_summary)

    anchor_rows.sort(key=lambda row: str(row["sample_id"]))
    segment_rows.sort(key=lambda row: str(row["sample_id"]))
    anchor_calibration_rows.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    segment_calibration_rows.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    (
        anchor_release_rows,
        release_rows,
        release_summary,
        release_thresholds,
    ) = _apply_strict_nested_release_gate(
        data,
        anchor_rows=anchor_rows,
        segment_rows=segment_rows,
        anchor_calibration_rows=anchor_calibration_rows,
        segment_calibration_rows=segment_calibration_rows,
        base_rows=base_rows,
        base_calibration_rows=base_calibration_rows,
    )
    anchor_path = root / "anchor_oof_predictions.jsonl"
    segment_path = root / "segment_oof_predictions.jsonl"
    anchor_calibration_path = (
        root / "inner_anchor_calibration_predictions.jsonl"
    )
    segment_calibration_path = (
        root / "inner_segment_calibration_predictions.jsonl"
    )
    anchor_release_path = root / "anchor_release_oof_predictions.jsonl"
    release_path = root / "release_oof_predictions.jsonl"
    _write_jsonl(anchor_path, anchor_rows)
    _write_jsonl(segment_path, segment_rows)
    _write_jsonl(anchor_calibration_path, anchor_calibration_rows)
    _write_jsonl(segment_calibration_path, segment_calibration_rows)
    _write_jsonl(anchor_release_path, anchor_release_rows)
    _write_jsonl(release_path, release_rows)
    model = JointAnchorSegmentGate(config)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "JOINT_ANCHOR_SEGMENT_GATE_STRICT_NESTED_OOF",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "config": asdict(config),
        "parameter_count": sum(
            parameter.numel() for parameter in model.parameters()
        ),
        "anchor_count": len(data.anchors),
        "anchor_supervised_count": sum(
            row.gate_supervised for row in data.anchors
        ),
        "segment_count": len(data.segments),
        "segment_supervised_count": sum(
            row.gate_supervised for row in data.segments
        ),
        "fold_count": len(folds),
        "epoch_selection": (
            "inner fold loss only; fixed selected epoch retrained on all "
            "outer-training folds"
        ),
        "shared_encoder_contract": (
            "Segment gate loss backpropagates through the same anchor evidence "
            "encoder used by the per-anchor gate head."
        ),
        "metrics": _joint_metrics(anchor_rows, segment_rows),
        "release": release_summary,
        "release_thresholds": release_thresholds,
        "release_threshold_source": (
            "each outer fold uses only its inner validation predictions; "
            "outer labels are evaluation-only"
        ),
        "folds": fold_rows,
        "inputs": {
            "anchor_manifest": _input_record(anchor_root / "manifest.json"),
            "candidate_manifest": _input_record(
                candidate_root / "manifest.json"
            ),
            "plan_labels": _input_record(
                label_root / "training_plan_labels.jsonl"
            ),
            "base_anchor_summary": _input_record(base_root / "summary.json"),
            "base_anchor_inner_calibration": _input_record(
                base_root / "inner_calibration_predictions.jsonl"
            ),
        },
        "outputs": {
            "anchor_oof_predictions": _input_record(anchor_path),
            "segment_oof_predictions": _input_record(segment_path),
            "inner_anchor_calibration_predictions": _input_record(
                anchor_calibration_path
            ),
            "inner_segment_calibration_predictions": _input_record(
                segment_calibration_path
            ),
            "anchor_release_oof_predictions": _input_record(
                anchor_release_path
            ),
            "release_oof_predictions": _input_record(release_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            release_summary["unsafe_auto_anchor"] == 0
            and release_summary["unsafe_auto_segment"] == 0
        ),
        "decision": (
            "JOINT_GATE_DIAGNOSTIC_GO"
            if (
                release_summary["unsafe_auto_anchor"] == 0
                and release_summary["unsafe_auto_segment"] == 0
            )
            else "JOINT_GATE_DIAGNOSTIC_NO_GO"
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def _fit_with_early_stopping(
    data: JointGateData,
    *,
    anchor_training_indices: Sequence[int],
    segment_training_indices: Sequence[int],
    anchor_validation_indices: Sequence[int],
    segment_validation_indices: Sequence[int],
    config: JointGateConfig,
    seed: int,
    device: torch.device,
) -> dict[str, Any]:
    _seed(seed)
    model = JointAnchorSegmentGate(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    anchor_weights = _balanced_binary_weights(
        [
            data.anchors[index].gate_label
            for index in anchor_training_indices
            if data.anchors[index].gate_supervised
        ]
    ).to(device)
    segment_weights = _balanced_binary_weights(
        [
            data.segments[index].gate_label
            for index in segment_training_indices
            if data.segments[index].gate_supervised
        ]
    ).to(device)
    best_loss = math.inf
    best_epoch = 1
    best_state: dict[str, torch.Tensor] | None = None
    history: list[dict[str, float]] = []
    stale = 0
    for epoch in range(1, config.max_epochs + 1):
        train_loss = _train_epoch(
            model,
            data,
            anchor_indices=anchor_training_indices,
            segment_indices=segment_training_indices,
            optimizer=optimizer,
            anchor_class_weights=anchor_weights,
            segment_class_weights=segment_weights,
            config=config,
            seed=seed + epoch,
            device=device,
        )
        validation_loss = _evaluate_loss(
            model,
            data,
            anchor_indices=anchor_validation_indices,
            segment_indices=segment_validation_indices,
            anchor_class_weights=anchor_weights,
            segment_class_weights=segment_weights,
            config=config,
            device=device,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(
                {
                    key: value.detach().cpu()
                    for key, value in model.state_dict().items()
                }
            )
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("joint gate did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_fixed_epochs(
    data: JointGateData,
    *,
    anchor_training_indices: Sequence[int],
    segment_training_indices: Sequence[int],
    config: JointGateConfig,
    seed: int,
    device: torch.device,
    epochs: int,
) -> dict[str, Any]:
    _seed(seed)
    model = JointAnchorSegmentGate(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    anchor_weights = _balanced_binary_weights(
        [
            data.anchors[index].gate_label
            for index in anchor_training_indices
            if data.anchors[index].gate_supervised
        ]
    ).to(device)
    segment_weights = _balanced_binary_weights(
        [
            data.segments[index].gate_label
            for index in segment_training_indices
            if data.segments[index].gate_supervised
        ]
    ).to(device)
    history = []
    for epoch in range(1, epochs + 1):
        loss = _train_epoch(
            model,
            data,
            anchor_indices=anchor_training_indices,
            segment_indices=segment_training_indices,
            optimizer=optimizer,
            anchor_class_weights=anchor_weights,
            segment_class_weights=segment_weights,
            config=config,
            seed=seed + epoch,
            device=device,
        )
        history.append({"epoch": float(epoch), "train_loss": loss})
    return {"model": model, "history": history}


def _train_epoch(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    *,
    anchor_indices: Sequence[int],
    segment_indices: Sequence[int],
    optimizer: torch.optim.Optimizer,
    anchor_class_weights: torch.Tensor,
    segment_class_weights: torch.Tensor,
    config: JointGateConfig,
    seed: int,
    device: torch.device,
) -> float:
    model.train()
    rng = random.Random(seed)
    anchor_batches = _batches(anchor_indices, config.batch_size, rng)
    segment_batches = _batches(segment_indices, config.batch_size, rng)
    steps = max(len(anchor_batches), len(segment_batches))
    total = 0.0
    for step in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.zeros((), device=device)
        if anchor_batches:
            indices = anchor_batches[step % len(anchor_batches)]
            loss = loss + config.anchor_loss_weight * _anchor_loss(
                model,
                data,
                indices,
                class_weights=anchor_class_weights,
                device=device,
            )
        if segment_batches:
            indices = segment_batches[step % len(segment_batches)]
            loss = loss + config.segment_loss_weight * _segment_loss(
                model,
                data,
                indices,
                class_weights=segment_class_weights,
                device=device,
            )
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float(loss.detach().cpu())
    return total / max(steps, 1)


def _evaluate_loss(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    *,
    anchor_indices: Sequence[int],
    segment_indices: Sequence[int],
    anchor_class_weights: torch.Tensor,
    segment_class_weights: torch.Tensor,
    config: JointGateConfig,
    device: torch.device,
) -> float:
    model.eval()
    with torch.no_grad():
        anchor = _anchor_loss(
            model,
            data,
            anchor_indices,
            class_weights=anchor_class_weights,
            device=device,
        )
        segment = _segment_loss(
            model,
            data,
            segment_indices,
            class_weights=segment_class_weights,
            device=device,
        )
    return float(
        (
            config.anchor_loss_weight * anchor
            + config.segment_loss_weight * segment
        ).cpu()
    )


def _anchor_loss(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    indices: Sequence[int],
    *,
    class_weights: torch.Tensor,
    device: torch.device,
) -> torch.Tensor:
    features = data.anchor_features[list(indices)].to(device)
    labels = torch.tensor(
        [data.anchors[index].gate_label for index in indices],
        dtype=torch.long,
        device=device,
    )
    task = torch.tensor(
        [data.anchors[index].gate_supervised for index in indices],
        dtype=torch.bool,
        device=device,
    )
    sample = torch.tensor(
        [data.anchors[index].sample_weight for index in indices],
        dtype=torch.float32,
        device=device,
    )
    logits = model.forward_anchor(features)
    return _masked_weighted_binary_loss(
        logits,
        labels,
        task,
        sample,
        class_weights,
    )


def _segment_loss(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    indices: Sequence[int],
    *,
    class_weights: torch.Tensor,
    device: torch.device,
) -> torch.Tensor:
    batch = collate_joint_segment_gate_batch(data, indices)
    logits = model.forward_segment(
        segment_features=batch.segment_features.to(device),
        anchor_features=batch.anchor_features.to(device),
        anchor_mask=batch.anchor_mask.to(device),
    )
    return _masked_weighted_binary_loss(
        logits,
        batch.labels.to(device),
        batch.task_mask.to(device),
        batch.sample_weights.to(device),
        class_weights,
    )


def _masked_weighted_binary_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
    class_weights: torch.Tensor,
) -> torch.Tensor:
    losses = torch.nn.functional.cross_entropy(
        logits,
        labels,
        reduction="none",
    )
    weights = (
        task_mask.to(losses.dtype)
        * sample_weights
        * class_weights[labels]
    )
    if not bool(task_mask.any()):
        return logits.sum() * 0.0
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _predict_anchors(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    indices: Sequence[int],
    *,
    config: JointGateConfig,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows = []
    with torch.no_grad():
        for batch_indices in _ordered_batches(indices, config.batch_size):
            logits = model.forward_anchor(
                data.anchor_features[list(batch_indices)].to(device)
            )
            probabilities = logits.softmax(dim=-1)[:, 1].cpu().tolist()
            for index, probability in zip(
                batch_indices,
                probabilities,
                strict=True,
            ):
                source = data.anchors[index]
                rows.append(
                    {
                        "sample_id": source.sample_id,
                        "case_key": source.case_key,
                        "anchor_id": source.anchor_id,
                        "fold": source.fold,
                        "gate_label": source.gate_label,
                        "gate_supervised": source.gate_supervised,
                        "pass_probability": float(probability),
                        "predicted_pass": bool(
                            probability >= config.pass_threshold
                        ),
                    }
                )
    return rows


def _predict_segments(
    model: JointAnchorSegmentGate,
    data: JointGateData,
    indices: Sequence[int],
    *,
    config: JointGateConfig,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows = []
    with torch.no_grad():
        for batch_indices in _ordered_batches(indices, config.batch_size):
            batch = collate_joint_segment_gate_batch(data, batch_indices)
            logits = model.forward_segment(
                segment_features=batch.segment_features.to(device),
                anchor_features=batch.anchor_features.to(device),
                anchor_mask=batch.anchor_mask.to(device),
            )
            probabilities = logits.softmax(dim=-1)[:, 1].cpu().tolist()
            for index, probability in zip(
                batch_indices,
                probabilities,
                strict=True,
            ):
                source = data.segments[index]
                rows.append(
                    {
                        "sample_id": source.sample_id,
                        "case_key": source.case_key,
                        "segment_id": source.segment_id,
                        "fold": source.fold,
                        "gate_label": source.gate_label,
                        "gate_supervised": source.gate_supervised,
                        "required_anchor_count": len(
                            source.required_anchor_indices
                        ),
                        "pass_probability": float(probability),
                        "predicted_pass": bool(
                            probability >= config.pass_threshold
                        ),
                    }
                )
    return rows


def _with_outer_fold(
    rows: Sequence[Mapping[str, Any]],
    *,
    outer_fold: int,
) -> list[dict[str, Any]]:
    return [{**dict(row), "outer_fold": outer_fold} for row in rows]


def _apply_strict_nested_release_gate(
    data: JointGateData,
    *,
    anchor_rows: Sequence[Mapping[str, Any]],
    segment_rows: Sequence[Mapping[str, Any]],
    anchor_calibration_rows: Sequence[Mapping[str, Any]],
    segment_calibration_rows: Sequence[Mapping[str, Any]],
    base_rows: Mapping[str, Mapping[str, Any]],
    base_calibration_rows: Mapping[
        tuple[int, str],
        Mapping[str, Any],
    ],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    anchor_by_id = {row.sample_id: row for row in data.anchors}
    anchor_index_by_id = {
        row.sample_id: index for index, row in enumerate(data.anchors)
    }
    segment_by_id = {row.sample_id: row for row in data.segments}
    outer_folds = sorted({int(row["fold"]) for row in anchor_rows})
    if {
        int(row["outer_fold"]) for row in anchor_calibration_rows
    } != set(outer_folds):
        raise ValueError("joint release anchor calibration folds differ")
    if {
        int(row["outer_fold"]) for row in segment_calibration_rows
    } != set(outer_folds):
        raise ValueError("joint release Segment calibration folds differ")

    anchor_release_rows: list[dict[str, Any]] = []
    anchor_thresholds: dict[str, dict[str, float]] = {}
    outer_anchor_acceptance: dict[tuple[int, int], bool] = {}
    calibration_anchor_acceptance: dict[tuple[int, int], bool] = {}
    for outer_fold in outer_folds:
        calibration = [
            _anchor_release_evidence(
                row,
                anchor=anchor_by_id[str(row["sample_id"])],
                base=base_calibration_rows[
                    (outer_fold, str(row["sample_id"]))
                ],
            )
            for row in anchor_calibration_rows
            if int(row["outer_fold"]) == outer_fold
        ]
        held_out = [
            _anchor_release_evidence(
                row,
                anchor=anchor_by_id[str(row["sample_id"])],
                base=base_rows[str(row["sample_id"])],
            )
            for row in anchor_rows
            if int(row["fold"]) == outer_fold
        ]
        thresholds = _zero_unsafe_thresholds(calibration, held_out)
        anchor_thresholds[str(outer_fold)] = thresholds
        for row in calibration:
            accepted = _threshold_accepts(row, thresholds)
            index = anchor_index_by_id[str(row["sample_id"])]
            calibration_anchor_acceptance[(outer_fold, index)] = accepted
        for row in held_out:
            result = _release_result(row, thresholds=thresholds)
            index = anchor_index_by_id[str(row["sample_id"])]
            outer_anchor_acceptance[(outer_fold, index)] = bool(
                result["release_accepted"]
            )
            anchor_release_rows.append(result)

    segment_release_rows: list[dict[str, Any]] = []
    segment_thresholds: dict[str, dict[str, float]] = {}
    for outer_fold in outer_folds:
        calibration = [
            _segment_release_evidence(
                row,
                segment=segment_by_id[str(row["sample_id"])],
                anchors_accepted=all(
                    calibration_anchor_acceptance[(outer_fold, index)]
                    for index in segment_by_id[
                        str(row["sample_id"])
                    ].required_anchor_indices
                ),
            )
            for row in segment_calibration_rows
            if int(row["outer_fold"]) == outer_fold
        ]
        held_out = [
            _segment_release_evidence(
                row,
                segment=segment_by_id[str(row["sample_id"])],
                anchors_accepted=all(
                    outer_anchor_acceptance[(outer_fold, index)]
                    for index in segment_by_id[
                        str(row["sample_id"])
                    ].required_anchor_indices
                ),
            )
            for row in segment_rows
            if int(row["fold"]) == outer_fold
        ]
        thresholds = _zero_unsafe_thresholds(calibration, held_out)
        segment_thresholds[str(outer_fold)] = thresholds
        segment_release_rows.extend(
            _release_result(row, thresholds=thresholds)
            for row in held_out
        )

    anchor_release_rows.sort(key=lambda row: str(row["sample_id"]))
    segment_release_rows.sort(key=lambda row: str(row["sample_id"]))
    anchor_summary = _release_summary(anchor_release_rows)
    segment_summary = _release_summary(segment_release_rows)
    segment_supervised_count = sum(
        row.gate_supervised for row in data.segments
    )
    segment_supervised_accepted = sum(
        bool(row["release_accepted"]) and bool(row["gate_supervised"])
        for row in segment_release_rows
    )
    release_summary = {
        "anchor_release_accepted": anchor_summary["accepted"],
        "anchor_count": anchor_summary["count"],
        "anchor_safe_auto": anchor_summary["safe_auto"],
        "anchor_supervised_error_auto": anchor_summary[
            "supervised_error_auto"
        ],
        "anchor_unverifiable_auto": anchor_summary[
            "unverifiable_auto"
        ],
        "unsafe_auto_anchor": anchor_summary["unsafe_auto"],
        "segment_release_accepted": segment_summary["accepted"],
        "segment_count": segment_summary["count"],
        "segment_safe_auto": segment_summary["safe_auto"],
        "segment_supervised_error_auto": segment_summary[
            "supervised_error_auto"
        ],
        "segment_unverifiable_auto": segment_summary[
            "unverifiable_auto"
        ],
        "unsafe_auto_segment": segment_summary["unsafe_auto"],
        "segment_supervised_count": segment_supervised_count,
        "segment_supervised_accepted": segment_supervised_accepted,
        "segment_supervised_coverage": (
            segment_supervised_accepted / segment_supervised_count
            if segment_supervised_count
            else 0.0
        )
    }
    return (
        anchor_release_rows,
        segment_release_rows,
        release_summary,
        {
            "anchor": anchor_thresholds,
            "segment": segment_thresholds,
        },
    )


def _anchor_release_evidence(
    row: Mapping[str, Any],
    *,
    anchor: JointGateAnchorTarget,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    predicted = str(base.get("predicted") or "")
    success_index = ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
    no_evidence_index = ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
    raw_candidate = predicted in {"SUCCESS", "NO_EVIDENCE"}
    safe_success = bool(
        predicted == "SUCCESS"
        and anchor.status_supervised
        and anchor.status_label == success_index
        and anchor.candidate_supervised
        and base.get("candidate_acceptable_exact") is True
    )
    safe_no_evidence = bool(
        predicted == "NO_EVIDENCE"
        and anchor.status_supervised
        and anchor.status_label == no_evidence_index
    )
    status_error = bool(
        raw_candidate
        and anchor.status_supervised
        and (
            (predicted == "SUCCESS" and anchor.status_label != success_index)
            or (
                predicted == "NO_EVIDENCE"
                and anchor.status_label != no_evidence_index
            )
        )
    )
    candidate_error = bool(
        predicted == "SUCCESS"
        and anchor.status_supervised
        and anchor.status_label == success_index
        and anchor.candidate_supervised
        and base.get("candidate_acceptable_exact") is not True
    )
    if predicted == "NO_EVIDENCE":
        release_group = "NO_EVIDENCE"
    elif predicted == "SUCCESS":
        release_group = (
            f"SUCCESS:{base.get('candidate_type') or 'UNKNOWN'}"
        )
    else:
        release_group = "INELIGIBLE"
    base_release_confidence = _base_release_confidence(
        base,
        predicted=predicted,
    )
    return {
        **dict(row),
        "base_predicted": predicted,
        "base_candidate_type": str(base.get("candidate_type") or ""),
        "base_candidate_predicted_id": str(
            base.get("candidate_predicted_id") or ""
        ),
        "base_candidate_acceptable_exact": base.get(
            "candidate_acceptable_exact"
        ),
        "release_group": release_group,
        "joint_gate_pass_probability": float(row["pass_probability"]),
        "base_release_confidence": base_release_confidence,
        "release_score": min(
            float(row["pass_probability"]),
            base_release_confidence,
        ),
        "raw_release_candidate": raw_candidate,
        "proven_safe": safe_success or safe_no_evidence,
        "supervised_error_candidate": status_error or candidate_error,
    }


def _base_release_confidence(
    base: Mapping[str, Any],
    *,
    predicted: str,
) -> float:
    if predicted == "SUCCESS":
        return float(base.get("candidate_confidence_score") or 0.0)
    if predicted == "NO_EVIDENCE":
        probabilities = base.get("probabilities")
        no_evidence_probability = (
            float(probabilities.get("NO_EVIDENCE") or 0.0)
            if isinstance(probabilities, Mapping)
            else 0.0
        )
        return min(
            float(base.get("gate_pass_probability") or 0.0),
            no_evidence_probability,
        )
    return 0.0


def _segment_release_evidence(
    row: Mapping[str, Any],
    *,
    segment: JointGateSegmentExample,
    anchors_accepted: bool,
) -> dict[str, Any]:
    return {
        **dict(row),
        "all_required_anchor_release_pass": anchors_accepted,
        "release_group": "STANDARD",
        "release_score": float(row["pass_probability"]),
        "raw_release_candidate": anchors_accepted,
        "proven_safe": bool(
            segment.gate_supervised and segment.gate_label == 1
        ),
        "supervised_error_candidate": bool(
            segment.gate_supervised and segment.gate_label == 0
        ),
    }


def _zero_unsafe_thresholds(
    calibration_rows: Sequence[Mapping[str, Any]],
    held_out_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    groups = sorted(
        {
            str(row["release_group"])
            for row in (*calibration_rows, *held_out_rows)
        }
    )
    thresholds: dict[str, float] = {}
    for group in groups:
        relevant = [
            row
            for row in calibration_rows
            if str(row["release_group"]) == group
            and bool(row["raw_release_candidate"])
        ]
        safe_scores = [
            float(row["release_score"])
            for row in relevant
            if bool(row["proven_safe"])
        ]
        unsafe_scores = [
            float(row["release_score"])
            for row in relevant
            if not bool(row["proven_safe"])
        ]
        thresholds[group] = (
            max(unsafe_scores, default=-1.0) if safe_scores else 1.0
        )
    return thresholds


def _threshold_accepts(
    row: Mapping[str, Any],
    thresholds: Mapping[str, float],
) -> bool:
    threshold = float(thresholds.get(str(row["release_group"]), 1.0))
    return bool(
        row["raw_release_candidate"]
        and float(row["release_score"]) > threshold
    )


def _release_result(
    row: Mapping[str, Any],
    *,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    threshold = float(thresholds.get(str(row["release_group"]), 1.0))
    accepted = _threshold_accepts(row, thresholds)
    safe = bool(row["proven_safe"])
    supervised_error = bool(
        accepted and row["supervised_error_candidate"]
    )
    unsafe = bool(accepted and not safe)
    return {
        **dict(row),
        "release_threshold": threshold,
        "release_accepted": accepted,
        "release_safe_auto": bool(accepted and safe),
        "release_supervised_error_auto": supervised_error,
        "release_unverifiable_auto": bool(
            unsafe and not supervised_error
        ),
        "unsafe_auto": unsafe,
    }


def _release_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        "count": len(rows),
        "accepted": sum(bool(row["release_accepted"]) for row in rows),
        "safe_auto": sum(bool(row["release_safe_auto"]) for row in rows),
        "supervised_error_auto": sum(
            bool(row["release_supervised_error_auto"]) for row in rows
        ),
        "unverifiable_auto": sum(
            bool(row["release_unverifiable_auto"]) for row in rows
        ),
        "unsafe_auto": sum(bool(row["unsafe_auto"]) for row in rows),
    }


def _joint_metrics(
    anchor_rows: Sequence[Mapping[str, Any]],
    segment_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "anchor": _binary_metrics(anchor_rows),
        "segment": _binary_metrics(segment_rows),
    }


def _binary_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    supervised = [row for row in rows if bool(row["gate_supervised"])]
    true_negative = sum(
        int(not row["predicted_pass"] and int(row["gate_label"]) == 0)
        for row in supervised
    )
    false_positive = sum(
        int(row["predicted_pass"] and int(row["gate_label"]) == 0)
        for row in supervised
    )
    true_positive = sum(
        int(row["predicted_pass"] and int(row["gate_label"]) == 1)
        for row in supervised
    )
    false_negative = sum(
        int(not row["predicted_pass"] and int(row["gate_label"]) == 1)
        for row in supervised
    )
    return {
        "count": len(rows),
        "supervised_count": len(supervised),
        "accuracy": (
            (true_positive + true_negative) / len(supervised)
            if supervised
            else 0.0
        ),
        "failure_recall": (
            true_negative / (true_negative + false_positive)
            if true_negative + false_positive
            else 0.0
        ),
        "pass_recall": (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        ),
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def _balanced_binary_weights(labels: Sequence[int]) -> torch.Tensor:
    counts = [labels.count(index) for index in (0, 1)]
    total = sum(counts)
    if not total or any(count == 0 for count in counts):
        return torch.ones(2, dtype=torch.float32)
    return torch.tensor(
        [total / (2.0 * count) for count in counts],
        dtype=torch.float32,
    )


def _indices_for_fold(rows: Sequence[Any], fold: int) -> list[int]:
    return [index for index, row in enumerate(rows) if row.fold == fold]


def _indices_excluding_folds(
    rows: Sequence[Any],
    folds: set[int],
) -> list[int]:
    return [index for index, row in enumerate(rows) if row.fold not in folds]


def _inner_fold_for_outer(folds: Sequence[int], outer_fold: int) -> int:
    index = list(folds).index(outer_fold)
    return int(folds[(index + 1) % len(folds)])


def _batches(
    indices: Sequence[int],
    batch_size: int,
    rng: random.Random,
) -> list[list[int]]:
    values = list(indices)
    rng.shuffle(values)
    return [
        values[start : start + batch_size]
        for start in range(0, len(values), batch_size)
    ]


def _ordered_batches(
    indices: Sequence[int],
    batch_size: int,
) -> list[list[int]]:
    values = list(indices)
    return [
        values[start : start + batch_size]
        for start in range(0, len(values), batch_size)
    ]


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


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
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _input_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


__all__ = [
    "run_joint_gate_strict_nested_oof",
]
