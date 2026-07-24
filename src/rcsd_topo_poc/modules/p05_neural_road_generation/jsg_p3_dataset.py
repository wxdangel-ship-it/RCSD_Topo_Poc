from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import (
    _environment,
    _rss_bytes,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_context import (
    GroupDescriptor,
    build_context_tokens,
    count_bucket,
    describe_group,
    forbidden_context_hits,
    reverse_dependencies,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_models import (
    JSGP3DatasetConfig,
    JSG_P3_CONTEXT_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_evidence import (
    build_relative_evidence_tokens,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_training import (
    P3GroupExample,
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


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
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


def _grouped_rows(
    path: Path,
) -> Iterator[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    active_key: tuple[str, str, str] | None = None
    active: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in _read_jsonl(path):
        key = (str(row["domain"]), str(row["case_key"]), str(row["group_id"]))
        if active_key is None:
            active_key = key
        if key != active_key:
            if active_key in seen:
                raise ValueError(f"feature group is not contiguous: {active_key}")
            seen.add(active_key)
            yield active_key, active
            active_key = key
            active = []
        active.append(row)
    if active_key is not None:
        yield active_key, active


def _load_contract(config: JSGP3DatasetConfig) -> dict[str, Any]:
    p2_root = normalize_runtime_path(config.p2_dataset_run_root).resolve(strict=True)
    p2_manifest_path = p2_root / "p05_jsg_p2_dataset_manifest.json"
    p2_manifest = _read_json(p2_manifest_path)
    if p2_manifest.get("status") != "dataset_passed":
        raise ValueError("P2 dataset did not pass")
    p2_outputs = dict(p2_manifest.get("outputs") or {})
    feature_path = _verified_output(
        p2_outputs, "features", strict_hashes=config.strict_hashes
    )
    case_index_path = _verified_output(
        p2_outputs, "case_index", strict_hashes=config.strict_hashes
    )
    leakage_path = _verified_output(
        p2_outputs, "leakage_audit", strict_hashes=config.strict_hashes
    )
    if not bool(_read_json(leakage_path).get("passed")):
        raise ValueError("P2 leakage audit did not pass")
    case_rows = _read_csv(case_index_path)
    if len(case_rows) != config.expected_case_count:
        raise ValueError("P2 Case scope mismatch")
    case_folds = {row["case_key"]: int(row["fold"]) for row in case_rows}
    if set(case_folds.values()) != set(range(config.expected_fold_count)):
        raise ValueError("P2 fold scope mismatch")

    p1_root = normalize_runtime_path(config.p1_candidate_run_root).resolve(strict=True)
    p1_manifest_path = p1_root / "p05_jsg_p1_candidate_manifest.json"
    if config.strict_hashes and sha256_file(p1_manifest_path) != str(
        p2_manifest.get("p1_candidate_manifest_sha256") or ""
    ):
        raise ValueError("P2/P1 candidate manifest mismatch")
    p1_manifest = _read_json(p1_manifest_path)
    if p1_manifest.get("status") != "candidate_scope_passed":
        raise ValueError("P1 candidate run did not pass")
    for field in (
        "truth_input_count",
        "truth_derived_candidate_count",
        "label_only_candidate_count",
    ):
        if int(p1_manifest.get(field, -1)) != 0:
            raise ValueError(f"P1 candidate leakage declaration: {field}")
    if p1_manifest.get("silent_fix") is not False:
        raise ValueError("P1 candidate must declare silent_fix=false")
    p1_candidate_path = _verified_output(
        dict(p1_manifest.get("outputs") or {}),
        "candidates",
        strict_hashes=config.strict_hashes,
    )
    return {
        "p2_manifest_path": p2_manifest_path,
        "p2_manifest": p2_manifest,
        "feature_path": feature_path,
        "case_index_path": case_index_path,
        "case_rows": case_rows,
        "case_folds": case_folds,
        "p1_manifest_path": p1_manifest_path,
        "p1_candidate_path": p1_candidate_path,
    }


def _access_position(
    segment: Mapping[str, Any] | None, junction_id: str
) -> str:
    if not segment or not junction_id:
        return "UNKNOWN"
    endpoints = tuple(str(value) for value in segment.get("endpoint_positions") or [])
    attached = {str(value) for value in segment.get("attached_junctions") or []}
    if len(endpoints) >= 2 and endpoints[0] == junction_id and endpoints[1] == junction_id:
        return "LOOP"
    if endpoints and endpoints[0] == junction_id:
        return "START"
    if len(endpoints) >= 2 and endpoints[1] == junction_id:
        return "END"
    if junction_id in attached:
        return "THROUGH"
    return "UNKNOWN"


def _load_jsg_structure(
    path: Path, *, case_scope: set[str]
) -> tuple[
    dict[tuple[str, str, str], tuple[str, ...]],
    dict[tuple[str, str, str], tuple[str, ...]],
]:
    dependencies: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    metadata: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(dict)
    evidence_paths: dict[str, dict[str, str]] = defaultdict(dict)
    observed_cases: set[str] = set()
    for candidate in _read_jsonl(path):
        if str(candidate.get("stage") or "") == "PTO_B":
            continue
        case_key = str(candidate["case_key"])
        if case_key not in case_scope:
            raise ValueError(f"P1 candidate outside P3 Case scope: {case_key}")
        observed_cases.add(case_key)
        key = (case_key, "JSG", str(candidate["group_id"]))
        dependencies[key].update(str(value) for value in candidate.get("dependencies") or [])
        payload = dict(candidate.get("payload") or {})
        for name in (
            "attached_junctions",
            "connector_id",
            "endpoint_positions",
            "from_segment_access",
            "junction_id",
            "segment_id",
            "structural_role",
            "to_segment_access",
        ):
            value = payload.get(name)
            if value not in (None, "", [], ()):
                metadata[key][name] = value
        metadata[key]["object_type"] = str(candidate["object_type"])
        for evidence in candidate.get("evidence_refs") or []:
            record = dict(evidence)
            role = str(record.get("role") or "")
            evidence_path = str(record.get("path") or "")
            if role and evidence_path:
                evidence_paths[case_key][role] = evidence_path
    if observed_cases != case_scope:
        raise ValueError("P1/P2 Case scope differs")
    structure: dict[tuple[str, str, str], tuple[str, ...]] = {}
    segments: dict[tuple[str, str], dict[str, Any]] = {}
    for key, row in metadata.items():
        if row.get("object_type") == "STANDARD_SEGMENT":
            segment_id = str(row.get("segment_id") or "")
            if segment_id:
                segments[(key[0], segment_id)] = row
    for key, row in metadata.items():
        object_type = str(row.get("object_type") or "")
        tokens: set[str] = set()
        if object_type == "STANDARD_SEGMENT":
            endpoints = tuple(str(value) for value in row.get("endpoint_positions") or [])
            attached = tuple(str(value) for value in row.get("attached_junctions") or [])
            tokens.add(f"segment_endpoint_count={count_bucket(len(endpoints))}")
            tokens.add(f"segment_attached_count={count_bucket(len(attached))}")
            tokens.add(
                "segment_endpoint_layout=LOOP"
                if len(endpoints) >= 2 and endpoints[0] == endpoints[1]
                else "segment_endpoint_layout=DISTINCT"
            )
        elif object_type == "RELATION":
            segment = segments.get((key[0], str(row.get("segment_id") or "")))
            position = _access_position(segment, str(row.get("junction_id") or ""))
            tokens.add(f"relation_access_position={position}")
            tokens.add(f"relation_structural_role={str(row.get('structural_role') or 'UNKNOWN')}")
        elif object_type == "PHYSICAL_MOVEMENT":
            junction_id = str(row.get("junction_id") or "")
            from_segment = str(row.get("from_segment_access") or "").partition("@")[0]
            to_segment = str(row.get("to_segment_access") or "").partition("@")[0]
            from_position = _access_position(
                segments.get((key[0], from_segment)), junction_id
            )
            to_position = _access_position(segments.get((key[0], to_segment)), junction_id)
            tokens.add(f"movement_from_access_position={from_position}")
            tokens.add(f"movement_to_access_position={to_position}")
            tokens.add(f"movement_access_pair={from_position}->{to_position}")
        elif object_type == "SEGMENT_CONNECTOR":
            tokens.add("connector_candidate=true")
        if tokens:
            structure[key] = tuple(sorted(tokens))
    relative_evidence = build_relative_evidence_tokens(metadata, evidence_paths)
    for key, values in relative_evidence.items():
        structure.setdefault(key, ())
        structure[key] = tuple(sorted(set(structure[key]) | set(values)))
    return (
        {key: tuple(sorted(values)) for key, values in dependencies.items()},
        structure,
    )


def _descriptor_rows(
    *,
    descriptors: Mapping[tuple[str, str, str], GroupDescriptor],
    reverse_map: Mapping[tuple[str, str, str], Sequence[str]],
    case_type_counts: Mapping[tuple[str, str], Mapping[str, int]],
    case_folds: Mapping[str, int],
    structural_tokens: Mapping[tuple[str, str, str], Sequence[str]],
    context_vocabulary: Counter[str],
    forbidden_hits: list[dict[str, Any]],
    signature_rows: list[tuple[str, str, str, str]],
) -> Iterator[dict[str, Any]]:
    for key in sorted(descriptors):
        descriptor = descriptors[key]
        tokens = build_context_tokens(
            descriptor,
            descriptors=descriptors,
            reverse_map=reverse_map,
            case_type_counts=case_type_counts,
            structural_tokens=structural_tokens,
        )
        identifiers = (
            descriptor.case_key,
            descriptor.case_key.partition(":")[2],
            descriptor.group_id,
        )
        hits = forbidden_context_hits(tokens, identifiers=identifiers)
        if hits:
            forbidden_hits.append(
                {
                    "case_key": descriptor.case_key,
                    "domain": descriptor.domain,
                    "group_id": descriptor.group_id,
                    "tokens": hits,
                }
            )
        signature = canonical_sha256(tokens)
        context_vocabulary.update(tokens)
        signature_rows.append(
            (descriptor.case_key, descriptor.domain, descriptor.group_id, signature)
        )
        yield {
            "schema_version": JSG_P3_CONTEXT_SCHEMA_VERSION,
            "case_key": descriptor.case_key,
            "fold": case_folds[descriptor.case_key],
            "domain": descriptor.domain,
            "group_id": descriptor.group_id,
            "object_type": descriptor.object_type,
            "group_option_count": descriptor.option_count,
            "dependency_count": len(descriptor.dependencies),
            "reverse_dependency_count": len(reverse_map.get(key, ())),
            "context_tokens": list(tokens),
            "context_signature": signature,
            "feature_uses_truth": False,
        }


def build_jsg_p3_context_dataset(config: JSGP3DatasetConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    contract = _load_contract(config)
    case_scope = set(contract["case_folds"])
    dependencies, structural_tokens = _load_jsg_structure(
        contract["p1_candidate_path"], case_scope=case_scope
    )
    rss_samples = [_rss_bytes()]
    descriptors: dict[tuple[str, str, str], GroupDescriptor] = {}
    case_type_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    domain_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    candidate_count = 0
    truth_count = 0
    for source_key, rows in _grouped_rows(contract["feature_path"]):
        canonical_key = (source_key[1], source_key[0], source_key[2])
        descriptor = describe_group(
            rows, dependencies=dependencies.get(canonical_key, ())
        )
        if canonical_key in descriptors:
            raise ValueError(f"duplicate P3 group: {canonical_key}")
        descriptors[canonical_key] = descriptor
        case_type_counts[(descriptor.case_key, descriptor.domain)][
            descriptor.object_type
        ] += 1
        domain_counts[descriptor.domain] += 1
        type_counts[f"{descriptor.domain}:{descriptor.object_type}"] += 1
        candidate_count += len(rows)
        group_truth_count = sum(bool(row["truth_equivalent"]) for row in rows)
        if group_truth_count != 1:
            raise ValueError(f"group truth cardinality is not one: {canonical_key}")
        truth_count += group_truth_count
    if len(descriptors) != config.expected_group_count:
        raise ValueError(
            f"P3 group count mismatch: {len(descriptors)} != {config.expected_group_count}"
        )
    if candidate_count != config.expected_candidate_count:
        raise ValueError(
            f"P3 candidate count mismatch: {candidate_count} != {config.expected_candidate_count}"
        )
    if truth_count != len(descriptors):
        raise ValueError("P3 truth/group cardinality mismatch")
    rss_samples.append(_rss_bytes())

    reverse_map = reverse_dependencies(descriptors)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    context_path = target_root / "p05_jsg_p3_group_context.jsonl"
    context_vocabulary: Counter[str] = Counter()
    forbidden_hits: list[dict[str, Any]] = []
    signature_rows: list[tuple[str, str, str, str]] = []
    _write_jsonl(
        context_path,
        _descriptor_rows(
            descriptors=descriptors,
            reverse_map=reverse_map,
            case_type_counts=case_type_counts,
            case_folds=contract["case_folds"],
            structural_tokens=structural_tokens,
            context_vocabulary=context_vocabulary,
            forbidden_hits=forbidden_hits,
            signature_rows=signature_rows,
        ),
    )
    rss_samples.append(_rss_bytes())
    if forbidden_hits:
        raise ValueError(f"forbidden P3 context token detected: {forbidden_hits[:3]}")

    case_rows = []
    for source in contract["case_rows"]:
        case_key = source["case_key"]
        domain_group_counts = Counter(
            descriptor.domain
            for descriptor in descriptors.values()
            if descriptor.case_key == case_key
        )
        case_rows.append(
            {
                **source,
                "jsg_group_count": domain_group_counts["JSG"],
                "roadgraph_group_count": domain_group_counts["ROADGRAPH"],
            }
        )
    case_index_path = target_root / "p05_jsg_p3_case_index.csv"
    vocabulary_path = target_root / "p05_jsg_p3_context_vocabulary.json"
    leakage_path = target_root / "p05_jsg_p3_leakage_audit.json"
    summary_path = target_root / "p05_jsg_p3_dataset_summary.json"
    write_csv(case_index_path, case_rows, list(case_rows[0]))
    write_json(
        vocabulary_path,
        {
            "schema_version": "p05-jsg-p3-context-vocabulary-v1",
            "context_feature_count": len(context_vocabulary),
            "context_features": dict(sorted(context_vocabulary.items())),
        },
    )
    leakage_audit = {
        "schema_version": "p05-jsg-p3-leakage-audit-v1",
        "forbidden_context_hit_count": 0,
        "candidate_id_used_as_feature_count": 0,
        "case_or_business_id_used_as_feature_count": 0,
        "group_or_object_id_used_as_feature_count": 0,
        "truth_or_oracle_used_as_feature_count": 0,
        "absolute_coordinate_used_as_feature_count": 0,
        "outer_held_out_statistics_used_as_feature_count": 0,
        "passed": True,
    }
    write_json(leakage_path, leakage_audit)
    summary = {
        "schema_version": "p05-jsg-p3-dataset-summary-v1",
        "case_count": len(case_rows),
        "fold_count": len(set(contract["case_folds"].values())),
        "group_count": len(descriptors),
        "candidate_count": candidate_count,
        "truth_candidate_count": truth_count,
        "domain_group_counts": dict(sorted(domain_counts.items())),
        "object_type_group_counts": dict(sorted(type_counts.items())),
        "context_feature_count": len(context_vocabulary),
        "context_signature": canonical_sha256(sorted(signature_rows)),
        "forbidden_context_hit_count": 0,
        "excluded_occurrence_count": 0,
        "gate_pass": (
            len(case_rows) == config.expected_case_count
            and len(descriptors) == config.expected_group_count
            and candidate_count == config.expected_candidate_count
        ),
        "peak_rss_bytes": max(rss_samples, default=0),
        "cpu_seconds": time.process_time() - cpu_started,
        "wall_seconds": time.perf_counter() - started,
        "gpu_required": False,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(summary_path, summary)
    outputs = {
        "group_context": output_record(context_path),
        "case_index": output_record(case_index_path),
        "context_vocabulary": output_record(vocabulary_path),
        "leakage_audit": output_record(leakage_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": "p05-jsg-p3-dataset-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_passed" if summary["gate_pass"] else "dataset_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "p2_dataset_manifest_path": str(contract["p2_manifest_path"]),
        "p2_dataset_manifest_sha256": sha256_file(contract["p2_manifest_path"]),
        "p1_candidate_manifest_path": str(contract["p1_manifest_path"]),
        "p1_candidate_manifest_sha256": sha256_file(contract["p1_manifest_path"]),
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "expected_fold_count": config.expected_fold_count,
            "expected_group_count": config.expected_group_count,
            "expected_candidate_count": config.expected_candidate_count,
            "strict_hashes": config.strict_hashes,
        },
        "environment": _environment(),
        "outputs": outputs,
        "feature_uses_truth": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p3_dataset_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


def load_p3_group_examples(
    feature_path: Path,
    context_path: Path,
) -> list[P3GroupExample]:
    contexts: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _read_jsonl(context_path):
        key = (str(row["domain"]), str(row["case_key"]), str(row["group_id"]))
        if key in contexts:
            raise ValueError(f"duplicate P3 context group: {key}")
        contexts[key] = row
    groups: list[P3GroupExample] = []
    seen: set[tuple[str, str, str]] = set()
    for key, rows in _grouped_rows(feature_path):
        context = contexts.get(key)
        if context is None:
            raise ValueError(f"P3 context missing: {key}")
        truth_indices = [index for index, row in enumerate(rows) if row["truth_equivalent"]]
        if len(truth_indices) != 1:
            raise ValueError(f"P3 group truth cardinality is not one: {key}")
        folds = {int(row["fold"]) for row in rows}
        object_types = {str(row["object_type"]) for row in rows}
        sample_weights = {float(row["sample_weight"]) for row in rows}
        if len(folds) != 1 or len(object_types) != 1 or len(sample_weights) != 1:
            raise ValueError(f"P3 group metadata differs across candidates: {key}")
        if int(context["fold"]) != next(iter(folds)):
            raise ValueError(f"P3 feature/context fold mismatch: {key}")
        groups.append(
            P3GroupExample(
                case_key=key[1],
                fold=next(iter(folds)),
                domain=key[0],
                group_id=key[2],
                object_type=next(iter(object_types)),
                candidate_ids=tuple(str(row["candidate_id"]) for row in rows),
                candidate_tokens=tuple(
                    tuple(str(token) for token in row.get("feature_tokens") or [])
                    for row in rows
                ),
                feature_signatures=tuple(str(row["feature_signature"]) for row in rows),
                context_tokens=tuple(
                    str(token) for token in context.get("context_tokens") or []
                ),
                context_signature=str(context["context_signature"]),
                truth_index=truth_indices[0],
                sample_weight=next(iter(sample_weights)),
            )
        )
        seen.add(key)
    if seen != set(contexts):
        raise ValueError("P3 context/feature group scope differs")
    return groups


__all__ = ["build_jsg_p3_context_dataset", "load_p3_group_examples"]
