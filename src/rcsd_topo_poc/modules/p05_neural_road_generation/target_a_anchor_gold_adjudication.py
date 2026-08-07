from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


QUEUE_SCHEMA_VERSION = "target_a_anchor_gold_phase1_v1"
LIST_SEPARATOR = ";"


class AnchorGoldDecision(str, Enum):
    SUCCESS_CONFIRMED = "SUCCESS_CONFIRMED"
    PROVEN_NO_EVIDENCE = "PROVEN_NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    CANDIDATE_MISSING = "CANDIDATE_MISSING"


@dataclass(frozen=True)
class AnchorGoldAdjudication:
    case_key: str
    anchor_id: str
    decision: AnchorGoldDecision
    acceptable_candidate_ids: tuple[str, ...]
    preferred_candidate_id: str
    evidence_note: str
    affected_segment_ids: tuple[str, ...]
    queue_sample_id: str
    source_row_number: int


CSV_FIELDS = (
    "priority",
    "case_key",
    "fold",
    "anchor_id",
    "sample_id",
    "candidate_count",
    "candidate_ids_json",
    "impact_segment_count",
    "impact_segment_ids",
    "queue_row_sha256",
    "manual_decision",
    "manual_acceptable_candidate_ids",
    "manual_preferred_candidate_id",
    "manual_evidence_note",
)
MANUAL_FIELDS = {
    "manual_decision",
    "manual_acceptable_candidate_ids",
    "manual_preferred_candidate_id",
    "manual_evidence_note",
}
HASH_FIELDS = (
    "queue_schema_version",
    "case_key",
    "fold",
    "anchor_id",
    "sample_id",
    "candidate_ids",
    "impact_segment_ids",
)


def queue_row_sha256(row: Mapping[str, Any]) -> str:
    payload = {field: row[field] for field in HASH_FIELDS}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_anchor_gold_csv(
    *,
    csv_path: Path,
    queue_path: Path,
    require_complete: bool = True,
) -> tuple[AnchorGoldAdjudication, ...]:
    source = normalize_runtime_path(csv_path).resolve(strict=True)
    queue_source = normalize_runtime_path(queue_path).resolve(strict=True)
    queue_rows = _read_jsonl(queue_source)
    queue_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in queue_rows:
        if str(row.get("queue_schema_version")) != QUEUE_SCHEMA_VERSION:
            raise ValueError("Anchor Gold queue schema differs from the frozen contract")
        expected_hash = queue_row_sha256(row)
        if str(row.get("queue_row_sha256")) != expected_hash:
            raise ValueError("Anchor Gold queue row hash is invalid")
        key = (str(row["case_key"]), str(row["anchor_id"]))
        if key in queue_by_key:
            raise ValueError("Anchor Gold queue has duplicate Case anchors")
        queue_by_key[key] = row

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise ValueError("Anchor Gold CSV columns differ from the frozen template")
        csv_rows = list(reader)
    csv_by_key: dict[tuple[str, str], tuple[int, Mapping[str, str]]] = {}
    for row_number, row in enumerate(csv_rows, start=2):
        key = (
            str(row.get("case_key") or "").strip(),
            str(row.get("anchor_id") or "").strip(),
        )
        if not all(key):
            raise ValueError(f"Anchor Gold row {row_number} lacks its Case key")
        if key in csv_by_key:
            raise ValueError(f"Anchor Gold CSV duplicates {key} at row {row_number}")
        csv_by_key[key] = (row_number, row)

    missing = sorted(set(queue_by_key) - set(csv_by_key))
    extra = sorted(set(csv_by_key) - set(queue_by_key))
    if missing or extra:
        raise ValueError(
            "Anchor Gold CSV scope differs from the frozen queue: "
            f"missing={missing}, extra={extra}"
        )

    result: list[AnchorGoldAdjudication] = []
    for queue_row in queue_rows:
        key = (str(queue_row["case_key"]), str(queue_row["anchor_id"]))
        row_number, csv_row = csv_by_key[key]
        _validate_immutable_fields(csv_row, queue_row, row_number=row_number)
        raw_decision = str(csv_row["manual_decision"] or "").strip().upper()
        acceptable = _parse_manual_ids(
            str(csv_row["manual_acceptable_candidate_ids"] or "")
        )
        preferred = str(csv_row["manual_preferred_candidate_id"] or "").strip()
        note = str(csv_row["manual_evidence_note"] or "").strip()
        if not raw_decision:
            if acceptable or preferred or note:
                raise ValueError(
                    f"Anchor Gold row {row_number} has manual fields without a decision"
                )
            if require_complete:
                raise ValueError(f"Anchor Gold row {row_number} is incomplete")
            continue
        try:
            decision = AnchorGoldDecision(raw_decision)
        except ValueError as exc:
            raise ValueError(
                f"Anchor Gold row {row_number} has an invalid decision"
            ) from exc
        if not note:
            raise ValueError(f"Anchor Gold row {row_number} lacks an evidence note")
        candidates = tuple(str(value) for value in queue_row["candidate_ids"])
        candidate_set = set(candidates)
        if decision is AnchorGoldDecision.SUCCESS_CONFIRMED:
            if not acceptable:
                raise ValueError(
                    f"SUCCESS_CONFIRMED row {row_number} lacks acceptable candidates"
                )
            outside = sorted(set(acceptable) - candidate_set)
            if outside:
                raise ValueError(
                    f"SUCCESS_CONFIRMED row {row_number} selects objects outside "
                    f"the frozen candidate set: {outside}"
                )
            if preferred not in acceptable:
                raise ValueError(
                    f"SUCCESS_CONFIRMED row {row_number} preferred candidate must "
                    "belong to the acceptable set"
                )
        elif acceptable or preferred:
            raise ValueError(
                f"{decision.value} row {row_number} must not select candidates"
            )
        result.append(
            AnchorGoldAdjudication(
                case_key=key[0],
                anchor_id=key[1],
                decision=decision,
                acceptable_candidate_ids=acceptable,
                preferred_candidate_id=preferred,
                evidence_note=note,
                affected_segment_ids=tuple(
                    str(value) for value in queue_row["impact_segment_ids"]
                ),
                queue_sample_id=str(queue_row["sample_id"]),
                source_row_number=row_number,
            )
        )
    return tuple(result)


