from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)

_KEEP_REASONS = frozenset(
    {
        "NO_RCSD_EVIDENCE",
        "ANCHOR_UNRESOLVED",
        "POSITIVE_BUSINESS_KEEP",
        "REALITY_CHANGE_CONFLICT",
        "OTHER_EXPLAINED",
    }
)
_FALLBACK_SCOPES = frozenset({"NONE", "SEGMENT", "JUNCTION"})


def build_clue_scope_adjudication_bundle(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    ordinary_oof_root: Path,
    safety_run_roots: Sequence[Path],
    output_root: Path,
    run_id: str,
    controls_per_case_decision: int = 3,
    phase1_control_backfill_sample_ids: Sequence[str] = (),
) -> Path:
    """Prepare a label-only review queue without inferring any adjudication."""
    if controls_per_case_decision < 0:
        raise ValueError("control sample count must not be negative")
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    preflight = normalize_runtime_path(preflight_root).resolve(strict=True)
    ordinary_root = normalize_runtime_path(ordinary_oof_root).resolve(
        strict=True
    )
    safety_roots = [
        normalize_runtime_path(path).resolve(strict=True)
        for path in safety_run_roots
    ]
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    group_path = candidate_root / "inference_plan_groups.jsonl"
    label_path = preflight / "training_plan_labels.jsonl"
    prediction_path = ordinary_root / "oof_predictions.jsonl"
    groups = {
        _sample_id(row): row for row in _read_jsonl(group_path)
    }
    labels = {
        _sample_id(row): row for row in _read_jsonl(label_path)
    }
    predictions = {
        str(row["sample_id"]): row
        for row in _read_jsonl(prediction_path)
    }
    safety_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    safety_input_records = []
    for safety_root in safety_roots:
        safety_path = safety_root / "safety_predictions.jsonl"
        safety_input_records.append(
            {
                "run": safety_root.name,
                "path": str(safety_path.resolve()),
                "sha256": sha256_file(safety_path),
            }
        )
        for row in _read_jsonl(safety_path):
            safety_by_sample[str(row["sample_id"])].append(
                {
                    "run": safety_root.name,
                    "applied": bool(row.get("use_safety_applied")),
                    "accepted": bool(row.get("use_safety_accepted")),
                    "unsafe_auto": bool(row.get("use_safety_unsafe_auto")),
                    "score": row.get("use_safety_score"),
                    "threshold": row.get("use_safety_threshold"),
                }
            )

    related_segments = _related_segments_by_anchor(groups.values())
    reviewable_ids = {
        sample_id
        for sample_id, label in labels.items()
        if bool(label.get("training_task_mask"))
        and float(label.get("label_weight") or 0.0) > 0.0
    }
    requested_backfill_ids = tuple(
        sorted(
            {
                str(sample_id)
                for sample_id in phase1_control_backfill_sample_ids
            }
        )
    )
    selected_ids, priority_by_id = _select_queue_ids(
        predictions,
        safety_by_sample,
        controls_per_case_decision=controls_per_case_decision,
        allowed_sample_ids=reviewable_ids,
        backfill_control_sample_ids=requested_backfill_ids,
    )
    locked_ids = {
        sample_id
        for sample_id, label in labels.items()
        if str(label.get("label_origin")) == "user_manual_adjudication"
    }
    queue_ids = selected_ids - locked_ids
    queue = [
        _adjudication_row(
            sample_id,
            priority=priority_by_id[sample_id],
            group=groups[sample_id],
            label=labels[sample_id],
            prediction=predictions[sample_id],
            safety_rows=safety_by_sample.get(sample_id, ()),
            related_segments=related_segments,
        )
        for sample_id in sorted(queue_ids)
    ]
    references = [
        _locked_reference_row(
            sample_id,
            group=groups[sample_id],
            label=labels[sample_id],
            prediction=predictions.get(sample_id),
            related_segments=related_segments,
        )
        for sample_id in sorted(locked_ids & groups.keys())
    ]
    queue_path = root / "adjudication_queue.jsonl"
    reference_path = root / "locked_manual_references.jsonl"
    phase1 = [
        row
        for row in queue
        if row["priority"]
        in {"P0_SAFETY_UNSAFE", "P2_MATCHED_CORRECT_CONTROL"}
    ]
    remaining = [
        row
        for row in queue
        if row["priority"]
        not in {"P0_SAFETY_UNSAFE", "P2_MATCHED_CORRECT_CONTROL"}
    ]
    phase1_carrier = [
        row for row in phase1 if "CARRIER_PLAN" in row["review_tasks"]
    ]
    phase1_clue_scope = [
        row
        for row in phase1
        if "KEEP_REASON_CLUE_SCOPE" in row["review_tasks"]
    ]
    phase1_path = root / "phase1_adjudication_queue.jsonl"
    phase1_carrier_path = root / "phase1_carrier_plan_review.jsonl"
    phase1_clue_scope_path = (
        root / "phase1_keep_reason_clue_scope_review.jsonl"
    )
    remaining_path = root / "remaining_adjudication_queue.jsonl"
    _write_jsonl(queue_path, queue)
    _write_jsonl(reference_path, references)
    _write_jsonl(phase1_path, phase1)
    _write_jsonl(phase1_carrier_path, phase1_carrier)
    _write_jsonl(phase1_clue_scope_path, phase1_clue_scope)
    _write_jsonl(remaining_path, remaining)

    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "CLUE_SCOPE_ADJUDICATION_PREPARATION",
        "label_only": True,
        "inference_input_allowed": False,
        "automatic_adjudication_count": 0,
        "t06_t11_automatic_mapping_count": 0,
        "contract": (
            "The bundle only prioritizes existing Case objects and presents "
            "evidence. Every non-locked adjudication remains UNKNOWN/PENDING. "
            "Only supervised label-scope objects may enter review. T06/T11 "
            "may be consulted by a reviewer but are not mapped into labels "
            "by this builder."
        ),
        "phase1_control_backfill_sample_ids": list(
            requested_backfill_ids
        ),
        "allowed_review_values": {
            "carrier_verdict": [
                "EXISTING_ACCEPTABLE",
                "EXISTING_WRONG",
                "MULTIPLE_ACCEPTABLE",
                "UNKNOWN",
            ],
            "keep_reason": [
                "NO_RCSD_EVIDENCE",
                "ANCHOR_UNRESOLVED",
                "POSITIVE_BUSINESS_KEEP",
                "REALITY_CHANGE_CONFLICT",
                "OTHER_EXPLAINED",
                "UNKNOWN",
            ],
            "fallback_scope": [
                "NONE",
                "SEGMENT",
                "JUNCTION",
                "UNKNOWN",
            ],
            "review_status": ["PENDING", "CONFIRMED"],
        },
        "counts": {
            "candidate_group_count": len(groups),
            "plan_label_count": len(labels),
            "ordinary_prediction_count": len(predictions),
            "reviewable_label_count": len(reviewable_ids),
            "excluded_context_prediction_count": len(
                set(predictions) - reviewable_ids
            ),
            "queue_count": len(queue),
            "locked_manual_reference_count": len(references),
            "by_priority": dict(
                sorted(Counter(row["priority"] for row in queue).items())
            ),
            "by_case": dict(
                sorted(Counter(row["case_key"] for row in queue).items())
            ),
            "by_existing_label_origin": dict(
                sorted(
                    Counter(
                        row["existing_label"]["label_origin"]
                        for row in queue
                    ).items()
                )
            ),
            "all_queue_rows_pending": sum(
                row["adjudication"]["review_status"] == "PENDING"
                for row in queue
            ),
            "all_queue_clues_unknown": sum(
                row["adjudication"]["reality_change_clue"] is None
                for row in queue
            ),
            "all_queue_scopes_unknown": sum(
                row["adjudication"]["fallback_scope"] == "UNKNOWN"
                for row in queue
            ),
            "by_review_task": dict(
                sorted(
                    Counter(
                        task
                        for row in queue
                        for task in row["review_tasks"]
                    ).items()
                )
            ),
            "phase1_queue_count": len(phase1),
            "phase1_carrier_plan_count": len(phase1_carrier),
            "phase1_keep_reason_clue_scope_count": len(
                phase1_clue_scope
            ),
            "phase1_control_backfill_requested_count": len(
                requested_backfill_ids
            ),
            "phase1_control_backfill_selected_count": sum(
                priority_by_id.get(sample_id)
                == "P2_MATCHED_CORRECT_CONTROL"
                for sample_id in requested_backfill_ids
            ),
            "remaining_queue_count": len(remaining),
        },
        "inputs": {
            "candidate_groups": _input_record(group_path),
            "plan_labels": _input_record(label_path),
            "ordinary_predictions": _input_record(prediction_path),
            "safety_predictions": safety_input_records,
        },
        "outputs": {
            "queue": _input_record(queue_path),
            "locked_manual_references": _input_record(reference_path),
            "phase1_queue": _input_record(phase1_path),
            "phase1_carrier_plan_review": _input_record(
                phase1_carrier_path
            ),
            "phase1_keep_reason_clue_scope_review": _input_record(
                phase1_clue_scope_path
            ),
            "remaining_queue": _input_record(remaining_path),
        },
    }
    _write_json(root / "summary.json", summary)
    return root


