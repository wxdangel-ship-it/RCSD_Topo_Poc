from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SCHEME_A_P1_DATASET_SCHEMA,
    SchemeAP1DatasetConfig,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


DATASET_MANIFEST_VERSION = "p05-scheme-a-p1-dataset-manifest-v1"


def build_scheme_a_p1_dataset(config: SchemeAP1DatasetConfig) -> Path:
    candidate_root = _resolve_dir(config.candidate_run_root)
    baseline_root = _resolve_dir(config.scheme_a_baseline_run_root)
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    candidate_manifest_path = candidate_root / "scheme_a_p1_candidate_manifest.json"
    candidate_manifest = _read_json(candidate_manifest_path)
    if candidate_manifest.get("status") != "candidate_scope_passed":
        raise ValueError("candidate run is not passed")
    for field in (
        "truth_input_count",
        "truth_derived_candidate_count",
        "truth_feature_count",
        "absolute_coordinate_feature_count",
    ):
        if int(candidate_manifest.get(field, -1)) != 0:
            raise ValueError(f"candidate manifest leakage: {field}")
    _verify_output_manifest(candidate_manifest, config.strict_hashes)

    baseline_manifest_path = baseline_root / "scheme_a_manifest.json"
    baseline_manifest = _read_json(baseline_manifest_path)
    if baseline_manifest.get("status") != "passed":
        raise ValueError("Scheme A baseline is not passed")
    if int(baseline_manifest.get("counts", {}).get("case_count", 0)) != config.expected_case_count:
        raise ValueError("Scheme A baseline Case count mismatch")
    _verify_output_manifest(baseline_manifest, config.strict_hashes)

    candidates = _read_jsonl(candidate_root / "candidate_groups.jsonl")
    features = {
        row["candidate_id"]: row
        for row in _read_jsonl(candidate_root / "candidate_features.jsonl")
    }
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        key = (row["case_key"], row["object_type"], row["object_id"])
        groups[key].append(row)
    labels = _read_jsonl(baseline_root / "carrier_labels.jsonl")
    positive_objects = _fallback_positive_objects(
        _read_jsonl(baseline_root / "fallback_plans.jsonl")
    )

    feature_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    missing_groups: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []
    forbidden_hits: list[dict[str, str]] = []
    available_total = available_reachable = 0
    unsafe_total = unsafe_reachable = 0
    case_keys: set[str] = set()
    folds: set[int] = set()
    target_counts: Counter[str] = Counter()

    for label in labels:
        key = (label["case_key"], label["object_type"], label["object_id"])
        case_keys.add(label["case_key"])
        fold = int(label["fold"])
        folds.add(fold)
        rows = groups.get(key, [])
        if not rows:
            missing_groups.append(_label_audit(label, "candidate_group_missing"))
            continue
        matches = [row for row in rows if candidate_matches_label(row, label)]
        if label["available"]:
            available_total += 1
            available_reachable += int(len(matches) == 1)
        else:
            unsafe_total += 1
            unsafe_reachable += int(len(matches) == 1)
        if len(matches) != 1:
            unreachable.append(
                {
                    **_label_audit(label, "exact_candidate_not_unique"),
                    "match_count": len(matches),
                    "candidate_count": len(rows),
                }
            )
        truth_candidate_id = matches[0]["candidate_id"] if len(matches) == 1 else ""
        anomaly_target = (
            not bool(label["available"])
            or (label["case_key"], label["object_type"], label["object_id"])
            in positive_objects
        )
        label_rows.append(
            {
                "schema_version": SCHEME_A_P1_DATASET_SCHEMA,
                "case_key": label["case_key"],
                "object_type": label["object_type"],
                "object_id": label["object_id"],
                "group_id": rows[0]["group_id"],
                "truth_candidate_id": truth_candidate_id,
                "carrier_target": label["carrier_target"],
                "target_kind": label["target_kind"],
                "target_payload": label["target_payload"],
                "available": bool(label["available"]),
                "anomaly_target": anomaly_target,
                "label_weight": float(label["label_weight"]),
                "weight_role": label["weight_role"],
                "fold": fold,
                "label_only": True,
            }
        )
        target_counts[f"{label['object_type']}:{label['carrier_target']}"] += 1
        fold_rows.append(
            {
                "case_key": label["case_key"],
                "object_type": label["object_type"],
                "object_id": label["object_id"],
                "group_id": rows[0]["group_id"],
                "fold": fold,
            }
        )
        for candidate in rows:
            feature = features[candidate["candidate_id"]]
            hits = forbidden_feature_hits(feature, label)
            forbidden_hits.extend(
                {
                    "case_key": label["case_key"],
                    "candidate_id": candidate["candidate_id"],
                    "hit": hit,
                }
                for hit in hits
            )
            feature_rows.append(
                {
                    "schema_version": SCHEME_A_P1_DATASET_SCHEMA,
                    "case_key": candidate["case_key"],
                    "object_type": candidate["object_type"],
                    "object_id": candidate["object_id"],
                    "group_id": candidate["group_id"],
                    "candidate_id": candidate["candidate_id"],
                    "candidate_target": candidate["candidate_target"],
                    "target_kind": candidate["target_kind"],
                    "source_kinds": candidate["source_kinds"],
                    "object_tokens": feature["object_tokens"],
                    "candidate_tokens": feature["candidate_tokens"],
                    "context_tokens": feature["context_tokens"],
                    "numeric_features": feature["numeric_features"],
                    "hard_unsafe": bool(feature["hard_unsafe"]),
                    "fold": fold,
                    "feature_uses_truth": False,
                    "absolute_coordinate_feature_count": 0,
                }
            )

    available_recall = available_reachable / available_total if available_total else 0.0
    unsafe_recall = unsafe_reachable / unsafe_total if unsafe_total else 0.0
    gate_pass = (
        len(case_keys) == config.expected_case_count
        and len(folds) == config.expected_fold_count
        and available_recall == 1.0
        and not missing_groups
        and not unreachable
        and not forbidden_hits
    )
    feature_rows.sort(key=lambda row: (row["case_key"], row["group_id"], row["candidate_id"]))
    label_rows.sort(key=lambda row: (row["case_key"], row["group_id"]))
    fold_rows.sort(key=lambda row: (row["case_key"], row["group_id"]))
    feature_path = run_root / "feature_rows.jsonl"
    label_path = run_root / "labels.jsonl"
    fold_path = run_root / "grouped_folds.csv"
    _write_jsonl(feature_path, feature_rows)
    _write_jsonl(label_path, label_rows)
    write_csv(
        fold_path,
        fold_rows,
        ["case_key", "object_type", "object_id", "group_id", "fold"],
    )
    leakage_audit = {
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "forbidden_hits": forbidden_hits[:100],
        "fold_count": len(folds),
        "case_count": len(case_keys),
        "passed": not forbidden_hits and len(folds) == config.expected_fold_count,
    }
    reachability_audit = {
        "available_label_count": available_total,
        "available_reachable_count": available_reachable,
        "available_exact_reachability": available_recall,
        "unsafe_label_count": unsafe_total,
        "unsafe_reachable_count": unsafe_reachable,
        "unsafe_exact_reachability": unsafe_recall,
        "missing_groups": missing_groups,
        "unreachable": unreachable,
        "passed": available_recall == 1.0 and not missing_groups and not unreachable,
    }
    leakage_path = run_root / "leakage_audit.json"
    reachability_path = run_root / "reachability_audit.json"
    write_json(leakage_path, leakage_audit)
    write_json(reachability_path, reachability_audit)
    signatures = {
        "features": canonical_sha256(feature_rows),
        "labels": canonical_sha256(label_rows),
        "folds": canonical_sha256(fold_rows),
    }
    summary = {
        "schema_version": "p05-scheme-a-p1-dataset-summary-v1",
        "gate_pass": gate_pass,
        "decision": "CANDIDATE_GATE_PASS" if gate_pass else "P1_UPSTREAM_CANDIDATE_NO_GO",
        "case_count": len(case_keys),
        "fold_count": len(folds),
        "group_count": len(label_rows),
        "candidate_count": len(feature_rows),
        "target_counts": dict(sorted(target_counts.items())),
        "available_exact_reachability": available_recall,
        "unsafe_exact_reachability": unsafe_recall,
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "signatures": signatures,
    }
    summary_path = run_root / "scheme_a_p1_dataset_summary.json"
    write_json(summary_path, summary)
    outputs = {
        "features": output_record(feature_path),
        "labels": output_record(label_path),
        "folds": output_record(fold_path),
        "leakage_audit": output_record(leakage_path),
        "reachability_audit": output_record(reachability_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": DATASET_MANIFEST_VERSION,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_passed" if gate_pass else "candidate_gate_failed",
        "input_manifests": {
            "candidate": {
                "path": str(candidate_manifest_path.resolve()),
                "sha256": sha256_file(candidate_manifest_path),
            },
            "scheme_a_baseline": {
                "path": str(baseline_manifest_path.resolve()),
                "sha256": sha256_file(baseline_manifest_path),
            },
        },
        "truth_feature_count": len(forbidden_hits),
        "absolute_coordinate_feature_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "signatures": signatures,
        "outputs": outputs,
    }
    manifest_path = run_root / "scheme_a_p1_dataset_manifest.json"
    write_json(manifest_path, manifest)
    artifact_path = run_root / "artifact_manifest.json"
    write_json(
        artifact_path,
        {
            "schema_version": "p05-scheme-a-p1-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def candidate_matches_label(candidate: Mapping[str, Any], label: Mapping[str, Any]) -> bool:
    return (
        candidate.get("candidate_target") == label.get("carrier_target")
        and candidate.get("target_kind") == label.get("target_kind")
        and tuple(sorted(str(value) for value in candidate.get("target_payload") or []))
        == tuple(sorted(str(value) for value in label.get("target_payload") or []))
    )


def forbidden_feature_hits(
    feature: Mapping[str, Any], label: Mapping[str, Any]
) -> list[str]:
    tokens = [
        str(token)
        for field in ("object_tokens", "candidate_tokens", "context_tokens")
        for token in feature.get(field) or []
    ]
    hits: list[str] = []
    dynamic_values = {
        str(label.get("case_key") or ""),
        str(label.get("object_id") or ""),
        *(str(value) for value in label.get("target_payload") or []),
    }
    for token in tokens:
        folded = token.casefold()
        if any(word in folded for word in ("oracle", "label_only", "relation_status", "relation_reason")):
            hits.append(f"forbidden_token:{token}")
        for value in dynamic_values:
            if value and len(value) >= 5 and value in token:
                hits.append(f"dynamic_id:{token}")
    if feature.get("feature_uses_truth"):
        hits.append("feature_uses_truth")
    if int(feature.get("absolute_coordinate_feature_count", 0)):
        hits.append("absolute_coordinate")
    return sorted(set(hits))


def _fallback_positive_objects(rows: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for row in rows:
        case_key = str(row["case_key"])
        result.update((case_key, "SEGMENT", str(value)) for value in row.get("segment_ids") or [])
        result.update((case_key, "MOVEMENT", str(value)) for value in row.get("movement_ids") or [])
    return result


def _label_audit(label: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_key": label.get("case_key"),
        "object_type": label.get("object_type"),
        "object_id": label.get("object_id"),
        "carrier_target": label.get("carrier_target"),
        "target_kind": label.get("target_kind"),
        "target_payload": label.get("target_payload"),
        "available": label.get("available"),
        "reason": reason,
    }


def _verify_output_manifest(manifest: Mapping[str, Any], strict_hashes: bool) -> None:
    for role, record in (manifest.get("outputs") or {}).items():
        path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
        if strict_hashes and sha256_file(path) != record["sha256"]:
            raise ValueError(f"output hash mismatch: {role}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _resolve_dir(path: Path | str) -> Path:
    resolved = normalize_runtime_path(path).resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


__all__ = [
    "build_scheme_a_p1_dataset",
    "candidate_matches_label",
    "forbidden_feature_hits",
]
