from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
    collate_ordinary_plan_batch,
    ordinary_batches_for_fold,
    read_ordinary_plan_training_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    move_training_batch,
    train_target_a_stage,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_ordinary_plan_oof(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
) -> Path:
    """Train ordinary complete-plan selection under teacher-forced anchor locks."""
    started = time.perf_counter()
    config.validate()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(preflight_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_ordinary_plan_training_examples(
        candidate_store_root=candidate_root,
        preflight_root=label_root,
    )
    folds = sorted({row.fold for row in examples})
    if len(folds) < 2:
        raise ValueError("ordinary plan OOF requires at least two folds")
    device = _resolve_device(requested_device)
    predictions: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        train_batches, validation_batches = ordinary_batches_for_fold(
            examples,
            held_out_fold=fold,
            batch_size=batch_size,
        )
        result = train_target_a_stage(
            train_batches,
            validation_batches,
            config=config,
            seed=seed + fold,
            device=device,
        )
        validation_examples = [row for row in examples if row.fold == fold]
        fold_predictions = _predict_plans(
            result.model,
            validation_examples,
            batch_size=batch_size,
            device=device,
        )
        predictions.extend(fold_predictions)
        checkpoint_path = root / f"fold_{fold}_checkpoint.pt"
        torch.save(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "stage": "ORDINARY_PLAN_TEACHER_FORCING_OOF",
                "fold": fold,
                "seed": seed + fold,
                "config": asdict(config),
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
            "best_epoch": result.best_epoch,
            "best_validation_loss": result.best_validation_loss,
            "wall_seconds": result.wall_seconds,
            "state_signature": result.state_signature,
            "checkpoint": str(checkpoint_path.resolve()),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "metrics": _plan_metrics(fold_predictions),
            "history": result.history,
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{fold}_summary.json", fold_row)
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    coverage_ok = (
        len(predictions) == len(examples)
        and {row["sample_id"] for row in predictions}
        == {row.sample_id for row in examples}
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_PLAN_TEACHER_FORCING_OOF",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "config": asdict(config),
        "parameter_count": parameter_count(TargetAJointNetwork(config)),
        "candidate_store_manifest_sha256": sha256_file(
            candidate_root / "manifest.json"
        ),
        "preflight_summary_sha256": sha256_file(label_root / "summary.json"),
        "example_count": len(examples),
        "fold_count": len(folds),
        "folds": fold_rows,
        "oof_metrics": _plan_metrics(predictions),
        "oof_coverage_exact": coverage_ok,
        "teacher_forced_anchor": True,
        "scope_statement": (
            "This stage evaluates ordinary complete-plan scoring only on "
            "truth-free candidate groups whose accepted plan is reachable. "
            "It does not measure OOF-anchor-conditioned or full RoadGraph exact."
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not coverage_ok:
        raise RuntimeError(f"ordinary plan OOF coverage differs: {root}")
    return root


def _predict_plans(
    model: TargetAJointNetwork,
    examples: Sequence[OrdinaryPlanTrainingExample],
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
                collate_ordinary_plan_batch(source_examples),
                device,
            )
            logits = model(batch.tensors)["ordinary_plan_logits"][:, 0, :]
            probabilities = torch.softmax(logits, dim=-1).detach().cpu()
            predictions = probabilities.argmax(dim=-1).tolist()
            for example, predicted_index, probability in zip(
                source_examples,
                predictions,
                probabilities.tolist(),
                strict=True,
            ):
                acceptable = set(example.acceptable_indices)
                acceptable_decisions = sorted(
                    {
                        example.candidate_decisions[index]
                        for index in acceptable
                    }
                )
                rows.append(
                    {
                        "sample_id": example.sample_id,
                        "case_key": example.case_key,
                        "segment_id": example.segment_id,
                        "fold": example.fold,
                        "predicted_plan_id": example.candidate_ids[predicted_index],
                        "predicted_decision": example.candidate_decisions[
                            predicted_index
                        ],
                        "predicted_probability": float(
                            probability[predicted_index]
                        ),
                        "acceptable_plan_ids": [
                            example.candidate_ids[index]
                            for index in example.acceptable_indices
                        ],
                        "acceptable_decisions": acceptable_decisions,
                        "preferred_plan_id": (
                            example.candidate_ids[example.preferred_index]
                            if example.preferred_index >= 0
                            else ""
                        ),
                        "preferred_decision": example.preferred_decision,
                        "acceptable_exact": predicted_index in acceptable,
                        "preferred_exact": (
                            predicted_index == example.preferred_index
                            if example.preferred_index >= 0
                            else None
                        ),
                    }
                )
    return rows


def _plan_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("plan metrics require prediction rows")
    acceptable = sum(bool(row["acceptable_exact"]) for row in rows)
    decision_correct = sum(
        str(row["predicted_decision"]) in set(row["acceptable_decisions"])
        for row in rows
    )
    preferred_rows = [
        row for row in rows if row.get("preferred_exact") is not None
    ]
    per_decision: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        preferred = str(row.get("preferred_decision") or "")
        per_decision[preferred]["support"] += 1
        per_decision[preferred]["acceptable_exact"] += int(
            bool(row["acceptable_exact"])
        )
        per_decision[preferred]["decision_correct"] += int(
            str(row["predicted_decision"]) in set(row["acceptable_decisions"])
        )
    return {
        "count": len(rows),
        "complete_plan_acceptable_exact": acceptable / len(rows),
        "carrier_decision_accuracy": decision_correct / len(rows),
        "preferred_plan_exact": (
            sum(bool(row["preferred_exact"]) for row in preferred_rows)
            / len(preferred_rows)
            if preferred_rows
            else 0.0
        ),
        "preferred_plan_count": len(preferred_rows),
        "always_keep_decision_accuracy": sum(
            "KEEP_SWSD" in set(row["acceptable_decisions"]) for row in rows
        )
        / len(rows),
        "per_preferred_decision": {
            decision: {
                "support": counts["support"],
                "complete_plan_acceptable_exact": (
                    counts["acceptable_exact"] / counts["support"]
                ),
                "carrier_decision_accuracy": (
                    counts["decision_correct"] / counts["support"]
                ),
            }
            for decision, counts in sorted(per_decision.items())
        },
    }


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
                + "\n"
            )


__all__ = ["run_ordinary_plan_oof"]
