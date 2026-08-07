from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_anchor_conditioned_plan_gate(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    consensus_root: Path,
    teacher_plan_oof_root: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """Audit which ordinary plans may follow the locked anchor stage."""
    started = time.perf_counter()
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(preflight_root).resolve(strict=True)
    anchor_root = normalize_runtime_path(consensus_root).resolve(strict=True)
    plan_root = normalize_runtime_path(teacher_plan_oof_root).resolve(strict=True)
    destination = normalize_runtime_path(output_root).resolve() / run_id
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)

    groups = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    }
    labels = _read_jsonl(label_root / "training_plan_labels.jsonl")
    anchor_rows = {
        str(row["sample_id"]): row
        for row in _read_jsonl(
            anchor_root / "consensus_gated_oof_predictions.jsonl"
        )
    }
    plan_predictions = {
        str(row["sample_id"]): row
        for row in _read_jsonl(plan_root / "oof_predictions.jsonl")
    }
    rows = _build_segment_gate_rows(
        groups=groups,
        labels=labels,
        anchor_rows=anchor_rows,
        plan_predictions=plan_predictions,
    )
    _write_jsonl(destination / "ordinary_anchor_gate_audit.jsonl", rows)
    summary = _segment_gate_summary(rows)
    summary.update(
        {
            "stage": "ORDINARY_OOF_ANCHOR_CONDITIONING_GATE",
            "run_id": run_id,
            "candidate_store_manifest_sha256": sha256_file(
                candidate_root / "manifest.json"
            ),
            "preflight_summary_sha256": sha256_file(label_root / "summary.json"),
            "anchor_consensus_summary_sha256": sha256_file(
                anchor_root / "summary.json"
            ),
            "teacher_plan_oof_summary_sha256": sha256_file(
                plan_root / "summary.json"
            ),
            "required_anchor_join": (
                "sha256(case_key + ':' + canonical SWSD semantic junction ID)"
            ),
            "teacher_plan_caveat": (
                "Road-plan predictions remain teacher-forcing OOF. This audit "
                "measures the strict chain gate but is not T032 retraining."
            ),
            "terminal_feature_count": 0,
            "wall_seconds": time.perf_counter() - started,
        }
    )
    _write_json(destination / "summary.json", summary)
    return destination


