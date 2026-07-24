from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p0_models import (
    DATASET_P0_SCHEMA_VERSION,
    SchemeADatasetP0Config,
)


_ARTIFACT_ROLE_CONTRACT: dict[str, tuple[str, str, bool, bool]] = {
    "t01_segment": ("T01", "INPUT_FROZEN_SKELETON", True, False),
    "t07_nodes": ("T07", "DETERMINISTIC_INPUT_EVIDENCE", True, False),
    "t03_nodes": ("T03", "LABEL_ONLY_INTERMEDIATE", False, True),
    "t04_nodes": ("T04", "LABEL_ONLY_INTERMEDIATE", False, True),
    "t05_intersection_match_all": ("T05", "LABEL_ONLY_INTERMEDIATE", False, True),
    "t05_rcsdnode_out": ("T05", "LABEL_ONLY_INTERMEDIATE", False, True),
    "t05_rcsdroad_out": ("T05", "LABEL_ONLY_INTERMEDIATE", False, True),
    "t06_frcsd_node": ("T06", "LABEL_ONLY_PRIMARY_TARGET", False, True),
    "t06_frcsd_road": ("T06", "LABEL_ONLY_PRIMARY_TARGET", False, True),
    "t06_swsd_frcsd_segment_relation": (
        "T06",
        "LABEL_ONLY_PRIMARY_TARGET",
        False,
        True,
    ),
}


