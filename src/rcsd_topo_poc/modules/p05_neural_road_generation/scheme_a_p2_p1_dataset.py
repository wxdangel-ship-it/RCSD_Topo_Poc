from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_dataset import (
    candidate_matches_label,
    forbidden_feature_hits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SCHEME_A_P2_P1_DATASET_SCHEMA,
    SchemeAP2P1DatasetConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_node_carriers import (
    build_endpoint_node_carriers,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


DATASET_MANIFEST_VERSION = "p05-scheme-a-p2-p1-dataset-manifest-v1"


@dataclass
class _NodeGroupStats:
    case_key: str
    family: str
    business_id: str
    raw_group_id: str
    candidate_count: int = 0
    actions: set[str] = field(default_factory=set)
    lineage_kinds: set[str] = field(default_factory=set)
    source_kinds: set[str] = field(default_factory=set)
    source_roles: set[str] = field(default_factory=set)
    mainnode_ids: set[str] = field(default_factory=set)
    output_object_ids: set[str] = field(default_factory=set)
    truth_candidate_id: str = ""
    truth_target: str = ""

    @property
    def group_id(self) -> str:
        return f"P2P1:NODE:{self.case_key}:{self.raw_group_id}"

    @property
    def junction_key(self) -> str:
        if self.mainnode_ids:
            value = ",".join(sorted(self.mainnode_ids))
            return f"{self.case_key}:MAINNODE:{value}"
        return f"{self.case_key}:NODE:{self.raw_group_id}"


def build_scheme_a_p2_p1_dataset(config: SchemeAP2P1DatasetConfig) -> Path:
    dataset_p0_root = _resolve_dir(config.dataset_p0_run_root)
    p1_root = _resolve_dir(config.p1_candidate_run_root)
    pto_candidate_root = _resolve_dir(config.pto_candidate_run_root)
    pto_solve_root = _resolve_dir(config.pto_solve_run_root)
    baseline_root = _resolve_dir(config.scheme_a_baseline_run_root)

    dataset_p0_manifest_path = dataset_p0_root / "dataset_p0_manifest.json"
    p1_manifest_path = p1_root / "scheme_a_p1_candidate_manifest.json"
    pto_candidate_manifest_path = pto_candidate_root / "p05_pto_candidate_manifest.json"
    pto_solve_manifest_path = pto_solve_root / "p05_pto_solve_manifest.json"
    baseline_manifest_path = baseline_root / "scheme_a_manifest.json"
    manifests = {
        "dataset_p0": _read_json(dataset_p0_manifest_path),
        "p1_candidate": _read_json(p1_manifest_path),
        "pto_candidate": _read_json(pto_candidate_manifest_path),
        "pto_solve": _read_json(pto_solve_manifest_path),
        "scheme_a_baseline": _read_json(baseline_manifest_path),
    }
    _validate_manifests(manifests, config)
    for manifest in manifests.values():
        _verify_outputs(manifest, config.strict_hashes)
    if manifests["pto_solve"].get("candidate_manifest_sha256") != sha256_file(
        pto_candidate_manifest_path
    ):
        raise ValueError("PTO solve/candidate lineage mismatch")

    p1_candidate_path = _verified_output(manifests["p1_candidate"], "candidates")
    p1_feature_path = _verified_output(manifests["p1_candidate"], "features")
    p1_lineage_path = _verified_output(manifests["p1_candidate"], "lineage")
    pto_candidate_path = _verified_output(manifests["pto_candidate"], "candidates")
    _verified_output(manifests["pto_solve"], "oracle_costs")
    certificate_path = _verified_output(manifests["pto_solve"], "solve_certificates")
    baseline_labels_path = baseline_root / "carrier_labels.jsonl"

    baseline_segment_labels, case_folds = _load_segment_labels(baseline_labels_path)
    if len(case_folds) != config.expected_case_count:
        raise ValueError("Scheme A Case scope differs from P2-P1 contract")
    if len(set(case_folds.values())) != config.expected_fold_count:
        raise ValueError("Scheme A fold scope differs from P2-P1 contract")
    segment_candidates = _load_segment_candidates(p1_candidate_path)
    segment_labels = {
        key: dict(value) for key, value in baseline_segment_labels.items()
    }
    junction_fallback_overrides: set[tuple[str, str]] = set()
    for _ in range(config.expected_case_count + 1):
        node_bundle = build_endpoint_node_carriers(
            pto_candidate_path=pto_candidate_path,
            p1_lineage_path=p1_lineage_path,
            segment_candidates=segment_candidates,
            segment_labels=segment_labels,
            case_folds=case_folds,
            expected_missing_nodes=config.expected_missing_endpoint_nodes,
        )
        requested = {
            (str(case_key), str(segment_id))
            for case_key, segment_id in node_bundle["junction_fallback_segment_keys"]
        }
        new_overrides = requested - junction_fallback_overrides
        if not requested:
            break
        if not new_overrides:
            raise ValueError("Junction fallback did not resolve shared Node payload conflicts")
        for key in sorted(new_overrides):
            safe = [
                row
                for row in segment_candidates[key]
                if row.get("candidate_target") == "KEEP_SWSD"
                and row.get("target_payload")
            ]
            if len(safe) != 1:
                raise ValueError(f"Junction fallback Segment has no unique SWSD carrier: {key}")
            segment_labels[key].update(
                {
                    "carrier_target": "KEEP_SWSD",
                    "target_kind": safe[0]["target_kind"],
                    "target_payload": safe[0]["target_payload"],
                    "available": True,
                    "mask_reason": "shared_node_payload_conflict_junction_fallback",
                    "junction_fallback": True,
                }
            )
        junction_fallback_overrides.update(new_overrides)
    else:
        raise ValueError("Junction fallback iteration limit exceeded")
    fallback_positive_segments = _fallback_positive_segments(
        baseline_root / "fallback_plans.jsonl"
    ) | junction_fallback_overrides

    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    feature_path = run_root / "candidate_features.jsonl"
    payload_path = run_root / "candidate_payloads.jsonl"
    label_path = run_root / "labels.jsonl"
    group_path = run_root / "group_index.csv"
    compatibility_edge_path = run_root / "compatibility_edges.jsonl"

    labels: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    forbidden_hits: list[dict[str, str]] = []
    segment_truth_ids: set[str] = set()
    candidate_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()

    with feature_path.open("w", encoding="utf-8", newline="\n") as feature_stream, payload_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as payload_stream:
        p1_features = {
            str(row["candidate_id"]): row
            for row in _read_jsonl(p1_feature_path)
            if row.get("object_type") == "SEGMENT"
        }
        for key in sorted(segment_labels):
            label = segment_labels[key]
            rows = segment_candidates.get(key, [])
            matches = [row for row in rows if candidate_matches_label(row, label)]
            if len(matches) != 1:
                raise ValueError(f"Segment truth candidate is not unique: {key}")
            truth_id = str(matches[0]["candidate_id"])
            segment_truth_ids.add(truth_id)
            group_id = str(rows[0]["group_id"])
            labels.append(
                {
                    "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
                    "case_key": label["case_key"],
                    "object_type": "SEGMENT",
                    "object_id": label["object_id"],
                    "group_id": group_id,
                    "junction_key": "",
                    "truth_candidate_id": truth_id,
                    "carrier_target": label["carrier_target"],
                    "available": bool(label["available"]),
                    "anomaly_target": key in fallback_positive_segments
                    or not bool(label["available"]),
                    "label_weight": float(label["label_weight"]),
                    "weight_role": label["weight_role"],
                    "fold": int(label["fold"]),
                    "label_only": True,
                }
            )
            target_counts[f"SEGMENT:{label['carrier_target']}"] += 1
            groups.append(
                _group_index_row(
                    label["case_key"], "SEGMENT", label["object_id"], group_id, "", len(rows), int(label["fold"])
                )
            )
            for candidate in sorted(rows, key=lambda item: str(item["candidate_id"])):
                feature = p1_features[str(candidate["candidate_id"])]
                hits = forbidden_feature_hits(feature, label)
                forbidden_hits.extend(
                    {"candidate_id": str(candidate["candidate_id"]), "hit": hit} for hit in hits
                )
                feature_row = {
                    "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
                    "case_key": candidate["case_key"],
                    "object_type": "SEGMENT",
                    "object_id": candidate["object_id"],
                    "group_id": group_id,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_target": candidate["candidate_target"],
                    "object_tokens": feature["object_tokens"],
                    "candidate_tokens": feature["candidate_tokens"],
                    "context_tokens": feature["context_tokens"],
                    "numeric_features": feature["numeric_features"],
                    "hard_unsafe": bool(feature["hard_unsafe"]),
                    "fold": int(label["fold"]),
                    "feature_uses_truth": False,
                    "absolute_coordinate_feature_count": 0,
                }
                _write_jsonl_row(feature_stream, feature_row)
                _write_jsonl_row(
                    payload_stream,
                    {
                        "case_key": candidate["case_key"],
                        "object_type": "SEGMENT",
                        "object_id": candidate["object_id"],
                        "group_id": group_id,
                        "candidate_id": candidate["candidate_id"],
                        "candidate_target": candidate["candidate_target"],
                        "target_kind": candidate["target_kind"],
                        "target_payload": candidate["target_payload"],
                        "payload_artifact_by_id": candidate.get("payload_artifact_by_id") or [],
                        "payload_artifacts": candidate.get("payload_artifacts") or [],
                    },
                )
                candidate_counts["SEGMENT"] += 1

        for feature_row in node_bundle["features"]:
            _write_jsonl_row(feature_stream, feature_row)
            candidate_counts["NODE"] += 1
        for payload_row in node_bundle["payloads"]:
            _write_jsonl_row(payload_stream, payload_row)

    labels.extend(node_bundle["labels"])
    groups.extend(node_bundle["groups"])
    for row in node_bundle["labels"]:
        target_counts[f"NODE:{row['carrier_target']}"] += 1

    labels.sort(key=lambda row: (row["case_key"], row["object_type"], row["group_id"]))
    groups.sort(key=lambda row: (row["case_key"], row["object_type"], row["group_id"]))
    _write_jsonl(label_path, labels)
    _write_jsonl(compatibility_edge_path, node_bundle["compatibility_edges"])
    write_csv(
        group_path,
        groups,
        ["case_key", "object_type", "object_id", "group_id", "junction_key", "candidate_count", "fold"],
    )

    certificate_audit = _certificate_audit(certificate_path, config.expected_case_count)
    segment_group_count = sum(row["object_type"] == "SEGMENT" for row in groups)
    node_group_count = sum(row["object_type"] == "NODE" for row in groups)
    segment_group_ids = {row["group_id"] for row in groups if row["object_type"] == "SEGMENT"}
    node_group_ids = {row["group_id"] for row in groups if row["object_type"] == "NODE"}
    invalid_compatibility_edges = [
        row
        for row in node_bundle["compatibility_edges"]
        if row["segment_group_id"] not in segment_group_ids
        or row["node_group_id"] not in node_group_ids
        or row["required_node_target"] not in {"T01_NODE", "PROPOSAL_NODE"}
        or bool(row.get("feature_uses_truth"))
    ]
    compatibility = {
        "schema_version": "p05-scheme-a-p2-p1-compatibility-oracle-v1",
        "candidate_first": True,
        "segment_truth_unique_count": len(segment_truth_ids),
        "segment_group_count": segment_group_count,
        "segment_exact_reachability": len(segment_truth_ids) / max(1, segment_group_count),
        "node_truth_unique_count": len(node_bundle["labels"]),
        "node_group_count": node_group_count,
        "node_exact_reachability": len(node_bundle["labels"]) / max(1, node_group_count),
        "junction_unit_count": len(
            {row["junction_key"] for row in node_bundle["groups"]}
        ),
        "node_candidate_signature": node_bundle["candidate_signature"],
        "compatibility_edge_count": len(node_bundle["compatibility_edges"]),
        "invalid_compatibility_edge_count": len(invalid_compatibility_edges),
        "compatibility_edges_truth_free": not invalid_compatibility_edges,
        "possible_endpoint_count": node_bundle["possible_endpoint_count"],
        "required_endpoint_count": node_bundle["required_endpoint_count"],
        "conditioned_node_missing": node_bundle["missing"],
        "shared_node_payload_conflicts": node_bundle["shared_payload_conflicts"],
        "junction_fallback_segment_count": len(junction_fallback_overrides),
        "junction_fallback_segment_keys": [list(value) for value in sorted(junction_fallback_overrides)],
        "pto_semantic_exact_case_count": certificate_audit["semantic_exact_case_count"],
        "pto_relaxation_count": certificate_audit["relaxation_count"],
        "pto_content_repair_count": certificate_audit["content_repair_count"],
        "joint_truth_exact_case_count": certificate_audit["semantic_exact_case_count"],
        "joint_truth_exact": certificate_audit["semantic_exact_case_count"] == config.expected_case_count,
        "movement_candidate_count": 0,
        "passed": certificate_audit["passed"]
        and len(segment_truth_ids) == segment_group_count
        and node_bundle["passed"]
        and len(node_bundle["labels"]) == node_group_count
        and not invalid_compatibility_edges,
    }
    compatibility_path = run_root / "compatibility_oracle.json"
    write_json(compatibility_path, compatibility)
    leakage = {
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "candidate_manifest_frozen_before_label_join": True,
        "forbidden_hits": forbidden_hits[:100],
        "passed": not forbidden_hits,
    }
    leakage_path = run_root / "leakage_audit.json"
    write_json(leakage_path, leakage)

    gate_pass = (
        compatibility["passed"]
        and leakage["passed"]
        and segment_group_count == config.expected_segment_group_count
        and (
            config.expected_node_group_count == 0
            or node_group_count == config.expected_node_group_count
        )
        and len({row["case_key"] for row in groups}) == config.expected_case_count
    )
    summary = {
        "schema_version": "p05-scheme-a-p2-p1-dataset-summary-v1",
        "gate_pass": gate_pass,
        "decision": "P2_P1_DATASET_GATE_PASS" if gate_pass else "P2_P1_DATA_NO_GO",
        "case_count": len({row["case_key"] for row in groups}),
        "fold_count": len(set(case_folds.values())),
        "group_counts": {"SEGMENT": segment_group_count, "NODE": node_group_count, "MOVEMENT": 0},
        "candidate_counts": dict(sorted(candidate_counts.items())),
        "compatibility_edge_count": len(node_bundle["compatibility_edges"]),
        "target_counts": dict(sorted(target_counts.items())),
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "compatibility_oracle_pass": compatibility["passed"],
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    summary_path = run_root / "scheme_a_p2_p1_dataset_summary.json"
    write_json(summary_path, summary)
    outputs = {
        "features": output_record(feature_path),
        "payloads": output_record(payload_path),
        "labels": output_record(label_path),
        "groups": output_record(group_path),
        "compatibility_edges": output_record(compatibility_edge_path),
        "compatibility_oracle": output_record(compatibility_path),
        "leakage_audit": output_record(leakage_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": DATASET_MANIFEST_VERSION,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_passed" if gate_pass else "dataset_failed",
        "input_manifests": {
            name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for name, path in {
                "dataset_p0": dataset_p0_manifest_path,
                "p1_candidate": p1_manifest_path,
                "pto_candidate": pto_candidate_manifest_path,
                "pto_solve": pto_solve_manifest_path,
                "scheme_a_baseline": baseline_manifest_path,
            }.items()
        },
        "candidate_first": True,
        "compatibility_edge_count": len(node_bundle["compatibility_edges"]),
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "outputs": outputs,
    }
    manifest_path = run_root / "scheme_a_p2_p1_dataset_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p1-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)] + [output_record(manifest_path)],
        },
    )
    return run_root


def _validate_manifests(manifests: Mapping[str, Mapping[str, Any]], config: SchemeAP2P1DatasetConfig) -> None:
    expected = {
        "dataset_p0": "completed",
        "p1_candidate": "candidate_scope_passed",
        "pto_candidate": "candidate_scope_passed",
        "pto_solve": "p0_semantic_passed_performance_failed",
        "scheme_a_baseline": "passed",
    }
    for name, status in expected.items():
        if manifests[name].get("status") != status:
            raise ValueError(f"{name} status is not accepted: {manifests[name].get('status')}")
    if int(manifests["dataset_p0"].get("counts", {}).get("case_count", config.expected_case_count)) != config.expected_case_count:
        raise ValueError("Dataset-P0 Case count mismatch")
    for name in ("p1_candidate", "pto_candidate"):
        manifest = manifests[name]
        for field in ("truth_input_count", "truth_derived_candidate_count"):
            if int(manifest.get(field, 0)) != 0:
                raise ValueError(f"{name} contains truth-derived candidates: {field}")
    for field in ("truth_feature_count", "absolute_coordinate_feature_count"):
        if int(manifests["p1_candidate"].get(field, 0)) != 0:
            raise ValueError(f"P1 candidate contains forbidden feature: {field}")


def _load_segment_labels(path: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, int]]:
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    case_folds: dict[str, int] = {}
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        key = (str(row["case_key"]), str(row["object_id"]))
        if key in labels:
            raise ValueError(f"duplicate Segment label: {key}")
        labels[key] = row
        fold = int(row["fold"])
        previous = case_folds.setdefault(key[0], fold)
        if previous != fold:
            raise ValueError(f"Case crosses folds: {key[0]}")
    return labels, case_folds


def _load_segment_candidates(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        if row.get("object_type") == "SEGMENT":
            result[(str(row["case_key"]), str(row["object_id"]))].append(row)
    return result


def _fallback_positive_segments(path: Path) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for row in _read_jsonl(path):
        result.update(
            (str(row["case_key"]), str(segment_id))
            for segment_id in row.get("segment_ids") or []
        )
    return result


def _load_node_truth(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for row in _read_jsonl(path):
        raw_group_id = str(row.get("group_id") or "")
        if not raw_group_id.startswith("FINAL_NODE:") or not bool(row.get("truth_equivalent")):
            continue
        case_key = f"{row['family']}:{row['business_id']}"
        key = (case_key, raw_group_id)
        if key in result:
            raise ValueError(f"multiple Node Oracle truth candidates: {key}")
        result[key] = (str(row["candidate_id"]), "")
    return result


def _scan_node_groups(path: Path, truth: Mapping[tuple[str, str], tuple[str, str]]) -> dict[tuple[str, str], _NodeGroupStats]:
    result: dict[tuple[str, str], _NodeGroupStats] = {}
    for row in _read_jsonl(path):
        if row.get("stage") != "FINAL_NODE":
            continue
        case_key = _case_key(row)
        key = (case_key, str(row["group_id"]))
        stats = result.setdefault(
            key,
            _NodeGroupStats(case_key, str(row["family"]), str(row["business_id"]), str(row["group_id"])),
        )
        stats.candidate_count += 1
        stats.actions.add(str(row["action"]))
        stats.lineage_kinds.add(str(row.get("lineage_kind") or "UNKNOWN"))
        for source in row.get("sources") or []:
            stats.source_kinds.add(str(source.get("source_kind") or "UNKNOWN"))
            stats.source_roles.add(str(source.get("role") or "UNKNOWN"))
        stats.output_object_ids.update(str(value) for value in row.get("output_object_ids") or [])
        for payload in row.get("output_payloads") or []:
            properties = payload.get("properties") or {}
            mainnode = properties.get("mainnodeid")
            if mainnode not in (None, "", 0, 0.0):
                stats.mainnode_ids.add(_stable_identifier(mainnode))
        truth_value = truth.get(key)
        if truth_value and str(row["candidate_id"]) == truth_value[0]:
            if stats.truth_candidate_id:
                raise ValueError(f"Node truth candidate repeated: {key}")
            stats.truth_candidate_id = str(row["candidate_id"])
            stats.truth_target = str(row["action"])
    if set(result) != set(truth):
        missing = sorted(set(result) ^ set(truth))[:10]
        raise ValueError(f"PTO Node candidate/Oracle group scope differs: {missing}")
    missing_truth = [key for key, stats in result.items() if not stats.truth_candidate_id]
    if missing_truth:
        raise ValueError(f"Node truth candidate missing: {missing_truth[:10]}")
    return result


def _node_feature(row: Mapping[str, Any], stats: _NodeGroupStats, fold: int) -> dict[str, Any]:
    payloads = list(row.get("output_payloads") or [])
    sources = list(row.get("sources") or [])
    geometry_types = sorted({str((payload.get("geometry") or {}).get("type") or "NONE") for payload in payloads})
    mainnode_present = any(
        (payload.get("properties") or {}).get("mainnodeid") not in (None, "", 0, 0.0)
        for payload in payloads
    )
    node_lid_count = sum(
        len([value for value in str((payload.get("properties") or {}).get("node_lid") or "").split(",") if value])
        for payload in payloads
    )
    property_key_count = sum(len(payload.get("properties") or {}) for payload in payloads)
    candidate_tokens = {
        f"ACTION:{row['action']}",
        f"LINEAGE:{row.get('lineage_kind') or 'UNKNOWN'}",
        f"OUTPUT_COUNT:{_count_bin(len(payloads))}",
        f"SOURCE_COUNT:{_count_bin(len(sources))}",
        f"MAINNODE_PRESENT:{mainnode_present}",
        *(f"GEOMETRY:{value}" for value in geometry_types),
        *(f"SOURCE_KIND:{source.get('source_kind') or 'UNKNOWN'}" for source in sources),
        *(f"SOURCE_ROLE:{source.get('role') or 'UNKNOWN'}" for source in sources),
    }
    object_tokens = {
        "OBJECT:NODE",
        f"GROUP_CANDIDATE_COUNT:{_count_bin(stats.candidate_count)}",
        f"GROUP_ACTION_COUNT:{_count_bin(len(stats.actions))}",
        f"GROUP_MAINNODE_VARIANTS:{_count_bin(len(stats.mainnode_ids))}",
        f"GROUP_OUTPUT_VARIANTS:{_count_bin(len(stats.output_object_ids))}",
    }
    context_tokens = {
        f"CONTEXT_ACTION:{value}" for value in stats.actions
    } | {
        f"CONTEXT_LINEAGE:{value}" for value in stats.lineage_kinds
    } | {
        f"CONTEXT_SOURCE_KIND:{value}" for value in stats.source_kinds
    }
    numeric = (
        math.log1p(len(payloads)),
        math.log1p(len(sources)),
        float(bool(payloads)),
        float(mainnode_present),
        math.log1p(node_lid_count),
        math.log1p(property_key_count),
        math.log1p(stats.candidate_count),
        math.log1p(len(stats.output_object_ids)),
    )
    return {
        "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
        "case_key": stats.case_key,
        "object_type": "NODE",
        "object_id": stats.raw_group_id,
        "group_id": stats.group_id,
        "candidate_id": row["candidate_id"],
        "candidate_target": row["action"],
        "object_tokens": sorted(object_tokens),
        "candidate_tokens": sorted(candidate_tokens),
        "context_tokens": sorted(context_tokens),
        "numeric_features": list(numeric),
        "hard_unsafe": False,
        "fold": fold,
        "feature_uses_truth": False,
        "absolute_coordinate_feature_count": 0,
    }


def _certificate_audit(path: Path, expected_case_count: int) -> dict[str, Any]:
    case_count = semantic_exact = relaxation = content_repair = hard_failures = 0
    for row in _read_jsonl(path):
        case_count += 1
        relaxation += int(bool(row.get("relaxation")))
        content_repair += int(bool(row.get("content_repair")))
        hard_failures += len(row.get("hard_failures") or [])
        semantic_exact += int(
            float(row.get("objective", 1)) == 0.0
            and float(row.get("optimality_gap", 1)) == 0.0
            and not row.get("missing_groups")
            and not row.get("extra_exactly_one_groups")
            and not row.get("hard_failures")
            and not row.get("relaxation")
            and not row.get("content_repair")
        )
    return {
        "case_count": case_count,
        "semantic_exact_case_count": semantic_exact,
        "relaxation_count": relaxation,
        "content_repair_count": content_repair,
        "hard_failure_count": hard_failures,
        "passed": case_count == expected_case_count == semantic_exact
        and relaxation == content_repair == hard_failures == 0,
    }


def _group_index_row(case_key: str, object_type: str, object_id: str, group_id: str, junction_key: str, candidate_count: int, fold: int) -> dict[str, Any]:
    return {
        "case_key": case_key,
        "object_type": object_type,
        "object_id": object_id,
        "group_id": group_id,
        "junction_key": junction_key,
        "candidate_count": candidate_count,
        "fold": fold,
    }


def _case_key(row: Mapping[str, Any]) -> str:
    return f"{row['family']}:{row['business_id']}"


def _stable_identifier(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _count_bin(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2_4"
    if value <= 8:
        return "5_8"
    if value <= 16:
        return "9_16"
    return "17_PLUS"


def _verify_outputs(manifest: Mapping[str, Any], strict_hashes: bool) -> None:
    for role, record in (manifest.get("outputs") or {}).items():
        path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
        if strict_hashes and sha256_file(path) != record["sha256"]:
            raise ValueError(f"input output hash mismatch: {role}")


def _verified_output(manifest: Mapping[str, Any], role: str) -> Path:
    record = (manifest.get("outputs") or {}).get(role)
    if not record:
        raise ValueError(f"manifest output missing: {role}")
    return normalize_runtime_path(str(record["path"])).resolve(strict=True)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            _write_jsonl_row(stream, row)


def _write_jsonl_row(stream: Any, row: Mapping[str, Any]) -> None:
    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


def _resolve_dir(path: Path | str) -> Path:
    resolved = normalize_runtime_path(path).resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


__all__ = ["build_scheme_a_p2_p1_dataset"]