def _build_segment_gate_rows(
    *,
    groups: Mapping[tuple[str, str], Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    anchor_rows: Mapping[str, Mapping[str, Any]],
    plan_predictions: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in labels:
        if (
            not bool(label.get("training_task_mask"))
            or str(label.get("segment_type")) != "STANDARD"
            or not label.get("acceptable_plan_ids")
        ):
            continue
        case_key = str(label["case_key"])
        segment_id = str(label["segment_id"])
        key = (case_key, segment_id)
        group = groups.get(key)
        if group is None:
            raise ValueError(f"ordinary candidate group is missing: {key}")
        plan_sample_id = f"{case_key}:{segment_id}"
        plan_prediction = plan_predictions.get(plan_sample_id)
        if plan_prediction is None:
            raise ValueError(f"ordinary OOF prediction is missing: {plan_sample_id}")
        required_ids = tuple(
            sorted(str(value) for value in group.get("required_anchor_ids", ()))
        )
        required_samples = tuple(
            _t05_anchor_sample_id(case_key, anchor_id)
            for anchor_id in required_ids
        )
        anchors = [anchor_rows.get(sample_id) for sample_id in required_samples]
        anchor_rows_complete = all(row is not None for row in anchors)
        anchor_gate_accepted = bool(
            anchor_rows_complete
            and all(bool(row["consensus_safety_accepted"]) for row in anchors)
        )
        anchor_gate_proven_safe = bool(
            anchor_rows_complete
            and all(
                bool(row["consensus_proven_safe_anchor"]) for row in anchors
            )
        )
        plan_exact = bool(plan_prediction["acceptable_exact"])
        safe_auto = bool(
            anchor_gate_accepted and anchor_gate_proven_safe and plan_exact
        )
        unsafe_auto = bool(anchor_gate_accepted and not safe_auto)
        rows.append(
            {
                "sample_id": plan_sample_id,
                "case_key": case_key,
                "segment_id": segment_id,
                "fold": int(label["fold"]),
                "required_anchor_ids": list(required_ids),
                "required_anchor_sample_ids": list(required_samples),
                "required_anchor_count": len(required_ids),
                "anchor_rows_complete": anchor_rows_complete,
                "anchor_gate_accepted": anchor_gate_accepted,
                "anchor_gate_proven_safe": anchor_gate_proven_safe,
                "teacher_plan_id": str(plan_prediction["predicted_plan_id"]),
                "teacher_plan_decision": str(
                    plan_prediction["predicted_decision"]
                ),
                "teacher_plan_acceptable_exact": plan_exact,
                "chain_safe_auto": safe_auto,
                "chain_unsafe_auto": unsafe_auto,
                "anchor_decisions": [
                    {
                        "anchor_id": anchor_id,
                        "sample_id": sample_id,
                        "present": row is not None,
                        "accepted": bool(
                            row and row["consensus_safety_accepted"]
                        ),
                        "proven_safe": bool(
                            row and row["consensus_proven_safe_anchor"]
                        ),
                        "candidate_index": (
                            int(row["consensus_candidate_index"])
                            if row is not None
                            else -1
                        ),
                    }
                    for anchor_id, sample_id, row in zip(
                        required_ids,
                        required_samples,
                        anchors,
                        strict=True,
                    )
                ],
            }
        )
    return sorted(rows, key=lambda row: (row["case_key"], row["segment_id"]))


def _segment_gate_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("ordinary anchor gate requires eligible Segment rows")
    counts: Counter[str] = Counter()
    per_fold: defaultdict[int, Counter[str]] = defaultdict(Counter)
    per_case: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        values = {
            "eligible_segment": True,
            "zero_required_anchor": int(row["required_anchor_count"]) == 0,
            "anchor_rows_complete": bool(row["anchor_rows_complete"]),
            "anchor_gate_accepted": bool(row["anchor_gate_accepted"]),
            "anchor_gate_proven_safe": bool(row["anchor_gate_proven_safe"]),
            "teacher_plan_exact": bool(row["teacher_plan_acceptable_exact"]),
            "chain_safe_auto": bool(row["chain_safe_auto"]),
            "chain_unsafe_auto": bool(row["chain_unsafe_auto"]),
        }
        for key, value in values.items():
            increment = int(value)
            counts[key] += increment
            per_fold[int(row["fold"])][key] += increment
            per_case[str(row["case_key"])][key] += increment
    fold_gate_counts = [
        value["anchor_gate_accepted"] for _, value in sorted(per_fold.items())
    ]
    return {
        "counts": dict(sorted(counts.items())),
        "anchor_gate_coverage": (
            counts["anchor_gate_accepted"] / counts["eligible_segment"]
        ),
        "chain_safe_auto_coverage": (
            counts["chain_safe_auto"] / counts["eligible_segment"]
        ),
        "safety_gate_pass": counts["chain_unsafe_auto"] == 0,
        "all_folds_have_anchor_gate_accepted": bool(fold_gate_counts)
        and min(fold_gate_counts) > 0,
        "minimum_fold_anchor_gate_accepted": min(fold_gate_counts, default=0),
        "per_fold": {
            str(key): dict(sorted(value.items()))
            for key, value in sorted(per_fold.items())
        },
        "per_case": {
            key: dict(sorted(value.items()))
            for key, value in sorted(per_case.items())
        },
    }


def _t05_anchor_sample_id(case_key: str, anchor_id: str) -> str:
    digest = hashlib.sha256(f"{case_key}:{anchor_id}".encode("utf-8")).hexdigest()
    return f"anchor-t05:{digest[:20]}"


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


__all__ = ["run_anchor_conditioned_plan_gate"]