def _select_queue_ids(
    predictions: Mapping[str, Mapping[str, Any]],
    safety_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    controls_per_case_decision: int,
    allowed_sample_ids: set[str] | None = None,
    backfill_control_sample_ids: Sequence[str] = (),
) -> tuple[set[str], dict[str, str]]:
    allowed = (
        set(predictions)
        if allowed_sample_ids is None
        else set(allowed_sample_ids)
    )
    priority: dict[str, str] = {}
    for sample_id, rows in safety_by_sample.items():
        if (
            sample_id in allowed
            and any(bool(row.get("unsafe_auto")) for row in rows)
        ):
            priority[sample_id] = "P0_SAFETY_UNSAFE"
    for sample_id, row in predictions.items():
        if sample_id not in allowed or sample_id in priority:
            continue
        if bool(row.get("anchor_gate_fallback_required")):
            priority[sample_id] = "P1_ANCHOR_FALLBACK"
        elif (
            bool(row.get("automatic_decision"))
            and row.get("acceptable_exact") is not True
        ):
            priority[sample_id] = "P1_CARRIER_ERROR"

    correct_by_group: dict[
        tuple[str, str],
        list[tuple[str, Mapping[str, Any]]],
    ] = defaultdict(list)
    for sample_id, row in predictions.items():
        if (
            sample_id in allowed
            and sample_id not in priority
            and bool(row.get("automatic_decision"))
            and row.get("acceptable_exact") is True
        ):
            correct_by_group[
                (str(row["case_key"]), str(row["preferred_decision"]))
            ].append((sample_id, row))
    for rows in correct_by_group.values():
        ranked = sorted(
            rows,
            key=lambda item: hashlib.sha256(
                item[0].encode("utf-8")
            ).hexdigest(),
        )
        for sample_id, _ in ranked[:controls_per_case_decision]:
            priority[sample_id] = "P2_MATCHED_CORRECT_CONTROL"
    for sample_id in backfill_control_sample_ids:
        row = predictions.get(sample_id)
        if row is None:
            raise ValueError(
                f"Phase1 control backfill prediction is missing: {sample_id}"
            )
        if sample_id not in allowed:
            raise ValueError(
                f"Phase1 control backfill is outside label scope: {sample_id}"
            )
        existing_priority = priority.get(sample_id)
        if existing_priority in {
            "P0_SAFETY_UNSAFE",
            "P1_ANCHOR_FALLBACK",
            "P1_CARRIER_ERROR",
        }:
            raise ValueError(
                "Phase1 control backfill is not a matched control: "
                f"{sample_id}: {existing_priority}"
            )
        if not bool(row.get("automatic_decision")) or (
            row.get("acceptable_exact") is not True
        ):
            raise ValueError(
                "Phase1 control backfill must be an exact automatic result: "
                f"{sample_id}"
            )
        priority[sample_id] = "P2_MATCHED_CORRECT_CONTROL"
    return set(priority), priority


