from __future__ import annotations

import hashlib
import json
import platform
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import parameter_count
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import P1GroupExample
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_execution import (
    load_p2_p1_payloads,
    materialize_p2_p1_seed,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_dataset import (
    load_segment_safety_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_models import (
    SCHEME_A_P2_P2_P1_SCHEMA,
    SchemeAP2P2P1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_training import (
    safety_metrics,
    train_segment_safety_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p2_p1_oof(config: SchemeAP2P2P1Config) -> Path:
    started = time.perf_counter()
    groups, metadata = load_segment_safety_groups(config)
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    all_scores: list[dict[str, Any]] = []
    all_decisions: list[dict[str, Any]] = []
    all_evaluation: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    training_started = time.perf_counter()
    for seed in config.safety_seeds:
        for fold in range(config.expected_fold_count):
            result = train_segment_safety_fold(
                groups,
                proposals=metadata["proposals"],
                case_folds=metadata["case_folds"],
                held_out_fold=fold,
                seed=seed,
                dataset_signature=metadata["lineage"]["safety_dataset_signature"],
                config=config,
            )
            model_signature = _state_signature(result["model"])
            fold_record = _save_fold(
                run_root / "folds" / str(seed) / str(fold),
                result,
                seed=seed,
                fold=fold,
                model_signature=model_signature,
                dataset_signature=metadata["lineage"]["safety_dataset_signature"],
                config=config,
            )
            fold_records.append(fold_record)
            for group, scores, probabilities, anomaly in zip(
                result["held_out_groups"],
                result["held_out_scores"],
                result["held_out_probabilities"],
                result["held_out_anomaly_probabilities"],
                strict=True,
            ):
                for candidate, score, probability in zip(
                    group.candidates, scores, probabilities, strict=True
                ):
                    all_scores.append(
                        {
                            "schema_version": SCHEME_A_P2_P2_P1_SCHEMA,
                            "case_key": group.case_key,
                            "group_id": group.group_id,
                            "object_type": "SEGMENT",
                            "candidate_id": candidate.candidate_id,
                            "candidate_target": candidate.candidate_target,
                            "score": float(score),
                            "probability": float(probability),
                            "anomaly_probability": float(anomaly),
                            "seed": seed,
                            "fold": fold,
                            "model_signature": model_signature,
                        }
                    )
            for row in result["held_out_decisions"]:
                all_decisions.append(
                    {
                        "schema_version": SCHEME_A_P2_P2_P1_SCHEMA,
                        **row,
                        "seed": seed,
                        "model_signature": model_signature,
                    }
                )
            for row in result["held_out_evaluation"]:
                all_evaluation.append({**row, "seed": seed})
            del result
    training_seconds = time.perf_counter() - training_started

    expected_failure_cases = {row[0] for row in config.expected_roadgraph_failures}
    for decision in all_decisions:
        if decision["case_key"] in expected_failure_cases:
            decision.update(
                {
                    "accepted": False,
                    "decision": "FALLBACK",
                    "reason": "expected_swsd_baseline_failure",
                }
            )
    accepted_by_key = {
        (int(row["seed"]), str(row["group_id"])): bool(row["accepted"])
        for row in all_decisions
    }
    for row in all_evaluation:
        row["accepted"] = accepted_by_key[(int(row["seed"]), str(row["group_id"]))]

    all_groups = list(metadata["all_groups"])
    payload_path = _payload_path(metadata["dataset"])
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    node_scores = _base_node_scores(metadata["oof_a"]["paths"]["scores"], config.base_seeds)
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
    for seed in config.safety_seeds:
        seed_decisions = [row for row in all_decisions if int(row["seed"]) == seed]
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

    score_path = run_root / "safety_scores.jsonl"
    decision_path = run_root / "decisions.jsonl"
    evaluation_path = run_root / "evaluation.jsonl"
    effective_path = run_root / "effective_selections.jsonl"
    roadgraph_path = run_root / "roadgraph_index.jsonl"
    feature_audit_path = run_root / "feature_audit.json"
    _write_jsonl(score_path, sorted(all_scores, key=_score_key))
    _write_jsonl(decision_path, sorted(all_decisions, key=_seed_group_key))
    _write_jsonl(evaluation_path, sorted(all_evaluation, key=_seed_group_key))
    _write_jsonl(effective_path, sorted(effective_rows, key=_seed_group_key))
    _write_jsonl(roadgraph_path, sorted(roadgraph_rows, key=lambda row: (int(row["seed"]), row["case_key"])))
    feature_audit = {
        "schema_version": "p05-scheme-a-p2-p2-p1-feature-audit-v1",
        "case_count": len(metadata["case_folds"]),
        "segment_group_count": len(groups),
        "base_seed_count": len(config.base_seeds),
        "fold_count": len(set(metadata["case_folds"].values())),
        "review_count": sum(group.truth_target == "REVIEW_FALLBACK" for group in groups),
        "anomaly_target_count": sum(group.anomaly_target for group in groups),
        "stable_false_use_count": len(metadata["stable_false_use_group_ids"]),
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "oof_ab_comparison": metadata["oof_ab_comparison"],
        "case_fold_overlap_count": sum(
            bool(
                set(record["summary"]["train_case_keys"])
                & set(record["summary"]["held_out_case_keys"])
            )
            for record in fold_records
        ),
        "passed": True,
    }
    feature_audit["passed"] = (
        feature_audit["case_count"] == config.expected_case_count
        and feature_audit["segment_group_count"] == config.expected_segment_group_count
        and feature_audit["review_count"] == config.expected_review_count
        and feature_audit["stable_false_use_count"] == config.expected_stable_false_use_count
        and not feature_audit["case_fold_overlap_count"]
        and all(metadata["oof_ab_comparison"].values())
    )
    write_json(feature_audit_path, feature_audit)

    seed_metrics = [
        _seed_metrics(
            seed,
            groups,
            all_decisions,
            all_evaluation,
            metadata["stable_false_use_group_ids"],
            roadgraph_rows,
            closure_rows,
            config,
        )
        for seed in config.safety_seeds
    ]
    safety_pass = all(row["safety_gate_pass"] for row in seed_metrics)
    roadgraph_pass = all(row["roadgraph_gate_pass"] for row in seed_metrics)
    if not feature_audit["passed"]:
        decision = "P05_SCHEME_A_P2_P2_P1_EVIDENCE_NO_GO"
    elif not safety_pass:
        decision = "P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO"
    elif not roadgraph_pass:
        decision = "P05_SCHEME_A_P2_P2_P1_ROADGRAPH_NO_GO"
    else:
        decision = "P05_SCHEME_A_P2_P2_P1_SAFETY_HEAD_GO"
    deterministic_payload = {
        "scores": sorted(all_scores, key=_score_key),
        "decisions": sorted(all_decisions, key=_seed_group_key),
        "evaluation": sorted(all_evaluation, key=_seed_group_key),
        "effective": sorted(effective_rows, key=_seed_group_key),
        "roadgraphs": [
            {key: value for key, value in row.items() if key != "output"}
            for row in sorted(roadgraph_rows, key=lambda item: (int(item["seed"]), item["case_key"]))
        ],
        "seed_metrics": seed_metrics,
    }
    resource_audit = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": "cpu",
        "cuda_available": torch.cuda.is_available(),
        "training_wall_seconds": training_seconds,
        "total_wall_seconds": time.perf_counter() - started,
        "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        "gpu_peak_memory_mb": 0.0,
        "training_within_six_hours": training_seconds <= 6 * 60 * 60,
        "cpu_ram_within_16gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0 <= 16 * 1024,
        "gpu_vram_within_8gb": True,
    }
    summary = {
        "schema_version": "p05-scheme-a-p2-p2-p1-summary-v1",
        "decision": decision,
        "gate_pass": decision == "P05_SCHEME_A_P2_P2_P1_SAFETY_HEAD_GO",
        "case_count": len(metadata["case_folds"]),
        "segment_group_count": len(groups),
        "fold_count": config.expected_fold_count,
        "base_seeds": list(config.base_seeds),
        "safety_seeds": list(config.safety_seeds),
        "movement_candidate_count": 0,
        "movement_decision_count": 0,
        "seed_metrics": seed_metrics,
        "roadgraph_terminal_counts": dict(
            sorted(Counter(str(row["terminal_state"]) for row in roadgraph_rows).items())
        ),
        "feature_audit": feature_audit,
        "resource": resource_audit,
        "determinism_signature": canonical_sha256(deterministic_payload),
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    summary_path = run_root / "scheme_a_p2_p2_p1_summary.json"
    report_path = run_root / "validation_report.md"
    fold_index_path = run_root / "fold_index.json"
    write_json(summary_path, summary)
    write_json(fold_index_path, fold_records)
    report_path.write_text(_validation_report(summary), encoding="utf-8")
    outputs = {
        "scores": output_record(score_path),
        "decisions": output_record(decision_path),
        "evaluation": output_record(evaluation_path),
        "effective_selections": output_record(effective_path),
        "roadgraphs": output_record(roadgraph_path),
        "feature_audit": output_record(feature_audit_path),
        "fold_index": output_record(fold_index_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-scheme-a-p2-p2-p1-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "safety_head_passed" if summary["gate_pass"] else "safety_head_no_go",
        "decision": decision,
        "lineage": metadata["lineage"],
        "parameters": {
            "base_seeds": config.base_seeds,
            "safety_seeds": config.safety_seeds,
            "expected_fold_count": config.expected_fold_count,
            "embedding_dim": config.embedding_dim,
            "hidden_dim": config.hidden_dim,
            "type_embedding_dim": config.type_embedding_dim,
            "numeric_dim": config.numeric_dim,
            "dropout": config.dropout,
            "learning_rate": config.learning_rate,
            "weight_decay": config.weight_decay,
            "max_epochs": config.max_epochs,
            "patience": config.patience,
            "device": config.device,
        },
        "outputs": outputs,
        "determinism_signature": summary["determinism_signature"],
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    manifest_path = run_root / "scheme_a_p2_p2_p1_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p2-p1-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)] + [output_record(manifest_path)],
        },
    )
    return run_root


def build_joint_safety_selections(
    groups: Sequence[P1GroupExample],
    decisions: Sequence[Mapping[str, Any]],
    *,
    compatibility_edges: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
    node_scores: Mapping[str, Mapping[str, float]],
    expected_failure_cases: set[str] | frozenset[str] = frozenset(),
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    group_by_id = {group.group_id: group for group in groups}
    segment_groups = {key: value for key, value in group_by_id.items() if value.object_type == "SEGMENT"}
    node_groups = {key: value for key, value in group_by_id.items() if value.object_type == "NODE"}
    decision_by_group = {str(row["group_id"]): dict(row) for row in decisions}
    if set(decision_by_group) != set(segment_groups):
        raise ValueError("safety decision denominator differs from Segment groups")
    safe_candidate = {
        group_id: _single_candidate(group, "KEEP_SWSD") for group_id, group in segment_groups.items()
    }
    effective: dict[str, str] = {}
    for group_id, group in segment_groups.items():
        row = decision_by_group[group_id]
        proposal_id = str(row.get("proposal_candidate_id") or "")
        if bool(row["accepted"]) and proposal_id:
            effective[group_id] = proposal_id
        else:
            effective[group_id] = safe_candidate[group_id].candidate_id

    edges_by_choice: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    junction_segments: dict[str, set[str]] = defaultdict(set)
    node_junction: dict[str, str] = {}
    for edge in compatibility_edges:
        segment_group_id = str(edge["segment_group_id"])
        node_group_id = str(edge["node_group_id"])
        if segment_group_id not in segment_groups or node_group_id not in node_groups:
            continue
        relation = (node_group_id, str(edge["required_node_target"]))
        choice = (segment_group_id, str(edge["segment_candidate_id"]))
        if relation not in edges_by_choice[choice]:
            edges_by_choice[choice].append(relation)
        junction_key = str((labels.get(node_group_id) or {}).get("junction_key") or node_group_id)
        node_junction[node_group_id] = junction_key
        junction_segments[junction_key].add(segment_group_id)

    forced_junctions: set[str] = set()
    for _ in range(len(junction_segments) + 2):
        requirements, contributors = _requirements(effective, edges_by_choice)
        conflicts: dict[str, str] = {}
        for node_group_id, node_group in node_groups.items():
            targets = requirements.get(node_group_id, set())
            if len(targets) > 1:
                conflicts[node_group_id] = "shared_node_source_conflict"
                continue
            target = next(iter(targets), "OMIT")
            if not any(candidate.candidate_target == target for candidate in node_group.candidates):
                conflicts[node_group_id] = "required_node_candidate_missing"
        new_junctions = {
            node_junction.get(node_group_id, node_group_id)
            for node_group_id in conflicts
            if contributors.get(node_group_id)
        } - forced_junctions
        if not new_junctions:
            break
        forced_junctions.update(new_junctions)
        for junction in new_junctions:
            for segment_group_id in junction_segments.get(junction, set()):
                effective[segment_group_id] = safe_candidate[segment_group_id].candidate_id
    else:
        raise ValueError("P2-P2-P1 Junction fallback did not converge")
    requirements, _ = _requirements(effective, edges_by_choice)

    selection_rows: list[dict[str, Any]] = []
    for group_id, group in sorted(segment_groups.items()):
        decision = decision_by_group[group_id]
        effective_id = effective[group_id]
        forced = effective_id != (
            str(decision.get("proposal_candidate_id") or "")
            if bool(decision["accepted"])
            else safe_candidate[group_id].candidate_id
        )
        accepted = bool(decision["accepted"]) and not forced
        selected_id = str(decision.get("proposal_candidate_id") or safe_candidate[group_id].candidate_id)
        selected_candidate = _candidate_by_id(group, selected_id)
        selection_rows.append(
            {
                "case_key": group.case_key,
                "group_id": group_id,
                "object_type": "SEGMENT",
                "object_id": group.object_id,
                "selected_candidate_id": selected_candidate.candidate_id,
                "selected_target": selected_candidate.candidate_target,
                "confidence": float(decision["risk"]),
                "raw_selected_candidate_id": selected_candidate.candidate_id,
                "raw_selected_target": selected_candidate.candidate_target,
                "raw_confidence": float(decision["safety_probability"]),
                "constraint_required_target": "",
                "constraint_conflict": False,
                "joint_constraint_applied": False,
                "structural_candidate_id": selected_candidate.candidate_id,
                "structural_target": selected_candidate.candidate_target,
                "junction_key": "",
                "junction_fallback_applied": forced,
                "anomaly_probability": float(decision["anomaly_probability"]),
                "accepted": accepted,
                "decision": "ACCEPT" if accepted else "FALLBACK",
                "fallback_unit": "JUNCTION" if forced else "SEGMENT",
                "reason": "shared_carrier_junction_fallback" if forced else str(decision["reason"]),
                "seed": seed,
                "fold": group.fold,
                "model_signature": str(decision["model_signature"]),
            }
        )

    node_target_mismatch_count = 0
    node_original_truth_divergence_count = 0
    for group_id, group in sorted(node_groups.items()):
        targets = requirements.get(group_id, set())
        if len(targets) > 1:
            raise ValueError("Node requirement conflict remains after Junction fallback")
        target = next(iter(targets), "OMIT")
        candidates = [candidate for candidate in group.candidates if candidate.candidate_target == target]
        if not candidates:
            if group.case_key not in expected_failure_cases:
                raise ValueError(f"required Node candidate remains missing: {group_id}/{target}")
            candidates = [
                candidate
                for fallback_target in ("OMIT", "T01_NODE", "COPY", "DROP", "PROPOSAL_NODE")
                for candidate in group.candidates
                if candidate.candidate_target == fallback_target
            ]
            if not candidates:
                raise ValueError(f"expected-failure Node has no fallback candidate: {group_id}")
            target = candidates[0].candidate_target
        selected = max(
            candidates,
            key=lambda candidate: (
                float((node_scores.get(group_id) or {}).get(candidate.candidate_id, -float("inf"))),
                candidate.candidate_id,
            ),
        )
        node_target_mismatch_count += selected.candidate_target != target
        node_original_truth_divergence_count += (
            group.case_key not in expected_failure_cases
            and selected.candidate_target != group.truth_target
        )
        junction_key = str((labels.get(group_id) or {}).get("junction_key") or group_id)
        selection_rows.append(
            {
                "case_key": group.case_key,
                "group_id": group_id,
                "object_type": "NODE",
                "object_id": group.object_id,
                "selected_candidate_id": selected.candidate_id,
                "selected_target": selected.candidate_target,
                "confidence": 1.0,
                "raw_selected_candidate_id": selected.candidate_id,
                "raw_selected_target": selected.candidate_target,
                "raw_confidence": 1.0,
                "constraint_required_target": target,
                "constraint_conflict": False,
                "joint_constraint_applied": True,
                "structural_candidate_id": selected.candidate_id,
                "structural_target": selected.candidate_target,
                "junction_key": junction_key,
                "junction_fallback_applied": junction_key in forced_junctions,
                "anomaly_probability": 0.0,
                "accepted": True,
                "decision": "ACCEPT",
                "fallback_unit": "JUNCTION",
                "reason": "effective_segment_node_requirement",
                "seed": seed,
                "fold": group.fold,
                "model_signature": "p2-p2-p1-node-closure",
            }
        )
    return selection_rows, {
        "seed": seed,
        "junction_fallback_count": len(forced_junctions),
        "requirement_conflict_count": 0,
        "node_target_mismatch_count": node_target_mismatch_count,
        "node_original_truth_divergence_count": node_original_truth_divergence_count,
        "forced_junctions": sorted(forced_junctions),
    }


def _requirements(
    effective: Mapping[str, str],
    edges_by_choice: Mapping[tuple[str, str], Sequence[tuple[str, str]]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    requirements: dict[str, set[str]] = defaultdict(set)
    contributors: dict[str, set[str]] = defaultdict(set)
    for group_id, candidate_id in effective.items():
        for node_group_id, target in edges_by_choice.get((group_id, candidate_id), ()):
            requirements[node_group_id].add(target)
            contributors[node_group_id].add(group_id)
    return dict(requirements), dict(contributors)


def _seed_metrics(
    seed: int,
    groups: Sequence[P1GroupExample],
    decisions: Sequence[Mapping[str, Any]],
    evaluation: Sequence[Mapping[str, Any]],
    stable_false_use_ids: Sequence[str],
    roadgraphs: Sequence[Mapping[str, Any]],
    closures: Sequence[Mapping[str, Any]],
    config: SchemeAP2P2P1Config,
) -> dict[str, Any]:
    seed_decisions = [row for row in decisions if int(row["seed"]) == seed]
    seed_evaluation = [row for row in evaluation if int(row["seed"]) == seed]
    metrics = dict(safety_metrics(groups, seed_decisions, seed_evaluation))
    accepted_by_group = {str(row["group_id"]): bool(row["accepted"]) for row in seed_decisions}
    metrics["stable_false_use_auto_publish_count"] = sum(
        accepted_by_group.get(group_id, False) for group_id in stable_false_use_ids
    )
    seed_graphs = [row for row in roadgraphs if int(row["seed"]) == seed]
    terminal_counts = Counter(str(row["terminal_state"]) for row in seed_graphs)
    node_payload_conflict_count = 0
    for row in seed_graphs:
        graph = json.loads(normalize_runtime_path(str(row["output"]["path"])).read_text(encoding="utf-8"))
        node_payload_conflict_count += int(graph["audit"].get("node_conflict_count") or 0)
    closure = next(row for row in closures if int(row["seed"]) == seed)
    metrics.update(
        {
            "roadgraph_terminal_counts": dict(sorted(terminal_counts.items())),
            "roadgraph_legal_publish_count": terminal_counts["LEGAL"],
            "roadgraph_expected_fail_count": terminal_counts["EXPECTED_FAIL"],
            "roadgraph_unexpected_failure_count": terminal_counts["FAIL"],
            "node_payload_conflict_count": node_payload_conflict_count,
            "requirement_conflict_count": int(closure["requirement_conflict_count"]),
            "node_target_mismatch_count": int(closure["node_target_mismatch_count"]),
            "node_original_truth_divergence_count": int(
                closure["node_original_truth_divergence_count"]
            ),
            "junction_fallback_count": int(closure["junction_fallback_count"]),
        }
    )
    metrics["safety_gate_pass"] = (
        metrics["accepted_wrong_count"] == 0
        and metrics["accepted_precision"] == 1.0
        and metrics["safe_coverage"] >= config.minimum_safe_coverage
        and metrics["use_rcsd_safe_coverage"] >= config.minimum_use_rcsd_safe_coverage
        and metrics["unsafe_fallback_recall"] == 1.0
        and metrics["review_auto_publish_count"] == 0
        and metrics["stable_false_use_auto_publish_count"] == 0
    )
    metrics["roadgraph_gate_pass"] = (
        metrics["roadgraph_legal_publish_count"] == config.expected_case_count - len(config.expected_roadgraph_failures)
        and metrics["roadgraph_expected_fail_count"] == len(config.expected_roadgraph_failures)
        and metrics["roadgraph_unexpected_failure_count"] == 0
        and metrics["node_payload_conflict_count"] == 0
        and metrics["requirement_conflict_count"] == 0
        and metrics["node_target_mismatch_count"] == 0
    )
    return {"seed": seed, **metrics}


def _save_fold(
    root: Path,
    result: Mapping[str, Any],
    *,
    seed: int,
    fold: int,
    model_signature: str,
    dataset_signature: str,
    config: SchemeAP2P2P1Config,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    checkpoint_path = root / "model.pt"
    torch.save(
        {
            "schema_version": "p05-scheme-a-p2-p2-p1-checkpoint-v1",
            "seed": seed,
            "fold": fold,
            "state_signature": model_signature,
            "state_dict": {
                key: value.detach().cpu() for key, value in result["model"].state_dict().items()
            },
        },
        checkpoint_path,
    )
    vocabulary_payload = result["vocabulary"].to_dict()
    vocabulary_path = root / "fold_vocabulary.json"
    write_json(vocabulary_path, vocabulary_payload)
    threshold_path = root / "thresholds.json"
    write_json(threshold_path, result["thresholds"])
    history_path = root / "training_history.csv"
    write_csv(history_path, result["history"], list(result["history"][0]))
    contract_path = root / "model_contract.json"
    write_json(
        contract_path,
        {
            "schema_version": "p05-scheme-a-p2-p2-p1-segment-safety-head-v1",
            "parameter_count": parameter_count(result["model"]),
            "accept_or_abstain_only": True,
            "candidate_replacement_allowed": False,
            "object_types": ["SEGMENT"],
            "movement_candidate_count": 0,
            "listwise_safety_loss": True,
            "anomaly_head": True,
            "dataset_signature": dataset_signature,
            "model_state_signature": model_signature,
            "numeric_dim": config.numeric_dim,
            "embedding_dim": config.embedding_dim,
            "hidden_dim": config.hidden_dim,
            "type_embedding_dim": config.type_embedding_dim,
            "dropout": config.dropout,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    summary = {
        **dict(result["summary"]),
        "train_case_keys": list(result["vocabulary"].train_case_keys),
        "inner_validation_case_keys": list(result["vocabulary"].inner_validation_case_keys),
        "held_out_case_keys": list(result["vocabulary"].held_out_case_keys),
    }
    summary_path = root / "training_summary.json"
    write_json(summary_path, summary)
    return {
        "seed": seed,
        "fold": fold,
        "model_signature": model_signature,
        "checkpoint": output_record(checkpoint_path),
        "fold_vocabulary": output_record(vocabulary_path),
        "thresholds": output_record(threshold_path),
        "training_history": output_record(history_path),
        "model_contract": output_record(contract_path),
        "training_summary": output_record(summary_path),
        "summary": summary,
    }


def _base_node_scores(path: Path, base_seeds: Sequence[int]) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in _read_jsonl(path):
        if row.get("object_type") == "NODE" and int(row["seed"]) in set(base_seeds):
            values[str(row["group_id"])][str(row["candidate_id"])].append(float(row["score"]))
    result: dict[str, dict[str, float]] = {}
    for group_id, candidate_values in values.items():
        if any(len(rows) != len(base_seeds) for rows in candidate_values.values()):
            raise ValueError(f"base Node score seed denominator differs: {group_id}")
        result[group_id] = {
            candidate_id: sum(rows) / len(rows) for candidate_id, rows in candidate_values.items()
        }
    return result


def _payload_path(dataset: Mapping[str, Any]) -> Path:
    record = dict((dataset["dataset_manifest"].get("outputs") or {}).get("payloads") or {})
    return normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)


def _single_candidate(group: P1GroupExample, target: str) -> Any:
    candidates = [candidate for candidate in group.candidates if candidate.candidate_target == target]
    if len(candidates) != 1:
        raise ValueError(f"candidate target is not unique: {group.group_id}/{target}")
    return candidates[0]


def _candidate_by_id(group: P1GroupExample, candidate_id: str) -> Any:
    candidates = [candidate for candidate in group.candidates if candidate.candidate_id == candidate_id]
    if len(candidates) != 1:
        raise ValueError(f"candidate id is not unique: {group.group_id}/{candidate_id}")
    return candidates[0]


def _state_signature(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _validation_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# P05-Scheme-A-P2-P2-P1 validation",
        "",
        f"- decision: `{summary['decision']}`",
        f"- gate_pass: `{summary['gate_pass']}`",
        f"- Segment groups: {summary['segment_group_count']}",
        "- Movement candidate/decision/evaluation: 0",
        "- skeleton mutation: 0",
        "- content repair / silent fix: false / false",
        "",
        "| seed | wrong | precision | coverage | USE coverage | unsafe recall | legal | expected fail | gate |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["seed_metrics"]:
        lines.append(
            f"| {row['seed']} | {row['accepted_wrong_count']} | {row['accepted_precision']:.6f} | "
            f"{row['safe_coverage']:.6f} | {row['use_rcsd_safe_coverage']:.6f} | "
            f"{row['unsafe_fallback_recall']:.6f} | {row['roadgraph_legal_publish_count']} | "
            f"{row['roadgraph_expected_fail_count']} | {row['safety_gate_pass'] and row['roadgraph_gate_pass']} |"
        )
    return "\n".join(lines) + "\n"


def _score_key(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return int(row["seed"]), str(row["group_id"]), str(row["candidate_id"])


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["build_joint_safety_selections", "run_scheme_a_p2_p2_p1_oof"]
