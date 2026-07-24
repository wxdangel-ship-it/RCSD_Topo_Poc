from __future__ import annotations

import hashlib
import json
import math
import resource
import time
from collections import Counter
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_oof import (
    _all_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_training import (
    train_hierarchical_fold,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_oof import (
    _execution_scope_audit,
    apply_localized_failure,
    build_dataset_p1_context_fallback,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p3_audit import (
    build_access_gate_ledger,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_models import (
    SchemeAP2P3P5Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_oof import (
    _access_audit,
    _load_segment_inventory,
    _materialize_replay,
    replay_advance_right_gate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_models import (
    SCHEME_A_P2_P3_P9_SCHEMA,
    SchemeAP2P3P9Config,
    choose_p9_decision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_source import (
    load_p9_inputs,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_training import (
    build_control_treatment_decisions,
    train_source_adapter_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_STABLE_GROUP_ID = (
    "SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080"
)


def run_scheme_a_p2_p3_p9_oof(config: SchemeAP2P3P9Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)

    examples, metadata, source_rows, field_contract = load_p9_inputs(config)
    source_applicable = {
        str(row["group_id"]): bool(row["source_applicable"])
        for row in source_rows
    }
    failure_group_ids = set(metadata["failure_group_ids"])
    promotion_fields = tuple(
        field_contract["promotion_candidate_fields"]
    )
    run_root.mkdir(parents=True)

    control_scores: list[dict[str, Any]] = []
    treatment_scores: list[dict[str, Any]] = []
    control_decisions: list[dict[str, Any]] = []
    treatment_decisions: list[dict[str, Any]] = []
    control_evaluations: list[dict[str, Any]] = []
    treatment_evaluations: list[dict[str, Any]] = []
    control_folds: list[dict[str, Any]] = []
    treatment_folds: list[dict[str, Any]] = []
    training_started = time.perf_counter()
    for seed in config.engine_config.base_config.model_seeds:
        for fold in range(
            config.engine_config.base_config.expected_fold_count
        ):
            control = train_hierarchical_fold(
                examples,
                config=config.engine_config.base_config,
                held_out_fold=fold,
                seed=seed,
                dataset_manifest_sha256=metadata["p9_lineage"][
                    "p9_input_signature"
                ],
            )
            adapter = train_source_adapter_fold(
                control,
                examples,
                source_rows,
                promotion_fields=promotion_fields,
                config=config,
                held_out_fold=fold,
                seed=seed,
            )
            control_record, treatment_record = _fold_records(
                control.training_summary,
                adapter.training_summary,
            )
            control_folds.append(control_record)
            treatment_folds.append(treatment_record)
            fold_control_decisions, fold_treatment_decisions = (
                build_control_treatment_decisions(
                    control_scores=control.held_out_scores,
                    treatment_scores=adapter.held_out_scores,
                    control=control,
                    adapter=adapter,
                    seed=seed,
                )
            )
            control_signature = str(
                control.training_summary["model_signature"]
            )
            treatment_signature = (
                f"{control_signature}+"
                f"{adapter.training_summary['adapter_model_signature']}"
            )
            for control_row, treatment_row in zip(
                control.held_out_scores,
                adapter.held_out_scores,
                strict=True,
            ):
                if control_row["group_id"] != treatment_row["group_id"]:
                    raise ValueError("Control/Treatment held-out order differs")
                applicable = source_applicable[str(control_row["group_id"])]
                control_scores.append(
                    _score_record(
                        control_row,
                        seed=seed,
                        model_signature=control_signature,
                        source_applicable=applicable,
                        arm="CONTROL",
                    )
                )
                treatment_scores.append(
                    _score_record(
                        treatment_row,
                        seed=seed,
                        model_signature=treatment_signature,
                        source_applicable=applicable,
                        arm="TREATMENT",
                    )
                )
                control_evaluations.append(
                    _evaluation_record(
                        control_row,
                        seed=seed,
                        source_applicable=applicable,
                        arm="CONTROL",
                    )
                )
                treatment_evaluations.append(
                    _evaluation_record(
                        treatment_row,
                        seed=seed,
                        source_applicable=applicable,
                        arm="TREATMENT",
                    )
                )
            control_decisions.extend(
                _decision_record(
                    apply_localized_failure(
                        row,
                        failure_group_ids=failure_group_ids,
                    ),
                    arm="CONTROL",
                )
                for row in fold_control_decisions
            )
            treatment_decisions.extend(
                _decision_record(
                    apply_localized_failure(
                        row,
                        failure_group_ids=failure_group_ids,
                    ),
                    arm="TREATMENT",
                )
                for row in fold_treatment_decisions
            )
            del adapter
            del control
    training_seconds = time.perf_counter() - training_started

    p5_config = _p5_compat_config(config)
    segment_inventory = _load_segment_inventory(p5_config)
    gate_ledger, segment_by_group = build_access_gate_ledger(
        examples,
        segment_inventory,
        expected_gate_count=config.expected_access_gate_count,
    )
    control_decisions, control_gate_changes = replay_advance_right_gate(
        control_decisions,
        segment_by_group,
    )
    treatment_decisions, treatment_gate_changes = replay_advance_right_gate(
        treatment_decisions,
        segment_by_group,
    )
    control_decisions = [
        _decision_record(row, arm="CONTROL")
        for row in control_decisions
    ]
    treatment_decisions = [
        _decision_record(row, arm="TREATMENT")
        for row in treatment_decisions
    ]
    context_control = [
        _decision_record(
            build_dataset_p1_context_fallback(example, seed=seed),
            arm="CONTROL",
            label_eligible=False,
        )
        for seed in config.engine_config.base_config.model_seeds
        for example in metadata["context_examples"]
    ]
    context_treatment = [
        _decision_record(
            build_dataset_p1_context_fallback(example, seed=seed),
            arm="TREATMENT",
            label_eligible=False,
        )
        for seed in config.engine_config.base_config.model_seeds
        for example in metadata["context_examples"]
    ]
    control_all = sorted(
        [*control_decisions, *context_control],
        key=_seed_group_key,
    )
    treatment_all = sorted(
        [*treatment_decisions, *context_treatment],
        key=_seed_group_key,
    )
    _validate_scopes(
        config,
        control_scores,
        treatment_scores,
        control_decisions,
        treatment_decisions,
        control_all,
        treatment_all,
    )

    control_roadgraphs, control_effective, control_closures = (
        _materialize_replay(
            p5_config,
            config.engine_config,
            run_root / "control_materialized",
            control_all,
            metadata,
        )
    )
    treatment_roadgraphs, treatment_effective, treatment_closures = (
        _materialize_replay(
            p5_config,
            config.engine_config,
            run_root / "treatment_materialized",
            treatment_all,
            metadata,
        )
    )
    eligible_ids = {example.group.group_id for example in examples}
    control_eligible_effective = _eligible_effective(
        control_effective, eligible_ids
    )
    treatment_eligible_effective = _eligible_effective(
        treatment_effective, eligible_ids
    )
    control_metrics = _all_metrics(
        examples,
        control_decisions,
        control_evaluations,
        control_eligible_effective,
        control_roadgraphs,
        control_closures,
        control_folds,
        metadata["eligible_clue_only_group_ids"],
        config.engine_config.base_config,
    )
    treatment_metrics = _all_metrics(
        examples,
        treatment_decisions,
        treatment_evaluations,
        treatment_eligible_effective,
        treatment_roadgraphs,
        treatment_closures,
        treatment_folds,
        metadata["eligible_clue_only_group_ids"],
        config.engine_config.base_config,
    )
    expected_failure_cases = set(metadata["failure_by_case"])
    control_execution = _execution_scope_audit(
        config.engine_config,
        all_segment_decisions=control_all,
        effective_rows=control_effective,
        scope_application_rows=metadata["scope_application_rows"],
        roadgraph_rows=control_roadgraphs,
        closure_rows=control_closures,
        failure_group_ids=failure_group_ids,
        expected_failure_cases=expected_failure_cases,
    )
    treatment_execution = _execution_scope_audit(
        config.engine_config,
        all_segment_decisions=treatment_all,
        effective_rows=treatment_effective,
        scope_application_rows=metadata["scope_application_rows"],
        roadgraph_rows=treatment_roadgraphs,
        closure_rows=treatment_closures,
        failure_group_ids=failure_group_ids,
        expected_failure_cases=expected_failure_cases,
    )
    control_access = _access_audit(
        p5_config,
        gate_ledger,
        control_gate_changes,
        control_decisions,
        examples,
    )
    treatment_access = _access_audit(
        p5_config,
        gate_ledger,
        treatment_gate_changes,
        treatment_decisions,
        examples,
    )
    comparison = _comparison_metrics(
        config,
        source_applicable,
        control_scores,
        treatment_scores,
        control_decisions,
        treatment_decisions,
        control_evaluations,
        treatment_evaluations,
        control_metrics,
        treatment_metrics,
    )

    parameter_gate = all(
        int(row["adapter_parameter_count"])
        <= config.adapter_max_parameter_count
        and int(row["total_parameter_count"])
        <= config.total_max_parameter_count
        for row in treatment_folds
    )
    source_gate = (
        len(examples) == config.expected_eligible_count
        and len(metadata["context_examples"]) == config.expected_context_count
        and len(source_rows) == config.expected_eligible_count
        and sum(source_applicable.values())
        == config.expected_source_applicable_count
        and len(promotion_fields) == config.expected_promotion_field_count
        and metadata["scope_audit"]["context_label_weight_count"] == 0
        and metadata["scope_audit"]["context_metric_eligible_count"] == 0
    )
    architecture_gate = (
        comparison["non_applicable_score_difference_count"] == 0
        and comparison["non_applicable_decision_difference_count"] == 0
        and comparison["clue_probability_difference_count"] == 0
        and parameter_gate
    )
    roadgraph_gate = (
        control_metrics["roadgraph_gate_pass"]
        and treatment_metrics["roadgraph_gate_pass"]
        and control_execution["gate_pass"]
        and treatment_execution["gate_pass"]
    )
    inference_p95 = float(
        treatment_metrics["performance"]["case_inference_p95_seconds"]
    )
    resource_metrics = {
        "wall_seconds": time.perf_counter() - started,
        "training_seconds": training_seconds,
        "peak_rss_bytes": _peak_rss_bytes(),
        "peak_rss_gib": _peak_rss_bytes() / (1024**3),
        "gpu_vram_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else 0
        ),
        "case_inference_p95_seconds": inference_p95,
        "case_inference_max_seconds": float(
            treatment_metrics["performance"][
                "case_inference_max_seconds"
            ]
        ),
    }
    resource_gate = (
        resource_metrics["wall_seconds"] <= 15 * 60
        and resource_metrics["peak_rss_bytes"] <= 8 * 1024**3
        and resource_metrics["gpu_vram_bytes"] == 0
        and resource_metrics["case_inference_p95_seconds"] <= 0.5
    )
    deterministic_components = {
        "lineage": metadata["p9_lineage"],
        "control_scores": _rows_signature(control_scores),
        "treatment_scores": _rows_signature(treatment_scores),
        "control_decisions": _rows_signature(
            control_decisions, excluded_keys={"model_signature"}
        ),
        "treatment_decisions": _rows_signature(
            treatment_decisions, excluded_keys={"model_signature"}
        ),
        "control_effective": _rows_signature(
            control_effective,
            excluded_keys={"output", "wall_seconds"},
        ),
        "treatment_effective": _rows_signature(
            treatment_effective,
            excluded_keys={"output", "wall_seconds"},
        ),
        "control_roadgraphs": _roadgraph_signature(control_roadgraphs),
        "treatment_roadgraphs": _roadgraph_signature(
            treatment_roadgraphs
        ),
        "control_folds": _fold_signature(control_folds),
        "treatment_folds": _fold_signature(treatment_folds),
        "comparison": comparison,
        "control_execution": control_execution,
        "treatment_execution": treatment_execution,
    }
    determinism_signature = canonical_sha256(
        deterministic_components
    )
    reference_match = _reference_match(
        config.reference_run_root,
        determinism_signature,
    )
    audit_gate = (
        source_gate
        and architecture_gate
        and roadgraph_gate
        and control_access["gate_pass"]
        and treatment_access["gate_pass"]
        and resource_gate
        and reference_match is not False
    )
    promotion_gate = bool(comparison["promotion_gate_pass"])
    full_carrier_gate = (
        promotion_gate and treatment_metrics["carrier_gate_pass"]
    )
    decision = choose_p9_decision(
        audit_gate=audit_gate,
        promotion_gate=promotion_gate,
        full_carrier_gate=full_carrier_gate,
    )

    paths = {
        "source_contract": run_root / "source_contract.json",
        "gate_ledger": run_root / "advance_right_access_gate_ledger.jsonl",
        "control_scores": run_root / "control_scores.jsonl",
        "treatment_scores": run_root / "treatment_scores.jsonl",
        "control_decisions": run_root / "control_eligible_decisions.jsonl",
        "treatment_decisions": run_root / "treatment_eligible_decisions.jsonl",
        "control_evaluation": run_root / "control_evaluation.jsonl",
        "treatment_evaluation": run_root / "treatment_evaluation.jsonl",
        "control_all": run_root / "control_all_segment_decisions.jsonl",
        "treatment_all": run_root / "treatment_all_segment_decisions.jsonl",
        "control_effective": run_root / "control_effective.jsonl",
        "treatment_effective": run_root / "treatment_effective.jsonl",
        "control_roadgraphs": run_root / "control_roadgraphs.jsonl",
        "treatment_roadgraphs": run_root / "treatment_roadgraphs.jsonl",
        "control_closure": run_root / "control_closure.jsonl",
        "treatment_closure": run_root / "treatment_closure.jsonl",
        "folds": run_root / "fold_index.json",
        "metrics": run_root / "metrics.json",
        "feature_audit": run_root / "feature_audit.json",
        "summary": run_root / "scheme_a_p2_p3_p9_summary.json",
        "report": run_root / "validation_report.md",
    }
    write_json(
        paths["source_contract"],
        {
            "promotion_fields": list(promotion_fields),
            "field_contract": field_contract,
            "lineage": metadata["p9_lineage"],
        },
    )
    _write_jsonl(paths["gate_ledger"], gate_ledger)
    _write_jsonl(paths["control_scores"], sorted(control_scores, key=_seed_group_key))
    _write_jsonl(
        paths["treatment_scores"],
        sorted(treatment_scores, key=_seed_group_key),
    )
    _write_jsonl(
        paths["control_decisions"],
        sorted(control_decisions, key=_seed_group_key),
    )
    _write_jsonl(
        paths["treatment_decisions"],
        sorted(treatment_decisions, key=_seed_group_key),
    )
    _write_jsonl(
        paths["control_evaluation"],
        sorted(control_evaluations, key=_seed_group_key),
    )
    _write_jsonl(
        paths["treatment_evaluation"],
        sorted(treatment_evaluations, key=_seed_group_key),
    )
    _write_jsonl(paths["control_all"], control_all)
    _write_jsonl(paths["treatment_all"], treatment_all)
    _write_jsonl(
        paths["control_effective"],
        sorted(control_effective, key=_seed_group_key),
    )
    _write_jsonl(
        paths["treatment_effective"],
        sorted(treatment_effective, key=_seed_group_key),
    )
    _write_jsonl(
        paths["control_roadgraphs"],
        sorted(control_roadgraphs, key=_seed_case_key),
    )
    _write_jsonl(
        paths["treatment_roadgraphs"],
        sorted(treatment_roadgraphs, key=_seed_case_key),
    )
    _write_jsonl(
        paths["control_closure"],
        sorted(control_closures, key=lambda row: int(row["seed"])),
    )
    _write_jsonl(
        paths["treatment_closure"],
        sorted(treatment_closures, key=lambda row: int(row["seed"])),
    )
    write_json(
        paths["folds"],
        {"control": control_folds, "treatment": treatment_folds},
    )
    metrics = {
        "comparison": comparison,
        "control": control_metrics,
        "treatment": treatment_metrics,
        "control_execution": control_execution,
        "treatment_execution": treatment_execution,
        "control_access": control_access,
        "treatment_access": treatment_access,
    }
    write_json(paths["metrics"], metrics)
    feature_audit = {
        "control_feature_count": config.expected_feature_count,
        "control_t03_t04_feature_count": 0,
        "treatment_source_field_count": len(promotion_fields),
        "source_applicable_count": sum(source_applicable.values()),
        "source_not_applicable_count": sum(
            not value for value in source_applicable.values()
        ),
        "clue_source_feature_count": 0,
        "clue_source_loss_count": 0,
        "clue_source_decision_count": 0,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "path_feature_count": 0,
        "free_text_feature_count": 0,
        "review_feature_count": 0,
        "t05_t06_feature_count": 0,
        "movement_feature_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "source_gate_pass": source_gate,
        "architecture_gate_pass": architecture_gate,
        "parameter_gate_pass": parameter_gate,
    }
    write_json(paths["feature_audit"], feature_audit)
    summary = {
        "schema_version": SCHEME_A_P2_P3_P9_SCHEMA,
        "decision": decision,
        "audit_gate_pass": audit_gate,
        "promotion_gate_pass": promotion_gate,
        "full_carrier_gate_pass": full_carrier_gate,
        "source_gate_pass": source_gate,
        "architecture_gate_pass": architecture_gate,
        "roadgraph_gate_pass": roadgraph_gate,
        "resource_gate_pass": resource_gate,
        "reference_run_match": reference_match,
        "determinism_signature": determinism_signature,
        "comparison": comparison,
        "control_metrics": control_metrics,
        "treatment_metrics": treatment_metrics,
        "control_execution": control_execution,
        "treatment_execution": treatment_execution,
        "resource": resource_metrics,
        "lineage": metadata["p9_lineage"],
        "model_training_count": 15,
        "adapter_training_count": 15,
        "old_model_state_reused": False,
        "control_threshold_reused_by_treatment": True,
        "clue_source_feature_count": 0,
        "clue_source_loss_count": 0,
        "clue_source_decision_count": 0,
        "movement_decision_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
        "skeleton_mutation_count": 0,
        "repair_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(
        _validation_report(summary), encoding="utf-8"
    )
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p9_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P9_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "carrier_only_source_adapter_oof_completed",
            "decision": decision,
            "determinism_signature": determinism_signature,
            "reference_run_match": reference_match,
            "lineage": metadata["p9_lineage"],
            "parameters": {
                "model_seeds": list(
                    config.engine_config.base_config.model_seeds
                ),
                "fold_count": 5,
                "control_feature_count": config.expected_feature_count,
                "source_field_count": len(promotion_fields),
                "source_applicable_count": sum(source_applicable.values()),
                "device": "cpu",
            },
            "outputs": outputs,
            "clue_source_feature_count": 0,
            "clue_source_loss_count": 0,
            "clue_source_decision_count": 0,
            "movement_feature_count": 0,
            "geometry_write_count": 0,
            "coordinate_transform_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p9-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _p5_compat_config(
    config: SchemeAP2P3P9Config,
) -> SchemeAP2P3P5Config:
    return SchemeAP2P3P5Config(
        base_config=config.engine_config.base_config,
        dataset_p1_root=config.engine_config.dataset_p1_root,
        scope_first_dataset_root=(
            config.engine_config.base_config.dataset_run_root
        ),
        scheme_a_baseline_root=config.scheme_a_baseline_root,
        output_root=config.output_root,
        engine_output_root=config.output_root,
        run_id=f"{config.run_id}-p5-compat",
        engine_run_id=f"{config.run_id}-engine-compat",
    )


def _fold_records(
    control: Mapping[str, Any],
    adapter: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    control_record = dict(control)
    control_record["arm"] = "CONTROL"
    treatment_record = {
        **dict(control),
        **dict(adapter),
        "arm": "TREATMENT",
        "wall_seconds": float(control["wall_seconds"])
        + float(adapter["wall_seconds"]),
        "case_inference_latencies": [
            {
                **dict(row),
                "seconds": float(row["seconds"])
                + float(adapter["inference_seconds"]),
            }
            for row in control["case_inference_latencies"]
        ],
    }
    return control_record, treatment_record


def _score_record(
    row: Mapping[str, Any],
    *,
    seed: int,
    model_signature: str,
    source_applicable: bool,
    arm: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEME_A_P2_P3_P9_SCHEMA,
        **dict(row),
        "seed": seed,
        "model_signature": model_signature,
        "source_applicable": source_applicable,
        "arm": arm,
        "feature_uses_truth": False,
        "movement_used": False,
        "clue_source_used": False,
    }


def _evaluation_record(
    row: Mapping[str, Any],
    *,
    seed: int,
    source_applicable: bool,
    arm: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEME_A_P2_P3_P9_SCHEMA,
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
        "source_applicable": source_applicable,
        "arm": arm,
        "label_eligible": True,
        "label_only": True,
    }


def _decision_record(
    row: Mapping[str, Any],
    *,
    arm: str,
    label_eligible: bool = True,
) -> dict[str, Any]:
    result = dict(row)
    result.update(
        {
            "schema_version": SCHEME_A_P2_P3_P9_SCHEMA,
            "arm": arm,
            "label_eligible": label_eligible,
        }
    )
    return result


def _comparison_metrics(
    config: SchemeAP2P3P9Config,
    source_applicable: Mapping[str, bool],
    control_scores: Sequence[Mapping[str, Any]],
    treatment_scores: Sequence[Mapping[str, Any]],
    control_decisions: Sequence[Mapping[str, Any]],
    treatment_decisions: Sequence[Mapping[str, Any]],
    control_evaluations: Sequence[Mapping[str, Any]],
    treatment_evaluations: Sequence[Mapping[str, Any]],
    control_metrics: Mapping[str, Any],
    treatment_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    control_score_by_key = {
        _seed_group_key(row): row for row in control_scores
    }
    treatment_score_by_key = {
        _seed_group_key(row): row for row in treatment_scores
    }
    control_decision_by_key = {
        _seed_group_key(row): row for row in control_decisions
    }
    treatment_decision_by_key = {
        _seed_group_key(row): row for row in treatment_decisions
    }
    non_applicable_score_differences = 0
    clue_differences = 0
    for key, control in control_score_by_key.items():
        treatment = treatment_score_by_key[key]
        group_id = key[1]
        clue_differences += int(
            control["clue_probability"]
            != treatment["clue_probability"]
        )
        if not source_applicable[group_id]:
            non_applicable_score_differences += int(
                any(
                    control[field] != treatment[field]
                    for field in (
                        "candidate_scores",
                        "candidate_probabilities",
                        "candidate_utilities",
                        "selected_candidate_id",
                        "selected_target",
                        "carrier_confidence",
                        "clue_probability",
                        "auxiliary_probabilities",
                    )
                )
            )
    non_applicable_decision_differences = 0
    for key, control in control_decision_by_key.items():
        if source_applicable[key[1]]:
            continue
        treatment = treatment_decision_by_key[key]
        non_applicable_decision_differences += int(
            any(
                control[field] != treatment[field]
                for field in (
                    "proposal_candidate_id",
                    "proposal_target",
                    "accepted",
                    "risk",
                    "safety_probability",
                    "anomaly_probability",
                    "clue_predicted",
                    "carrier_threshold",
                    "clue_threshold",
                    "reason",
                )
            )
        )

    control_eval_by_key = {
        _seed_group_key(row): row for row in control_evaluations
    }
    treatment_eval_by_key = {
        _seed_group_key(row): row for row in treatment_evaluations
    }
    control_seed_scope = {
        int(row["seed"]): row
        for row in control_metrics["scope_metrics"]
        if row["scope"] == "SEED"
    }
    treatment_seed_scope = {
        int(row["seed"]): row
        for row in treatment_metrics["scope_metrics"]
        if row["scope"] == "SEED"
    }
    seed_rows: list[dict[str, Any]] = []
    pooled_control: list[Mapping[str, Any]] = []
    pooled_treatment: list[Mapping[str, Any]] = []
    for seed in config.engine_config.base_config.model_seeds:
        keys = [
            key
            for key in control_eval_by_key
            if key[0] == seed and source_applicable[key[1]]
        ]
        control_app = [control_eval_by_key[key] for key in keys]
        treatment_app = [treatment_eval_by_key[key] for key in keys]
        pooled_control.extend(control_app)
        pooled_treatment.extend(treatment_app)
        control_class = _classification_metrics(control_app)
        treatment_class = _classification_metrics(treatment_app)
        wrong_accepted, review_auto, safety_recall = _decision_safety(
            seed,
            treatment_eval_by_key,
            treatment_decision_by_key,
        )
        stable = treatment_eval_by_key[(seed, _STABLE_GROUP_ID)]
        control_scope = control_seed_scope[seed]
        treatment_scope = treatment_seed_scope[seed]
        safe_delta = float(treatment_scope["safe_coverage"]) - float(
            control_scope["safe_coverage"]
        )
        use_delta = float(
            treatment_scope["use_rcsd_safe_coverage"]
        ) - float(control_scope["use_rcsd_safe_coverage"])
        gate = (
            wrong_accepted == 0
            and review_auto == 0
            and safety_recall == 1.0
            and stable["selected_target"] == "KEEP_SWSD"
            and treatment_class["macro_f1"]
            >= control_class["macro_f1"]
            and treatment_class["keep_recall"]
            >= control_class["keep_recall"]
            and safe_delta >= -0.01
            and use_delta >= -0.01
        )
        seed_rows.append(
            {
                "seed": seed,
                "source_applicable_count": len(keys),
                "control_macro_f1": control_class["macro_f1"],
                "treatment_macro_f1": treatment_class["macro_f1"],
                "control_keep_recall": control_class["keep_recall"],
                "treatment_keep_recall": treatment_class["keep_recall"],
                "scorer_carrier_wrong_accepted_count": wrong_accepted,
                "review_auto_publish_count": review_auto,
                "carrier_safety_recall": safety_recall,
                "stable_selected_target": stable["selected_target"],
                "safe_coverage_delta": safe_delta,
                "use_rcsd_safe_coverage_delta": use_delta,
                "gate_pass": gate,
            }
        )
    pooled_control_metrics = _classification_metrics(pooled_control)
    pooled_treatment_metrics = _classification_metrics(pooled_treatment)
    strict_gain = (
        pooled_treatment_metrics["macro_f1"]
        > pooled_control_metrics["macro_f1"] + 1e-12
        or pooled_treatment_metrics["keep_recall"]
        > pooled_control_metrics["keep_recall"] + 1e-12
    )
    promotion_gate = (
        all(row["gate_pass"] for row in seed_rows)
        and strict_gain
        and non_applicable_score_differences == 0
        and non_applicable_decision_differences == 0
    )
    return {
        "seed_metrics": seed_rows,
        "pooled_control": pooled_control_metrics,
        "pooled_treatment": pooled_treatment_metrics,
        "pooled_strict_gain": strict_gain,
        "non_applicable_score_difference_count": (
            non_applicable_score_differences
        ),
        "non_applicable_decision_difference_count": (
            non_applicable_decision_differences
        ),
        "clue_probability_difference_count": clue_differences,
        "promotion_gate_pass": promotion_gate,
    }


def _classification_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    classes = ("KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD")
    f1_values: list[float] = []
    keep_true = 0
    keep_correct = 0
    for label in classes:
        true_positive = sum(
            row["truth_target"] == label
            and row["selected_target"] == label
            for row in rows
        )
        false_positive = sum(
            row["truth_target"] != label
            and row["selected_target"] == label
            for row in rows
        )
        false_negative = sum(
            row["truth_target"] == label
            and row["selected_target"] != label
            for row in rows
        )
        denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append(
            1.0 if denominator == 0 else 2 * true_positive / denominator
        )
        if label == "KEEP_SWSD":
            keep_true = true_positive + false_negative
            keep_correct = true_positive
    return {
        "macro_f1": sum(f1_values) / len(f1_values),
        "keep_recall": keep_correct / max(1, keep_true),
    }


def _decision_safety(
    seed: int,
    evaluation_by_key: Mapping[tuple[int, str], Mapping[str, Any]],
    decision_by_key: Mapping[tuple[int, str], Mapping[str, Any]],
) -> tuple[int, int, float]:
    keys = [key for key in evaluation_by_key if key[0] == seed]
    wrong_accepted = 0
    review_auto = 0
    unsafe = 0
    for key in keys:
        evaluation = evaluation_by_key[key]
        decision = decision_by_key[key]
        wrong = (
            evaluation["selected_candidate_id"]
            != evaluation["truth_candidate_id"]
        )
        review = evaluation["truth_target"] == "REVIEW_FALLBACK"
        unsafe += int(wrong or review)
        wrong_accepted += int(bool(decision["accepted"]) and wrong)
        review_auto += int(bool(decision["accepted"]) and review)
    recall = 1.0 - (wrong_accepted + review_auto) / max(1, unsafe)
    return wrong_accepted, review_auto, recall


def _validate_scopes(
    config: SchemeAP2P3P9Config,
    control_scores: Sequence[Mapping[str, Any]],
    treatment_scores: Sequence[Mapping[str, Any]],
    control_decisions: Sequence[Mapping[str, Any]],
    treatment_decisions: Sequence[Mapping[str, Any]],
    control_all: Sequence[Mapping[str, Any]],
    treatment_all: Sequence[Mapping[str, Any]],
) -> None:
    seed_count = len(config.engine_config.base_config.model_seeds)
    eligible = config.expected_eligible_count * seed_count
    all_count = (
        config.expected_eligible_count + config.expected_context_count
    ) * seed_count
    if any(
        len(rows) != eligible
        for rows in (
            control_scores,
            treatment_scores,
            control_decisions,
            treatment_decisions,
        )
    ):
        raise ValueError("P9 eligible A/B denominator differs")
    if len(control_all) != all_count or len(treatment_all) != all_count:
        raise ValueError("P9 all-Segment A/B denominator differs")


def _eligible_effective(
    rows: Sequence[Mapping[str, Any]],
    eligible_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if row.get("object_type") == "SEGMENT"
        and str(row["group_id"]) in eligible_ids
    ]


def _rows_signature(
    rows: Sequence[Mapping[str, Any]],
    *,
    excluded_keys: set[str] | None = None,
) -> str:
    excluded = excluded_keys or set()
    digest = hashlib.sha256()
    for row in sorted(rows, key=_seed_group_key):
        normalized = {
            key: value for key, value in row.items() if key not in excluded
        }
        digest.update(
            json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _roadgraph_signature(
    rows: Sequence[Mapping[str, Any]],
) -> str:
    normalized = [
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
        for row in sorted(rows, key=_seed_case_key)
    ]
    return canonical_sha256(normalized)


def _fold_signature(rows: Sequence[Mapping[str, Any]]) -> str:
    stable_keys = {
        "seed",
        "held_out_fold",
        "best_epoch",
        "best_inner_loss",
        "parameter_count",
        "model_signature",
        "carrier_threshold",
        "clue_threshold",
        "adapter_parameter_count",
        "total_parameter_count",
        "adapter_model_signature",
        "source_transform_signature",
    }
    normalized = [
        {key: row[key] for key in sorted(stable_keys) if key in row}
        for row in sorted(
            rows,
            key=lambda row: (
                int(row["seed"]),
                int(row["held_out_fold"]),
            ),
        )
    ]
    return canonical_sha256(normalized)


def _reference_match(
    root_value: Path | None,
    signature: str,
) -> bool | None:
    if root_value is None:
        return None
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest = json.loads(
        (root / "scheme_a_p2_p3_p9_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return str(manifest.get("determinism_signature") or "") == signature


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _validation_report(summary: Mapping[str, Any]) -> str:
    comparison = summary["comparison"]
    return (
        "# P05-Scheme-A-P2-P3-P9 Validation\n\n"
        f"- decision: `{summary['decision']}`\n"
        f"- audit/promotion/full carrier: "
        f"`{summary['audit_gate_pass']}` / "
        f"`{summary['promotion_gate_pass']}` / "
        f"`{summary['full_carrier_gate_pass']}`\n"
        f"- non-app score/decision differences: "
        f"`{comparison['non_applicable_score_difference_count']}` / "
        f"`{comparison['non_applicable_decision_difference_count']}`\n"
        f"- pooled strict gain: `{comparison['pooled_strict_gain']}`\n"
        f"- RoadGraph/resource: `{summary['roadgraph_gate_pass']}` / "
        f"`{summary['resource_gate_pass']}`\n"
        f"- determinism signature: `{summary['determinism_signature']}`\n"
        f"- reference match: `{summary['reference_run_match']}`\n"
    )


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _seed_case_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["case_key"])


def _write_jsonl(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = ["run_scheme_a_p2_p3_p9_oof"]
