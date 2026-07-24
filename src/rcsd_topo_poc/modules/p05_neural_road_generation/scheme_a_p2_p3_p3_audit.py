from __future__ import annotations

import csv
import json
import math
import resource
import time
from collections import Counter
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p3_models import (
    DECISION_ARCHITECTURE_REQUIRED,
    DECISION_AUDIT_NO_GO,
    DECISION_NEXT_REPRESENTATION,
    SCHEME_A_P2_P3_P3_SCHEMA,
    SchemeAP2P3P3Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_ACCESS_GATE_REASON = "advance_right_access_invalid"
_P2_P3_P2_MANIFEST = "scheme_a_p2_p3_p2_manifest.json"
_BASELINE_MANIFEST = "scheme_a_manifest.json"


def run_scheme_a_p2_p3_p3_audit(config: SchemeAP2P3P3Config) -> Path:
    started = time.perf_counter()
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    source = _load_source_run(config)
    examples, metadata = load_dataset_p1_hierarchical_examples(
        config.p2_p3_p2_config
    )
    segment_inventory = _load_segment_inventory(config)
    evaluation_rows = list(_read_jsonl(source["paths"]["evaluation"]))
    evaluation_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in evaluation_rows
    }
    if len(evaluation_by_key) != len(evaluation_rows):
        raise ValueError("duplicate eligible evaluation identity")

    gate_ledger, segment_by_group = build_access_gate_ledger(
        examples,
        segment_inventory,
        expected_gate_count=config.expected_access_gate_count,
    )
    eligible_decisions = list(_read_jsonl(source["paths"]["eligible_decisions"]))
    replayed_eligible: list[dict[str, Any]] = []
    gate_decisions: list[dict[str, Any]] = []
    for row in eligible_decisions:
        group_id = str(row["group_id"])
        replayed = apply_advance_right_access_gate(
            row,
            segment_by_group[group_id],
        )
        replayed_eligible.append(replayed)
        if replayed is not row and replayed != row:
            gate_decisions.append(
                {
                    "schema_version": SCHEME_A_P2_P3_P3_SCHEMA,
                    "seed": int(row["seed"]),
                    "case_key": str(row["case_key"]),
                    "group_id": group_id,
                    "object_id": str(row["object_id"]),
                    "before_accepted": bool(row["accepted"]),
                    "before_reason": str(row["reason"]),
                    "before_proposal_target": str(row["proposal_target"]),
                    "after_accepted": bool(replayed["accepted"]),
                    "after_reason": str(replayed["reason"]),
                    "after_proposal_target": str(replayed["proposal_target"]),
                    "access_valid": False,
                    "segment_type": "ADVANCE_RIGHT",
                }
            )

    all_decisions = list(_read_jsonl(source["paths"]["all_segment_decisions"]))
    replay_by_key = {
        (int(row["seed"]), str(row["group_id"])): row
        for row in replayed_eligible
    }
    replayed_all = [
        replay_by_key.get((int(row["seed"]), str(row["group_id"])), row)
        for row in all_decisions
    ]
    _validate_replay_scope(
        config,
        original_eligible=eligible_decisions,
        replayed_eligible=replayed_eligible,
        all_decisions=replayed_all,
        gate_decisions=gate_decisions,
        evaluation_by_key=evaluation_by_key,
    )

    roadgraph_rows, effective_rows, closure_rows = _materialize_replay(
        config,
        run_root,
        replayed_all,
        metadata,
    )
    eligible_ids = {example.group.group_id for example in examples}
    eligible_effective = [
        row
        for row in effective_rows
        if row.get("object_type") == "SEGMENT"
        and str(row["group_id"]) in eligible_ids
    ]
    fold_records = list(
        _read_json(source["paths"]["folds"]).get("folds") or []
    )
    metrics = _all_metrics(
        examples,
        replayed_eligible,
        evaluation_rows,
        eligible_effective,
        roadgraph_rows,
        closure_rows,
        fold_records,
        metadata["eligible_clue_only_group_ids"],
        config.p2_p3_p2_config.base_config,
    )
    replay_audit = _replay_audit(
        config,
        replayed_eligible,
        replayed_all,
        evaluation_by_key,
        effective_rows,
        roadgraph_rows,
        closure_rows,
        gate_decisions,
        metadata["failure_group_ids"],
        metrics,
    )
    residual_audit = build_residual_false_use_audit(
        config,
        examples,
        fold_records,
        list(_read_jsonl(source["paths"]["scores"])),
        replayed_eligible,
        evaluation_rows,
    )

    source_gate = (
        len(gate_ledger) == config.expected_eligible_count
        and sum(bool(row["gate_triggered"]) for row in gate_ledger)
        == config.expected_access_gate_count
        and all(
            row["truth_target"] == "REVIEW_FALLBACK"
            for row in gate_ledger
            if row["gate_triggered"]
        )
        and not any(
            row["truth_target"] != "REVIEW_FALLBACK"
            and row["gate_triggered"]
            for row in gate_ledger
        )
    )
    safety_gate = (
        replay_audit["gate_decision_count"]
        == config.expected_access_gate_count * config.expected_seed_count
        and replay_audit["review_auto_publish_by_seed"]
        == {str(seed): 0 for seed in config.p2_p3_p2_config.base_config.model_seeds}
        and replay_audit["wrong_accepted_by_seed"]
        == {"311": 1, "313": 1, "317": 0}
        and replay_audit["non_gated_decision_change_count"] == 0
    )
    roadgraph_gate = replay_audit["roadgraph_gate_pass"]
    residual_gate = residual_audit["gate_pass"]
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
    audit_gate = (
        source_gate and safety_gate and roadgraph_gate and residual_gate
        and resource_gate
    )
    if not audit_gate:
        decision = DECISION_AUDIT_NO_GO
    elif residual_audit["route"] == "NEW_PRE_T06_REPRESENTATION_REQUIRED":
        decision = DECISION_NEXT_REPRESENTATION
    else:
        decision = DECISION_ARCHITECTURE_REQUIRED

    paths = {
        "gate_ledger": run_root / "advance_right_access_gate_ledger.jsonl",
        "gate_decisions": run_root / "advance_right_gate_decisions.jsonl",
        "eligible_decisions": run_root / "eligible_decisions.jsonl",
        "all_segment_decisions": run_root / "all_segment_decisions.jsonl",
        "effective": run_root / "effective_selections.jsonl",
        "roadgraphs": run_root / "roadgraph_index.jsonl",
        "closure": run_root / "junction_closure.jsonl",
        "residual_audit": run_root / "residual_false_use_audit.json",
        "metrics": run_root / "metrics.json",
        "summary": run_root / "scheme_a_p2_p3_p3_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["gate_ledger"], gate_ledger)
    _write_jsonl(paths["gate_decisions"], gate_decisions)
    _write_jsonl(paths["eligible_decisions"], replayed_eligible)
    _write_jsonl(paths["all_segment_decisions"], replayed_all)
    _write_jsonl(paths["effective"], effective_rows)
    _write_jsonl(paths["roadgraphs"], roadgraph_rows)
    _write_jsonl(paths["closure"], closure_rows)
    write_json(paths["residual_audit"], residual_audit)
    write_json(paths["metrics"], metrics)

    deterministic_payload = {
        "source_lineage": source["lineage"],
        "gate_ledger": gate_ledger,
        "gate_decisions": gate_decisions,
        "eligible_decisions": replayed_eligible,
        "effective": [_normalized_effective(row) for row in effective_rows],
        "roadgraphs": [_normalized_roadgraph(row) for row in roadgraph_rows],
        "closure": closure_rows,
        "residual_audit": residual_audit,
        "metrics": _deterministic_metrics(metrics),
        "replay_audit": replay_audit,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    if reference_match is False:
        decision = DECISION_AUDIT_NO_GO
        audit_gate = False
    summary = {
        "schema_version": SCHEME_A_P2_P3_P3_SCHEMA,
        "decision": decision,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "source_gate_pass": source_gate,
        "safety_gate_pass": safety_gate,
        "roadgraph_gate_pass": roadgraph_gate,
        "residual_gate_pass": residual_gate,
        "resource_gate_pass": resource_gate,
        "audit_gate_pass": audit_gate,
        "gate_ledger_count": len(gate_ledger),
        "gate_object_count": sum(row["gate_triggered"] for row in gate_ledger),
        "gate_decision_count": len(gate_decisions),
        "replay_audit": replay_audit,
        "residual_false_use_audit": residual_audit,
        "metrics": metrics,
        "resource": resource,
        "lineage": source["lineage"],
        "model_training_count": 0,
        "threshold_change_count": 0,
        "truth_inference_feature_count": 0,
        "t06_inference_feature_count": 0,
        "movement_feature_count": 0,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_performed": False,
        "crs": "EPSG:3857",
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(_validation_report(summary), encoding="utf-8")
    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p3_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P3_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "safety_gate_and_residual_audit_completed",
            "decision": decision,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "parameters": {
                "model_seeds": list(
                    config.p2_p3_p2_config.base_config.model_seeds
                ),
                "nearest_neighbor_count": config.nearest_neighbor_count,
                "residual_group_id": config.residual_group_id,
                "new_model_training": False,
                "threshold_change": False,
            },
            "outputs": outputs,
            "truth_inference_feature_count": 0,
            "t06_inference_feature_count": 0,
            "movement_feature_count": 0,
            "geometry_write_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p3-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def build_access_gate_ledger(
    examples: Sequence[Any],
    segment_inventory: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    expected_gate_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]]]:
    rows: list[dict[str, Any]] = []
    by_group: dict[str, Mapping[str, Any]] = {}
    for example in examples:
        group = example.group
        key = (group.case_key, group.object_id)
        segment = segment_inventory.get(key)
        if segment is None:
            raise ValueError(f"eligible Segment is absent from inventory: {group.group_id}")
        if (
            str(segment["case_key"]) != group.case_key
            or str(segment["segment_id"]) != group.object_id
        ):
            raise ValueError(f"Segment inventory identity mismatch: {group.group_id}")
        segment_type = str(segment["segment_type"]).upper()
        access_valid = _yes(segment["access_valid"])
        gate_triggered = segment_type == "ADVANCE_RIGHT" and not access_valid
        rows.append(
            {
                "schema_version": SCHEME_A_P2_P3_P3_SCHEMA,
                "case_key": group.case_key,
                "fold": int(group.fold),
                "group_id": group.group_id,
                "object_id": group.object_id,
                "segment_type": segment_type,
                "access_valid": access_valid,
                "independent_road_valid": _yes(segment["independent_road_valid"]),
                "truth_target": group.truth_target,
                "gate_triggered": gate_triggered,
                "inference_source": "T01_FROZEN_SEGMENT_ACCESS",
            }
        )
        by_group[group.group_id] = segment
    rows.sort(key=lambda row: str(row["group_id"]))
    if len(by_group) != len(examples):
        raise ValueError("eligible Segment inventory join is not one-to-one")
    triggered = [row for row in rows if row["gate_triggered"]]
    if len(triggered) != expected_gate_count:
        raise ValueError("ADVANCE_RIGHT invalid-access denominator differs")
    if any(
        row["segment_type"] != "ADVANCE_RIGHT"
        or row["access_valid"]
        or row["truth_target"] != "REVIEW_FALLBACK"
        for row in triggered
    ):
        raise ValueError("invalid access conflicts with confirmed Review semantics")
    return rows, by_group


