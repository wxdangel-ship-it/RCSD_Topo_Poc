from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_business_adjudications import (
    user_anchor_adjudication,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


RELATION_RECORD_ABSENT_PREFIX = "t05:relation_record_absent:"
T11_NO_VALID_PREFIX = "t11_manual:no_valid_relation:"
T11_MANUAL_PREFIX = "t11_manual:"
OBJECT_MASKED_SUFFIX = ":object_selection_masked"
FORMAL_T03_T04_PREFIX = "formal_t03_t04_to_t05:"
FORMAL_OBJECT_UNREACHABLE_SUFFIX = ":final_object_unreachable"


def apply_anchor_plan_supervision_policy(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
    output_root: Path,
    run_id: str,
    confirmed_no_evidence_anchor_keys: Iterable[tuple[str, str]] = (),
    confirmed_no_evidence_segment_keys: Iterable[tuple[str, str]] = (),
) -> Path:
    """Apply the confirmed three-state anchor policy without changing features."""
    source_anchor = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    source_plan = normalize_runtime_path(plan_label_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    examples = read_anchor_pretraining_stores(source_anchor)
    explicit_no_evidence = {
        (str(case_key), str(anchor_id))
        for case_key, anchor_id in confirmed_no_evidence_anchor_keys
    }
    explicit_no_evidence_segments = {
        (str(case_key), str(segment_id))
        for case_key, segment_id in confirmed_no_evidence_segment_keys
    }
    transformed, anchor_counts = apply_anchor_supervision_policy(
        examples,
        confirmed_no_evidence_anchor_keys=explicit_no_evidence,
    )
    anchor_output = write_anchor_pretraining_stores(
        transformed,
        output_root=root,
        run_id="anchor_store",
    )
    source_feature_path = (
        source_anchor / "inference_feature_store" / "anchor_features.jsonl"
    )
    output_feature_path = (
        anchor_output / "inference_feature_store" / "anchor_features.jsonl"
    )
    if sha256_file(source_feature_path) != sha256_file(output_feature_path):
        raise RuntimeError("anchor policy changed truth-free inference features")

    groups = _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    plan_rows = _read_jsonl(source_plan / "training_plan_labels.jsonl")
    transformed_plans, plan_counts = apply_plan_supervision_policy(
        plan_rows,
        groups=groups,
        anchor_examples=transformed,
        confirmed_no_evidence_segment_keys=explicit_no_evidence_segments,
    )
    plan_output = root / "plan_label_store"
    plan_output.mkdir()
    plan_path = plan_output / "training_plan_labels.jsonl"
    _write_jsonl(plan_path, transformed_plans)
    plan_summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_CONSISTENT_PLAN_LABEL_POLICY",
        "label_only": True,
        "inference_input_allowed": False,
        "terminal_feature_count": 0,
        "counts": dict(sorted(plan_counts.items())),
        "source_plan_labels": _input_record(
            source_plan / "training_plan_labels.jsonl"
        ),
        "training_labels": _input_record(plan_path),
    }
    _write_json(plan_output / "summary.json", plan_summary)

    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_PLAN_SUPERVISION_POLICY",
        "policy": {
            "proven_no_rcsd_evidence": (
                "resolved positive anchor terminal state; no RCSD object selected"
            ),
            "relation_record_absent": (
                "unknown and masked; never converted to success or failure"
            ),
            "t11_no_valid_relation": (
                "explicit unresolved anchor; direct Segment fallback"
            ),
            "known_positive_candidate_missing": (
                "supervised object truth outside the frozen candidate set; "
                "explicit Segment fallback"
            ),
            "user_visual_anchorable_target_unspecified": (
                "positive anchor gate supervision; exact RCSD object head "
                "masked; current inference may still ABSTAIN safely"
            ),
        },
        "confirmed_no_evidence_anchor_keys": [
            {"case_key": case_key, "anchor_id": anchor_id}
            for case_key, anchor_id in sorted(explicit_no_evidence)
        ],
        "confirmed_no_evidence_segment_keys": [
            {"case_key": case_key, "segment_id": segment_id}
            for case_key, segment_id in sorted(explicit_no_evidence_segments)
        ],
        "anchor_counts": dict(sorted(anchor_counts.items())),
        "plan_counts": dict(sorted(plan_counts.items())),
        "feature_rows_recomputed": 0,
        "feature_store_byte_identical": True,
        "inputs": {
            "anchor_manifest": _input_record(source_anchor / "manifest.json"),
            "candidate_manifest": _input_record(candidate_root / "manifest.json"),
            "plan_labels": _input_record(
                source_plan / "training_plan_labels.jsonl"
            ),
        },
        "outputs": {
            "anchor_manifest": _input_record(anchor_output / "manifest.json"),
            "plan_labels": _input_record(plan_path),
        },
        "gate_pass": (
            anchor_counts["supervised_relation_record_absent"] == 0
            and anchor_counts["t11_no_valid_supervised_failure"]
            == anchor_counts["t11_no_valid"]
            and anchor_counts["known_candidate_missing_supervised_failure"]
            == anchor_counts["known_candidate_missing"]
            and plan_counts["failed_segment_scope_violation"] == 0
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("anchor/plan supervision policy gate failed")
    return root


def apply_anchor_supervision_policy(
    examples: Sequence[AnchorPretrainExample],
    *,
    confirmed_no_evidence_anchor_keys: Iterable[tuple[str, str]] = (),
) -> tuple[list[AnchorPretrainExample], Counter[str]]:
    explicit_no_evidence = {
        (str(case_key), str(anchor_id))
        for case_key, anchor_id in confirmed_no_evidence_anchor_keys
    }
    by_key = {(row.case_key, row.anchor_id): row for row in examples}
    if len(by_key) != len(examples):
        raise ValueError("anchor supervision policy has duplicate Case anchors")
    missing = sorted(explicit_no_evidence - set(by_key))
    if missing:
        raise ValueError(
            f"confirmed no-evidence anchors are outside the store: {missing}"
        )
    invalid = sorted(
        key
        for key in explicit_no_evidence
        if not by_key[key].label_reason.startswith(
            RELATION_RECORD_ABSENT_PREFIX
        )
    )
    if invalid:
        raise ValueError(
            "confirmed no-evidence override conflicts with existing anchor truth: "
            f"{invalid}"
        )

    counts: Counter[str] = Counter()
    transformed: list[AnchorPretrainExample] = []
    for row in examples:
        key = (row.case_key, row.anchor_id)
        adjudication = user_anchor_adjudication(
            row.case_key,
            row.anchor_id,
        )
        if adjudication is not None:
            acceptable = tuple(
                index
                for index, candidate_id in enumerate(row.candidate_ids)
                if candidate_id
                in adjudication.acceptable_candidate_ids
            )
            if (
                adjudication.acceptable_candidate_ids
                and not acceptable
            ):
                raise ValueError(
                    "user anchor adjudication target is outside the "
                    f"truth-free candidate set: {key}"
                )
            result = replace(
                row,
                status_label=ANCHOR_STATUS_INDEX[
                    AnchorStatus(adjudication.business_status)
                ],
                status_supervised=adjudication.status_supervised,
                gate_label=int(
                    adjudication.business_status
                    in {
                        AnchorStatus.SUCCESS.value,
                        AnchorStatus.NO_EVIDENCE.value,
                    }
                ),
                gate_supervised=adjudication.status_supervised,
                candidate_acceptable_indices=acceptable,
                preferred_candidate_index=(
                    acceptable[0] if acceptable else -1
                ),
                candidate_supervised=bool(acceptable),
                sample_weight=adjudication.sample_weight,
                label_reason=(
                    f"user_manual_anchor:{adjudication.reason}:"
                    + (
                        "object_reachable"
                        if acceptable
                        else "object_unspecified"
                    )
                ),
            )
            counts["user_manual_anchor_adjudication"] += 1
            counts["user_manual_anchor_candidate_unspecified"] += int(
                not acceptable
            )
        elif row.label_reason.startswith(RELATION_RECORD_ABSENT_PREFIX):
            counts["relation_record_absent"] += 1
            if key in explicit_no_evidence:
                result = replace(
                    row,
                    status_label=ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
                    status_supervised=True,
                    gate_label=1,
                    gate_supervised=True,
                    candidate_acceptable_indices=(),
                    preferred_candidate_index=-1,
                    candidate_supervised=False,
                    sample_weight=1.0,
                    label_reason=(
                        "user_confirmed:no_rcsd_evidence:"
                        "positive_keep_swsd_clue_false"
                    ),
                )
                counts["promoted_proven_no_evidence"] += 1
            else:
                result = replace(
                    row,
                    status_supervised=False,
                    gate_supervised=False,
                    candidate_acceptable_indices=(),
                    preferred_candidate_index=-1,
                    candidate_supervised=False,
                    label_reason=(
                        "t05:relation_record_absent:"
                        "anchor_truth_unknown:masked"
                    ),
                )
                counts["masked_relation_record_absent"] += 1
        elif (candidate_missing_origin := _candidate_missing_origin(row)):
            if (
                not row.status_supervised
                or row.status_label
                != ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
                or row.candidate_supervised
                or row.candidate_acceptable_indices
            ):
                raise ValueError(
                    "Known candidate-missing anchor has inconsistent source "
                    f"supervision: {key}"
                )
            reason = row.label_reason
            suffix = (
                FORMAL_OBJECT_UNREACHABLE_SUFFIX
                if reason.endswith(FORMAL_OBJECT_UNREACHABLE_SUFFIX)
                else OBJECT_MASKED_SUFFIX
            )
            result = replace(
                row,
                status_label=ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
                status_supervised=True,
                gate_label=0,
                gate_supervised=True,
                candidate_acceptable_indices=(),
                preferred_candidate_index=-1,
                candidate_supervised=False,
                label_reason=(
                    reason[: -len(suffix)]
                    + ":candidate_missing:segment_fallback"
                ),
            )
            counts["known_candidate_missing"] += 1
            counts[f"{candidate_missing_origin}_candidate_missing"] += 1
        else:
            result = row
        if result.label_reason.startswith(T11_NO_VALID_PREFIX):
            counts["t11_no_valid"] += 1
            if (
                result.status_supervised
                and result.gate_supervised
                and result.status_label
                == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
                and result.gate_label == 0
            ):
                counts["t11_no_valid_supervised_failure"] += 1
        if ":candidate_missing:segment_fallback" in result.label_reason:
            if (
                result.status_supervised
                and result.gate_supervised
                and result.status_label
                == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
                and result.gate_label == 0
                and not result.candidate_supervised
            ):
                counts["known_candidate_missing_supervised_failure"] += 1
        if (
            result.label_reason.startswith(RELATION_RECORD_ABSENT_PREFIX)
            and (result.status_supervised or result.gate_supervised)
        ):
            counts["supervised_relation_record_absent"] += 1
        transformed.append(result)
    counts["example"] = len(transformed)
    return transformed, counts


def _candidate_missing_origin(
    row: AnchorPretrainExample,
) -> str:
    if (
        not row.status_supervised
        or row.status_label
        != ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        or row.candidate_supervised
        or row.candidate_acceptable_indices
        or row.member_supervised
        or row.member_acceptable_sets
    ):
        return ""
    reason = row.label_reason
    if (
        reason.startswith(T11_MANUAL_PREFIX)
        and reason.endswith(OBJECT_MASKED_SUFFIX)
    ):
        return "t11_manual"
    if (
        reason.startswith("t05:")
        and reason.endswith(OBJECT_MASKED_SUFFIX)
    ):
        return "t05_weak"
    if (
        reason.startswith(FORMAL_T03_T04_PREFIX)
        and reason.endswith(FORMAL_OBJECT_UNREACHABLE_SUFFIX)
    ):
        return "formal_t03_t04"
    return ""


def apply_plan_supervision_policy(
    plan_rows: Sequence[Mapping[str, Any]],
    *,
    groups: Sequence[Mapping[str, Any]],
    anchor_examples: Sequence[AnchorPretrainExample],
    confirmed_no_evidence_segment_keys: Iterable[tuple[str, str]] = (),
) -> tuple[list[dict[str, Any]], Counter[str]]:
    group_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row for row in groups
    }
    anchor_by_key = {
        (row.case_key, row.anchor_id): row for row in anchor_examples
    }
    explicit_no_evidence_segments = {
        (str(case_key), str(segment_id))
        for case_key, segment_id in confirmed_no_evidence_segment_keys
    }
    missing_segments = sorted(
        explicit_no_evidence_segments - set(group_by_key)
    )
    if missing_segments:
        raise ValueError(
            "confirmed no-evidence Segments are outside the plan groups: "
            f"{missing_segments}"
        )
    counts: Counter[str] = Counter()
    transformed: list[dict[str, Any]] = []
    for source in plan_rows:
        row = dict(source)
        key = (str(row["case_key"]), str(row["segment_id"]))
        group = group_by_key.get(key)
        if group is None:
            raise ValueError(f"plan supervision group is missing: {key}")
        if str(group.get("segment_type")) != "STANDARD":
            row["segment_anchor_gate_label"] = None
            row["segment_anchor_gate_task_mask"] = False
            row["anchor_supervision_state"] = "NOT_APPLICABLE"
            transformed.append(row)
            counts["not_applicable"] += 1
            continue

        required = tuple(str(value) for value in group["required_anchor_ids"])
        anchors = [
            anchor_by_key.get((key[0], anchor_id)) for anchor_id in required
        ]
        all_present = all(anchor is not None for anchor in anchors)
        all_supervised = all_present and all(
            bool(anchor and anchor.gate_supervised) for anchor in anchors
        )
        any_failed = bool(required) and any(
            bool(
                anchor
                and anchor.gate_supervised
                and anchor.gate_label == 0
            )
            for anchor in anchors
        )
        all_resolved = all_supervised and all(
            bool(anchor and anchor.gate_label == 1) for anchor in anchors
        )
        manual_unresolved = (
            bool(row.get("keep_reason_task_mask"))
            and str(row.get("keep_reason")) == "ANCHOR_UNRESOLVED"
            and bool(row.get("fallback_scope_task_mask"))
            and str(row.get("fallback_scope")) == "SEGMENT"
        )
        if any_failed or manual_unresolved:
            state = "FAILED"
            row["segment_anchor_gate_label"] = 0
            row["segment_anchor_gate_task_mask"] = True
            row["carrier_task_mask"] = False
            row["carrier_is_conditional_on_anchor"] = True
            row["keep_reason"] = "ANCHOR_UNRESOLVED"
            row["keep_reason_task_mask"] = True
            row["fallback_scope"] = "SEGMENT"
            row["fallback_scope_task_mask"] = True
            counts["segment_gate_failure"] += 1
        elif all_resolved:
            state = "RESOLVED"
            row["segment_anchor_gate_label"] = 1
            row["segment_anchor_gate_task_mask"] = True
            row["carrier_task_mask"] = bool(
                row.get("carrier_task_mask", True)
            )
            if (
                str(row.get("preferred_carrier_target")) == "KEEP_SWSD"
                and (
                    key in explicit_no_evidence_segments
                    or (
                        bool(row.get("keep_reason_task_mask"))
                        and str(row.get("keep_reason"))
                        == "NO_RCSD_EVIDENCE"
                    )
                )
            ):
                row["keep_reason"] = "NO_RCSD_EVIDENCE"
                row["keep_reason_task_mask"] = True
                row["reality_change_clue"] = False
                row["clue_task_mask"] = True
                row["fallback_scope"] = "NONE"
                row["fallback_scope_task_mask"] = True
                counts["positive_keep_proven_no_evidence"] += 1
            counts["segment_gate_resolved"] += 1
        else:
            state = "UNKNOWN"
            row["segment_anchor_gate_label"] = None
            row["segment_anchor_gate_task_mask"] = False
            row["carrier_task_mask"] = bool(
                row.get("carrier_task_mask", True)
            )
            row["carrier_is_conditional_on_anchor"] = True
            if (
                bool(row.get("fallback_scope_task_mask"))
                and str(row.get("fallback_scope")) == "NONE"
            ):
                row["fallback_scope"] = None
                row["fallback_scope_task_mask"] = False
                counts["masked_unknown_none_scope"] += 1
            counts["segment_gate_unknown"] += 1
        row["anchor_supervision_state"] = state
        row["anchor_supervision_task_mask"] = all_supervised
        if (
            state == "FAILED"
            and (
                bool(row.get("carrier_task_mask"))
                or not bool(row.get("fallback_scope_task_mask"))
                or str(row.get("fallback_scope")) != "SEGMENT"
            )
        ):
            counts["failed_segment_scope_violation"] += 1
        transformed.append(row)
    counts["plan_row"] = len(transformed)
    return transformed, counts


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
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _input_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


__all__ = [
    "apply_anchor_plan_supervision_policy",
    "apply_anchor_supervision_policy",
    "apply_plan_supervision_policy",
]
