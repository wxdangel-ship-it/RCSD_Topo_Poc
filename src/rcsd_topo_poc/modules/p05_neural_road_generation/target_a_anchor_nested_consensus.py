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


def run_strict_nested_anchor_consensus(
    *,
    nested_oof_roots: Sequence[Path],
    output_root: Path,
    run_id: str,
    required_seed_count: int = 3,
) -> Path:
    """Calibrate each outer fold only from its inner-validation predictions."""
    started = time.perf_counter()
    if len(nested_oof_roots) != required_seed_count:
        raise ValueError(
            f"strict nested consensus requires {required_seed_count} seeds"
        )
    roots = [
        normalize_runtime_path(root).resolve(strict=True)
        for root in nested_oof_roots
    ]
    if len(set(roots)) != len(roots):
        raise ValueError("strict nested consensus roots must be unique")
    destination = normalize_runtime_path(output_root).resolve() / run_id
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)

    summaries = [_read_json(root / "summary.json") for root in roots]
    outer_groups = [
        _read_jsonl(root / "oof_predictions.jsonl") for root in roots
    ]
    calibration_groups = [
        _read_jsonl(root / "inner_calibration_predictions.jsonl")
        for root in roots
    ]
    _validate_inputs(summaries, outer_groups, calibration_groups)
    folds = sorted({int(row["outer_fold"]) for row in outer_groups[0]})
    gated_rows: list[dict[str, Any]] = []
    calibration_audit: list[dict[str, Any]] = []
    thresholds: dict[str, dict[str, float]] = {}
    for outer_fold in folds:
        fold_calibration_groups = [
            [
                row
                for row in rows
                if int(row["outer_fold"]) == outer_fold
            ]
            for rows in calibration_groups
        ]
        calibration_rows = _consensus_rows(fold_calibration_groups)
        fold_thresholds = _thresholds_from_inner_calibration(
            calibration_rows
        )
        thresholds[str(outer_fold)] = fold_thresholds
        for row in calibration_rows:
            calibration_audit.append(
                {
                    **row,
                    "safety_threshold": fold_thresholds.get(
                        str(row["consensus_candidate_type"]),
                        1.0,
                    ),
                }
            )

        fold_outer_groups = [
            [
                row
                for row in rows
                if int(row["outer_fold"]) == outer_fold
            ]
            for rows in outer_groups
        ]
        for row in _consensus_rows(fold_outer_groups):
            candidate_type = str(row["consensus_candidate_type"])
            threshold = fold_thresholds.get(candidate_type, 1.0)
            accepted = bool(
                row["consensus_raw_success"]
                and float(row["consensus_confidence_score"]) > threshold
            )
            gated_rows.append(
                {
                    **row,
                    "strict_nested_safety_threshold": threshold,
                    "strict_nested_safety_accepted": accepted,
                    "strict_nested_safety_unsafe_auto": bool(
                        accepted
                        and not bool(row["consensus_proven_safe_anchor"])
                    ),
                }
            )
    gated_rows.sort(key=lambda row: str(row["sample_id"]))
    calibration_audit.sort(
        key=lambda row: (int(row["outer_fold"]), str(row["sample_id"]))
    )
    _write_jsonl(
        destination / "strict_nested_consensus_oof_predictions.jsonl",
        gated_rows,
    )
    _write_jsonl(
        destination / "strict_nested_inner_calibration_audit.jsonl",
        calibration_audit,
    )
    summary = _summary(gated_rows)
    summary.update(
        {
            "stage": "ANCHOR_STRICT_NESTED_MULTI_SEED_CONSENSUS",
            "run_id": run_id,
            "required_seed_count": required_seed_count,
            "seed_run_ids": [str(item["run_id"]) for item in summaries],
            "source_store_manifest_sha256": summaries[0][
                "source_manifest_sha256"
            ],
            "source_summary_sha256": [
                sha256_file(root / "summary.json") for root in roots
            ],
            "source_outer_prediction_sha256": [
                sha256_file(root / "oof_predictions.jsonl")
                for root in roots
            ],
            "source_inner_calibration_sha256": [
                sha256_file(root / "inner_calibration_predictions.jsonl")
                for root in roots
            ],
            "strict_nested_thresholds": thresholds,
            "threshold_calibration_group": (
                "PER_OUTER_FOLD_INNER_VALIDATION_ONLY"
            ),
            "outer_label_access_during_threshold_selection": 0,
            "consensus_rule": (
                "all seeds predict SUCCESS and the same candidate object; "
                "confidence is the minimum per-seed confidence"
            ),
            "threshold_objective": (
                "maximum inner-validation unsafe consensus confidence by "
                "candidate type; outer fold is evaluation-only"
            ),
            "terminal_feature_count": 0,
            "wall_seconds": time.perf_counter() - started,
        }
    )
    _write_json(destination / "summary.json", summary)
    return destination


