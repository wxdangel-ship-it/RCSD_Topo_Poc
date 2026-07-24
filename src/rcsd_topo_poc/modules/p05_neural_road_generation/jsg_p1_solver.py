from __future__ import annotations

import csv
import gc
import json
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_compiler import _carrier_failures
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import JSGCaseTruth
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import (
    _environment,
    _percentile,
    _rss_bytes,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    JSGP1OracleConfig,
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import PTOOracleSolveConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_p0 import (
    _evaluation_exact,
    solve_pto_oracle_run,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
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


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _verified_output(outputs: dict[str, Any], role: str, *, strict_hashes: bool) -> Path:
    record = dict(outputs.get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"P1 output hash mismatch: {role}")
    return path


def _case_directory(case_key: str) -> str:
    return canonical_sha256(case_key)[:20]


def _projection_truth(case: JSGCaseTruth) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    expected: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for row in case.junction_units:
        group = f"PTO_A:JUNCTION:{row.junction_id}"
        expected[group] = {
            "junction_id": row.junction_id,
            "junction_type": row.junction_type.value,
            "growth_level": row.growth_level,
            "state": row.state.value,
        }
        counts["JUNCTION"] += 1
    for row in case.standard_segments:
        group = f"PTO_A:STANDARD_SEGMENT:{row.segment_id}"
        expected[group] = {
            "segment_id": row.segment_id,
            "endpoint_positions": list(row.endpoint_positions),
            "attached_junctions": list(row.attached_junctions),
            "direction_structure": row.direction_structure.value,
            "growth_level": row.growth_level,
            "road_grade": row.road_grade,
            "explicit_loop": row.explicit_loop,
            "state": row.state.value,
        }
        counts["STANDARD_SEGMENT"] += 1
    for row in case.junction_segment_relations:
        group = (
            f"PTO_A:RELATION:{row.junction_id}:{row.segment_id}:{row.structural_role.value}"
        )
        expected[group] = {
            "junction_id": row.junction_id,
            "segment_id": row.segment_id,
            "structural_role": row.structural_role.value,
            "direction_role": row.direction_role.value,
            "state": row.state.value,
        }
        counts["RELATION"] += 1
    for row in case.physical_movements:
        group = f"PTO_A:PHYSICAL_MOVEMENT:{row.movement_id}"
        expected[group] = {
            "movement_id": row.movement_id,
            "junction_id": row.junction_id,
            "from_segment_access": row.from_segment_access,
            "to_segment_access": row.to_segment_access,
            "physical_reachable": row.physical_reachable,
            "state": row.state.value,
            "outcome": "PRESENT",
        }
        counts["PHYSICAL_MOVEMENT"] += 1
    connector_truth = {row.connector_id: row for row in case.segment_connectors}
    anomaly_codes: dict[str, set[str]] = defaultdict(set)
    for anomaly in case.anomalies:
        anomaly_codes[anomaly.object_id].add(anomaly.code)
    connector_ids = set(connector_truth)
    connector_ids.update(
        object_id
        for object_id, codes in anomaly_codes.items()
        if codes & {"auxiliary_internal_carrier", "connector_not_materialized"}
    )
    for connector_id in sorted(connector_ids):
        group = f"PTO_A:SEGMENT_CONNECTOR:{connector_id}"
        if connector_id in connector_truth:
            row = connector_truth[connector_id]
            expected[group] = {
                "connector_id": connector_id,
                "direction": row.direction,
                "state": row.state.value,
                "outcome": "PRESENT",
            }
            counts["SEGMENT_CONNECTOR_PRESENT"] += 1
        elif "auxiliary_internal_carrier" in anomaly_codes[connector_id]:
            expected[group] = {
                "connector_id": connector_id,
                "direction": "FORWARD",
                "state": "REVIEW",
                "outcome": "AUXILIARY_INTERNAL",
            }
            counts["SEGMENT_CONNECTOR_AUXILIARY"] += 1
        else:
            expected[group] = {
                "connector_id": connector_id,
                "direction": "FORWARD",
                "state": "REVIEW",
                "outcome": "NOT_MATERIALIZED",
            }
            counts["SEGMENT_CONNECTOR_NOT_MATERIALIZED"] += 1
    return expected, counts


def solve_pto_a_case(
    candidates: list[dict[str, Any]],
    truth: JSGCaseTruth,
) -> dict[str, Any]:
    expected, truth_counts = _projection_truth(truth)
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    carrier_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("truth_derived") is not False or candidate.get("label_only") is not False:
            raise ValueError(f"candidate leakage flag invalid: {candidate.get('candidate_id')}")
        if candidate.get("stage") == "PTO_B":
            carrier_candidates.append(candidate)
            continue
        by_group[str(candidate["group_id"])].append(candidate)
    for group_id, options in by_group.items():
        if group_id.startswith("PTO_A:PHYSICAL_MOVEMENT:") and group_id not in expected:
            movement_id = str(options[0]["object_key"])
            expected[group_id] = {"movement_id": movement_id, "outcome": "ABSENT"}
            truth_counts["PHYSICAL_MOVEMENT_ABSENT"] += 1

    missing_groups: list[str] = []
    unmatched_groups: list[str] = []
    selected: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    represented: Counter[str] = Counter()
    for group_id, truth_payload in sorted(expected.items()):
        options = by_group.get(group_id, [])
        truth_sha = canonical_sha256(truth_payload)
        if not options:
            missing_groups.append(group_id)
            continue
        exact = [row for row in options if row["payload_sha256"] == truth_sha]
        for row in options:
            costs.append(
                {
                    "candidate_id": row["candidate_id"],
                    "group_id": group_id,
                    "cost": 0 if row["payload_sha256"] == truth_sha else 1,
                    "truth_equivalent": row["payload_sha256"] == truth_sha,
                    "label_only": True,
                }
            )
        if not exact:
            unmatched_groups.append(group_id)
            continue
        choice = min(exact, key=lambda row: str(row["candidate_id"]))
        selected.append(choice)
        represented[str(choice["object_type"])] += 1
    extra_groups = sorted(set(by_group) - set(expected))
    selected_groups = {row["group_id"] for row in selected}
    dependency_failures: list[str] = []
    for row in selected:
        for dependency in row.get("dependencies") or []:
            if dependency not in selected_groups:
                dependency_failures.append(f"{row['candidate_id']} missing dependency {dependency}")

    through_by_junction: dict[str, int] = Counter()
    for row in selected:
        payload = dict(row.get("payload") or {})
        if (
            row.get("object_type") == "RELATION"
            and payload.get("structural_role") == "THROUGH"
            and payload.get("state") == "PUBLISHABLE"
        ):
            through_by_junction[str(payload["junction_id"])] += 1
    multi_through_auto_selected = sum(value > 1 for value in through_by_junction.values())
    if multi_through_auto_selected:
        dependency_failures.append("multiple publishable THROUGH relations were selected")
    carrier_group_count = len(carrier_candidates)
    if carrier_group_count != 1:
        dependency_failures.append(f"expected one PTO-B carrier-domain reference, got {carrier_group_count}")
    failures = missing_groups + unmatched_groups + extra_groups + dependency_failures
    status = "OPTIMAL" if not failures else "INFEASIBLE"
    return {
        "status": status,
        "objective": 0.0 if status == "OPTIMAL" else None,
        "lower_bound": 0.0 if status == "OPTIMAL" else None,
        "optimality_gap": 0.0 if status == "OPTIMAL" else None,
        "selected": selected,
        "costs": sorted(costs, key=lambda row: (row["group_id"], row["candidate_id"])),
        "truth_counts": dict(sorted(truth_counts.items())),
        "represented_counts": dict(sorted(represented.items())),
        "missing_groups": missing_groups,
        "unmatched_groups": unmatched_groups,
        "extra_groups": extra_groups,
        "dependency_failures": dependency_failures,
        "multi_through_auto_selected_count": multi_through_auto_selected,
        "candidate_count": len(candidates),
        "group_count": len(by_group) + carrier_group_count,
        "selected_candidate_count": len(selected),
        "carrier_domain_candidate_count": carrier_group_count,
        "semantic_projection_signature": canonical_sha256(
            {row["group_id"]: row["payload_sha256"] for row in selected}
        ),
        "selection_signature": canonical_sha256(sorted(row["candidate_id"] for row in selected)),
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _load_candidate_run(
    config: JSGP1OracleConfig,
) -> tuple[Path, dict[str, Any], Path, dict[str, dict[str, str]]]:
    root = normalize_runtime_path(config.candidate_run_root).resolve(strict=True)
    manifest_path = root / "p05_jsg_p1_candidate_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-jsg-p1-candidate-manifest-v1":
        raise ValueError("invalid JSG-P1 candidate manifest")
    if manifest.get("status") != "candidate_scope_passed" or manifest.get("silent_fix") is not False:
        raise ValueError("JSG-P1 candidate run did not pass scope")
    for key in ("truth_input_count", "truth_derived_candidate_count", "label_only_candidate_count"):
        if int(manifest.get(key, -1)) != 0:
            raise ValueError(f"JSG-P1 candidate manifest leakage: {key}")
    outputs = dict(manifest.get("outputs") or {})
    candidate_path = _verified_output(outputs, "candidates", strict_hashes=config.strict_hashes)
    case_index_path = _verified_output(outputs, "case_index", strict_hashes=config.strict_hashes)
    _verified_output(outputs, "group_index", strict_hashes=config.strict_hashes)
    _verified_output(outputs, "lineage", strict_hashes=config.strict_hashes)
    index = {row["case_key"]: row for row in _read_csv(case_index_path)}
    if len(index) != config.expected_case_count:
        raise ValueError(f"P1 candidate run has {len(index)} cases")
    return manifest_path, manifest, candidate_path, index


def _load_p0_truth(
    config: JSGP1OracleConfig,
) -> tuple[Path, dict[str, Any], dict[str, tuple[JSGCaseTruth, Path]]]:
    root = normalize_runtime_path(config.p0_truth_run_root).resolve(strict=True)
    manifest_path = root / "run_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-jsg-p0-manifest-v1":
        raise ValueError("invalid P0 truth manifest")
    if (
        manifest.get("status") != "passed"
        or manifest.get("label_only") is not True
        or manifest.get("content_repair") is not False
        or manifest.get("silent_fix") is not False
    ):
        raise ValueError("P0 truth run must be passed label-only no-repair")
    case_index_path = _verified_output(
        dict(manifest.get("outputs") or {}), "case_inventory", strict_hashes=config.strict_hashes
    )
    output: dict[str, tuple[JSGCaseTruth, Path]] = {}
    for row in _read_csv(case_index_path):
        case_root = normalize_runtime_path(row["case_root"]).resolve(strict=True)
        truth_path = case_root / "jsg_truth.json"
        truth = JSGCaseTruth.from_dict(_read_json(truth_path))
        if truth.case_key != row["case_key"]:
            raise ValueError(f"P0 truth Case key mismatch: {row['case_key']}")
        output[truth.case_key] = (truth, truth_path)
    if len(output) != config.expected_case_count:
        raise ValueError(f"P0 truth run has {len(output)} cases")
    return manifest_path, manifest, output


def _iter_candidate_cases(path: Path) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    active_key = ""
    active_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _read_jsonl(path):
        case_key = str(row["case_key"])
        if not active_key:
            active_key = case_key
        if case_key != active_key:
            if active_key in seen:
                raise ValueError(f"candidate Case is not contiguous: {active_key}")
            seen.add(active_key)
            yield active_key, active_rows
            active_key = case_key
            active_rows = []
        active_rows.append(row)
    if active_key:
        yield active_key, active_rows


def solve_jsg_p1_oracle_run(config: JSGP1OracleConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    candidate_manifest_path, candidate_manifest, candidate_path, candidate_index = _load_candidate_run(config)
    p0_manifest_path, _, truth_by_case = _load_p0_truth(config)
    if set(candidate_index) != set(truth_by_case):
        raise ValueError("P1 candidate/P0 truth Case scope differs")
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    cost_path = target_root / "p05_jsg_p1_oracle_costs.jsonl"
    pto_a_path = target_root / "p05_jsg_p1_pto_a_certificates.jsonl"
    pto_b_path = target_root / "p05_jsg_p1_pto_b_certificates.jsonl"
    for path in (cost_path, pto_a_path, pto_b_path):
        path.touch()
    candidate_manifest_sha = sha256_file(candidate_manifest_path)
    p0_manifest_sha = sha256_file(p0_manifest_path)
    pto_a_results: dict[str, dict[str, Any]] = {}
    pto_a_selected: dict[str, list[dict[str, Any]]] = {}
    pto_a_seconds: dict[str, float] = {}
    observed_case_keys: set[str] = set()
    rss_samples = [_rss_bytes()]
    for case_key, rows in _iter_candidate_cases(candidate_path):
        if case_key not in truth_by_case:
            raise ValueError(f"candidate Case not in P0 truth: {case_key}")
        solve_started = time.perf_counter()
        result = solve_pto_a_case(rows, truth_by_case[case_key][0])
        pto_a_seconds[case_key] = time.perf_counter() - solve_started
        observed_case_keys.add(case_key)
        _append_jsonl(
            cost_path,
            (
                {
                    **cost,
                    "case_key": case_key,
                    "candidate_manifest_sha256": candidate_manifest_sha,
                }
                for cost in result["costs"]
            ),
        )
        certificate = {key: value for key, value in result.items() if key not in {"selected", "costs"}}
        certificate.update(
            {
                "case_key": case_key,
                "selected_candidate_ids": sorted(row["candidate_id"] for row in result["selected"]),
                "candidate_manifest_sha256": candidate_manifest_sha,
                "p0_truth_manifest_sha256": p0_manifest_sha,
            }
        )
        _append_jsonl(pto_a_path, [certificate])
        pto_a_results[case_key] = certificate
        pto_a_selected[case_key] = result["selected"]
        rss_samples.append(_rss_bytes())
    if observed_case_keys != set(truth_by_case):
        raise ValueError("P1 candidate JSONL Case scope is incomplete")
    gc.collect()

    upstream_pto_root = normalize_runtime_path(
        str(candidate_manifest.get("upstream_pto_candidate_run_root") or "")
    ).resolve(strict=True)
    nested_output = target_root / "_pto_b"
    pto_b_summary = solve_pto_oracle_run(
        PTOOracleSolveConfig(
            candidate_run_root=upstream_pto_root,
            r2_oracle_run_root=config.r2_oracle_run_root,
            output_root=nested_output,
            run_id="roadgraph_oracle",
            expected_case_count=config.expected_case_count,
            strict_hashes=config.strict_hashes,
            emit_reconstructed_gpkg=config.emit_reconstructed_gpkg,
        )
    )
    pto_b_root = nested_output / "roadgraph_oracle"
    pto_b_index = {
        f"{row['family']}:{row['business_id']}": row
        for row in _read_csv(pto_b_root / "p05_pto_case_index.csv")
    }
    if set(pto_b_index) != set(truth_by_case):
        raise ValueError("PTO-B/P0 truth Case scope differs")

    case_rows: list[dict[str, Any]] = []
    pto_a_optimal = pto_b_optimal = compiler_exact = 0
    hard_failure_count = carrier_missing_count = carrier_reference_count = 0
    total_truth_counts: Counter[str] = Counter()
    total_represented_counts: Counter[str] = Counter()
    for case_key in sorted(truth_by_case):
        truth, truth_path = truth_by_case[case_key]
        family, business_id = case_key.split(":", 1)
        pto_a = pto_a_results[case_key]
        pto_b = pto_b_index[case_key]
        case_root = target_root / "cases" / _case_directory(case_key)
        case_root.mkdir(parents=True)
        selected_jsg_path = case_root / "selected_jsg.json"
        pto_a_case_path = case_root / "pto_a_certificate.json"
        pto_b_case_path = case_root / "pto_b_certificate.json"
        compiled_road_path = case_root / "compiled_road.gpkg"
        compiled_node_path = case_root / "compiled_node.gpkg"
        evaluation_path = case_root / "roadgraph_evaluation.json"
        selected_rows = pto_a_selected[case_key]
        write_json(
            selected_jsg_path,
            {
                "schema_version": "p05-jsg-p1-selected-v1",
                "case_key": case_key,
                "crs": candidate_index[case_key]["crs"],
                "candidate_manifest_sha256": candidate_manifest_sha,
                "selected_candidates": [
                    {
                        "candidate_id": row["candidate_id"],
                        "stage": row["stage"],
                        "object_type": row["object_type"],
                        "object_key": row["object_key"],
                        "group_id": row["group_id"],
                        "payload": row["payload"],
                        "dependencies": row.get("dependencies") or [],
                        "evidence_refs": row.get("evidence_refs") or [],
                        "source_kinds": row.get("source_kinds") or [],
                    }
                    for row in sorted(selected_rows, key=lambda item: item["group_id"])
                ],
                "semantic_projection_signature": pto_a["semantic_projection_signature"],
                "selection_signature": pto_a["selection_signature"],
                "label_only": True,
                "content_repair": False,
                "silent_fix": False,
            },
        )
        write_json(pto_a_case_path, pto_a)
        selected_road = normalize_runtime_path(pto_b["selected_road_path"]).resolve(strict=True)
        selected_node = normalize_runtime_path(pto_b["selected_node_path"]).resolve(strict=True)
        shutil.copy2(selected_road, compiled_road_path)
        shutil.copy2(selected_node, compiled_node_path)
        truth_road = normalize_runtime_path(truth.carrier_realization.expected_truth_road).resolve(strict=True)
        truth_node = normalize_runtime_path(truth.carrier_realization.expected_truth_node).resolve(strict=True)
        evaluation = evaluate_frcsd(
            compiled_road_path, compiled_node_path, truth_road, truth_node
        )
        write_json(evaluation_path, evaluation)
        roads, _ = read_vector_payloads(compiled_road_path, source_role="p1_selected_road")
        nodes, _ = read_vector_payloads(compiled_node_path, source_role="p1_selected_node")
        carrier_failures, references = _carrier_failures(truth, set(roads), set(nodes))
        exact = _evaluation_exact(evaluation) and not carrier_failures
        pto_b_certificate = {
            "case_key": case_key,
            "status": pto_b["status"],
            "optimality_gap": float(pto_b["optimality_gap"]),
            "candidate_signature": pto_b["candidate_signature"],
            "selection_signature": pto_b["selection_signature"],
            "normalized_graph_signature": pto_b["normalized_graph_signature"],
            "carrier_reference_count": references,
            "carrier_missing_reference_count": len(carrier_failures),
            "carrier_hard_failures": carrier_failures,
            "compiler_exact": exact,
            "relaxation": False,
            "content_repair": False,
            "silent_fix": False,
        }
        write_json(pto_b_case_path, pto_b_certificate)
        _append_jsonl(pto_b_path, [pto_b_certificate])
        artifacts = {
            "selected_jsg": output_record(selected_jsg_path),
            "pto_a_certificate": output_record(pto_a_case_path),
            "pto_b_certificate": output_record(pto_b_case_path),
            "compiled_road": output_record(compiled_road_path),
            "compiled_node": output_record(compiled_node_path),
            "roadgraph_evaluation": output_record(evaluation_path),
            "p0_truth": {
                "path": str(truth_path.resolve()),
                "sha256": sha256_file(truth_path),
                "size_bytes": truth_path.stat().st_size,
            },
        }
        write_json(
            case_root / "artifact_manifest.json",
            {"schema_version": "p05-jsg-p1-case-artifacts-v1", "case_key": case_key, "artifacts": artifacts},
        )
        for key, value in dict(pto_a["truth_counts"]).items():
            total_truth_counts[key] += int(value)
        for key, value in dict(pto_a["represented_counts"]).items():
            total_represented_counts[key] += int(value)
        pto_a_ok = pto_a["status"] == "OPTIMAL" and float(pto_a["optimality_gap"]) == 0.0
        pto_b_ok = pto_b["status"] == "OPTIMAL" and float(pto_b["optimality_gap"]) == 0.0
        pto_a_optimal += pto_a_ok
        pto_b_optimal += pto_b_ok
        compiler_exact += exact
        hard_failure_count += len(list(evaluation.get("hard_failures") or [])) + len(carrier_failures)
        carrier_missing_count += len(carrier_failures)
        carrier_reference_count += references
        incremental_seconds = (
            float(candidate_index[case_key]["p1_candidate_build_seconds"])
            + pto_a_seconds[case_key]
            + float(pto_b["candidate_build_plus_solve_seconds"])
            + float(pto_b["materialize_evaluate_seconds"])
        )
        case_rows.append(
            {
                "case_key": case_key,
                "family": family,
                "business_id": business_id,
                "pto_a_status": pto_a["status"],
                "pto_b_status": pto_b["status"],
                "pto_a_gap": pto_a["optimality_gap"],
                "pto_b_gap": pto_b["optimality_gap"],
                "pto_a_candidate_count": pto_a["candidate_count"],
                "pto_b_candidate_count": pto_b["candidate_count"],
                "pto_a_selection_signature": pto_a["selection_signature"],
                "pto_b_selection_signature": pto_b["selection_signature"],
                "semantic_projection_signature": pto_a["semantic_projection_signature"],
                "normalized_graph_signature": pto_b["normalized_graph_signature"],
                "carrier_reference_count": references,
                "carrier_missing_reference_count": len(carrier_failures),
                "compiler_exact": exact,
                "hard_failure_count": len(list(evaluation.get("hard_failures") or [])) + len(carrier_failures),
                "p1_incremental_seconds": incremental_seconds,
                "upstream_replay_seconds": float(candidate_index[case_key]["upstream_replay_seconds"]),
                "case_root": str(case_root.resolve()),
            }
        )
        rss_samples.append(_rss_bytes())

    p95 = _percentile([float(row["p1_incremental_seconds"]) for row in case_rows], 0.95)
    maximum = max(float(row["p1_incremental_seconds"]) for row in case_rows)
    cpu_seconds = time.process_time() - cpu_started
    peak_rss = max(rss_samples, default=0)
    excluded = set(
        dict(candidate_manifest.get("parameters") or {}).get("excluded_business_ids") or []
    )
    excluded_occurrences = sum(row["business_id"] in excluded for row in case_rows)
    pto_a_reachability = pto_a_optimal == len(case_rows)
    pto_b_reachability = bool(pto_b_summary.get("gate1_candidate_reachability_pass"))
    semantic_gate = (
        len(case_rows) == config.expected_case_count
        and excluded_occurrences == 0
        and pto_a_reachability
        and pto_b_reachability
        and pto_b_optimal == len(case_rows)
        and compiler_exact == len(case_rows)
        and hard_failure_count == 0
        and carrier_missing_count == 0
        and sum(int(row["multi_through_auto_selected_count"]) for row in pto_a_results.values()) == 0
    )
    performance_gate = (
        p95 <= 60.0
        and maximum <= 300.0
        and peak_rss <= 16 * 1024**3
        and cpu_seconds <= 2 * 3600.0
    )
    candidate_signature = str(
        _read_json(_verified_output(dict(candidate_manifest["outputs"]), "summary", strict_hashes=config.strict_hashes)).get(
            "candidate_signature"
        )
    )
    summary = {
        "schema_version": "p05-jsg-p1-summary-v1",
        "case_count": len(case_rows),
        "family_counts": dict(sorted(Counter(row["family"] for row in case_rows).items())),
        "excluded_business_ids": sorted(excluded),
        "excluded_occurrence_count": excluded_occurrences,
        "truth_counts": dict(sorted(total_truth_counts.items())),
        "represented_counts": dict(sorted(total_represented_counts.items())),
        "pto_a_optimal_case_count": pto_a_optimal,
        "pto_b_optimal_case_count": pto_b_optimal,
        "compiler_exact_case_count": compiler_exact,
        "hard_failure_count": hard_failure_count,
        "carrier_reference_count": carrier_reference_count,
        "carrier_missing_reference_count": carrier_missing_count,
        "multi_through_auto_selected_count": sum(
            int(row["multi_through_auto_selected_count"]) for row in pto_a_results.values()
        ),
        "pto_a_candidate_reachability_pass": pto_a_reachability,
        "pto_b_candidate_reachability_pass": pto_b_reachability,
        "semantic_gate_pass": semantic_gate,
        "performance_gate_pass": performance_gate,
        "gate_pass": semantic_gate and performance_gate,
        "candidate_signature": candidate_signature,
        "pto_a_selection_signature": canonical_sha256(
            {row["case_key"]: row["pto_a_selection_signature"] for row in case_rows}
        ),
        "pto_b_selection_signature": canonical_sha256(
            {row["case_key"]: row["pto_b_selection_signature"] for row in case_rows}
        ),
        "semantic_projection_signature": canonical_sha256(
            {row["case_key"]: row["semantic_projection_signature"] for row in case_rows}
        ),
        "compiled_graph_signature": canonical_sha256(
            {row["case_key"]: row["normalized_graph_signature"] for row in case_rows}
        ),
        "p1_incremental_p95_seconds": p95,
        "p1_incremental_max_seconds": maximum,
        "p1_cpu_seconds": cpu_seconds,
        "peak_rss_bytes": peak_rss,
        "upstream_replay_total_seconds": sum(
            float(row["upstream_replay_seconds"]) for row in case_rows
        ),
        "gpu_required": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
        "determinism_verified": False,
        "wall_seconds": time.perf_counter() - started,
    }
    case_index_path = target_root / "p05_jsg_p1_case_index.csv"
    summary_path = target_root / "p05_jsg_p1_summary.json"
    write_csv(case_index_path, case_rows, list(case_rows[0]))
    write_json(summary_path, summary)
    outputs = {
        "oracle_costs": output_record(cost_path),
        "pto_a_certificates": output_record(pto_a_path),
        "pto_b_certificates": output_record(pto_b_path),
        "case_index": output_record(case_index_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": "p05-jsg-p1-solve-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "p1_passed" if summary["gate_pass"] else "p1_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_manifest_path": str(candidate_manifest_path),
        "candidate_manifest_sha256": candidate_manifest_sha,
        "p0_truth_manifest_path": str(p0_manifest_path),
        "p0_truth_manifest_sha256": p0_manifest_sha,
        "r2_oracle_run_root": str(normalize_runtime_path(config.r2_oracle_run_root).resolve(strict=True)),
        "nested_pto_b_manifest_path": str(pto_b_summary["manifest_path"]),
        "nested_pto_b_manifest_sha256": str(pto_b_summary["manifest_sha256"]),
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "strict_hashes": config.strict_hashes,
            "emit_reconstructed_gpkg": config.emit_reconstructed_gpkg,
        },
        "environment": _environment(),
        "outputs": outputs,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p1_solve_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["solve_jsg_p1_oracle_run", "solve_pto_a_case"]
