from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


class AnchorAdjudicationDecision(str, Enum):
    SUCCESS_UNIQUE = "SUCCESS_UNIQUE"
    PROVEN_NO_EVIDENCE = "PROVEN_NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    CANDIDATE_MISSING = "CANDIDATE_MISSING"


@dataclass(frozen=True)
class AnchorManualAdjudication:
    case_key: str
    anchor_id: str
    decision: AnchorAdjudicationDecision
    selected_candidate_id: str
    evidence_note: str
    affected_segment_ids: tuple[str, ...]
    queue_sample_id: str
    source_row_number: int


CSV_FIELDS = (
    "priority",
    "priority_reason",
    "case_key",
    "anchor_id",
    "current_status",
    "label_reason",
    "candidate_count",
    "candidate_ids",
    "model_status",
    "model_candidate_id",
    "model_joint_score",
    "impact_segment_count",
    "impact_segment_ids",
    "review_auto_segment_ids",
    "unverified_releasable_segment_ids",
    "manual_decision",
    "manual_selected_candidate_id",
    "manual_evidence_note",
)
MANUAL_FIELDS = {
    "manual_decision",
    "manual_selected_candidate_id",
    "manual_evidence_note",
}


def read_anchor_adjudication_csv(
    *,
    csv_path: Path,
    queue_path: Path,
    require_complete: bool = True,
) -> tuple[AnchorManualAdjudication, ...]:
    source = normalize_runtime_path(csv_path).resolve(strict=True)
    queue_source = normalize_runtime_path(queue_path).resolve(strict=True)
    queue_rows = _read_jsonl(queue_source)
    queue_by_key = {
        (str(row["case_key"]), str(row["anchor_id"])): row
        for row in queue_rows
    }
    if len(queue_by_key) != len(queue_rows):
        raise ValueError("Anchor adjudication queue has duplicate Case anchors")

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise ValueError(
                "Anchor adjudication CSV columns differ from the frozen template"
            )
        csv_rows = list(reader)
    csv_by_key: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}
    for row_number, row in enumerate(csv_rows, start=2):
        key = (
            str(row.get("case_key") or "").strip(),
            str(row.get("anchor_id") or "").strip(),
        )
        if not all(key):
            raise ValueError(
                f"Anchor adjudication row {row_number} lacks its Case key"
            )
        if key in csv_by_key:
            raise ValueError(
                f"Anchor adjudication CSV duplicates {key} at row {row_number}"
            )
        csv_by_key[key] = (row_number, row)

    missing = sorted(set(queue_by_key) - set(csv_by_key))
    extra = sorted(set(csv_by_key) - set(queue_by_key))
    if missing or extra:
        raise ValueError(
            "Anchor adjudication CSV scope differs from the frozen queue: "
            f"missing={missing}, extra={extra}"
        )

    result: list[AnchorManualAdjudication] = []
    for queue_row in queue_rows:
        key = (
            str(queue_row["case_key"]),
            str(queue_row["anchor_id"]),
        )
        row_number, csv_row = csv_by_key[key]
        _validate_immutable_fields(
            csv_row,
            queue_row,
            row_number=row_number,
        )
        raw_decision = str(csv_row["manual_decision"] or "").strip().upper()
        selected = str(
            csv_row["manual_selected_candidate_id"] or ""
        ).strip()
        evidence_note = str(
            csv_row["manual_evidence_note"] or ""
        ).strip()
        if not raw_decision:
            if selected or evidence_note:
                raise ValueError(
                    f"Anchor adjudication row {row_number} has manual fields "
                    "without a decision"
                )
            if require_complete:
                raise ValueError(
                    f"Anchor adjudication row {row_number} is incomplete"
                )
            continue
        try:
            decision = AnchorAdjudicationDecision(raw_decision)
        except ValueError as exc:
            raise ValueError(
                f"Anchor adjudication row {row_number} has an invalid decision"
            ) from exc
        if not evidence_note:
            raise ValueError(
                f"Anchor adjudication row {row_number} lacks an evidence note"
            )
        candidates = {
            str(candidate) for candidate in queue_row["candidate_ids"]
        }
        if decision is AnchorAdjudicationDecision.SUCCESS_UNIQUE:
            if not selected:
                raise ValueError(
                    f"SUCCESS_UNIQUE row {row_number} lacks a candidate"
                )
            if selected not in candidates:
                raise ValueError(
                    f"SUCCESS_UNIQUE row {row_number} selects an object "
                    "outside the frozen candidate set"
                )
        elif selected:
            raise ValueError(
                f"{decision.value} row {row_number} must not select a candidate"
            )
        result.append(
            AnchorManualAdjudication(
                case_key=key[0],
                anchor_id=key[1],
                decision=decision,
                selected_candidate_id=selected,
                evidence_note=evidence_note,
                affected_segment_ids=tuple(
                    str(value)
                    for value in queue_row["impact_segment_ids"]
                ),
                queue_sample_id=str(queue_row["sample_id"]),
                source_row_number=row_number,
            )
        )
    return tuple(result)


