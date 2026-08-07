from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    anchor_batches_for_fold,
    collate_anchor_pretrain_batch,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    move_training_batch,
    train_target_a_stage,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_anchor_status_oof(
    *,
    store_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
) -> Path:
    """Train Case-group OOF anchor-status heads and persist auditable artifacts."""
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
    if len(folds) < 2:
        raise ValueError("Target A OOF requires at least two non-empty folds")
    device = _resolve_device(requested_device)
    prediction_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        training_examples = [row for row in examples if row.fold != fold]
        fold_class_weights = _balanced_class_weights(training_examples)
        fold_config = replace(
            config,
            anchor_status_class_weights=fold_class_weights,
            anchor_gate_class_weights=(
                _balanced_gate_class_weights(training_examples)
                if config.learned_anchor_gate
                else ()
            ),
        )
        train_batches, validation_batches = anchor_batches_for_fold(
            examples,
            held_out_fold=fold,
            batch_size=batch_size,
            include_candidate_relations=(
                fold_config.structured_anchor_object_decoder
            ),
        )
        result = train_target_a_stage(
            train_batches,
            validation_batches,
            config=fold_config,
            seed=seed + fold,
            device=device,
        )
        validation_examples = [row for row in examples if row.fold == fold]
        fold_predictions = _predict_anchor_status(
            result.model,
            validation_examples,
            batch_size=batch_size,
            device=device,
        )
        prediction_rows.extend(fold_predictions)
        metrics = _classification_metrics(fold_predictions)
        checkpoint_path = root / f"fold_{fold}_checkpoint.pt"
        torch.save(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "stage": "ANCHOR_STATUS_OOF",
                "fold": fold,
                "seed": seed + fold,
                "config": asdict(fold_config),
                "state_signature": result.state_signature,
                "model_state_dict": {
                    key: value.detach().cpu()
                    for key, value in sorted(result.model.state_dict().items())
                },
            },
            checkpoint_path,
        )
        fold_row = {
            "fold": fold,
            "train_example_count": sum(row.fold != fold for row in examples),
            "validation_example_count": len(validation_examples),
            "anchor_status_class_weights": list(fold_class_weights),
            "best_epoch": result.best_epoch,
            "best_validation_loss": result.best_validation_loss,
            "wall_seconds": result.wall_seconds,
            "state_signature": result.state_signature,
            "checkpoint": str(checkpoint_path.resolve()),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "metrics": metrics,
            "history": result.history,
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{fold}_summary.json", fold_row)

    prediction_rows.sort(key=lambda row: row["case_key"])
    _write_jsonl(root / "oof_predictions.jsonl", prediction_rows)
    combined_metrics = _classification_metrics(prediction_rows)
    coverage_ok = (
        len(prediction_rows) == len(examples)
        and len({row["sample_id"] for row in prediction_rows}) == len(examples)
        and {row["sample_id"] for row in prediction_rows}
        == {row.sample_id for row in examples}
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_STATUS_OOF",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "config": asdict(config),
        "batch_size": batch_size,
        "parameter_count": parameter_count(TargetAJointNetwork(config)),
        "source_store": str(source_root),
        "source_manifest_sha256": sha256_file(source_root / "manifest.json"),
        "example_count": len(examples),
        "fold_count": len(folds),
        "folds": fold_rows,
        "oof_metrics": combined_metrics,
        "oof_coverage_exact": coverage_ok,
        "candidate_selection_supervised_count": sum(
            row.candidate_supervised for row in examples
        ),
        "anchor_status_loss": "fold_train_frequency_balanced_cross_entropy",
        "scope_statement": (
            "This stage jointly trains anchor status and available direct raw "
            "RCSD object selection. T05 Road-break/generated-Node selection "
            "remains masked and this is not complete RoadGraph performance."
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not coverage_ok:
        raise RuntimeError(f"Target A OOF prediction coverage differs: {root}")
    return root


def _predict_anchor_status(
    model: TargetAJointNetwork,
    examples: Sequence[AnchorPretrainExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source_examples = examples[start : start + batch_size]
            batch = move_training_batch(
                collate_anchor_pretrain_batch(
                    source_examples,
                    include_candidate_relations=(
                        model.config.structured_anchor_object_decoder
                    ),
                ),
                device,
            )
            outputs = model(batch.tensors)
            logits = outputs["anchor_status_logits"][:, 0, :]
            candidate_logits = outputs["anchor_candidate_logits"][:, 0, :]
            probabilities = torch.softmax(logits, dim=-1).detach().cpu()
            gate_pass_probabilities = (
                torch.softmax(
                    outputs["anchor_gate_logits"][:, 0, :],
                    dim=-1,
                )[:, 1]
                .detach()
                .cpu()
                if "anchor_gate_logits" in outputs
                else torch.ones(len(source_examples))
            )
            candidate_predictions = candidate_logits.argmax(dim=-1).detach().cpu()
            raw_predictions = probabilities.argmax(dim=-1)
            for (
                example,
                raw_predicted,
                probability,
                gate_pass_probability,
                candidate_prediction,
            ) in zip(
                source_examples,
                raw_predictions.tolist(),
                probabilities.tolist(),
                gate_pass_probabilities.tolist(),
                candidate_predictions.tolist(),
                strict=True,
            ):
                gate_passed = (
                    float(gate_pass_probability)
                    >= model.config.anchor_gate_pass_threshold
                )
                predicted = (
                    int(raw_predicted)
                    if gate_passed
                    else ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
                )
                acceptable = set(example.candidate_acceptable_indices)
                rows.append(
                    {
                        "sample_id": example.sample_id,
                        "case_key": example.case_key,
                        "anchor_id": example.anchor_id,
                        "fold": example.fold,
                        "label_index": example.status_label,
                        "label": list(AnchorStatus)[example.status_label].value,
                        "status_supervised": example.status_supervised,
                        "gate_label": example.gate_label,
                        "gate_supervised": example.gate_supervised,
                        "gate_pass_probability": float(
                            gate_pass_probability
                        ),
                        "gate_passed": gate_passed,
                        "raw_status_predicted_index": int(raw_predicted),
                        "raw_status_predicted": list(AnchorStatus)[
                            int(raw_predicted)
                        ].value,
                        "predicted_index": int(predicted),
                        "predicted": list(AnchorStatus)[int(predicted)].value,
                        "probabilities": {
                            status.value: float(probability[index])
                            for index, status in enumerate(AnchorStatus)
                        },
                        "candidate_supervised": example.candidate_supervised,
                        "candidate_predicted_index": int(candidate_prediction),
                        "candidate_predicted_id": example.candidate_ids[
                            int(candidate_prediction)
                        ],
                        "candidate_acceptable_indices": sorted(acceptable),
                        "candidate_acceptable_ids": [
                            example.candidate_ids[index]
                            for index in sorted(acceptable)
                        ],
                        "candidate_preferred_index": (
                            example.preferred_candidate_index
                        ),
                        "candidate_preferred_id": (
                            example.candidate_ids[
                                example.preferred_candidate_index
                            ]
                            if example.preferred_candidate_index >= 0
                            else ""
                        ),
                        "candidate_acceptable_exact": (
                            int(candidate_prediction) in acceptable
                            if example.candidate_supervised
                            else None
                        ),
                        "candidate_preferred_exact": (
                            int(candidate_prediction)
                            == example.preferred_candidate_index
                            if example.candidate_supervised
                            and example.preferred_candidate_index >= 0
                            else None
                        ),
                    }
                )
    return rows


def _classification_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("classification metrics require prediction rows")
    status_rows = [
        row for row in rows if bool(row.get("status_supervised", True))
    ]
    if not status_rows:
        raise ValueError("classification metrics require supervised status rows")
    labels = [int(row["label_index"]) for row in status_rows]
    predictions = [int(row["predicted_index"]) for row in status_rows]
    candidate_rows = [
        row for row in rows if bool(row.get("candidate_supervised"))
    ]
    gate_rows = [row for row in rows if bool(row.get("gate_supervised"))]
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    supported_f1_values: list[float] = []
    for index, status in enumerate(AnchorStatus):
        true_positive = sum(
            label == index and prediction == index
            for label, prediction in zip(labels, predictions, strict=True)
        )
        false_positive = sum(
            label != index and prediction == index
            for label, prediction in zip(labels, predictions, strict=True)
        )
        false_negative = sum(
            label == index and prediction != index
            for label, prediction in zip(labels, predictions, strict=True)
        )
        support = sum(label == index for label in labels)
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        f1_values.append(f1)
        if support:
            supported_f1_values.append(f1)
        per_class[status.value] = {
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "count": len(status_rows),
        "prediction_count": len(rows),
        "accuracy": sum(
            label == prediction
            for label, prediction in zip(labels, predictions, strict=True)
        )
        / len(status_rows),
        "macro_f1_all_statuses": sum(f1_values) / len(f1_values),
        "macro_f1_supported_statuses": (
            sum(supported_f1_values) / len(supported_f1_values)
            if supported_f1_values
            else 0.0
        ),
        "per_class": per_class,
        "candidate_selection": {
            "supervised_count": len(candidate_rows),
            "acceptable_exact": (
                sum(bool(row["candidate_acceptable_exact"]) for row in candidate_rows)
                / len(candidate_rows)
                if candidate_rows
                else 0.0
            ),
            "preferred_exact": (
                sum(bool(row["candidate_preferred_exact"]) for row in candidate_rows)
                / len(candidate_rows)
                if candidate_rows
                else 0.0
            ),
        },
        "anchor_gate": {
            "supervised_count": len(gate_rows),
            "accuracy": (
                sum(
                    int(bool(row["gate_label"]))
                    == int(bool(row["gate_passed"]))
                    for row in gate_rows
                )
                / len(gate_rows)
                if gate_rows
                else 0.0
            ),
            "pass_recall": _binary_recall(
                gate_rows,
                label=True,
            ),
            "failure_recall": _binary_recall(
                gate_rows,
                label=False,
            ),
        },
    }


def _balanced_class_weights(
    examples: Sequence[AnchorPretrainExample],
) -> tuple[float, ...]:
    supervised = [
        row for row in examples if bool(getattr(row, "status_supervised", True))
    ]
    counts = [
        sum(row.status_label == index for row in supervised)
        for index, _ in enumerate(AnchorStatus)
    ]
    supported = sum(count > 0 for count in counts)
    if supported < 2:
        raise ValueError("anchor status class balancing requires two classes")
    total = len(supervised)
    return tuple(
        total / (supported * count) if count else 0.0
        for count in counts
    )


def _balanced_gate_class_weights(
    examples: Sequence[AnchorPretrainExample],
) -> tuple[float, float]:
    supervised = [row for row in examples if row.gate_supervised]
    counts = [
        sum(row.gate_label == index for row in supervised)
        for index in range(2)
    ]
    if not supervised or min(counts) < 1:
        raise ValueError("anchor gate balancing requires both gate classes")
    total = len(supervised)
    return tuple(total / (2 * count) for count in counts)


def _binary_recall(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: bool,
) -> float:
    selected = [row for row in rows if bool(row["gate_label"]) is label]
    if not selected:
        return 0.0
    return sum(bool(row["gate_passed"]) is label for row in selected) / len(
        selected
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
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


__all__ = ["run_anchor_status_oof"]