def _consensus_rows(
    row_groups: Sequence[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    if len(row_groups) < 2:
        raise ValueError("strict nested consensus requires multiple seeds")
    indexed = [
        {str(row["sample_id"]): row for row in rows}
        for rows in row_groups
    ]
    sample_sets = [set(rows) for rows in indexed]
    if (
        not sample_sets[0]
        or any(values != sample_sets[0] for values in sample_sets[1:])
        or any(len(rows) != len(sample_sets[0]) for rows in row_groups)
    ):
        raise ValueError("strict nested consensus sample coverage differs")
    result: list[dict[str, Any]] = []
    for sample_id in sorted(indexed[0]):
        seed_rows = [rows[sample_id] for rows in indexed]
        _validate_sample(seed_rows)
        reference = seed_rows[0]
        predicted_ids = [
            str(row.get("candidate_predicted_id") or "")
            for row in seed_rows
        ]
        predicted_indices = [
            int(row["candidate_predicted_index"]) for row in seed_rows
        ]
        candidate_agreement = (
            len(set(predicted_ids)) == 1
            and len(set(predicted_indices)) == 1
        )
        all_success = all(
            str(row["predicted"]) == "SUCCESS" for row in seed_rows
        )
        raw_success = candidate_agreement and all_success
        acceptable_ids = {
            str(value)
            for value in reference.get("candidate_acceptable_ids", ())
        }
        agreed_id = predicted_ids[0] if candidate_agreement else ""
        candidate_supervised = bool(reference["candidate_supervised"])
        proven_safe = bool(
            raw_success
            and str(reference["label"]) == "SUCCESS"
            and candidate_supervised
            and agreed_id in acceptable_ids
        )
        candidate_types = {
            str(row["candidate_type"]) for row in seed_rows
        }
        candidate_type = (
            next(iter(candidate_types))
            if candidate_agreement and len(candidate_types) == 1
            else "DISAGREE"
        )
        result.append(
            {
                "sample_id": sample_id,
                "case_key": str(reference["case_key"]),
                "anchor_id": str(reference.get("anchor_id") or ""),
                "fold": int(reference["fold"]),
                "outer_fold": int(reference["outer_fold"]),
                "inner_validation_fold": int(
                    reference["inner_validation_fold"]
                ),
                "label": str(reference["label"]),
                "candidate_supervised": candidate_supervised,
                "candidate_acceptable_ids": sorted(acceptable_ids),
                "candidate_agreement": candidate_agreement,
                "all_status_success": all_success,
                "consensus_raw_success": raw_success,
                "consensus_candidate_index": (
                    predicted_indices[0] if candidate_agreement else -1
                ),
                "consensus_candidate_id": agreed_id,
                "consensus_candidate_type": candidate_type,
                "consensus_confidence_score": min(
                    float(row["candidate_confidence_score"])
                    for row in seed_rows
                ),
                "consensus_proven_safe_anchor": proven_safe,
                "consensus_raw_unsafe_success": bool(
                    raw_success and not proven_safe
                ),
                "seed_predictions": [
                    {
                        "predicted": str(row["predicted"]),
                        "candidate_predicted_index": int(
                            row["candidate_predicted_index"]
                        ),
                        "candidate_predicted_id": str(
                            row.get("candidate_predicted_id") or ""
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
    return result


def _thresholds_from_inner_calibration(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    candidate_types = sorted(
        {
            str(row["consensus_candidate_type"])
            for row in rows
            if str(row["consensus_candidate_type"]) != "DISAGREE"
        }
    )
    thresholds: dict[str, float] = {}
    for candidate_type in candidate_types:
        safe_scores = [
            float(row["consensus_confidence_score"])
            for row in rows
            if str(row["consensus_candidate_type"]) == candidate_type
            and bool(row["consensus_proven_safe_anchor"])
        ]
        unsafe_scores = [
            float(row["consensus_confidence_score"])
            for row in rows
            if str(row["consensus_candidate_type"]) == candidate_type
            and bool(row["consensus_raw_unsafe_success"])
        ]
        thresholds[candidate_type] = (
            max(unsafe_scores, default=-1.0) if safe_scores else 1.0
        )
    return thresholds


def _validate_sample(seed_rows: Sequence[Mapping[str, Any]]) -> None:
    invariant_keys = (
        "sample_id",
        "case_key",
        "anchor_id",
        "fold",
        "outer_fold",
        "inner_validation_fold",
        "label",
        "candidate_supervised",
        "candidate_acceptable_ids",
    )
    reference = seed_rows[0]
    for row in seed_rows[1:]:
        for key in invariant_keys:
            if row.get(key) != reference.get(key):
                raise ValueError(
                    f"strict nested seed truth differs: "
                    f"{reference['sample_id']}:{key}"
                )


def _validate_inputs(
    summaries: Sequence[Mapping[str, Any]],
    outer_groups: Sequence[Sequence[Mapping[str, Any]]],
    calibration_groups: Sequence[Sequence[Mapping[str, Any]]],
) -> None:
    if not summaries:
        raise ValueError("strict nested consensus inputs are empty")
    if {
        str(summary.get("stage")) for summary in summaries
    } != {"ANCHOR_STATUS_STRICT_NESTED_OOF"}:
        raise ValueError("strict nested consensus source stage differs")
    source_hashes = {
        str(summary["source_manifest_sha256"]) for summary in summaries
    }
    if len(source_hashes) != 1:
        raise ValueError("strict nested consensus feature stores differ")
    run_ids = {str(summary["run_id"]) for summary in summaries}
    if len(run_ids) != len(summaries):
        raise ValueError("strict nested consensus run IDs must be unique")
    if not all(bool(summary["oof_coverage_exact"]) for summary in summaries):
        raise ValueError("strict nested source OOF coverage is incomplete")
    if len(outer_groups) != len(summaries) or len(calibration_groups) != len(
        summaries
    ):
        raise ValueError("strict nested consensus source files are incomplete")


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_fold: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        accepted = bool(row["strict_nested_safety_accepted"])
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
        fold = int(row["outer_fold"])
        for key, value in values.items():
            increment = int(value)
            counts[key] += increment
            per_type[candidate_type][key] += increment
            per_fold[fold][key] += increment
    fold_safe_counts = [
        counter["safety_safe_auto"]
        for _, counter in sorted(per_fold.items())
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


__all__ = ["run_strict_nested_anchor_consensus"]