def _adjudication_row(
    sample_id: str,
    *,
    priority: str,
    group: Mapping[str, Any],
    label: Mapping[str, Any],
    prediction: Mapping[str, Any],
    safety_rows: Sequence[Mapping[str, Any]],
    related_segments: Mapping[tuple[str, str], tuple[str, ...]],
) -> dict[str, Any]:
    candidates = {
        str(row["plan_id"]): {
            "decision": str(row["decision"]),
            "road_ids": [str(value) for value in row.get("road_ids") or ()],
            "road_roles": list(row.get("road_roles") or ()),
            "generator": str(row.get("generator") or ""),
            "hard_valid": bool(row.get("hard_valid", True)),
        }
        for row in group["candidates"]
    }
    anchor_context = [
        {
            "anchor_id": str(anchor_id),
            "direct_related_segment_ids": list(
                related_segments.get(
                    (str(group["case_key"]), str(anchor_id)),
                    (),
                )
            ),
        }
        for anchor_id in group.get("required_anchor_ids") or ()
    ]
    return {
        "sample_id": sample_id,
        "priority": priority,
        "review_tasks": _review_tasks(label, prediction),
        "case_key": str(group["case_key"]),
        "segment_id": str(group["segment_id"]),
        "segment_type": str(group["segment_type"]),
        "required_anchor_context": anchor_context,
        "existing_label": {
            "label_origin": str(label.get("label_origin") or ""),
            "label_weight": float(label.get("label_weight") or 0.0),
            "preferred_carrier_target": str(
                label.get("preferred_carrier_target") or ""
            ),
            "preferred_plan": candidates.get(
                str(label.get("preferred_plan_id") or "")
            ),
            "acceptable_plans": [
                candidates[plan_id]
                for plan_id in label.get("acceptable_plan_ids") or ()
                if plan_id in candidates
            ],
            "clue_task_mask": bool(label.get("clue_task_mask")),
            "fallback_scope_task_mask": bool(
                label.get("fallback_scope_task_mask")
            ),
        },
        "model_evidence": {
            "v45_effective_decision": str(
                prediction["effective_decision"]
            ),
            "v45_predicted_probability": float(
                prediction["raw_predicted_probability"]
            ),
            "v45_predicted_plan": candidates.get(
                str(prediction["raw_predicted_plan_id"])
            ),
            "v45_acceptable_exact": prediction.get("acceptable_exact"),
            "anchor_gate_fallback_required": bool(
                prediction["anchor_gate_fallback_required"]
            ),
            "safety_runs": list(safety_rows),
        },
        "adjudication": {
            "carrier_verdict": "UNKNOWN",
            "acceptable_road_plans": [],
            "preferred_road_plan": None,
            "keep_reason": "UNKNOWN",
            "reality_change_clue": None,
            "fallback_scope": "UNKNOWN",
            "affected_segment_ids": [],
            "review_status": "PENDING",
            "review_note": "",
        },
    }


