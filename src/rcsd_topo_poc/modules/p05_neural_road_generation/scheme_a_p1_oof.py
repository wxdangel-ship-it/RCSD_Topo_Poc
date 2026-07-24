from __future__ import annotations

import csv
import gc
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

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
    expand_movement_fallback_closure,
    fallback_case_to_swsd,
    fallback_conflicting_groups_to_swsd,
    materialize_case_roadgraph,
    select_effective_candidate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SchemeAP1OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    model_contract,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1EncodedGroup,
    P1GroupExample,
    load_scheme_a_p1_groups,
    score_encoded_groups,
    train_scheme_a_p1_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


RAM_LIMIT_BYTES = 16 * 1024**3
VRAM_LIMIT_BYTES = 8 * 1024**3


def run_scheme_a_p1_oof(config: SchemeAP1OOFConfig) -> Path:
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    groups, dataset_contract = load_scheme_a_p1_groups(
        config.dataset_run_root, strict_hashes=config.strict_hashes
    )
    candidate_contract = _load_candidate_contract(config, dataset_contract)
    case_folds = _case_folds(groups, config)
    expected_failure_manifest = _expected_failure_manifest(config)
    if not set(expected_failure_manifest) <= set(case_folds):
        raise ValueError("expected RoadGraph failure is outside the 51-Case scope")
    candidates_by_group, candidates_by_id = _load_candidates(
        candidate_contract["candidate_path"]
    )
    if set(candidates_by_group) != {group.group_id for group in groups}:
        raise ValueError("OOF candidate/group scope differs from dataset")
    lineage_by_case = _load_lineage(candidate_contract["lineage_path"])
    rss_samples = [_rss_bytes()]
    seed_summaries: list[dict[str, Any]] = []
    baseline_summaries: list[dict[str, Any]] = []
    all_fold_artifacts: list[dict[str, Any]] = []
    total_training_seconds = 0.0
    max_vram_bytes = 0
    score_seconds_by_case: Counter[str] = Counter()
    for seed in config.seeds:
        seed_started = time.perf_counter()
        predictions: list[dict[str, Any]] = []
        fold_artifacts: list[dict[str, Any]] = []
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        for fold in range(config.expected_fold_count):
            result = train_scheme_a_p1_fold(
                groups,
                case_folds=case_folds,
                held_out_fold=fold,
                seed=seed,
                dataset_manifest_sha256=dataset_contract["dataset_manifest_sha256"],
                config=config,
            )
            total_training_seconds += float(result["summary"]["training_wall_seconds"])
            artifact = _save_fold_artifacts(
                run_root / "checkpoints" / str(seed) / str(fold),
                run_root / "scores" / str(seed) / f"{fold}.jsonl",
                seed=seed,
                fold=fold,
                result=result,
                dataset_manifest_sha256=dataset_contract["dataset_manifest_sha256"],
                config=config,
            )
            fold_artifacts.append(artifact)
            all_fold_artifacts.append(artifact)
            held_groups: Sequence[P1GroupExample] = result["held_out_groups"]
            scores: Sequence[Sequence[float]] = result["held_out_scores"]
            probabilities: Sequence[Sequence[float]] = result["held_out_probabilities"]
            anomalies: Sequence[float] = result["held_out_anomaly_probabilities"]
            thresholds = result["thresholds"]
            for group, group_scores, group_probabilities, anomaly_probability in zip(
                held_groups, scores, probabilities, anomalies, strict=True
            ):
                selected_index = max(
                    range(len(group_scores)),
                    key=lambda index: (
                        float(group_scores[index]),
                        group.candidates[index].candidate_id,
                    ),
                )
                selected_id = group.candidates[selected_index].candidate_id
                decision = select_effective_candidate(
                    candidates_by_group[group.group_id],
                    selected_candidate_id=selected_id,
                    confidence=float(group_probabilities[selected_index]),
                    anomaly_probability=float(anomaly_probability),
                    confidence_threshold=float(thresholds["confidence_threshold"]),
                    anomaly_threshold=float(thresholds["anomaly_threshold"]),
                    hard_unsafe=group.hard_unsafe,
                )
                predictions.append(
                    {
                        "schema_version": "p05-scheme-a-p1-prediction-v1",
                        "seed": seed,
                        "fold": fold,
                        "case_key": group.case_key,
                        "group_id": group.group_id,
                        "object_type": group.object_type,
                        "object_id": group.object_id,
                        "confidence": float(group_probabilities[selected_index]),
                        "uncertainty": 1.0 - float(group_probabilities[selected_index]),
                        "anomaly_probability": float(anomaly_probability),
                        "anomaly_threshold": float(thresholds["anomaly_threshold"]),
                        "confidence_threshold": float(thresholds["confidence_threshold"]),
                        "hard_unsafe": group.hard_unsafe,
                        "model_state_signature": artifact["model_state_signature"],
                        **decision,
                        "label_only": False,
                        "content_repair": False,
                        "silent_fix": False,
                    }
                )
            _measure_case_scoring(
                result,
                score_seconds_by_case,
                batch_group_count=config.batch_group_count,
            )
            rss_samples.append(_rss_bytes())
            if torch.cuda.is_available():
                max_vram_bytes = max(
                    max_vram_bytes, int(torch.cuda.max_memory_allocated())
                )
            del result
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        predictions = _expand_by_case(predictions, candidates_by_group)
        roadgraph_records, predictions = _materialize_seed(
            run_root,
            seed,
            predictions,
            candidates_by_group,
            candidates_by_id,
            lineage_by_case,
            expected_failure_manifest,
        )
        prediction_path = run_root / "predictions" / f"{seed}.jsonl"
        _write_jsonl(prediction_path, predictions)
        fallback_path = run_root / "fallbacks" / f"{seed}.jsonl"
        _write_jsonl(
            fallback_path,
            [row for row in predictions if row["decision"] != "PUBLISH_CANDIDATE"],
        )
        metrics = _seed_metrics(groups, predictions, roadgraph_records)
        metrics["seed_wall_seconds"] = time.perf_counter() - seed_started
        metrics_path = run_root / "metrics" / f"{seed}.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(metrics_path, metrics)
        baseline = _run_non_neural_baseline(
            groups, case_folds, candidates_by_group
        )
        baseline_summaries.append({"seed": seed, **baseline})
        seed_summary = {
            "seed": seed,
            **metrics,
            "prediction": output_record(prediction_path),
            "fallback": output_record(fallback_path),
            "metrics": output_record(metrics_path),
            "folds": fold_artifacts,
        }
        seed_summaries.append(seed_summary)
    non_neural_path = run_root / "non_neural_baselines.json"
    write_json(non_neural_path, {"baselines": baseline_summaries})
    resource_audit = _resource_audit(
        config,
        seed_summaries,
        all_fold_artifacts,
        rss_samples,
        max_vram_bytes,
        score_seconds_by_case,
        total_training_seconds,
    )
    resource_path = run_root / "resource_audit.json"
    write_json(resource_path, resource_audit)
    summary = _oof_summary(config, seed_summaries, baseline_summaries, resource_audit)
    summary_path = run_root / "scheme_a_p1_oof_summary.json"
    write_json(summary_path, summary)
    validation_path = run_root / "validation_report.md"
    validation_path.write_text(_validation_report(summary), encoding="utf-8", newline="\n")
    determinism_path = run_root / "determinism_audit.json"
    write_json(
        determinism_path,
        {
            "schema_version": "p05-scheme-a-p1-determinism-audit-v1",
            "same_seed_replay_completed": False,
            "status": "PENDING_SEPARATE_REPLAY",
        },
    )
    artifact_path = run_root / "artifact_manifest.json"
    _write_artifact_manifest(run_root, artifact_path)
    manifest = {
        "schema_version": "p05-scheme-a-p1-oof-manifest-v1",
        "run_id": config.run_id,
        "module_id": "p05_neural_road_generation",
        "status": "completed",
        "decision": summary["decision"],
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": time.perf_counter() - started,
        "seeds": config.seeds,
        "fold_count": config.expected_fold_count,
        "case_count": config.expected_case_count,
        "expected_roadgraph_failures": [list(row) for row in config.expected_roadgraph_failures],
        "input_manifests": {
            "dataset": output_record(dataset_contract["dataset_manifest_path"]),
            "candidate": output_record(candidate_contract["candidate_manifest_path"]),
        },
        "outputs": {
            "summary": output_record(summary_path),
            "non_neural_baselines": output_record(non_neural_path),
            "resource_audit": output_record(resource_path),
            "determinism_audit": output_record(determinism_path),
            "validation_report": output_record(validation_path),
            "artifact_manifest": output_record(artifact_path),
        },
        "environment": _environment(),
        "skeleton_mutation_count": 0,
        "truth_feature_count": 0,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(run_root / "scheme_a_p1_oof_manifest.json", manifest)
    return run_root


def _load_candidate_contract(
    config: SchemeAP1OOFConfig, dataset_contract: Mapping[str, Any]
) -> dict[str, Any]:
    root = normalize_runtime_path(config.candidate_run_root).resolve(strict=True)
    manifest_path = root / "scheme_a_p1_candidate_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "candidate_scope_passed":
        raise ValueError("P1 candidate run did not pass")
    dataset_candidate = dict(
        dataset_contract["dataset_manifest"].get("input_manifests", {}).get("candidate")
        or {}
    )
    if config.strict_hashes and dataset_candidate.get("sha256") != sha256_file(manifest_path):
        raise ValueError("P1 dataset/candidate manifest mismatch")
    outputs = dict(manifest.get("outputs") or {})
    return {
        "candidate_manifest_path": manifest_path,
        "candidate_manifest": manifest,
        "candidate_path": _verified_output(outputs, "candidates", config.strict_hashes),
        "lineage_path": _verified_output(outputs, "lineage", config.strict_hashes),
    }


def _load_candidates(
    path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        candidate_id = str(row["candidate_id"])
        if candidate_id in by_id:
            raise ValueError(f"duplicate P1 candidate ID: {candidate_id}")
        by_id[candidate_id] = row
        by_group[str(row["group_id"])].append(row)
    for rows in by_group.values():
        rows.sort(key=lambda row: str(row["candidate_id"]))
    return dict(by_group), by_id


def _load_lineage(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("label_only") or "").lower() == "true":
                continue
            result[str(row["case_key"])][str(row["role"])] = str(row["path"])
    return dict(result)


def _case_folds(
    groups: Sequence[P1GroupExample], config: SchemeAP1OOFConfig
) -> dict[str, int]:
    values: dict[str, set[int]] = defaultdict(set)
    for group in groups:
        values[group.case_key].add(group.fold)
    if any(len(folds) != 1 for folds in values.values()):
        raise ValueError("one Case appears in multiple folds")
    result = {key: next(iter(folds)) for key, folds in values.items()}
    if len(result) != config.expected_case_count or set(result.values()) != set(
        range(config.expected_fold_count)
    ):
        raise ValueError("P1 OOF Case/fold denominator mismatch")
    return result


def _expected_failure_manifest(
    config: SchemeAP1OOFConfig,
) -> dict[str, frozenset[str]]:
    return {
        case_key: frozenset(
            {
                f"Road endpoint Node missing: {node_id}",
                f"directed edge endpoint missing: {directed_edge}",
            }
        )
        for case_key, node_id, directed_edge in config.expected_roadgraph_failures
    }


def _save_fold_artifacts(
    root: Path,
    score_path: Path,
    *,
    seed: int,
    fold: int,
    result: Mapping[str, Any],
    dataset_manifest_sha256: str,
    config: SchemeAP1OOFConfig,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    score_path.parent.mkdir(parents=True, exist_ok=True)
    model = result["model"]
    state_signature = _state_signature(model)
    checkpoint_path = root / "model.pt"
    torch.save(
        {
            "schema_version": "p05-scheme-a-p1-checkpoint-v1",
            "seed": seed,
            "fold": fold,
            "state_signature": state_signature,
            "state_dict": {
                key: value.detach().cpu() for key, value in model.state_dict().items()
            },
        },
        checkpoint_path,
    )
    vocabulary = result["vocabulary"].to_dict()
    vocabulary_path = root / "fold_vocabulary.json"
    write_json(vocabulary_path, vocabulary)
    history_path = root / "training_history.csv"
    history = list(result["history"])
    write_csv(history_path, history, list(history[0]))
    threshold_path = root / "thresholds.json"
    write_json(threshold_path, result["thresholds"])
    training_path = root / "training_summary.json"
    training_summary = dict(result["summary"])
    training_summary["model_state_signature"] = state_signature
    write_json(training_path, training_summary)
    contract_path = root / "model_contract.json"
    write_json(
        contract_path,
        model_contract(
            model,
            seed=seed,
            fold=fold,
            dataset_manifest_sha256=dataset_manifest_sha256,
            checkpoint_sha256=sha256_file(checkpoint_path),
            model_state_signature=state_signature,
            vocabulary_signature=vocabulary["vocabulary_signature"],
            numeric_dim=config.numeric_dim,
            embedding_dim=config.embedding_dim,
            hidden_dim=config.hidden_dim,
            type_embedding_dim=config.type_embedding_dim,
            dropout=config.dropout,
        ),
    )
    score_rows: list[dict[str, Any]] = []
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        result["held_out_groups"],
        result["held_out_scores"],
        result["held_out_probabilities"],
        result["held_out_anomaly_probabilities"],
        strict=True,
    ):
        for candidate, score, probability in zip(
            group.candidates, group_scores, group_probabilities, strict=True
        ):
            score_rows.append(
                {
                    "schema_version": "p05-scheme-a-p1-score-v1",
                    "seed": seed,
                    "fold": fold,
                    "case_key": group.case_key,
                    "group_id": group.group_id,
                    "object_type": group.object_type,
                    "object_id": group.object_id,
                    "candidate_id": candidate.candidate_id,
                    "score": float(score),
                    "cost": -float(score),
                    "probability": float(probability),
                    "anomaly_probability": float(anomaly_probability),
                    "model_state_signature": state_signature,
                    "label_only": False,
                }
            )
    _write_jsonl(score_path, score_rows)
    return {
        "seed": seed,
        "fold": fold,
        "model_state_signature": state_signature,
        "checkpoint": output_record(checkpoint_path),
        "model_contract": output_record(contract_path),
        "fold_vocabulary": output_record(vocabulary_path),
        "thresholds": output_record(threshold_path),
        "training_history": output_record(history_path),
        "training_summary": output_record(training_path),
        "scores": output_record(score_path),
        "summary": training_summary,
    }


def _measure_case_scoring(
    result: Mapping[str, Any],
    target: Counter[str],
    *,
    batch_group_count: int,
) -> None:
    groups: Sequence[P1GroupExample] = result["held_out_groups"]
    encoded: Sequence[P1EncodedGroup] = result["held_out_encoded"]
    for case_key in sorted({group.case_key for group in groups}):
        indices = [index for index, group in enumerate(groups) if group.case_key == case_key]
        started = time.perf_counter()
        score_encoded_groups(
            result["model"],
            [encoded[index] for index in indices],
            batch_group_count=batch_group_count,
            device=result["device"],
        )
        target[case_key] += time.perf_counter() - started


def _expand_by_case(
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in predictions:
        by_case[str(row["case_key"])].append(row)
    output: list[dict[str, Any]] = []
    for case_key in sorted(by_case):
        output.extend(
            expand_movement_fallback_closure(by_case[case_key], candidates_by_group)
        )
    return sorted(output, key=lambda row: str(row["group_id"]))


def _materialize_seed(
    run_root: Path,
    seed: int,
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
    candidates_by_id: Mapping[str, Mapping[str, Any]],
    lineage_by_case: Mapping[str, Mapping[str, str]],
    expected_failure_manifest: Mapping[str, frozenset[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in predictions:
        by_case[str(row["case_key"])].append(row)
    records: list[dict[str, Any]] = []
    updated_predictions: list[dict[str, Any]] = []
    for case_key in sorted(by_case):
        case_predictions = [dict(row) for row in by_case[case_key]]
        vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
        payload_signature_cache: dict[int, str] = {}
        expected_failures = expected_failure_manifest.get(case_key)
        hard_gate_iterations: list[dict[str, Any]] = []
        if expected_failures is not None:
            case_predictions = fallback_case_to_swsd(
                case_predictions,
                candidates_by_group,
                reason="expected_swsd_baseline_failure",
            )
        roadgraph = materialize_case_roadgraph(
            case_key,
            case_predictions,
            candidates_by_id,
            lineage_by_case[case_key],
            vector_cache=vector_cache,
            payload_signature_cache=payload_signature_cache,
        )
        initial_failures = list(roadgraph["audit"]["failures"])
        initial_signature = roadgraph["roadgraph_signature"]
        if expected_failures is None:
            for iteration in range(len(case_predictions) + 1):
                if roadgraph["audit"]["legal"]:
                    break
                failure_group_ids = list(roadgraph["audit"]["failure_group_ids"])
                if not failure_group_ids:
                    break
                case_predictions, changed_count = fallback_conflicting_groups_to_swsd(
                    case_predictions,
                    candidates_by_group,
                    failure_group_ids,
                    reason="roadgraph_hard_gate_conflict",
                )
                hard_gate_iterations.append(
                    {
                        "iteration": iteration + 1,
                        "failure_count": int(roadgraph["audit"]["failure_count"]),
                        "failure_group_count": len(failure_group_ids),
                        "changed_group_count": changed_count,
                        "roadgraph_signature": roadgraph["roadgraph_signature"],
                    }
                )
                if changed_count == 0:
                    break
                roadgraph = materialize_case_roadgraph(
                    case_key,
                    case_predictions,
                    candidates_by_id,
                    lineage_by_case[case_key],
                    vector_cache=vector_cache,
                    payload_signature_cache=payload_signature_cache,
                )
        actual_failures = frozenset(str(value) for value in roadgraph["audit"]["failures"])
        if expected_failures is not None:
            expected_failure_match = actual_failures == expected_failures
            terminal_state = "EXPECTED_FAIL" if expected_failure_match else "FAIL"
        else:
            expected_failure_match = False
            terminal_state = "LEGAL" if roadgraph["audit"]["legal"] else "FAIL"
        roadgraph["audit"]["terminal_state"] = terminal_state
        roadgraph["audit"]["publish"] = terminal_state == "LEGAL"
        roadgraph["audit"]["expected_failure_match"] = expected_failure_match
        roadgraph["audit"]["hard_gate_fallback_applied"] = bool(
            hard_gate_iterations or expected_failures is not None
        )
        roadgraph["audit"]["hard_gate_iterations"] = hard_gate_iterations
        if hard_gate_iterations or expected_failures is not None:
            roadgraph["audit"]["pre_fallback_failure_count"] = len(initial_failures)
            roadgraph["audit"]["pre_fallback_failures"] = initial_failures
            roadgraph["audit"]["pre_fallback_roadgraph_signature"] = initial_signature
        roadgraph.pop("roadgraph_signature", None)
        roadgraph["roadgraph_signature"] = canonical_sha256(roadgraph)
        updated_predictions.extend(case_predictions)
        case_token = canonical_sha256({"case_key": case_key})[:20]
        path = run_root / "cases" / str(seed) / case_token / "roadgraph.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, roadgraph)
        records.append(
            {
                "case_key": case_key,
                "legal": bool(roadgraph["audit"]["legal"]),
                "terminal_state": terminal_state,
                "publish": bool(roadgraph["audit"]["publish"]),
                "expected_failure_match": expected_failure_match,
                "failure_count": int(roadgraph["audit"]["failure_count"]),
                "roadgraph_signature": roadgraph["roadgraph_signature"],
                "output": output_record(path),
            }
        )
    return records, sorted(updated_predictions, key=lambda row: str(row["group_id"]))


def _seed_metrics(
    groups: Sequence[P1GroupExample],
    predictions: Sequence[Mapping[str, Any]],
    roadgraphs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    group_by_id = {group.group_id: group for group in groups}
    prediction_by_id = {str(row["group_id"]): row for row in predictions}
    if set(group_by_id) != set(prediction_by_id):
        raise ValueError("P1 prediction denominator differs")
    segment_truth: list[str] = []
    segment_predicted: list[str] = []
    use_tp = use_fp = 0
    anomaly_tp = anomaly_fp = anomaly_fn = 0
    fallback_tp = fallback_fn = 0
    movement_correct = movement_count = 0
    accepted = 0
    unsafe_advance_published = 0
    junction_conflict_wrong_replace = 0
    mixed_correct = mixed_count = 0
    decision_counts: Counter[str] = Counter()
    for group_id, group in group_by_id.items():
        row = prediction_by_id[group_id]
        selected_candidate = next(
            candidate
            for candidate in group.candidates
            if candidate.candidate_id == str(row["selected_candidate_id"])
        )
        predicted_target = selected_candidate.candidate_target
        predicted_anomaly = bool(row["hard_unsafe"]) or float(
            row["anomaly_probability"]
        ) >= float(row["anomaly_threshold"])
        anomaly_tp += predicted_anomaly and group.anomaly_target
        anomaly_fp += predicted_anomaly and not group.anomaly_target
        anomaly_fn += (not predicted_anomaly) and group.anomaly_target
        is_fallback = row["decision"] != "PUBLISH_CANDIDATE"
        fallback_tp += is_fallback and group.anomaly_target
        fallback_fn += (not is_fallback) and group.anomaly_target
        accepted += not is_fallback
        decision_counts[str(row["decision"])] += 1
        if group.object_type == "SEGMENT":
            if group.truth_target == "MIXED_CARRIER":
                mixed_count += 1
                mixed_correct += str(row["selected_candidate_id"]) == group.candidates[
                    group.truth_index
                ].candidate_id
            else:
                segment_truth.append(group.truth_target)
                segment_predicted.append(predicted_target)
            use_tp += predicted_target == "USE_RCSD" and group.truth_target == "USE_RCSD"
            use_fp += predicted_target == "USE_RCSD" and group.truth_target != "USE_RCSD"
            tokens = set(group.object_tokens)
            unsafe_advance_published += (
                "SEGMENT_TYPE:ADVANCE_RIGHT" in tokens
                and "ACCESS_VALID:False" in tokens
                and row["decision"] == "PUBLISH_CANDIDATE"
            )
            junction_conflict_wrong_replace += (
                any(
                    token.startswith("PROPOSAL_JUNCTION_CONFLICT_COUNT:")
                    and not token.endswith(":0")
                    for token in tokens
                )
                and str(row["effective_candidate_target"]) != "KEEP_SWSD"
            )
        elif not group.anomaly_target:
            movement_count += 1
            movement_correct += str(row["selected_candidate_id"]) == group.candidates[
                group.truth_index
            ].candidate_id
    macro = _macro_f1(
        segment_truth,
        segment_predicted,
        ("USE_RCSD", "KEEP_SWSD", "REVIEW_FALLBACK"),
    )
    anomaly_precision = anomaly_tp / max(1, anomaly_tp + anomaly_fp)
    anomaly_recall = anomaly_tp / max(1, anomaly_tp + anomaly_fn)
    legal_count = sum(bool(row["legal"]) for row in roadgraphs)
    terminal_counts = Counter(str(row.get("terminal_state") or "FAIL") for row in roadgraphs)
    expected_failure_case_keys = sorted(
        str(row["case_key"])
        for row in roadgraphs
        if row.get("terminal_state") == "EXPECTED_FAIL"
    )
    unexpected_failure_case_keys = sorted(
        str(row["case_key"])
        for row in roadgraphs
        if row.get("terminal_state") == "FAIL"
    )
    return {
        "segment_macro_f1": macro,
        "segment_class_metrics": _class_metrics(segment_truth, segment_predicted),
        "use_rcsd_precision": use_tp / max(1, use_tp + use_fp),
        "unsafe_fallback_recall": fallback_tp / max(1, fallback_tp + fallback_fn),
        "accepted_coverage": accepted / max(1, len(groups)),
        "movement_available_exact": movement_correct / max(1, movement_count),
        "anomaly_precision": anomaly_precision,
        "anomaly_recall": anomaly_recall,
        "mixed_carrier_exact": mixed_correct / max(1, mixed_count),
        "mixed_carrier_count": mixed_count,
        "decision_counts": dict(decision_counts),
        "roadgraph_legal_count": legal_count,
        "roadgraph_case_count": len(roadgraphs),
        "roadgraph_failure_count": sum(int(row["failure_count"]) for row in roadgraphs),
        "roadgraph_expected_failure_count": terminal_counts["EXPECTED_FAIL"],
        "roadgraph_expected_failure_case_keys": expected_failure_case_keys,
        "roadgraph_unexpected_failure_count": terminal_counts["FAIL"],
        "roadgraph_unexpected_failure_case_keys": unexpected_failure_case_keys,
        "roadgraph_terminal_counts": dict(sorted(terminal_counts.items())),
        "unsafe_advance_right_published_count": unsafe_advance_published,
        "junction_conflict_wrong_replace_count": junction_conflict_wrong_replace,
    }


def _run_non_neural_baseline(
    groups: Sequence[P1GroupExample],
    case_folds: Mapping[str, int],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    predictions: list[dict[str, Any]] = []
    for fold in sorted(set(case_folds.values())):
        train = [group for group in groups if group.fold != fold]
        held = [group for group in groups if group.fold == fold]
        trials: Counter[tuple[str, str]] = Counter()
        correct: Counter[tuple[str, str]] = Counter()
        for group in train:
            for index, candidate in enumerate(group.candidates):
                key = group.object_type, candidate.candidate_target
                trials[key] += 1
                correct[key] += index == group.truth_index
        for group in held:
            selected = max(
                range(len(group.candidates)),
                key=lambda index: (
                    correct[(group.object_type, group.candidates[index].candidate_target)]
                    / max(1, trials[(group.object_type, group.candidates[index].candidate_target)]),
                    group.candidates[index].candidate_id,
                ),
            )
            decision = select_effective_candidate(
                candidates_by_group[group.group_id],
                selected_candidate_id=group.candidates[selected].candidate_id,
                confidence=1.0,
                anomaly_probability=1.0 if group.hard_unsafe else 0.0,
                confidence_threshold=0.0,
                anomaly_threshold=0.5,
                hard_unsafe=group.hard_unsafe,
            )
            predictions.append(
                {
                    "case_key": group.case_key,
                    "group_id": group.group_id,
                    "object_type": group.object_type,
                    "object_id": group.object_id,
                    "hard_unsafe": group.hard_unsafe,
                    "anomaly_probability": 1.0 if group.hard_unsafe else 0.0,
                    "anomaly_threshold": 0.5,
                    **decision,
                }
            )
    predictions = _expand_by_case(predictions, candidates_by_group)
    metrics = _seed_metrics(groups, predictions, [])
    return {
        "name": "train_only_candidate_target_frequency",
        "segment_macro_f1": metrics["segment_macro_f1"],
        "use_rcsd_precision": metrics["use_rcsd_precision"],
        "movement_available_exact": metrics["movement_available_exact"],
    }


def _resource_audit(
    config: SchemeAP1OOFConfig,
    seeds: Sequence[Mapping[str, Any]],
    folds: Sequence[Mapping[str, Any]],
    rss_samples: Sequence[int],
    max_vram_bytes: int,
    score_seconds: Mapping[str, float],
    total_training_seconds: float,
) -> dict[str, Any]:
    fold_seconds = [float(row["summary"]["training_wall_seconds"]) for row in folds]
    case_seconds = sorted(float(value) for value in score_seconds.values())
    parameter_counts = [int(row["summary"]["parameter_count"]) for row in folds]
    audit = {
        "schema_version": "p05-scheme-a-p1-resource-audit-v1",
        "parameter_count_min": min(parameter_counts),
        "parameter_count_max": max(parameter_counts),
        "max_rss_bytes": max(rss_samples),
        "max_vram_bytes": max_vram_bytes,
        "max_fold_training_seconds": max(fold_seconds),
        "max_seed_wall_seconds": max(float(row["seed_wall_seconds"]) for row in seeds),
        "total_training_seconds": total_training_seconds,
        "score_case_p95_seconds": _percentile(case_seconds, 0.95),
        "score_case_max_seconds": max(case_seconds),
    }
    audit["passed"] = (
        config.min_parameter_count <= audit["parameter_count_min"]
        and audit["parameter_count_max"] <= config.max_parameter_count
        and audit["max_rss_bytes"] <= RAM_LIMIT_BYTES
        and audit["max_vram_bytes"] <= VRAM_LIMIT_BYTES
        and audit["max_fold_training_seconds"] <= 3600
        and audit["max_seed_wall_seconds"] <= 5 * 3600
        and audit["total_training_seconds"] <= len(config.seeds) * 5 * 3600
        and audit["score_case_p95_seconds"] <= 5.0
        and audit["score_case_max_seconds"] <= 20.0
    )
    return audit


def _oof_summary(
    config: SchemeAP1OOFConfig,
    seeds: Sequence[Mapping[str, Any]],
    baselines: Sequence[Mapping[str, Any]],
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_macro = max(float(row["segment_macro_f1"]) for row in baselines)
    expected_failure_cases = sorted(row[0] for row in config.expected_roadgraph_failures)
    expected_legal_count = config.expected_case_count - len(expected_failure_cases)
    seed_gates: list[dict[str, Any]] = []
    for row in seeds:
        gate1 = (
            row["segment_macro_f1"] >= 0.85
            and row["use_rcsd_precision"] >= 0.95
            and row["unsafe_fallback_recall"] >= 0.98
            and row["accepted_coverage"] >= 0.50
        )
        gate2 = (
            row["movement_available_exact"] >= 0.90
            and row["anomaly_recall"] >= 0.95
            and row["anomaly_precision"] >= 0.80
            and row["segment_macro_f1"] >= baseline_macro + 0.03
        )
        gate4 = (
            row["roadgraph_case_count"] == config.expected_case_count
            and row["roadgraph_legal_count"] == expected_legal_count
            and row["roadgraph_expected_failure_count"] == len(expected_failure_cases)
            and row["roadgraph_expected_failure_case_keys"] == expected_failure_cases
            and row["roadgraph_unexpected_failure_count"] == 0
            and row["unsafe_advance_right_published_count"] == 0
            and row["junction_conflict_wrong_replace_count"] == 0
        )
        seed_gates.append(
            {"seed": row["seed"], "gate1": gate1, "gate2": gate2, "gate4": gate4}
        )
    macros = [float(row["segment_macro_f1"]) for row in seeds]
    gate3 = len(seeds) == 3 and max(macros) - min(macros) <= 0.03 and all(
        row["gate1"] and row["gate2"] for row in seed_gates
    )
    all_pass = (
        all(row["gate1"] and row["gate2"] and row["gate4"] for row in seed_gates)
        and gate3
        and bool(resources["passed"])
    )
    return {
        "schema_version": "p05-scheme-a-p1-oof-summary-v1",
        "decision": "P05_SCHEME_A_P1_MODEL_GO" if all_pass else "P05_SCHEME_A_P1_MODEL_NO_GO",
        "case_count": config.expected_case_count,
        "seeds": list(config.seeds),
        "seed_metrics": [
            {
                key: value
                for key, value in row.items()
                if key
                in {
                    "seed",
                    "segment_macro_f1",
                    "use_rcsd_precision",
                    "unsafe_fallback_recall",
                    "accepted_coverage",
                    "movement_available_exact",
                    "anomaly_precision",
                    "anomaly_recall",
                    "roadgraph_legal_count",
                    "roadgraph_failure_count",
                    "roadgraph_expected_failure_count",
                    "roadgraph_expected_failure_case_keys",
                    "roadgraph_unexpected_failure_count",
                    "roadgraph_unexpected_failure_case_keys",
                    "roadgraph_terminal_counts",
                    "unsafe_advance_right_published_count",
                    "junction_conflict_wrong_replace_count",
                }
            }
            for row in seeds
        ],
        "strongest_non_neural_segment_macro_f1": baseline_macro,
        "expected_roadgraph_failure_case_keys": expected_failure_cases,
        "seed_gates": seed_gates,
        "gate3_stability": gate3,
        "macro_seed_spread": max(macros) - min(macros),
        "resource_gate": bool(resources["passed"]),
        "truth_feature_count": 0,
        "skeleton_mutation_count": 0,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _validation_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# P05-Scheme-A-P1 validation",
        "",
        f"- decision: `{summary['decision']}`",
        f"- Case: `{summary['case_count']}`",
        f"- seeds: `{summary['seeds']}`",
        f"- macro seed spread: `{summary['macro_seed_spread']:.6f}`",
        f"- strongest non-neural macro: `{summary['strongest_non_neural_segment_macro_f1']:.6f}`",
        f"- expected RoadGraph failures: `{summary['expected_roadgraph_failure_case_keys']}`",
        f"- resource gate: `{summary['resource_gate']}`",
        "",
        "## Seed gates",
        "",
    ]
    lines.extend(
        f"- seed {row['seed']}: Gate1={row['gate1']}, Gate2={row['gate2']}, Gate4={row['gate4']}"
        for row in summary["seed_gates"]
    )
    return "\n".join(lines) + "\n"


def _state_signature(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _class_metrics(truth: Sequence[str], predicted: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in ("USE_RCSD", "KEEP_SWSD", "REVIEW_FALLBACK"):
        tp = sum(a == label and b == label for a, b in zip(truth, predicted, strict=True))
        fp = sum(a != label and b == label for a, b in zip(truth, predicted, strict=True))
        fn = sum(a == label and b != label for a, b in zip(truth, predicted, strict=True))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        result[label] = {
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / max(1e-12, precision + recall),
            "support": sum(value == label for value in truth),
        }
    return result


def _macro_f1(truth: Sequence[str], predicted: Sequence[str], labels: Sequence[str]) -> float:
    metrics = _class_metrics(truth, predicted)
    return sum(float(metrics[label]["f1"]) for label in labels) / len(labels)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    position = max(0, min(len(values) - 1, math.ceil(fraction * len(values)) - 1))
    return sorted(values)[position]


def _verified_output(outputs: Mapping[str, Any], key: str, strict_hashes: bool) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"P1 candidate output hash mismatch: {key}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _write_artifact_manifest(run_root: Path, path: Path) -> None:
    excluded = {"artifact_manifest.json", "scheme_a_p1_oof_manifest.json"}
    rows = [
        output_record(file_path)
        for file_path in sorted(run_root.rglob("*"))
        if file_path.is_file() and file_path.name not in excluded
    ]
    write_json(
        path,
        {
            "schema_version": "p05-scheme-a-p1-artifact-manifest-v1",
            "artifact_count": len(rows),
            "artifacts": rows,
            "signature": canonical_sha256(rows),
        },
    )


__all__ = ["run_scheme_a_p1_oof"]