def apply_anchor_adjudication_labels(
    examples: Sequence[AnchorPretrainExample],
    *,
    adjudications: Sequence[AnchorManualAdjudication],
) -> tuple[list[AnchorPretrainExample], Counter[str]]:
    by_key = {(row.case_key, row.anchor_id): row for row in examples}
    if len(by_key) != len(examples):
        raise ValueError("Anchor label store has duplicate Case anchors")
    adjudication_by_key = {
        (row.case_key, row.anchor_id): row for row in adjudications
    }
    if len(adjudication_by_key) != len(adjudications):
        raise ValueError("Manual anchor adjudications contain duplicate keys")
    missing = sorted(set(adjudication_by_key) - set(by_key))
    if missing:
        raise ValueError(
            f"Manual anchor adjudications are outside the label store: {missing}"
        )

    counts: Counter[str] = Counter()
    transformed: list[AnchorPretrainExample] = []
    for source in examples:
        key = (source.case_key, source.anchor_id)
        adjudication = adjudication_by_key.get(key)
        if adjudication is None:
            transformed.append(source)
            continue
        if source.sample_id != adjudication.queue_sample_id:
            raise ValueError(
                f"Manual anchor adjudication uses a stale sample ID: {key}"
            )
        if source.status_supervised or source.candidate_supervised:
            raise ValueError(
                "Manual Phase 1 adjudication must not overwrite existing "
                f"anchor truth: {key}"
            )
        selected_indices = tuple(
            index
            for index, candidate_id in enumerate(source.candidate_ids)
            if candidate_id == adjudication.selected_candidate_id
        )
        if (
            adjudication.decision
            is AnchorAdjudicationDecision.SUCCESS_UNIQUE
            and len(selected_indices) != 1
        ):
            raise ValueError(
                f"Manual anchor selection is no longer uniquely reachable: {key}"
            )
        status, gate_label, reason = _decision_label(adjudication.decision)
        candidate_supervised = bool(selected_indices)
        result = replace(
            source,
            status_label=ANCHOR_STATUS_INDEX[status],
            status_supervised=True,
            gate_label=gate_label,
            gate_supervised=True,
            candidate_acceptable_indices=selected_indices,
            preferred_candidate_index=(
                selected_indices[0] if selected_indices else -1
            ),
            candidate_supervised=candidate_supervised,
            sample_weight=1.0,
            label_reason=reason,
        )
        transformed.append(result)
        counts["adjudicated_anchor"] += 1
        counts[f"decision:{adjudication.decision.value}"] += 1
        counts["candidate_supervised"] += int(candidate_supervised)
        counts["positive_gate"] += int(gate_label == 1)
        counts["segment_fallback_gate"] += int(gate_label == 0)
    counts["example"] = len(transformed)
    return transformed, counts


