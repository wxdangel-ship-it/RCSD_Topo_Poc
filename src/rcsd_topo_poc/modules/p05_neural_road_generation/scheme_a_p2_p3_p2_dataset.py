from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_dataset import (
    load_hierarchical_training_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    HierarchicalTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_models import (
    SchemeAP2P3P2Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def load_dataset_p1_hierarchical_examples(
    config: SchemeAP2P3P2Config,
) -> tuple[list[HierarchicalTrainingExample], dict[str, Any]]:
    all_examples, base_metadata = load_hierarchical_training_examples(config.base_config)
    root = normalize_runtime_path(config.dataset_p1_root).resolve(strict=True)
    manifest_path = root / "dataset_p1_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("decision") != "P05_SCHEME_A_DATASET_P1_GO":
        raise ValueError("Dataset-P1 label-scope gate did not pass")
    outputs = dict(manifest.get("outputs") or {})
    scope_path = _verified_output(outputs, "label_scope", config.base_config.strict_hashes)
    expected_failure_path = _verified_output(
        outputs, "expected_failure", config.base_config.strict_hashes
    )
    scope_rows = list(_read_jsonl(scope_path))
    eligible_examples, context_examples, application_rows = apply_dataset_p1_scope(
        all_examples,
        scope_rows,
    )
    failure_rows = list(_read_jsonl(expected_failure_path))
    failure_group_ids, failure_by_case = _failure_scope(
        failure_rows,
        model_seeds=config.base_config.model_seeds,
    )
    clue_only_ids = set(base_metadata["clue_only_group_ids"])
    eligible_ids = {example.group.group_id for example in eligible_examples}
    eligible_clue_only_ids = sorted(clue_only_ids & eligible_ids)
    _validate_scope(
        config,
        eligible_examples=eligible_examples,
        context_examples=context_examples,
        application_rows=application_rows,
        failure_group_ids=failure_group_ids,
        eligible_clue_only_ids=eligible_clue_only_ids,
    )
    scope_signature_payload = [
        {
            "group_id": row["group_id"],
            "label_eligible": row["label_eligible"],
            "scorer_metric_eligible": row["scorer_metric_eligible"],
            "label_weight": row["label_weight"],
            "context_input_weight": row["context_input_weight"],
            "object_failure_localized": row["object_failure_localized"],
        }
        for row in application_rows
    ]
    lineage = {
        **base_metadata["lineage"],
        "dataset_p1_manifest_sha256": sha256_file(manifest_path),
        "dataset_p1_label_scope_sha256": sha256_file(scope_path),
        "dataset_p1_expected_failure_sha256": sha256_file(expected_failure_path),
        "dataset_p1_scope_signature": canonical_sha256(scope_signature_payload),
    }
    lineage["dataset_p1_training_signature"] = canonical_sha256(lineage)
    return eligible_examples, {
        **base_metadata,
        "all_segment_examples": all_examples,
        "context_examples": context_examples,
        "scope_application_rows": application_rows,
        "failure_group_ids": sorted(failure_group_ids),
        "failure_by_case": failure_by_case,
        "eligible_clue_only_group_ids": eligible_clue_only_ids,
        "dataset_p1_manifest": manifest,
        "dataset_p1_manifest_path": manifest_path,
        "dataset_p1_scope_path": scope_path,
        "dataset_p1_expected_failure_path": expected_failure_path,
        "lineage": lineage,
        "scope_audit": _scope_audit(
            eligible_examples,
            context_examples,
            application_rows,
            eligible_clue_only_ids,
            failure_group_ids,
        ),
    }


def apply_dataset_p1_scope(
    examples: Sequence[HierarchicalTrainingExample],
    scope_rows: Sequence[Mapping[str, Any]],
) -> tuple[
    list[HierarchicalTrainingExample],
    list[HierarchicalTrainingExample],
    list[dict[str, Any]],
]:
    example_by_id = {example.group.group_id: example for example in examples}
    if len(example_by_id) != len(examples):
        raise ValueError("duplicate base hierarchical group")
    scope_by_id: dict[str, Mapping[str, Any]] = {}
    for row in scope_rows:
        group_id = str(row.get("group_id") or "")
        if not group_id or group_id in scope_by_id:
            raise ValueError("empty or duplicate Dataset-P1 scope group")
        scope_by_id[group_id] = row
    if set(scope_by_id) != set(example_by_id):
        raise ValueError("Dataset-P1 scope and hierarchical Segment groups differ")

    eligible: list[HierarchicalTrainingExample] = []
    context: list[HierarchicalTrainingExample] = []
    applications: list[dict[str, Any]] = []
    for group_id in sorted(example_by_id):
        example = example_by_id[group_id]
        group = example.group
        scope = scope_by_id[group_id]
        if (
            str(scope.get("case_key") or "") != group.case_key
            or int(scope.get("fold")) != group.fold
            or str(scope.get("object_id") or "") != group.object_id
        ):
            raise ValueError(f"Dataset-P1 identity mismatch: {group_id}")
        label_eligible = bool(scope.get("label_eligible"))
        metric_eligible = bool(scope.get("scorer_metric_eligible"))
        if label_eligible != metric_eligible:
            raise ValueError(f"label/metric eligibility differs: {group_id}")
        if not bool(scope.get("context_input_eligible")):
            raise ValueError(f"Segment is absent from context input scope: {group_id}")
        label_weight = scope.get("label_weight")
        context_weight = scope.get("context_input_weight")
        if label_eligible:
            if label_weight is None or float(label_weight) <= 0:
                raise ValueError(f"eligible Segment lacks a positive weight: {group_id}")
            if context_weight is not None:
                raise ValueError(f"eligible Segment has context-only weight: {group_id}")
            eligible.append(
                replace(
                    example,
                    group=replace(group, sample_weight=float(label_weight)),
                )
            )
        else:
            if label_weight is not None:
                raise ValueError(f"context Segment retains label weight: {group_id}")
            if float(context_weight) != 0.3:
                raise ValueError(f"context Segment weight differs from 0.3: {group_id}")
            context.append(example)
        applications.append(
            {
                "case_key": group.case_key,
                "fold": group.fold,
                "group_id": group_id,
                "object_id": group.object_id,
                "scope_class": str(scope.get("scope_class") or ""),
                "label_eligible": label_eligible,
                "scorer_metric_eligible": metric_eligible,
                "label_weight": float(label_weight) if label_weight is not None else None,
                "context_input_eligible": True,
                "context_input_weight": (
                    float(context_weight) if context_weight is not None else None
                ),
                "object_failure_localized": bool(
                    scope.get("object_failure_localized")
                ),
            }
        )
    return eligible, context, applications


def _failure_scope(
    rows: Sequence[Mapping[str, Any]],
    *,
    model_seeds: Sequence[int],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    expected_seeds = set(model_seeds)
    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(str(row["case_key"]), []).append(row)
    result: dict[str, dict[str, Any]] = {}
    group_ids: set[str] = set()
    for case_key, case_rows in sorted(by_case.items()):
        if {int(row["seed"]) for row in case_rows} != expected_seeds:
            raise ValueError(f"expected-failure seed scope differs: {case_key}")
        frozen_groups = {
            tuple(str(value) for value in row.get("failure_group_ids") or [])
            for row in case_rows
        }
        if len(frozen_groups) != 1 or len(next(iter(frozen_groups))) != 1:
            raise ValueError(f"expected-failure group is not uniquely localized: {case_key}")
        group_id = next(iter(frozen_groups))[0]
        if any(
            row.get("terminal_state") != "EXPECTED_FAIL"
            or bool(row.get("publish"))
            or int(row.get("corrected_case_cascade_mask_count") or 0) != 0
            for row in case_rows
        ):
            raise ValueError(f"expected-failure Case contract differs: {case_key}")
        group_ids.add(group_id)
        result[case_key] = {
            "failure_group_id": group_id,
            "failures": list(case_rows[0].get("failures") or []),
            "seed_count": len(case_rows),
        }
    return group_ids, result


def _validate_scope(
    config: SchemeAP2P3P2Config,
    *,
    eligible_examples: Sequence[HierarchicalTrainingExample],
    context_examples: Sequence[HierarchicalTrainingExample],
    application_rows: Sequence[Mapping[str, Any]],
    failure_group_ids: set[str],
    eligible_clue_only_ids: Sequence[str],
) -> None:
    if len(application_rows) != config.expected_all_segment_count:
        raise ValueError("all Segment scope denominator differs")
    if len(eligible_examples) != config.expected_eligible_count:
        raise ValueError("eligible Segment denominator differs")
    if len(context_examples) != config.expected_context_count:
        raise ValueError("context Segment denominator differs")
    if len({example.group.case_key for example in eligible_examples}) != (
        config.expected_case_count
    ):
        raise ValueError("one or more Cases lack eligible Segment labels")
    targets = Counter(example.group.truth_target for example in eligible_examples)
    if targets != Counter(dict(config.expected_target_counts)):
        raise ValueError("eligible carrier target denominator differs")
    folds = Counter(example.group.fold for example in eligible_examples)
    if tuple(folds[index] for index in range(len(config.expected_fold_eligible_counts))) != (
        config.expected_fold_eligible_counts
    ):
        raise ValueError("eligible fold denominator differs")
    if sum(
        example.group.truth_target == "REVIEW_FALLBACK"
        for example in eligible_examples
    ) != config.expected_review_count:
        raise ValueError("eligible Review denominator differs")
    if sum(example.group.anomaly_target for example in eligible_examples) != (
        config.expected_anomaly_count
    ):
        raise ValueError("eligible anomaly denominator differs")
    localized = {
        str(row["group_id"])
        for row in application_rows
        if bool(row["object_failure_localized"])
    }
    if localized != failure_group_ids or len(localized) != config.expected_local_failure_count:
        raise ValueError("localized failure scope differs")
    eligible_ids = {example.group.group_id for example in eligible_examples}
    if not failure_group_ids <= eligible_ids:
        raise ValueError("localized expected failure is absent from eligible labels")
    if len(eligible_clue_only_ids) != config.expected_clue_only_eligible_count:
        raise ValueError("eligible clue-only denominator differs")


def _scope_audit(
    eligible_examples: Sequence[HierarchicalTrainingExample],
    context_examples: Sequence[HierarchicalTrainingExample],
    application_rows: Sequence[Mapping[str, Any]],
    eligible_clue_only_ids: Sequence[str],
    failure_group_ids: set[str],
) -> dict[str, Any]:
    return {
        "all_segment_count": len(application_rows),
        "eligible_count": len(eligible_examples),
        "context_only_count": len(context_examples),
        "eligible_case_count": len(
            {example.group.case_key for example in eligible_examples}
        ),
        "target_counts": dict(
            Counter(example.group.truth_target for example in eligible_examples)
        ),
        "fold_eligible_counts": dict(
            Counter(example.group.fold for example in eligible_examples)
        ),
        "review_count": sum(
            example.group.truth_target == "REVIEW_FALLBACK"
            for example in eligible_examples
        ),
        "anomaly_count": sum(
            example.group.anomaly_target for example in eligible_examples
        ),
        "eligible_clue_only_count": len(eligible_clue_only_ids),
        "localized_failure_count": len(failure_group_ids),
        "context_label_weight_count": sum(
            row["label_weight"] is not None
            for row in application_rows
            if not row["label_eligible"]
        ),
        "context_metric_eligible_count": sum(
            bool(row["scorer_metric_eligible"])
            for row in application_rows
            if not row["label_eligible"]
        ),
    }


def _verified_output(
    outputs: Mapping[str, Any], key: str, strict_hashes: bool
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"Dataset-P1 output hash mismatch: {key}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "apply_dataset_p1_scope",
    "load_dataset_p1_hierarchical_examples",
]