def _review_tasks(
    label: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> list[str]:
    tasks = ["CARRIER_PLAN"]
    if str(label.get("preferred_carrier_target")) == "KEEP_SWSD":
        tasks.append("KEEP_REASON_CLUE_SCOPE")
    if bool(prediction.get("anchor_gate_fallback_required")):
        tasks.append("ANCHOR_RESULT")
    return tasks


def _locked_reference_row(
    sample_id: str,
    *,
    group: Mapping[str, Any],
    label: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    related_segments: Mapping[tuple[str, str], tuple[str, ...]],
) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "case_key": str(group["case_key"]),
        "segment_id": str(group["segment_id"]),
        "label_origin": "user_manual_adjudication",
        "preferred_carrier_target": label.get("preferred_carrier_target"),
        "reality_change_clue": label.get("reality_change_clue"),
        "fallback_scope": label.get("fallback_scope"),
        "required_anchor_context": [
            {
                "anchor_id": str(anchor_id),
                "direct_related_segment_ids": list(
                    related_segments.get(
                        (str(group["case_key"]), str(anchor_id)),
                        (),
                    )
                ),
            }
            for anchor_id in group.get("required_anchor_ids") or ()
        ],
        "v45_effective_decision": (
            prediction.get("effective_decision") if prediction else None
        ),
    }


def _related_segments_by_anchor(
    groups: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[str, ...]]:
    values: dict[tuple[str, str], set[str]] = defaultdict(set)
    for group in groups:
        if str(group.get("segment_type")) != "STANDARD":
            continue
        for anchor_id in group.get("required_anchor_ids") or ():
            values[(str(group["case_key"]), str(anchor_id))].add(
                str(group["segment_id"])
            )
    return {
        key: tuple(sorted(segment_ids))
        for key, segment_ids in values.items()
    }


def _sample_id(row: Mapping[str, Any]) -> str:
    return f"{row['case_key']}:{row['segment_id']}"