def write_anchor_adjudication_overlay(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
    queue_path: Path,
    adjudication_csv_path: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_label_policy import (
        apply_anchor_supervision_policy,
        apply_plan_supervision_policy,
    )

    source_anchor = normalize_runtime_path(anchor_store_root).resolve(
        strict=True
    )
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    source_plan = normalize_runtime_path(plan_label_root).resolve(strict=True)
    queue_source = normalize_runtime_path(queue_path).resolve(strict=True)
    csv_source = normalize_runtime_path(adjudication_csv_path).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    adjudications = read_anchor_adjudication_csv(
        csv_path=csv_source,
        queue_path=queue_source,
        require_complete=True,
    )
    examples = read_anchor_pretraining_stores(source_anchor)
    manually_labeled, manual_counts = apply_anchor_adjudication_labels(
        examples,
        adjudications=adjudications,
    )
    transformed, policy_counts = apply_anchor_supervision_policy(
        manually_labeled
    )
    anchor_output = write_anchor_pretraining_stores(
        transformed,
        output_root=root,
        run_id="anchor_store",
    )
    source_feature = (
        source_anchor / "inference_feature_store" / "anchor_features.jsonl"
    )
    output_feature = (
        anchor_output / "inference_feature_store" / "anchor_features.jsonl"
    )
    feature_store_byte_identical = (
        sha256_file(source_feature) == sha256_file(output_feature)
    )
    if not feature_store_byte_identical:
        raise RuntimeError(
            "Manual anchor adjudication changed inference-time features"
        )

    groups = _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    _validate_affected_segments(adjudications, groups)
    plan_rows = _read_jsonl(source_plan / "training_plan_labels.jsonl")
    no_evidence_segments = {
        (row.case_key, segment_id)
        for row in adjudications
        if row.decision is AnchorAdjudicationDecision.PROVEN_NO_EVIDENCE
        for segment_id in row.affected_segment_ids
    }
    transformed_plans, plan_counts = apply_plan_supervision_policy(
        plan_rows,
        groups=groups,
        anchor_examples=transformed,
        confirmed_no_evidence_segment_keys=no_evidence_segments,
    )
    plan_output = root / "plan_label_store"
    plan_output.mkdir()
    plan_path = plan_output / "training_plan_labels.jsonl"
    _write_jsonl(plan_path, transformed_plans)
    decision_counts = Counter(row.decision.value for row in adjudications)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_MANUAL_ADJUDICATION_LABEL_OVERLAY",
        "label_only": True,
        "inference_input_allowed": False,
        "feature_rows_recomputed": 0,
        "feature_store_byte_identical": feature_store_byte_identical,
        "adjudication_count": len(adjudications),
        "decision_counts": dict(sorted(decision_counts.items())),
        "manual_label_counts": dict(sorted(manual_counts.items())),
        "anchor_policy_counts": dict(sorted(policy_counts.items())),
        "plan_counts": dict(sorted(plan_counts.items())),
        "inputs": {
            "anchor_manifest": _record(source_anchor / "manifest.json"),
            "candidate_manifest": _record(candidate_root / "manifest.json"),
            "plan_labels": _record(
                source_plan / "training_plan_labels.jsonl"
            ),
            "queue": _record(queue_source),
            "adjudication_csv": _record(csv_source),
        },
        "outputs": {
            "anchor_manifest": _record(anchor_output / "manifest.json"),
            "plan_labels": _record(plan_path),
        },
        "gate_pass": (
            len(adjudications) > 0
            and manual_counts["adjudicated_anchor"] == len(adjudications)
            and feature_store_byte_identical
            and plan_counts["failed_segment_scope_violation"] == 0
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("Manual anchor adjudication overlay gate failed")
    return root


def _validate_immutable_fields(
    csv_row: Mapping[str, str],
    queue_row: Mapping[str, Any],
    *,
    row_number: int,
) -> None:
    for field in CSV_FIELDS:
        if field in MANUAL_FIELDS:
            continue
        expected = _queue_csv_value(queue_row, field)
        actual = str(csv_row.get(field) or "")
        if actual != expected:
            raise ValueError(
                f"Anchor adjudication row {row_number} changed frozen field "
                f"{field}"
            )


def _queue_csv_value(row: Mapping[str, Any], field: str) -> str:
    value = row[field]
    if field in {
        "candidate_ids",
        "impact_segment_ids",
        "review_auto_segment_ids",
        "unverified_releasable_segment_ids",
    }:
        return "|".join(str(item) for item in value)
    return str(value)


def _decision_label(
    decision: AnchorAdjudicationDecision,
) -> tuple[AnchorStatus, int, str]:
    if decision is AnchorAdjudicationDecision.SUCCESS_UNIQUE:
        return (
            AnchorStatus.SUCCESS,
            1,
            "user_phase1_anchor:success_unique:object_reachable",
        )
    if decision is AnchorAdjudicationDecision.PROVEN_NO_EVIDENCE:
        return (
            AnchorStatus.NO_EVIDENCE,
            1,
            "user_confirmed:no_rcsd_evidence:positive_keep_swsd_clue_false",
        )
    if decision is AnchorAdjudicationDecision.AMBIGUOUS:
        return (
            AnchorStatus.AMBIGUOUS,
            0,
            "user_phase1_anchor:ambiguous:segment_fallback",
        )
    return (
        AnchorStatus.ABSTAIN,
        0,
        "user_phase1_anchor:candidate_missing:segment_fallback",
    )


def _validate_affected_segments(
    adjudications: Sequence[AnchorManualAdjudication],
    groups: Sequence[Mapping[str, Any]],
) -> None:
    actual: dict[tuple[str, str], set[str]] = {}
    for group in groups:
        case_key = str(group["case_key"])
        segment_id = str(group["segment_id"])
        for anchor_id in group.get("required_anchor_ids") or ():
            actual.setdefault((case_key, str(anchor_id)), set()).add(
                segment_id
            )
    for adjudication in adjudications:
        key = (adjudication.case_key, adjudication.anchor_id)
        expected = set(adjudication.affected_segment_ids)
        if actual.get(key, set()) != expected:
            raise ValueError(
                "Manual anchor adjudication uses a stale affected-Segment "
                f"scope: {key}"
            )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


__all__ = [
    "AnchorAdjudicationDecision",
    "AnchorManualAdjudication",
    "apply_anchor_adjudication_labels",
    "read_anchor_adjudication_csv",
    "write_anchor_adjudication_overlay",
]