def apply_anchor_gold_labels(
    examples: Sequence[AnchorPretrainExample],
    *,
    adjudications: Sequence[AnchorGoldAdjudication],
) -> tuple[list[AnchorPretrainExample], Counter[str]]:
    by_key = {(row.case_key, row.anchor_id): row for row in examples}
    if len(by_key) != len(examples):
        raise ValueError("Anchor label store has duplicate Case anchors")
    adjudication_by_key = {
        (row.case_key, row.anchor_id): row for row in adjudications
    }
    if len(adjudication_by_key) != len(adjudications):
        raise ValueError("Anchor Gold adjudications contain duplicate keys")
    missing = sorted(set(adjudication_by_key) - set(by_key))
    if missing:
        raise ValueError(f"Anchor Gold adjudications are outside the label store: {missing}")

    counts: Counter[str] = Counter()
    transformed: list[AnchorPretrainExample] = []
    for source in examples:
        key = (source.case_key, source.anchor_id)
        adjudication = adjudication_by_key.get(key)
        if adjudication is None:
            transformed.append(source)
            continue
        if source.sample_id != adjudication.queue_sample_id:
            raise ValueError(f"Anchor Gold adjudication uses a stale sample ID: {key}")
        if source.sample_weight >= 1.0:
            raise ValueError(f"Anchor Gold must not overwrite existing Gold truth: {key}")
        acceptable_indices = tuple(
            index
            for index, candidate_id in enumerate(source.candidate_ids)
            if candidate_id in set(adjudication.acceptable_candidate_ids)
        )
        preferred_index = (
            source.candidate_ids.index(adjudication.preferred_candidate_id)
            if adjudication.preferred_candidate_id
            else -1
        )
        if (
            adjudication.decision is AnchorGoldDecision.SUCCESS_CONFIRMED
            and len(acceptable_indices) != len(adjudication.acceptable_candidate_ids)
        ):
            raise ValueError(f"Anchor Gold objects are no longer reachable: {key}")
        status, gate_label, reason = _decision_label(adjudication.decision)
        candidate_supervised = bool(acceptable_indices)
        transformed.append(
            replace(
                source,
                status_label=ANCHOR_STATUS_INDEX[status],
                status_supervised=True,
                gate_label=gate_label,
                gate_supervised=True,
                candidate_acceptable_indices=acceptable_indices,
                preferred_candidate_index=preferred_index,
                candidate_supervised=candidate_supervised,
                sample_weight=1.0,
                label_reason=reason,
            )
        )
        counts["adjudicated_anchor"] += 1
        counts[f"decision:{adjudication.decision.value}"] += 1
        counts["candidate_supervised"] += int(candidate_supervised)
        counts["multi_solution"] += int(len(acceptable_indices) > 1)
        counts["positive_gate"] += int(gate_label == 1)
        counts["segment_fallback_gate"] += int(gate_label == 0)
    counts["example"] = len(transformed)
    return transformed, counts


