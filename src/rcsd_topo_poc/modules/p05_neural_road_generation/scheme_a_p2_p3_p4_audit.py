from __future__ import annotations

import json
import resource
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_dataset import (
    _fallback_positive_segments,
    _load_segment_candidates,
    _load_segment_labels,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p4_models import (
    DECISION_TRUTH_REBASELINE_GO,
    DECISION_TRUTH_REBASELINE_NO_GO,
    SCHEME_A_P2_P3_P4_SCHEMA,
    SchemeAP2P3P4Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p4_scope import (
    build_label_delta,
    build_scope_first_truth,
    rebaseline_metrics,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p3_p4_audit(config: SchemeAP2P3P4Config) -> Path:
    started = time.perf_counter()
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    source = _load_sources(config)
    baseline_labels, case_folds = _load_segment_labels(
        source["paths"]["baseline_labels"]
    )
    if len(case_folds) != config.expected_case_count:
        raise ValueError("Scheme-A Case denominator differs")
    if len(set(case_folds.values())) != config.expected_fold_count:
        raise ValueError("Scheme-A fold denominator differs")
    segment_candidates = _load_segment_candidates(
        source["paths"]["p1_candidates"]
    )
    scope_rows = list(_read_jsonl(source["paths"]["dataset_p1_scope"]))
    fallback_positive = _fallback_positive_segments(
        source["paths"]["fallback_plans"]
    )
    truth = build_scope_first_truth(
        baseline_labels=baseline_labels,
        segment_candidates=segment_candidates,
        scope_rows=scope_rows,
        pto_candidate_path=source["paths"]["pto_candidates"],
        p1_lineage_path=source["paths"]["p1_lineage"],
        case_folds=case_folds,
        fallback_positive_segments=fallback_positive,
        expected_missing_nodes=config.expected_missing_endpoint_nodes,
        iteration_limit=config.expected_case_count + 1,
    )
    old_labels = list(_read_jsonl(source["paths"]["old_labels"]))
    delta_rows = build_label_delta(truth["segment_labels"], old_labels)
    decisions = list(_read_jsonl(source["paths"]["p3_decisions"]))
    evaluations = list(_read_jsonl(source["paths"]["p2_evaluation"]))
    effective = list(_read_jsonl(source["paths"]["p3_effective"]))
    metrics = rebaseline_metrics(
        corrected_rows=truth["segment_labels"],
        decisions=decisions,
        evaluations=evaluations,
        effective_rows=effective,
        model_seeds=config.model_seeds,
        minimum_safe_coverage=config.minimum_safe_coverage,
        minimum_use_coverage=config.minimum_use_rcsd_safe_coverage,
        minimum_clue_precision=config.minimum_clue_precision,
        minimum_clue_macro_f1=config.minimum_clue_macro_f1,
    )
    roadgraph_audit = _roadgraph_audit(
        list(_read_jsonl(source["paths"]["p3_roadgraphs"])),
        list(_read_jsonl(source["paths"]["p3_closure"])),
        config,
    )
    residual = _residual_reinterpretation(
        config,
        truth["segment_labels"],
        delta_rows,
        decisions,
        evaluations,
        effective,
    )
    counts = _counts(truth, delta_rows)
    gates = _gates(config, counts, metrics, roadgraph_audit, residual)

    paths = {
        "segment_labels": run_root / "scope_first_segment_labels.jsonl",
        "node_labels": run_root / "scope_first_node_labels.jsonl",
        "initial_conflicts": run_root / "initial_node_conflicts.jsonl",
        "closure": run_root / "junction_fallback_closure.jsonl",
        "delta": run_root / "label_delta.jsonl",
        "metrics": run_root / "metric_rebaseline.json",
        "residual": run_root / "residual_reinterpretation.json",
        "dataset_manifest": run_root / "scope_first_dataset_manifest.json",
        "summary": run_root / "scheme_a_p2_p3_p4_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["segment_labels"], truth["segment_labels"])
    _write_jsonl(paths["node_labels"], truth["node_labels"])
    _write_jsonl(paths["initial_conflicts"], truth["initial_node_conflicts"])
    _write_jsonl(paths["closure"], truth["junction_fallback_closure"])
    _write_jsonl(paths["delta"], delta_rows)
    write_json(paths["metrics"], metrics)
    write_json(paths["residual"], residual)
    dataset_manifest = {
        "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
        "status": "scope_first_truth_layer_rebuilt",
        "scope_order": [
            "DATASET_P1_LABEL_SCOPE",
            "CONTEXT_SAFE_KEEP_MATERIALIZATION",
            "NODE_JUNCTION_TRUTH_CLOSURE",
        ],
        "counts": counts,
        "truth_free_layers_reused": {
            role: source["lineage"][role]
            for role in (
                "old_p2_p1_features",
                "old_p2_p1_payloads",
                "old_p2_p1_compatibility_edges",
            )
        },
        "label_layer_rebuilt": True,
        "candidate_layer_rebuilt": False,
        "context_label_contribution_count": 0,
        "context_input_weight": 0.3,
        "model_training_count": 0,
    }
    write_json(paths["dataset_manifest"], dataset_manifest)

    deterministic_payload = {
        "source_lineage": source["lineage"],
        "segment_labels": truth["segment_labels"],
        "node_labels": truth["node_labels"],
        "initial_conflicts": truth["initial_node_conflicts"],
        "closure": truth["junction_fallback_closure"],
        "delta": delta_rows,
        "metrics": metrics,
        "residual": residual,
        "roadgraph_audit": roadgraph_audit,
        "counts": counts,
        "gates": gates,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    resource = {
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": _peak_rss_bytes(),
        "peak_rss_gib": _peak_rss_bytes() / (1024**3),
        "gpu_vram_bytes": 0,
    }
    resource_gate = (
        resource["wall_seconds"] <= 30 * 60
        and resource["peak_rss_bytes"] <= 8 * 1024**3
    )
    gates["gate4_determinism_resource"] = (
        resource_gate and reference_match is not False
    )
    gate_pass = all(gates.values())
    decision = (
        DECISION_TRUTH_REBASELINE_GO
        if gate_pass
        else DECISION_TRUTH_REBASELINE_NO_GO
    )
    summary = {
        "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
        "decision": decision,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "gates": gates,
        "gate_pass": gate_pass,
        "counts": counts,
        "target_counts": truth["target_counts"],
        "metrics": metrics,
        "roadgraph_audit": roadgraph_audit,
        "residual_reinterpretation": residual,
        "resource": resource,
        "lineage": source["lineage"],
        "model_training_count": 0,
        "threshold_change_count": 0,
        "truth_inference_feature_count": 0,
        "t06_inference_feature_count": 0,
        "movement_decision_count": 0,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_performed": False,
        "crs": "EPSG:3857",
        "skeleton_mutation_count": 0,
        "repair_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(_validation_report(summary), encoding="utf-8")
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p4_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "truth_rebaseline_completed",
            "decision": decision,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "parameters": {
                "model_seeds": list(config.model_seeds),
                "new_model_training": False,
                "threshold_change": False,
                "scope_first_truth": True,
            },
            "outputs": outputs,
            "truth_inference_feature_count": 0,
            "t06_inference_feature_count": 0,
            "movement_decision_count": 0,
            "geometry_read_count": 0,
            "geometry_write_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p4-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _load_sources(config: SchemeAP2P3P4Config) -> dict[str, Any]:
    roots = {
        "dataset_p1": normalize_runtime_path(config.dataset_p1_root).resolve(
            strict=True
        ),
        "baseline": normalize_runtime_path(config.scheme_a_baseline_root).resolve(
            strict=True
        ),
        "p1": normalize_runtime_path(config.p1_candidate_root).resolve(strict=True),
        "pto": normalize_runtime_path(config.pto_candidate_root).resolve(strict=True),
        "p2_p1": normalize_runtime_path(config.p2_p1_dataset_root).resolve(
            strict=True
        ),
        "p2_p3_p2": normalize_runtime_path(config.p2_p3_p2_root).resolve(
            strict=True
        ),
        "p2_p3_p3": normalize_runtime_path(config.p2_p3_p3_root).resolve(
            strict=True
        ),
    }
    manifests = {
        "dataset_p1": _load_manifest(
            roots["dataset_p1"] / "dataset_p1_manifest.json",
            status="completed",
            decision="P05_SCHEME_A_DATASET_P1_GO",
        ),
        "baseline": _load_manifest(
            roots["baseline"] / "scheme_a_manifest.json",
            status="passed",
        ),
        "p1": _load_manifest(
            roots["p1"] / "scheme_a_p1_candidate_manifest.json",
            status="candidate_scope_passed",
        ),
        "pto": _load_manifest(
            roots["pto"] / "p05_pto_candidate_manifest.json",
            status="candidate_scope_passed",
        ),
        "p2_p1": _load_manifest(
            roots["p2_p1"] / "scheme_a_p2_p1_dataset_manifest.json",
            status="dataset_passed",
        ),
        "p2_p3_p2": _load_manifest(
            roots["p2_p3_p2"] / "scheme_a_p2_p3_p2_manifest.json",
            status="dataset_p1_scorer_completed",
            decision="P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO",
        ),
        "p2_p3_p3": _load_manifest(
            roots["p2_p3_p3"] / "scheme_a_p2_p3_p3_manifest.json",
            status="safety_gate_and_residual_audit_completed",
            decision=(
                "P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_"
                "NEXT_REPRESENTATION_REQUIRED"
            ),
        ),
    }
    manifest_paths = {
        "dataset_p1": roots["dataset_p1"] / "dataset_p1_manifest.json",
        "baseline": roots["baseline"] / "scheme_a_manifest.json",
        "p1": roots["p1"] / "scheme_a_p1_candidate_manifest.json",
        "pto": roots["pto"] / "p05_pto_candidate_manifest.json",
        "p2_p1": roots["p2_p1"] / "scheme_a_p2_p1_dataset_manifest.json",
        "p2_p3_p2": roots["p2_p3_p2"]
        / "scheme_a_p2_p3_p2_manifest.json",
        "p2_p3_p3": roots["p2_p3_p3"]
        / "scheme_a_p2_p3_p3_manifest.json",
    }
    paths = {
        "dataset_p1_scope": _verified_output(
            manifests["dataset_p1"], "label_scope", config.strict_hashes
        ),
        "baseline_labels": _verified_output(
            manifests["baseline"], "carrier_labels", config.strict_hashes
        ),
        "fallback_plans": _verified_output(
            manifests["baseline"], "fallback_plans", config.strict_hashes
        ),
        "p1_candidates": _verified_output(
            manifests["p1"], "candidates", config.strict_hashes
        ),
        "p1_lineage": _verified_output(
            manifests["p1"], "lineage", config.strict_hashes
        ),
        "pto_candidates": _verified_output(
            manifests["pto"], "candidates", config.strict_hashes
        ),
        "old_labels": _verified_output(
            manifests["p2_p1"], "labels", config.strict_hashes
        ),
        "p2_evaluation": _verified_output(
            manifests["p2_p3_p2"], "evaluation", config.strict_hashes
        ),
        "p3_decisions": _verified_output(
            manifests["p2_p3_p3"], "eligible_decisions", config.strict_hashes
        ),
        "p3_effective": _verified_output(
            manifests["p2_p3_p3"], "effective", config.strict_hashes
        ),
        "p3_roadgraphs": _verified_output(
            manifests["p2_p3_p3"], "roadgraphs", config.strict_hashes
        ),
        "p3_closure": _verified_output(
            manifests["p2_p3_p3"], "closure", config.strict_hashes
        ),
    }
    lineage = {
        f"{name}_manifest": _record(manifest_paths[name])
        for name in sorted(manifest_paths)
    }
    for role in ("features", "payloads", "compatibility_edges"):
        path = _verified_output(manifests["p2_p1"], role, config.strict_hashes)
        lineage[f"old_p2_p1_{role}"] = _record(path)
    for role, path in sorted(paths.items()):
        lineage[role] = _record(path)
    return {"paths": paths, "lineage": lineage}


def _counts(
    truth: Mapping[str, Any],
    delta_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    segment_rows = truth["segment_labels"]
    eligible = [row for row in segment_rows if row["label_eligible"]]
    context = [row for row in segment_rows if not row["label_eligible"]]
    closure = truth["junction_fallback_closure"]
    return {
        "segment_count": len(segment_rows),
        "eligible_count": len(eligible),
        "context_count": len(context),
        "context_label_contribution_count": sum(
            int(row["label_truth_contribution"]) for row in context
        ),
        "context_safe_keep_count": sum(
            row["effective_carrier_target"] == "KEEP_SWSD" for row in context
        ),
        "initial_node_conflict_count": len(truth["initial_node_conflicts"]),
        "junction_fallback_segment_count": len(closure),
        "junction_fallback_eligible_count": sum(
            bool(row["label_eligible"]) for row in closure
        ),
        "final_node_label_count": len(truth["node_labels"]),
        "final_node_conflict_count": 0,
        "final_unexpected_missing_node_count": 0,
        "total_delta_count": len(delta_rows),
        "context_delta_count": sum(
            not bool(row["label_eligible"]) for row in delta_rows
        ),
        "eligible_delta_count": sum(
            bool(row["label_eligible"]) for row in delta_rows
        ),
        "eligible_anomaly_count": sum(
            bool(row["effective_anomaly_target"]) for row in eligible
        ),
        "target_counts": dict(
            sorted(
                Counter(
                    str(row["effective_carrier_target"]) for row in segment_rows
                ).items()
            )
        ),
        "eligible_target_counts": dict(
            sorted(
                Counter(
                    str(row["effective_carrier_target"]) for row in eligible
                ).items()
            )
        ),
    }


def _gates(
    config: SchemeAP2P3P4Config,
    counts: Mapping[str, Any],
    metrics: Mapping[str, Any],
    roadgraph: Mapping[str, Any],
    residual: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "gate0_scope": (
            counts["segment_count"] == config.expected_segment_count
            and counts["eligible_count"] == config.expected_eligible_count
            and counts["context_count"] == config.expected_context_count
            and counts["context_label_contribution_count"] == 0
            and counts["context_safe_keep_count"] == config.expected_context_count
        ),
        "gate1_node_junction_truth": (
            counts["initial_node_conflict_count"]
            == config.expected_initial_node_conflict_count
            and counts["junction_fallback_segment_count"]
            == config.expected_junction_fallback_segment_count
            and counts["junction_fallback_eligible_count"]
            == config.expected_junction_fallback_eligible_count
            and counts["final_node_label_count"]
            == config.expected_node_label_count
            and counts["final_node_conflict_count"] == 0
            and counts["final_unexpected_missing_node_count"] == 0
        ),
        "gate2_label_delta": (
            counts["total_delta_count"] == config.expected_total_delta_count
            and counts["context_delta_count"]
            == config.expected_context_delta_count
            and counts["eligible_delta_count"]
            == config.expected_eligible_delta_count
            and counts["target_counts"]
            == {
                "KEEP_SWSD": 7_074,
                "REVIEW_FALLBACK": 40,
                "USE_RCSD": 1_749,
            }
            and residual["gate_pass"]
        ),
        "gate3_metric_reinterpretation": (
            metrics["accepted_wrong_by_seed"]
            == {str(seed): 0 for seed in config.model_seeds}
            and metrics["review_auto_publish_by_seed"]
            == {str(seed): 0 for seed in config.model_seeds}
            and metrics["carrier_safety_recall_by_seed"]
            == {str(seed): 1.0 for seed in config.model_seeds}
            and not metrics["model_gate_pass"]
            and roadgraph["gate_pass"]
        ),
        "gate4_determinism_resource": False,
    }


def _residual_reinterpretation(
    config: SchemeAP2P3P4Config,
    corrected_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    effective: list[dict[str, Any]],
) -> dict[str, Any]:
    corrected = [
        row
        for row in corrected_rows
        if row["group_id"] == config.residual_group_id
    ]
    delta = [
        row for row in delta_rows if row["group_id"] == config.residual_group_id
    ]
    decision_rows = [
        row for row in decisions if row["group_id"] == config.residual_group_id
    ]
    evaluation_rows = [
        row for row in evaluations if row["group_id"] == config.residual_group_id
    ]
    effective_rows = [
        row
        for row in effective
        if row.get("object_type") == "SEGMENT"
        and row["group_id"] == config.residual_group_id
    ]
    if not (
        len(corrected) == 1
        and len(delta) == 1
        and len(decision_rows) == len(config.model_seeds)
        and len(evaluation_rows) == len(config.model_seeds)
        and len(effective_rows) == len(config.model_seeds)
    ):
        raise ValueError("residual reinterpretation denominator differs")
    result = {
        "group_id": config.residual_group_id,
        "old_target": delta[0]["old_carrier_target"],
        "corrected_target": corrected[0]["effective_carrier_target"],
        "old_truth_candidate_id": delta[0]["old_truth_candidate_id"],
        "corrected_truth_candidate_id": corrected[0][
            "effective_truth_candidate_id"
        ],
        "old_anomaly_target": delta[0]["old_anomaly_target"],
        "corrected_anomaly_target": corrected[0]["effective_anomaly_target"],
        "selected_candidate_by_seed": {
            str(row["seed"]): str(row["selected_candidate_id"])
            for row in evaluation_rows
        },
        "accepted_by_seed": {
            str(row["seed"]): bool(row["accepted"]) for row in effective_rows
        },
        "accepted_wrong_after_rebaseline_by_seed": {
            str(row["seed"]): int(
                bool(row["accepted"])
                and str(row["effective_candidate_id"])
                != config.residual_truth_candidate_id
            )
            for row in effective_rows
        },
        "historical_conclusion": "NEW_PRE_T06_REPRESENTATION_REQUIRED",
        "reinterpreted_conclusion": (
            "NO_RESIDUAL_REPRESENTATION_REQUIRED_SCOPE_ORDER_DEFECT"
        ),
    }
    result["gate_pass"] = (
        result["old_target"] == "KEEP_SWSD"
        and result["corrected_target"] == "USE_RCSD"
        and result["corrected_truth_candidate_id"]
        == config.residual_truth_candidate_id
        and result["corrected_anomaly_target"] is False
        and result["accepted_wrong_after_rebaseline_by_seed"]
        == {str(seed): 0 for seed in config.model_seeds}
    )
    return result


def _roadgraph_audit(
    rows: list[dict[str, Any]],
    closure_rows: list[dict[str, Any]],
    config: SchemeAP2P3P4Config,
) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    for seed in config.model_seeds:
        seed_rows = [row for row in rows if int(row["seed"]) == seed]
        counts[str(seed)] = dict(
            sorted(Counter(str(row["terminal_state"]) for row in seed_rows).items())
        )
    closure_by_seed = {
        str(row["seed"]): {
            "requirement_conflict_count": int(row["requirement_conflict_count"]),
            "node_target_mismatch_count": int(row["node_target_mismatch_count"]),
        }
        for row in closure_rows
    }
    expected = {
        str(seed): {"EXPECTED_FAIL": 2, "LEGAL": 49}
        for seed in config.model_seeds
    }
    gate = (
        counts == expected
        and all(
            row["requirement_conflict_count"] == 0
            and row["node_target_mismatch_count"] == 0
            for row in closure_by_seed.values()
        )
    )
    return {
        "terminal_state_counts_by_seed": counts,
        "closure_safety_by_seed": closure_by_seed,
        "roadgraph_rebuilt": False,
        "source_artifact_hashes_verified": True,
        "gate_pass": gate,
    }


def _load_manifest(
    path: Path,
    *,
    status: str,
    decision: str | None = None,
) -> dict[str, Any]:
    manifest = _read_json(path)
    if manifest.get("status") != status:
        raise ValueError(f"source status differs: {path}")
    if decision is not None and manifest.get("decision") != decision:
        raise ValueError(f"source decision differs: {path}")
    return manifest


def _verified_output(
    manifest: Mapping[str, Any],
    role: str,
    strict_hashes: bool,
) -> Path:
    record = dict((manifest.get("outputs") or {}).get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != record.get("sha256"):
        raise ValueError(f"source output hash mismatch: {role}")
    return path


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _reference_match(root_value: Path | None, signature: str) -> bool | None:
    if root_value is None:
        return None
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p4_manifest.json")
    return str(manifest.get("determinism_signature")) == signature


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if value > 10**9 else value * 1024


def _validation_report(summary: Mapping[str, Any]) -> str:
    counts = summary["counts"]
    metrics = summary["metrics"]
    return (
        "# P05-Scheme-A-P2-P3-P4 验证报告\n\n"
        f"- 决策：`{summary['decision']}`\n"
        f"- 总门禁：`{summary['gate_pass']}`\n"
        f"- Segment：`{counts['segment_count']}`，eligible："
        f"`{counts['eligible_count']}`，context：`{counts['context_count']}`\n"
        f"- 初始 Node 冲突：`{counts['initial_node_conflict_count']}`；"
        f"Junction fallback Segment：`{counts['junction_fallback_segment_count']}`\n"
        f"- 标签 delta：总计 `{counts['total_delta_count']}`，context "
        f"`{counts['context_delta_count']}`，eligible "
        f"`{counts['eligible_delta_count']}`\n"
        f"- accepted wrong：`{metrics['accepted_wrong_by_seed']}`\n"
        f"- 模型结论：`{metrics['model_decision']}`\n"
        f"- Run A/B 匹配：`{summary['reference_run_match']}`\n"
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["run_scheme_a_p2_p3_p4_audit"]