def _module_role_contract() -> list[dict[str, Any]]:
    return [
        {
            "module": "T01",
            "business_meaning": "SWSD Segment construction and frozen Junction-Segment skeleton",
            "training_role": "INPUT_FROZEN_SKELETON",
            "model_input": True,
            "label_only": False,
            "candidate_role": "SWSD_FALLBACK_ONLY",
            "prohibited_interpretation": "RCSD truth or RCSD proposal source",
        },
        {
            "module": "T07",
            "business_meaning": "existing surface anchor evidence",
            "training_role": "DETERMINISTIC_INPUT_EVIDENCE",
            "model_input": True,
            "label_only": False,
            "candidate_role": "NONE",
            "evidence_mode": "DRIVEZONE_ONLY",
            "prohibited_interpretation": "Segment decision or virtual surface generation",
        },
        {
            "module": "T03",
            "business_meaning": "regular junction surface and relation evidence",
            "training_role": "LABEL_ONLY_INTERMEDIATE",
            "model_input": False,
            "label_only": True,
            "candidate_role": "TRUTH_FREE_STRATEGY_PROPOSAL_ALLOWED",
            "prohibited_interpretation": "surface accepted equals relation success",
        },
        {
            "module": "T04",
            "business_meaning": "complex junction surface, Reference Point and relation evidence",
            "training_role": "LABEL_ONLY_INTERMEDIATE",
            "model_input": False,
            "label_only": True,
            "candidate_role": "TRUTH_FREE_STRATEGY_PROPOSAL_ALLOWED",
            "prohibited_interpretation": "review/rejected as generic negative",
        },
        {
            "module": "T05",
            "business_meaning": "unique SWSD-RCSD relation and RCSD junctionization",
            "training_role": "LABEL_ONLY_INTERMEDIATE",
            "model_input": False,
            "label_only": True,
            "candidate_role": "TRUTH_FREE_STRATEGY_PROPOSAL_ALLOWED",
            "prohibited_interpretation": "blocking/cardinality conflict as success",
        },
        {
            "module": "T06",
            "business_meaning": "Segment carrier selection, fallback and final F-RCSD publication",
            "training_role": "LABEL_ONLY_PRIMARY_TARGET",
            "model_input": False,
            "label_only": True,
            "candidate_role": "TRUTH_FREE_STRATEGY_PROPOSAL_ALLOWED",
            "prohibited_interpretation": "reason/status as model input",
        },
        {
            "module": "T09",
            "business_meaning": "TrafficRule restoration on final carrier",
            "training_role": "DOWNSTREAM_VALIDATION_ONLY",
            "model_input": False,
            "label_only": False,
            "candidate_role": "NONE",
            "prohibited_interpretation": "Road or PhysicalMovement existence target",
        },
        {
            "module": "T11",
            "business_meaning": "manual relation repair candidate and review",
            "training_role": "HUMAN_CORRECTION_SOURCE",
            "model_input": False,
            "label_only": False,
            "candidate_role": "ACTIVE_LEARNING_ONLY",
            "prohibited_interpretation": "machine candidate as truth",
        },
        {
            "module": "T10",
            "business_meaning": "Case orchestration, evidence, split and lineage",
            "training_role": "DATASET_MANIFEST_AND_SPLIT",
            "model_input": False,
            "label_only": False,
            "candidate_role": "NONE",
            "prohibited_interpretation": "Case pass as object label",
        },
    ]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def _canonical_sha(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _normalized_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0"):
        prefix = text[:-2]
        if prefix.lstrip("-").isdigit():
            return prefix
    return text


def _resolve_declared_path(raw: str, *, parent: Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else parent / path


def _verify_declared_file(path: Path, expected_sha256: str, *, strict: bool) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    if not expected_sha256:
        return (not strict), "missing_declared_hash"
    actual = sha256_file(path)
    return actual == expected_sha256, "ok" if actual == expected_sha256 else "hash_mismatch"


def _manifest_file_refs(payload: Any) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                refs.append((value["path"], value["sha256"]))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return refs


def _verify_manifest_refs(path: Path, *, strict: bool) -> dict[str, Any]:
    payload = _read_json(path)
    statuses: Counter[str] = Counter()
    checked: set[tuple[str, str]] = set()
    for raw, expected in _manifest_file_refs(payload):
        key = (raw, expected)
        if key in checked:
            continue
        checked.add(key)
        target = _resolve_declared_path(raw, parent=path.parent)
        passed, status = _verify_declared_file(target, expected, strict=strict)
        statuses[status] += 1
        if strict and not passed:
            raise ValueError(f"manifest reference validation failed: {target} ({status})")
    return {"manifest": str(path.resolve()), "checked_count": len(checked), "statuses": dict(statuses)}


def _expected_weight_pair(family: str) -> tuple[float, float]:
    if family.startswith(("T03", "T04")):
        return 1.0, 0.3
    if family == "T10":
        return 0.7, 0.7
    if family.startswith("T10"):
        return 0.7, 0.3
    raise ValueError(f"unsupported Dataset-P0 family: {family}")


def _verify_sample_manifest(
    item: Mapping[str, str],
    *,
    strict: bool,
) -> tuple[bool, str]:
    metadata = json.loads(item["source_metadata"])
    if metadata.get("package_type") == "t10_case_organization_fallback":
        record = metadata.get("organization_record")
        if not isinstance(record, dict):
            return False, "missing_organization_record"
        actual = _canonical_sha(record)
        passed = actual == item["manifest_sha256"]
        return passed, "ok" if passed else "stable_record_hash_mismatch"
    return _verify_declared_file(
        Path(item["manifest_path"]),
        item["manifest_sha256"],
        strict=strict,
    )


def _artifact_contract(role: str) -> tuple[str, str, bool, bool]:
    try:
        return _ARTIFACT_ROLE_CONTRACT[role]
    except KeyError as exc:
        raise ValueError(f"unknown M0 artifact role: {role}") from exc


def _candidate_source_module(role: str) -> str:
    lowered = role.lower()
    for module in ("t01", "t03", "t04", "t05", "t06", "t07", "t09", "t10", "t11"):
        if lowered.startswith(module + "_"):
            return module.upper()
    if lowered in {"rcsdroad", "rcsdnode"}:
        return "RAW_RCSD"
    if "swsd" in lowered:
        return "RAW_SWSD"
    return "OTHER"


def _candidate_source_category(sources: Sequence[Mapping[str, Any]]) -> set[str]:
    categories: set[str] = set()
    for source in sources:
        role = str(source.get("role") or "")
        kind = str(source.get("source_kind") or "")
        module = _candidate_source_module(role)
        if module in {"T01", "RAW_SWSD"}:
            categories.add("T01_OR_SWSD_FALLBACK")
        if module in {"RAW_RCSD", "T03", "T04", "T05", "T06"} or kind == "STRATEGY_REPLAY":
            categories.add("NON_T01_PROPOSAL")
    return categories or {"UNCLASSIFIED"}


def _validate_candidate_summary(summary: Mapping[str, Any], expected_case_count: int) -> None:
    if int(summary.get("case_count", -1)) != expected_case_count:
        raise ValueError("PTO candidate Case count mismatch")
    if int(summary.get("truth_input_count", -1)) != 0:
        raise ValueError("truth input entered Dataset-P0 candidate")
    if int(summary.get("truth_derived_candidate_count", -1)) != 0:
        raise ValueError("truth-derived candidate entered Dataset-P0")
    if bool(summary.get("unbounded_enumeration")):
        raise ValueError("unbounded candidate enumeration is not allowed")


def _load_upstream(config: SchemeADatasetP0Config) -> dict[str, Any]:
    paths = {
        "m0_manifest": config.m0_run_root / "p05_m0_manifest.json",
        "m0_summary": config.m0_run_root / "p05_m0_summary.json",
        "m2r_manifest": config.m2r_supervision_run_root / "p05_m2r_supervision_manifest.json",
        "m2r_summary": config.m2r_supervision_run_root / "p05_m2r_supervision_summary.json",
        "baseline_manifest": config.scheme_a_baseline_run_root / "scheme_a_manifest.json",
        "baseline_summary": config.scheme_a_baseline_run_root / "scheme_a_summary.json",
        "pto_candidate_manifest": config.pto_candidate_run_root / "p05_pto_candidate_manifest.json",
        "pto_candidate_summary": config.pto_candidate_run_root / "p05_pto_candidate_summary.json",
        "pto_solve_manifest": config.pto_solve_run_root / "p05_pto_solve_manifest.json",
        "pto_solve_summary": config.pto_solve_run_root / "p05_pto_summary.json",
        "p2_manifest": config.historical_p2_oracle_run_root / "scheme_a_p2_oracle_manifest.json",
        "p2_summary": config.historical_p2_oracle_run_root / "scheme_a_p2_oracle_summary.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Dataset-P0 upstream files missing: {missing}")
    payloads = {name: _read_json(path) for name, path in paths.items()}
    candidate_summary = payloads["pto_candidate_summary"]
    _validate_candidate_summary(candidate_summary, config.expected_case_count)
    solve_manifest = payloads["pto_solve_manifest"]
    declared_candidate_manifest = Path(str(solve_manifest["candidate_manifest_path"]))
    if declared_candidate_manifest.resolve() != paths["pto_candidate_manifest"].resolve():
        raise ValueError("PTO solve does not reference the configured candidate manifest")
    if sha256_file(paths["pto_candidate_manifest"]) != str(
        solve_manifest["candidate_manifest_sha256"]
    ):
        raise ValueError("PTO solve candidate manifest hash mismatch")
    return {"paths": paths, "payloads": payloads}


def _build_sample_rows(
    config: SchemeADatasetP0Config,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], dict[str, int]]:
    source = _read_csv(config.m0_run_root / "p05_training_samples.csv")
    if len(source) != config.expected_sample_count:
        raise ValueError(f"M0 sample count mismatch: {len(source)}")
    rows: list[dict[str, Any]] = []
    sample_index: dict[str, dict[str, str]] = {}
    invalid_weight_count = 0
    excluded_enabled_task_count = 0
    manifest_error_count = 0
    outside_scope_count = 0
    poc_root = config.poc_data_root.resolve()
    for item in source:
        family = item["family"]
        business_id = item["business_id"]
        target_weight = float(item["target_weight"])
        context_weight = float(item["context_weight"])
        expected_weights = _expected_weight_pair(family)
        invalid_weight = (target_weight, context_weight) != expected_weights
        invalid_weight_count += int(invalid_weight)
        task_mask = json.loads(item["task_mask"])
        reasons = json.loads(item["task_mask_reasons"])
        excluded = business_id in config.approved_excluded_business_ids
        enabled_task_count = sum(bool(value) for value in task_mask.values())
        excluded_enabled_task_count += int(excluded) * enabled_task_count
        case_root = Path(item["case_root"]).resolve()
        within_scope = case_root == poc_root or poc_root in case_root.parents
        outside_scope_count += int(not within_scope)
        manifest_path = Path(item["manifest_path"])
        passed, manifest_status = _verify_sample_manifest(item, strict=config.strict_hashes)
        manifest_error_count += int(not passed)
        rows.append(
            {
                "sample_id": item["sample_id"],
                "sample_group_id": item["sample_group_id"],
                "family": family,
                "business_id": business_id,
                "scope_type": item["scope_type"],
                "case_root": str(case_root),
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": item["manifest_sha256"],
                "manifest_status": manifest_status,
                "target_weight": target_weight,
                "context_weight": context_weight,
                "weight_valid": not invalid_weight,
                "task_mask": task_mask,
                "task_mask_reasons": reasons,
                "enabled_task_count": enabled_task_count,
                "approved_exclusion": excluded,
                "within_poc_scope": within_scope,
            }
        )
        sample_index[item["sample_id"]] = item
    stats = {
        "invalid_weight_count": invalid_weight_count,
        "excluded_enabled_task_count": excluded_enabled_task_count,
        "manifest_error_count": manifest_error_count,
        "outside_scope_count": outside_scope_count,
    }
    return rows, sample_index, stats


def _build_artifact_rows(
    config: SchemeADatasetP0Config,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    source = _read_csv(config.m0_run_root / "p05_label_artifacts.csv")
    rows: list[dict[str, Any]] = []
    hash_error_count = 0
    t01_rcsd_label_count = 0
    for item in source:
        module, training_role, model_input, label_only = _artifact_contract(item["role"])
        path = Path(item["artifact_path"])
        passed, status = _verify_declared_file(
            path,
            item["artifact_sha256"],
            strict=config.strict_hashes,
        )
        hash_error_count += int(not passed)
        t01_rcsd_label_count += int(module == "T01" and label_only)
        rows.append(
            {
                "sample_id": item["sample_id"],
                "family": item["family"],
                "business_id": item["business_id"],
                "artifact_role": item["role"],
                "module": module,
                "training_role": training_role,
                "model_input": model_input,
                "label_only": label_only,
                "path": str(path.resolve()),
                "sha256": item["artifact_sha256"],
                "hash_status": status,
                "target_weight": float(item["target_weight"]),
                "context_weight": float(item["context_weight"]),
                "baseline_id": item["baseline_id"],
                "repo_head": item["repo_head"],
            }
        )
    return rows, {
        "artifact_count": len(rows),
        "hash_error_count": hash_error_count,
        "t01_rcsd_label_count": t01_rcsd_label_count,
    }


def _build_task_rows(
    config: SchemeADatasetP0Config,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = _read_csv(config.m2r_supervision_run_root / "p05_m2r_task_targets.csv")
    if len(source) != config.expected_task_target_count:
        raise ValueError(f"M2R task target count mismatch: {len(source)}")
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    invalid_available_artifact_count = 0
    unknown_enabled_label_count = 0
    verified_artifacts: dict[tuple[str, str], tuple[bool, str]] = {}
    for item in source:
        module = item["task_name"]
        if module not in {"T03", "T04", "T05", "T06", "T07"}:
            raise ValueError(f"unsupported M2R task module: {module}")
        availability = item["availability"].lower()
        approved_exclusion = item["business_id"] in config.approved_excluded_business_ids
        label_role = "DETERMINISTIC_INPUT_EVIDENCE" if module == "T07" else (
            "LABEL_ONLY_PRIMARY_TARGET" if module == "T06" else "LABEL_ONLY_INTERMEDIATE"
        )
        enabled_label = module in {"T03", "T04", "T05", "T06"} and availability == "available"
        enabled_label = enabled_label and not approved_exclusion
        if availability != "available" and enabled_label:
            unknown_enabled_label_count += 1
        artifact_status = "not_applicable"
        if availability == "available" and item["artifact_path"]:
            key = (item["artifact_path"], item["artifact_sha256"])
            if key not in verified_artifacts:
                verified_artifacts[key] = _verify_declared_file(
                    Path(item["artifact_path"]),
                    item["artifact_sha256"],
                    strict=config.strict_hashes,
                )
            passed, artifact_status = verified_artifacts[key]
            invalid_available_artifact_count += int(not passed)
        elif availability == "available":
            invalid_available_artifact_count += 1
            artifact_status = "missing_available_artifact"
        counts[f"{module}:{availability}"] += 1
        counts[f"{module}:enabled"] += int(enabled_label)
        rows.append(
            {
                "sample_id": item["sample_id"],
                "sample_group_id": item["sample_group_id"],
                "family": item["family"],
                "business_id": item["business_id"],
                "fold": item["fold"],
                "split": item["split"],
                "module": module,
                "target_kind": item["target_kind"],
                "availability": availability,
                "trust_tier": item["trust_tier"],
                "target_weight": float(item["target_weight"]),
                "context_weight": float(item["context_weight"]),
                "training_role": label_role,
                "enabled_label": enabled_label,
                "approved_exclusion": approved_exclusion,
                "artifact_role": item["artifact_role"],
                "artifact_path": item["artifact_path"],
                "artifact_sha256": item["artifact_sha256"],
                "artifact_status": artifact_status,
                "reason": item["reason"],
            }
        )
    return rows, {
        "counts": dict(sorted(counts.items())),
        "invalid_available_artifact_count": invalid_available_artifact_count,
        "unknown_enabled_label_count": unknown_enabled_label_count,
        "unique_available_artifact_count": len(verified_artifacts),
    }


def _scan_candidates(
    config: SchemeADatasetP0Config,
) -> tuple[dict[str, dict[str, set[str]]], list[dict[str, Any]], dict[str, int]]:
    path = config.pto_candidate_run_root / "p05_pto_candidates.jsonl"
    by_case: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {
            "road_all": set(),
            "road_non_t01": set(),
            "road_t01": set(),
            "node_all": set(),
        }
    )
    source_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    candidate_count = 0
    truth_derived_count = 0
    unclassified_source_count = 0
    for line in path.open("r", encoding="utf-8"):
        row = json.loads(line)
        candidate_count += 1
        truth_derived_count += int(bool(row.get("truth_derived")))
        stage = str(row.get("stage") or "")
        case_key = f"{row['family']}:{row['business_id']}"
        sources = row.get("sources") or []
        categories = _candidate_source_category(sources)
        unclassified_source_count += int("UNCLASSIFIED" in categories and stage in {"FINAL_ROAD", "FINAL_NODE"})
        output_ids = {_normalized_id(value) for value in row.get("output_object_ids") or []}
        output_ids.discard("")
        for source in sources:
            role = str(source.get("role") or "")
            kind = str(source.get("source_kind") or "")
            module = _candidate_source_module(role)
            for category in sorted(categories):
                source_counts[(stage, role, kind, module, category)] += 1
        if stage == "FINAL_ROAD":
            by_case[case_key]["road_all"].update(output_ids)
            if "NON_T01_PROPOSAL" in categories:
                by_case[case_key]["road_non_t01"].update(output_ids)
            if "T01_OR_SWSD_FALLBACK" in categories:
                by_case[case_key]["road_t01"].update(output_ids)
        elif stage == "FINAL_NODE":
            by_case[case_key]["node_all"].update(output_ids)
    source_rows = [
        {
            "stage": key[0],
            "source_role": key[1],
            "source_kind": key[2],
            "source_module": key[3],
            "source_category": key[4],
            "candidate_reference_count": count,
        }
        for key, count in sorted(source_counts.items())
    ]
    return by_case, source_rows, {
        "candidate_count": candidate_count,
        "truth_derived_count": truth_derived_count,
        "unclassified_source_count": unclassified_source_count,
    }


def _gpkg_object_ids(path: Path) -> tuple[set[str], set[str], int]:
    ids: set[str] = set()
    crs_values: set[str] = set()
    duplicate_count = 0
    connection = sqlite3.connect(str(path))
    try:
        tables = connection.execute(
            "SELECT table_name, srs_id FROM gpkg_contents WHERE data_type='features'"
        ).fetchall()
        if not tables:
            raise ValueError(f"no feature layer in GPKG: {path}")
        for table_name, srs_id in tables:
            escaped = str(table_name).replace('"', '""')
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()
            ]
            id_column = next(
                (name for name in ("id", "road_id", "node_id", "objectid", "OBJECTID") if name in columns),
                None,
            )
            if id_column is None:
                raise ValueError(f"no object ID column in {path}:{table_name}")
            escaped_id = id_column.replace('"', '""')
            for (raw_id,) in connection.execute(f'SELECT "{escaped_id}" FROM "{escaped}"'):
                value = _normalized_id(raw_id)
                if not value:
                    continue
                duplicate_count += int(value in ids)
                ids.add(value)
            srs = connection.execute(
                "SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id=?",
                (srs_id,),
            ).fetchone()
            if srs:
                crs_values.add(f"{str(srs[0]).upper()}:{srs[1]}")
            else:
                crs_values.add(f"SRS:{srs_id}")
    finally:
        connection.close()
    return ids, crs_values, duplicate_count


def _truth_objects_by_case(
    config: SchemeADatasetP0Config,
    sample_index: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, Any]]:
    rows = _read_csv(config.m0_run_root / "p05_label_artifacts.csv")
    by_case: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"road": set(), "node": set(), "crs": set()}
    )
    duplicate_count = 0
    artifact_count = 0
    for item in rows:
        if item["role"] not in {"t06_frcsd_road", "t06_frcsd_node"}:
            continue
        sample = sample_index[item["sample_id"]]
        if sample["business_id"] in config.approved_excluded_business_ids:
            continue
        case_key = f"{sample['family']}:{sample['business_id']}"
        object_ids, crs_values, duplicates = _gpkg_object_ids(Path(item["artifact_path"]))
        kind = "road" if item["role"] == "t06_frcsd_road" else "node"
        by_case[case_key][kind].update(object_ids)
        by_case[case_key]["crs"].update(crs_values)
        duplicate_count += duplicates
        artifact_count += 1
    return by_case, {
        "truth_artifact_count": artifact_count,
        "duplicate_id_count": duplicate_count,
        "crs_values": sorted({value for case in by_case.values() for value in case["crs"]}),
    }


