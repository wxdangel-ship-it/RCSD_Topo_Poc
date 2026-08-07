from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    move_training_batch,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_anchor_oof_safety_calibration(
    *,
    store_root: Path,
    oof_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    batch_size: int,
    requested_device: str = "cuda",
) -> Path:
    """Rescore OOF checkpoints and apply fold-isolated conservative gates."""
    started = time.perf_counter()
    config.validate()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source_root = normalize_runtime_path(store_root).resolve(strict=True)
    prediction_root = normalize_runtime_path(oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_anchor_pretraining_stores(source_root)
    prediction_rows = {
        str(row["sample_id"]): row
        for row in _read_jsonl(prediction_root / "oof_predictions.jsonl")
    }
    if set(prediction_rows) != {row.sample_id for row in examples}:
        raise ValueError("anchor safety input does not have exact OOF coverage")
    device = _resolve_device(requested_device)
    enriched: list[dict[str, Any]] = []
    for fold in sorted({row.fold for row in examples}):
        checkpoint_path = prediction_root / f"fold_{fold}_checkpoint.pt"
        checkpoint = torch.load(
            checkpoint_path,
            map_location=device,
            weights_only=False,
        )
        model = TargetAJointNetwork(config).to(device)
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        fold_examples = [row for row in examples if row.fold == fold]
        for row in _candidate_confidence_rows(
            model,
            fold_examples,
            batch_size=batch_size,
            device=device,
        ):
            original = prediction_rows[row["sample_id"]]
            if (
                int(original["predicted_index"]) != row["status_predicted_index"]
                or int(original["candidate_predicted_index"])
                != row["candidate_predicted_index"]
            ):
                raise RuntimeError("anchor checkpoint rescore differs from OOF row")
            acceptable_exact = original.get("candidate_acceptable_exact")
            proven_safe = bool(
                original["label"] == "SUCCESS"
                and acceptable_exact is True
            )
            enriched.append(
                {
                    **original,
                    **row,
                    "proven_safe_anchor": proven_safe,
                    "raw_unsafe_success": bool(
                        original["predicted"] == "SUCCESS" and not proven_safe
                    ),
                }
            )
    gated, thresholds = _apply_fold_excluded_safety_gate(enriched)
    gated.sort(key=lambda row: str(row["sample_id"]))
    _write_jsonl(root / "gated_oof_predictions.jsonl", gated)
    summary = _safety_summary(gated)
    summary.update(
        {
            "stage": "ANCHOR_OOF_SAFETY_CALIBRATION",
            "run_id": run_id,
            "requested_device": requested_device,
            "actual_device": str(device),
            "example_count": len(gated),
            "fold_count": len({int(row["fold"]) for row in gated}),
            "fold_excluded_thresholds": thresholds,
            "source_store_manifest_sha256": sha256_file(
                source_root / "manifest.json"
            ),
            "source_oof_summary_sha256": sha256_file(
                prediction_root / "summary.json"
            ),
            "candidate_confidence_uses_truth": False,
            "threshold_calibration_group": "OTHER_OOF_FOLDS",
            "threshold_calibration_limit": (
                "held-out fold labels are excluded directly; this is "
                "cross-fitted calibration, not strict nested CV"
            ),
            "threshold_objective": (
                "zero proven-unsafe SUCCESS on calibration folds, then "
                "maximize retained proven-safe anchors through the resulting "
                "minimum confidence threshold"
            ),
            "acceptance_requires_raw_success": True,
            "terminal_feature_count": 0,
            "wall_seconds": time.perf_counter() - started,
        }
    )
    _write_json(root / "summary.json", summary)
    return root


def _candidate_confidence_rows(
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
            source = examples[start : start + batch_size]
            batch = move_training_batch(
                collate_anchor_pretrain_batch(
                    source,
                    include_candidate_relations=(
                        model.config.structured_anchor_object_decoder
                    ),
                ),
                device,
            )
            outputs = model(batch.tensors)
            status_probabilities = torch.softmax(
                outputs["anchor_status_logits"][:, 0, :],
                dim=-1,
            ).detach().cpu()
            gate_pass_probabilities = (
                torch.softmax(
                    outputs["anchor_gate_logits"][:, 0, :],
                    dim=-1,
                )[:, 1]
                .detach()
                .cpu()
                if "anchor_gate_logits" in outputs
                else torch.ones(len(source))
            )
            candidate_probabilities = torch.softmax(
                outputs["anchor_candidate_logits"][:, 0, :],
                dim=-1,
            ).detach().cpu()
            for (
                example,
                status_probability,
                gate_pass_probability,
                candidate_probability,
            ) in zip(
                source,
                status_probabilities,
                gate_pass_probabilities,
                candidate_probabilities,
                strict=True,
            ):
                predicted_index = int(candidate_probability.argmax().item())
                ordered = candidate_probability.sort(descending=True).values
                top_one = float(ordered[0].item())
                top_two = float(ordered[1].item()) if len(ordered) > 1 else 0.0
                success_probability = float(status_probability[0].item())
                raw_status_predicted_index = int(
                    status_probability.argmax().item()
                )
                gate_passed = (
                    float(gate_pass_probability)
                    >= model.config.anchor_gate_pass_threshold
                )
                status_predicted_index = (
                    raw_status_predicted_index
                    if gate_passed
                    else ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
                )
                candidate_type = _candidate_type(example, predicted_index)
                score = min(
                    float(gate_pass_probability),
                    success_probability,
                    top_one,
                    max(0.0, top_one - top_two),
                )
                rows.append(
                    {
                        "sample_id": example.sample_id,
                        "status_predicted_index": status_predicted_index,
                        "raw_status_predicted_index": (
                            raw_status_predicted_index
                        ),
                        "gate_pass_probability": float(
                            gate_pass_probability
                        ),
                        "gate_passed": gate_passed,
                        "success_probability": success_probability,
                        "candidate_probability": top_one,
                        "candidate_margin": top_one - top_two,
                        "candidate_confidence_score": score,
                        "candidate_predicted_index": predicted_index,
                        "candidate_type": candidate_type,
                    }
                )
    return rows


def _candidate_type(
    example: AnchorPretrainExample,
    predicted_index: int,
) -> str:
    family = example.case_key.split(":", 1)[0]
    if family not in {"T10", "T10-Error", "T10-Error-2"}:
        return "SINGLE_POINT"
    features = example.candidate_features[predicted_index]
    return "ROAD" if features[27] > 0.5 else "NODE"


def _apply_fold_excluded_safety_gate(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    if not rows:
        raise ValueError("anchor safety calibration requires prediction rows")
    folds = sorted({int(row["fold"]) for row in rows})
    candidate_types = sorted({str(row["candidate_type"]) for row in rows})
    thresholds: dict[str, dict[str, float]] = {}
    gated: list[dict[str, Any]] = []
    for held_out_fold in folds:
        fold_thresholds: dict[str, float] = {}
        calibration = [
            row for row in rows if int(row["fold"]) != held_out_fold
        ]
        for candidate_type in candidate_types:
            proven_safe_scores = [
                float(row["candidate_confidence_score"])
                for row in calibration
                if str(row["candidate_type"]) == candidate_type
                and bool(row["proven_safe_anchor"])
            ]
            unsafe_scores = [
                float(row["candidate_confidence_score"])
                for row in calibration
                if str(row["candidate_type"]) == candidate_type
                and str(row["predicted"]) == "SUCCESS"
                and not bool(row["proven_safe_anchor"])
            ]
            threshold = (
                max(unsafe_scores, default=-1.0)
                if proven_safe_scores
                else 1.0
            )
            fold_thresholds[candidate_type] = threshold
        thresholds[str(held_out_fold)] = fold_thresholds
        for row in rows:
            if int(row["fold"]) != held_out_fold:
                continue
            threshold = fold_thresholds[str(row["candidate_type"])]
            accepted = bool(
                str(row["predicted"]) == "SUCCESS"
                and float(row["candidate_confidence_score"]) > threshold
            )
            failure_flags = _safety_failure_flags(row, accepted=accepted)
            gated.append(
                {
                    **row,
                    "safety_threshold": threshold,
                    "safety_accepted": accepted,
                    "safety_unsafe_auto": bool(
                        accepted and not bool(row["proven_safe_anchor"])
                    ),
                    **failure_flags,
                }
            )
    return gated, thresholds


def apply_inner_calibrated_anchor_safety_gate(
    calibration_rows: Sequence[Mapping[str, Any]],
    oof_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """Apply thresholds learned only from each outer fold's inner validation."""
    if not calibration_rows or not oof_rows:
        raise ValueError("strict anchor safety calibration requires both row sets")
    outer_folds = sorted({int(row["fold"]) for row in oof_rows})
    calibration_folds = {
        int(row["outer_fold"]) for row in calibration_rows
    }
    if set(outer_folds) != calibration_folds:
        raise ValueError("strict anchor safety fold coverage differs")
    thresholds: dict[str, dict[str, float]] = {}
    gated: list[dict[str, Any]] = []
    for outer_fold in outer_folds:
        calibration = [
            row
            for row in calibration_rows
            if int(row["outer_fold"]) == outer_fold
        ]
        held_out = [
            row for row in oof_rows if int(row["fold"]) == outer_fold
        ]
        candidate_types = sorted(
            {
                str(row["candidate_type"])
                for row in (*calibration, *held_out)
            }
        )
        fold_thresholds: dict[str, float] = {}
        for candidate_type in candidate_types:
            proven_safe_scores = [
                float(row["candidate_confidence_score"])
                for row in calibration
                if str(row["candidate_type"]) == candidate_type
                and bool(row["proven_safe_anchor"])
            ]
            unsafe_scores = [
                float(row["candidate_confidence_score"])
                for row in calibration
                if str(row["candidate_type"]) == candidate_type
                and bool(row["raw_unsafe_success"])
            ]
            fold_thresholds[candidate_type] = (
                max(unsafe_scores, default=-1.0)
                if proven_safe_scores
                else 1.0
            )
        thresholds[str(outer_fold)] = fold_thresholds
        for row in held_out:
            threshold = fold_thresholds[str(row["candidate_type"])]
            accepted = bool(
                str(row["predicted"]) == "SUCCESS"
                and float(row["candidate_confidence_score"]) > threshold
            )
            failure_flags = _safety_failure_flags(row, accepted=accepted)
            gated.append(
                {
                    **row,
                    "safety_calibration_outer_fold": outer_fold,
                    "safety_threshold": threshold,
                    "safety_accepted": accepted,
                    "safety_unsafe_auto": bool(
                        accepted and not bool(row["proven_safe_anchor"])
                    ),
                    **failure_flags,
                }
            )
    return gated, thresholds


def _safety_failure_flags(
    row: Mapping[str, Any],
    *,
    accepted: bool,
) -> dict[str, bool]:
    unsafe = bool(accepted and not bool(row["proven_safe_anchor"]))
    supervised_status_error = bool(
        unsafe
        and bool(row.get("status_supervised"))
        and str(row.get("label")) != AnchorStatus.SUCCESS.value
    )
    supervised_candidate_error = bool(
        unsafe
        and str(row.get("label")) == AnchorStatus.SUCCESS.value
        and bool(row.get("candidate_supervised"))
        and row.get("candidate_acceptable_exact") is not True
    )
    supervised_error = supervised_status_error or supervised_candidate_error
    return {
        "safety_supervised_error_auto": supervised_error,
        "safety_unverifiable_auto": bool(unsafe and not supervised_error),
    }


def _safety_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_fold: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        accepted = bool(row["safety_accepted"])
        safe = bool(row["proven_safe_anchor"])
        raw_success = str(row["predicted"]) == "SUCCESS"
        failure_flags = _safety_failure_flags(row, accepted=accepted)
        values = {
            "example": True,
            "proven_safe": safe,
            "raw_success": raw_success,
            "raw_unsafe_success": bool(row["raw_unsafe_success"]),
            "safety_accepted": accepted,
            "safety_safe_auto": accepted and safe,
            "safety_unsafe_auto": accepted and not safe,
            **failure_flags,
        }
        for key, value in values.items():
            counts[key] += int(value)
            per_type[str(row["candidate_type"])][key] += int(value)
            per_fold[int(row["fold"])][key] += int(value)
    return {
        "counts": dict(sorted(counts.items())),
        "accepted_coverage": (
            counts["safety_accepted"] / counts["example"]
            if counts["example"]
            else 0.0
        ),
        "proven_safe_recall": (
            counts["safety_safe_auto"] / counts["proven_safe"]
            if counts["proven_safe"]
            else 0.0
        ),
        "per_candidate_type": {
            key: dict(sorted(value.items()))
            for key, value in sorted(per_type.items())
        },
        "per_fold": {
            str(key): dict(sorted(value.items()))
            for key, value in sorted(per_fold.items())
        },
        "safety_gate_pass": counts["safety_unsafe_auto"] == 0,
    }


def _resolve_device(requested: str) -> torch.device:
    normalized = requested.strip().lower()
    if normalized == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if normalized in {"cuda", "cpu"}:
        return torch.device("cpu")
    raise ValueError(f"unsupported Target A device: {requested}")


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


__all__ = [
    "apply_inner_calibrated_anchor_safety_gate",
    "run_anchor_oof_safety_calibration",
]