def compile_clue_scope_adjudications(
    *,
    preflight_root: Path,
    adjudication_path: Path,
    output_root: Path,
    run_id: str,
    manual_label_weight: float = 1.0,
) -> Path:
    """Compile confirmed label-only reviews into a separate training overlay."""
    if manual_label_weight <= 0:
        raise ValueError("manual label weight must be positive")
    preflight = normalize_runtime_path(preflight_root).resolve(strict=True)
    review_path = normalize_runtime_path(adjudication_path).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    labels = _read_jsonl(preflight / "training_plan_labels.jsonl")
    label_by_id = {_sample_id(row): row for row in labels}
    reviews = _read_jsonl(review_path)
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for review in reviews:
        sample_id = str(review.get("sample_id") or "")
        if not sample_id or sample_id in seen:
            raise ValueError(
                f"adjudication sample id is empty or duplicated: {sample_id}"
            )
        seen.add(sample_id)
        label = label_by_id.get(sample_id)
        if label is None:
            raise ValueError(
                f"adjudication sample is outside preflight scope: {sample_id}"
            )
        if not bool(label.get("training_task_mask")):
            raise ValueError(
                f"adjudication sample is outside training scope: {sample_id}"
            )
        payload = review.get("adjudication")
        if not isinstance(payload, Mapping):
            raise ValueError(f"adjudication payload is missing: {sample_id}")
        if str(payload.get("review_status")) != "CONFIRMED":
            raise ValueError(f"adjudication is not confirmed: {sample_id}")
        verdict = str(payload.get("carrier_verdict") or "")
        if verdict != "EXISTING_ACCEPTABLE":
            raise ValueError(
                "Phase1 compiler only accepts confirmed existing plans; "
                f"{sample_id} has {verdict}"
            )
        existing = review.get("existing_label")
        if not isinstance(existing, Mapping):
            raise ValueError(f"existing label evidence is missing: {sample_id}")
        decision = str(existing.get("preferred_carrier_target") or "")
        if decision != str(label.get("preferred_carrier_target") or ""):
            raise ValueError(
                f"adjudication decision differs from preflight: {sample_id}"
            )

        source_origin = str(label.get("label_origin") or "")
        label["source_label_origin"] = source_origin
        label["label_origin"] = "phase1_manual_adjudication"
        label["label_weight"] = max(
            float(label.get("label_weight") or 0.0),
            manual_label_weight,
        )
        label["manual_adjudication_task_mask"] = True
        label["manual_adjudication_sample_id"] = sample_id
        label["manual_carrier_verdict"] = verdict
        label["manual_review_note"] = str(payload.get("review_note") or "")
        label["manual_review_source"] = str(review_path)
        label["keep_reason"] = "UNKNOWN"
        label["keep_reason_task_mask"] = False
        label["carrier_task_mask"] = True
        if decision == "KEEP_SWSD":
            reason = str(payload.get("keep_reason") or "")
            scope = str(payload.get("fallback_scope") or "")
            clue = payload.get("reality_change_clue")
            if reason not in _KEEP_REASONS:
                raise ValueError(
                    f"confirmed KEEP reason is invalid: {sample_id} {reason}"
                )
            if scope not in _FALLBACK_SCOPES:
                raise ValueError(
                    f"confirmed fallback scope is invalid: {sample_id} {scope}"
                )
            if not isinstance(clue, bool):
                raise ValueError(
                    f"confirmed clue must be boolean: {sample_id}"
                )
            if reason == "ANCHOR_UNRESOLVED" and scope != "SEGMENT":
                raise ValueError(
                    "unresolved Segment anchor must use Segment fallback: "
                    f"{sample_id}"
                )
            if reason == "NO_RCSD_EVIDENCE" and (clue or scope != "NONE"):
                raise ValueError(
                    "missing RCSD evidence must be positive KEEP without clue "
                    f"or fallback: {sample_id}"
                )
            label["keep_reason"] = reason
            label["keep_reason_task_mask"] = True
            label["reality_change_clue"] = clue
            label["clue_task_mask"] = True
            label["fallback_scope"] = scope
            label["fallback_scope_task_mask"] = True
            label["carrier_task_mask"] = reason != "ANCHOR_UNRESOLVED"
            counts[f"keep_reason:{reason}"] += 1
            counts[f"fallback_scope:{scope}"] += 1
            counts[f"clue:{str(clue).lower()}"] += 1
        counts[f"decision:{decision}"] += 1
        counts[f"carrier_task_mask:{str(label['carrier_task_mask']).lower()}"] += 1
        counts[f"source_label_origin:{source_origin}"] += 1
        counts["compiled"] += 1

    output_path = root / "training_plan_labels.jsonl"
    _write_jsonl(output_path, labels)
    source_summary_path = preflight / "summary.json"
    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "MANUAL_ADJUDICATION_LABEL_OVERLAY",
        "label_only": True,
        "inference_input_allowed": False,
        "terminal_feature_count": 0,
        "automatic_adjudication_count": 0,
        "manual_adjudication_count": len(reviews),
        "manual_label_weight": manual_label_weight,
        "counts": dict(sorted(counts.items())),
        "inputs": {
            "preflight_summary": _input_record(source_summary_path),
            "preflight_labels": _input_record(
                preflight / "training_plan_labels.jsonl"
            ),
            "adjudications": _input_record(review_path),
        },
        "output": _input_record(output_path),
        "source_preflight_stage": source_summary.get("stage"),
        "gate_pass": (
            bool(reviews)
            and counts["compiled"] == len(reviews)
            and counts["carrier_task_mask:false"]
            == counts["keep_reason:ANCHOR_UNRESOLVED"]
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise ValueError("manual adjudication overlay gate failed")
    return root


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
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


__all__ = [
    "build_clue_scope_adjudication_bundle",
    "compile_clue_scope_adjudications",
]
