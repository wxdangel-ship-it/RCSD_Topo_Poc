from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_no_evidence_proof_gate(
    *,
    anchor_oof_root: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """Require an inner-only zero-false-positive threshold for NO_EVIDENCE."""
    started = time.perf_counter()
    source = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    outer_rows = _read_jsonl(source / "oof_predictions.jsonl")
    inner_rows = _read_jsonl(
        source / "inner_calibration_predictions.jsonl"
    )
    folds = sorted({int(row["outer_fold"]) for row in outer_rows})
    thresholds: dict[int, float] = {}
    calibration: list[dict[str, Any]] = []
    for fold in folds:
        rows = [
            row for row in inner_rows if int(row["outer_fold"]) == fold
        ]
        threshold = select_zero_false_positive_threshold(rows)
        thresholds[fold] = threshold
        calibration.append(
            {
                "outer_fold": fold,
                "threshold": threshold,
                **no_evidence_proof_metrics(rows, threshold),
            }
        )
    gated_rows = [
        apply_no_evidence_proof(
            row,
            threshold=thresholds[int(row["outer_fold"])],
        )
        for row in outer_rows
    ]
    prediction_path = root / "oof_predictions.jsonl"
    calibration_path = root / "inner_calibration_predictions.jsonl"
    _write_jsonl(prediction_path, gated_rows)
    _write_jsonl(calibration_path, inner_rows)
    outer_metrics = no_evidence_proof_metrics_by_fold(
        gated_rows,
        thresholds,
        already_gated=True,
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "NO_EVIDENCE_PROOF_GATE_STRICT_NESTED_OOF",
        "run_id": run_id,
        "source_anchor_oof": str(source),
        "source_summary_sha256": sha256_file(source / "summary.json"),
        "selection_contract": (
            "For each outer fold, use only its inner-validation predictions. "
            "The threshold is immediately above the highest supervised "
            "non-NO_EVIDENCE score among rows predicted NO_EVIDENCE."
        ),
        "unknown_contract": (
            "Unsupervised relation_record_absent rows never influence the "
            "threshold and are reported separately, not as success or failure."
        ),
        "fold_thresholds": {
            str(fold): threshold for fold, threshold in thresholds.items()
        },
        "inner_calibration": calibration,
        "outer_oof": outer_metrics,
        "outputs": {
            "oof_predictions": _file_record(prediction_path),
            "inner_calibration_predictions": _file_record(calibration_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": outer_metrics["false_proof_count"] == 0,
        "decision": (
            "NO_EVIDENCE_PROOF_DIAGNOSTIC_GO"
            if outer_metrics["false_proof_count"] == 0
            else "NO_EVIDENCE_PROOF_DIAGNOSTIC_NO_GO"
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def select_zero_false_positive_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    negatives = [
        _no_evidence_probability(row)
        for row in rows
        if (
            _is_no_evidence_candidate(row)
            and _is_supervised(row)
            and str(row.get("label") or "") != "NO_EVIDENCE"
        )
    ]
    if not negatives:
        return 0.5
    maximum = max(negatives)
    if maximum >= 1.0:
        return 1.0
    return math.nextafter(maximum, math.inf)


def apply_no_evidence_proof(
    row: Mapping[str, Any],
    *,
    threshold: float,
) -> dict[str, Any]:
    result = dict(row)
    candidate = _is_no_evidence_candidate(row)
    probability = _no_evidence_probability(row)
    passed = candidate and probability >= threshold
    result["no_evidence_proof_candidate"] = candidate
    result["no_evidence_proof_probability"] = probability
    result["no_evidence_proof_threshold"] = threshold
    result["no_evidence_proof_passed"] = passed
    result["no_evidence_proof_evaluable"] = _is_supervised(row)
    result["predicted_before_no_evidence_proof"] = str(
        row.get("predicted") or ""
    )
    if candidate and not passed:
        result["predicted"] = "ABSTAIN"
        result["predicted_index"] = 3
        result["status_predicted_index"] = 3
        result["gate_passed"] = False
        result["no_evidence_proof_fallback_reason"] = (
            "NO_EVIDENCE_NOT_PROVEN"
        )
    return result


def no_evidence_proof_metrics_by_fold(
    rows: Sequence[Mapping[str, Any]],
    thresholds: Mapping[int, float],
    *,
    already_gated: bool,
) -> dict[str, Any]:
    evaluated = (
        list(rows)
        if already_gated
        else [
            apply_no_evidence_proof(
                row,
                threshold=thresholds[int(row["outer_fold"])],
            )
            for row in rows
        ]
    )
    overall = no_evidence_proof_metrics(
        evaluated,
        threshold=None,
        already_gated=True,
    )
    overall["per_fold"] = {
        str(fold): no_evidence_proof_metrics(
            [
                row
                for row in evaluated
                if int(row["outer_fold"]) == fold
            ],
            threshold=None,
            already_gated=True,
        )
        for fold in sorted(thresholds)
    }
    return overall


def no_evidence_proof_metrics(
    rows: Sequence[Mapping[str, Any]],
    threshold: float | None,
    *,
    already_gated: bool = False,
) -> dict[str, Any]:
    evaluated = (
        list(rows)
        if already_gated
        else [
            apply_no_evidence_proof(row, threshold=float(threshold))
            for row in rows
        ]
    )
    accepted = [
        row for row in evaluated if bool(row["no_evidence_proof_passed"])
    ]
    supervised = [row for row in accepted if _is_supervised(row)]
    true_proof = [
        row for row in supervised if str(row.get("label")) == "NO_EVIDENCE"
    ]
    false_proof = [
        row for row in supervised if str(row.get("label")) != "NO_EVIDENCE"
    ]
    known_positive_count = sum(
        _is_supervised(row) and str(row.get("label")) == "NO_EVIDENCE"
        for row in evaluated
    )
    return {
        "row_count": len(evaluated),
        "proof_accepted_count": len(accepted),
        "true_proof_count": len(true_proof),
        "false_proof_count": len(false_proof),
        "unknown_proof_count": len(accepted) - len(supervised),
        "known_precision": (
            len(true_proof) / len(supervised) if supervised else 0.0
        ),
        "known_recall": (
            len(true_proof) / known_positive_count
            if known_positive_count
            else 0.0
        ),
    }


def _is_no_evidence_candidate(row: Mapping[str, Any]) -> bool:
    return str(row.get("predicted") or "") == "NO_EVIDENCE"


def _is_supervised(row: Mapping[str, Any]) -> bool:
    return bool(row.get("gate_supervised"))


def _no_evidence_probability(row: Mapping[str, Any]) -> float:
    probabilities = row.get("probabilities") or {}
    return float(probabilities.get("NO_EVIDENCE") or 0.0)


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
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _file_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


__all__ = [
    "apply_no_evidence_proof",
    "no_evidence_proof_metrics",
    "run_no_evidence_proof_gate",
    "select_zero_false_positive_threshold",
]
