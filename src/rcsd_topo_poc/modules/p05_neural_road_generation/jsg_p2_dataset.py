from __future__ import annotations

import csv
import importlib.metadata
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import _rss_bytes
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_features import (
    forbidden_feature_hits,
    jsg_feature_tokens,
    roadgraph_feature_tokens,
    v0_cost,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    JSGP2DatasetConfig,
    JSG_P2_DATASET_SCHEMA_VERSION,
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield row


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _verified_output(
    outputs: Mapping[str, Any], role: str, *, strict_hashes: bool
) -> Path:
    record = dict(outputs.get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"artifact hash mismatch: {role}")
    return path


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("numpy", "fiona", "shapely", "pyproj"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def _load_labels(path: Path) -> dict[tuple[str, str], bool]:
    labels: dict[tuple[str, str], bool] = {}
    for row in _read_jsonl(path):
        candidate_id = str(row["candidate_id"])
        case_key = str(row.get("case_key") or "")
        if not case_key:
            case_key = f"{row['family']}:{row['business_id']}"
        key = (case_key, candidate_id)
        value = bool(row["truth_equivalent"])
        if key in labels and labels[key] != value:
            raise ValueError(f"conflicting candidate label: {case_key}/{candidate_id}")
        labels[key] = value
    return labels


def _load_group_options(path: Path, *, jsg: bool) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for row in _read_csv(path):
        case_key = (
            str(row["case_key"])
            if jsg
            else f"{row['family']}:{row['business_id']}"
        )
        key = (case_key, str(row["group_id"] if jsg else row["component_id"]))
        value = int(row["option_count"] if jsg else row["candidate_count"])
        if key in result and result[key] != value:
            raise ValueError(f"conflicting group option count: {key}")
        result[key] = value
    return result


def _is_target_candidate(candidate: Mapping[str, Any], business_id: str) -> bool:
    identity_values = {
        str(candidate.get("object_key") or ""),
        str(candidate.get("base_object_id") or ""),
    }
    identity_values.update(str(value) for value in candidate.get("output_object_ids") or [])
    payload = dict(candidate.get("payload") or {})
    for key in ("segment_id", "connector_id", "junction_id"):
        identity_values.add(str(payload.get(key) or ""))
    return business_id in identity_values


def _load_scope_contract(
    config: JSGP2DatasetConfig,
) -> tuple[Path, dict[str, dict[str, Any]], dict[str, int]]:
    m0_root = normalize_runtime_path(config.m0_run_root).resolve(strict=True)
    manifest_path = m0_root / "p05_m0_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m0-manifest-v1":
        raise ValueError("invalid M0 manifest")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M0 manifest must declare silent_fix=false")
    outputs = dict(manifest.get("outputs") or {})
    samples_path = _verified_output(outputs, "samples", strict_hashes=config.strict_hashes)
    split_path = _verified_output(outputs, "split", strict_hashes=config.strict_hashes)
    samples: dict[str, dict[str, Any]] = {}
    sample_id_to_scope: dict[str, str] = {}
    for row in _read_csv(samples_path):
        if str(row.get("scope_type") or "") not in {"t10_case", "t10_segment"}:
            continue
        case_key = f"{row['family']}:{row['business_id']}"
        if case_key in samples:
            raise ValueError(f"duplicate M0 RoadGraph scope: {case_key}")
        samples[case_key] = {
            **row,
            "target_weight": float(row["target_weight"]),
            "context_weight": float(row["context_weight"]),
        }
        sample_id_to_scope[row["sample_id"]] = case_key
    folds: dict[str, int] = {}
    for row in _read_csv(split_path):
        case_key = sample_id_to_scope.get(row["sample_id"])
        if case_key is None:
            continue
        fold = int(row["fold"])
        if case_key in folds and folds[case_key] != fold:
            raise ValueError(f"conflicting M0 fold: {case_key}")
        folds[case_key] = fold
    if len(samples) != config.expected_case_count + 1:
        raise ValueError(
            f"M0 RoadGraph scope expected 52 including exclusion, got {len(samples)}"
        )
    excluded = {
        f"{row['family']}:{row['business_id']}"
        for row in manifest.get("approved_exclusions") or []
    }
    for case_key in excluded:
        samples.pop(case_key, None)
        folds.pop(case_key, None)
    if len(samples) != config.expected_case_count or set(samples) != set(folds):
        raise ValueError("M0 P2 Case/fold scope mismatch")
    observed_folds = set(folds.values())
    if observed_folds != set(range(config.expected_fold_count)):
        raise ValueError(f"M0 fold coverage mismatch: {sorted(observed_folds)}")
    return manifest_path, samples, folds


def _load_p1_contract(config: JSGP2DatasetConfig) -> dict[str, Any]:
    candidate_root = normalize_runtime_path(config.p1_candidate_run_root).resolve(strict=True)
    candidate_manifest_path = candidate_root / "p05_jsg_p1_candidate_manifest.json"
    candidate_manifest = _read_json(candidate_manifest_path)
    if candidate_manifest.get("status") != "candidate_scope_passed":
        raise ValueError("P1 candidate run did not pass")
    for field in ("truth_input_count", "truth_derived_candidate_count", "label_only_candidate_count"):
        if int(candidate_manifest.get(field, -1)) != 0:
            raise ValueError(f"P1 candidate leakage declaration: {field}")
    if candidate_manifest.get("silent_fix") is not False:
        raise ValueError("P1 candidate must declare silent_fix=false")
    candidate_outputs = dict(candidate_manifest.get("outputs") or {})
    jsg_candidate_path = _verified_output(
        candidate_outputs, "candidates", strict_hashes=config.strict_hashes
    )
    jsg_group_path = _verified_output(
        candidate_outputs, "group_index", strict_hashes=config.strict_hashes
    )
    jsg_case_path = _verified_output(
        candidate_outputs, "case_index", strict_hashes=config.strict_hashes
    )
    scopes = {
        f"{row['family']}:{row['business_id']}" for row in _read_csv(jsg_case_path)
    }
    if len(scopes) != config.expected_case_count:
        raise ValueError("P1 candidate Case scope mismatch")

    oracle_root = normalize_runtime_path(config.p1_oracle_run_root).resolve(strict=True)
    oracle_manifest_path = oracle_root / "p05_jsg_p1_solve_manifest.json"
    oracle_manifest = _read_json(oracle_manifest_path)
    if oracle_manifest.get("status") != "p1_passed":
        raise ValueError("P1 Oracle run did not pass")
    if oracle_manifest.get("candidate_manifest_sha256") != sha256_file(candidate_manifest_path):
        raise ValueError("P1 Oracle/candidate manifest mismatch")
    oracle_outputs = dict(oracle_manifest.get("outputs") or {})
    jsg_label_path = _verified_output(
        oracle_outputs, "oracle_costs", strict_hashes=config.strict_hashes
    )

    nested_manifest_path = normalize_runtime_path(
        str(oracle_manifest.get("nested_pto_b_manifest_path") or "")
    ).resolve(strict=True)
    if config.strict_hashes and sha256_file(nested_manifest_path) != str(
        oracle_manifest.get("nested_pto_b_manifest_sha256") or ""
    ):
        raise ValueError("nested PTO-B manifest hash mismatch")
    nested_manifest = _read_json(nested_manifest_path)
    if nested_manifest.get("status") not in {
        "p0_passed",
        "p0_semantic_passed_performance_failed",
    }:
        raise ValueError("nested PTO-B run did not pass semantic gates")
    roadgraph_outputs = dict(nested_manifest.get("outputs") or {})
    roadgraph_label_path = _verified_output(
        roadgraph_outputs, "oracle_costs", strict_hashes=config.strict_hashes
    )
    roadgraph_candidate_manifest_path = normalize_runtime_path(
        str(nested_manifest.get("candidate_manifest_path") or "")
    ).resolve(strict=True)
    if config.strict_hashes and sha256_file(roadgraph_candidate_manifest_path) != str(
        nested_manifest.get("candidate_manifest_sha256") or ""
    ):
        raise ValueError("RoadGraph candidate manifest hash mismatch")
    roadgraph_manifest = _read_json(roadgraph_candidate_manifest_path)
    if int(roadgraph_manifest.get("truth_input_count", -1)) != 0 or int(
        roadgraph_manifest.get("truth_derived_candidate_count", -1)
    ) != 0:
        raise ValueError("RoadGraph candidate manifest declares truth leakage")
    roadgraph_candidate_outputs = dict(roadgraph_manifest.get("outputs") or {})
    return {
        "candidate_manifest_path": candidate_manifest_path,
        "candidate_manifest": candidate_manifest,
        "oracle_manifest_path": oracle_manifest_path,
        "oracle_manifest": oracle_manifest,
        "jsg_candidate_path": jsg_candidate_path,
        "jsg_group_path": jsg_group_path,
        "jsg_label_path": jsg_label_path,
        "roadgraph_candidate_manifest_path": roadgraph_candidate_manifest_path,
        "roadgraph_candidate_manifest": roadgraph_manifest,
        "roadgraph_candidate_path": _verified_output(
            roadgraph_candidate_outputs, "candidates", strict_hashes=config.strict_hashes
        ),
        "roadgraph_group_path": _verified_output(
            roadgraph_candidate_outputs, "group_index", strict_hashes=config.strict_hashes
        ),
        "roadgraph_label_path": roadgraph_label_path,
        "scopes": scopes,
    }


def build_jsg_p2_dataset(config: JSGP2DatasetConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    m0_manifest_path, samples, folds = _load_scope_contract(config)
    contract = _load_p1_contract(config)
    if set(samples) != set(contract["scopes"]):
        raise ValueError("M0/P1 Case scope differs")
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    feature_path = target_root / "p05_jsg_p2_features.jsonl"
    feature_path.touch()
    jsg_labels = _load_labels(contract["jsg_label_path"])
    roadgraph_labels = _load_labels(contract["roadgraph_label_path"])
    jsg_options = _load_group_options(contract["jsg_group_path"], jsg=True)
    roadgraph_options = _load_group_options(contract["roadgraph_group_path"], jsg=False)
    vocabulary: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    fold_counts: Counter[int] = Counter()
    case_counts: dict[str, Counter[str]] = defaultdict(Counter)
    forbidden_hits: list[dict[str, Any]] = []
    feature_signature_rows: list[tuple[str, str]] = []
    label_signature_rows: list[tuple[str, bool]] = []
    seen_labels: dict[str, set[str]] = {"JSG": set(), "ROADGRAPH": set()}
    rss_samples = [_rss_bytes()]

    def emit(candidate: dict[str, Any], *, domain: str) -> None:
        case_key = (
            str(candidate["case_key"])
            if domain == "JSG"
            else f"{candidate['family']}:{candidate['business_id']}"
        )
        if case_key not in samples:
            raise ValueError(f"candidate outside P2 scope: {case_key}")
        candidate_id = str(candidate["candidate_id"])
        labels = jsg_labels if domain == "JSG" else roadgraph_labels
        label_key = (case_key, candidate_id)
        if label_key not in labels:
            raise ValueError(f"candidate label missing: {case_key}/{candidate_id}")
        group_id = str(candidate["group_id"])
        options = jsg_options if domain == "JSG" else roadgraph_options
        option_count = options.get((case_key, group_id))
        if option_count is None:
            raise ValueError(f"group option count missing: {case_key}/{group_id}")
        tokens = (
            jsg_feature_tokens(candidate, group_option_count=option_count)
            if domain == "JSG"
            else roadgraph_feature_tokens(candidate, group_option_count=option_count)
        )
        hits = forbidden_feature_hits(tokens, candidate)
        if hits:
            forbidden_hits.append(
                {"candidate_id": candidate_id, "case_key": case_key, "tokens": hits}
            )
        scope = samples[case_key]
        sample_weight = (
            float(scope["target_weight"])
            if scope["scope_type"] == "t10_case"
            or _is_target_candidate(candidate, str(scope["business_id"]))
            else float(scope["context_weight"])
        )
        truth_equivalent = labels[label_key]
        feature_signature = canonical_sha256(tokens)
        row = {
            "schema_version": JSG_P2_DATASET_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "case_key": case_key,
            "family": str(scope["family"]),
            "business_id": str(scope["business_id"]),
            "fold": folds[case_key],
            "domain": domain,
            "stage": str(candidate.get("stage") or ""),
            "object_type": str(
                candidate.get("object_type") or candidate.get("object_kind") or ""
            ),
            "group_id": group_id,
            "group_option_count": option_count,
            "feature_tokens": list(tokens),
            "feature_signature": feature_signature,
            "truth_equivalent": truth_equivalent,
            "sample_weight": sample_weight,
            "v0_cost": v0_cost(tokens),
            "label_only": True,
            "feature_uses_truth": False,
        }
        _append_jsonl(feature_path, [row])
        vocabulary.update(tokens)
        domain_counts[domain] += 1
        fold_counts[folds[case_key]] += 1
        case_counts[case_key][domain] += 1
        case_counts[case_key]["positive"] += int(truth_equivalent)
        seen_labels[domain].add(f"{case_key}\0{candidate_id}")
        feature_signature_rows.append((candidate_id, feature_signature))
        label_signature_rows.append((candidate_id, truth_equivalent))

    for candidate in _read_jsonl(contract["jsg_candidate_path"]):
        if str(candidate.get("stage") or "") == "PTO_B":
            continue
        emit(candidate, domain="JSG")
    rss_samples.append(_rss_bytes())
    for candidate in _read_jsonl(contract["roadgraph_candidate_path"]):
        emit(candidate, domain="ROADGRAPH")
    rss_samples.append(_rss_bytes())
    if seen_labels["JSG"] != {f"{case_key}\0{candidate_id}" for case_key, candidate_id in jsg_labels}:
        raise ValueError("JSG candidate/label scope differs")
    if seen_labels["ROADGRAPH"] != {
        f"{case_key}\0{candidate_id}" for case_key, candidate_id in roadgraph_labels
    }:
        raise ValueError("RoadGraph candidate/label scope differs")
    if forbidden_hits:
        raise ValueError(f"forbidden feature token detected: {forbidden_hits[:3]}")

    case_rows = [
        {
            "case_key": case_key,
            "family": samples[case_key]["family"],
            "business_id": samples[case_key]["business_id"],
            "fold": folds[case_key],
            "scope_type": samples[case_key]["scope_type"],
            "target_weight": samples[case_key]["target_weight"],
            "context_weight": samples[case_key]["context_weight"],
            "jsg_candidate_count": case_counts[case_key]["JSG"],
            "roadgraph_candidate_count": case_counts[case_key]["ROADGRAPH"],
            "positive_candidate_count": case_counts[case_key]["positive"],
        }
        for case_key in sorted(samples)
    ]
    vocabulary_path = target_root / "p05_jsg_p2_feature_vocabulary.json"
    case_index_path = target_root / "p05_jsg_p2_case_index.csv"
    leakage_path = target_root / "p05_jsg_p2_leakage_audit.json"
    summary_path = target_root / "p05_jsg_p2_dataset_summary.json"
    write_json(
        vocabulary_path,
        {
            "schema_version": "p05-jsg-p2-feature-vocabulary-v1",
            "feature_count": len(vocabulary),
            "features": dict(sorted(vocabulary.items())),
        },
    )
    write_csv(case_index_path, case_rows, list(case_rows[0]))
    leakage_audit = {
        "schema_version": "p05-jsg-p2-leakage-audit-v1",
        "forbidden_feature_hit_count": 0,
        "case_fold_conflict_count": 0,
        "train_held_out_overlap_count": 0,
        "candidate_id_used_as_feature_count": 0,
        "group_id_used_as_feature_count": 0,
        "object_id_used_as_feature_count": 0,
        "truth_or_oracle_used_as_feature_count": 0,
        "passed": True,
    }
    write_json(leakage_path, leakage_audit)
    summary = {
        "schema_version": "p05-jsg-p2-dataset-summary-v1",
        "case_count": len(case_rows),
        "fold_count": len(set(folds.values())),
        "fold_case_counts": dict(
            sorted(Counter(folds.values()).items(), key=lambda item: item[0])
        ),
        "candidate_count": sum(domain_counts.values()),
        "domain_counts": dict(sorted(domain_counts.items())),
        "fold_candidate_counts": dict(sorted(fold_counts.items())),
        "feature_count": len(vocabulary),
        "feature_signature": canonical_sha256(sorted(feature_signature_rows)),
        "label_signature": canonical_sha256(sorted(label_signature_rows)),
        "forbidden_feature_hit_count": 0,
        "excluded_occurrence_count": 0,
        "gate_pass": len(case_rows) == config.expected_case_count,
        "peak_rss_bytes": max(rss_samples, default=0),
        "cpu_seconds": time.process_time() - cpu_started,
        "wall_seconds": time.perf_counter() - started,
        "gpu_required": False,
        "silent_fix": False,
    }
    write_json(summary_path, summary)
    outputs = {
        "features": output_record(feature_path),
        "case_index": output_record(case_index_path),
        "vocabulary": output_record(vocabulary_path),
        "leakage_audit": output_record(leakage_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": "p05-jsg-p2-dataset-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_passed" if summary["gate_pass"] else "dataset_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "p1_candidate_manifest_path": str(contract["candidate_manifest_path"]),
        "p1_candidate_manifest_sha256": sha256_file(contract["candidate_manifest_path"]),
        "p1_oracle_manifest_path": str(contract["oracle_manifest_path"]),
        "p1_oracle_manifest_sha256": sha256_file(contract["oracle_manifest_path"]),
        "roadgraph_candidate_manifest_path": str(
            contract["roadgraph_candidate_manifest_path"]
        ),
        "roadgraph_candidate_manifest_sha256": sha256_file(
            contract["roadgraph_candidate_manifest_path"]
        ),
        "m0_manifest_path": str(m0_manifest_path),
        "m0_manifest_sha256": sha256_file(m0_manifest_path),
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "expected_fold_count": config.expected_fold_count,
            "strict_hashes": config.strict_hashes,
        },
        "environment": _environment(),
        "outputs": outputs,
        "feature_uses_truth": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p2_dataset_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["build_jsg_p2_dataset"]
