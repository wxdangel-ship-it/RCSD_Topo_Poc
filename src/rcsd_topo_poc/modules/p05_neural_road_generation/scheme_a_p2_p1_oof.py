from __future__ import annotations

import hashlib
import json
import platform
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
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    expected_calibration_error,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_execution import (
    load_p2_p1_payloads,
    materialize_p2_p1_seed,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SCHEME_A_P2_P1_SCORE_SCHEMA,
    SchemeAP2P1OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_training import (
    load_scheme_a_p2_p1_groups,
    score_selection_rows,
    train_scheme_a_p2_p1_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p1_oof(config: SchemeAP2P1OOFConfig) -> Path:
    started = time.perf_counter()
    groups, dataset = load_scheme_a_p2_p1_groups(
        config.dataset_run_root, strict_hashes=config.strict_hashes
    )
    compatibility_edges = dataset["compatibility_edges"]
    junction_by_group = {
        group_id: str(label.get("junction_key") or group_id)
        for group_id, label in dataset["labels"].items()
    }
    case_folds = _case_folds(groups, config)
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    score_path = run_root / "scores.jsonl"
    selection_path = run_root / "selections.jsonl"
    fold_records: list[dict[str, Any]] = []
    all_score_rows: list[dict[str, Any]] = []
    all_selection_rows: list[dict[str, Any]] = []
    seed_groups: dict[int, list[Any]] = defaultdict(list)
    with score_path.open("w", encoding="utf-8", newline="\n") as score_stream, selection_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as selection_stream:
        for seed in config.seeds:
            for fold in range(config.expected_fold_count):
                result = train_scheme_a_p2_p1_fold(
                    groups,
                    case_folds=case_folds,
                    held_out_fold=fold,
                    seed=seed,
                    dataset_manifest_sha256=dataset["dataset_manifest_sha256"],
                    config=config,
                    compatibility_edges=compatibility_edges,
                    junction_by_group=junction_by_group,
                )
                fold_root = run_root / "folds" / str(seed) / str(fold)
                model_signature = _state_signature(result["model"])
                record = _save_fold_artifacts(
                    fold_root,
                    result,
                    seed=seed,
                    fold=fold,
                    model_signature=model_signature,
                    dataset_manifest_sha256=dataset["dataset_manifest_sha256"],
                    config=config,
                )
                fold_records.append(record)
                scores, selections = score_selection_rows(
                    result["held_out_groups"],
                    result["held_out_scores"],
                    result["held_out_probabilities"],
                    result["held_out_anomaly_probabilities"],
                    result["thresholds"],
                    seed=seed,
                    fold=fold,
                    model_signature=model_signature,
                    compatibility_edges=compatibility_edges,
                    junction_by_group=junction_by_group,
                )
                for row in scores:
                    row["schema_version"] = SCHEME_A_P2_P1_SCORE_SCHEMA
                    _write_jsonl_row(score_stream, row)
                for row in selections:
                    _write_jsonl_row(selection_stream, row)
                all_score_rows.extend(scores)
                all_selection_rows.extend(selections)
                seed_groups[seed].extend(result["held_out_groups"])
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    payload_path = _verified_output(dataset["dataset_manifest"].get("outputs") or {}, "payloads", config.strict_hashes)
    payloads_by_id, payloads_by_group = load_p2_p1_payloads(payload_path)
    expected_failures = {
        case_key: frozenset(
            {
                f"Road endpoint Node missing: {node_id}",
                f"directed edge endpoint missing: {edge}",
            }
        )
        for case_key, node_id, edge in config.expected_roadgraph_failures
    }
    roadgraph_records: list[dict[str, Any]] = []
    effective_selections: list[dict[str, Any]] = []
    for seed in config.seeds:
        seed_rows = [row for row in all_selection_rows if int(row["seed"]) == seed]
        roadgraphs, effective = materialize_p2_p1_seed(
            run_root,
            seed=seed,
            selections=seed_rows,
            payloads_by_id=payloads_by_id,
            payloads_by_group=payloads_by_group,
            expected_failure_manifest=expected_failures,
        )
        roadgraph_records.extend({"seed": seed, **row} for row in roadgraphs)
        effective_selections.extend(effective)

    effective_path = run_root / "effective_selections.jsonl"
    roadgraph_path = run_root / "roadgraph_index.jsonl"
    _write_jsonl(effective_path, effective_selections)
    _write_jsonl(roadgraph_path, roadgraph_records)
    label_metadata = dataset["labels"]
    seed_metrics: list[dict[str, Any]] = []
    for seed in config.seeds:
        selections = [row for row in effective_selections if int(row["seed"]) == seed]
        roadgraphs = [row for row in roadgraph_records if int(row["seed"]) == seed]
        metrics = _seed_metrics(seed_groups[seed], selections, roadgraphs, label_metadata)
        metrics["seed"] = seed
        seed_metrics.append(metrics)
    seed_gate_rows = [_seed_gate(row, config) for row in seed_metrics]
    all_pass = all(row["passed"] for row in seed_gate_rows)
    if all_pass:
        decision = "P05_SCHEME_A_P2_P1_OFFLINE_SCORER_GO"
    elif any(row["accepted_wrong_replacement_count"] for row in seed_metrics) or any(
        row["roadgraph_unexpected_failure_count"] for row in seed_metrics
    ):
        decision = "P05_SCHEME_A_P2_P1_SAFETY_NO_GO"
    else:
        decision = "P05_SCHEME_A_P2_P1_MODEL_NO_GO"
    resource = _resource_audit(started, fold_records, config)
    summary = {
        "schema_version": "p05-scheme-a-p2-p1-oof-summary-v1",
        "decision": decision,
        "gate_pass": all_pass,
        "case_count": len(case_folds),
        "fold_count": config.expected_fold_count,
        "seeds": list(config.seeds),
        "movement_candidate_count": 0,
        "seed_metrics": seed_metrics,
        "seed_gates": seed_gate_rows,
        "roadgraph_terminal_counts": dict(
            sorted(Counter(str(row["terminal_state"]) for row in roadgraph_records).items())
        ),
        "resource": resource,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    summary_path = run_root / "scheme_a_p2_p1_oof_summary.json"
    report_path = run_root / "validation_report.md"
    write_json(summary_path, summary)
    report_path.write_text(_validation_report(summary), encoding="utf-8")
    fold_index_path = run_root / "fold_index.json"
    write_json(fold_index_path, fold_records)
    outputs = {
        "scores": output_record(score_path),
        "selections": output_record(selection_path),
        "effective_selections": output_record(effective_path),
        "roadgraphs": output_record(roadgraph_path),
        "fold_index": output_record(fold_index_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-scheme-a-p2-p1-oof-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "offline_scorer_passed" if all_pass else "offline_scorer_no_go",
        "decision": decision,
        "dataset_manifest": {
            "path": str(dataset["dataset_manifest_path"]),
            "sha256": dataset["dataset_manifest_sha256"],
        },
        "parameters": {
            "seeds": config.seeds,
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
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    manifest_path = run_root / "scheme_a_p2_p1_oof_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p1-oof-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)] + [output_record(manifest_path)],
        },
    )
    return run_root


def _save_fold_artifacts(
    root: Path,
    result: Mapping[str, Any],
    *,
    seed: int,
    fold: int,
    model_signature: str,
    dataset_manifest_sha256: str,
    config: SchemeAP2P1OOFConfig,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    checkpoint_path = root / "model.pt"
    torch.save(
        {
            "schema_version": "p05-scheme-a-p2-p1-checkpoint-v1",
            "seed": seed,
            "fold": fold,
            "state_signature": model_signature,
            "state_dict": {
                key: value.detach().cpu() for key, value in result["model"].state_dict().items()
            },
        },
        checkpoint_path,
    )
    vocabulary = result["vocabulary"].to_dict()
    vocabulary["schema_version"] = "p05-scheme-a-p2-p1-fold-vocabulary-v1"
    vocabulary_path = root / "fold_vocabulary.json"
    write_json(vocabulary_path, vocabulary)
    history_path = root / "training_history.csv"
    history = list(result["history"])
    write_csv(history_path, history, list(history[0]))
    threshold_path = root / "thresholds.json"
    write_json(threshold_path, result["thresholds"])
    training_path = root / "training_summary.json"
    training_summary = dict(result["summary"])
    training_summary["model_state_signature"] = model_signature
    write_json(training_path, training_summary)
    contract_path = root / "model_contract.json"
    write_json(
        contract_path,
        {
            "schema_version": "p05-scheme-a-p2-p1-object-conditioned-scorer-v1",
            "parameter_count": parameter_count(result["model"]),
            "object_types": ["SEGMENT", "NODE"],
            "movement_candidate_count": 0,
            "listwise_loss": True,
            "anomaly_head": True,
            "dataset_manifest_sha256": dataset_manifest_sha256,
            "model_state_signature": model_signature,
            "vocabulary_signature": vocabulary["vocabulary_signature"],
            "numeric_dim": config.numeric_dim,
            "embedding_dim": config.embedding_dim,
            "hidden_dim": config.hidden_dim,
            "type_embedding_dim": config.type_embedding_dim,
            "dropout": config.dropout,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    return {
        "seed": seed,
        "fold": fold,
        "model_state_signature": model_signature,
        "checkpoint": output_record(checkpoint_path),
        "model_contract": output_record(contract_path),
        "fold_vocabulary": output_record(vocabulary_path),
        "thresholds": output_record(threshold_path),
        "training_history": output_record(history_path),
        "training_summary": output_record(training_path),
        "summary": training_summary,
    }


def _seed_metrics(
    groups: Sequence[Any],
    selections: Sequence[Mapping[str, Any]],
    roadgraphs: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    by_group = {group.group_id: group for group in groups}
    selected = {str(row["group_id"]): row for row in selections}
    if set(by_group) != set(selected):
        raise ValueError("P2-P1 selection denominator differs")
    segment_truth: list[str] = []
    segment_predicted: list[str] = []
    correctness: list[bool] = []
    confidences: list[float] = []
    node_correct: list[bool] = []
    raw_node_correct: list[bool] = []
    junction_correct: dict[str, list[bool]] = defaultdict(list)
    raw_junction_correct: dict[str, list[bool]] = defaultdict(list)
    use_correct = use_count = use_accepted = 0
    segment_count = segment_accepted = 0
    accepted = accepted_correct = 0
    mixed_count = mixed_correct = 0
    anomaly_tp = anomaly_fp = anomaly_fn = 0
    fallback_tp = fallback_fn = 0
    for group_id, group in by_group.items():
        row = selected[group_id]
        chosen_id = str(row["selected_candidate_id"])
        correct = chosen_id == group.candidates[group.truth_index].candidate_id
        correctness.append(correct)
        confidences.append(float(row["confidence"]))
        anomaly_predicted = row["reason"] in {"hard_unsafe", "anomaly_threshold"}
        anomaly_tp += anomaly_predicted and group.anomaly_target
        anomaly_fp += anomaly_predicted and not group.anomaly_target
        anomaly_fn += (not anomaly_predicted) and group.anomaly_target
        fallback_tp += (not bool(row["accepted"])) and group.anomaly_target
        fallback_fn += bool(row["accepted"]) and group.anomaly_target
        accepted += int(bool(row["accepted"]))
        accepted_correct += int(bool(row["accepted"]) and correct)
        if group.object_type == "SEGMENT":
            segment_count += 1
            predicted_target = next(
                candidate.candidate_target for candidate in group.candidates if candidate.candidate_id == chosen_id
            )
            if group.truth_target == "MIXED_CARRIER":
                mixed_count += 1
                mixed_correct += int(correct)
            else:
                segment_truth.append(group.truth_target)
                segment_predicted.append(predicted_target)
            segment_accepted += int(bool(row["accepted"]))
            if group.truth_target == "USE_RCSD":
                use_count += 1
                use_correct += int(correct)
                use_accepted += int(bool(row["accepted"]))
        else:
            node_correct.append(correct)
            junction_key = str(labels[group_id].get("junction_key") or group_id)
            junction_correct[junction_key].append(correct)
            raw_correct = str(row.get("raw_selected_candidate_id") or chosen_id) == str(
                group.candidates[group.truth_index].candidate_id
            )
            raw_node_correct.append(raw_correct)
            raw_junction_correct[junction_key].append(raw_correct)
    confidence_tensor = torch.tensor(confidences, dtype=torch.float32)
    correctness_tensor = torch.tensor(correctness, dtype=torch.bool)
    terminal = Counter(str(row["terminal_state"]) for row in roadgraphs)
    return {
        "segment_macro_f1": _macro_f1(
            segment_truth,
            segment_predicted,
            ("KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD"),
        ),
        "mixed_carrier_exact": mixed_correct / max(1, mixed_count),
        "mixed_carrier_count": mixed_count,
        "use_rcsd_recall": use_correct / max(1, use_count),
        "node_candidate_exact": sum(node_correct) / max(1, len(node_correct)),
        "junction_node_exact": sum(all(values) for values in junction_correct.values())
        / max(1, len(junction_correct)),
        "raw_independent_node_candidate_exact": sum(raw_node_correct)
        / max(1, len(raw_node_correct)),
        "raw_independent_junction_node_exact": sum(
            all(values) for values in raw_junction_correct.values()
        )
        / max(1, len(raw_junction_correct)),
        "ece": expected_calibration_error(confidence_tensor, correctness_tensor),
        "accepted_wrong_replacement_count": accepted - accepted_correct,
        "accepted_precision": accepted_correct / max(1, accepted),
        "safe_accepted_coverage": accepted / max(1, len(groups)),
        "segment_safe_accepted_coverage": segment_accepted / max(1, segment_count),
        "use_rcsd_safe_accepted_coverage": use_accepted / max(1, use_count),
        "hard_conflict_recall": fallback_tp / max(1, fallback_tp + fallback_fn),
        "anomaly_precision": anomaly_tp / max(1, anomaly_tp + anomaly_fp),
        "roadgraph_legal_count": terminal["LEGAL"],
        "roadgraph_expected_failure_count": terminal["EXPECTED_FAIL"],
        "roadgraph_unexpected_failure_count": terminal["FAIL"],
        "roadgraph_case_count": len(roadgraphs),
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }


def _seed_gate(metrics: Mapping[str, Any], config: SchemeAP2P1OOFConfig) -> dict[str, Any]:
    checks = {
        "segment_macro_f1": float(metrics["segment_macro_f1"]) >= config.minimum_segment_macro_f1,
        "use_rcsd_recall": float(metrics["use_rcsd_recall"]) >= config.minimum_use_rcsd_recall,
        "junction_node_exact": float(metrics["junction_node_exact"]) >= config.minimum_junction_node_exact,
        "ece": float(metrics["ece"]) <= config.maximum_ece,
        "accepted_wrong": int(metrics["accepted_wrong_replacement_count"]) == 0,
        "accepted_precision": float(metrics["accepted_precision"]) == 1.0,
        "safe_coverage": float(metrics["safe_accepted_coverage"]) >= config.minimum_safe_coverage,
        "use_rcsd_safe_coverage": float(metrics["use_rcsd_safe_accepted_coverage"])
        >= config.minimum_use_rcsd_safe_coverage,
        "hard_conflict_recall": float(metrics["hard_conflict_recall"]) == 1.0,
        "anomaly_precision": float(metrics["anomaly_precision"]) >= config.minimum_anomaly_precision,
        "roadgraph_49_2": int(metrics["roadgraph_legal_count"]) == 49
        and int(metrics["roadgraph_expected_failure_count"]) == 2
        and int(metrics["roadgraph_unexpected_failure_count"]) == 0,
    }
    return {"seed": metrics["seed"], "passed": all(checks.values()), "checks": checks}


def _case_folds(groups: Sequence[Any], config: SchemeAP2P1OOFConfig) -> dict[str, int]:
    result: dict[str, int] = {}
    for group in groups:
        previous = result.setdefault(group.case_key, group.fold)
        if previous != group.fold:
            raise ValueError(f"Case crosses P2-P1 folds: {group.case_key}")
    if len(result) != config.expected_case_count or set(result.values()) != set(
        range(config.expected_fold_count)
    ):
        raise ValueError("P2-P1 Case/fold denominator mismatch")
    return result


def _resource_audit(started: float, folds: Sequence[Mapping[str, Any]], config: SchemeAP2P1OOFConfig) -> dict[str, Any]:
    parameter_counts = [int(row["summary"]["parameter_count"]) for row in folds]
    training_seconds = sum(float(row["summary"]["training_wall_seconds"]) for row in folds)
    return {
        "wall_seconds": time.perf_counter() - started,
        "training_wall_seconds": training_seconds,
        "parameter_count_min": min(parameter_counts),
        "parameter_count_max": max(parameter_counts),
        "parameter_gate_pass": min(parameter_counts) >= config.min_parameter_count
        and max(parameter_counts) <= config.max_parameter_count,
        "gpu_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _validation_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# P05 Scheme-A-P2-P1 OOF 验证报告",
        "",
        f"- 决策：`{summary['decision']}`",
        f"- Case/Fold/Seed：{summary['case_count']} / {summary['fold_count']} / {summary['seeds']}",
        f"- RoadGraph：{summary['roadgraph_terminal_counts']}",
        "- Movement candidate/decision/evaluation：0",
        "- content repair / silent fix / skeleton mutation：0 / 0 / 0",
        "",
    ]
    for metrics in summary["seed_metrics"]:
        lines.append(
            f"- seed {metrics['seed']}：macro={metrics['segment_macro_f1']:.6f}，"
            f"USE_RCSD recall={metrics['use_rcsd_recall']:.6f}，"
            f"Junction Node exact={metrics['junction_node_exact']:.6f}，"
            f"coverage={metrics['safe_accepted_coverage']:.6f}，"
            f"wrong={metrics['accepted_wrong_replacement_count']}"
        )
    return "\n".join(lines) + "\n"


def _macro_f1(truth: Sequence[str], predicted: Sequence[str], labels: Sequence[str]) -> float:
    values: list[float] = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, predicted, strict=True))
        fp = sum(a != label and b == label for a, b in zip(truth, predicted, strict=True))
        fn = sum(a == label and b != label for a, b in zip(truth, predicted, strict=True))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        values.append(2 * precision * recall / max(1e-12, precision + recall))
    return sum(values) / len(values)


def _state_signature(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _verified_output(outputs: Mapping[str, Any], role: str, strict_hashes: bool) -> Path:
    record = outputs.get(role)
    if not record:
        raise ValueError(f"P2-P1 dataset output missing: {role}")
    path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
    if strict_hashes and sha256_file(path) != record["sha256"]:
        raise ValueError(f"P2-P1 dataset output hash mismatch: {role}")
    return path


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            _write_jsonl_row(stream, row)


def _write_jsonl_row(stream: Any, row: Mapping[str, Any]) -> None:
    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


__all__ = ["run_scheme_a_p2_p1_oof"]