def write_anchor_gold_overlay(
    *,
    anchor_store_root: Path,
    queue_path: Path,
    adjudication_csv_path: Path,
    output_root: Path,
    run_id: str,
    expected_adjudication_count: int = 80,
) -> Path:
    if expected_adjudication_count <= 0:
        raise ValueError("Expected Anchor Gold count must be positive")
    source_anchor = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    queue_source = normalize_runtime_path(queue_path).resolve(strict=True)
    csv_source = normalize_runtime_path(adjudication_csv_path).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    adjudications = read_anchor_gold_csv(
        csv_path=csv_source,
        queue_path=queue_source,
        require_complete=True,
    )
    examples = read_anchor_pretraining_stores(source_anchor)
    transformed, apply_counts = apply_anchor_gold_labels(
        examples,
        adjudications=adjudications,
    )
    output_anchor = write_anchor_pretraining_stores(
        transformed,
        output_root=root,
        run_id="anchor_store",
    )
    source_feature = (
        source_anchor / "inference_feature_store" / "anchor_features.jsonl"
    )
    output_feature = (
        output_anchor / "inference_feature_store" / "anchor_features.jsonl"
    )
    feature_store_byte_identical = (
        sha256_file(source_feature) == sha256_file(output_feature)
    )
    if not feature_store_byte_identical:
        raise RuntimeError("Anchor Gold overlay changed inference-time features")

    source_by_key = {(row.case_key, row.anchor_id): row for row in examples}
    changed_keys = {
        (row.case_key, row.anchor_id) for row in adjudications
    }
    if len(changed_keys) != len(adjudications):
        raise ValueError("Anchor Gold overlay contains duplicate Case anchors")
    fold_counts = Counter(
        source_by_key[key].fold for key in sorted(changed_keys)
    )
    case_counts = Counter(row.case_key for row in adjudications)
    decision_counts = Counter(row.decision.value for row in adjudications)
    summary = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "stage": "TARGET_A_UNIQUE_JUNCTION_GOLD_LABEL_OVERLAY",
        "label_only": True,
        "adjudication_count": len(adjudications),
        "expected_adjudication_count": expected_adjudication_count,
        "decision_counts": dict(sorted(decision_counts.items())),
        "case_counts": dict(sorted(case_counts.items())),
        "fold_counts": {
            str(key): value for key, value in sorted(fold_counts.items())
        },
        "apply_counts": dict(sorted(apply_counts.items())),
        "feature_store_byte_identical": feature_store_byte_identical,
        "inference_feature_sha256": sha256_file(output_feature),
        "inputs": {
            "anchor_manifest": _file_record(source_anchor / "manifest.json"),
            "queue": _file_record(queue_source),
            "adjudication_csv": _file_record(csv_source),
        },
        "outputs": {
            "anchor_manifest": _file_record(output_anchor / "manifest.json"),
            "training_labels": _file_record(
                output_anchor / "training_label_store" / "anchor_labels.jsonl"
            ),
        },
        "t01_skeleton_changed": False,
        "geometry_changed": False,
        "topology_changed": False,
        "silent_fix": False,
        "t03_t06_terminal_inference_input_added": False,
        "production_authorized": False,
        "gate_pass": bool(
            len(adjudications) == expected_adjudication_count
            and int(apply_counts["adjudicated_anchor"])
            == expected_adjudication_count
            and feature_store_byte_identical
        ),
    }
    if not summary["gate_pass"]:
        raise RuntimeError("Anchor Gold label-only overlay gate failed")
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _parse_manual_ids(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    result = tuple(part.strip() for part in value.split(LIST_SEPARATOR))
    if not all(result):
        raise ValueError("Anchor Gold acceptable candidate list contains an empty ID")
    if len(set(result)) != len(result):
        raise ValueError("Anchor Gold acceptable candidate list contains duplicates")
    return result


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
                f"Anchor Gold row {row_number} changed frozen field {field}"
            )


def _queue_csv_value(row: Mapping[str, Any], field: str) -> str:
    if field == "candidate_ids_json":
        return json.dumps(row["candidate_ids"], ensure_ascii=False, separators=(",", ":"))
    if field == "impact_segment_ids":
        return LIST_SEPARATOR.join(str(value) for value in row["impact_segment_ids"])
    return str(row[field])


def _decision_label(
    decision: AnchorGoldDecision,
) -> tuple[AnchorStatus, int, str]:
    if decision is AnchorGoldDecision.SUCCESS_CONFIRMED:
        return AnchorStatus.SUCCESS, 1, "user_anchor_gold:success_confirmed:object_reachable"
    if decision is AnchorGoldDecision.PROVEN_NO_EVIDENCE:
        return (
            AnchorStatus.NO_EVIDENCE,
            1,
            "user_anchor_gold:no_rcsd_evidence:positive_keep_swsd_clue_false",
        )
    if decision is AnchorGoldDecision.AMBIGUOUS:
        return AnchorStatus.AMBIGUOUS, 0, "user_anchor_gold:ambiguous:segment_fallback"
    return AnchorStatus.ABSTAIN, 0, "user_anchor_gold:candidate_missing:segment_fallback"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }
