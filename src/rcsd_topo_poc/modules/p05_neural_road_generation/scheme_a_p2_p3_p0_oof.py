from __future__ import annotations

import json
import math
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_execution import (
    load_p2_p1_payloads,
    materialize_p2_p1_seed,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_oof import (
    build_joint_safety_selections,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_dataset import (
    load_hierarchical_training_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    AUXILIARY_TARGET_NAMES,
    SCHEME_A_P2_P3_P0_SCHEMA,
    SchemeAP2P3P0Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_training import (
    decision_from_score,
    train_hierarchical_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p3_p0_oof(config: SchemeAP2P3P0Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    examples, metadata = load_hierarchical_training_examples(config)
    score_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    evaluation_rows: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    training_started = time.perf_counter()
    for seed in config.model_seeds:
        for fold in range(config.expected_fold_count):
            result = train_hierarchical_fold(
                examples,
                config=config,
                held_out_fold=fold,
                seed=seed,
                dataset_manifest_sha256=metadata["lineage"][
                    "hierarchical_dataset_signature"
                ],
            )
            training_summary = dict(result.training_summary)
            model_signature = str(training_summary["model_signature"])
            fold_records.append(
                {
                    **training_summary,
                    "evidence_transform_signature": canonical_sha256(
                        {
                            "mean": result.transform.evidence_mean,
                            "scale": result.transform.evidence_scale,
                            "train_cases": training_summary["train_case_keys"],
                        }
                    ),
                    "vocabulary_signature": result.transform.vocabulary.to_dict()[
                        "vocabulary_signature"
                    ],
                }
            )
            for row in result.held_out_scores:
                score_rows.append(
                    {
                        "schema_version": SCHEME_A_P2_P3_P0_SCHEMA,
                        "case_key": row["case_key"],
                        "fold": int(row["fold"]),
                        "group_id": row["group_id"],
                        "object_id": row["object_id"],
                        "candidate_ids": row["candidate_ids"],
                        "candidate_targets": row["candidate_targets"],
                        "candidate_scores": row["candidate_scores"],
                        "candidate_probabilities": row["candidate_probabilities"],
                        "candidate_correctness_probabilities": row[
                            "candidate_correctness_probabilities"
                        ],
                        "candidate_utilities": row["candidate_utilities"],
                        "selected_candidate_id": row["selected_candidate_id"],
                        "selected_target": row["selected_target"],
                        "carrier_confidence": row["carrier_confidence"],
                        "clue_probability": row["clue_probability"],
                        "auxiliary_probabilities": row["auxiliary_probabilities"],
                        "seed": seed,
                        "model_signature": model_signature,
                        "feature_uses_truth": False,
                        "label_only_source_used_as_input": False,
                        "movement_used": False,
                    }
                )
                decision = decision_from_score(
                    row,
                    result.thresholds,
                    seed=seed,
                    model_signature=model_signature,
                )
                decision_rows.append(
                    {"schema_version": SCHEME_A_P2_P3_P0_SCHEMA, **decision}
                )
                evaluation_rows.append(
                    {
                        "schema_version": SCHEME_A_P2_P3_P0_SCHEMA,
                        "case_key": row["case_key"],
                        "fold": int(row["fold"]),
                        "group_id": row["group_id"],
                        "truth_candidate_id": row["truth_candidate_id"],
                        "truth_target": row["truth_target"],
                        "clue_target": bool(row["clue_target"]),
                        "review_target": bool(row["review_target"]),
                        "selected_candidate_id": row["selected_candidate_id"],
                        "selected_target": row["selected_target"],
                        "seed": seed,
                        "label_only": True,
                    }
                )
            del result
    training_seconds = time.perf_counter() - training_started

    expected_failure_cases = {row[0] for row in config.expected_roadgraph_failures}
    for decision in decision_rows:
        if decision["case_key"] in expected_failure_cases:
            decision.update(
                {
                    "accepted": False,
                    "reason": "expected_swsd_baseline_failure",
                }
            )
    all_groups = list(metadata["all_groups"])
    payload_path = _payload_path(metadata["dataset"])
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    node_scores = _base_node_scores(config.base_oof_run_a, config.base_seeds)
    expected_failure_manifest = {
        case_key: frozenset(
            {
                f"Road endpoint Node missing: {node_id}",
                f"directed edge endpoint missing: {edge}",
            }
        )
        for case_key, node_id, edge in config.expected_roadgraph_failures
    }
    roadgraph_rows: list[dict[str, Any]] = []
    effective_rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    for seed in config.model_seeds:
        seed_decisions = [row for row in decision_rows if int(row["seed"]) == seed]
        selections, closure = build_joint_safety_selections(
            all_groups,
            seed_decisions,
            compatibility_edges=metadata["dataset"]["compatibility_edges"],
            labels=metadata["dataset"]["labels"],
            node_scores=node_scores,
            expected_failure_cases=expected_failure_cases,
            seed=seed,
        )
        closure_rows.append(closure)
        records, effective = materialize_p2_p1_seed(
            run_root,
            seed=seed,
            selections=selections,
            payloads_by_id=payloads_by_id,
            payloads_by_group=payloads_by_group,
            expected_failure_manifest=expected_failure_manifest,
        )
        roadgraph_rows.extend({"seed": seed, **row} for row in records)
        effective_rows.extend(effective)

    metrics = _all_metrics(
        examples,
        decision_rows,
        evaluation_rows,
        effective_rows,
        roadgraph_rows,
        closure_rows,
        fold_records,
        metadata["clue_only_group_ids"],
        config,
    )
    resource_metrics = {
        "wall_seconds": time.perf_counter() - started,
        "training_seconds": training_seconds,
        "peak_rss_bytes": _peak_rss_bytes(),
        "peak_rss_gib": _peak_rss_bytes() / (1024**3),
        "gpu_vram_bytes": (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
        ),
        **metrics["performance"],
    }
    resource_gate_pass = (
        resource_metrics["peak_rss_bytes"] <= 8 * 1024**3
        and resource_metrics["gpu_vram_bytes"] <= 8 * 1024**3
        and resource_metrics["max_seed_training_seconds"] <= 2 * 3600
        and resource_metrics["total_seed_training_seconds"] <= 6 * 3600
        and resource_metrics["case_inference_p95_seconds"] <= 5.0
        and resource_metrics["case_inference_max_seconds"] <= 20.0
    )
    source_gate_pass = all(
        int(metadata["inference_feature_audit"][key]) == 0
        for key in (
            "truth_feature_count",
            "identifier_feature_count",
            "absolute_coordinate_feature_count",
            "movement_feature_count",
            "t03_inference_feature_count",
            "t04_inference_feature_count",
            "t05_inference_feature_count",
            "t06_inference_feature_count",
        )
    )
    parameter_counts = {int(row["parameter_count"]) for row in fold_records}
    model_contract_gate_pass = (
        bool(parameter_counts)
        and min(parameter_counts) >= config.target_min_parameter_count
        and max(parameter_counts) <= config.target_max_parameter_count
        and max(parameter_counts) <= config.hard_max_parameter_count
    )
    deterministic_payload = {
        "scores": sorted(score_rows, key=_seed_group_key),
        "decisions": sorted(decision_rows, key=_seed_group_key),
        "effective": [
            _normalized_effective(row)
            for row in sorted(effective_rows, key=_seed_group_key)
        ],
        "roadgraphs": [
            {
                key: row[key]
                for key in (
                    "seed",
                    "case_key",
                    "legal",
                    "terminal_state",
                    "publish",
                    "expected_failure_match",
                    "failure_count",
                    "roadgraph_signature",
                )
            }
            for row in sorted(roadgraph_rows, key=lambda item: (int(item["seed"]), item["case_key"]))
        ],
        "folds": [
            {
                key: row[key]
                for key in (
                    "seed",
                    "held_out_fold",
                    "best_epoch",
                    "best_inner_loss",
                    "parameter_count",
                    "model_signature",
                    "carrier_threshold",
                    "clue_threshold",
                    "evidence_transform_signature",
                    "vocabulary_signature",
                )
            }
            for row in sorted(
                fold_records, key=lambda item: (int(item["seed"]), int(item["held_out_fold"]))
            )
        ],
    }
    determinism_signature = canonical_sha256(deterministic_payload)
    reference_run_match = _reference_match(config.reference_run_root, determinism_signature)
    audit_gate_pass = (
        source_gate_pass
        and model_contract_gate_pass
        and resource_gate_pass
        and (reference_run_match is not False)
    )
    model_gate_pass = (
        metrics["carrier_gate_pass"]
        and metrics["clue_gate_pass"]
        and metrics["roadgraph_gate_pass"]
    )
    if not audit_gate_pass:
        decision = "P05_SCHEME_A_P2_P3_P0_AUDIT_NO_GO"
    elif model_gate_pass:
        decision = "P05_SCHEME_A_P2_P3_P0_HIERARCHICAL_MODEL_GO"
    else:
        decision = "P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO"

    score_path = run_root / "hierarchical_scores.jsonl"
    decision_path = run_root / "decisions.jsonl"
    evaluation_path = run_root / "evaluation.jsonl"
    effective_path = run_root / "effective_selections.jsonl"
    roadgraph_path = run_root / "roadgraph_index.jsonl"
    closure_path = run_root / "junction_closure.jsonl"
    auxiliary_path = run_root / "auxiliary_labels.jsonl"
    fold_path = run_root / "fold_index.json"
    metrics_path = run_root / "metrics.json"
    feature_audit_path = run_root / "feature_audit.json"
    summary_path = run_root / "scheme_a_p2_p3_p0_summary.json"
    report_path = run_root / "validation_report.md"
    _write_jsonl(score_path, sorted(score_rows, key=_seed_group_key))
    _write_jsonl(decision_path, sorted(decision_rows, key=_seed_group_key))
    _write_jsonl(evaluation_path, sorted(evaluation_rows, key=_seed_group_key))
    _write_jsonl(effective_path, sorted(effective_rows, key=_seed_group_key))
    _write_jsonl(
        roadgraph_path,
        sorted(roadgraph_rows, key=lambda row: (int(row["seed"]), str(row["case_key"]))),
    )
    _write_jsonl(closure_path, sorted(closure_rows, key=lambda row: int(row["seed"])))
    _write_jsonl(auxiliary_path, metadata["auxiliary_label_rows"])
    write_json(fold_path, {"folds": fold_records})
    write_json(metrics_path, metrics)
    write_json(feature_audit_path, metadata["inference_feature_audit"])
    summary = {
        "schema_version": SCHEME_A_P2_P3_P0_SCHEMA,
        "decision": decision,
        "case_count": config.expected_case_count,
        "segment_count": config.expected_segment_group_count,
        "seed_count": len(config.model_seeds),
        "fold_count": config.expected_fold_count,
        "parameter_count_min": min(parameter_counts),
        "parameter_count_max": max(parameter_counts),
        "carrier_gate_pass": metrics["carrier_gate_pass"],
        "clue_gate_pass": metrics["clue_gate_pass"],
        "roadgraph_gate_pass": metrics["roadgraph_gate_pass"],
        "source_gate_pass": source_gate_pass,
        "model_contract_gate_pass": model_contract_gate_pass,
        "resource_gate_pass": resource_gate_pass,
        "reference_run_match": reference_run_match,
        "determinism_signature": determinism_signature,
        "metrics": metrics,
        "resource": resource_metrics,
        "lineage": metadata["lineage"],
        "auxiliary_metadata": {
            key: value
            for key, value in metadata["auxiliary_metadata"].items()
            if key != "inventory_path"
        },
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "geometry_modified": False,
        "coordinate_transform_performed": False,
    }
    write_json(summary_path, summary)
    report_path.write_text(_validation_report(summary), encoding="utf-8")
    outputs = {
        "scores": output_record(score_path),
        "decisions": output_record(decision_path),
        "evaluation": output_record(evaluation_path),
        "effective_selections": output_record(effective_path),
        "roadgraphs": output_record(roadgraph_path),
        "junction_closure": output_record(closure_path),
        "auxiliary_labels": output_record(auxiliary_path),
        "fold_index": output_record(fold_path),
        "metrics": output_record(metrics_path),
        "feature_audit": output_record(feature_audit_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest_path = run_root / "scheme_a_p2_p3_p0_manifest.json"
    manifest = {
        "schema_version": SCHEME_A_P2_P3_P0_SCHEMA,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "hierarchical_model_completed",
        "decision": decision,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_run_match,
        "lineage": metadata["lineage"],
        "parameters": {
            "model_seeds": list(config.model_seeds),
            "base_seeds": list(config.base_seeds),
            "expected_fold_count": config.expected_fold_count,
            "embedding_dim": config.embedding_dim,
            "hidden_dim": config.hidden_dim,
            "evidence_hidden_dim": config.evidence_hidden_dim,
            "type_embedding_dim": config.type_embedding_dim,
            "numeric_dim": config.numeric_dim,
            "evidence_dim": config.expected_evidence_dim,
            "auxiliary_dim": len(AUXILIARY_TARGET_NAMES),
            "dropout": config.dropout,
            "learning_rate": config.learning_rate,
            "weight_decay": config.weight_decay,
            "max_epochs": config.max_epochs,
            "patience": config.patience,
            "device": config.device,
        },
        "outputs": outputs,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p0-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _all_metrics(
    examples: Sequence[Any],
    decisions: Sequence[Mapping[str, Any]],
    evaluations: Sequence[Mapping[str, Any]],
    effective: Sequence[Mapping[str, Any]],
    roadgraphs: Sequence[Mapping[str, Any]],
    closures: Sequence[Mapping[str, Any]],
    folds: Sequence[Mapping[str, Any]],
    clue_only_group_ids: Sequence[str],
    config: SchemeAP2P3P0Config,
) -> dict[str, Any]:
    group_by_id = {example.group.group_id: example.group for example in examples}
    decision_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in decisions
    }
    evaluation_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in evaluations
    }
    effective_segments = [
        row for row in effective if row.get("object_type") == "SEGMENT"
    ]
    effective_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in effective_segments
    }
    expected_keys = {
        (seed, group_id)
        for seed in config.model_seeds
        for group_id in group_by_id
    }
    if set(decision_by_key) != expected_keys or set(evaluation_by_key) != expected_keys:
        raise ValueError("OOF decision/evaluation denominator differs")
    if set(effective_by_key) != expected_keys:
        raise ValueError("effective Segment denominator differs")
    scope_metrics: list[dict[str, Any]] = []
    for seed in config.model_seeds:
        scope_metrics.append(
            _scope_metrics(
                seed,
                None,
                group_by_id,
                decision_by_key,
                evaluation_by_key,
                effective_by_key,
                clue_only_group_ids,
                config,
            )
        )
        for fold in range(config.expected_fold_count):
            scope_metrics.append(
                _scope_metrics(
                    seed,
                    fold,
                    group_by_id,
                    decision_by_key,
                    evaluation_by_key,
                    effective_by_key,
                    clue_only_group_ids,
                    config,
                )
            )
    carrier_gate_pass = all(
        row["carrier_gate_pass"] for row in scope_metrics if row["scope"] in {"SEED", "FOLD"}
    )
    clue_gate_pass = all(
        row["clue_gate_pass"] for row in scope_metrics if row["scope"] in {"SEED", "FOLD"}
    )
    closure_by_seed = {int(row["seed"]): row for row in closures}
    roadgraph_metrics: list[dict[str, Any]] = []
    for seed in config.model_seeds:
        seed_rows = [row for row in roadgraphs if int(row["seed"]) == seed]
        states = Counter(str(row["terminal_state"]) for row in seed_rows)
        audits = [_read_json(normalize_runtime_path(row["output"]["path"])) for row in seed_rows]
        hard_gate_iteration_count = sum(
            len((audit.get("audit") or {}).get("hard_gate_iterations") or [])
            for audit in audits
        )
        node_conflict_count = sum(
            int((audit.get("audit") or {}).get("node_conflict_count") or 0)
            for audit in audits
        )
        closure = closure_by_seed[seed]
        gate = (
            len(seed_rows) == config.expected_case_count
            and states["LEGAL"]
            == config.expected_case_count - len(config.expected_roadgraph_failures)
            and states["EXPECTED_FAIL"] == len(config.expected_roadgraph_failures)
            and states["FAIL"] == 0
            and int(closure["requirement_conflict_count"]) == 0
            and int(closure["node_target_mismatch_count"]) == 0
            and node_conflict_count == 0
            and hard_gate_iteration_count == 0
        )
        roadgraph_metrics.append(
            {
                "seed": seed,
                "terminal_state_counts": dict(states),
                "requirement_conflict_count": int(
                    closure["requirement_conflict_count"]
                ),
                "node_target_mismatch_count": int(
                    closure["node_target_mismatch_count"]
                ),
                "node_conflict_count": node_conflict_count,
                "hard_gate_iteration_count": hard_gate_iteration_count,
                "gate_pass": gate,
            }
        )
    latencies = [
        float(item["seconds"])
        for fold in folds
        for item in fold["case_inference_latencies"]
    ]
    seed_training = {
        seed: sum(
            float(fold["wall_seconds"]) for fold in folds if int(fold["seed"]) == seed
        )
        for seed in config.model_seeds
    }
    return {
        "scope_metrics": scope_metrics,
        "carrier_gate_pass": carrier_gate_pass,
        "clue_gate_pass": clue_gate_pass,
        "roadgraph_metrics": roadgraph_metrics,
        "roadgraph_gate_pass": all(row["gate_pass"] for row in roadgraph_metrics),
        "performance": {
            "case_inference_p95_seconds": _percentile(latencies, 0.95),
            "case_inference_max_seconds": max(latencies),
            "case_inference_measurement_count": len(latencies),
            "seed_training_seconds": seed_training,
            "max_seed_training_seconds": max(seed_training.values()),
            "total_seed_training_seconds": sum(seed_training.values()),
        },
    }


def _scope_metrics(
    seed: int,
    fold: int | None,
    group_by_id: Mapping[str, Any],
    decisions: Mapping[tuple[int, str], Mapping[str, Any]],
    evaluations: Mapping[tuple[int, str], Mapping[str, Any]],
    effective: Mapping[tuple[int, str], Mapping[str, Any]],
    clue_only_group_ids: Sequence[str],
    config: SchemeAP2P3P0Config,
) -> dict[str, Any]:
    group_ids = [
        group_id
        for group_id, group in group_by_id.items()
        if fold is None or int(group.fold) == fold
    ]
    wrong_accepted = 0
    review_auto = 0
    unsafe_count = 0
    correct_auto = 0
    non_review_count = 0
    use_count = 0
    use_correct_auto = 0
    tp = fp = fn = tn = 0
    clue_only_caught = 0
    clue_only_scope = 0
    for group_id in group_ids:
        group = group_by_id[group_id]
        truth_candidate_id = group.candidates[group.truth_index].candidate_id
        decision = decisions[(seed, group_id)]
        evaluation = evaluations[(seed, group_id)]
        final = effective[(seed, group_id)]
        accepted = bool(final["accepted"])
        correct = str(final["effective_candidate_id"]) == truth_candidate_id
        wrong_accepted += int(accepted and not correct)
        review_auto += int(accepted and group.truth_target == "REVIEW_FALLBACK")
        raw_unsafe = (
            str(evaluation["selected_candidate_id"]) != truth_candidate_id
            or group.truth_target == "REVIEW_FALLBACK"
        )
        unsafe_count += int(raw_unsafe)
        if group.truth_target != "REVIEW_FALLBACK":
            non_review_count += 1
            correct_auto += int(accepted and correct)
        if group.truth_target == "USE_RCSD":
            use_count += 1
            use_correct_auto += int(accepted and correct)
        clue_truth = bool(group.anomaly_target)
        clue_predicted = bool(decision["clue_predicted"])
        tp += int(clue_truth and clue_predicted)
        fp += int(not clue_truth and clue_predicted)
        fn += int(clue_truth and not clue_predicted)
        tn += int(not clue_truth and not clue_predicted)
        if group_id in clue_only_group_ids:
            clue_only_scope += 1
            clue_only_caught += int(clue_predicted)
    carrier_safety_recall = 1.0 - (wrong_accepted + review_auto) / max(1, unsafe_count)
    safe_coverage = correct_auto / max(1, non_review_count)
    use_coverage = use_correct_auto / max(1, use_count)
    clue_recall = tp / max(1, tp + fn)
    clue_precision = tp / max(1, tp + fp)
    positive_f1 = _f1(tp, fp, fn)
    negative_f1 = _f1(tn, fn, fp)
    macro_f1 = (positive_f1 + negative_f1) / 2
    carrier_gate = (
        wrong_accepted == 0
        and review_auto == 0
        and carrier_safety_recall == 1.0
        and safe_coverage >= config.minimum_safe_coverage
        and use_coverage >= config.minimum_use_rcsd_safe_coverage
    )
    clue_gate = (
        clue_recall == 1.0
        and clue_precision >= config.minimum_clue_precision
        and macro_f1 >= config.minimum_clue_macro_f1
        and clue_only_caught == clue_only_scope
    )
    return {
        "scope": "SEED" if fold is None else "FOLD",
        "seed": seed,
        "fold": fold,
        "group_count": len(group_ids),
        "carrier_wrong_accepted_count": wrong_accepted,
        "review_auto_publish_count": review_auto,
        "carrier_unsafe_count": unsafe_count,
        "carrier_safety_recall": carrier_safety_recall,
        "safe_coverage": safe_coverage,
        "use_rcsd_safe_coverage": use_coverage,
        "clue_true_positive": tp,
        "clue_false_positive": fp,
        "clue_false_negative": fn,
        "clue_true_negative": tn,
        "clue_recall": clue_recall,
        "clue_precision": clue_precision,
        "clue_macro_f1": macro_f1,
        "clue_only_scope_count": clue_only_scope,
        "clue_only_caught_count": clue_only_caught,
        "carrier_gate_pass": carrier_gate,
        "clue_gate_pass": clue_gate,
    }


def _base_node_scores(
    root_value: Path, base_seeds: Sequence[int]
) -> dict[str, dict[str, float]]:
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p1_oof_manifest.json")
    record = dict((manifest.get("outputs") or {}).get("scores") or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    seed_set = set(base_seeds)
    for row in _read_jsonl(path):
        if row.get("object_type") == "NODE" and int(row["seed"]) in seed_set:
            values[str(row["group_id"])][str(row["candidate_id"])].append(
                float(row["score"])
            )
    result: dict[str, dict[str, float]] = {}
    for group_id, candidate_values in values.items():
        if any(len(rows) != len(base_seeds) for rows in candidate_values.values()):
            raise ValueError(f"base Node score seed denominator differs: {group_id}")
        result[group_id] = {
            candidate_id: sum(rows) / len(rows)
            for candidate_id, rows in candidate_values.items()
        }
    return result


def _payload_path(dataset: Mapping[str, Any]) -> Path:
    record = dict((dataset["dataset_manifest"].get("outputs") or {}).get("payloads") or {})
    return normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)


def _reference_match(
    reference_root_value: Path | None, determinism_signature: str
) -> bool | None:
    if reference_root_value is None:
        return None
    root = normalize_runtime_path(reference_root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p0_manifest.json")
    return str(manifest.get("determinism_signature") or "") == determinism_signature


def _normalized_effective(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"output", "wall_seconds"}
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile values must not be empty")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    denominator = 2 * true_positive + false_positive + false_negative
    return 1.0 if denominator == 0 else 2 * true_positive / denominator


def _validation_report(summary: Mapping[str, Any]) -> str:
    metrics = summary["metrics"]
    lines = [
        "# P05-Scheme-A-P2-P3-P0 Validation",
        "",
        f"- decision: `{summary['decision']}`",
        f"- carrier gate: `{summary['carrier_gate_pass']}`",
        f"- clue gate: `{summary['clue_gate_pass']}`",
        f"- RoadGraph gate: `{summary['roadgraph_gate_pass']}`",
        f"- source/model/resource gate: `{summary['source_gate_pass']}` / "
        f"`{summary['model_contract_gate_pass']}` / `{summary['resource_gate_pass']}`",
        f"- parameter count: `{summary['parameter_count_min']}–"
        f"{summary['parameter_count_max']}`",
        f"- determinism signature: `{summary['determinism_signature']}`",
        f"- reference match: `{summary['reference_run_match']}`",
        f"- scope metric rows: `{len(metrics['scope_metrics'])}`",
        "",
    ]
    return "\n".join(lines)


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["run_scheme_a_p2_p3_p0_oof"]