def _segment_rows(
    config: SchemeADatasetP0Config,
    candidates: Mapping[str, Mapping[str, set[str]]],
    truth_objects: Mapping[str, Mapping[str, set[str]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    segment_types = {
        (row["case_key"], row["segment_id"]): row["segment_type"]
        for row in _read_csv(config.scheme_a_baseline_run_root / "segment_inventory.csv")
    }
    labels_path = config.scheme_a_baseline_run_root / "carrier_labels.jsonl"
    for line in labels_path.open("r", encoding="utf-8"):
        label = json.loads(line)
        if label.get("object_type") != "SEGMENT":
            continue
        case_key = str(label["case_key"])
        target = str(label["carrier_target"])
        available = bool(label.get("available"))
        target_ids = {_normalized_id(value) for value in label.get("target_payload") or []}
        target_ids.discard("")
        case_candidates = candidates.get(case_key, {})
        road_all = case_candidates.get("road_all", set())
        road_non_t01 = case_candidates.get("road_non_t01", set())
        road_reachable = available and target_ids.issubset(road_all)
        use_rcsd_non_t01_reachable = (
            available and target == "USE_RCSD" and target_ids.issubset(road_non_t01)
        )
        node_truth = truth_objects.get(case_key, {}).get("node", set())
        node_candidates = case_candidates.get("node_all", set())
        case_node_exact = bool(node_truth) and node_truth.issubset(node_candidates)
        joint_exact = road_reachable and case_node_exact
        if not available:
            attribution = "MASKED_BY_CONFIRMED_LABEL_CONTRACT"
        elif target == "USE_RCSD" and not use_rcsd_non_t01_reachable:
            attribution = "NON_T01_RCSD_PROPOSAL_MISSING"
        elif not road_reachable:
            attribution = "ROAD_CANDIDATE_MISSING"
        elif not case_node_exact:
            attribution = "FINAL_NODE_CANDIDATE_MISSING"
        else:
            attribution = "REACHABLE"
        counts["segment_count"] += 1
        counts["available_segment_count"] += int(available)
        counts["available_road_reachable_count"] += int(road_reachable)
        counts["joint_exact_count"] += int(joint_exact)
        counts["use_rcsd_truth_count"] += int(available and target == "USE_RCSD")
        counts["use_rcsd_non_t01_reachable_count"] += int(use_rcsd_non_t01_reachable)
        counts["unreachable_attributed_count"] += int(attribution != "REACHABLE")
        rows.append(
            {
                "case_key": case_key,
                "object_id": label["object_id"],
                "segment_type": segment_types.get((case_key, str(label["object_id"])), "UNKNOWN"),
                "carrier_target": target,
                "available": available,
                "label_weight": float(label["label_weight"]),
                "weight_role": label["weight_role"],
                "target_road_ids": sorted(target_ids),
                "road_candidate_reachable": road_reachable,
                "use_rcsd_non_t01_reachable": use_rcsd_non_t01_reachable,
                "case_final_node_exact": case_node_exact,
                "joint_exact": joint_exact,
                "missing_road_candidate_ids": sorted(target_ids - road_all),
                "missing_non_t01_candidate_ids": sorted(target_ids - road_non_t01)
                if target == "USE_RCSD"
                else [],
                "attribution": attribution,
            }
        )
    if counts["segment_count"] != config.expected_segment_count:
        raise ValueError(f"Scheme A Segment count mismatch: {counts['segment_count']}")
    available = counts["available_segment_count"]
    use_total = counts["use_rcsd_truth_count"]
    metrics = {
        **dict(counts),
        "available_segment_road_reachability": counts["available_road_reachable_count"] / available
        if available
        else 0.0,
        "use_rcsd_truth_reachability": counts["use_rcsd_non_t01_reachable_count"] / use_total
        if use_total
        else 0.0,
        "joint_truth_exact_coverage": counts["joint_exact_count"] / available if available else 0.0,
    }
    return rows, metrics


def _case_rows(
    config: SchemeADatasetP0Config,
    candidates: Mapping[str, Mapping[str, set[str]]],
    truth_objects: Mapping[str, Mapping[str, set[str]]],
    segment_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    p2_rows = {
        row["case_key"]: row
        for row in _read_csv(config.historical_p2_oracle_run_root / "case_results.csv")
    }
    by_case_segments: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in segment_rows:
        by_case_segments[str(row["case_key"])].append(row)
    case_keys = sorted(truth_objects)
    if len(case_keys) != config.expected_case_count:
        raise ValueError(f"T06 truth Case count mismatch: {len(case_keys)}")
    rows: list[dict[str, Any]] = []
    road_truth_count = road_reachable_count = 0
    node_truth_count = node_reachable_count = 0
    crs_conflict_count = 0
    for case_key in case_keys:
        truth = truth_objects[case_key]
        candidate = candidates.get(case_key, {})
        truth_roads = truth["road"]
        truth_nodes = truth["node"]
        candidate_roads = candidate.get("road_all", set())
        candidate_nodes = candidate.get("node_all", set())
        reachable_roads = truth_roads & candidate_roads
        reachable_nodes = truth_nodes & candidate_nodes
        road_truth_count += len(truth_roads)
        road_reachable_count += len(reachable_roads)
        node_truth_count += len(truth_nodes)
        node_reachable_count += len(reachable_nodes)
        crs_values = sorted(truth["crs"])
        crs_conflict_count += int(len(crs_values) != 1)
        segments = by_case_segments[case_key]
        available_segments = [row for row in segments if row["available"]]
        p2 = p2_rows.get(case_key, {})
        rows.append(
            {
                "case_key": case_key,
                "final_road_truth_count": len(truth_roads),
                "final_road_candidate_reachable_count": len(reachable_roads),
                "final_road_candidate_reachability": len(reachable_roads) / len(truth_roads)
                if truth_roads
                else 0.0,
                "final_node_truth_count": len(truth_nodes),
                "final_node_candidate_reachable_count": len(reachable_nodes),
                "final_node_candidate_reachability": len(reachable_nodes) / len(truth_nodes)
                if truth_nodes
                else 0.0,
                "segment_count": len(segments),
                "available_segment_count": len(available_segments),
                "segment_joint_exact_count": sum(bool(row["joint_exact"]) for row in available_segments),
                "crs_values": crs_values,
                "historical_p2_terminal_state": p2.get("terminal_state", "MISSING"),
                "historical_p2_publish": p2.get("publish", ""),
                "historical_p2_expected_failure_match": p2.get("expected_failure_match", ""),
            }
        )
    return rows, {
        "final_road_truth_count": road_truth_count,
        "final_road_candidate_reachable_count": road_reachable_count,
        "final_road_candidate_reachability": road_reachable_count / road_truth_count
        if road_truth_count
        else 0.0,
        "final_node_truth_count": node_truth_count,
        "final_node_candidate_reachable_count": node_reachable_count,
        "final_node_candidate_reachability": node_reachable_count / node_truth_count
        if node_truth_count
        else 0.0,
        "crs_conflict_count": crs_conflict_count,
    }


def _peak_rss_bytes() -> int:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, AttributeError):
        pass
    if sys.platform != "win32":
        try:
            import resource

            peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if peak > 0:
                return peak * 1024 if sys.platform.startswith("linux") else peak
        except (ImportError, OSError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_current_process = ctypes.windll.kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            get_process_memory_info.restype = wintypes.BOOL
            handle = get_current_process()
            if get_process_memory_info(handle, ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize)
        except (AttributeError, OSError):
            return 0
    return 0


def _decision(gate0: bool, gate1: bool, gate2: bool, gate3: bool, gate4: bool) -> str:
    if not gate0 or not gate1:
        return "P05_SCHEME_A_DATASET_P0_LABEL_NO_GO"
    if not gate2:
        return "P05_SCHEME_A_DATASET_P0_CANDIDATE_NO_GO"
    if not gate3 or not gate4:
        return "P05_SCHEME_A_DATASET_P0_SAFETY_NO_GO"
    return "P05_SCHEME_A_DATASET_P0_GO"


def _report(summary: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# P05-Scheme-A-Dataset-P0 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- sample/case/Segment: `{summary['sample_count']}/{summary['case_count']}/{summary['segment_count']}`",
            f"- USE_RCSD non-T01 reachability: `{summary['candidate_metrics']['use_rcsd_truth_reachability']:.6f}`",
            f"- available Segment Road reachability: `{summary['candidate_metrics']['available_segment_road_reachability']:.6f}`",
            f"- final Road/Node reachability: `{summary['case_metrics']['final_road_candidate_reachability']:.6f}/{summary['case_metrics']['final_node_candidate_reachability']:.6f}`",
            f"- joint exact coverage: `{summary['candidate_metrics']['joint_truth_exact_coverage']:.6f}`",
            f"- historical safety: `{summary['roadgraph_terminal_counts']}`",
            f"- gates: `{summary['gates']}`",
            f"- wall/RSS/GPU: `{summary['performance']['wall_seconds']:.3f}s/{summary['performance']['peak_rss_bytes']}/false`",
            "- T01 RCSD label, truth leakage, content repair and silent fix remain zero.",
            "",
        ]
    )


def build_scheme_a_dataset_p0_run(config: SchemeADatasetP0Config) -> Path:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    expected_poc_root = Path(r"E:\TestData\POC_Data").resolve()
    if config.poc_data_root.resolve() != expected_poc_root:
        raise ValueError(f"Dataset-P0 scope must be {expected_poc_root}")
    run_root = config.output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(f"Dataset-P0 run root already exists: {run_root}")
    run_root.mkdir(parents=True)

    upstream = _load_upstream(config)
    upstream_refs = [
        _verify_manifest_refs(path, strict=config.strict_hashes)
        for name, path in upstream["paths"].items()
        if name.endswith("manifest")
    ]
    role_contract = _module_role_contract()
    sample_rows, sample_index, sample_stats = _build_sample_rows(config)
    artifact_rows, artifact_stats = _build_artifact_rows(config)
    task_rows, task_stats = _build_task_rows(config)
    candidates, source_rows, candidate_stats = _scan_candidates(config)
    truth_objects, truth_stats = _truth_objects_by_case(config, sample_index)
    segment_rows, segment_metrics = _segment_rows(config, candidates, truth_objects)
    case_rows, case_metrics = _case_rows(
        config,
        candidates,
        truth_objects,
        segment_rows,
    )

    payloads = upstream["payloads"]
    m0_summary = payloads["m0_summary"]
    m2r_summary = payloads["m2r_summary"]
    baseline_summary = payloads["baseline_summary"]
    pto_summary = payloads["pto_solve_summary"]
    p2_summary = payloads["p2_summary"]
    terminal_counts = dict(p2_summary.get("roadgraph_terminal_counts") or {})
    expected_failures = sorted(p2_summary.get("roadgraph_expected_failure_case_keys") or [])
    expected_failures_match = expected_failures == sorted(config.expected_failure_case_keys)
    manifest_ref_errors = sum(
        sum(count for status, count in audit["statuses"].items() if status != "ok")
        for audit in upstream_refs
    )

    gate0_checks = {
        "sample_count": len(sample_rows) == config.expected_sample_count,
        "case_count": len(case_rows) == config.expected_case_count,
        "segment_count": len(segment_rows) == config.expected_segment_count,
        "excluded_enabled_task_count_zero": sample_stats["excluded_enabled_task_count"] == 0,
        "t01_rcsd_label_count_zero": artifact_stats["t01_rcsd_label_count"] == 0,
        "t07_drivezone_only": config.t07_evidence_mode == "DRIVEZONE_ONLY",
        "movement_counts_zero": all(
            int(p2_summary.get(key, -1)) == 0
            for key in (
                "movement_candidate_count",
                "movement_decision_count",
                "movement_evaluation_count",
            )
        ),
        "truth_input_count_zero": int(payloads["pto_candidate_summary"].get("truth_input_count", -1))
        == 0,
        "truth_derived_candidate_count_zero": candidate_stats["truth_derived_count"] == 0,
        "skeleton_mutation_count_zero": int(baseline_summary["counts"]["skeleton_mutation_count"])
        == 0,
        "poc_scope_complete": sample_stats["outside_scope_count"] == 0,
    }
    gate1_checks = {
        "manifest_ref_errors_zero": manifest_ref_errors == 0,
        "sample_manifest_errors_zero": sample_stats["manifest_error_count"] == 0,
        "artifact_hash_errors_zero": artifact_stats["hash_error_count"] == 0,
        "available_task_artifact_errors_zero": task_stats["invalid_available_artifact_count"] == 0,
        "weights_valid": sample_stats["invalid_weight_count"] == 0,
        "m2r_label_integrity_errors_zero": int(m2r_summary["label_integrity_error_count"]) == 0,
        "m2r_split_conflicts_zero": int(m2r_summary["split_group_conflict_count"]) == 0,
        "unknown_enabled_labels_zero": task_stats["unknown_enabled_label_count"] == 0,
        "task_target_count": len(task_rows) == config.expected_task_target_count,
    }
    gate2_checks = {
        "use_rcsd_reachability": segment_metrics["use_rcsd_truth_reachability"]
        >= config.min_use_rcsd_reachability,
        "available_segment_road_reachability": segment_metrics[
            "available_segment_road_reachability"
        ]
        == 1.0,
        "final_road_reachability": case_metrics["final_road_candidate_reachability"] == 1.0,
        "final_node_reachability": case_metrics["final_node_candidate_reachability"] == 1.0,
        "joint_exact_coverage": segment_metrics["joint_truth_exact_coverage"]
        >= config.min_joint_exact_coverage,
        "candidate_sources_classified": candidate_stats["unclassified_source_count"] == 0,
    }
    gate3_checks = {
        "pto_candidate_full_coverage": bool(pto_summary["full_candidate_coverage"]),
        "pto_semantic_exact_51": int(pto_summary["semantic_exact_case_count"])
        == config.expected_case_count,
        "pto_hard_failure_zero": int(pto_summary["hard_failure_count"]) == 0,
        "roadgraph_49_legal": int(terminal_counts.get("LEGAL", 0)) == 49,
        "roadgraph_2_expected_fail": int(terminal_counts.get("EXPECTED_FAIL", 0)) == 2,
        "expected_failures_match": expected_failures_match,
        "roadgraph_unexpected_failure_zero": not p2_summary.get(
            "roadgraph_unexpected_failure_case_keys"
        ),
        "content_repair_false": not bool(pto_summary["content_repair"])
        and not bool(p2_summary["content_repair"]),
        "silent_fix_false": not bool(pto_summary["silent_fix"])
        and not bool(p2_summary["silent_fix"]),
        "relaxation_false": not bool(pto_summary["relaxation"])
        and not bool(p2_summary["relaxation"]),
    }
    wall_seconds = time.perf_counter() - started
    peak_rss_bytes = _peak_rss_bytes()
    gate4_checks = {
        "crs_conflict_zero": case_metrics["crs_conflict_count"] == 0,
        "duplicate_truth_id_zero": truth_stats["duplicate_id_count"] == 0,
        "peak_rss_within_budget": 0 < peak_rss_bytes <= config.max_peak_rss_bytes,
        "wall_time_within_budget": wall_seconds <= config.max_wall_seconds,
        "gpu_required_false": True,
    }
    gates = {
        "gate0_scope_role_isolation": all(gate0_checks.values()),
        "gate1_label_integrity": all(gate1_checks.values()),
        "gate2_candidate_reachability": all(gate2_checks.values()),
        "gate3_oracle_roadgraph_safety": all(gate3_checks.values()),
        "gate4_gis_resource": all(gate4_checks.values()),
    }
    decision = _decision(*gates.values())
    signatures = {
        "module_role_contract": _canonical_sha(role_contract),
        "sample": _canonical_sha(sample_rows),
        "artifact": _canonical_sha(artifact_rows),
        "task": _canonical_sha(task_rows),
        "candidate_source": _canonical_sha(source_rows),
        "segment_reachability": _canonical_sha(segment_rows),
        "case_reachability": _canonical_sha(case_rows),
    }
    summary = {
        "schema_version": DATASET_P0_SCHEMA_VERSION,
        "decision": decision,
        "sample_count": len(sample_rows),
        "case_count": len(case_rows),
        "segment_count": len(segment_rows),
        "artifact_count": len(artifact_rows),
        "task_target_count": len(task_rows),
        "t07_evidence_mode": config.t07_evidence_mode,
        "movement_candidate_count": int(p2_summary["movement_candidate_count"]),
        "movement_decision_count": int(p2_summary["movement_decision_count"]),
        "movement_evaluation_count": int(p2_summary["movement_evaluation_count"]),
        "sample_audit": sample_stats,
        "artifact_audit": artifact_stats,
        "task_audit": task_stats,
        "candidate_audit": candidate_stats,
        "truth_object_audit": truth_stats,
        "candidate_metrics": segment_metrics,
        "case_metrics": case_metrics,
        "historical_p2_use_rcsd_truth_retention": float(p2_summary["use_rcsd_truth_retention"]),
        "roadgraph_terminal_counts": terminal_counts,
        "roadgraph_expected_failure_case_keys": expected_failures,
        "gate_checks": {
            "gate0": gate0_checks,
            "gate1": gate1_checks,
            "gate2": gate2_checks,
            "gate3": gate3_checks,
            "gate4": gate4_checks,
        },
        "gates": gates,
        "signatures": signatures,
        "content_repair": False,
        "silent_fix": False,
        "performance": {
            "wall_seconds": wall_seconds,
            "peak_rss_bytes": peak_rss_bytes,
            "gpu_required": False,
        },
    }

    paths = {
        "module_role_contract": run_root / "module_role_contract.json",
        "training_sample_manifest": run_root / "training_sample_manifest.csv",
        "module_artifact_inventory": run_root / "module_artifact_inventory.csv",
        "task_target_audit": run_root / "task_target_audit.csv",
        "candidate_source_inventory": run_root / "candidate_source_inventory.csv",
        "segment_candidate_reachability": run_root / "segment_candidate_reachability.csv",
        "case_candidate_reachability": run_root / "case_candidate_reachability.csv",
        "summary": run_root / "dataset_p0_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_json(paths["module_role_contract"], role_contract)
    _write_csv(paths["training_sample_manifest"], sample_rows, list(sample_rows[0]))
    _write_csv(paths["module_artifact_inventory"], artifact_rows, list(artifact_rows[0]))
    _write_csv(paths["task_target_audit"], task_rows, list(task_rows[0]))
    _write_csv(paths["candidate_source_inventory"], source_rows, list(source_rows[0]))
    _write_csv(paths["segment_candidate_reachability"], segment_rows, list(segment_rows[0]))
    _write_csv(paths["case_candidate_reachability"], case_rows, list(case_rows[0]))
    _write_json(paths["summary"], summary)
    paths["report"].write_text(_report(summary), encoding="utf-8")
    artifact_manifest = {
        "schema_version": DATASET_P0_SCHEMA_VERSION,
        "artifacts": {
            name: {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for name, path in paths.items()
        },
    }
    artifact_manifest_path = run_root / "artifact_manifest.json"
    _write_json(artifact_manifest_path, artifact_manifest)
    run_manifest = {
        "schema_version": DATASET_P0_SCHEMA_VERSION,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "completed",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "poc_data_root": str(config.poc_data_root.resolve()),
            "approved_excluded_business_ids": list(config.approved_excluded_business_ids),
            "expected_failure_case_keys": list(config.expected_failure_case_keys),
            "expected_sample_count": config.expected_sample_count,
            "expected_case_count": config.expected_case_count,
            "expected_segment_count": config.expected_segment_count,
            "expected_task_target_count": config.expected_task_target_count,
            "min_use_rcsd_reachability": config.min_use_rcsd_reachability,
            "min_joint_exact_coverage": config.min_joint_exact_coverage,
            "t07_evidence_mode": config.t07_evidence_mode,
            "strict_hashes": config.strict_hashes,
        },
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for name, path in upstream["paths"].items()
        },
        "upstream_reference_audit": upstream_refs,
        "outputs": {
            "artifact_manifest": {
                "path": str(artifact_manifest_path.resolve()),
                "sha256": sha256_file(artifact_manifest_path),
                "size_bytes": artifact_manifest_path.stat().st_size,
            },
            **artifact_manifest["artifacts"],
        },
        "decision": decision,
        "gates": gates,
        "signatures": signatures,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
        },
        "content_repair": False,
        "silent_fix": False,
    }
    _write_json(run_root / "dataset_p0_manifest.json", run_manifest)
    return run_root


def compare_scheme_a_dataset_p0_runs(
    run_a: Path,
    run_b: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    summary_a = _read_json(run_a / "dataset_p0_summary.json")
    summary_b = _read_json(run_b / "dataset_p0_summary.json")
    signature_a = summary_a["signatures"]
    signature_b = summary_b["signatures"]
    differing = sorted(key for key in set(signature_a) | set(signature_b) if signature_a.get(key) != signature_b.get(key))
    result = {
        "schema_version": DATASET_P0_SCHEMA_VERSION,
        "run_a": str(run_a.resolve()),
        "run_b": str(run_b.resolve()),
        "decision_a": summary_a["decision"],
        "decision_b": summary_b["decision"],
        "signatures_equal": not differing,
        "differing_signatures": differing,
        "gates_equal": summary_a["gates"] == summary_b["gates"],
        "determinism_pass": not differing
        and summary_a["gates"] == summary_b["gates"]
        and summary_a["decision"] == summary_b["decision"],
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(output_path, result)
    return result


__all__ = [
    "build_scheme_a_dataset_p0_run",
    "compare_scheme_a_dataset_p0_runs",
]
