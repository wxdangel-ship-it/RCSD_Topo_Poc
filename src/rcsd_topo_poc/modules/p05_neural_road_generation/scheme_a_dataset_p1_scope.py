from __future__ import annotations

import csv
import json
import platform
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p1_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_GO,
    DECISION_MAPPING_NO_GO,
    DECISION_SCOPE_NO_GO,
    SCHEME_A_DATASET_P1_SCHEMA,
    SchemeADatasetP1Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_SEGMENT_FAMILIES = frozenset({"T10-Error", "T10-Error-2"})
_EXPECTED_TERMINAL_STATE = "EXPECTED_FAIL"


def build_scheme_a_dataset_p1_scope(config: SchemeADatasetP1Config) -> Path:
    started = time.perf_counter()
    roots = {
        "dataset_p0": _resolve_dir(config.dataset_p0_run_root),
        "scheme_a_baseline": _resolve_dir(config.scheme_a_baseline_run_root),
        "p2_p3_p0": _resolve_dir(config.p2_p3_p0_run_root),
        "poc_data": _resolve_dir(config.poc_data_root),
    }
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    inputs, input_records = _load_inputs(roots, strict_hashes=config.strict_hashes)
    sample_rows = _read_csv(inputs["training_sample_manifest"])
    case_rows = _read_csv(inputs["case_inventory"])
    if len(sample_rows) != config.expected_sample_count:
        raise ValueError("Dataset-P0 sample denominator differs")
    if len(case_rows) != config.expected_case_count:
        raise ValueError("Scheme A Case denominator differs")

    cases, segment_index, crs_values = _load_frozen_skeletons(
        roots["scheme_a_baseline"], case_rows
    )
    segment_count = sum(len(rows) for rows in segment_index.values())
    if segment_count != config.expected_segment_count:
        raise ValueError("Scheme A Segment denominator differs")

    lineage_rows = _build_package_lineage(
        sample_rows=sample_rows,
        segment_index=segment_index,
        approved_exclusions=set(config.approved_exclusions),
        strict_hashes=config.strict_hashes,
    )
    expected_rows, failure_groups = _build_expected_failure_scope(
        p2_p3_manifest=inputs["p2_p3_manifest_payload"],
        segment_index=segment_index,
        strict_hashes=config.strict_hashes,
    )
    label_rows = _build_label_scope(
        cases=cases,
        segment_index=segment_index,
        lineage_rows=lineage_rows,
        failure_groups=failure_groups,
    )
    invalidation_rows = _historical_metric_invalidation()

    counts = _scope_counts(
        sample_rows=sample_rows,
        lineage_rows=lineage_rows,
        label_rows=label_rows,
        expected_rows=expected_rows,
        approved_exclusions=set(config.approved_exclusions),
    )
    mapping_errors = _mapping_error_count(lineage_rows)
    partition_counts = sorted(
        len(row["current_segment_ids"])
        for row in lineage_rows
        if row["mapping_method"] == "ROAD_PARTITION_LINEAGE"
    )
    gate0 = (
        counts["sample_count"] == config.expected_sample_count
        and counts["case_count"] == config.expected_case_count
        and counts["segment_count"] == config.expected_segment_count
        and counts["enabled_segment_package_count"]
        == config.expected_enabled_segment_package_count
        and counts["approved_exclusion_label_count"] == 0
    )
    gate1 = (
        mapping_errors == 0
        and counts["mapped_segment_package_count"]
        == config.expected_enabled_segment_package_count
        and counts["direct_package_count"] + counts["partition_package_count"]
        == config.expected_enabled_segment_package_count
        and counts["partition_package_count"]
        == config.expected_partition_package_count
        and counts["direct_road_drift_count"]
        == config.expected_direct_road_drift_count
        and partition_counts == sorted(config.expected_partition_descendant_counts)
    )
    gate2 = (
        counts["t10_label_count"] == config.expected_t10_segment_count
        and counts["context_label_leak_count"] == 0
        and counts["label_count"] + counts["context_only_count"]
        == config.expected_segment_count
        and counts["scope_duplicate_count"] == 0
    )
    gate3 = _expected_failure_gate(expected_rows, config)
    gate4 = all(row["artifact_status"] == "HISTORICAL_OLD_SCOPE" for row in invalidation_rows)

    signature_payload = {
        "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
        "lineage": lineage_rows,
        "label_scope": label_rows,
        "expected_failure": expected_rows,
        "historical_metric_invalidation": invalidation_rows,
        "counts": counts,
        "gates": {
            "gate0_scope": gate0,
            "gate1_mapping": gate1,
            "gate2_label_context_isolation": gate2,
            "gate3_expected_failure_layers": gate3,
            "gate4_historical_invalidation": gate4,
        },
        "crs_values": sorted(crs_values),
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    determinism_signature = canonical_sha256(signature_payload)
    reference_match = _reference_match(
        config.reference_run_root, determinism_signature
    )
    performance = _resource_summary(started, config)
    gate5 = (
        sorted(crs_values) == ["EPSG:3857"]
        and performance["gate_pass"]
        and reference_match in {None, True}
    )
    decision = _decision(gate0, gate1, gate2, gate3, gate4, gate5)

    paths = {
        "lineage": run_root / "segment_package_lineage.jsonl",
        "label_scope": run_root / "segment_label_scope.jsonl",
        "expected_failure": run_root / "expected_failure_scope.jsonl",
        "invalidation": run_root / "historical_metric_invalidation.jsonl",
        "summary": run_root / "dataset_p1_summary.json",
        "report": run_root / "validation_report.md",
        "artifact_manifest": run_root / "artifact_manifest.json",
        "manifest": run_root / "dataset_p1_manifest.json",
    }
    _write_jsonl(paths["lineage"], lineage_rows)
    _write_jsonl(paths["label_scope"], label_rows)
    _write_jsonl(paths["expected_failure"], expected_rows)
    _write_jsonl(paths["invalidation"], invalidation_rows)
    summary = {
        **signature_payload,
        "decision": decision,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "performance": performance,
        "gates": {
            **signature_payload["gates"],
            "gate5_determinism_gis_resource": gate5,
        },
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(_validation_report(summary), encoding="utf-8")
    artifact_payload = {
        key: output_record(path)
        for key, path in paths.items()
        if key not in {"artifact_manifest", "manifest"}
    }
    write_json(paths["artifact_manifest"], artifact_payload)
    manifest = {
        "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "completed" if decision == DECISION_GO else "failed",
        "decision": decision,
        "parameters": {
            "approved_exclusions": list(config.approved_exclusions),
            "expected_sample_count": config.expected_sample_count,
            "expected_case_count": config.expected_case_count,
            "expected_segment_count": config.expected_segment_count,
            "expected_t10_segment_count": config.expected_t10_segment_count,
            "expected_enabled_segment_package_count": (
                config.expected_enabled_segment_package_count
            ),
            "expected_partition_package_count": config.expected_partition_package_count,
            "expected_direct_road_drift_count": (
                config.expected_direct_road_drift_count
            ),
            "strict_hashes": config.strict_hashes,
        },
        "inputs": input_records,
        "outputs": {
            **artifact_payload,
            "artifact_manifest": output_record(paths["artifact_manifest"]),
        },
        "counts": counts,
        "gates": summary["gates"],
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "model_training_count": 0,
        "movement_decision_count": 0,
    }
    write_json(paths["manifest"], manifest)
    return run_root


def map_segment_package(
    *,
    target_segment_id: str,
    target_road_ids: Sequence[str],
    current_segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target_roads = frozenset(str(value) for value in target_road_ids if str(value))
    if not target_segment_id or not target_roads:
        return _mapping_result(
            method="UNAVAILABLE",
            status="TARGET_MANIFEST_INCOMPLETE",
            target_roads=target_roads,
        )
    current = {
        str(row["segment_id"]): frozenset(
            str(value) for value in row.get("swsd_road_ids") or () if str(value)
        )
        for row in current_segments
    }
    if target_segment_id in current:
        direct_roads = current[target_segment_id]
        return _mapping_result(
            method=(
                "DIRECT_ID_AND_ROAD_SET"
                if direct_roads == target_roads
                else "DIRECT_ID_WITH_ROAD_DRIFT"
            ),
            status="MAPPED",
            target_roads=target_roads,
            mapped={target_segment_id: direct_roads},
            missing=target_roads - direct_roads,
            extra=direct_roads - target_roads,
        )

    candidates = {
        segment_id: road_ids
        for segment_id, road_ids in current.items()
        if road_ids and road_ids.issubset(target_roads)
    }
    owners: dict[str, list[str]] = defaultdict(list)
    for segment_id, road_ids in candidates.items():
        for road_id in road_ids:
            owners[road_id].append(segment_id)
    duplicate_roads = {
        road_id for road_id, segment_ids in owners.items() if len(segment_ids) > 1
    }
    mapped_roads = frozenset(owners)
    missing_roads = target_roads - mapped_roads
    status = (
        "MAPPED"
        if candidates and not duplicate_roads and not missing_roads
        else "ROAD_PARTITION_INCOMPLETE_OR_AMBIGUOUS"
    )
    return _mapping_result(
        method="ROAD_PARTITION_LINEAGE",
        status=status,
        target_roads=target_roads,
        mapped=candidates,
        missing=missing_roads,
        duplicate=duplicate_roads,
    )


def _mapping_result(
    *,
    method: str,
    status: str,
    target_roads: Iterable[str],
    mapped: Mapping[str, Iterable[str]] | None = None,
    missing: Iterable[str] = (),
    duplicate: Iterable[str] = (),
    extra: Iterable[str] = (),
) -> dict[str, Any]:
    mapped = mapped or {}
    return {
        "mapping_method": method,
        "mapping_status": status,
        "target_road_ids": sorted(target_roads),
        "current_segment_ids": sorted(mapped),
        "current_segment_road_ids": {
            segment_id: sorted(road_ids)
            for segment_id, road_ids in sorted(mapped.items())
        },
        "missing_road_ids": sorted(missing),
        "duplicate_road_ids": sorted(duplicate),
        "extra_road_ids": sorted(extra),
        "road_drift_observed": bool(set(missing) or set(extra)),
        "geometry_inference_used": False,
    }


def _load_inputs(
    roots: Mapping[str, Path], *, strict_hashes: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifests = {
        "dataset_p0": roots["dataset_p0"] / "dataset_p0_manifest.json",
        "scheme_a_baseline": roots["scheme_a_baseline"] / "scheme_a_manifest.json",
        "p2_p3_p0": roots["p2_p3_p0"] / "scheme_a_p2_p3_p0_manifest.json",
    }
    payloads = {key: _read_json(path) for key, path in manifests.items()}
    if payloads["dataset_p0"].get("decision") != "P05_SCHEME_A_DATASET_P0_GO":
        raise ValueError("Dataset-P0 input decision differs")
    if payloads["p2_p3_p0"].get("decision") != "P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO":
        raise ValueError("P2-P3-P0 input decision differs")
    paths = {
        "training_sample_manifest": _output_path(
            payloads["dataset_p0"], "training_sample_manifest"
        ),
        "case_inventory": _output_path(payloads["scheme_a_baseline"], "case_inventory"),
        "decisions": _output_path(payloads["p2_p3_p0"], "decisions"),
        "roadgraphs": _output_path(payloads["p2_p3_p0"], "roadgraphs"),
        "p2_p3_manifest_payload": payloads["p2_p3_p0"],
    }
    for manifest in payloads.values():
        _verify_manifest_outputs(manifest, strict_hashes=strict_hashes)
    records = {
        key: output_record(path) for key, path in manifests.items()
    }
    return paths, records


def _load_frozen_skeletons(
    baseline_root: Path, case_rows: Sequence[Mapping[str, str]]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    set[str],
]:
    cases: dict[str, dict[str, Any]] = {}
    segment_index: dict[str, list[dict[str, Any]]] = {}
    crs_values: set[str] = set()
    for row in case_rows:
        relative_path = Path(str(row["frozen_skeleton"]).replace("\\", "/"))
        path = baseline_root / relative_path
        payload = _read_json(path)
        case_key = str(payload["case_key"])
        if case_key in cases:
            raise ValueError(f"duplicate frozen Case: {case_key}")
        segments = [dict(value) for value in payload["segments"]]
        ids = [str(value["segment_id"]) for value in segments]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate Segment ID: {case_key}")
        cases[case_key] = {
            "case_key": case_key,
            "family": str(payload["family"]),
            "fold": int(payload["fold"]),
            "crs": str(payload["crs"]),
        }
        segment_index[case_key] = segments
        crs_values.add(str(payload["crs"]))
    return cases, segment_index, crs_values


def _build_package_lineage(
    *,
    sample_rows: Sequence[Mapping[str, str]],
    segment_index: Mapping[str, Sequence[Mapping[str, Any]]],
    approved_exclusions: set[str],
    strict_hashes: bool,
) -> list[dict[str, Any]]:
    result = []
    for sample in sample_rows:
        family = str(sample["family"])
        if family not in _SEGMENT_FAMILIES:
            continue
        case_key = f"{family}:{sample['business_id']}"
        if case_key in approved_exclusions:
            continue
        manifest_path = normalize_runtime_path(sample["manifest_path"]).resolve()
        manifest = _read_json(manifest_path)
        if strict_hashes and sha256_file(manifest_path) != str(sample["manifest_sha256"]):
            raise ValueError(f"Segment package manifest hash differs: {case_key}")
        scope = dict(manifest.get("scope") or {})
        target_id = str(scope.get("swsd_segment_id") or "")
        properties = dict(scope.get("segment_properties") or {})
        property_id = str(properties.get("id") or "")
        target_roads = _split_ids(properties.get("roads"))
        business_id = str(sample["business_id"])
        if target_id != business_id or property_id != business_id:
            raise ValueError(f"Segment package target ID differs: {case_key}")
        if case_key not in segment_index:
            raise ValueError(f"Segment package has no frozen Case: {case_key}")
        mapping = map_segment_package(
            target_segment_id=target_id,
            target_road_ids=target_roads,
            current_segments=segment_index[case_key],
        )
        result.append(
            {
                "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
                "case_key": case_key,
                "family": family,
                "target_segment_id": target_id,
                "manifest_path": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                **mapping,
            }
        )
    return sorted(result, key=lambda row: row["case_key"])


def _build_expected_failure_scope(
    *,
    p2_p3_manifest: Mapping[str, Any],
    segment_index: Mapping[str, Sequence[Mapping[str, Any]]],
    strict_hashes: bool,
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    roadgraph_path = _output_path(p2_p3_manifest, "roadgraphs")
    decisions_path = _output_path(p2_p3_manifest, "decisions")
    if strict_hashes:
        _verify_output_record(
            p2_p3_manifest["outputs"]["roadgraphs"], roadgraph_path
        )
        _verify_output_record(
            p2_p3_manifest["outputs"]["decisions"], decisions_path
        )
    historical_masks: Counter[tuple[str, int]] = Counter()
    for row in _read_jsonl(decisions_path):
        if row.get("reason") == "expected_swsd_baseline_failure":
            historical_masks[(str(row["case_key"]), int(row["seed"]))] += 1

    rows = []
    groups: dict[str, set[str]] = defaultdict(set)
    for index_row in _read_jsonl(roadgraph_path):
        if str(index_row.get("terminal_state")) != _EXPECTED_TERMINAL_STATE:
            continue
        case_key = str(index_row["case_key"])
        seed = int(index_row["seed"])
        graph_path = normalize_runtime_path(str(index_row["output"]["path"])).resolve()
        if strict_hashes and sha256_file(graph_path) != str(index_row["output"]["sha256"]):
            raise ValueError(f"RoadGraph hash differs: {case_key}/{seed}")
        graph = _read_json(graph_path)
        audit = dict(graph.get("audit") or {})
        failure_group_ids = sorted(str(value) for value in audit["failure_group_ids"])
        expected_prefix = f"SCHEME_A_P1:SEGMENT:{case_key}:"
        if any(not group_id.startswith(expected_prefix) for group_id in failure_group_ids):
            raise ValueError(f"expected-failure group scope differs: {case_key}")
        groups[case_key].update(failure_group_ids)
        rows.append(
            {
                "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
                "case_key": case_key,
                "seed": seed,
                "terminal_state": str(audit["terminal_state"]),
                "publish": bool(audit["publish"]),
                "expected_failure_match": bool(audit["expected_failure_match"]),
                "failure_group_ids": failure_group_ids,
                "failure_count": int(audit["failure_count"]),
                "failures": list(audit["failures"]),
                "case_segment_count": len(segment_index[case_key]),
                "localized_failure_segment_count": len(failure_group_ids),
                "historical_case_cascade_mask_count": historical_masks[(case_key, seed)],
                "corrected_case_cascade_mask_count": 0,
            }
        )
    return sorted(rows, key=lambda row: (row["case_key"], row["seed"])), groups


def _build_label_scope(
    *,
    cases: Mapping[str, Mapping[str, Any]],
    segment_index: Mapping[str, Sequence[Mapping[str, Any]]],
    lineage_rows: Sequence[Mapping[str, Any]],
    failure_groups: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    lineage_by_case = {str(row["case_key"]): row for row in lineage_rows}
    rows = []
    for case_key in sorted(segment_index):
        case = cases[case_key]
        lineage = lineage_by_case.get(case_key)
        mapped_ids = (
            set(lineage["current_segment_ids"])
            if lineage and lineage["mapping_status"] == "MAPPED"
            else set()
        )
        for segment in sorted(segment_index[case_key], key=lambda row: str(row["segment_id"])):
            object_id = str(segment["segment_id"])
            group_id = f"SCHEME_A_P1:SEGMENT:{case_key}:{object_id}"
            if case["family"] == "T10":
                scope_class = "CASE_TRUTH_LABEL"
                label_eligible = True
                reason = "whole T10 Case manually confirmed"
                target_id = ""
                method = "CASE_LEVEL_TRUTH"
            elif object_id in mapped_ids:
                scope_class = "TARGET_LINEAGE_LABEL"
                label_eligible = True
                reason = "package target or lineage-proven current T01 descendant"
                target_id = str(lineage["target_segment_id"])
                method = str(lineage["mapping_method"])
            else:
                scope_class = "CONTEXT_ONLY_MASKED"
                label_eligible = False
                reason = "non-target Segment in Segment-scoped evidence package"
                target_id = str(lineage["target_segment_id"])
                method = str(lineage["mapping_method"])
            rows.append(
                {
                    "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
                    "case_key": case_key,
                    "family": case["family"],
                    "fold": case["fold"],
                    "group_id": group_id,
                    "object_id": object_id,
                    "scope_class": scope_class,
                    "label_eligible": label_eligible,
                    "label_weight": 0.7 if label_eligible else None,
                    "scorer_metric_eligible": label_eligible,
                    "context_input_eligible": True,
                    "context_input_weight": None if label_eligible else 0.3,
                    "package_target_segment_id": target_id,
                    "lineage_method": method,
                    "case_terminal_state": (
                        _EXPECTED_TERMINAL_STATE
                        if case_key in failure_groups
                        else "LEGAL"
                    ),
                    "object_failure_localized": group_id
                    in failure_groups.get(case_key, set()),
                    "reason": reason,
                }
            )
    return rows


def _scope_counts(
    *,
    sample_rows: Sequence[Mapping[str, str]],
    lineage_rows: Sequence[Mapping[str, Any]],
    label_rows: Sequence[Mapping[str, Any]],
    expected_rows: Sequence[Mapping[str, Any]],
    approved_exclusions: set[str],
) -> dict[str, Any]:
    group_ids = [str(row["group_id"]) for row in label_rows]
    labels = [row for row in label_rows if bool(row["label_eligible"])]
    context = [
        row for row in label_rows if row["scope_class"] == "CONTEXT_ONLY_MASKED"
    ]
    return {
        "sample_count": len(sample_rows),
        "case_count": len({row["case_key"] for row in label_rows}),
        "segment_count": len(label_rows),
        "enabled_segment_package_count": len(lineage_rows),
        "mapped_segment_package_count": sum(
            row["mapping_status"] == "MAPPED" for row in lineage_rows
        ),
        "direct_package_count": sum(
            str(row["mapping_method"]).startswith("DIRECT_ID_")
            and row["mapping_status"] == "MAPPED"
            for row in lineage_rows
        ),
        "direct_road_drift_count": sum(
            row["mapping_method"] == "DIRECT_ID_WITH_ROAD_DRIFT"
            and row["mapping_status"] == "MAPPED"
            for row in lineage_rows
        ),
        "partition_package_count": sum(
            row["mapping_method"] == "ROAD_PARTITION_LINEAGE"
            and row["mapping_status"] == "MAPPED"
            for row in lineage_rows
        ),
        "segment_package_target_label_count": sum(
            row["scope_class"] == "TARGET_LINEAGE_LABEL" for row in label_rows
        ),
        "t10_label_count": sum(
            row["scope_class"] == "CASE_TRUTH_LABEL" for row in label_rows
        ),
        "label_count": len(labels),
        "context_only_count": len(context),
        "context_label_leak_count": sum(
            bool(row["label_eligible"]) or row["label_weight"] is not None
            for row in context
        ),
        "scope_duplicate_count": len(group_ids) - len(set(group_ids)),
        "approved_exclusion_label_count": sum(
            row["case_key"] in approved_exclusions and bool(row["label_eligible"])
            for row in label_rows
        ),
        "expected_failure_case_count": len(
            {row["case_key"] for row in expected_rows}
        ),
        "expected_failure_seed_row_count": len(expected_rows),
        "historical_case_cascade_mask_count": sum(
            int(row["historical_case_cascade_mask_count"]) for row in expected_rows
        ),
        "corrected_case_cascade_mask_count": sum(
            int(row["corrected_case_cascade_mask_count"]) for row in expected_rows
        ),
    }


def _mapping_error_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        row["mapping_status"] != "MAPPED"
        or (
            row["mapping_method"] == "ROAD_PARTITION_LINEAGE"
            and (
                bool(row["missing_road_ids"])
                or bool(row["duplicate_road_ids"])
                or bool(row["extra_road_ids"])
            )
        )
        or bool(row["geometry_inference_used"])
        for row in rows
    )


def _expected_failure_gate(
    rows: Sequence[Mapping[str, Any]], config: SchemeADatasetP1Config
) -> bool:
    cases = {str(row["case_key"]) for row in rows}
    seeds = {int(row["seed"]) for row in rows}
    return (
        len(cases) == config.expected_failure_case_count
        and len(seeds) == config.expected_seed_count
        and len(rows) == config.expected_failure_case_count * config.expected_seed_count
        and all(row["terminal_state"] == _EXPECTED_TERMINAL_STATE for row in rows)
        and all(not bool(row["publish"]) for row in rows)
        and all(bool(row["expected_failure_match"]) for row in rows)
        and all(int(row["localized_failure_segment_count"]) >= 1 for row in rows)
        and all(int(row["corrected_case_cascade_mask_count"]) == 0 for row in rows)
        and all(
            int(row["historical_case_cascade_mask_count"])
            == int(row["case_segment_count"])
            for row in rows
        )
    )


def _historical_metric_invalidation() -> list[dict[str, Any]]:
    rows = (
        (
            "Scheme-A-Baseline",
            ["frozen T01 skeleton", "fallback lineage", "RoadGraph safety"],
            ["8,863-row carrier label eligibility", "0.3 context label weights"],
        ),
        (
            "Scheme-A-Dataset-P0",
            ["candidate inventory", "artifact lineage", "Road/Node reachability evidence"],
            ["8,863 Segment label denominator", "label-weighted reachability metrics"],
        ),
        (
            "Scheme-A-P1",
            ["model artifacts", "generic graph legality evidence"],
            ["training labels", "macro-F1", "coverage", "anomaly metrics"],
        ),
        (
            "Scheme-A-P2-P0",
            ["candidate bundles", "Junction compatibility design"],
            ["joint truth retention on old Segment denominator"],
        ),
        (
            "Scheme-A-P2-P1",
            ["Node conditioning implementation", "RoadGraph safety evidence"],
            ["training labels", "accepted wrong", "coverage", "macro-F1"],
        ),
        (
            "Scheme-A-P2-P2-P0/P1",
            ["calibration and safety-head artifacts"],
            ["stable error sets", "coverage", "unsafe recall"],
        ),
        (
            "Scheme-A-P2-P2-P2-P0/P1/P2",
            ["evidence inventory", "source-role audit", "decoder legality"],
            ["error/clue denominators", "fold metrics", "model restart decision inputs"],
        ),
        (
            "Scheme-A-P2-P3-P0",
            ["2.818M model artifacts", "generic Node/Junction decoder safety"],
            ["training labels", "stable wrong", "fold coverage", "clue metrics"],
        ),
        (
            "Scheme-A-P2-P3-P1",
            ["raw attribution artifacts", "field-role inventory"],
            [
                "T10-Error:1029603_1043020 stable-wrong interpretation",
                "fold 2 expected-failure coverage ceiling",
            ],
        ),
    )
    return [
        {
            "schema_version": SCHEME_A_DATASET_P1_SCHEMA,
            "stage": stage,
            "artifact_status": "HISTORICAL_OLD_SCOPE",
            "preserved_facts": preserved,
            "invalidated_metrics": invalidated,
            "reason": (
                "T10-Error/T10-Error-2 non-target Segment were context, not labels"
            ),
            "required_next_action": "rebuild dataset and retrain/re-evaluate on Dataset-P1",
        }
        for stage, preserved, invalidated in rows
    ]


def _decision(
    gate0: bool,
    gate1: bool,
    gate2: bool,
    gate3: bool,
    gate4: bool,
    gate5: bool,
) -> str:
    if not gate0 or not gate5:
        return DECISION_AUDIT_NO_GO
    if not gate1:
        return DECISION_MAPPING_NO_GO
    if not gate2 or not gate3 or not gate4:
        return DECISION_SCOPE_NO_GO
    return DECISION_GO


def _resource_summary(
    started: float, config: SchemeADatasetP1Config
) -> dict[str, Any]:
    wall = time.perf_counter() - started
    peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    return {
        "wall_seconds": wall,
        "peak_rss_bytes": peak_rss,
        "gpu_vram_bytes": 0,
        "wall_within_10_minutes": wall <= config.max_wall_seconds,
        "cpu_ram_within_4gb": 0 < peak_rss <= config.max_peak_rss_bytes,
        "gpu_vram_zero": True,
        "gate_pass": (
            wall <= config.max_wall_seconds
            and 0 < peak_rss <= config.max_peak_rss_bytes
        ),
    }


def _validation_report(summary: Mapping[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# P05-Scheme-A-Dataset-P1 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- label/context denominator: `{counts['label_count']}/{counts['context_only_count']}`",
            f"- T10 labels: `{counts['t10_label_count']}`",
            f"- Segment-package target descendants: `{counts['segment_package_target_label_count']}`",
            f"- direct/partition package: `{counts['direct_package_count']}/{counts['partition_package_count']}`",
            f"- direct-ID Road drift package: `{counts['direct_road_drift_count']}`",
            f"- context label leakage: `{counts['context_label_leak_count']}`",
            f"- historical/corrected Case cascade masks: `{counts['historical_case_cascade_mask_count']}/{counts['corrected_case_cascade_mask_count']}`",
            f"- determinism signature: `{summary['determinism_signature']}`",
            f"- reference match: `{summary['reference_run_match']}`",
            "",
            "No model training, threshold tuning, Movement decision, geometry read/write,",
            "skeleton mutation, content repair, silent fix or T01-T12 implementation change",
            "was performed.",
            "",
        ]
    )


def _reference_match(path: Path | None, signature: str) -> bool | None:
    if path is None:
        return None
    root = _resolve_dir(path)
    summary = _read_json(root / "dataset_p1_summary.json")
    return str(summary["determinism_signature"]) == signature


def _verify_manifest_outputs(
    manifest: Mapping[str, Any], *, strict_hashes: bool
) -> None:
    for key, record in (manifest.get("outputs") or {}).items():
        path = normalize_runtime_path(str(record["path"])).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if int(record.get("size_bytes", path.stat().st_size)) != path.stat().st_size:
            raise ValueError(f"output size differs: {key}")
        if strict_hashes and sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"output hash differs: {key}")


def _verify_output_record(record: Mapping[str, Any], path: Path) -> None:
    if int(record["size_bytes"]) != path.stat().st_size:
        raise ValueError(f"output size differs: {path}")
    if sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"output hash differs: {path}")


def _output_path(manifest: Mapping[str, Any], key: str) -> Path:
    return normalize_runtime_path(str(manifest["outputs"][key]["path"])).resolve()


def _split_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        return _split_ids(parsed)
    return sorted({item.strip() for item in text.split(",") if item.strip()})


def _resolve_dir(path: Path) -> Path:
    resolved = normalize_runtime_path(path).resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
            stream.write("\n")


__all__ = [
    "build_scheme_a_dataset_p1_scope",
    "map_segment_package",
]
