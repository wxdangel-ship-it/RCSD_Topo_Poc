from __future__ import annotations

import csv
import json
import resource
import time
from collections import Counter
from dataclasses import replace
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_dataset import (
    load_dataset_p1_hierarchical_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_models import (
    DECISION_AUDIT_NO_GO as ENGINE_AUDIT_NO_GO,
    SchemeAP2P3P2Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_oof import (
    _execution_scope_audit,
    run_scheme_a_p2_p3_p2_oof,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p3_audit import (
    apply_advance_right_access_gate,
    build_access_gate_ledger,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_DATASET_GO,
    DECISION_MODEL_GO,
    DECISION_MODEL_NO_GO,
    SCHEME_A_P2_P3_P5_SCHEMA,
    SchemeAP2P3P5Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p3_p5_oof(config: SchemeAP2P3P5Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)

    dataset_root, dataset_manifest = _load_dataset(config)
    engine_config = _engine_config(config, dataset_root)
    engine_root = run_scheme_a_p2_p3_p2_oof(engine_config)
    engine = _load_engine(engine_root, config.strict_hashes)
    if engine["manifest"].get("decision") == ENGINE_AUDIT_NO_GO:
        raise ValueError("P2-P3-P5 training engine audit did not pass")

    examples, metadata = load_dataset_p1_hierarchical_examples(engine_config)
    segment_inventory = _load_segment_inventory(config)
    gate_ledger, segment_by_group = build_access_gate_ledger(
        examples,
        segment_inventory,
        expected_gate_count=config.expected_access_gate_count,
    )
    original_eligible = list(
        _read_jsonl(engine["paths"]["eligible_decisions"])
    )
    replayed_eligible, gate_decisions = replay_advance_right_gate(
        original_eligible,
        segment_by_group,
    )
    original_all = list(
        _read_jsonl(engine["paths"]["all_segment_decisions"])
    )
    replay_by_key = {
        (int(row["seed"]), str(row["group_id"])): row
        for row in replayed_eligible
    }
    replayed_all = [
        _stage_row(
            replay_by_key.get(
                (int(row["seed"]), str(row["group_id"])),
                row,
            )
        )
        for row in original_all
    ]
    replayed_eligible = [_stage_row(row) for row in replayed_eligible]
    gate_decisions = [_stage_row(row) for row in gate_decisions]
    _validate_replay_scope(
        config,
        original_eligible,
        replayed_eligible,
        replayed_all,
        gate_decisions,
    )

    run_root.mkdir(parents=True)
    roadgraphs, effective, closures = _materialize_replay(
        config,
        engine_config,
        run_root,
        replayed_all,
        metadata,
    )
    evaluation_rows = list(_read_jsonl(engine["paths"]["evaluation"]))
    fold_records = list(_read_json(engine["paths"]["folds"]).get("folds") or [])
    eligible_ids = {example.group.group_id for example in examples}
    eligible_effective = [
        row
        for row in effective
        if row.get("object_type") == "SEGMENT"
        and str(row["group_id"]) in eligible_ids
    ]
    metrics = _all_metrics(
        examples,
        replayed_eligible,
        evaluation_rows,
        eligible_effective,
        roadgraphs,
        closures,
        fold_records,
        metadata["eligible_clue_only_group_ids"],
        engine_config.base_config,
    )
    failure_group_ids = set(metadata["failure_group_ids"])
    expected_failure_cases = set(metadata["failure_by_case"])
    execution_audit = _execution_scope_audit(
        engine_config,
        all_segment_decisions=replayed_all,
        effective_rows=effective,
        scope_application_rows=metadata["scope_application_rows"],
        roadgraph_rows=roadgraphs,
        closure_rows=closures,
        failure_group_ids=failure_group_ids,
        expected_failure_cases=expected_failure_cases,
    )
    access_audit = _access_audit(
        config,
        gate_ledger,
        gate_decisions,
        replayed_eligible,
        examples,
    )
    source_lineage = {
        "scope_first_dataset_manifest_sha256": sha256_file(
            dataset_root / "scheme_a_p2_p3_p5_dataset_manifest.json"
        ),
        "scope_first_loader_manifest_sha256": sha256_file(
            dataset_root / "scheme_a_p2_p1_dataset_manifest.json"
        ),
        "engine_determinism_signature": str(
            engine["manifest"]["determinism_signature"]
        ),
        "baseline_segment_inventory_sha256": sha256_file(
            segment_inventory["_path"]
        ),
    }
    source_gate = (
        dataset_manifest.get("decision") == DECISION_DATASET_GO
        and bool(engine["summary"]["source_gate_pass"])
        and bool(engine["summary"]["model_contract_gate_pass"])
        and bool(engine["summary"]["resource_gate_pass"])
        and bool(engine["summary"]["execution_scope_gate_pass"])
        and engine["manifest"].get("reference_run_match") is not False
        and access_audit["gate_pass"]
    )
    resource_metrics = {
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": _peak_rss_bytes(),
        "peak_rss_gib": _peak_rss_bytes() / (1024**3),
        "gpu_vram_bytes": int(
            engine["summary"]["resource"]["gpu_vram_bytes"]
        ),
        **metrics["performance"],
    }
    resource_gate = (
        resource_metrics["wall_seconds"] <= 30 * 60
        and resource_metrics["peak_rss_bytes"] <= 8 * 1024**3
        and resource_metrics["gpu_vram_bytes"] == 0
        and resource_metrics["case_inference_p95_seconds"] <= 5.0
        and resource_metrics["case_inference_max_seconds"] <= 20.0
    )
    deterministic_payload = {
        "source_lineage": source_lineage,
        "gate_ledger": gate_ledger,
        "gate_decisions": gate_decisions,
        "eligible_decisions": replayed_eligible,
        "effective": [
            _normalized_effective(row)
            for row in sorted(effective, key=_seed_group_key)
        ],
        "roadgraphs": [
            _normalized_roadgraph(row)
            for row in sorted(
                roadgraphs,
                key=lambda value: (
                    int(value["seed"]),
                    str(value["case_key"]),
                ),
            )
        ],
        "closures": closures,
        "metrics": _deterministic_metrics(metrics),
        "execution_audit": execution_audit,
        "access_audit": access_audit,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    audit_gate = (
        source_gate
        and execution_audit["gate_pass"]
        and resource_gate
        and reference_match is not False
    )
    model_gate = (
        metrics["carrier_gate_pass"]
        and metrics["clue_gate_pass"]
        and metrics["roadgraph_gate_pass"]
    )
    decision = choose_p5_decision(audit_gate, model_gate)

    paths = {
        "gate_ledger": run_root / "advance_right_access_gate_ledger.jsonl",
        "gate_decisions": run_root / "advance_right_gate_decisions.jsonl",
        "scope_application": run_root / "dataset_p1_scope_application.jsonl",
        "eligible_decisions": run_root / "eligible_decisions.jsonl",
        "all_segment_decisions": run_root / "all_segment_decisions.jsonl",
        "effective": run_root / "effective_selections.jsonl",
        "roadgraphs": run_root / "roadgraph_index.jsonl",
        "closure": run_root / "junction_closure.jsonl",
        "metrics": run_root / "metrics.json",
        "feature_audit": run_root / "feature_audit.json",
        "summary": run_root / "scheme_a_p2_p3_p5_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["gate_ledger"], gate_ledger)
    _write_jsonl(paths["gate_decisions"], gate_decisions)
    _write_jsonl(paths["scope_application"], metadata["scope_application_rows"])
    _write_jsonl(paths["eligible_decisions"], replayed_eligible)
    _write_jsonl(paths["all_segment_decisions"], replayed_all)
    _write_jsonl(paths["effective"], sorted(effective, key=_seed_group_key))
    _write_jsonl(
        paths["roadgraphs"],
        sorted(
            roadgraphs,
            key=lambda row: (int(row["seed"]), str(row["case_key"])),
        ),
    )
    _write_jsonl(
        paths["closure"],
        sorted(closures, key=lambda row: int(row["seed"])),
    )
    write_json(paths["metrics"], metrics)
    feature_audit = {
        **engine["feature_audit"],
        "scope_first_truth": True,
        "scope_first_dataset_decision": dataset_manifest["decision"],
        "advance_right_gate_count": config.expected_access_gate_count,
        "context_supervision_count": 0,
        "context_threshold_count": 0,
        "context_metric_count": 0,
        "truth_inference_feature_count": 0,
        "t06_inference_feature_count": 0,
        "movement_decision_count": 0,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "skeleton_mutation_count": 0,
    }
    write_json(paths["feature_audit"], feature_audit)
    summary = {
        "schema_version": SCHEME_A_P2_P3_P5_SCHEMA,
        "decision": decision,
        "audit_gate_pass": audit_gate,
        "model_gate_pass": model_gate,
        "source_gate_pass": source_gate,
        "access_gate_pass": access_audit["gate_pass"],
        "execution_scope_gate_pass": execution_audit["gate_pass"],
        "resource_gate_pass": resource_gate,
        "carrier_gate_pass": metrics["carrier_gate_pass"],
        "clue_gate_pass": metrics["clue_gate_pass"],
        "roadgraph_gate_pass": metrics["roadgraph_gate_pass"],
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "engine_run_root": str(engine_root.resolve()),
        "engine_decision": engine["manifest"]["decision"],
        "engine_reference_run_match": engine["manifest"].get(
            "reference_run_match"
        ),
        "scope_audit": metadata["scope_audit"],
        "access_audit": access_audit,
        "execution_scope_audit": execution_audit,
        "metrics": metrics,
        "resource": resource_metrics,
        "lineage": source_lineage,
        "model_training_count": len(config.base_config.model_seeds)
        * config.base_config.expected_fold_count,
        "old_model_state_reused": False,
        "old_threshold_reused": False,
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
    outputs.update(
        {
            "scores": output_record(engine["paths"]["scores"]),
            "evaluation": output_record(engine["paths"]["evaluation"]),
            "folds": output_record(engine["paths"]["folds"]),
            "training_engine_manifest": output_record(
                engine_root / "scheme_a_p2_p3_p2_manifest.json"
            ),
        }
    )
    manifest_path = run_root / "scheme_a_p2_p3_p5_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P5_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "scope_first_oof_completed",
            "decision": decision,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source_lineage,
            "parameters": {
                "model_seeds": list(config.base_config.model_seeds),
                "fold_count": config.base_config.expected_fold_count,
                "eligible_segment_count": config.expected_eligible_count,
                "context_segment_count": config.expected_context_count,
                "network_schema": "p05-scheme-a-p2-p3-p0-network-v1",
                "evidence_dim": config.base_config.expected_evidence_dim,
                "device": config.base_config.device,
                "advance_right_hard_gate": True,
                "scope_first_truth": True,
            },
            "outputs": outputs,
            "context_supervision_count": 0,
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
            "schema_version": "p05-scheme-a-p2-p3-p5-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def replay_advance_right_gate(
    decisions: Sequence[Mapping[str, Any]],
    segment_by_group: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    replayed: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for row in decisions:
        group_id = str(row["group_id"])
        segment = segment_by_group.get(group_id)
        if segment is None:
            raise ValueError(f"decision Segment inventory is missing: {group_id}")
        result = apply_advance_right_access_gate(row, segment)
        result_row = dict(result)
        replayed.append(result_row)
        if result_row != dict(row):
            changes.append(
                {
                    "seed": int(row["seed"]),
                    "case_key": str(row["case_key"]),
                    "group_id": group_id,
                    "object_id": str(row["object_id"]),
                    "before_accepted": bool(row["accepted"]),
                    "before_reason": str(row["reason"]),
                    "after_accepted": bool(result_row["accepted"]),
                    "after_reason": str(result_row["reason"]),
                    "access_valid": False,
                    "segment_type": "ADVANCE_RIGHT",
                }
            )
    return replayed, changes


def choose_p5_decision(audit_gate: bool, model_gate: bool) -> str:
    if not audit_gate:
        return DECISION_AUDIT_NO_GO
    return DECISION_MODEL_GO if model_gate else DECISION_MODEL_NO_GO


def _engine_config(
    config: SchemeAP2P3P5Config,
    dataset_root: Path,
) -> SchemeAP2P3P2Config:
    base = replace(config.base_config, dataset_run_root=dataset_root)
    return SchemeAP2P3P2Config(
        base_config=base,
        dataset_p1_root=config.dataset_p1_root,
        output_root=config.engine_output_root,
        run_id=config.engine_run_id,
        reference_run_root=config.reference_engine_root,
        expected_all_segment_count=config.expected_all_segment_count,
        expected_eligible_count=config.expected_eligible_count,
        expected_context_count=config.expected_context_count,
        expected_case_count=config.expected_case_count,
        expected_review_count=config.expected_review_count,
        expected_anomaly_count=config.expected_anomaly_count,
        expected_clue_only_eligible_count=(
            config.expected_clue_only_eligible_count
        ),
        expected_local_failure_count=config.expected_local_failure_count,
        expected_target_counts=config.expected_target_counts,
        expected_fold_eligible_counts=config.expected_fold_eligible_counts,
    )


def _materialize_replay(
    config: SchemeAP2P3P5Config,
    engine_config: SchemeAP2P3P2Config,
    run_root: Path,
    decisions: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset = metadata["dataset"]
    payload_path = normalize_runtime_path(
        str(dataset["dataset_manifest"]["outputs"]["payloads"]["path"])
    ).resolve(strict=True)
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    node_scores = _base_node_scores(
        engine_config.base_config.base_oof_run_a,
        engine_config.base_config.base_seeds,
    )
    expected_failure_cases = set(metadata["failure_by_case"])
    expected_failure_manifest = {
        case_key: frozenset(info["failures"])
        for case_key, info in metadata["failure_by_case"].items()
    }
    all_groups = list(metadata["all_groups"])
    roadgraphs: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    closures: list[dict[str, Any]] = []
    for seed in config.base_config.model_seeds:
        seed_decisions = [
            row for row in decisions if int(row["seed"]) == seed
        ]
        selections, closure = build_joint_safety_selections(
            all_groups,
            seed_decisions,
            compatibility_edges=dataset["compatibility_edges"],
            labels=dataset["labels"],
            node_scores=node_scores,
            expected_failure_cases=expected_failure_cases,
            seed=seed,
        )
        records, rows = materialize_p2_p1_seed(
            run_root,
            seed=seed,
            selections=selections,
            payloads_by_id=payloads_by_id,
            payloads_by_group=payloads_by_group,
            expected_failure_manifest=expected_failure_manifest,
        )
        roadgraphs.extend({"seed": seed, **row} for row in records)
        effective.extend(rows)
        closures.append(closure)
    return roadgraphs, effective, closures


def _load_dataset(
    config: SchemeAP2P3P5Config,
) -> tuple[Path, dict[str, Any]]:
    root = normalize_runtime_path(config.scope_first_dataset_root).resolve(
        strict=True
    )
    manifest = _read_json(root / "scheme_a_p2_p3_p5_dataset_manifest.json")
    if manifest.get("decision") != DECISION_DATASET_GO:
        raise ValueError("P2-P3-P5 dataset decision differs")
    loader = _read_json(root / "scheme_a_p2_p1_dataset_manifest.json")
    if loader.get("status") != "dataset_passed":
        raise ValueError("scope-first loader dataset status differs")
    return root, manifest


def _load_engine(root: Path, strict_hashes: bool) -> dict[str, Any]:
    manifest_path = root / "scheme_a_p2_p3_p2_manifest.json"
    manifest = _read_json(manifest_path)
    outputs = dict(manifest.get("outputs") or {})
    keys = (
        "scores",
        "eligible_decisions",
        "evaluation",
        "all_segment_decisions",
        "folds",
    )
    paths = {
        key: _verified_output(outputs, key, strict_hashes) for key in keys
    }
    return {
        "manifest": manifest,
        "summary": _read_json(
            _verified_output(outputs, "summary", strict_hashes)
        ),
        "feature_audit": _read_json(
            _verified_output(outputs, "feature_audit", strict_hashes)
        ),
        "paths": paths,
    }


def _load_segment_inventory(
    config: SchemeAP2P3P5Config,
) -> dict[Any, Any]:
    root = normalize_runtime_path(config.scheme_a_baseline_root).resolve(
        strict=True
    )
    manifest = _read_json(root / "scheme_a_manifest.json")
    if manifest.get("status") != "passed":
        raise ValueError("Scheme-A baseline status differs")
    path = _verified_output(
        dict(manifest.get("outputs") or {}),
        "segment_inventory",
        config.strict_hashes,
    )
    result: dict[Any, Any] = {"_path": path}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (str(row["case_key"]), str(row["segment_id"]))
            if key in result:
                raise ValueError(f"duplicate Segment inventory identity: {key}")
            result[key] = dict(row)
    return result


def _access_audit(
    config: SchemeAP2P3P5Config,
    ledger: Sequence[Mapping[str, Any]],
    gate_decisions: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    examples: Sequence[Any],
) -> dict[str, Any]:
    gate_objects = sum(bool(row["gate_triggered"]) for row in ledger)
    expected_decisions = (
        config.expected_access_gate_count * len(config.base_config.model_seeds)
    )
    review_ids = {
        example.group.group_id
        for example in examples
        if example.group.truth_target == "REVIEW_FALLBACK"
    }
    gated_ids = {
        str(row["group_id"]) for row in ledger if row["gate_triggered"]
    }
    gated_replayed = [
        row for row in decisions if str(row["group_id"]) in gated_ids
    ]
    gate = (
        len(ledger) == config.expected_eligible_count
        and gate_objects == config.expected_access_gate_count
        and len(gate_decisions) == expected_decisions
        and gated_ids == review_ids
        and len(gated_replayed) == expected_decisions
        and all(
            not bool(row["accepted"])
            and bool(row["clue_predicted"])
            and row["reason"] == "advance_right_access_invalid"
            for row in gated_replayed
        )
    )
    return {
        "ledger_count": len(ledger),
        "gate_object_count": gate_objects,
        "gate_decision_count": len(gate_decisions),
        "gated_review_count": len(gated_ids & review_ids),
        "non_review_gate_count": len(gated_ids - review_ids),
        "gate_pass": gate,
    }


def _validate_replay_scope(
    config: SchemeAP2P3P5Config,
    original_eligible: Sequence[Mapping[str, Any]],
    replayed_eligible: Sequence[Mapping[str, Any]],
    replayed_all: Sequence[Mapping[str, Any]],
    gate_decisions: Sequence[Mapping[str, Any]],
) -> None:
    seed_count = len(config.base_config.model_seeds)
    if len(original_eligible) != config.expected_eligible_count * seed_count:
        raise ValueError("engine eligible decision denominator differs")
    if len(replayed_eligible) != len(original_eligible):
        raise ValueError("replayed eligible decision denominator differs")
    if len(replayed_all) != config.expected_all_segment_count * seed_count:
        raise ValueError("replayed all-Segment denominator differs")
    if len(gate_decisions) != config.expected_access_gate_count * seed_count:
        raise ValueError("access-gate decision denominator differs")


def _stage_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    source_schema = str(result.get("schema_version") or "")
    result["schema_version"] = SCHEME_A_P2_P3_P5_SCHEMA
    if source_schema and source_schema != SCHEME_A_P2_P3_P5_SCHEMA:
        result["source_schema_version"] = source_schema
    return result


def _normalized_effective(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"output", "wall_seconds"}
    }


def _normalized_roadgraph(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
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


def _deterministic_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key != "performance"}


def _reference_match(root_value: Path | None, signature: str) -> bool | None:
    if root_value is None:
        return None
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p5_manifest.json")
    return str(manifest.get("determinism_signature")) == signature


def _verified_output(
    outputs: Mapping[str, Any],
    key: str,
    strict_hashes: bool,
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(
        strict=True
    )
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"source output hash mismatch: {key}")
    return path


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _validation_report(summary: Mapping[str, Any]) -> str:
    seed_rows = [
        row
        for row in summary["metrics"]["scope_metrics"]
        if row["scope"] == "SEED"
    ]
    return (
        "# P05-Scheme-A-P2-P3-P5 Validation\n\n"
        f"- decision: `{summary['decision']}`\n"
        f"- audit/model gate: `{summary['audit_gate_pass']}` / "
        f"`{summary['model_gate_pass']}`\n"
        f"- carrier/clue/RoadGraph: `{summary['carrier_gate_pass']}` / "
        f"`{summary['clue_gate_pass']}` / `{summary['roadgraph_gate_pass']}`\n"
        f"- seed wrong accepted: "
        f"`{ {str(row['seed']): row['carrier_wrong_accepted_count'] for row in seed_rows} }`\n"
        f"- determinism signature: `{summary['determinism_signature']}`\n"
        f"- reference match: `{summary['reference_run_match']}`\n"
    )


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _write_jsonl(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
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


__all__ = [
    "choose_p5_decision",
    "replay_advance_right_gate",
    "run_scheme_a_p2_p3_p5_oof",
]
