from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import (
    _environment,
    _rss_bytes,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_execution import (
    _canonical_crs,
    _payload_signature,
    _property,
    _read_vector,
    _semantic_payload_signature,
    _text,
    fallback_case_to_swsd,
    fallback_conflicting_groups_to_swsd,
    materialize_case_roadgraph,
    select_effective_candidate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_oof import (
    _load_candidates,
    _load_lineage,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1GroupExample,
    load_scheme_a_p1_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_models import (
    SchemeAP2CandidateConfig,
    SchemeAP2OracleConfig,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


P2_CANDIDATE_SCHEMA = "p05-scheme-a-p2-candidate-v1"
P2_NODE_OPTION_SCHEMA = "p05-scheme-a-p2-node-option-v1"
P2_ORACLE_SCHEMA = "p05-scheme-a-p2-oracle-v1"


def build_scheme_a_p2_candidate_run(config: SchemeAP2CandidateConfig) -> Path:
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    baseline_root = normalize_runtime_path(config.scheme_a_baseline_run_root).resolve()
    p1_root = normalize_runtime_path(config.p1_candidate_run_root).resolve()
    baseline_manifest_path = baseline_root / "scheme_a_manifest.json"
    p1_manifest_path = p1_root / "scheme_a_p1_candidate_manifest.json"
    baseline_manifest = _read_json(baseline_manifest_path)
    p1_manifest = _read_json(p1_manifest_path)
    _validate_candidate_inputs(config, baseline_manifest, p1_manifest)
    _verify_manifest_outputs(p1_manifest, ("candidates", "case_index", "lineage"), config.strict_hashes)
    _verify_manifest_outputs(baseline_manifest, ("case_inventory",), config.strict_hashes)

    p1_candidate_path = _record_path(p1_manifest["outputs"]["candidates"])
    p1_lineage_path = _record_path(p1_manifest["outputs"]["lineage"])
    segment_rows: list[dict[str, Any]] = []
    segment_groups: set[str] = set()
    case_keys: set[str] = set()
    with p1_candidate_path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row.get("object_type") != "SEGMENT":
                continue
            if row.get("truth_derived") or row.get("feature_uses_truth"):
                raise ValueError("P2 candidate received a truth-derived P1 candidate")
            reduced = {
                "schema_version": P2_CANDIDATE_SCHEMA,
                "case_key": str(row["case_key"]),
                "family": str(row["family"]),
                "business_id": str(row["business_id"]),
                "object_id": str(row["object_id"]),
                "group_id": str(row["group_id"]),
                "candidate_id": str(row["candidate_id"]),
                "candidate_target": str(row["candidate_target"]),
                "target_kind": str(row["target_kind"]),
                "target_payload": list(row.get("target_payload") or []),
                "source_kinds": list(row.get("source_kinds") or []),
                "object_tokens": list(row.get("object_tokens") or []),
                "payload_artifacts": list(row.get("payload_artifacts") or []),
                "payload_artifact_by_id": list(row.get("payload_artifact_by_id") or []),
                "truth_derived": False,
                "label_only": False,
            }
            segment_rows.append(reduced)
            segment_groups.add(reduced["group_id"])
            case_keys.add(reduced["case_key"])
    if len(case_keys) != config.expected_case_count:
        raise ValueError(f"P2 candidate Case count mismatch: {len(case_keys)}")
    if len(segment_groups) != config.expected_segment_count:
        raise ValueError(f"P2 candidate Segment count mismatch: {len(segment_groups)}")

    lineage_rows, lineage_by_case = _read_lineage_rows(p1_lineage_path)
    node_options: list[dict[str, Any]] = []
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
    observed_crs: set[str] = set()
    for case_key in sorted(case_keys):
        roles = lineage_by_case.get(case_key, {})
        for role in ("t01_nodes", "proposal_nodes"):
            lineage = roles.get(role)
            if lineage is None:
                raise ValueError(f"missing {role} lineage for {case_key}")
            payloads, crs = _read_vector(lineage["path"], vector_cache)
            canonical_crs = _canonical_crs(crs)
            observed_crs.add(canonical_crs)
            for node_id, payload in sorted(payloads.items()):
                properties = dict(payload.get("properties") or {})
                mainnode = _text(_property(properties, "mainnodeid"))
                mainnode_key = mainnode if mainnode not in {"", "0", "0.0"} else node_id
                semantic_signature = _semantic_payload_signature(payload)
                node_options.append(
                    {
                        "schema_version": P2_NODE_OPTION_SCHEMA,
                        "case_key": case_key,
                        "node_id": node_id,
                        "candidate_id": "sap2n:"
                        + canonical_sha256(
                            {
                                "case_key": case_key,
                                "node_id": node_id,
                                "role": role,
                                "semantic_signature": semantic_signature,
                            }
                        )[:24],
                        "source_role": role,
                        "source_path": lineage["path"],
                        "source_sha256": lineage["sha256"],
                        "crs": canonical_crs,
                        "mainnode_key": mainnode_key,
                        "semantic_signature": semantic_signature,
                        "payload_signature": _payload_signature(payload),
                        "truth_derived": False,
                        "label_only": False,
                    }
                )
    if observed_crs != {"EPSG:3857"}:
        raise ValueError(f"P2 candidate CRS mismatch: {sorted(observed_crs)}")

    case_inventory_path = _record_path(baseline_manifest["outputs"]["case_inventory"])
    case_rows = _read_csv(case_inventory_path)
    if {str(row["case_key"]) for row in case_rows} != case_keys:
        raise ValueError("P2 candidate Case scope differs from Scheme A baseline")
    excluded = {
        str(row["business_id"])
        for row in case_rows
        if str(row["business_id"]) in set(config.excluded_business_ids)
    }
    if excluded:
        raise ValueError(f"excluded business IDs entered P2 candidate scope: {sorted(excluded)}")
    case_index = [
        {
            "case_key": row["case_key"],
            "family": row["family"],
            "business_id": row["business_id"],
            "fold": row["fold"],
            "crs": row["crs"],
            "segment_count": row["segment_count"],
            "junction_count": row["junction_count"],
            "skeleton_signature": row["skeleton_signature"],
            "frozen_skeleton": str((baseline_root / str(row["frozen_skeleton"])).resolve()),
        }
        for row in case_rows
    ]

    segment_path = run_root / "segment_candidate_index.jsonl"
    node_path = run_root / "node_carrier_options.jsonl"
    case_path = run_root / "case_index.csv"
    _write_jsonl(segment_path, segment_rows)
    _write_jsonl(node_path, node_options)
    write_csv(case_path, case_index, list(case_index[0]))
    signatures = {
        "segments": canonical_sha256(segment_rows),
        "nodes": canonical_sha256(node_options),
        "cases": canonical_sha256(case_index),
        "lineage": canonical_sha256(lineage_rows),
    }
    wall_seconds = time.perf_counter() - started
    summary = {
        "schema_version": "p05-scheme-a-p2-candidate-summary-v1",
        "status": "candidate_scope_passed",
        "case_count": len(case_keys),
        "segment_group_count": len(segment_groups),
        "segment_candidate_count": len(segment_rows),
        "node_option_count": len(node_options),
        "movement_candidate_count": 0,
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "truth_feature_count": 0,
        "skeleton_mutation_count": 0,
        "crs_values": sorted(observed_crs),
        "wall_seconds": wall_seconds,
        "peak_rss_bytes": _rss_bytes(),
        "signatures": signatures,
    }
    summary_path = run_root / "scheme_a_p2_candidate_summary.json"
    write_json(summary_path, summary)
    manifest = {
        "schema_version": "p05-scheme-a-p2-candidate-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "candidate_scope_passed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "poc_data_root": str(config.poc_data_root),
            "excluded_business_ids": list(config.excluded_business_ids),
            "expected_case_count": config.expected_case_count,
            "expected_segment_count": config.expected_segment_count,
            "strict_hashes": config.strict_hashes,
            "enforce_poc_scope": config.enforce_poc_scope,
        },
        "input_manifests": {
            "scheme_a_baseline": output_record(baseline_manifest_path),
            "p1_candidate": output_record(p1_manifest_path),
        },
        "outputs": {
            "segments": output_record(segment_path),
            "nodes": output_record(node_path),
            "case_index": output_record(case_path),
            "summary": output_record(summary_path),
        },
        "signatures": signatures,
        "environment": _environment(),
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "movement_candidate_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = run_root / "scheme_a_p2_candidate_manifest.json"
    write_json(manifest_path, manifest)
    _write_artifact_manifest(run_root, manifest_path)
    return run_root


def solve_scheme_a_p2_oracle_run(config: SchemeAP2OracleConfig) -> Path:
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    candidate_root = normalize_runtime_path(config.candidate_run_root).resolve()
    baseline_root = normalize_runtime_path(config.scheme_a_baseline_run_root).resolve()
    candidate_manifest_path = candidate_root / "scheme_a_p2_candidate_manifest.json"
    baseline_manifest_path = baseline_root / "scheme_a_manifest.json"
    dataset_manifest_path = (
        normalize_runtime_path(config.p1_dataset_run_root).resolve()
        / "scheme_a_p1_dataset_manifest.json"
    )
    candidate_manifest = _read_json(candidate_manifest_path)
    baseline_manifest = _read_json(baseline_manifest_path)
    dataset_manifest = _read_json(dataset_manifest_path)
    _validate_oracle_inputs(config, candidate_manifest, baseline_manifest, dataset_manifest)
    _verify_manifest_outputs(candidate_manifest, ("segments", "nodes", "case_index"), config.strict_hashes)
    _verify_manifest_outputs(dataset_manifest, ("labels",), config.strict_hashes)
    _verify_manifest_outputs(baseline_manifest, ("carrier_labels",), config.strict_hashes)

    groups, _ = load_scheme_a_p1_groups(config.p1_dataset_run_root, strict_hashes=config.strict_hashes)
    segment_groups = [group for group in groups if group.object_type == "SEGMENT"]
    if len(segment_groups) != config.expected_segment_count:
        raise ValueError(f"P2 Oracle Segment denominator mismatch: {len(segment_groups)}")
    segment_rows = _read_jsonl(_record_path(candidate_manifest["outputs"]["segments"]))
    candidates_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidates_by_id: dict[str, dict[str, Any]] = {}
    for row in segment_rows:
        candidates_by_group[str(row["group_id"])].append(row)
        candidates_by_id[str(row["candidate_id"])] = row
    if set(candidates_by_group) != {group.group_id for group in segment_groups}:
        raise ValueError("P2 Oracle Segment candidate scope differs from dataset")

    node_rows = _read_jsonl(_record_path(candidate_manifest["outputs"]["nodes"]))
    node_options: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in node_rows:
        node_options[str(row["case_key"])][str(row["node_id"])].append(row)
    case_rows = _read_csv(_record_path(candidate_manifest["outputs"]["case_index"]))
    skeleton_by_case = {
        str(row["case_key"]): _read_json(normalize_runtime_path(row["frozen_skeleton"]))
        for row in case_rows
    }
    lineage_by_case = _load_lineage(
        _record_path(_read_json(candidate_manifest["input_manifests"]["p1_candidate"]["path"])["outputs"]["lineage"])
    )
    truth_node_paths = _truth_node_paths(
        _record_path(baseline_manifest["outputs"]["carrier_labels"])
    )
    expected_failures = {
        case_key: frozenset(
            {
                f"Road endpoint Node missing: {node_id}",
                f"directed edge endpoint missing: {directed_edge}",
            }
        )
        for case_key, node_id, directed_edge in config.expected_roadgraph_failures
    }

    group_by_id = {group.group_id: group for group in segment_groups}
    predictions_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    initial_clues: list[dict[str, Any]] = []
    for group in segment_groups:
        truth_candidate = group.candidates[group.truth_index]
        raw_candidate = candidates_by_id[truth_candidate.candidate_id]
        reasons = candidate_intrinsic_reasons(
            group.object_tokens,
            raw_candidate.get("source_kinds") or [],
            anomaly_target=group.anomaly_target,
            truth_target=group.truth_target,
        )
        hard_unsafe = bool(reasons)
        decision = select_effective_candidate(
            candidates_by_group[group.group_id],
            selected_candidate_id=truth_candidate.candidate_id,
            confidence=1.0,
            anomaly_probability=float(group.anomaly_target),
            confidence_threshold=0.0,
            anomaly_threshold=0.5,
            hard_unsafe=hard_unsafe,
        )
        prediction = {
            "schema_version": P2_ORACLE_SCHEMA,
            "case_key": group.case_key,
            "group_id": group.group_id,
            "object_type": "SEGMENT",
            "object_id": group.object_id,
            "truth_candidate_id": truth_candidate.candidate_id,
            "truth_target": group.truth_target,
            "selected_candidate_id": truth_candidate.candidate_id,
            "hard_unsafe": hard_unsafe,
            "intrinsic_reasons": reasons,
            "label_only": True,
            **decision,
        }
        predictions_by_case[group.case_key].append(prediction)
        if reasons:
            initial_clues.append(
                _clue(
                    group.case_key,
                    "SEGMENT",
                    group.object_id,
                    "segment_intrinsic_carrier_conflict",
                    reasons,
                    [group.object_id],
                )
            )

    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
    final_predictions: list[dict[str, Any]] = []
    final_junctions: list[dict[str, Any]] = []
    clues = list(initial_clues)
    case_results: list[dict[str, Any]] = []
    case_seconds: list[float] = []
    for case_key in sorted(predictions_by_case):
        case_started = time.perf_counter()
        rows = [dict(row) for row in predictions_by_case[case_key]]
        expected = expected_failures.get(case_key)
        junction_fallback_ids: set[str] = set()
        if expected is not None:
            rows = fallback_case_to_swsd(rows, candidates_by_group, reason="expected_swsd_baseline_failure")
        roadgraph: dict[str, Any] | None = None
        junction_records: list[dict[str, Any]] = []
        node_selection: dict[str, dict[str, Any]] = {}
        node_sources: dict[str, str] = {}
        hard_gate_iterations: list[dict[str, Any]] = []
        for iteration in range(len(rows) + 1):
            solved = _solve_case_node_carriers(
                case_key,
                rows,
                skeleton_by_case[case_key],
                candidates_by_id,
                node_options.get(case_key, {}),
                lineage_by_case[case_key],
                truth_node_paths[case_key],
                junction_fallback_ids=junction_fallback_ids,
                force_swsd=expected is not None,
                vector_cache=vector_cache,
            )
            junction_records = solved["junction_records"]
            node_selection = solved["node_payloads"]
            node_sources = solved["node_sources"]
            failure_groups = set(solved["failure_group_ids"])
            conflict_junctions = set(solved["conflict_junction_ids"])
            if expected is None and failure_groups:
                before = _prediction_state(rows)
                rows, changed = fallback_conflicting_groups_to_swsd(
                    rows,
                    candidates_by_group,
                    failure_groups,
                    reason="junction_unit_node_carrier_conflict",
                )
                for row in rows:
                    if str(row["group_id"]) in failure_groups:
                        row["fallback_unit"] = (
                            "JUNCTION"
                            if set(solved["group_junctions"].get(str(row["group_id"]), []))
                            & conflict_junctions
                            else "SEGMENT"
                        )
                junction_fallback_ids.update(conflict_junctions)
                clues.extend(solved["clues"])
                hard_gate_iterations.append(
                    {
                        "iteration": iteration + 1,
                        "phase": "junction_node_solve",
                        "failure_group_count": len(failure_groups),
                        "junction_conflict_count": len(conflict_junctions),
                        "changed_group_count": changed,
                    }
                )
                if changed and before != _prediction_state(rows):
                    continue
            roadgraph = materialize_case_roadgraph(
                case_key,
                rows,
                candidates_by_id,
                lineage_by_case[case_key],
                vector_cache=vector_cache,
                node_payload_overrides=node_selection,
                node_source_overrides=node_sources,
            )
            if expected is not None or roadgraph["audit"]["legal"]:
                break
            graph_failure_groups = set(roadgraph["audit"]["failure_group_ids"])
            if not graph_failure_groups:
                break
            before = _prediction_state(rows)
            rows, changed = fallback_conflicting_groups_to_swsd(
                rows,
                candidates_by_group,
                graph_failure_groups,
                reason="roadgraph_hard_gate_conflict",
            )
            for row in rows:
                if str(row["group_id"]) in graph_failure_groups:
                    row["fallback_unit"] = "SEGMENT"
            clues.append(
                _clue(
                    case_key,
                    "SEGMENT_SET",
                    canonical_sha256(sorted(graph_failure_groups))[:20],
                    "roadgraph_hard_gate_conflict",
                    roadgraph["audit"]["failures"],
                    [str(row["object_id"]) for row in rows if str(row["group_id"]) in graph_failure_groups],
                )
            )
            hard_gate_iterations.append(
                {
                    "iteration": iteration + 1,
                    "phase": "roadgraph_hard_gate",
                    "failure_group_count": len(graph_failure_groups),
                    "changed_group_count": changed,
                    "roadgraph_signature": roadgraph["roadgraph_signature"],
                }
            )
            if not changed or before == _prediction_state(rows):
                break
        if roadgraph is None:
            raise RuntimeError(f"P2 Oracle did not materialize {case_key}")
        actual_failures = frozenset(str(value) for value in roadgraph["audit"]["failures"])
        if expected is not None:
            expected_match = actual_failures == expected
            terminal_state = "EXPECTED_FAIL" if expected_match else "FAIL"
            failure_groups = set(roadgraph["audit"]["failure_group_ids"])
            clues.append(
                _clue(
                    case_key,
                    "CASE",
                    case_key,
                    "expected_swsd_baseline_roadgraph_failure",
                    sorted(actual_failures),
                    [
                        str(row["object_id"])
                        for row in rows
                        if str(row["group_id"]) in failure_groups
                    ],
                )
            )
        else:
            expected_match = False
            terminal_state = "LEGAL" if roadgraph["audit"]["legal"] else "FAIL"
        roadgraph["audit"].update(
            {
                "terminal_state": terminal_state,
                "publish": terminal_state == "LEGAL",
                "expected_failure_match": expected_match,
                "junction_mainnode_conflict_count": sum(
                    row["status"] == "CONFLICT" for row in junction_records
                ),
                "junction_fallback_count": len(junction_fallback_ids),
                "hard_gate_iterations": hard_gate_iterations,
                "movement_decision_count": 0,
            }
        )
        roadgraph.pop("roadgraph_signature", None)
        roadgraph["roadgraph_signature"] = canonical_sha256(roadgraph)
        token = canonical_sha256({"case_key": case_key})[:20]
        roadgraph_path = run_root / "cases" / token / "roadgraph.json"
        roadgraph_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(roadgraph_path, roadgraph)
        final_predictions.extend(rows)
        fallback_junctions = set(junction_fallback_ids)
        for record in junction_records:
            record["fallback_applied"] = str(record["junction_id"]) in fallback_junctions
            final_junctions.append(record)
        case_seconds.append(time.perf_counter() - case_started)
        case_results.append(
            {
                "case_key": case_key,
                "terminal_state": terminal_state,
                "legal": roadgraph["audit"]["legal"],
                "publish": roadgraph["audit"]["publish"],
                "expected_failure_match": expected_match,
                "failure_count": roadgraph["audit"]["failure_count"],
                "junction_fallback_count": len(junction_fallback_ids),
                "roadgraph_signature": roadgraph["roadgraph_signature"],
                "roadgraph_path": str(roadgraph_path.resolve()),
                "case_wall_seconds": case_seconds[-1],
            }
        )

    final_predictions.sort(key=lambda row: str(row["group_id"]))
    final_junctions.sort(key=lambda row: (str(row["case_key"]), str(row["junction_id"])))
    clues = _deduplicate_clues(clues)
    metrics = _oracle_metrics(config, group_by_id, final_predictions, final_junctions, case_results)
    wall_seconds = time.perf_counter() - started
    resources = {
        "wall_seconds": wall_seconds,
        "case_p95_wall_seconds": _percentile(case_seconds, 0.95),
        "case_max_wall_seconds": max(case_seconds),
        "peak_rss_bytes": _rss_bytes(),
        "gpu_required": False,
    }
    resources["passed"] = (
        resources["case_p95_wall_seconds"] <= 30.0
        and resources["case_max_wall_seconds"] <= 120.0
        and resources["peak_rss_bytes"] <= 16 * 1024**3
        and resources["wall_seconds"] <= 3600.0
    )
    metrics["resource_gate"] = resources["passed"]
    if not metrics["gate3_roadgraph_safety"]:
        decision = "P05_SCHEME_A_P2_P0_SAFETY_NO_GO"
    elif not metrics["gate1_joint_truth"] or not metrics["gate2_carrier_value"]:
        decision = "P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO"
    elif not resources["passed"]:
        decision = "P05_SCHEME_A_P2_P0_SAFETY_NO_GO"
    else:
        decision = "P05_SCHEME_A_P2_P0_GO"
    metrics["decision"] = decision

    segment_path = run_root / "segment_joint_truth.jsonl"
    junction_path = run_root / "junction_node_selection.jsonl"
    clue_path = run_root / "reality_change_clues.jsonl"
    case_path = run_root / "case_results.csv"
    summary_path = run_root / "scheme_a_p2_oracle_summary.json"
    resource_path = run_root / "resource_audit.json"
    report_path = run_root / "validation_report.md"
    _write_jsonl(segment_path, final_predictions)
    _write_jsonl(junction_path, final_junctions)
    _write_jsonl(clue_path, clues)
    write_csv(case_path, case_results, list(case_results[0]))
    write_json(summary_path, metrics)
    write_json(resource_path, resources)
    report_path.write_text(_validation_report(metrics), encoding="utf-8")
    signatures = {
        "segments": canonical_sha256(final_predictions),
        "junctions": canonical_sha256(final_junctions),
        "clues": canonical_sha256(clues),
        "roadgraphs": canonical_sha256(
            [
                {key: row[key] for key in ("case_key", "terminal_state", "roadgraph_signature")}
                for row in case_results
            ]
        ),
        "metrics": canonical_sha256(
            {key: value for key, value in metrics.items() if key != "resource_gate"}
        ),
    }
    manifest = {
        "schema_version": "p05-scheme-a-p2-oracle-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "completed",
        "decision": decision,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_manifests": {
            "p2_candidate": output_record(candidate_manifest_path),
            "p1_dataset": output_record(dataset_manifest_path),
            "scheme_a_baseline": output_record(baseline_manifest_path),
        },
        "outputs": {
            "segments": output_record(segment_path),
            "junctions": output_record(junction_path),
            "clues": output_record(clue_path),
            "cases": output_record(case_path),
            "summary": output_record(summary_path),
            "resources": output_record(resource_path),
            "report": output_record(report_path),
        },
        "signatures": signatures,
        "environment": _environment(),
        "label_only": True,
        "movement_decision_count": 0,
        "skeleton_mutation_count": 0,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = run_root / "scheme_a_p2_oracle_manifest.json"
    write_json(manifest_path, manifest)
    _write_artifact_manifest(run_root, manifest_path)
    return run_root


def candidate_intrinsic_reasons(
    object_tokens: Iterable[str],
    source_kinds: Iterable[str],
    *,
    anomaly_target: bool,
    truth_target: str,
) -> list[str]:
    tokens = set(object_tokens)
    reasons: list[str] = []
    if "ACCESS_VALID:False" in tokens:
        reasons.append("access_invalid")
    if "INDEPENDENT_ROAD_VALID:False" in tokens:
        reasons.append("independent_road_invalid")
    proposal_selected = "REGISTERED_STRATEGY_PROPOSAL" in set(source_kinds)
    if proposal_selected:
        for prefix, reason in (
            ("PROPOSAL_ACCESS_MISSING_COUNT:", "proposal_access_missing"),
            ("PROPOSAL_ROAD_MISSING_COUNT:", "proposal_road_missing"),
        ):
            if any(token.startswith(prefix) and not token.endswith(":0") for token in tokens):
                reasons.append(reason)
    if anomaly_target or truth_target == "REVIEW_FALLBACK":
        reasons.append("labelled_unsafe")
    return sorted(set(reasons))


def choose_common_node_options(
    required_node_ids: Sequence[str],
    options_by_node: Mapping[str, Sequence[Mapping[str, Any]]],
    target_signatures: Mapping[str, str],
    *,
    junction_id: str,
    source_role: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]], str]:
    allowed_by_node: dict[str, list[dict[str, Any]]] = {}
    for node_id in sorted(set(required_node_ids)):
        options = [dict(row) for row in options_by_node.get(node_id, [])]
        if source_role is not None:
            options = [row for row in options if row.get("source_role") == source_role]
        target = target_signatures.get(node_id, "")
        if target:
            options = [row for row in options if row.get("semantic_signature") == target]
        if not options:
            return "", {}, f"node_candidate_missing:{node_id}"
        allowed_by_node[node_id] = options
    common_keys: set[str] | None = None
    for options in allowed_by_node.values():
        keys = {str(row["mainnode_key"]) for row in options}
        common_keys = keys if common_keys is None else common_keys & keys
    if not common_keys:
        return "", {}, "no_common_mainnode_key"
    selected_key = min(
        common_keys,
        key=lambda key: (
            key != junction_id,
            -sum(
                any(
                    row.get("mainnode_key") == key
                    and row.get("semantic_signature") == target_signatures.get(node_id)
                    for row in options
                )
                for node_id, options in allowed_by_node.items()
            ),
            key,
        ),
    )
    selected: dict[str, dict[str, Any]] = {}
    for node_id, options in allowed_by_node.items():
        selected[node_id] = min(
            [row for row in options if str(row["mainnode_key"]) == selected_key],
            key=lambda row: (
                row.get("semantic_signature") != target_signatures.get(node_id),
                row.get("source_role") != source_role if source_role else False,
                str(row["candidate_id"]),
            ),
        )
    return selected_key, selected, ""


def _solve_case_node_carriers(
    case_key: str,
    predictions: Sequence[Mapping[str, Any]],
    skeleton: Mapping[str, Any],
    candidates_by_id: Mapping[str, Mapping[str, Any]],
    node_options: Mapping[str, Sequence[Mapping[str, Any]]],
    lineage_by_role: Mapping[str, str],
    truth_node_path: str,
    *,
    junction_fallback_ids: set[str],
    force_swsd: bool,
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> dict[str, Any]:
    prediction_by_segment = {str(row["object_id"]): row for row in predictions}
    group_by_segment = {
        str(row["object_id"]): str(row["group_id"]) for row in predictions
    }
    segment_endpoints: dict[str, set[str]] = defaultdict(set)
    endpoint_groups: dict[str, set[str]] = defaultdict(set)
    endpoint_road_roles: dict[str, Counter[str]] = defaultdict(Counter)
    failure_group_ids: set[str] = set()
    clues: list[dict[str, Any]] = []
    for segment_id, row in prediction_by_segment.items():
        candidate = candidates_by_id[str(row["effective_candidate_id"])]
        road_role = (
            "proposal_roads"
            if row.get("effective_source_kind") == "REGISTERED_STRATEGY_PROPOSAL"
            else "t01_roads"
        )
        roads, _ = _read_vector(lineage_by_role[road_role], vector_cache)
        for road_id in candidate.get("target_payload") or []:
            road = roads.get(str(road_id))
            if road is None:
                failure_group_ids.add(str(row["group_id"]))
                clues.append(
                    _clue(
                        case_key,
                        "SEGMENT",
                        segment_id,
                        "selected_road_payload_missing",
                        [str(road_id), road_role],
                        [segment_id],
                    )
                )
                continue
            properties = dict(road.get("properties") or {})
            for node_id in (
                _text(_property(properties, "snodeid")),
                _text(_property(properties, "enodeid")),
            ):
                if not node_id:
                    continue
                segment_endpoints[segment_id].add(node_id)
                endpoint_groups[node_id].add(str(row["group_id"]))
                endpoint_road_roles[node_id][road_role] += 1

    truth_nodes, truth_crs = _read_vector(truth_node_path, vector_cache)
    if _canonical_crs(truth_crs) != "EPSG:3857":
        raise ValueError(f"truth Node CRS mismatch for {case_key}")
    truth_signatures = {
        node_id: _semantic_payload_signature(payload)
        for node_id, payload in truth_nodes.items()
    }
    relations_by_junction: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for relation in skeleton.get("junction_segment_relations") or []:
        relations_by_junction[str(relation["junction_id"])].append(relation)
    junction_ids = {
        str(row["junction_id"]) for row in skeleton.get("junctions") or []
    } | set(relations_by_junction)
    selected_options: dict[str, dict[str, Any]] = {}
    junction_records: list[dict[str, Any]] = []
    conflict_junction_ids: set[str] = set()
    group_junctions: dict[str, set[str]] = defaultdict(set)
    assigned_junction: dict[str, str] = {}
    for junction_id in sorted(junction_ids):
        relations = relations_by_junction.get(junction_id, [])
        related_segments = sorted(
            {
                str(relation["segment_id"])
                for relation in relations
                if str(relation["segment_id"]) in prediction_by_segment
            }
        )
        required_nodes: set[str] = set()
        relation_missing_segments: set[str] = set()
        for relation in relations:
            segment_id = str(relation["segment_id"])
            if segment_id not in prediction_by_segment:
                continue
            group_id = group_by_segment[segment_id]
            group_junctions[group_id].add(junction_id)
            access = {str(value) for value in relation.get("access_node_ids") or []}
            matched = set()
            for node_id in segment_endpoints.get(segment_id, set()):
                keys = {
                    str(option["mainnode_key"])
                    for option in node_options.get(node_id, [])
                }
                if node_id == junction_id or node_id in access or junction_id in keys:
                    matched.add(node_id)
            if not matched:
                relation_missing_segments.add(segment_id)
            required_nodes.update(matched)
        if not required_nodes and not related_segments:
            junction_records.append(
                {
                    "schema_version": P2_ORACLE_SCHEMA,
                    "case_key": case_key,
                    "junction_id": junction_id,
                    "status": "NO_SELECTED_ACCESS",
                    "mainnode_key": "",
                    "required_node_ids": [],
                    "selected_node_candidate_ids": [],
                    "related_segment_ids": [],
                    "label_only": True,
                }
            )
            continue
        if relation_missing_segments and not force_swsd:
            affected_groups = {
                group_by_segment[segment_id]
                for segment_id in relation_missing_segments
            }
            failure_group_ids.update(affected_groups)
            clues.append(
                _clue(
                    case_key,
                    "SEGMENT_SET",
                    junction_id,
                    "junction_relation_access_missing",
                    sorted(relation_missing_segments),
                    sorted(relation_missing_segments),
                )
            )
        source_role = (
            "t01_nodes"
            if force_swsd or junction_id in junction_fallback_ids
            else None
        )
        target = {} if source_role else truth_signatures
        key, choices, reason = choose_common_node_options(
            sorted(required_nodes),
            node_options,
            target,
            junction_id=junction_id,
            source_role=source_role,
        )
        status = "SELECTED"
        if reason:
            status = "CONFLICT"
            conflict_junction_ids.add(junction_id)
            affected_groups = {
                group_by_segment[segment_id] for segment_id in related_segments
            }
            if not force_swsd:
                failure_group_ids.update(affected_groups)
            clues.append(
                _clue(
                    case_key,
                    "JUNCTION",
                    junction_id,
                    "junction_node_carrier_conflict",
                    [reason, *sorted(required_nodes)],
                    related_segments,
                )
            )
        else:
            for node_id, option in choices.items():
                previous = selected_options.get(node_id)
                if previous is not None and previous["candidate_id"] != option["candidate_id"]:
                    status = "CONFLICT"
                    conflict_junction_ids.update(
                        {junction_id, assigned_junction.get(node_id, junction_id)}
                    )
                    affected_groups = {
                        group_by_segment[segment_id] for segment_id in related_segments
                    }
                    if not force_swsd:
                        failure_group_ids.update(affected_groups)
                    clues.append(
                        _clue(
                            case_key,
                            "JUNCTION",
                            junction_id,
                            "shared_node_selected_twice",
                            [node_id, previous["candidate_id"], option["candidate_id"]],
                            related_segments,
                        )
                    )
                selected_options[node_id] = option
                assigned_junction[node_id] = junction_id
        junction_records.append(
            {
                "schema_version": P2_ORACLE_SCHEMA,
                "case_key": case_key,
                "junction_id": junction_id,
                "status": status,
                "mainnode_key": key,
                "required_node_ids": sorted(required_nodes),
                "selected_node_candidate_ids": sorted(
                    str(row["candidate_id"]) for row in choices.values()
                ),
                "related_segment_ids": related_segments,
                "label_only": True,
            }
        )

    all_endpoints = set(endpoint_groups)
    for node_id in sorted(all_endpoints - set(selected_options)):
        role = (
            "proposal_nodes"
            if endpoint_road_roles[node_id]["proposal_roads"]
            > endpoint_road_roles[node_id]["t01_roads"]
            else "t01_nodes"
        )
        target = {} if force_swsd else truth_signatures
        _, choice, reason = choose_common_node_options(
            [node_id],
            node_options,
            target,
            junction_id=node_id,
            source_role="t01_nodes" if force_swsd else None,
        )
        if reason:
            if force_swsd and node_id not in node_options:
                continue
            failure_group_ids.update(endpoint_groups[node_id])
            clues.append(
                _clue(
                    case_key,
                    "NODE",
                    node_id,
                    "endpoint_node_carrier_missing",
                    [reason, role],
                    sorted(endpoint_groups[node_id]),
                )
            )
            continue
        selected_options.update(choice)

    payloads: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    for node_id, option in selected_options.items():
        source_payloads, source_crs = _read_vector(str(option["source_path"]), vector_cache)
        if _canonical_crs(source_crs) != "EPSG:3857":
            raise ValueError(f"P2 Node option CRS mismatch for {case_key}/{node_id}")
        payload = source_payloads.get(node_id)
        if payload is None or _semantic_payload_signature(payload) != option["semantic_signature"]:
            failure_group_ids.update(endpoint_groups.get(node_id, set()))
            clues.append(
                _clue(
                    case_key,
                    "NODE",
                    node_id,
                    "node_option_payload_drift",
                    [str(option["candidate_id"])],
                    sorted(endpoint_groups.get(node_id, set())),
                )
            )
            continue
        payloads[node_id] = payload
        sources[node_id] = str(option["source_role"])
    return {
        "node_payloads": payloads,
        "node_sources": sources,
        "junction_records": junction_records,
        "failure_group_ids": sorted(failure_group_ids),
        "conflict_junction_ids": sorted(conflict_junction_ids),
        "group_junctions": {
            key: sorted(value) for key, value in group_junctions.items()
        },
        "clues": clues,
    }


def _oracle_metrics(
    config: SchemeAP2OracleConfig,
    groups: Mapping[str, P1GroupExample],
    predictions: Sequence[Mapping[str, Any]],
    junctions: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    prediction_by_id = {str(row["group_id"]): row for row in predictions}
    if set(prediction_by_id) != set(groups):
        raise ValueError("P2 Oracle prediction denominator differs")
    exact = 0
    use_total = use_exact = 0
    keep_total = keep_wrong = 0
    wrong_rcsd_replace = 0
    unsafe_advance_published = 0
    decision_counts: Counter[str] = Counter()
    fallback_units: Counter[str] = Counter()
    for group_id, group in groups.items():
        row = prediction_by_id[group_id]
        safe_exact = (
            not group.anomaly_target
            and str(row["effective_candidate_id"]) == str(row["truth_candidate_id"])
        )
        exact += safe_exact
        decision_counts[str(row["decision"])] += 1
        if row["decision"] != "PUBLISH_CANDIDATE":
            fallback_units[str(row.get("fallback_unit") or "SEGMENT")] += 1
        if group.truth_target == "USE_RCSD":
            use_total += 1
            use_exact += safe_exact
        if group.truth_target == "KEEP_SWSD":
            keep_total += 1
            wrong = str(row["effective_candidate_target"]) != "KEEP_SWSD"
            keep_wrong += wrong
            wrong_rcsd_replace += wrong
        tokens = set(group.object_tokens)
        unsafe_advance_published += (
            "SEGMENT_TYPE:ADVANCE_RIGHT" in tokens
            and "ACCESS_VALID:False" in tokens
            and row["decision"] == "PUBLISH_CANDIDATE"
        )
    joint_coverage = exact / max(1, len(groups))
    use_retention = use_exact / max(1, use_total)
    expected_cases = sorted(row[0] for row in config.expected_roadgraph_failures)
    terminal_counts = Counter(str(row["terminal_state"]) for row in cases)
    actual_expected = sorted(
        str(row["case_key"]) for row in cases if row["terminal_state"] == "EXPECTED_FAIL"
    )
    unexpected = sorted(
        str(row["case_key"]) for row in cases if row["terminal_state"] == "FAIL"
    )
    junction_conflicts = sum(row["status"] == "CONFLICT" for row in junctions)
    gate1 = (
        len(groups) == config.expected_segment_count
        and len(junctions) >= 1
        and all(row["status"] in {"SELECTED", "NO_SELECTED_ACCESS", "CONFLICT"} for row in junctions)
    )
    gate2 = (
        joint_coverage >= config.min_joint_truth_exact_coverage
        and use_retention >= config.min_use_rcsd_retention
        and keep_wrong == 0
        and wrong_rcsd_replace == 0
        and unsafe_advance_published == 0
    )
    gate3 = (
        len(cases) == config.expected_case_count
        and terminal_counts["LEGAL"] == config.expected_case_count - len(expected_cases)
        and actual_expected == expected_cases
        and not unexpected
    )
    return {
        "schema_version": "p05-scheme-a-p2-oracle-summary-v1",
        "case_count": len(cases),
        "segment_count": len(groups),
        "movement_candidate_count": 0,
        "movement_decision_count": 0,
        "movement_evaluation_count": 0,
        "joint_truth_exact_count": exact,
        "joint_truth_exact_coverage": joint_coverage,
        "use_rcsd_truth_count": use_total,
        "use_rcsd_retained_count": use_exact,
        "use_rcsd_truth_retention": use_retention,
        "keep_swsd_truth_count": keep_total,
        "keep_swsd_wrong_replace_count": keep_wrong,
        "wrong_rcsd_replace_count": wrong_rcsd_replace,
        "unsafe_advance_right_published_count": unsafe_advance_published,
        "decision_counts": dict(sorted(decision_counts.items())),
        "fallback_unit_counts": dict(sorted(fallback_units.items())),
        "junction_record_count": len(junctions),
        "junction_conflict_record_count": junction_conflicts,
        "roadgraph_terminal_counts": dict(sorted(terminal_counts.items())),
        "roadgraph_expected_failure_case_keys": actual_expected,
        "roadgraph_unexpected_failure_case_keys": unexpected,
        "gate0_scope_and_isolation": len(groups) == config.expected_segment_count,
        "gate1_joint_truth": gate1,
        "gate2_carrier_value": gate2,
        "gate3_roadgraph_safety": gate3,
        "truth_feature_count": 0,
        "skeleton_mutation_count": 0,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _validate_candidate_inputs(
    config: SchemeAP2CandidateConfig,
    baseline: Mapping[str, Any],
    p1: Mapping[str, Any],
) -> None:
    if baseline.get("status") != "passed" or p1.get("status") != "candidate_scope_passed":
        raise ValueError("P2 candidate requires passed Scheme A/P1 candidate inputs")
    counts = baseline.get("counts") or {}
    if int(counts.get("case_count", -1)) != config.expected_case_count:
        raise ValueError("Scheme A baseline Case count mismatch")
    if int(counts.get("segment_count", -1)) != config.expected_segment_count:
        raise ValueError("Scheme A baseline Segment count mismatch")
    if p1.get("truth_input_count") or p1.get("truth_derived_candidate_count"):
        raise ValueError("P1 candidate is not truth-free")


def _validate_oracle_inputs(
    config: SchemeAP2OracleConfig,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> None:
    if candidate.get("status") != "candidate_scope_passed":
        raise ValueError("P2 candidate run has not passed")
    if candidate.get("truth_input_count") or candidate.get("truth_derived_candidate_count"):
        raise ValueError("P2 candidate run is not truth-free")
    if candidate.get("movement_candidate_count") != 0:
        raise ValueError("Movement entered the P2 candidate run")
    if baseline.get("status") != "passed" or dataset.get("status") != "dataset_passed":
        raise ValueError("P2 Oracle requires passed baseline/dataset inputs")
    if int(baseline.get("counts", {}).get("segment_count", -1)) != config.expected_segment_count:
        raise ValueError("P2 Oracle Segment count mismatch")


def _truth_node_paths(label_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with label_path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            for lineage in row.get("lineage") or []:
                if lineage.get("role") == "t06_frcsd_node_truth":
                    result[str(row["case_key"])] = str(lineage["path"])
    return result


def _read_lineage_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, str]]]]:
    rows = _read_csv(path)
    by_case: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        if str(row.get("label_only")).lower() == "true" or str(row.get("truth_derived")).lower() == "true":
            raise ValueError("truth lineage entered P2 candidate")
        by_case[str(row["case_key"])][str(row["role"])] = {
            "path": str(row["path"]),
            "sha256": str(row["sha256"]),
        }
    return rows, by_case


def _verify_manifest_outputs(
    manifest: Mapping[str, Any], roles: Sequence[str], strict_hashes: bool
) -> None:
    for role in roles:
        record = manifest.get("outputs", {}).get(role)
        if record is None:
            raise ValueError(f"manifest output missing: {role}")
        path = _record_path(record)
        if not path.is_file():
            raise FileNotFoundError(path)
        if strict_hashes and sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"manifest output hash mismatch: {role}")


def _write_artifact_manifest(run_root: Path, manifest_path: Path) -> None:
    rows = [
        {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(run_root.rglob("*"))
        if path.is_file() and path.name != "artifact_manifest.json"
    ]
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-artifact-manifest-v1",
            "run_manifest": output_record(manifest_path),
            "artifacts": rows,
        },
    )


def _record_path(record: Mapping[str, Any] | str) -> Path:
    value = record if isinstance(record, str) else record["path"]
    return normalize_runtime_path(value).resolve()


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(normalize_runtime_path(path).read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            target.write("\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        return list(csv.DictReader(source))


def _prediction_state(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha256(
        [
            {
                "group_id": row["group_id"],
                "decision": row["decision"],
                "effective_candidate_id": row["effective_candidate_id"],
            }
            for row in sorted(rows, key=lambda item: str(item["group_id"]))
        ]
    )


def _clue(
    case_key: str,
    object_type: str,
    object_id: str,
    reason: str,
    evidence: Iterable[Any],
    affected_segments: Iterable[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": "p05-scheme-a-p2-reality-change-clue-v1",
        "case_key": case_key,
        "object_type": object_type,
        "object_id": object_id,
        "reason": reason,
        "evidence": [str(value) for value in evidence],
        "affected_segment_ids": sorted({str(value) for value in affected_segments}),
        "label_only": True,
        "content_repair": False,
        "silent_fix": False,
    }
    payload["clue_id"] = "sap2c:" + canonical_sha256(payload)[:24]
    return payload


def _deduplicate_clues(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row["clue_id"]): dict(row) for row in rows}
    return [by_id[key] for key in sorted(by_id)]


def _percentile(values: Sequence[float], ratio: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * ratio)))
    return ordered[index]


def _validation_report(summary: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# P05-Scheme-A-P2-P0 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- Case: `{summary['case_count']}`",
            f"- Segment: `{summary['segment_count']}`",
            f"- joint truth exact coverage: `{summary['joint_truth_exact_coverage']:.6f}`",
            f"- USE_RCSD truth retention: `{summary['use_rcsd_truth_retention']:.6f}`",
            f"- RoadGraph terminals: `{summary['roadgraph_terminal_counts']}`",
            f"- Gate 1 joint truth: `{summary['gate1_joint_truth']}`",
            f"- Gate 2 carrier value: `{summary['gate2_carrier_value']}`",
            f"- Gate 3 RoadGraph safety: `{summary['gate3_roadgraph_safety']}`",
            f"- resource gate: `{summary['resource_gate']}`",
            "",
        ]
    )


__all__ = [
    "build_scheme_a_p2_candidate_run",
    "candidate_intrinsic_reasons",
    "choose_common_node_options",
    "solve_scheme_a_p2_oracle_run",
]
