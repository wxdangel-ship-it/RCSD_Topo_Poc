from __future__ import annotations

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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_execution import (
    load_p2_p1_payloads,
    materialize_p2_p1_seed,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_oof import (
    build_joint_safety_selections,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_evidence import (
    load_safety_evidence,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_models import (
    SCHEME_A_P2_P2_P2_P0_SCHEMA,
    SafetyEvidenceExample,
    SchemeAP2P2P2P0Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_probe import (
    probe_metrics,
    train_probe_fold,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def run_scheme_a_p2_p2_p2_p0_audit(config: SchemeAP2P2P2P0Config) -> Path:
    started = time.perf_counter()
    examples, metadata = load_safety_evidence(config)
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    evidence_path = run_root / "safety_evidence.jsonl"
    labels_path = run_root / "label_only_join.jsonl"
    contract_path = run_root / "evidence_contract.json"
    ledger_path = run_root / "error_review_ledger.jsonl"
    _write_jsonl(evidence_path, metadata["feature_rows"])
    _write_jsonl(labels_path, metadata["label_rows"])
    write_json(
        contract_path,
        {
            "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
            "candidate_first": True,
            "accept_or_fallback_only": True,
            "candidate_reselection_allowed": False,
            "feature_names": list(metadata["feature_names"]),
            "feature_count": len(metadata["feature_names"]),
            "allowed_modules": ["T01", "T07"],
            "allowed_derived_roles": [
                "TRUTH_FREE_PROPOSAL_PAYLOAD",
                "SEGMENT_NODE_COMPATIBILITY",
                "BASE_OOF_STATISTIC",
            ],
            "prohibited_modules": ["T03", "T04", "T05", "T06"],
            "truth_feature_count": 0,
            "identifier_feature_count": 0,
            "absolute_coordinate_feature_count": 0,
            "movement_feature_count": 0,
            "t07_evidence_mode": "DRIVEZONE_ONLY",
            "lineage": metadata["lineage"],
            "evidence_signature": metadata["evidence_signature"],
        },
    )
    audited_ids = set(metadata["agreed_wrong_group_ids"]) | {
        example.group_id for example in examples if example.review_target
    }
    label_by_group = {row["group_id"]: row for row in metadata["label_rows"]}
    feature_by_group = {row["group_id"]: row for row in metadata["feature_rows"]}
    _write_jsonl(
        ledger_path,
        [
            {
                "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
                "case_key": feature_by_group[group_id]["case_key"],
                "group_id": group_id,
                "object_id": feature_by_group[group_id]["object_id"],
                "proposal_candidate_id": feature_by_group[group_id]["proposal_candidate_id"],
                "proposal_target": feature_by_group[group_id]["proposal_target"],
                "evidence_vector_complete": len(feature_by_group[group_id]["features"])
                == len(metadata["feature_names"]),
                **label_by_group[group_id],
            }
            for group_id in sorted(audited_ids)
        ],
    )

    expected_failure_cases = {row[0] for row in config.expected_roadgraph_failures}
    probe_results: list[dict[str, Any]] = []
    all_scores: list[dict[str, Any]] = []
    all_decisions: list[dict[str, Any]] = []
    all_evaluation: list[dict[str, Any]] = []
    all_effective: list[dict[str, Any]] = []
    all_roadgraphs: list[dict[str, Any]] = []
    all_closures: list[dict[str, Any]] = []
    payload_path = _output_path(metadata["dataset"]["dataset_manifest"], "payloads")
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
    for probe_index, probe_name in enumerate(config.probe_names):
        probe_decisions: list[dict[str, Any]] = []
        probe_evaluation: list[dict[str, Any]] = []
        fold_summaries: list[dict[str, Any]] = []
        for fold in range(config.expected_fold_count):
            result = train_probe_fold(
                examples,
                case_folds=metadata["case_folds"],
                held_out_fold=fold,
                probe_name=probe_name,
                config=config,
            )
            fold_root = run_root / "folds" / probe_name.lower() / str(fold)
            _save_fold(fold_root, result, metadata["feature_names"])
            held_examples: Sequence[SafetyEvidenceExample] = result["held_out_examples"]
            rows = [dict(row) for row in result["held_out_rows"]]
            for example, probability, row in zip(
                held_examples, result["held_out_probabilities"], rows, strict=True
            ):
                if example.case_key in expected_failure_cases:
                    row.update(
                        {
                            "accepted": False,
                            "decision": "FALLBACK",
                            "reason": "expected_swsd_baseline_failure",
                        }
                    )
                row.update(
                    {
                        "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
                        "probe": probe_name,
                        "model_signature": result["state_signature"],
                        "seed": 301 + probe_index,
                    }
                )
                probe_decisions.append(row)
                all_scores.append(
                    {
                        "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
                        "case_key": example.case_key,
                        "group_id": example.group_id,
                        "object_type": "SEGMENT",
                        "probe": probe_name,
                        "fold": fold,
                        "unsafe_probability": float(probability),
                        "model_signature": result["state_signature"],
                    }
                )
                probe_evaluation.append(
                    {
                        "case_key": example.case_key,
                        "group_id": example.group_id,
                        "truth_candidate_id": example.truth_candidate_id,
                        "truth_target": example.truth_target,
                        "proposal_correct": example.proposal_correct,
                        "anomaly_target": example.anomaly_target,
                        "review_target": example.review_target,
                        "accepted": bool(row["accepted"]),
                        "probe": probe_name,
                        "fold": fold,
                        "label_only": True,
                    }
                )
            held_rows = probe_decisions[-len(held_examples) :]
            fold_metrics = probe_metrics(held_examples, held_rows)
            accepted_by_group = {str(row["group_id"]): bool(row["accepted"]) for row in held_rows}
            fold_wrong_ids = set(metadata["agreed_wrong_group_ids"]) & {
                example.group_id for example in held_examples
            }
            fold_metrics["agreed_wrong_auto_publish_count"] = sum(
                accepted_by_group.get(group_id, False) for group_id in fold_wrong_ids
            )
            fold_gate = _safety_gate(fold_metrics, config)
            fold_summary = {
                **dict(result["summary"]),
                **fold_metrics,
                "agreed_wrong_held_out_count": len(fold_wrong_ids),
                "gate_pass": fold_gate,
            }
            fold_summaries.append(fold_summary)
            write_json(fold_root / "held_out_summary.json", fold_summary)

        probe_seed = 301 + probe_index
        selections, closure = build_joint_safety_selections(
            metadata["all_groups"],
            probe_decisions,
            compatibility_edges=metadata["dataset"]["compatibility_edges"],
            labels=metadata["dataset"]["labels"],
            node_scores=node_scores,
            expected_failure_cases=expected_failure_cases,
            seed=probe_seed,
        )
        graphs, effective = materialize_p2_p1_seed(
            run_root,
            seed=probe_seed,
            selections=selections,
            payloads_by_id=payloads_by_id,
            payloads_by_group=payloads_by_group,
            expected_failure_manifest=expected_failure_manifest,
        )
        graph_metrics = _roadgraph_metrics(graphs, closure, config)
        ordered_examples = _examples_aligned_to_rows(examples, probe_decisions)
        overall = probe_metrics(ordered_examples, probe_decisions)
        accepted_by_group = {
            str(row["group_id"]): bool(row["accepted"]) for row in probe_decisions
        }
        overall["agreed_wrong_auto_publish_count"] = sum(
            accepted_by_group.get(group_id, False)
            for group_id in metadata["agreed_wrong_group_ids"]
        )
        probe_gate = all(row["gate_pass"] for row in fold_summaries)
        probe_results.append(
            {
                "probe": probe_name,
                "parameter_count": max(row["parameter_count"] for row in fold_summaries),
                "fold_metrics": fold_summaries,
                "overall_metrics": overall,
                "cross_case_gate_pass": probe_gate,
                "roadgraph_gate_pass": graph_metrics["gate_pass"],
                "roadgraph_metrics": graph_metrics,
                "gate_pass": probe_gate and graph_metrics["gate_pass"],
            }
        )
        all_decisions.extend(probe_decisions)
        all_evaluation.extend(probe_evaluation)
        all_effective.extend({"probe": probe_name, **row} for row in effective)
        all_roadgraphs.extend({"probe": probe_name, **row} for row in graphs)
        all_closures.append({"probe": probe_name, **closure})

    score_path = run_root / "probe_scores.jsonl"
    decision_path = run_root / "decisions.jsonl"
    evaluation_path = run_root / "evaluation.jsonl"
    effective_path = run_root / "effective_selections.jsonl"
    roadgraph_path = run_root / "roadgraph_index.jsonl"
    closure_path = run_root / "closure_audit.jsonl"
    _write_jsonl(score_path, sorted(all_scores, key=_probe_group_key))
    _write_jsonl(decision_path, sorted(all_decisions, key=_probe_group_key))
    _write_jsonl(evaluation_path, sorted(all_evaluation, key=_probe_group_key))
    _write_jsonl(effective_path, sorted(all_effective, key=_probe_group_key))
    _write_jsonl(roadgraph_path, sorted(all_roadgraphs, key=_probe_case_key))
    _write_jsonl(closure_path, sorted(all_closures, key=lambda row: str(row["probe"])))

    gate0 = (
        len(examples) == config.expected_segment_group_count
        and len(metadata["case_folds"]) == config.expected_case_count
        and len(metadata["agreed_wrong_group_ids"]) == config.expected_agreed_wrong_count
        and len(metadata["stable_false_use_group_ids"])
        == config.expected_stable_false_use_count
        and all(value for value in metadata["lineage"].values())
    )
    gate1 = (
        len(audited_ids) == config.expected_agreed_wrong_count + config.expected_review_count
        and all(len(row["features"]) == len(metadata["feature_names"]) for row in metadata["feature_rows"])
    )
    deterministic_payload = {
        "evidence_signature": metadata["evidence_signature"],
        "scores": sorted(all_scores, key=_probe_group_key),
        "decisions": sorted(all_decisions, key=_probe_group_key),
        "evaluation": sorted(all_evaluation, key=_probe_group_key),
        "effective": [
            {key: value for key, value in row.items() if key not in {"output"}}
            for row in sorted(all_effective, key=_probe_group_key)
        ],
        "roadgraphs": [
            {key: value for key, value in row.items() if key != "output"}
            for row in sorted(all_roadgraphs, key=_probe_case_key)
        ],
        "closures": sorted(all_closures, key=lambda row: str(row["probe"])),
        "probe_results": _deterministic_probe_results(probe_results),
    }
    determinism_signature = canonical_sha256(deterministic_payload)
    reference_match: bool | None = None
    if config.reference_run_root is not None:
        reference_root = normalize_runtime_path(config.reference_run_root).resolve(strict=True)
        reference_match = determinism_signature == _determinism_signature_from_run(reference_root)
    resource = _resource_audit(started)
    if not gate0 or not gate1:
        decision = "P05_SCHEME_A_P2_P2_P2_P0_AUDIT_NO_GO"
    elif reference_match is False:
        decision = "P05_SCHEME_A_P2_P2_P2_P0_AUDIT_NO_GO"
    elif any(row["gate_pass"] for row in probe_results):
        decision = "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_GO"
    else:
        decision = "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO"
    summary = {
        "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
        "decision": decision,
        "case_count": len(metadata["case_folds"]),
        "segment_group_count": len(examples),
        "agreed_wrong_count": len(metadata["agreed_wrong_group_ids"]),
        "stable_false_use_count": len(metadata["stable_false_use_group_ids"]),
        "review_count": sum(example.review_target for example in examples),
        "feature_count": len(metadata["feature_names"]),
        "feature_gate_pass": gate0 and gate1,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_candidate_count": 0,
        "t03_t06_model_input_count": 0,
        "verified_road_artifact_count": metadata["verified_road_artifact_count"],
        "t07_case_count": metadata["t07_case_count"],
        "probe_results": probe_results,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "replay_status": "MATCHED" if reference_match else ("PENDING" if reference_match is None else "MISMATCH"),
        "resource": resource,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    summary_path = run_root / "scheme_a_p2_p2_p2_p0_summary.json"
    write_json(summary_path, summary)
    outputs = {
        "evidence": output_record(evidence_path),
        "labels": output_record(labels_path),
        "evidence_contract": output_record(contract_path),
        "ledger": output_record(ledger_path),
        "scores": output_record(score_path),
        "decisions": output_record(decision_path),
        "evaluation": output_record(evaluation_path),
        "effective_selections": output_record(effective_path),
        "roadgraphs": output_record(roadgraph_path),
        "closure_audit": output_record(closure_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
        "run_id": config.run_id,
        "decision": decision,
        "lineage": metadata["lineage"],
        "evidence_signature": metadata["evidence_signature"],
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "candidate_first": True,
        "candidate_reselection_allowed": False,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_candidate_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "outputs": outputs,
    }
    manifest_path = run_root / "scheme_a_p2_p2_p2_p0_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p2-p2-p0-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _save_fold(root: Path, result: Mapping[str, Any], feature_names: Sequence[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "model.pt"
    torch.save(
        {
            "schema_version": SCHEME_A_P2_P2_P2_P0_SCHEMA,
            "state_signature": result["state_signature"],
            "state_dict": {
                key: value.detach().cpu() for key, value in result["model"].state_dict().items()
            },
        },
        checkpoint,
    )
    write_json(
        root / "preprocessing.json",
        {
            "feature_names": list(feature_names),
            "means": list(result["means"]),
            "scales": list(result["scales"]),
            "threshold": result["threshold"],
        },
    )
    write_csv(root / "training_history.csv", result["history"], list(result["history"][0]))
    write_json(root / "training_summary.json", result["summary"])


def _safety_gate(metrics: Mapping[str, Any], config: SchemeAP2P2P2P0Config) -> bool:
    return (
        int(metrics["accepted_wrong_count"]) == 0
        and int(metrics["agreed_wrong_auto_publish_count"]) == 0
        and int(metrics["review_auto_publish_count"]) == 0
        and float(metrics["unsafe_fallback_recall"]) == 1.0
        and float(metrics["safe_coverage"]) >= config.minimum_safe_coverage
        and float(metrics["use_rcsd_safe_coverage"])
        >= config.minimum_use_rcsd_safe_coverage
    )


def _roadgraph_metrics(
    rows: Sequence[Mapping[str, Any]], closure: Mapping[str, Any], config: SchemeAP2P2P2P0Config
) -> dict[str, Any]:
    terminals = Counter(str(row["terminal_state"]) for row in rows)
    node_conflicts = 0
    for row in rows:
        graph = _read_json(normalize_runtime_path(str(row["output"]["path"])))
        node_conflicts += int(graph["audit"].get("node_conflict_count") or 0)
    result = {
        "terminal_counts": dict(sorted(terminals.items())),
        "legal_publish_count": terminals["LEGAL"],
        "expected_fail_count": terminals["EXPECTED_FAIL"],
        "unexpected_failure_count": terminals["FAIL"],
        "node_payload_conflict_count": node_conflicts,
        "requirement_conflict_count": int(closure["requirement_conflict_count"]),
        "node_target_mismatch_count": int(closure["node_target_mismatch_count"]),
        "junction_fallback_count": int(closure["junction_fallback_count"]),
    }
    result["gate_pass"] = (
        result["legal_publish_count"]
        == config.expected_case_count - len(config.expected_roadgraph_failures)
        and result["expected_fail_count"] == len(config.expected_roadgraph_failures)
        and result["unexpected_failure_count"] == 0
        and result["node_payload_conflict_count"] == 0
        and result["requirement_conflict_count"] == 0
        and result["node_target_mismatch_count"] == 0
    )
    return result


def _base_node_scores(path: Path, base_seeds: Sequence[int]) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    allowed = set(base_seeds)
    for row in _read_jsonl(path):
        if row.get("object_type") == "NODE" and int(row["seed"]) in allowed:
            values[str(row["group_id"])][str(row["candidate_id"])].append(float(row["score"]))
    result: dict[str, dict[str, float]] = {}
    for group_id, candidates in values.items():
        if any(len(scores) != len(base_seeds) for scores in candidates.values()):
            raise ValueError(f"base Node score seed denominator differs: {group_id}")
        result[group_id] = {
            candidate_id: sum(scores) / len(scores) for candidate_id, scores in candidates.items()
        }
    return result


def _examples_aligned_to_rows(
    examples: Sequence[SafetyEvidenceExample], rows: Sequence[Mapping[str, Any]]
) -> list[SafetyEvidenceExample]:
    by_group = {example.group_id: example for example in examples}
    if len(by_group) != len(examples):
        raise ValueError("duplicate evidence group")
    ordered = [by_group[str(row["group_id"])] for row in rows]
    if len(ordered) != len(examples) or {row.group_id for row in ordered} != set(by_group):
        raise ValueError("probe decision/evidence denominator differs")
    return ordered


def _deterministic_probe_results(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for result in results:
        normalized = dict(result)
        normalized["fold_metrics"] = []
        for fold in result["fold_metrics"]:
            fold_row = dict(fold)
            fold_row.pop("training_wall_seconds", None)
            normalized["fold_metrics"].append(fold_row)
        output.append(normalized)
    return output


def _determinism_signature_from_run(root: Path) -> str:
    manifest = _read_json(root / "scheme_a_p2_p2_p2_p0_manifest.json")
    summary = _read_json(root / "scheme_a_p2_p2_p2_p0_summary.json")
    payload = {
        "evidence_signature": manifest["evidence_signature"],
        "scores": list(_read_jsonl(root / "probe_scores.jsonl")),
        "decisions": list(_read_jsonl(root / "decisions.jsonl")),
        "evaluation": list(_read_jsonl(root / "evaluation.jsonl")),
        "effective": [
            {key: value for key, value in row.items() if key != "output"}
            for row in _read_jsonl(root / "effective_selections.jsonl")
        ],
        "roadgraphs": [
            {key: value for key, value in row.items() if key != "output"}
            for row in _read_jsonl(root / "roadgraph_index.jsonl")
        ],
        "closures": list(_read_jsonl(root / "closure_audit.jsonl")),
        "probe_results": _deterministic_probe_results(summary["probe_results"]),
    }
    return canonical_sha256(payload)


def _output_path(manifest: Mapping[str, Any], role: str) -> Path:
    record = dict(manifest.get("outputs") or {}).get(role) or {}
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"dataset output hash mismatch: {role}")
    return path


def _resource_audit(started: float) -> dict[str, Any]:
    try:
        import resource

        max_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except ImportError:
        max_rss_mb = 0.0
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": "cpu",
        "cuda_available": torch.cuda.is_available(),
        "total_wall_seconds": time.perf_counter() - started,
        "max_rss_mb": max_rss_mb,
        "wall_within_six_hours": time.perf_counter() - started <= 6 * 60 * 60,
        "cpu_ram_within_16gb": not max_rss_mb or max_rss_mb <= 16 * 1024,
        "gpu_peak_memory_mb": 0.0,
        "gpu_vram_within_8gb": True,
    }


def _probe_group_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("probe") or ""), str(row["group_id"])


def _probe_case_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("probe") or ""), str(row["case_key"])


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
            stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


__all__ = ["run_scheme_a_p2_p2_p2_p0_audit"]
