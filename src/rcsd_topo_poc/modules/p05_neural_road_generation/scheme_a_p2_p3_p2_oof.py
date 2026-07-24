from __future__ import annotations

import json
import math
import resource
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_execution import (
    load_p2_p1_payloads,
    materialize_p2_p1_seed,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_oof import (
    build_joint_safety_selections,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_oof import (
    _all_metrics,
    _base_node_scores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_training import (
    decision_from_score,
    train_hierarchical_fold,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_dataset import (
    load_dataset_p1_hierarchical_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_MODEL_NO_GO,
    DECISION_SCORER_GO,
    SCHEME_A_P2_P3_P2_SCHEMA,
    SchemeAP2P3P2Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p3_p2_oof(config: SchemeAP2P3P2Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    examples, metadata = load_dataset_p1_hierarchical_examples(config)
    score_rows: list[dict[str, Any]] = []
    eligible_decisions: list[dict[str, Any]] = []
    evaluation_rows: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    training_started = time.perf_counter()
    failure_group_ids = set(metadata["failure_group_ids"])
    for seed in config.base_config.model_seeds:
        for fold in range(config.base_config.expected_fold_count):
            result = train_hierarchical_fold(
                examples,
                config=config.base_config,
                held_out_fold=fold,
                seed=seed,
                dataset_manifest_sha256=metadata["lineage"][
                    "dataset_p1_training_signature"
                ],
            )
            training_summary = dict(result.training_summary)
            model_signature = str(training_summary["model_signature"])
            fold_records.append(
                {
                    **training_summary,
                    "eligible_train_group_count": training_summary["train_group_count"],
                    "eligible_inner_group_count": training_summary["inner_group_count"],
                    "eligible_held_out_group_count": training_summary[
                        "held_out_group_count"
                    ],
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
                        "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
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
                        "label_eligible": True,
                        "feature_uses_truth": False,
                        "label_only_source_used_as_input": False,
                        "movement_used": False,
                    }
                )
                raw_decision = decision_from_score(
                    row,
                    result.thresholds,
                    seed=seed,
                    model_signature=model_signature,
                )
                decision = apply_localized_failure(
                    raw_decision,
                    failure_group_ids=failure_group_ids,
                )
                eligible_decisions.append(
                    {
                        "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
                        **decision,
                        "label_eligible": True,
                    }
                )
                evaluation_rows.append(
                    {
                        "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
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
                        "label_eligible": True,
                        "label_only": True,
                    }
                )
            del result
    training_seconds = time.perf_counter() - training_started

    context_decisions = [
        {
            "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
            **build_dataset_p1_context_fallback(example, seed=seed),
            "label_eligible": False,
        }
        for seed in config.base_config.model_seeds
        for example in metadata["context_examples"]
    ]
    all_segment_decisions = sorted(
        [*eligible_decisions, *context_decisions],
        key=_seed_group_key,
    )
    _validate_decision_scope(config, eligible_decisions, context_decisions)

    all_groups = list(metadata["all_groups"])
    payload_path = _payload_path(metadata["dataset"])
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    node_scores = _base_node_scores(
        config.base_config.base_oof_run_a,
        config.base_config.base_seeds,
    )
    expected_failure_cases = set(metadata["failure_by_case"])
    expected_failure_manifest = {
        case_key: frozenset(info["failures"])
        for case_key, info in metadata["failure_by_case"].items()
    }
    roadgraph_rows: list[dict[str, Any]] = []
    effective_rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    for seed in config.base_config.model_seeds:
        seed_decisions = [
            row for row in all_segment_decisions if int(row["seed"]) == seed
        ]
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

    eligible_ids = {example.group.group_id for example in examples}
    eligible_effective = [
        row
        for row in effective_rows
        if row.get("object_type") == "SEGMENT"
        and str(row["group_id"]) in eligible_ids
    ]
    metrics = _all_metrics(
        examples,
        eligible_decisions,
        evaluation_rows,
        eligible_effective,
        roadgraph_rows,
        closure_rows,
        fold_records,
        metadata["eligible_clue_only_group_ids"],
        config.base_config,
    )
    execution_audit = _execution_scope_audit(
        config,
        all_segment_decisions=all_segment_decisions,
        effective_rows=effective_rows,
        scope_application_rows=metadata["scope_application_rows"],
        roadgraph_rows=roadgraph_rows,
        closure_rows=closure_rows,
        failure_group_ids=failure_group_ids,
        expected_failure_cases=expected_failure_cases,
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
    source_gate_pass = (
        all(
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
        and metadata["scope_audit"]["context_label_weight_count"] == 0
        and metadata["scope_audit"]["context_metric_eligible_count"] == 0
    )
    parameter_counts = {int(row["parameter_count"]) for row in fold_records}
    model_contract_gate_pass = (
        bool(parameter_counts)
        and min(parameter_counts)
        >= config.base_config.target_min_parameter_count
        and max(parameter_counts)
        <= config.base_config.target_max_parameter_count
        and max(parameter_counts)
        <= config.base_config.hard_max_parameter_count
    )
    deterministic_payload = {
        "lineage": metadata["lineage"],
        "scores": sorted(score_rows, key=_seed_group_key),
        "eligible_decisions": sorted(eligible_decisions, key=_seed_group_key),
        "context_decisions": sorted(context_decisions, key=_seed_group_key),
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
            for row in sorted(
                roadgraph_rows,
                key=lambda item: (int(item["seed"]), str(item["case_key"])),
            )
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
                fold_records,
                key=lambda item: (
                    int(item["seed"]),
                    int(item["held_out_fold"]),
                ),
            )
        ],
        "metrics": _deterministic_metrics(metrics),
        "execution_audit": execution_audit,
    }
    determinism_signature = canonical_sha256(deterministic_payload)
    reference_run_match = _reference_match(
        config.reference_run_root,
        determinism_signature,
    )
    audit_gate_pass = (
        source_gate_pass
        and model_contract_gate_pass
        and resource_gate_pass
        and execution_audit["gate_pass"]
        and (reference_run_match is not False)
    )
    model_gate_pass = (
        metrics["carrier_gate_pass"]
        and metrics["clue_gate_pass"]
        and metrics["roadgraph_gate_pass"]
    )
    if not audit_gate_pass:
        decision = DECISION_AUDIT_NO_GO
    elif model_gate_pass:
        decision = DECISION_SCORER_GO
    else:
        decision = DECISION_MODEL_NO_GO

    paths = {
        "scope_application": run_root / "dataset_p1_scope_application.jsonl",
        "scores": run_root / "eligible_scores.jsonl",
        "eligible_decisions": run_root / "eligible_decisions.jsonl",
        "evaluation": run_root / "eligible_evaluation.jsonl",
        "all_segment_decisions": run_root / "all_segment_decisions.jsonl",
        "effective": run_root / "effective_selections.jsonl",
        "roadgraphs": run_root / "roadgraph_index.jsonl",
        "closure": run_root / "junction_closure.jsonl",
        "folds": run_root / "fold_index.json",
        "metrics": run_root / "metrics.json",
        "feature_audit": run_root / "feature_audit.json",
        "summary": run_root / "scheme_a_p2_p3_p2_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["scope_application"], metadata["scope_application_rows"])
    _write_jsonl(paths["scores"], sorted(score_rows, key=_seed_group_key))
    _write_jsonl(
        paths["eligible_decisions"],
        sorted(eligible_decisions, key=_seed_group_key),
    )
    _write_jsonl(paths["evaluation"], sorted(evaluation_rows, key=_seed_group_key))
    _write_jsonl(paths["all_segment_decisions"], all_segment_decisions)
    _write_jsonl(paths["effective"], sorted(effective_rows, key=_seed_group_key))
    _write_jsonl(
        paths["roadgraphs"],
        sorted(
            roadgraph_rows,
            key=lambda row: (int(row["seed"]), str(row["case_key"])),
        ),
    )
    _write_jsonl(
        paths["closure"],
        sorted(closure_rows, key=lambda row: int(row["seed"])),
    )
    write_json(paths["folds"], {"folds": fold_records})
    write_json(paths["metrics"], metrics)
    feature_audit = {
        **metadata["inference_feature_audit"],
        **metadata["scope_audit"],
        "source_gate_pass": source_gate_pass,
        "model_contract_gate_pass": model_contract_gate_pass,
        "resource_gate_pass": resource_gate_pass,
        "execution_scope_gate_pass": execution_audit["gate_pass"],
        "old_model_state_reused": False,
        "old_threshold_reused": False,
        "context_supervision_count": 0,
        "context_threshold_count": 0,
        "context_metric_count": 0,
        "movement_decision_count": 0,
        "skeleton_mutation_count": 0,
    }
    write_json(paths["feature_audit"], feature_audit)
    summary = {
        "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
        "decision": decision,
        "case_count": config.expected_case_count,
        "all_segment_count": config.expected_all_segment_count,
        "eligible_segment_count": config.expected_eligible_count,
        "context_segment_count": config.expected_context_count,
        "seed_count": len(config.base_config.model_seeds),
        "fold_count": config.base_config.expected_fold_count,
        "parameter_count_min": min(parameter_counts),
        "parameter_count_max": max(parameter_counts),
        "carrier_gate_pass": metrics["carrier_gate_pass"],
        "clue_gate_pass": metrics["clue_gate_pass"],
        "roadgraph_gate_pass": metrics["roadgraph_gate_pass"],
        "source_gate_pass": source_gate_pass,
        "model_contract_gate_pass": model_contract_gate_pass,
        "resource_gate_pass": resource_gate_pass,
        "execution_scope_gate_pass": execution_audit["gate_pass"],
        "reference_run_match": reference_run_match,
        "determinism_signature": determinism_signature,
        "metrics": metrics,
        "execution_scope_audit": execution_audit,
        "resource": resource_metrics,
        "scope_audit": metadata["scope_audit"],
        "lineage": metadata["lineage"],
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "t06_inference_feature_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_performed": False,
        "crs": "EPSG:3857",
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(_validation_report(summary), encoding="utf-8")
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p2_manifest.json"
    manifest = {
        "schema_version": SCHEME_A_P2_P3_P2_SCHEMA,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_p1_scorer_completed",
        "decision": decision,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_run_match,
        "lineage": metadata["lineage"],
        "parameters": {
            "model_seeds": list(config.base_config.model_seeds),
            "base_seeds": list(config.base_config.base_seeds),
            "fold_count": config.base_config.expected_fold_count,
            "eligible_segment_count": config.expected_eligible_count,
            "context_segment_count": config.expected_context_count,
            "network_schema": "p05-scheme-a-p2-p3-p0-network-v1",
            "embedding_dim": config.base_config.embedding_dim,
            "hidden_dim": config.base_config.hidden_dim,
            "evidence_hidden_dim": config.base_config.evidence_hidden_dim,
            "type_embedding_dim": config.base_config.type_embedding_dim,
            "numeric_dim": config.base_config.numeric_dim,
            "evidence_dim": config.base_config.expected_evidence_dim,
            "dropout": config.base_config.dropout,
            "learning_rate": config.base_config.learning_rate,
            "weight_decay": config.base_config.weight_decay,
            "max_epochs": config.base_config.max_epochs,
            "patience": config.base_config.patience,
            "device": config.base_config.device,
        },
        "outputs": outputs,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "t06_inference_feature_count": 0,
        "context_supervision_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p2-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def build_dataset_p1_context_fallback(
    example: Any,
    *,
    seed: int,
) -> dict[str, Any]:
    group = example.group
    keep = [
        candidate
        for candidate in group.candidates
        if candidate.candidate_target == "KEEP_SWSD"
    ]
    if len(keep) != 1:
        raise ValueError(f"context Segment lacks unique KEEP_SWSD: {group.group_id}")
    candidate = keep[0]
    return {
        "case_key": group.case_key,
        "fold": group.fold,
        "group_id": group.group_id,
        "object_id": group.object_id,
        "proposal_candidate_id": candidate.candidate_id,
        "proposal_target": candidate.candidate_target,
        "accepted": False,
        "risk": 1.0,
        "safety_probability": 0.0,
        "anomaly_probability": 0.0,
        "clue_predicted": False,
        "carrier_threshold": None,
        "clue_threshold": None,
        "reason": "dataset_p1_context_only_fallback",
        "seed": seed,
        "model_signature": "dataset-p1-context-only-fallback",
    }


def apply_localized_failure(
    decision: Mapping[str, Any],
    *,
    failure_group_ids: set[str] | frozenset[str],
) -> dict[str, Any]:
    result = dict(decision)
    if str(result["group_id"]) in failure_group_ids:
        result.update(
            {
                "accepted": False,
                "reason": "dataset_p1_localized_expected_failure",
            }
        )
    return result


def _validate_decision_scope(
    config: SchemeAP2P3P2Config,
    eligible_decisions: Sequence[Mapping[str, Any]],
    context_decisions: Sequence[Mapping[str, Any]],
) -> None:
    seed_count = len(config.base_config.model_seeds)
    if len(eligible_decisions) != config.expected_eligible_count * seed_count:
        raise ValueError("eligible OOF decision denominator differs")
    if len(context_decisions) != config.expected_context_count * seed_count:
        raise ValueError("context fallback decision denominator differs")
    if any(bool(row["accepted"]) for row in context_decisions):
        raise ValueError("context-only Segment was auto accepted")
    if any(row["reason"] != "dataset_p1_context_only_fallback" for row in context_decisions):
        raise ValueError("context-only fallback reason differs")


def _execution_scope_audit(
    config: SchemeAP2P3P2Config,
    *,
    all_segment_decisions: Sequence[Mapping[str, Any]],
    effective_rows: Sequence[Mapping[str, Any]],
    scope_application_rows: Sequence[Mapping[str, Any]],
    roadgraph_rows: Sequence[Mapping[str, Any]],
    closure_rows: Sequence[Mapping[str, Any]],
    failure_group_ids: set[str],
    expected_failure_cases: set[str],
) -> dict[str, Any]:
    scope_by_id = {
        str(row["group_id"]): row for row in scope_application_rows
    }
    context_ids = {
        group_id
        for group_id, row in scope_by_id.items()
        if not bool(row["label_eligible"])
    }
    context_decisions = [
        row
        for row in all_segment_decisions
        if str(row["group_id"]) in context_ids
    ]
    effective_segments = [
        row for row in effective_rows if row.get("object_type") == "SEGMENT"
    ]
    context_effective = [
        row for row in effective_segments if str(row["group_id"]) in context_ids
    ]
    expected_case_nonlocal_cascade = sum(
        row["case_key"] in expected_failure_cases
        and str(row["group_id"]) not in failure_group_ids
        and row["reason"] == "dataset_p1_localized_expected_failure"
        for row in all_segment_decisions
    )
    localized_rows = [
        row
        for row in all_segment_decisions
        if str(row["group_id"]) in failure_group_ids
    ]
    states_by_seed: dict[int, dict[str, int]] = {}
    for seed in config.base_config.model_seeds:
        states: dict[str, int] = {}
        for row in roadgraph_rows:
            if int(row["seed"]) == seed:
                state = str(row["terminal_state"])
                states[state] = states.get(state, 0) + 1
        states_by_seed[seed] = states
    closure_conflicts = sum(
        int(row.get("requirement_conflict_count") or 0)
        + int(row.get("node_target_mismatch_count") or 0)
        for row in closure_rows
    )
    gate = (
        len(all_segment_decisions)
        == config.expected_all_segment_count * len(config.base_config.model_seeds)
        and len(effective_segments)
        == config.expected_all_segment_count * len(config.base_config.model_seeds)
        and len(context_decisions)
        == config.expected_context_count * len(config.base_config.model_seeds)
        and not any(bool(row["accepted"]) for row in context_decisions)
        and not any(
            row.get("effective_target") != "KEEP_SWSD" for row in context_effective
        )
        and len(localized_rows)
        == config.expected_local_failure_count * len(config.base_config.model_seeds)
        and not any(bool(row["accepted"]) for row in localized_rows)
        and expected_case_nonlocal_cascade == 0
        and closure_conflicts == 0
        and all(
            states.get("LEGAL") == config.expected_case_count - len(expected_failure_cases)
            and states.get("EXPECTED_FAIL") == len(expected_failure_cases)
            and states.get("FAIL", 0) == 0
            for states in states_by_seed.values()
        )
    )
    return {
        "all_segment_decision_count": len(all_segment_decisions),
        "effective_segment_count": len(effective_segments),
        "context_decision_count": len(context_decisions),
        "context_auto_accept_count": sum(
            bool(row["accepted"]) for row in context_decisions
        ),
        "context_effective_non_keep_count": sum(
            row.get("effective_target") != "KEEP_SWSD" for row in context_effective
        ),
        "localized_failure_decision_count": len(localized_rows),
        "localized_failure_auto_accept_count": sum(
            bool(row["accepted"]) for row in localized_rows
        ),
        "expected_case_nonlocal_cascade_count": expected_case_nonlocal_cascade,
        "closure_conflict_count": closure_conflicts,
        "roadgraph_states_by_seed": states_by_seed,
        "gate_pass": gate,
    }


def _payload_path(dataset: Mapping[str, Any]) -> Path:
    record = dict(
        (dataset["dataset_manifest"].get("outputs") or {}).get("payloads") or {}
    )
    return normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)


def _reference_match(
    reference_root_value: Path | None,
    determinism_signature: str,
) -> bool | None:
    if reference_root_value is None:
        return None
    root = normalize_runtime_path(reference_root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p2_manifest.json")
    return str(manifest.get("determinism_signature") or "") == determinism_signature


def _normalized_effective(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"output", "wall_seconds"}
    }


def _deterministic_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key != "performance"
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024


def _validation_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# P05-Scheme-A-P2-P3-P2 Validation",
        "",
        f"- decision: `{summary['decision']}`",
        f"- eligible/context: `{summary['eligible_segment_count']}/"
        f"{summary['context_segment_count']}`",
        f"- carrier gate: `{summary['carrier_gate_pass']}`",
        f"- clue gate: `{summary['clue_gate_pass']}`",
        f"- RoadGraph gate: `{summary['roadgraph_gate_pass']}`",
        f"- execution scope gate: `{summary['execution_scope_gate_pass']}`",
        f"- source/model/resource gate: `{summary['source_gate_pass']}` / "
        f"`{summary['model_contract_gate_pass']}` / "
        f"`{summary['resource_gate_pass']}`",
        f"- parameter count: `{summary['parameter_count_min']}–"
        f"{summary['parameter_count_max']}`",
        f"- determinism signature: `{summary['determinism_signature']}`",
        f"- reference match: `{summary['reference_run_match']}`",
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


__all__ = [
    "apply_localized_failure",
    "build_dataset_p1_context_fallback",
    "run_scheme_a_p2_p3_p2_oof",
]
