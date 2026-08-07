from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_anchor_oof_consensus_safety(
    *,
    safety_roots: Sequence[Path],
    output_root: Path,
    run_id: str,
    required_seed_count: int = 3,
) -> Path:
    """Build a fold-isolated safety gate from agreeing OOF anchor seeds."""
    started = time.perf_counter()
    if len(safety_roots) != required_seed_count:
        raise ValueError(
            f"anchor consensus requires exactly {required_seed_count} seeds"
        )
    roots = [
        normalize_runtime_path(root).resolve(strict=True)
        for root in safety_roots
    ]
    if len(set(roots)) != len(roots):
        raise ValueError("anchor consensus safety roots must be unique")
    destination = normalize_runtime_path(output_root).resolve() / run_id
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)

    summaries = [_read_json(root / "summary.json") for root in roots]
    row_groups = [
        _read_jsonl(root / "gated_oof_predictions.jsonl")
        for root in roots
    ]
    _validate_seed_inputs(summaries, row_groups)
    consensus_rows = _build_consensus_rows(row_groups)
    gated_rows, thresholds = _apply_fold_excluded_consensus_gate(consensus_rows)
    gated_rows.sort(key=lambda row: str(row["sample_id"]))
    _write_jsonl(destination / "consensus_gated_oof_predictions.jsonl", gated_rows)

    summary = _consensus_summary(gated_rows)
    summary.update(
        {
            "stage": "ANCHOR_OOF_MULTI_SEED_CONSENSUS_SAFETY",
            "run_id": run_id,
            "required_seed_count": required_seed_count,
            "seed_run_ids": [str(item["run_id"]) for item in summaries],
            "source_store_manifest_sha256": summaries[0][
                "source_store_manifest_sha256"
            ],
            "source_safety_summary_sha256": [
                sha256_file(root / "summary.json") for root in roots
            ],
            "source_prediction_sha256": [
                sha256_file(root / "gated_oof_predictions.jsonl")
                for root in roots
            ],
            "consensus_rule": (
                "all seeds predict SUCCESS and the same candidate index; "
                "confidence is the minimum per-seed confidence"
            ),
            "fold_excluded_thresholds": thresholds,
            "threshold_calibration_group": "OTHER_OOF_FOLDS",
            "threshold_calibration_limit": (
                "held-out fold labels are excluded directly; this is "
                "cross-fitted calibration, not strict nested CV"
            ),
            "threshold_objective": (
                "zero proven-unsafe consensus SUCCESS on calibration folds, "
                "then retain held-out consensus rows above that strict bound"
            ),
            "terminal_feature_count": 0,
            "wall_seconds": time.perf_counter() - started,
        }
    )
    _write_json(destination / "summary.json", summary)
    return destination


def _validate_seed_inputs(
    summaries: Sequence[Mapping[str, Any]],
    row_groups: Sequence[Sequence[Mapping[str, Any]]],
) -> None:
    if not summaries or len(summaries) != len(row_groups):
        raise ValueError("anchor consensus inputs are incomplete")
    source_hashes = {
        str(summary["source_store_manifest_sha256"]) for summary in summaries
    }
    if len(source_hashes) != 1:
        raise ValueError("anchor consensus seeds use different feature stores")
    run_ids = {str(summary["run_id"]) for summary in summaries}
    if len(run_ids) != len(summaries):
        raise ValueError("anchor consensus seed run IDs must be unique")
    sample_sets = [
        {str(row["sample_id"]) for row in rows} for rows in row_groups
    ]
    if not sample_sets[0] or any(items != sample_sets[0] for items in sample_sets[1:]):
        raise ValueError("anchor consensus seeds do not have identical OOF coverage")
    if any(len(rows) != len(sample_sets[0]) for rows in row_groups):
        raise ValueError("anchor consensus input contains duplicate sample IDs")


