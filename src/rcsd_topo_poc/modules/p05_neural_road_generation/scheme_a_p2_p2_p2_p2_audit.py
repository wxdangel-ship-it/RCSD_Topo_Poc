from __future__ import annotations

import csv
import json
import platform
import sys
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_dataset import (
    _load_segment_candidates,
    _load_segment_labels,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_node_carriers import (
    build_endpoint_node_carriers,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p2_models import (
    CLUE_MISS_ONLY,
    DECISION_AUDIT_NO_GO,
    DECISION_HIERARCHICAL_ROUTE_GO,
    DECISION_PARTIAL_ROUTE_NO_MODEL_GO,
    DECISION_SOURCE_CONTRACT_BLOCKED,
    ROAD_CARRIER_UNSAFE,
    SAFE_AND_VISIBLE,
    SCHEME_A_P2_P2_P2_P2_SCHEMA,
    SchemeAP2P2P2P2Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p2_p2_p2_audit(config: SchemeAP2P2P2P2Config) -> Path:
    started = time.perf_counter()
    p0_root = _resolve_dir(config.p2_p2_p2_p0_run_root)
    p1_root = _resolve_dir(config.p2_p2_p2_p1_run_root)
    dataset_root = _resolve_dir(config.p2_p1_dataset_run_root)
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    manifests, paths, input_records = _load_inputs(
        config=config,
        p0_root=p0_root,
        p1_root=p1_root,
        dataset_root=dataset_root,
    )
    evaluation_rows = list(_read_jsonl(paths["p0_evaluation"]))
    metric_rows = reinterpret_probe_metrics(
        evaluation_rows,
        expected_fold_count=config.expected_fold_count,
        minimum_safe_coverage=config.minimum_safe_coverage,
        minimum_use_rcsd_safe_coverage=config.minimum_use_rcsd_safe_coverage,
    )

    blocked = [
        row
        for row in _read_jsonl(paths["p1_attribution"])
        if row.get("terminal_class") == "SOURCE_FACT_BLOCKED"
    ]
    if len(blocked) != config.expected_blocked_object_count:
        raise ValueError("blocked-object denominator differs")
    target_group_ids = {str(row["group_id"]) for row in blocked}
    candidate_options = _target_candidate_options(
        paths["p1_candidates"], target_group_ids
    )
    source_routes = [
        build_object_source_route(row, candidate_options[str(row["group_id"])])
        for row in blocked
    ]
    class_counts = Counter(str(row["business_class"]) for row in source_routes)
    if class_counts != Counter(
        {
            ROAD_CARRIER_UNSAFE: config.expected_carrier_error_count,
            CLUE_MISS_ONLY: config.expected_clue_miss_only_count,
        }
    ):
        raise ValueError("blocked-object business-class denominator differs")

    source_ledger = _source_candidate_ledger(paths["module_role_contract"])
    source_contract_blocked = any(
        bool(row["proposed_inference_input"]) and bool(row["label_only"])
        for row in source_ledger
    )
    if source_contract_blocked:
        raise ValueError("label-only source was promoted to inference input")

    junction_rows, junction_summary = _junction_dependency_audit(
        config=config,
        paths=paths,
    )
    if junction_summary["initial_node_payload_conflict_count"] != (
        config.expected_initial_node_conflict_count
    ):
        raise ValueError("initial Node payload conflict denominator differs")
    if junction_summary["junction_fallback_segment_count"] != (
        config.expected_junction_fallback_segment_count
    ):
        raise ValueError("Junction fallback Segment denominator differs")

    route_gaps = [
        row["group_id"]
        for row in source_routes
        if not row["candidate_truth_reachable"] or not row["pre_t06_supervision_route"]
    ]
    shallow = next(row for row in metric_rows if row["probe"] == "SHALLOW_MLP")
    all_folds_pass = bool(shallow["cross_case_gate_pass"])
    roadgraph_pass = bool(
        _read_json(paths["p0_summary"])["probe_results"][1]["roadgraph_gate_pass"]
    )
    audit_gate = not route_gaps and not source_contract_blocked
    if not audit_gate:
        decision = DECISION_SOURCE_CONTRACT_BLOCKED
    elif all_folds_pass and roadgraph_pass:
        decision = DECISION_HIERARCHICAL_ROUTE_GO
    else:
        decision = DECISION_PARTIAL_ROUTE_NO_MODEL_GO

    deterministic_payload = {
        "schema_version": SCHEME_A_P2_P2_P2_P2_SCHEMA,
        "decision": decision,
        "metric_reinterpretation": metric_rows,
        "object_source_routes": source_routes,
        "junction_dependency_audit": junction_rows,
        "junction_summary": junction_summary,
        "source_candidate_ledger": source_ledger,
        "route_gaps": route_gaps,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)

    metric_path = run_root / "metric_reinterpretation.json"
    route_path = run_root / "object_source_routes.jsonl"
    junction_path = run_root / "junction_dependency_audit.jsonl"
    source_path = run_root / "source_candidate_ledger.jsonl"
    write_json(metric_path, {"probes": metric_rows})
    _write_jsonl(route_path, source_routes)
    _write_jsonl(junction_path, junction_rows)
    _write_jsonl(source_path, source_ledger)

    p0_summary = _read_json(paths["p0_summary"])
    summary = {
        "schema_version": SCHEME_A_P2_P2_P2_P2_SCHEMA,
        "decision": decision,
        "case_count": config.expected_case_count,
        "segment_count": config.expected_segment_count,
        "blocked_object_count": len(source_routes),
        "business_class_counts": dict(sorted(class_counts.items())),
        "candidate_truth_reachable_count": sum(
            bool(row["candidate_truth_reachable"]) for row in source_routes
        ),
        "pre_t06_supervision_route_count": sum(
            bool(row["pre_t06_supervision_route"]) for row in source_routes
        ),
        "no_use_candidate_safe_keep_count": sum(
            row["source_route"] == "CANDIDATE_ABSENCE_SAFE_KEEP_PLUS_CLUE_HEAD"
            for row in source_routes
        ),
        "mixed_candidate_scoring_error_count": sum(
            row["source_route"] == "MIXED_CARRIER_CANDIDATE_SCORING"
            for row in source_routes
        ),
        "junction_dependency_object_count": sum(
            row["source_route"] == "HIERARCHICAL_JUNCTION_CONSISTENCY"
            for row in source_routes
        ),
        "junction": junction_summary,
        "metric_reinterpretation": metric_rows,
        "shallow_mlp_corrected_cross_case_gate_pass": all_folds_pass,
        "shallow_mlp_corrected_fold_pass_count": shallow["fold_pass_count"],
        "roadgraph_gate_pass": roadgraph_pass,
        "roadgraph_metrics": p0_summary["probe_results"][1]["roadgraph_metrics"],
        "source_contract_blocked": source_contract_blocked,
        "route_gap_count": len(route_gaps),
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "training_performed": False,
        "threshold_tuning_performed": False,
        "candidate_reselection_performed": False,
        "geometry_modified": False,
        "coordinate_transform_performed": False,
        "silent_fix": False,
        "content_repair": False,
        "skeleton_mutation_count": 0,
        "t01_t12_modification_count": 0,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "resource": _resource_summary(started),
    }
    summary_path = run_root / "scheme_a_p2_p2_p2_p2_summary.json"
    write_json(summary_path, summary)
    report_path = run_root / "validation_report.md"
    report_path.write_text(_validation_report(summary), encoding="utf-8", newline="\n")

    outputs = {
        "metric_reinterpretation": output_record(metric_path),
        "object_source_routes": output_record(route_path),
        "junction_dependency_audit": output_record(junction_path),
        "source_candidate_ledger": output_record(source_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": f"{SCHEME_A_P2_P2_P2_P2_SCHEMA}-manifest",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "audit_completed",
        "decision": decision,
        "input_manifests": input_records,
        "outputs": outputs,
        "counts": {
            "case_count": config.expected_case_count,
            "segment_count": config.expected_segment_count,
            "blocked_object_count": len(source_routes),
            "business_class_counts": dict(sorted(class_counts.items())),
            **junction_summary,
        },
        "training_performed": False,
        "threshold_tuning_performed": False,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "skeleton_mutation_count": 0,
        "silent_fix": False,
        "content_repair": False,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
    }
    manifest_path = run_root / "scheme_a_p2_p2_p2_p2_manifest.json"
    write_json(manifest_path, manifest)
    artifact_manifest = {
        "schema_version": "p05-artifact-manifest-v1",
        "run_id": config.run_id,
        "artifacts": [output_record(manifest_path), *outputs.values()],
    }
    write_json(run_root / "artifact_manifest.json", artifact_manifest)
    return run_root


def reinterpret_probe_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_fold_count: int,
    minimum_safe_coverage: float,
    minimum_use_rcsd_safe_coverage: float,
) -> list[dict[str, Any]]:
    probes = sorted({str(row["probe"]) for row in rows})
    results: list[dict[str, Any]] = []
    for probe in probes:
        probe_rows = [row for row in rows if str(row["probe"]) == probe]
        fold_metrics = []
        for fold in range(expected_fold_count):
            held = [row for row in probe_rows if int(row["fold"]) == fold]
            if not held:
                raise ValueError(f"missing held-out fold {probe}/{fold}")
            fold_metrics.append(
                _reinterpret_metric_group(
                    held,
                    probe=probe,
                    fold=fold,
                    minimum_safe_coverage=minimum_safe_coverage,
                    minimum_use_rcsd_safe_coverage=minimum_use_rcsd_safe_coverage,
                )
            )
        overall = _reinterpret_metric_group(
            probe_rows,
            probe=probe,
            fold=None,
            minimum_safe_coverage=minimum_safe_coverage,
            minimum_use_rcsd_safe_coverage=minimum_use_rcsd_safe_coverage,
        )
        results.append(
            {
                "probe": probe,
                "fold_metrics": fold_metrics,
                "overall_metrics": overall,
                "fold_pass_count": sum(bool(row["gate_pass"]) for row in fold_metrics),
                "cross_case_gate_pass": all(
                    bool(row["gate_pass"]) for row in fold_metrics
                ),
            }
        )
    return results


def classify_business_outcome(row: Mapping[str, Any]) -> str:
    if not bool(row["proposal_correct"]) or bool(row["review_target"]):
        return ROAD_CARRIER_UNSAFE
    if bool(row["anomaly_target"]):
        return CLUE_MISS_ONLY
    return SAFE_AND_VISIBLE


def build_object_source_route(
    attribution: Mapping[str, Any],
    candidate_targets: Sequence[str],
) -> dict[str, Any]:
    targets = sorted(set(map(str, candidate_targets)))
    truth_target = str(attribution["truth_target"])
    direct_cause = str(attribution["direct_cause_code"])
    if direct_cause == "T06_RCSD_CARRIER_ROAD_MISSING":
        route = "CANDIDATE_ABSENCE_SAFE_KEEP_PLUS_CLUE_HEAD"
        supervision = ["T03_T04_NODE_EVIDENCE_AUXILIARY", "T06_CLUE_LABEL"]
        inference = ["TRUTH_FREE_CANDIDATE_SET", "P05_CLUE_HEAD"]
    elif direct_cause == "T06_SEGMENT_RELATION_CARRIER_TRUTH":
        route = "MIXED_CARRIER_CANDIDATE_SCORING"
        supervision = ["T05_RELATION_AUXILIARY", "T06_MIXED_CARRIER_LABEL"]
        inference = ["TRUTH_FREE_MIXED_CANDIDATE", "P05_CARRIER_SCORER"]
    elif direct_cause == "TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE":
        route = "HIERARCHICAL_JUNCTION_CONSISTENCY"
        supervision = [
            "T03_T04_NODE_EVIDENCE_AUXILIARY",
            "T06_SEGMENT_CARRIER_LABEL",
        ]
        inference = [
            "P05_SEGMENT_CARRIER_SCORER",
            "GENERIC_NODE_COMPATIBILITY",
            "GENERIC_JUNCTION_CLOSURE",
        ]
    else:
        route = "UNRESOLVED_SOURCE_ROUTE"
        supervision = []
        inference = []
    return {
        "schema_version": SCHEME_A_P2_P2_P2_P2_SCHEMA,
        "case_key": str(attribution["case_key"]),
        "group_id": str(attribution["group_id"]),
        "object_id": str(attribution["object_id"]),
        "population": str(attribution["population"]),
        "business_class": classify_business_outcome(attribution),
        "proposal_target": str(attribution["proposal_target"]),
        "truth_target": truth_target,
        "anomaly_target": bool(attribution["anomaly_target"]),
        "direct_cause_code": direct_cause,
        "candidate_targets": targets,
        "candidate_truth_reachable": truth_target in targets,
        "source_route": route,
        "pre_t06_supervision_route": bool(supervision),
        "supervision_only_sources": supervision,
        "inference_route_components": inference,
        "label_only_promoted_to_inference": False,
        "movement_used": False,
        "truth_used_for_audit_only": True,
        "lineage": attribution.get("lineage", []),
    }


def _reinterpret_metric_group(
    rows: Sequence[Mapping[str, Any]],
    *,
    probe: str,
    fold: int | None,
    minimum_safe_coverage: float,
    minimum_use_rcsd_safe_coverage: float,
) -> dict[str, Any]:
    carrier_unsafe = [
        row
        for row in rows
        if not bool(row["proposal_correct"]) or bool(row["review_target"])
    ]
    anomaly = [row for row in rows if bool(row["anomaly_target"])]
    use = [row for row in rows if str(row["truth_target"]) == "USE_RCSD"]
    accepted = [row for row in rows if bool(row["accepted"])]
    carrier_wrong_accepted = sum(
        bool(row["accepted"]) and not bool(row["proposal_correct"]) for row in rows
    )
    review_auto = sum(
        bool(row["accepted"]) and bool(row["review_target"]) for row in rows
    )
    clue_miss_only = sum(
        bool(row["accepted"])
        and bool(row["proposal_correct"])
        and not bool(row["review_target"])
        for row in anomaly
    )
    carrier_recall = (
        sum(not bool(row["accepted"]) for row in carrier_unsafe)
        / len(carrier_unsafe)
        if carrier_unsafe
        else 1.0
    )
    clue_recall = (
        sum(not bool(row["accepted"]) for row in anomaly) / len(anomaly)
        if anomaly
        else 1.0
    )
    safe_coverage = len(accepted) / len(rows)
    use_coverage = (
        sum(bool(row["accepted"]) for row in use) / len(use) if use else 1.0
    )
    result = {
        "probe": probe,
        "fold": fold,
        "object_count": len(rows),
        "accepted_count": len(accepted),
        "carrier_unsafe_count": len(carrier_unsafe),
        "carrier_wrong_accepted_count": carrier_wrong_accepted,
        "review_auto_publish_count": review_auto,
        "carrier_safety_recall": carrier_recall,
        "anomaly_target_count": len(anomaly),
        "clue_miss_only_count": clue_miss_only,
        "clue_recall": clue_recall,
        "safe_coverage": safe_coverage,
        "use_rcsd_safe_coverage": use_coverage,
    }
    result["gate_pass"] = (
        carrier_wrong_accepted == 0
        and review_auto == 0
        and carrier_recall == 1.0
        and safe_coverage >= minimum_safe_coverage
        and use_coverage >= minimum_use_rcsd_safe_coverage
    )
    return result


def _load_inputs(
    *,
    config: SchemeAP2P2P2P2Config,
    p0_root: Path,
    p1_root: Path,
    dataset_root: Path,
) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest_paths = {
        "p2_p2_p2_p0": p0_root / "scheme_a_p2_p2_p2_p0_manifest.json",
        "p2_p2_p2_p1": p1_root / "scheme_a_p2_p2_p2_p1_manifest.json",
        "p2_p1_dataset": dataset_root / "scheme_a_p2_p1_dataset_manifest.json",
    }
    manifests = {key: _read_json(path) for key, path in manifest_paths.items()}
    for manifest in manifests.values():
        _verify_outputs(manifest, config.strict_hashes)
    if manifests["p2_p2_p2_p0"]["decision"] != (
        "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO"
    ):
        raise ValueError("P2-P2-P2-P0 decision differs")
    if manifests["p2_p2_p2_p1"]["decision"] != (
        "P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED"
    ):
        raise ValueError("P2-P2-P2-P1 decision differs")

    p1_candidate_manifest_path = _manifest_ref(
        manifests["p2_p1_dataset"], "p1_candidate", config.strict_hashes
    )
    pto_candidate_manifest_path = _manifest_ref(
        manifests["p2_p1_dataset"], "pto_candidate", config.strict_hashes
    )
    dataset_p0_manifest_path = _manifest_ref(
        manifests["p2_p1_dataset"], "dataset_p0", config.strict_hashes
    )
    baseline_manifest_path = _manifest_ref(
        manifests["p2_p1_dataset"], "scheme_a_baseline", config.strict_hashes
    )
    extra_manifests = {
        "p1_candidate": _read_json(p1_candidate_manifest_path),
        "pto_candidate": _read_json(pto_candidate_manifest_path),
        "dataset_p0": _read_json(dataset_p0_manifest_path),
        "scheme_a_baseline": _read_json(baseline_manifest_path),
    }
    for manifest in extra_manifests.values():
        _verify_outputs(manifest, config.strict_hashes)
    manifests.update(extra_manifests)
    paths = {
        "p0_evaluation": _output_path(manifests["p2_p2_p2_p0"], "evaluation"),
        "p0_summary": _output_path(manifests["p2_p2_p2_p0"], "summary"),
        "p1_attribution": _output_path(
            manifests["p2_p2_p2_p1"], "attribution"
        ),
        "p1_candidates": _output_path(manifests["p1_candidate"], "candidates"),
        "p1_lineage": _output_path(manifests["p1_candidate"], "lineage"),
        "pto_candidates": _output_path(manifests["pto_candidate"], "candidates"),
        "module_role_contract": _output_path(
            manifests["dataset_p0"], "module_role_contract"
        ),
        "module_artifact_inventory": _output_path(
            manifests["dataset_p0"], "module_artifact_inventory"
        ),
        "baseline_labels": baseline_manifest_path.parent / "carrier_labels.jsonl",
        "compatibility_oracle": _output_path(
            manifests["p2_p1_dataset"], "compatibility_oracle"
        ),
    }
    input_records = {
        key: {"path": str(path), "sha256": sha256_file(path)}
        for key, path in {
            **manifest_paths,
            "p1_candidate": p1_candidate_manifest_path,
            "pto_candidate": pto_candidate_manifest_path,
            "dataset_p0": dataset_p0_manifest_path,
            "scheme_a_baseline": baseline_manifest_path,
        }.items()
    }
    return manifests, paths, input_records


def _junction_dependency_audit(
    *, config: SchemeAP2P2P2P2Config, paths: Mapping[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segment_labels, case_folds = _load_segment_labels(paths["baseline_labels"])
    segment_candidates = _load_segment_candidates(paths["p1_candidates"])
    initial = build_endpoint_node_carriers(
        pto_candidate_path=paths["pto_candidates"],
        p1_lineage_path=paths["p1_lineage"],
        segment_candidates=segment_candidates,
        segment_labels=segment_labels,
        case_folds=case_folds,
        expected_missing_nodes=(
            ("T10:609214532", "987665"),
            ("T10:74155468", "953982"),
        ),
    )
    fallback_keys = {
        (str(case_key), str(segment_id))
        for case_key, segment_id in initial["junction_fallback_segment_keys"]
    }
    frozen_oracle = _read_json(paths["compatibility_oracle"])
    frozen_keys = {
        (str(case_key), str(segment_id))
        for case_key, segment_id in frozen_oracle["junction_fallback_segment_keys"]
    }
    if fallback_keys != frozen_keys:
        raise ValueError("reconstructed Junction fallback differs from frozen oracle")

    by_case: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "conflict_nodes": [],
            "fallback_segment_ids": [],
            "target_counts": Counter(),
        }
    )
    for conflict in initial["shared_payload_conflicts"]:
        case_key = str(conflict["case_key"])
        by_case[case_key]["conflict_nodes"].append(dict(conflict))
    for case_key, segment_id in sorted(fallback_keys):
        by_case[case_key]["fallback_segment_ids"].append(segment_id)
        by_case[case_key]["target_counts"][
            str(segment_labels[(case_key, segment_id)]["carrier_target"])
        ] += 1
    rows = [
        {
            "schema_version": SCHEME_A_P2_P2_P2_P2_SCHEMA,
            "case_key": case_key,
            "initial_node_payload_conflict_count": len(values["conflict_nodes"]),
            "initial_node_payload_conflicts": sorted(
                values["conflict_nodes"],
                key=lambda row: (str(row.get("node_id")), canonical_sha256(row)),
            ),
            "junction_fallback_segment_count": len(
                values["fallback_segment_ids"]
            ),
            "junction_fallback_segment_ids": sorted(
                values["fallback_segment_ids"]
            ),
            "baseline_target_counts": dict(
                sorted(values["target_counts"].items())
            ),
            "generic_graph_legality_only": True,
            "skeleton_mutation_count": 0,
        }
        for case_key, values in sorted(by_case.items())
    ]
    summary = {
        "initial_node_payload_conflict_count": sum(
            row["initial_node_payload_conflict_count"] for row in rows
        ),
        "junction_fallback_segment_count": sum(
            row["junction_fallback_segment_count"] for row in rows
        ),
        "junction_case_count": len(rows),
        "junction_fallback_target_counts": dict(
            sorted(
                sum(
                    (
                        Counter(row["baseline_target_counts"])
                        for row in rows
                    ),
                    Counter(),
                ).items()
            )
        ),
        "frozen_oracle_exact_match": fallback_keys == frozen_keys,
    }
    return rows, summary


def _target_candidate_options(
    path: Path, target_group_ids: set[str]
) -> dict[str, list[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in _read_jsonl(path):
        group_id = str(row["group_id"])
        if group_id in target_group_ids:
            result[group_id].add(str(row["candidate_target"]))
    if set(result) != target_group_ids:
        missing = sorted(target_group_ids - set(result))
        raise ValueError(f"candidate groups missing: {missing}")
    return {key: sorted(values) for key, values in result.items()}


def _source_candidate_ledger(path: Path) -> list[dict[str, Any]]:
    contract = _read_json(path)
    proposed = {
        "T01": ("FROZEN_SKELETON_INPUT", True),
        "T07": ("DRIVEZONE_ONLY_INPUT", True),
        "T03": ("NODE_EVIDENCE_AUXILIARY_TARGET", False),
        "T04": ("NODE_EVIDENCE_AUXILIARY_TARGET", False),
        "T05": ("RELATION_AUXILIARY_TARGET", False),
        "T06": ("CARRIER_AND_CLUE_SUPERVISION", False),
        "T09": ("DOWNSTREAM_VALIDATION", False),
        "T11": ("ACTIVE_LEARNING_CORRECTION", False),
        "T10": ("SPLIT_AND_LINEAGE", False),
    }
    rows = []
    for row in contract:
        module = str(row["module"])
        use, inference = proposed[module]
        rows.append(
            {
                "schema_version": SCHEME_A_P2_P2_P2_P2_SCHEMA,
                "module": module,
                "current_training_role": str(row["training_role"]),
                "current_model_input": bool(row["model_input"]),
                "label_only": bool(row["label_only"]),
                "proposed_hierarchical_role": use,
                "proposed_inference_input": inference,
                "source_role_changed": False,
                "business_meaning": str(row["business_meaning"]),
                "prohibited_interpretation": str(
                    row["prohibited_interpretation"]
                ),
                "lineage": {
                    "path": str(path),
                    "sha256": sha256_file(path),
                },
            }
        )
    return rows


def _manifest_ref(
    manifest: Mapping[str, Any], key: str, strict_hashes: bool
) -> Path:
    record = manifest["input_manifests"][key]
    path = normalize_runtime_path(str(record["path"])).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if strict_hashes and sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"input manifest hash differs: {key}")
    return path


def _verify_outputs(manifest: Mapping[str, Any], strict_hashes: bool) -> None:
    for key, record in manifest.get("outputs", {}).items():
        path = normalize_runtime_path(str(record["path"])).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if int(record.get("size_bytes", path.stat().st_size)) != path.stat().st_size:
            raise ValueError(f"output size differs: {key}")
        if strict_hashes and sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"output hash differs: {key}")


def _output_path(manifest: Mapping[str, Any], key: str) -> Path:
    return normalize_runtime_path(str(manifest["outputs"][key]["path"])).resolve()


def _resolve_dir(path: Path) -> Path:
    resolved = normalize_runtime_path(path).resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


def _reference_match(path: Path | None, signature: str) -> bool | None:
    if path is None:
        return None
    root = _resolve_dir(path)
    summary = _read_json(root / "scheme_a_p2_p2_p2_p2_summary.json")
    return str(summary["determinism_signature"]) == signature


def _resource_summary(started: float) -> dict[str, Any]:
    peak_mb = 0.0
    try:
        import resource

        raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        peak_mb = raw / (1024.0 if sys.platform != "darwin" else 1024.0**2)
    except (ImportError, OSError):
        peak_mb = 0.0
    wall = time.perf_counter() - started
    return {
        "wall_seconds": wall,
        "wall_within_30_minutes": wall <= 1800.0,
        "peak_rss_mb": peak_mb,
        "cpu_ram_within_8gb": peak_mb <= 8192.0 if peak_mb else True,
        "gpu_peak_memory_mb": 0.0,
        "gpu_vram_zero": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _validation_report(summary: Mapping[str, Any]) -> str:
    shallow = next(
        row
        for row in summary["metric_reinterpretation"]
        if row["probe"] == "SHALLOW_MLP"
    )
    overall = shallow["overall_metrics"]
    return "\n".join(
        [
            "# P05-Scheme-A-P2-P2-P2-P2 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- blocked objects: `{summary['blocked_object_count']}`",
            f"- business classes: `{json.dumps(summary['business_class_counts'], ensure_ascii=False, sort_keys=True)}`",
            f"- SHALLOW_MLP carrier safety recall: `{overall['carrier_safety_recall']}`",
            f"- SHALLOW_MLP clue recall: `{overall['clue_recall']}`",
            f"- SHALLOW_MLP corrected fold pass: `{shallow['fold_pass_count']}/5`",
            f"- initial Node payload conflicts: `{summary['junction']['initial_node_payload_conflict_count']}`",
            f"- Junction fallback Segments: `{summary['junction']['junction_fallback_segment_count']}`",
            f"- determinism signature: `{summary['determinism_signature']}`",
            "",
        ]
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "build_object_source_route",
    "classify_business_outcome",
    "reinterpret_probe_metrics",
    "run_scheme_a_p2_p2_p2_p2_audit",
]
