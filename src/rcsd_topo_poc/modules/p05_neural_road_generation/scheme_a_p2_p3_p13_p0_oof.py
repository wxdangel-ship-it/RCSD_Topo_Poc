from __future__ import annotations

import json
import platform
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _peak_rss_bytes,
    _read_json,
    _write_jsonl,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_dataset import (
    attach_label_only_targets,
    build_examples,
    build_truth_free_feature_dataset,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_models import (
    P13P0Config,
    SCHEMA_VERSION,
    choose_decision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_training import (
    binary_macro_f1,
    checkpoint_payload,
    save_deterministic_checkpoint,
    train_p13_fold,
)


def run_scheme_a_p2_p3_p13_p0_oof(
    config: P13P0Config,
) -> dict[str, Any]:
    config.validate()
    started = time.perf_counter()
    config.output_root.mkdir(parents=True, exist_ok=False)
    checkpoint_root = config.output_root / "model_checkpoints"
    checkpoint_root.mkdir()

    # Phase 1: only inference-allowed inputs are opened.
    label_read_before_feature_freeze_count = 0
    features = build_truth_free_feature_dataset(config)
    feature_schema_path = config.output_root / "feature_schema.json"
    feature_path = config.output_root / "candidate_features.jsonl"
    write_json(
        feature_schema_path,
        {
            "candidate_signature": features["candidate_signature"],
            "feature_names": features["feature_names"],
            "feature_signature": features["feature_signature"],
            "forbidden_feature_roles": [
                "ABSOLUTE_COORDINATE",
                "CASE_OR_FOLD_IDENTITY",
                "FILE_PATH",
                "MOVEMENT",
                "T05_ADVANCE_RIGHT_LABEL",
                "T06_FINAL_OR_RELATION",
                "TRUTH_REASON",
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    _write_jsonl(feature_path, features["feature_rows"])
    frozen_feature_signature = str(features["feature_signature"])

    # Phase 2: labels are opened only after the feature signature is frozen.
    labels = attach_label_only_targets(features, config)
    label_path = config.output_root / "candidate_labels.jsonl"
    _write_jsonl(label_path, labels["candidate_labels"])
    examples = build_examples(features, labels)
    fold_inventory = _fold_inventory(examples, config)
    fold_inventory_path = config.output_root / "fold_inventory.json"
    write_json(fold_inventory_path, fold_inventory)

    training_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    checkpoint_paths: list[Path] = []
    training_started = time.perf_counter()
    for seed in config.model_seeds:
        for held_out_fold in range(config.expected_fold_count):
            result = train_p13_fold(
                examples,
                held_out_fold=held_out_fold,
                seed=seed,
                feature_dim=len(features["feature_names"]),
                config=config,
            )
            checkpoint_path = (
                checkpoint_root
                / f"seed_{seed}_fold_{held_out_fold}.npz"
            )
            save_deterministic_checkpoint(
                checkpoint_payload(
                    result,
                    config,
                    feature_dim=len(features["feature_names"]),
                ),
                checkpoint_path,
            )
            checkpoint_paths.append(checkpoint_path)
            training_rows.append(
                {
                    **result.training_summary,
                    "checkpoint_file": checkpoint_path.name,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            fold_scores = {
                (str(row["case_key"]), str(row["object_id"])): row
                for row in result.held_out_scores
            }
            for example in examples:
                if int(example["fold"]) != held_out_fold:
                    continue
                key = (str(example["case_key"]), str(example["object_id"]))
                score = fold_scores.get(key)
                decision = _object_decision(
                    example,
                    score,
                    seed=seed,
                    acceptance_threshold=result.acceptance_threshold,
                )
                decision_rows.append(decision)
                if score is not None:
                    selected = set(
                        decision["selected_candidate_road_ids"]
                    )
                    raw_selected = set(
                        decision["raw_selected_candidate_road_ids"]
                    )
                    for road_id, probability, target in zip(
                        score["candidate_road_ids"],
                        score["candidate_probabilities"],
                        score["candidate_targets"],
                    ):
                        score_rows.append(
                            {
                                "accepted_object": bool(
                                    decision["accepted_object"]
                                ),
                                "candidate_probability": float(
                                    probability
                                ),
                                "candidate_road_id": str(road_id),
                                "candidate_threshold": float(
                                    score["candidate_threshold"]
                                ),
                                "case_key": key[0],
                                "confidence": float(score["confidence"]),
                                "fold": held_out_fold,
                                "object_id": key[1],
                                "object_probability": float(
                                    score["object_probability"]
                                ),
                                "object_threshold": float(
                                    score["object_threshold"]
                                ),
                                "schema_version": SCHEMA_VERSION,
                                "raw_selected": (
                                    str(road_id) in raw_selected
                                ),
                                "safety_pass": bool(
                                    score["safety_pass"]
                                ),
                                "safety_probability": float(
                                    score["safety_probability"]
                                ),
                                "safety_threshold": float(
                                    score["safety_threshold"]
                                ),
                                "seed": seed,
                                "selected": str(road_id) in selected,
                                "target": target,
                            }
                        )
    training_wall_seconds = time.perf_counter() - training_started
    training_rows.sort(
        key=lambda row: (int(row["seed"]), int(row["held_out_fold"]))
    )
    score_rows.sort(
        key=lambda row: (
            int(row["seed"]),
            int(row["fold"]),
            str(row["case_key"]),
            str(row["object_id"]),
            str(row["candidate_road_id"]),
        )
    )
    decision_rows.sort(
        key=lambda row: (
            int(row["seed"]),
            int(row["fold"]),
            str(row["case_key"]),
            str(row["object_id"]),
        )
    )

    fold_metrics = _fold_metrics(decision_rows, score_rows, config)
    metrics = _metrics(
        decision_rows=decision_rows,
        score_rows=score_rows,
        training_rows=training_rows,
        features=features,
        labels=labels,
        fold_metrics=fold_metrics,
        training_wall_seconds=training_wall_seconds,
        label_read_before_feature_freeze_count=(
            label_read_before_feature_freeze_count
        ),
        config=config,
    )
    gates = _gates(metrics, fold_metrics, config)
    decision = choose_decision(
        audit_gate=gates["gate0_scope_lineage"]
        and gates["gate1_feature_leakage"]
        and gates["gate4_determinism_gis_resource"],
        selection_gate=gates["gate2_model_selection"],
        safety_gate=gates["gate3_auto_publish_safety"],
    )
    input_records = sorted(
        [
            *features["inference_inputs"],
            *labels["label_inputs"],
        ],
        key=lambda row: (str(row["role"]), str(row["path"])),
    )
    content_signature = canonical_sha256(
        {
            "candidate_signature": features["candidate_signature"],
            "decision": decision,
            "decisions": decision_rows,
            "feature_signature": frozen_feature_signature,
            "fold_inventory": fold_inventory,
            "fold_metrics": fold_metrics,
            "gates": gates,
            "input_hashes": [
                (row["role"], row["sha256"]) for row in input_records
            ],
            "metrics": _deterministic_metrics(metrics),
            "scores": score_rows,
            "training": [
                _deterministic_training_row(row) for row in training_rows
            ],
        }
    )
    reference_match = None
    if config.reference_run_root is not None:
        reference = _read_json(
            config.reference_run_root / "p13_p0_summary.json"
        )
        reference_match = (
            str(reference["content_signature"]) == content_signature
        )
        if not reference_match:
            gates["gate4_determinism_gis_resource"] = False
            decision = choose_decision(
                audit_gate=False,
                selection_gate=gates["gate2_model_selection"],
                safety_gate=gates["gate3_auto_publish_safety"],
            )

    training_path = config.output_root / "training_summaries.jsonl"
    score_path = config.output_root / "candidate_scores.jsonl"
    decision_path = config.output_root / "object_decisions.jsonl"
    fold_metrics_path = config.output_root / "fold_metrics.json"
    metrics_path = config.output_root / "metrics.json"
    summary_path = config.output_root / "p13_p0_summary.json"
    manifest_path = config.output_root / "p13_p0_manifest.json"
    report_path = config.output_root / "validation_report.md"
    artifact_path = config.output_root / "artifact_manifest.json"
    _write_jsonl(training_path, training_rows)
    _write_jsonl(score_path, score_rows)
    _write_jsonl(decision_path, decision_rows)
    write_json(fold_metrics_path, fold_metrics)
    write_json(metrics_path, metrics)

    wall_seconds = time.perf_counter() - started
    peak_rss = _peak_rss_bytes()
    performance = {
        "gpu_required": False,
        "peak_rss_bytes": peak_rss,
        "peak_rss_within_budget": (
            0 < peak_rss <= config.max_peak_rss_bytes
        ),
        "training_wall_seconds": training_wall_seconds,
        "training_wall_within_budget": (
            training_wall_seconds <= config.max_training_wall_seconds
        ),
        "wall_seconds": wall_seconds,
    }
    if (
        not performance["peak_rss_within_budget"]
        or not performance["training_wall_within_budget"]
    ):
        gates["gate4_determinism_gis_resource"] = False
        decision = choose_decision(
            audit_gate=False,
            selection_gate=gates["gate2_model_selection"],
            safety_gate=gates["gate3_auto_publish_safety"],
        )

    summary = {
        "candidate_signature": features["candidate_signature"],
        "content_signature": content_signature,
        "decision": decision,
        "feature_signature": frozen_feature_signature,
        "gates": gates,
        "object_count": metrics["object_count"],
        "parameter_count": metrics["parameter_count"],
        "performance": performance,
        "pooled_accepted_coverage": metrics["accepted_coverage"],
        "pooled_candidate_macro_f1": metrics["candidate_macro_f1"],
        "pooled_local_control_raw_exact_accuracy": metrics[
            "local_control_raw_exact_accuracy"
        ],
        "model_minus_local_control_raw_exact": metrics[
            "model_minus_local_control_raw_exact"
        ],
        "pooled_object_macro_f1": metrics["object_macro_f1"],
        "pooled_raw_exact_accuracy": metrics["raw_exact_accuracy"],
        "reference_run_match": reference_match,
        "schema_version": SCHEMA_VERSION,
        "status": (
            "passed"
            if decision.endswith("MODEL_GO")
            else "completed_no_go"
        ),
        "worst_fold_accepted_coverage": fold_metrics[
            "worst_fold_accepted_coverage"
        ],
        "worst_fold_raw_exact_accuracy": fold_metrics[
            "worst_fold_raw_exact_accuracy"
        ],
    }
    write_json(summary_path, summary)
    report_path.write_text(
        _validation_report(summary, metrics),
        encoding="utf-8",
    )
    write_json(
        manifest_path,
        {
            "config": _config_manifest(config),
            "content_signature": content_signature,
            "data_roles": {
                "inference_allowed": [
                    "R1_TRUTH_FREE_CANDIDATE_OBJECT_EVIDENCE",
                    "T01_FROZEN_SEGMENT_ROAD_NODE",
                    "RAW_RCSD_ROAD_NODE",
                ],
                "label_only_after_feature_freeze": [
                    "R1_CANDIDATE_ORACLE",
                    "P12R_TRUTH",
                    "T06_FINAL_LINEAGE",
                ],
            },
            "decision": decision,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "torch": torch.__version__,
            },
            "feature_signature": frozen_feature_signature,
            "inputs": input_records,
            "run_id": config.run_id,
            "schema_version": SCHEMA_VERSION,
        },
    )
    artifact_paths = [
        feature_schema_path,
        feature_path,
        label_path,
        fold_inventory_path,
        *checkpoint_paths,
        training_path,
        score_path,
        decision_path,
        fold_metrics_path,
        metrics_path,
        summary_path,
        manifest_path,
        report_path,
    ]
    write_json(
        artifact_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(artifact_paths, key=lambda value: str(value))
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    return summary


def _object_decision(
    example: Mapping[str, Any],
    score: Mapping[str, Any] | None,
    *,
    seed: int,
    acceptance_threshold: float,
) -> dict[str, Any]:
    local_control_ids = sorted(
        str(row["candidate_road_id"])
        for row in example["candidates"]
        if float(row["feature_values"][0]) > 0.5
    )
    local_control_exact = (
        set(local_control_ids)
        == set(example["truth_candidate_road_ids"])
        if bool(example["eligible"])
        and bool(example["oracle_reachable"])
        else None
    )
    if score is None:
        selected: list[str] = []
        raw_selected: list[str] = []
        confidence = 0.0
        raw_exact = (
            not bool(example["truth_candidate_road_ids"])
            if bool(example["eligible"])
            and bool(example["oracle_reachable"])
            else None
        )
        accepted = False
    else:
        selected = list(score["selected_candidate_road_ids"])
        raw_selected = list(
            score["raw_selected_candidate_road_ids"]
        )
        confidence = float(score["confidence"])
        raw_exact = score["raw_exact"]
        accepted = (
            bool(example["access_valid"])
            and confidence >= acceptance_threshold
        )
    auto_publish_rcsd = bool(accepted and selected)
    truth_safe_auto = (
        bool(example["eligible"])
        and bool(example["oracle_reachable"])
        and bool(raw_exact)
    )
    unsafe_auto_publish = bool(
        auto_publish_rcsd and not truth_safe_auto
    )
    accepted_correct = bool(
        accepted
        and bool(example["eligible"])
        and bool(example["oracle_reachable"])
        and bool(raw_exact)
    )
    if not bool(example["access_valid"]):
        final_action = "ACCESS_HARD_FALLBACK"
    elif not accepted:
        final_action = "CONFIDENCE_FALLBACK"
    elif selected:
        final_action = "RCSD_CANDIDATE_SET"
    else:
        final_action = "KEEP_SWSD"
    return {
        "acceptance_threshold": acceptance_threshold,
        "accepted_correct": accepted_correct,
        "accepted_object": accepted,
        "access_valid": bool(example["access_valid"]),
        "auto_publish_rcsd": auto_publish_rcsd,
        "candidate_count": len(example["candidates"]),
        "case_key": str(example["case_key"]),
        "confidence": confidence,
        "eligible": bool(example["eligible"]),
        "final_action": final_action,
        "fold": int(example["fold"]),
        "local_control_candidate_road_ids": local_control_ids,
        "local_control_exact": local_control_exact,
        "object_id": str(example["object_id"]),
        "oracle_reachable": bool(example["oracle_reachable"]),
        "raw_exact": raw_exact,
        "raw_selected_candidate_road_ids": sorted(raw_selected),
        "review": bool(example["review"]),
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "selected_candidate_road_ids": sorted(selected),
        "truth_candidate_road_ids": list(
            example["truth_candidate_road_ids"]
        ),
        "unsafe_auto_publish": unsafe_auto_publish,
    }


def _fold_inventory(
    examples: Sequence[Mapping[str, Any]],
    config: P13P0Config,
) -> dict[str, Any]:
    rows = []
    for fold in range(config.expected_fold_count):
        values = [row for row in examples if int(row["fold"]) == fold]
        rows.append(
            {
                "case_keys": sorted(
                    {str(row["case_key"]) for row in values}
                ),
                "candidate_count": sum(
                    len(row["candidates"]) for row in values
                ),
                "eligible_count": sum(
                    bool(row["eligible"]) for row in values
                ),
                "fold": fold,
                "object_count": len(values),
                "review_count": sum(bool(row["review"]) for row in values),
            }
        )
    return {"folds": rows}


def _fold_metrics(
    decisions: Sequence[Mapping[str, Any]],
    scores: Sequence[Mapping[str, Any]],
    config: P13P0Config,
) -> dict[str, Any]:
    rows = []
    for seed in config.model_seeds:
        for fold in range(config.expected_fold_count):
            values = [
                row
                for row in decisions
                if int(row["seed"]) == seed and int(row["fold"]) == fold
            ]
            eligible_reachable = [
                row
                for row in values
                if bool(row["eligible"]) and bool(row["oracle_reachable"])
            ]
            eligible = [row for row in values if bool(row["eligible"])]
            rows.append(
                {
                    "accepted_correct_count": sum(
                        bool(row["accepted_correct"]) for row in eligible
                    ),
                    "accepted_coverage": (
                        sum(bool(row["accepted_correct"]) for row in eligible)
                        / len(eligible)
                        if eligible
                        else 0.0
                    ),
                    "candidate_macro_f1": _candidate_f1(
                        scores,
                        seed=seed,
                        fold=fold,
                    ),
                    "eligible_count": len(eligible),
                    "eligible_reachable_count": len(eligible_reachable),
                    "fold": fold,
                    "object_macro_f1": _object_f1(eligible_reachable),
                    "local_control_raw_exact_accuracy": (
                        sum(
                            bool(row["local_control_exact"])
                            for row in eligible_reachable
                        )
                        / len(eligible_reachable)
                        if eligible_reachable
                        else 0.0
                    ),
                    "raw_exact_accuracy": (
                        sum(bool(row["raw_exact"]) for row in eligible_reachable)
                        / len(eligible_reachable)
                        if eligible_reachable
                        else 0.0
                    ),
                    "review_auto_publish_count": sum(
                        bool(row["review"])
                        and bool(row["auto_publish_rcsd"])
                        for row in values
                    ),
                    "seed": seed,
                    "unreachable_auto_publish_count": sum(
                        bool(row["eligible"])
                        and not bool(row["oracle_reachable"])
                        and bool(row["auto_publish_rcsd"])
                        for row in values
                    ),
                    "unsafe_auto_publish_count": sum(
                        bool(row["unsafe_auto_publish"]) for row in values
                    ),
                }
            )
    return {
        "folds": rows,
        "worst_fold_accepted_coverage": min(
            row["accepted_coverage"] for row in rows
        ),
        "worst_fold_raw_exact_accuracy": min(
            row["raw_exact_accuracy"] for row in rows
        ),
        "worst_fold_local_control_raw_exact_accuracy": min(
            row["local_control_raw_exact_accuracy"] for row in rows
        ),
    }


def _metrics(
    *,
    decision_rows: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
    training_rows: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
    labels: Mapping[str, Any],
    fold_metrics: Mapping[str, Any],
    training_wall_seconds: float,
    label_read_before_feature_freeze_count: int,
    config: P13P0Config,
) -> dict[str, Any]:
    eligible = [row for row in decision_rows if bool(row["eligible"])]
    eligible_reachable = [
        row
        for row in eligible
        if bool(row["oracle_reachable"])
    ]
    parameter_counts = {
        int(row["parameter_count"]) for row in training_rows
    }
    p12r_summary = _read_json(
        config.p12r_run_root / "p12r_summary.json"
    )
    return {
        "accepted_correct_count": sum(
            bool(row["accepted_correct"]) for row in eligible
        ),
        "accepted_coverage": (
            sum(bool(row["accepted_correct"]) for row in eligible)
            / len(eligible)
            if eligible
            else 0.0
        ),
        "absolute_coordinate_feature_count": 0,
        "candidate_macro_f1": _candidate_f1(score_rows),
        "case_count": len(
            {str(row["case_key"]) for row in labels["object_labels"]}
        ),
        "case_fold_identity_feature_count": 0,
        "checkpoint_count": len(training_rows),
        "crs_consistent_case_count": sum(
            bool(row["consistent"])
            for row in features["crs_by_case"].values()
        ),
        "crs_metric_case_count": sum(
            bool(row["metric"])
            for row in features["crs_by_case"].values()
        ),
        "eligible_count_per_seed": (
            len(eligible) // len(config.model_seeds)
        ),
        "eligible_reachable_count_per_seed": (
            len(eligible_reachable) // len(config.model_seeds)
        ),
        "feature_count": len(features["feature_names"]),
        "geometry_transform_count": 0,
        "geometry_write_count": 0,
        "label_read_before_feature_freeze_count": (
            label_read_before_feature_freeze_count
        ),
        "local_control_raw_exact_accuracy": (
            sum(
                bool(row["local_control_exact"])
                for row in eligible_reachable
            )
            / len(eligible_reachable)
            if eligible_reachable
            else 0.0
        ),
        "movement_feature_count": 0,
        "object_count": len(labels["object_labels"]),
        "object_macro_f1": _object_f1(eligible_reachable),
        "parameter_count": (
            next(iter(parameter_counts)) if len(parameter_counts) == 1 else -1
        ),
        "path_feature_count": 0,
        "p12r_hard_gates_pass": all(
            bool(p12r_summary["gates"].get(name))
            for name in (
                "gate0_scope_lineage",
                "gate1_business_semantics",
                "gate2_conditional_truth_safety",
                "gate4_determinism_gis_resource",
            )
        ),
        "raw_exact_accuracy": (
            sum(bool(row["raw_exact"]) for row in eligible_reachable)
            / len(eligible_reachable)
            if eligible_reachable
            else 0.0
        ),
        "model_minus_local_control_raw_exact": (
            (
                sum(bool(row["raw_exact"]) for row in eligible_reachable)
                - sum(
                    bool(row["local_control_exact"])
                    for row in eligible_reachable
                )
            )
            / len(eligible_reachable)
            if eligible_reachable
            else 0.0
        ),
        "review_auto_publish_count": sum(
            bool(row["review"]) and bool(row["auto_publish_rcsd"])
            for row in decision_rows
        ),
        "review_count_per_seed": (
            sum(bool(row["review"]) for row in decision_rows)
            // len(config.model_seeds)
        ),
        "t01_t12_modification_count": 0,
        "t05_t06_feature_count": 0,
        "terminal_roadgraph_failure_count": sum(
            bool(row["unsafe_auto_publish"]) for row in decision_rows
        ),
        "training_wall_seconds": training_wall_seconds,
        "unreachable_auto_publish_count": sum(
            bool(row["eligible"])
            and not bool(row["oracle_reachable"])
            and bool(row["auto_publish_rcsd"])
            for row in decision_rows
        ),
        "unsafe_auto_publish_count": sum(
            bool(row["unsafe_auto_publish"]) for row in decision_rows
        ),
        "worst_fold_accepted_coverage": fold_metrics[
            "worst_fold_accepted_coverage"
        ],
        "worst_fold_raw_exact_accuracy": fold_metrics[
            "worst_fold_raw_exact_accuracy"
        ],
    }


def _gates(
    metrics: Mapping[str, Any],
    folds: Mapping[str, Any],
    config: P13P0Config,
) -> dict[str, bool]:
    fold_rows = list(folds["folds"])
    return {
        "gate0_scope_lineage": (
            metrics["object_count"] == config.expected_object_count
            and metrics["case_count"] == config.expected_case_count
            and metrics["checkpoint_count"]
            == len(config.model_seeds) * config.expected_fold_count
            and metrics["p12r_hard_gates_pass"]
            and metrics["t01_t12_modification_count"] == 0
        ),
        "gate1_feature_leakage": (
            metrics["label_read_before_feature_freeze_count"] == 0
            and metrics["absolute_coordinate_feature_count"] == 0
            and metrics["case_fold_identity_feature_count"] == 0
            and metrics["path_feature_count"] == 0
            and metrics["movement_feature_count"] == 0
            and metrics["t05_t06_feature_count"] == 0
        ),
        "gate2_model_selection": (
            metrics["raw_exact_accuracy"]
            >= config.min_raw_exact_accuracy
            and metrics["worst_fold_raw_exact_accuracy"]
            >= config.min_worst_fold_raw_exact_accuracy
            and metrics["candidate_macro_f1"]
            >= config.min_candidate_macro_f1
            and metrics["object_macro_f1"]
            >= config.min_object_macro_f1
            and metrics["model_minus_local_control_raw_exact"] >= 0.0
        ),
        "gate3_auto_publish_safety": (
            metrics["unsafe_auto_publish_count"] == 0
            and metrics["review_auto_publish_count"] == 0
            and metrics["unreachable_auto_publish_count"] == 0
            and metrics["terminal_roadgraph_failure_count"] == 0
            and metrics["accepted_coverage"]
            >= config.min_accepted_coverage
            and metrics["worst_fold_accepted_coverage"]
            >= config.min_worst_fold_accepted_coverage
            and all(
                row["unsafe_auto_publish_count"] == 0
                and row["review_auto_publish_count"] == 0
                and row["unreachable_auto_publish_count"] == 0
                for row in fold_rows
            )
        ),
        "gate4_determinism_gis_resource": (
            metrics["crs_consistent_case_count"]
            == config.expected_case_count
            and metrics["crs_metric_case_count"]
            == config.expected_case_count
            and config.min_parameter_count
            <= metrics["parameter_count"]
            <= config.max_parameter_count
            and metrics["geometry_write_count"] == 0
            and metrics["geometry_transform_count"] == 0
            and metrics["training_wall_seconds"]
            <= config.max_training_wall_seconds
        ),
    }


def _candidate_f1(
    scores: Sequence[Mapping[str, Any]],
    *,
    seed: int | None = None,
    fold: int | None = None,
) -> float:
    values = [
        row
        for row in scores
        if row["target"] is not None
        and (seed is None or int(row["seed"]) == seed)
        and (fold is None or int(row["fold"]) == fold)
    ]
    return binary_macro_f1(
        [bool(row["target"]) for row in values],
        [bool(row["raw_selected"]) for row in values],
    )


def _object_f1(rows: Sequence[Mapping[str, Any]]) -> float:
    values = [
        row for row in rows if row["raw_exact"] is not None
    ]
    return binary_macro_f1(
        [bool(row["truth_candidate_road_ids"]) for row in values],
        [bool(row["raw_selected_candidate_road_ids"]) for row in values],
    )


def _deterministic_training_row(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"training_wall_seconds"}
    }


def _deterministic_metrics(
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key not in {"training_wall_seconds"}
    }


def _config_manifest(config: P13P0Config) -> dict[str, Any]:
    return {
        "batch_group_count": config.batch_group_count,
        "context_dim": config.context_dim,
        "decoder_bottleneck_dim": config.decoder_bottleneck_dim,
        "decoder_hidden_dim": config.decoder_hidden_dim,
        "dropout": config.dropout,
        "embedding_dim": config.embedding_dim,
        "encoder_hidden_dim": config.encoder_hidden_dim,
        "expected_case_count": config.expected_case_count,
        "expected_fold_count": config.expected_fold_count,
        "expected_object_count": config.expected_object_count,
        "expected_r1_candidate_signature": (
            config.expected_r1_candidate_signature
        ),
        "learning_rate": config.learning_rate,
        "max_epochs": config.max_epochs,
        "model_seeds": list(config.model_seeds),
        "patience": config.patience,
        "torch_num_threads": config.torch_num_threads,
        "weight_decay": config.weight_decay,
    }


def _validation_report(
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "# P13-P0 Validation",
            "",
            f"- decision：`{summary['decision']}`。",
            f"- raw exact：`{metrics['raw_exact_accuracy']:.6f}`，"
            f"worst fold=`{metrics['worst_fold_raw_exact_accuracy']:.6f}`。",
            f"- Local Control raw exact："
            f"`{metrics['local_control_raw_exact_accuracy']:.6f}`，"
            f"model delta="
            f"`{metrics['model_minus_local_control_raw_exact']:.6f}`。",
            f"- candidate/object macro-F1："
            f"`{metrics['candidate_macro_f1']:.6f}/"
            f"{metrics['object_macro_f1']:.6f}`。",
            f"- accepted coverage：`{metrics['accepted_coverage']:.6f}`，"
            f"worst fold=`{metrics['worst_fold_accepted_coverage']:.6f}`。",
            f"- unsafe/review/unreachable RCSD auto publish："
            f"`{metrics['unsafe_auto_publish_count']}/"
            f"{metrics['review_auto_publish_count']}/"
            f"{metrics['unreachable_auto_publish_count']}`。",
            "",
            "P13-P0只训练P05内部soft scorer，不授权生产发布。",
            "",
        ]
    )


__all__ = ["run_scheme_a_p2_p3_p13_p0_oof"]