def _build_consensus_rows(
    row_groups: Sequence[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    if len(row_groups) < 2:
        raise ValueError("anchor consensus requires multiple seed predictions")
    indexed = [
        {str(row["sample_id"]): row for row in rows} for rows in row_groups
    ]
    rows: list[dict[str, Any]] = []
    for sample_id in sorted(indexed[0]):
        seed_rows = [items[sample_id] for items in indexed]
        _validate_sample_truth(seed_rows)
        predicted_indices = [
            int(row["candidate_predicted_index"]) for row in seed_rows
        ]
        candidate_agreement = len(set(predicted_indices)) == 1
        all_success = all(str(row["predicted"]) == "SUCCESS" for row in seed_rows)
        raw_consensus_success = candidate_agreement and all_success
        reference = seed_rows[0]
        acceptable = {
            int(index) for index in reference["candidate_acceptable_indices"]
        }
        candidate_supervised = bool(reference["candidate_supervised"])
        agreed_index = predicted_indices[0] if candidate_agreement else -1
        proven_safe = bool(
            raw_consensus_success
            and str(reference["label"]) == "SUCCESS"
            and candidate_supervised
            and agreed_index in acceptable
        )
        candidate_types = {str(row["candidate_type"]) for row in seed_rows}
        candidate_type = (
            next(iter(candidate_types))
            if candidate_agreement and len(candidate_types) == 1
            else "DISAGREE"
        )
        rows.append(
            {
                "sample_id": sample_id,
                "case_key": str(reference["case_key"]),
                "fold": int(reference["fold"]),
                "label": str(reference["label"]),
                "label_index": int(reference["label_index"]),
                "candidate_supervised": candidate_supervised,
                "candidate_acceptable_indices": sorted(acceptable),
                "candidate_agreement": candidate_agreement,
                "all_status_success": all_success,
                "consensus_raw_success": raw_consensus_success,
                "consensus_candidate_index": agreed_index,
                "consensus_candidate_type": candidate_type,
                "consensus_confidence_score": min(
                    float(row["candidate_confidence_score"]) for row in seed_rows
                ),
                "consensus_proven_safe_anchor": proven_safe,
                "consensus_raw_unsafe_success": bool(
                    raw_consensus_success and not proven_safe
                ),
                "seed_predictions": [
                    {
                        "predicted": str(row["predicted"]),
                        "candidate_predicted_index": int(
                            row["candidate_predicted_index"]
                        ),
                        "candidate_type": str(row["candidate_type"]),
                        "candidate_confidence_score": float(
                            row["candidate_confidence_score"]
                        ),
                    }
                    for row in seed_rows
                ],
            }
        )
    return rows


def _validate_sample_truth(seed_rows: Sequence[Mapping[str, Any]]) -> None:
    invariant_keys = (
        "sample_id",
        "case_key",
        "fold",
        "label",
        "label_index",
        "candidate_supervised",
        "candidate_acceptable_indices",
    )
    reference = seed_rows[0]
    for row in seed_rows[1:]:
        for key in invariant_keys:
            if row[key] != reference[key]:
                raise ValueError(
                    f"anchor consensus truth differs for {reference['sample_id']}: {key}"
                )


def _apply_fold_excluded_consensus_gate(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    if not rows:
        raise ValueError("anchor consensus gate requires prediction rows")
    folds = sorted({int(row["fold"]) for row in rows})
    candidate_types = sorted(
        {
            str(row["consensus_candidate_type"])
            for row in rows
            if str(row["consensus_candidate_type"]) != "DISAGREE"
        }
    )
    thresholds: dict[str, dict[str, float]] = {}
    gated: list[dict[str, Any]] = []
    for held_out_fold in folds:
        calibration = [row for row in rows if int(row["fold"]) != held_out_fold]
        fold_thresholds: dict[str, float] = {}
        for candidate_type in candidate_types:
            safe_scores = [
                float(row["consensus_confidence_score"])
                for row in calibration
                if str(row["consensus_candidate_type"]) == candidate_type
                and bool(row["consensus_raw_success"])
                and bool(row["consensus_proven_safe_anchor"])
            ]
            unsafe_scores = [
                float(row["consensus_confidence_score"])
                for row in calibration
                if str(row["consensus_candidate_type"]) == candidate_type
                and bool(row["consensus_raw_unsafe_success"])
            ]
            fold_thresholds[candidate_type] = (
                max(unsafe_scores, default=-1.0) if safe_scores else 1.0
            )
        thresholds[str(held_out_fold)] = fold_thresholds
        for row in rows:
            if int(row["fold"]) != held_out_fold:
                continue
            candidate_type = str(row["consensus_candidate_type"])
            threshold = fold_thresholds.get(candidate_type, 1.0)
            accepted = bool(
                row["consensus_raw_success"]
                and float(row["consensus_confidence_score"]) > threshold
            )
            gated.append(
                {
                    **row,
                    "consensus_safety_threshold": threshold,
                    "consensus_safety_accepted": accepted,
                    "consensus_safety_unsafe_auto": bool(
                        accepted and not bool(row["consensus_proven_safe_anchor"])
                    ),
                }
            )
    return gated, thresholds


def _consensus_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_fold: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        accepted = bool(row["consensus_safety_accepted"])
        safe = bool(row["consensus_proven_safe_anchor"])
        values = {
            "example": True,
            "candidate_agreement": bool(row["candidate_agreement"]),
            "raw_consensus_success": bool(row["consensus_raw_success"]),
            "raw_unsafe_consensus_success": bool(
                row["consensus_raw_unsafe_success"]
            ),
            "proven_safe_consensus": safe,
            "safety_accepted": accepted,
            "safety_safe_auto": accepted and safe,
            "safety_unsafe_auto": accepted and not safe,
        }
        candidate_type = str(row["consensus_candidate_type"])
        fold = int(row["fold"])
        for key, value in values.items():
            increment = int(value)
            counts[key] += increment
            per_type[candidate_type][key] += increment
            per_fold[fold][key] += increment
    fold_safe_counts = [
        counter["safety_safe_auto"] for _, counter in sorted(per_fold.items())
    ]
    return {
        "counts": dict(sorted(counts.items())),
        "accepted_coverage": counts["safety_accepted"] / counts["example"],
        "proven_safe_recall": (
            counts["safety_safe_auto"] / counts["proven_safe_consensus"]
            if counts["proven_safe_consensus"]
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
        "all_folds_have_safe_auto": bool(fold_safe_counts)
        and min(fold_safe_counts) > 0,
        "minimum_fold_safe_auto": min(fold_safe_counts, default=0),
    }


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


__all__ = ["run_anchor_oof_consensus_safety"]