def apply_advance_right_access_gate(
    decision: Mapping[str, Any],
    segment: Mapping[str, Any],
) -> dict[str, Any] | Mapping[str, Any]:
    if (
        str(decision.get("case_key") or "") != str(segment.get("case_key") or "")
        or str(decision.get("object_id") or "")
        != str(segment.get("segment_id") or "")
    ):
        raise ValueError("access gate identity mismatch")
    segment_type = str(segment.get("segment_type") or "").upper()
    if "access_valid" not in segment:
        raise ValueError("access gate source lacks access_valid")
    if segment_type != "ADVANCE_RIGHT" or _yes(segment["access_valid"]):
        return decision
    result = dict(decision)
    result.update(
        {
            "accepted": False,
            "clue_predicted": True,
            "reason": _ACCESS_GATE_REASON,
            "access_safety_gate": True,
            "pre_gate_accepted": bool(decision["accepted"]),
            "pre_gate_reason": str(decision["reason"]),
        }
    )
    return result


def build_residual_false_use_audit(
    config: SchemeAP2P3P3Config,
    examples: Sequence[Any],
    fold_records: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    evaluations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    example_by_id = {example.group.group_id: example for example in examples}
    target = example_by_id.get(config.residual_group_id)
    if target is None:
        raise ValueError("residual false-use group is absent from eligible scope")
    if target.group.truth_target != "KEEP_SWSD" or target.group.fold != 1:
        raise ValueError("residual false-use truth/fold differs")

    scores = [
        row for row in score_rows if row["group_id"] == config.residual_group_id
    ]
    residual_decisions = [
        row for row in decisions if row["group_id"] == config.residual_group_id
    ]
    residual_evaluations = [
        row for row in evaluations if row["group_id"] == config.residual_group_id
    ]
    seeds = set(config.p2_p3_p2_config.base_config.model_seeds)
    if (
        {int(row["seed"]) for row in scores} != seeds
        or {int(row["seed"]) for row in residual_decisions} != seeds
        or {int(row["seed"]) for row in residual_evaluations} != seeds
    ):
        raise ValueError("residual false-use seed scope differs")
    if any(row["selected_target"] != "USE_RCSD" for row in scores):
        raise ValueError("residual false-use is not stable across seeds")

    fold_by_seed = {
        int(row["seed"]): row
        for row in fold_records
        if int(row["held_out_fold"]) == target.group.fold
    }
    if set(fold_by_seed) != seeds:
        raise ValueError("residual held-out fold records differ")
    seed_audits: list[dict[str, Any]] = []
    for score in sorted(scores, key=lambda row: int(row["seed"])):
        seed = int(score["seed"])
        fold = fold_by_seed[seed]
        train_cases = set(str(value) for value in fold["train_case_keys"])
        train_examples = [
            example for example in examples if example.group.case_key in train_cases
        ]
        if not train_examples or target.group.case_key in train_cases:
            raise ValueError("residual nearest-neighbor training scope leaked")
        neighbors = _nearest_neighbors(
            target,
            train_examples,
            limit=config.nearest_neighbor_count,
        )
        exact_evidence = [
            example
            for example in train_examples
            if example.evidence_features == target.evidence_features
        ]
        target_signature = _group_feature_signature(target.group)
        exact_group = [
            example
            for example in train_examples
            if _group_feature_signature(example.group) == target_signature
        ]
        truth_index = list(score["candidate_ids"]).index(
            next(
                row["truth_candidate_id"]
                for row in residual_evaluations
                if int(row["seed"]) == seed
            )
        )
        selected_index = list(score["candidate_ids"]).index(
            score["selected_candidate_id"]
        )
        decision = next(
            row for row in residual_decisions if int(row["seed"]) == seed
        )
        seed_audits.append(
            {
                "seed": seed,
                "fold": int(target.group.fold),
                "train_case_count": len(train_cases),
                "train_group_count": len(train_examples),
                "selected_target": score["selected_target"],
                "truth_target": target.group.truth_target,
                "accepted": bool(decision["accepted"]),
                "decision_reason": decision["reason"],
                "selected_score": float(score["candidate_scores"][selected_index]),
                "truth_score": float(score["candidate_scores"][truth_index]),
                "score_margin": float(
                    score["candidate_scores"][selected_index]
                    - score["candidate_scores"][truth_index]
                ),
                "selected_utility": float(
                    score["candidate_utilities"][selected_index]
                ),
                "truth_utility": float(score["candidate_utilities"][truth_index]),
                "utility_margin": float(
                    score["candidate_utilities"][selected_index]
                    - score["candidate_utilities"][truth_index]
                ),
                "clue_probability": float(score["clue_probability"]),
                "clue_threshold": float(decision["clue_threshold"]),
                "exact_evidence_collision_count": len(exact_evidence),
                "exact_evidence_collision_targets": dict(
                    Counter(row.group.truth_target for row in exact_evidence)
                ),
                "exact_group_signature_collision_count": len(exact_group),
                "exact_group_signature_collision_targets": dict(
                    Counter(row.group.truth_target for row in exact_group)
                ),
                "nearest_neighbors": neighbors,
                "nearest_neighbor_target_counts": dict(
                    Counter(row["truth_target"] for row in neighbors)
                ),
            }
        )

    candidate_comparison = _target_candidate_comparison(target.group)
    exact_collision = any(
        row["exact_group_signature_collision_count"] > 0 for row in seed_audits
    )
    neighbor_truths = Counter(
        neighbor["truth_target"]
        for seed_row in seed_audits
        for neighbor in seed_row["nearest_neighbors"]
    )
    all_rank_wrong = all(row["selected_target"] == "USE_RCSD" for row in seed_audits)
    all_large_margin = all(row["score_margin"] > 5.0 for row in seed_audits)
    representation_failure = (
        all_rank_wrong
        and all_large_margin
        and neighbor_truths["USE_RCSD"] > neighbor_truths["KEEP_SWSD"]
    )
    route = (
        "NEW_PRE_T06_REPRESENTATION_REQUIRED"
        if representation_failure
        else "ARCHITECTURE_DECISION_REQUIRED"
    )
    return {
        "schema_version": SCHEME_A_P2_P3_P3_SCHEMA,
        "group_id": config.residual_group_id,
        "case_key": target.group.case_key,
        "object_id": target.group.object_id,
        "truth_target": target.group.truth_target,
        "clue_target": bool(target.group.anomaly_target),
        "evidence_dim": len(target.evidence_features),
        "stable_wrong_ranking_all_seeds": all_rank_wrong,
        "large_wrong_margin_all_seeds": all_large_margin,
        "exact_cross_truth_collision_observed": exact_collision,
        "nearest_neighbor_target_counts": dict(neighbor_truths),
        "candidate_comparison": candidate_comparison,
        "seed_audits": seed_audits,
        "route": route,
        "gate_pass": (
            len(seed_audits) == config.expected_seed_count
            and all_rank_wrong
            and all(row["train_group_count"] > 0 for row in seed_audits)
        ),
        "truth_used_for_audit_only": True,
        "identifier_feature_count": 0,
        "t06_inference_feature_count": 0,
        "new_business_rule_created": False,
    }


def _nearest_neighbors(
    target: Any,
    train_examples: Sequence[Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    dimension = len(target.evidence_features)
    means = [
        sum(row.evidence_features[index] for row in train_examples)
        / len(train_examples)
        for index in range(dimension)
    ]
    scales = [
        max(
            1e-6,
            math.sqrt(
                sum(
                    (row.evidence_features[index] - means[index]) ** 2
                    for row in train_examples
                )
                / len(train_examples)
            ),
        )
        for index in range(dimension)
    ]
    target_vector = [
        (target.evidence_features[index] - means[index]) / scales[index]
        for index in range(dimension)
    ]
    distances: list[tuple[float, Any]] = []
    for example in train_examples:
        vector = [
            (example.evidence_features[index] - means[index]) / scales[index]
            for index in range(dimension)
        ]
        distance = math.sqrt(
            sum((left - right) ** 2 for left, right in zip(target_vector, vector))
            / dimension
        )
        distances.append((distance, example))
    return [
        {
            "rank": rank,
            "distance": distance,
            "case_key": example.group.case_key,
            "fold": int(example.group.fold),
            "group_id": example.group.group_id,
            "truth_target": example.group.truth_target,
            "clue_target": bool(example.group.anomaly_target),
            "object_type": example.group.object_type,
        }
        for rank, (distance, example) in enumerate(
            sorted(
                distances,
                key=lambda item: (item[0], item[1].group.group_id),
            )[:limit],
            start=1,
        )
    ]


def _target_candidate_comparison(group: Any) -> dict[str, Any]:
    by_target = {candidate.candidate_target: candidate for candidate in group.candidates}
    selected = by_target.get("USE_RCSD")
    truth = by_target.get("KEEP_SWSD")
    if selected is None or truth is None:
        raise ValueError("residual group lacks USE/KEEP candidate comparison")
    return {
        "selected_candidate_target": selected.candidate_target,
        "truth_candidate_target": truth.candidate_target,
        "selected_numeric_features": list(selected.numeric_features),
        "truth_numeric_features": list(truth.numeric_features),
        "numeric_delta": [
            left - right
            for left, right in zip(
                selected.numeric_features,
                truth.numeric_features,
                strict=True,
            )
        ],
        "selected_candidate_tokens": list(selected.candidate_tokens),
        "truth_candidate_tokens": list(truth.candidate_tokens),
        "shared_candidate_tokens": sorted(
            set(selected.candidate_tokens) & set(truth.candidate_tokens)
        ),
        "object_tokens": list(group.object_tokens),
        "context_tokens": list(group.context_tokens),
    }


def _group_feature_signature(group: Any) -> str:
    return canonical_sha256(
        {
            "object_type": group.object_type,
            "object_tokens": list(group.object_tokens),
            "context_tokens": list(group.context_tokens),
            "hard_unsafe": bool(group.hard_unsafe),
            "candidates": [
                {
                    "target": candidate.candidate_target,
                    "tokens": list(candidate.candidate_tokens),
                    "numeric": list(candidate.numeric_features),
                }
                for candidate in sorted(
                    group.candidates,
                    key=lambda value: (value.candidate_target, value.candidate_tokens),
                )
            ],
        }
    )


def _load_source_run(config: SchemeAP2P3P3Config) -> dict[str, Any]:
    root = normalize_runtime_path(config.p2_p3_p2_run_root).resolve(strict=True)
    manifest_path = root / _P2_P3_P2_MANIFEST
    manifest = _read_json(manifest_path)
    if manifest.get("decision") != "P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO":
        raise ValueError("P2-P3-P2 source decision differs")
    outputs = dict(manifest.get("outputs") or {})
    keys = (
        "eligible_decisions",
        "evaluation",
        "all_segment_decisions",
        "scores",
        "folds",
    )
    paths = {
        key: _verified_output(outputs, key, strict_hashes=config.strict_hashes)
        for key in keys
    }
    return {
        "root": root,
        "manifest": manifest,
        "paths": paths,
        "lineage": {
            "p2_p3_p2_manifest_sha256": sha256_file(manifest_path),
            "p2_p3_p2_determinism_signature": manifest["determinism_signature"],
            **{
                f"p2_p3_p2_{key}_sha256": sha256_file(path)
                for key, path in paths.items()
            },
        },
    }


def _load_segment_inventory(
    config: SchemeAP2P3P3Config,
) -> dict[tuple[str, str], dict[str, Any]]:
    root = normalize_runtime_path(config.scheme_a_baseline_root).resolve(strict=True)
    manifest_path = root / _BASELINE_MANIFEST
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "passed":
        raise ValueError("Scheme A baseline status differs")
    path = _verified_output(
        dict(manifest.get("outputs") or {}),
        "segment_inventory",
        strict_hashes=config.strict_hashes,
    )
    result: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (str(row["case_key"]), str(row["segment_id"]))
            if key in result:
                raise ValueError(f"duplicate Segment inventory identity: {key}")
            result[key] = dict(row)
    return result


def _materialize_replay(
    config: SchemeAP2P3P3Config,
    run_root: Path,
    decisions: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_groups = list(metadata["all_groups"])
    dataset = metadata["dataset"]
    payload_path = normalize_runtime_path(
        str(dataset["dataset_manifest"]["outputs"]["payloads"]["path"])
    ).resolve(strict=True)
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    node_scores = _base_node_scores(
        config.p2_p3_p2_config.base_config.base_oof_run_a,
        config.p2_p3_p2_config.base_config.base_seeds,
    )
    expected_failure_cases = set(metadata["failure_by_case"])
    expected_failure_manifest = {
        case_key: frozenset(info["failures"])
        for case_key, info in metadata["failure_by_case"].items()
    }
    roadgraphs: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    closures: list[dict[str, Any]] = []
    for seed in config.p2_p3_p2_config.base_config.model_seeds:
        seed_decisions = [row for row in decisions if int(row["seed"]) == seed]
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
    roadgraphs.sort(key=lambda row: (int(row["seed"]), str(row["case_key"])))
    effective.sort(key=lambda row: (int(row["seed"]), str(row["group_id"])))
    closures.sort(key=lambda row: int(row["seed"]))
    return roadgraphs, effective, closures


def _validate_replay_scope(
    config: SchemeAP2P3P3Config,
    *,
    original_eligible: Sequence[Mapping[str, Any]],
    replayed_eligible: Sequence[Mapping[str, Any]],
    all_decisions: Sequence[Mapping[str, Any]],
    gate_decisions: Sequence[Mapping[str, Any]],
    evaluation_by_key: Mapping[tuple[int, str], Mapping[str, Any]],
) -> None:
    expected_eligible = config.expected_eligible_count * config.expected_seed_count
    expected_all = (
        config.expected_eligible_count + config.expected_context_count
    ) * config.expected_seed_count
    if len(original_eligible) != expected_eligible or len(replayed_eligible) != expected_eligible:
        raise ValueError("eligible replay denominator differs")
    if len(all_decisions) != expected_all:
        raise ValueError("all-Segment replay denominator differs")
    if len(gate_decisions) != config.expected_access_gate_count * config.expected_seed_count:
        raise ValueError("access gate decision denominator differs")
    for before, after in zip(original_eligible, replayed_eligible, strict=True):
        key = (int(before["seed"]), str(before["group_id"]))
        truth = evaluation_by_key[key]
        if truth["truth_target"] == "REVIEW_FALLBACK":
            if bool(after["accepted"]) or after["reason"] != _ACCESS_GATE_REASON:
                raise ValueError("Review decision escaped access gate")
        elif before != after:
            raise ValueError("non-gated eligible decision changed")


def _replay_audit(
    config: SchemeAP2P3P3Config,
    eligible: Sequence[Mapping[str, Any]],
    all_decisions: Sequence[Mapping[str, Any]],
    evaluation: Mapping[tuple[int, str], Mapping[str, Any]],
    effective: Sequence[Mapping[str, Any]],
    roadgraphs: Sequence[Mapping[str, Any]],
    closures: Sequence[Mapping[str, Any]],
    gate_decisions: Sequence[Mapping[str, Any]],
    failure_group_ids: Sequence[str],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    seeds = config.p2_p3_p2_config.base_config.model_seeds
    seed_metrics = {
        int(row["seed"]): row
        for row in metrics["scope_metrics"]
        if row["scope"] == "SEED"
    }
    if set(seed_metrics) != set(seeds):
        raise ValueError("seed-level replay metrics differ")
    wrong = {
        str(seed): int(seed_metrics[seed]["carrier_wrong_accepted_count"])
        for seed in seeds
    }
    review = {
        str(seed): int(seed_metrics[seed]["review_auto_publish_count"])
        for seed in seeds
    }
    context_ids = {
        str(row["group_id"])
        for row in all_decisions
        if not bool(row.get("label_eligible"))
    }
    context_auto = sum(
        bool(row["accepted"]) for row in all_decisions
        if str(row["group_id"]) in context_ids
    )
    effective_segments = [
        row for row in effective if row.get("object_type") == "SEGMENT"
    ]
    context_non_keep = sum(
        row.get("effective_target") != "KEEP_SWSD"
        for row in effective_segments
        if str(row["group_id"]) in context_ids
    )
    terminals = {
        str(seed): dict(
            Counter(
                row["terminal_state"]
                for row in roadgraphs
                if int(row["seed"]) == seed
            )
        )
        for seed in seeds
    }
    conflict_count = sum(
        int(row.get("requirement_conflict_count") or 0)
        + int(row.get("node_conflict_count") or 0)
        + int(row.get("node_target_mismatch_count") or 0)
        for row in closures
    )
    expected_failure_nonlocal = sum(
        str(row["group_id"]) not in set(failure_group_ids)
        and row.get("reason") == "dataset_p1_localized_expected_failure"
        for row in all_decisions
    )
    return {
        "gate_decision_count": len(gate_decisions),
        "wrong_accepted_by_seed": wrong,
        "review_auto_publish_by_seed": review,
        "context_auto_accept_count": context_auto,
        "context_effective_non_keep_count": context_non_keep,
        "terminal_state_counts_by_seed": terminals,
        "closure_conflict_count": conflict_count,
        "expected_failure_nonlocal_cascade_count": expected_failure_nonlocal,
        "non_gated_decision_change_count": 0,
        "skeleton_mutation_count": 0,
        "repair_count": 0,
        "silent_fix_count": 0,
        "roadgraph_gate_pass": (
            context_auto == 0
            and context_non_keep == 0
            and conflict_count == 0
            and expected_failure_nonlocal == 0
            and all(
                terminals[str(seed)] == {"EXPECTED_FAIL": 2, "LEGAL": 49}
                for seed in seeds
            )
        ),
    }


def _verified_output(
    outputs: Mapping[str, Any],
    key: str,
    *,
    strict_hashes: bool,
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"output hash mismatch: {key}")
    return path


def _reference_match(path: Path | None, signature: str) -> bool | None:
    if path is None:
        return None
    root = normalize_runtime_path(path).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p3_manifest.json")
    return str(manifest.get("determinism_signature") or "") == signature


def _normalized_effective(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items()
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
    return {
        key: value for key, value in metrics.items() if key != "performance"
    }


def _validation_report(summary: Mapping[str, Any]) -> str:
    replay = summary["replay_audit"]
    residual = summary["residual_false_use_audit"]
    return "\n".join(
        [
            "# P05-Scheme-A-P2-P3-P3 Validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- access gate objects/decisions: `{summary['gate_object_count']}/"
            f"{summary['gate_decision_count']}`",
            f"- wrong accepted by seed: `{replay['wrong_accepted_by_seed']}`",
            f"- Review auto by seed: `{replay['review_auto_publish_by_seed']}`",
            f"- RoadGraph gate: `{summary['roadgraph_gate_pass']}`",
            f"- residual route: `{residual['route']}`",
            f"- determinism signature: `{summary['determinism_signature']}`",
            "",
        ]
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def _yes(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if value > 10_000_000 else value * 1024


__all__ = [
    "apply_advance_right_access_gate",
    "build_access_gate_ledger",
    "build_residual_false_use_audit",
    "run_scheme_a_p2_p3_p3_audit",
]
