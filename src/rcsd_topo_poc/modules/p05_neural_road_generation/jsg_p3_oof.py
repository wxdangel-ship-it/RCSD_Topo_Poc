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
from typing import Any, Iterable, Iterator, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_compiler import _carrier_failures
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import (
    _environment,
    _rss_bytes,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_oof import (
    _aggregate_graph_metrics,
    _case_dir,
    _load_contract as _load_p2_contract,
    _read_json,
    _read_jsonl,
    _validate_pto_a,
    _verified_output,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    JSGP2OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_dataset import (
    load_p3_group_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_models import (
    JSGP3OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_network import (
    expected_calibration_error,
    model_contract,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_training import (
    P3GroupExample,
    score_encoded_groups,
    train_fold_model,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_p0 import (
    _evaluation_exact,
    _percentile,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_solver import (
    validate_selected_graph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    read_vector_payloads,
    write_vector_payloads,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


EXPECTED_GROUP_COUNT = 191_331
EXPECTED_CANDIDATE_COUNT = 712_799
RAM_LIMIT_BYTES = 16 * 1024**3
VRAM_LIMIT_BYTES = 8 * 1024**3


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _load_contract(config: JSGP3OOFConfig) -> dict[str, Any]:
    p2_config = JSGP2OOFConfig(
        dataset_run_root=config.p2_dataset_run_root,
        p1_candidate_run_root=config.p1_candidate_run_root,
        p1_oracle_run_root=config.p1_oracle_run_root,
        p0_truth_run_root=config.p0_truth_run_root,
        r2_oracle_run_root=config.r2_oracle_run_root,
        output_root=config.output_root,
        run_id=f"{config.run_id}-p2-read-only-contract",
        expected_case_count=config.expected_case_count,
        expected_fold_count=config.expected_fold_count,
        strict_hashes=config.strict_hashes,
        emit_reconstructed_gpkg=config.emit_reconstructed_gpkg,
    )
    p2_contract = _load_p2_contract(
        p2_config
    )  # P3 freezes the P2 input/evaluator contract.
    context_root = normalize_runtime_path(config.context_dataset_run_root).resolve(strict=True)
    context_manifest_path = context_root / "p05_jsg_p3_dataset_manifest.json"
    context_manifest = _read_json(context_manifest_path)
    if context_manifest.get("status") != "dataset_passed":
        raise ValueError("P3 context dataset did not pass")
    if config.strict_hashes and str(
        context_manifest.get("p2_dataset_manifest_sha256") or ""
    ) != sha256_file(p2_contract["dataset_manifest_path"]):
        raise ValueError("P3 context/P2 dataset manifest mismatch")
    context_outputs = dict(context_manifest.get("outputs") or {})
    context_path = _verified_output(
        context_outputs, "group_context", strict_hashes=config.strict_hashes
    )
    context_case_path = _verified_output(
        context_outputs, "case_index", strict_hashes=config.strict_hashes
    )
    leakage_path = _verified_output(
        context_outputs, "leakage_audit", strict_hashes=config.strict_hashes
    )
    summary_path = _verified_output(
        context_outputs, "summary", strict_hashes=config.strict_hashes
    )
    if not bool(_read_json(leakage_path).get("passed")):
        raise ValueError("P3 context leakage audit did not pass")
    context_summary = _read_json(summary_path)
    if (
        int(context_summary.get("case_count") or 0) != config.expected_case_count
        or int(context_summary.get("group_count") or 0) != EXPECTED_GROUP_COUNT
        or int(context_summary.get("candidate_count") or 0) != EXPECTED_CANDIDATE_COUNT
    ):
        raise ValueError("P3 frozen context denominator mismatch")
    context_cases = {row["case_key"]: int(row["fold"]) for row in _read_csv(context_case_path)}
    if context_cases != p2_contract["case_folds"]:
        raise ValueError("P3 context/P2 Case-fold signature differs")
    groups = load_p3_group_examples(p2_contract["feature_path"], context_path)
    if len(groups) != EXPECTED_GROUP_COUNT or sum(
        len(group.candidate_ids) for group in groups
    ) != EXPECTED_CANDIDATE_COUNT:
        raise ValueError("P3 feature/context loaded denominator mismatch")
    return {
        **p2_contract,
        "context_manifest_path": context_manifest_path,
        "context_manifest": context_manifest,
        "context_path": context_path,
        "context_summary": context_summary,
        "groups": groups,
    }


def _state_signature(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _save_fold_artifacts(
    root: Path,
    *,
    seed: int,
    fold: int,
    result: Mapping[str, Any],
    config: JSGP3OOFConfig,
    dataset_manifest_sha256: str,
) -> dict[str, Any]:
    root.mkdir(parents=True)
    model = result["model"]
    state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    state_signature = _state_signature(model)
    checkpoint_path = root / "model.pt"
    torch.save(
        {
            "schema_version": "p05-jsg-p3-checkpoint-v1",
            "seed": seed,
            "fold": fold,
            "state_signature": state_signature,
            "state_dict": state,
        },
        checkpoint_path,
    )
    vocabulary_payload = result["vocabulary"].to_dict()
    vocabulary_path = root / "fold_vocabulary.json"
    write_json(vocabulary_path, vocabulary_payload)
    history = list(result["history"])
    history_path = root / "training_history.csv"
    write_csv(history_path, history, list(history[0]))
    training_summary = dict(result["summary"])
    training_summary["model_state_signature"] = state_signature
    training_summary_path = root / "training_summary.json"
    write_json(training_summary_path, training_summary)
    contract_payload = model_contract(
        model,
        seed=seed,
        fold=fold,
        dataset_manifest_sha256=dataset_manifest_sha256,
        model_state_signature=state_signature,
        checkpoint_sha256=sha256_file(checkpoint_path),
        vocabulary_signature=vocabulary_payload["vocabulary_signature"],
        embedding_dim=config.embedding_dim,
        hidden_dim=config.hidden_dim,
        type_embedding_dim=config.type_embedding_dim,
        dropout=config.dropout,
        listwise_loss=True,
        score_semantics="higher_is_better; cost=-score",
        content_repair=False,
        silent_fix=False,
    )
    contract_path = root / "model_contract.json"
    write_json(contract_path, contract_payload)
    return {
        "seed": seed,
        "fold": fold,
        "state_signature": state_signature,
        "checkpoint": output_record(checkpoint_path),
        "model_contract": output_record(contract_path),
        "fold_vocabulary": output_record(vocabulary_path),
        "training_history": output_record(history_path),
        "training_summary": output_record(training_summary_path),
        "summary": training_summary,
    }


def _train_seed(
    seed_root: Path,
    *,
    seed: int,
    contract: Mapping[str, Any],
    config: JSGP3OOFConfig,
    rss_samples: list[int],
) -> dict[str, Any]:
    score_map: dict[tuple[str, str, str], tuple[list[float], list[float], str]] = {}
    score_seconds_by_case: Counter[str] = Counter()
    fold_artifacts: list[dict[str, Any]] = []
    training_wall_seconds = 0.0
    model_root = seed_root / "models"
    dataset_sha = sha256_file(contract["context_manifest_path"])
    groups: Sequence[P3GroupExample] = contract["groups"]
    case_folds: Mapping[str, int] = contract["case_folds"]
    max_vram_bytes = 0
    for fold in range(config.expected_fold_count):
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        result = train_fold_model(
            groups,
            case_folds=case_folds,
            held_out_fold=fold,
            seed=seed,
            dataset_manifest_sha256=dataset_sha,
            config=config,
        )
        training_wall_seconds += float(result["summary"]["training_wall_seconds"])
        artifact = _save_fold_artifacts(
            model_root / f"fold_{fold}",
            seed=seed,
            fold=fold,
            result=result,
            config=config,
            dataset_manifest_sha256=dataset_sha,
        )
        fold_artifacts.append(artifact)
        model_signature = artifact["state_signature"]
        held_groups: Sequence[P3GroupExample] = result["held_out_groups"]
        held_encoded = result["held_out_encoded"]
        for case_key in sorted(result["vocabulary"].held_out_case_keys):
            indices = [
                index for index, group in enumerate(held_groups) if group.case_key == case_key
            ]
            case_groups = [held_groups[index] for index in indices]
            case_encoded = [held_encoded[index] for index in indices]
            score_started = time.perf_counter()
            case_scores, case_probabilities, _ = score_encoded_groups(
                result["model"],
                case_encoded,
                batch_group_count=config.batch_group_count,
                device=result["device"],
            )
            score_seconds_by_case[case_key] += time.perf_counter() - score_started
            for group, scores, probabilities in zip(
                case_groups, case_scores, case_probabilities, strict=True
            ):
                key = (group.domain, group.case_key, group.group_id)
                if key in score_map:
                    raise ValueError(f"duplicate P3 OOF score group: {key}")
                score_map[key] = (scores, probabilities, model_signature)
        if torch.cuda.is_available():
            max_vram_bytes = max(max_vram_bytes, int(torch.cuda.max_memory_allocated()))
        rss_samples.append(_rss_bytes())
        del result
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    if len(score_map) != len(groups):
        raise ValueError("P3 OOF score/group scope differs")
    return {
        "score_map": score_map,
        "score_seconds_by_case": score_seconds_by_case,
        "fold_artifacts": fold_artifacts,
        "training_wall_seconds": training_wall_seconds,
        "max_vram_bytes": max_vram_bytes,
    }


def _stage(group: P3GroupExample) -> str:
    stage_tokens = {
        token.partition(":")[2]
        for tokens in group.candidate_tokens
        for token in tokens
        if token.startswith("stage:")
    }
    return next(iter(stage_tokens)) if len(stage_tokens) == 1 else ""


def _selected_jsg_payload(
    case_key: str, seed: int, rows: Sequence[Mapping[str, Any]], signature: str
) -> dict[str, Any]:
    return {
        "schema_version": "p05-jsg-p3-selected-v1",
        "case_key": case_key,
        "seed": seed,
        "selected_candidates": [
            {
                "candidate_id": row["candidate_id"],
                "object_type": row["object_type"],
                "object_key": row["object_key"],
                "group_id": row["group_id"],
                "payload": row["payload"],
                "dependencies": row.get("dependencies") or [],
                "evidence_refs": row.get("evidence_refs") or [],
                "source_kinds": row.get("source_kinds") or [],
            }
            for row in sorted(rows, key=lambda item: item["group_id"])
        ],
        "selection_signature": signature,
        "label_only": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _write_score_and_group_outputs(
    seed_root: Path,
    *,
    seed: int,
    groups: Sequence[P3GroupExample],
    score_map: Mapping[tuple[str, str, str], tuple[list[float], list[float], str]],
) -> dict[str, Any]:
    score_path = seed_root / "p05_jsg_p3_scores.jsonl"
    group_path = seed_root / "p05_jsg_p3_group_metrics.csv"
    group_fields = [
        "case_key",
        "fold",
        "domain",
        "stage",
        "object_type",
        "group_id",
        "candidate_count",
        "truth_candidate_count",
        "selected_candidate_id",
        "selected_truth_equivalent",
        "best_score",
        "second_score",
        "margin",
        "confidence",
        "uncertainty",
    ]
    selected_ids: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    selected_costs: dict[tuple[str, str, str], float] = {}
    group_counts: Counter[str] = Counter()
    correct_counts: Counter[str] = Counter()
    type_group_counts: Counter[str] = Counter()
    type_correct_counts: Counter[str] = Counter()
    review_truth_count = review_truth_selected = 0
    review_selected_count = review_selected_correct = 0
    split_count = split_correct = 0
    jsg_confidences: list[float] = []
    jsg_correctness: list[bool] = []
    score_signature_digest = hashlib.sha256()
    probability_sum_max_error = 0.0
    score_record_count = 0
    with score_path.open("w", encoding="utf-8", newline="\n") as score_stream, group_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as group_stream:
        writer = csv.DictWriter(group_stream, fieldnames=group_fields)
        writer.writeheader()
        for group in groups:
            key = (group.domain, group.case_key, group.group_id)
            scores, probabilities, model_signature = score_map[key]
            if len(scores) != len(group.candidate_ids) or len(probabilities) != len(
                group.candidate_ids
            ):
                raise ValueError(f"P3 score candidate count differs: {key}")
            probability_sum_max_error = max(
                probability_sum_max_error, abs(sum(probabilities) - 1.0)
            )
            ordered = sorted(
                range(len(scores)),
                key=lambda index: (-float(scores[index]), group.candidate_ids[index]),
            )
            selected_index = ordered[0]
            selected_id = group.candidate_ids[selected_index]
            selected_truth = selected_index == group.truth_index
            second_score = float(scores[ordered[1]]) if len(ordered) > 1 else None
            margin = (
                float(scores[selected_index]) - second_score
                if second_score is not None
                else math.inf
            )
            for index, candidate_id in enumerate(group.candidate_ids):
                record = {
                    "candidate_id": candidate_id,
                    "case_key": group.case_key,
                    "fold": group.fold,
                    "seed": seed,
                    "domain": group.domain,
                    "stage": _stage(group),
                    "object_type": group.object_type,
                    "group_id": group.group_id,
                    "score": float(scores[index]),
                    "cost": -float(scores[index]),
                    "confidence": float(probabilities[index]),
                    "uncertainty": 1.0 - float(probabilities[index]),
                    "group_margin": margin,
                    "selected": index == selected_index,
                    "score_source": "P3_OBJECT_CONDITIONED_OOF",
                    "model_signature": model_signature,
                    "feature_signature": group.feature_signatures[index],
                    "context_signature": group.context_signature,
                    "feature_uses_truth": False,
                }
                line = json.dumps(
                    record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                score_stream.write(line + "\n")
                score_signature_digest.update(line.encode("utf-8"))
                score_signature_digest.update(b"\n")
                score_record_count += 1
            writer.writerow(
                {
                    "case_key": group.case_key,
                    "fold": group.fold,
                    "domain": group.domain,
                    "stage": _stage(group),
                    "object_type": group.object_type,
                    "group_id": group.group_id,
                    "candidate_count": len(group.candidate_ids),
                    "truth_candidate_count": 1,
                    "selected_candidate_id": selected_id,
                    "selected_truth_equivalent": selected_truth,
                    "best_score": scores[selected_index],
                    "second_score": "" if second_score is None else second_score,
                    "margin": margin,
                    "confidence": probabilities[selected_index],
                    "uncertainty": 1.0 - probabilities[selected_index],
                }
            )
            selected_ids[group.case_key][group.domain].add(selected_id)
            selected_costs[(group.case_key, group.domain, selected_id)] = -float(
                scores[selected_index]
            )
            group_counts[group.domain] += 1
            correct_counts[group.domain] += selected_truth
            if group.domain == "JSG":
                type_group_counts[group.object_type] += 1
                type_correct_counts[group.object_type] += selected_truth
                jsg_confidences.append(float(probabilities[selected_index]))
                jsg_correctness.append(selected_truth)
                if group.truth_is_review:
                    review_truth_count += 1
                    review_truth_selected += selected_truth
                if group.candidate_review_mask[selected_index]:
                    review_selected_count += 1
                    review_selected_correct += selected_truth
            elif "action:SPLIT" in group.candidate_tokens[group.truth_index]:
                split_count += 1
                split_correct += selected_truth
    ece = expected_calibration_error(
        torch.tensor(jsg_confidences, dtype=torch.float32),
        torch.tensor(jsg_correctness, dtype=torch.bool),
    )
    return {
        "score_path": score_path,
        "group_path": group_path,
        "selected_ids": selected_ids,
        "selected_costs": selected_costs,
        "group_counts": group_counts,
        "correct_counts": correct_counts,
        "type_group_counts": type_group_counts,
        "type_correct_counts": type_correct_counts,
        "review_truth_count": review_truth_count,
        "review_truth_selected": review_truth_selected,
        "review_selected_count": review_selected_count,
        "review_selected_correct": review_selected_correct,
        "split_count": split_count,
        "split_correct": split_correct,
        "jsg_ece": ece,
        "probability_sum_max_error": probability_sum_max_error,
        "score_record_count": score_record_count,
        "score_signature": score_signature_digest.hexdigest(),
    }


def _load_selected_candidates(
    contract: Mapping[str, Any],
    selected_ids: Mapping[str, Mapping[str, set[str]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    selected: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for candidate in _read_jsonl(contract["jsg_candidate_path"]):
        if candidate.get("stage") == "PTO_B":
            continue
        case_key = str(candidate["case_key"])
        if str(candidate["candidate_id"]) in selected_ids[case_key]["JSG"]:
            selected[case_key]["JSG"].append(candidate)
    for candidate in _read_jsonl(contract["roadgraph_candidate_path"]):
        case_key = f"{candidate['family']}:{candidate['business_id']}"
        if str(candidate["candidate_id"]) in selected_ids[case_key]["ROADGRAPH"]:
            selected[case_key]["ROADGRAPH"].append(candidate)
    return selected


def _materialize_seed(
    seed_root: Path,
    *,
    seed: int,
    contract: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Sequence[dict[str, Any]]]],
    selected_costs: Mapping[tuple[str, str, str], float],
    score_seconds_by_case: Mapping[str, float],
    config: JSGP3OOFConfig,
    rss_samples: list[int],
) -> dict[str, Any]:
    certificate_path = seed_root / "p05_jsg_p3_certificates.jsonl"
    case_rows: list[dict[str, Any]] = []
    case_evaluations: list[dict[str, Any]] = []
    hard_failure_count = 0
    multi_through_count = 0
    with certificate_path.open("w", encoding="utf-8", newline="\n") as stream:
        for case_key in sorted(contract["case_folds"]):
            started = time.perf_counter()
            family, business_id = case_key.split(":", 1)
            r2_case = contract["r2_cases"][case_key]
            truth_road_path = normalize_runtime_path(r2_case["truth_road_path"]).resolve(
                strict=True
            )
            truth_node_path = normalize_runtime_path(r2_case["truth_node_path"]).resolve(
                strict=True
            )
            _, road_meta = read_vector_payloads(
                truth_road_path, source_role="p3_truth_schema"
            )
            _, node_meta = read_vector_payloads(
                truth_node_path, source_role="p3_truth_schema"
            )
            p0_truth = contract["p0_truth"][case_key][0]
            jsg_rows = list(selected[case_key]["JSG"])
            roadgraph_rows = list(selected[case_key]["ROADGRAPH"])
            pto_a_failures, multi = _validate_pto_a(jsg_rows)
            multi_through_count += multi
            road_edits = [row for row in roadgraph_rows if row["stage"] == "FINAL_ROAD"]
            node_edits = [row for row in roadgraph_rows if row["stage"] == "FINAL_NODE"]
            t05_edits = [row for row in roadgraph_rows if row["stage"] == "T05_NODE"]
            pointer_values = [
                (str(row.get("base_object_id") or ""), str(row.get("pointer_value") or ""))
                for row in roadgraph_rows
                if row["stage"] == "T05_POINTER"
            ]
            roads, nodes, graph_failures = validate_selected_graph(
                road_edits, node_edits, t05_edits, pointer_values
            )
            case_root = seed_root / "cases" / _case_dir(case_key)
            case_root.mkdir(parents=True)
            pto_a_signature = canonical_sha256(sorted(row["candidate_id"] for row in jsg_rows))
            pto_b_signature = canonical_sha256(
                sorted(row["candidate_id"] for row in roadgraph_rows)
            )
            selected_jsg_path = case_root / "selected_jsg.json"
            write_json(
                selected_jsg_path,
                _selected_jsg_payload(case_key, seed, jsg_rows, pto_a_signature),
            )
            evaluation: dict[str, Any] = {}
            carrier_failures: list[str] = []
            selected_road_path = case_root / "selected_road.gpkg"
            selected_node_path = case_root / "selected_node.gpkg"
            if not graph_failures and config.emit_reconstructed_gpkg:
                write_vector_payloads(selected_road_path, roads.values(), meta=road_meta)
                write_vector_payloads(selected_node_path, nodes.values(), meta=node_meta)
                evaluation = evaluate_frcsd(
                    selected_road_path,
                    selected_node_path,
                    truth_road_path,
                    truth_node_path,
                )
                carrier_failures, _ = _carrier_failures(p0_truth, set(roads), set(nodes))
                write_json(case_root / "roadgraph_evaluation.json", evaluation)
            hard_failures = (
                pto_a_failures
                + graph_failures
                + carrier_failures
                + list(evaluation.get("hard_failures") or [])
            )
            hard_failure_count += len(hard_failures)
            pto_a_status = "OPTIMAL" if not pto_a_failures else "INFEASIBLE"
            pto_b_status = "OPTIMAL" if not graph_failures else "INFEASIBLE"
            roadgraph_signature = canonical_sha256(
                {
                    "roads": sorted(row["canonical_payload_sha256"] for row in road_edits),
                    "nodes": sorted(row["canonical_payload_sha256"] for row in node_edits),
                }
            )
            certificate = {
                "case_key": case_key,
                "family": family,
                "business_id": business_id,
                "fold": contract["case_folds"][case_key],
                "seed": seed,
                "pto_a_status": pto_a_status,
                "pto_b_status": pto_b_status,
                "pto_a_objective": sum(
                    selected_costs[(case_key, "JSG", str(row["candidate_id"]))]
                    for row in jsg_rows
                ),
                "pto_b_objective": sum(
                    selected_costs[(case_key, "ROADGRAPH", str(row["candidate_id"]))]
                    for row in roadgraph_rows
                ),
                "pto_a_gap": 0.0 if pto_a_status == "OPTIMAL" else None,
                "pto_b_gap": 0.0 if pto_b_status == "OPTIMAL" else None,
                "pto_a_selection_signature": pto_a_signature,
                "pto_b_selection_signature": pto_b_signature,
                "roadgraph_signature": roadgraph_signature,
                "pto_a_failures": pto_a_failures,
                "pto_b_failures": graph_failures,
                "carrier_failures": carrier_failures,
                "hard_failure_count": len(hard_failures),
                "relaxation": False,
                "content_repair": False,
                "silent_fix": False,
            }
            stream.write(
                json.dumps(
                    certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            )
            evaluation_exact = bool(evaluation) and _evaluation_exact(evaluation)
            materialize_seconds = time.perf_counter() - started
            row = {
                "case_key": case_key,
                "family": family,
                "business_id": business_id,
                "fold": contract["case_folds"][case_key],
                "seed": seed,
                "pto_a_status": pto_a_status,
                "pto_b_status": pto_b_status,
                "pto_a_gap": certificate["pto_a_gap"],
                "pto_b_gap": certificate["pto_b_gap"],
                "road_f1": float(dict(evaluation.get("road_object") or {}).get("f1", 0.0)),
                "node_f1": float(dict(evaluation.get("node_object") or {}).get("f1", 0.0)),
                "directed_topology_f1": float(
                    dict(evaluation.get("directed_topology") or {}).get("f1", 0.0)
                ),
                "direction_accuracy": float(
                    dict(evaluation.get("attributes") or {}).get("direction_accuracy", 0.0)
                ),
                "source_accuracy": float(
                    dict(evaluation.get("attributes") or {}).get("source_accuracy", 0.0)
                ),
                "evaluation_exact": evaluation_exact,
                "hard_failure_count": len(hard_failures),
                "pto_a_selection_signature": pto_a_signature,
                "pto_b_selection_signature": pto_b_signature,
                "roadgraph_signature": roadgraph_signature,
                "score_seconds": float(score_seconds_by_case[case_key]),
                "materialize_evaluate_seconds": materialize_seconds,
                "frozen_candidate_to_roadgraph_seconds": float(
                    score_seconds_by_case[case_key]
                )
                + materialize_seconds,
                "selected_jsg_path": str(selected_jsg_path.resolve()),
                "selected_road_path": str(selected_road_path.resolve()) if evaluation else "",
                "selected_node_path": str(selected_node_path.resolve()) if evaluation else "",
            }
            case_rows.append(row)
            case_evaluations.append({**row, "evaluation": evaluation})
            rss_samples.append(_rss_bytes())
    return {
        "certificate_path": certificate_path,
        "case_rows": case_rows,
        "case_evaluations": case_evaluations,
        "hard_failure_count": hard_failure_count,
        "multi_through_count": multi_through_count,
    }


def _seed_summary(
    *,
    seed: int,
    config: JSGP3OOFConfig,
    scored: Mapping[str, Any],
    materialized: Mapping[str, Any],
    trained: Mapping[str, Any],
    rss_samples: Sequence[int],
) -> dict[str, Any]:
    type_accuracy = {
        object_type: scored["type_correct_counts"][object_type]
        / scored["type_group_counts"][object_type]
        for object_type in sorted(scored["type_group_counts"])
    }
    jsg_accuracy = scored["correct_counts"]["JSG"] / scored["group_counts"]["JSG"]
    roadgraph_accuracy = (
        scored["correct_counts"]["ROADGRAPH"] / scored["group_counts"]["ROADGRAPH"]
    )
    macro = sum(type_accuracy.values()) / max(1, len(type_accuracy))
    review_recall = (
        scored["review_truth_selected"] / scored["review_truth_count"]
        if scored["review_truth_count"]
        else 1.0
    )
    review_precision = (
        scored["review_selected_correct"] / scored["review_selected_count"]
        if scored["review_selected_count"]
        else 1.0
    )
    split_recall = (
        scored["split_correct"] / scored["split_count"] if scored["split_count"] else 1.0
    )
    rows = materialized["case_rows"]
    graph_metrics = _aggregate_graph_metrics(materialized["case_evaluations"])
    score_times = [float(row["score_seconds"]) for row in rows]
    full_times = [float(row["frozen_candidate_to_roadgraph_seconds"]) for row in rows]
    parameter_counts = [
        int(artifact["summary"]["parameter_count"])
        for artifact in trained["fold_artifacts"]
    ]
    model_gate = (
        min(parameter_counts, default=0) >= 500_000
        and max(parameter_counts, default=math.inf) <= 3_000_000
        and scored["score_record_count"] == EXPECTED_CANDIDATE_COUNT
        and scored["probability_sum_max_error"] <= 1e-6
        and float(scored["jsg_ece"]) <= 0.10
    )
    ranking_gate = (
        jsg_accuracy >= 0.90
        and macro >= 0.85
        and min(type_accuracy.values(), default=0.0) >= 0.80
        and review_recall >= 0.90
        and review_precision >= 0.80
        and materialized["multi_through_count"] == 0
    )
    pto_a_optimal = sum(row["pto_a_status"] == "OPTIMAL" for row in rows)
    pto_b_optimal = sum(row["pto_b_status"] == "OPTIMAL" for row in rows)
    minimum_road = min((float(row["road_f1"]) for row in rows), default=0.0)
    exact_cases = sum(bool(row["evaluation_exact"]) for row in rows)
    graph_gate = (
        pto_a_optimal == config.expected_case_count
        and pto_b_optimal == config.expected_case_count
        and graph_metrics["road_f1"] == 1.0
        and graph_metrics["node_f1"] == 1.0
        and minimum_road == 1.0
        and graph_metrics["direction_accuracy"] == 1.0
        and graph_metrics["source_accuracy"] == 1.0
        and split_recall == 1.0
        and exact_cases == config.expected_case_count
        and materialized["hard_failure_count"] == 0
    )
    peak_rss = max(rss_samples, default=0)
    resource_gate = (
        trained["training_wall_seconds"] <= 7200.0
        and peak_rss <= RAM_LIMIT_BYTES
        and trained["max_vram_bytes"] <= VRAM_LIMIT_BYTES
        and _percentile(score_times, 0.95) <= 5.0
        and max(score_times, default=0.0) <= 20.0
        and _percentile(full_times, 0.95) <= 60.0
        and max(full_times, default=0.0) <= 300.0
    )
    return {
        "schema_version": "p05-jsg-p3-seed-summary-v1",
        "seed": seed,
        "case_count": config.expected_case_count,
        "fold_count": config.expected_fold_count,
        "group_count": EXPECTED_GROUP_COUNT,
        "candidate_count": EXPECTED_CANDIDATE_COUNT,
        "jsg_top1_accuracy": jsg_accuracy,
        "jsg_semantic_micro_f1": jsg_accuracy,
        "jsg_semantic_macro_f1": macro,
        "jsg_type_accuracy": type_accuracy,
        "review_unknown_recall": review_recall,
        "review_unknown_precision": review_precision,
        "jsg_ece_10_bin": float(scored["jsg_ece"]),
        "roadgraph_group_top1_accuracy": roadgraph_accuracy,
        "split_recall": split_recall,
        **graph_metrics,
        "worst_case_road_f1": minimum_road,
        "pto_a_optimal_case_count": pto_a_optimal,
        "pto_b_optimal_case_count": pto_b_optimal,
        "exact_case_count": exact_cases,
        "hard_failure_count": materialized["hard_failure_count"],
        "multi_through_auto_selected_count": materialized["multi_through_count"],
        "parameter_count_min": min(parameter_counts, default=0),
        "parameter_count_max": max(parameter_counts, default=0),
        "probability_sum_max_error": scored["probability_sum_max_error"],
        "score_record_count": scored["score_record_count"],
        "score_p95_seconds": _percentile(score_times, 0.95),
        "score_max_seconds": max(score_times, default=0.0),
        "frozen_candidate_to_roadgraph_p95_seconds": _percentile(full_times, 0.95),
        "frozen_candidate_to_roadgraph_max_seconds": max(full_times, default=0.0),
        "training_wall_seconds": trained["training_wall_seconds"],
        "peak_rss_bytes": peak_rss,
        "peak_vram_bytes": trained["max_vram_bytes"],
        "fold_model_state_signatures": {
            str(item["fold"]): item["state_signature"]
            for item in trained["fold_artifacts"]
        },
        "score_signature": scored["score_signature"],
        "pto_a_selection_signature": canonical_sha256(
            {row["case_key"]: row["pto_a_selection_signature"] for row in rows}
        ),
        "pto_b_selection_signature": canonical_sha256(
            {row["case_key"]: row["pto_b_selection_signature"] for row in rows}
        ),
        "roadgraph_signature": canonical_sha256(
            {row["case_key"]: row["roadgraph_signature"] for row in rows}
        ),
        "model_gate_pass": model_gate,
        "ranking_gate_pass": ranking_gate,
        "roadgraph_gate_pass": graph_gate,
        "resource_gate_pass": resource_gate,
        "gate_pass": model_gate and ranking_gate and graph_gate and resource_gate,
        "online_proposal_go": False,
        "production_go": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _run_seed(
    target_root: Path,
    *,
    seed: int,
    contract: Mapping[str, Any],
    config: JSGP3OOFConfig,
) -> dict[str, Any]:
    seed_root = target_root / f"seed_{seed}"
    seed_root.mkdir()
    rss_samples = [_rss_bytes()]
    trained = _train_seed(
        seed_root, seed=seed, contract=contract, config=config, rss_samples=rss_samples
    )
    scored = _write_score_and_group_outputs(
        seed_root,
        seed=seed,
        groups=contract["groups"],
        score_map=trained["score_map"],
    )
    rss_samples.append(_rss_bytes())
    selected = _load_selected_candidates(contract, scored["selected_ids"])
    rss_samples.append(_rss_bytes())
    materialized = _materialize_seed(
        seed_root,
        seed=seed,
        contract=contract,
        selected=selected,
        selected_costs=scored["selected_costs"],
        score_seconds_by_case=trained["score_seconds_by_case"],
        config=config,
        rss_samples=rss_samples,
    )
    summary = _seed_summary(
        seed=seed,
        config=config,
        scored=scored,
        materialized=materialized,
        trained=trained,
        rss_samples=rss_samples,
    )
    case_index_path = seed_root / "p05_jsg_p3_case_index.csv"
    summary_path = seed_root / "p05_jsg_p3_seed_summary.json"
    write_csv(case_index_path, materialized["case_rows"], list(materialized["case_rows"][0]))
    write_json(summary_path, summary)
    outputs = {
        "scores": output_record(scored["score_path"]),
        "group_metrics": output_record(scored["group_path"]),
        "case_index": output_record(case_index_path),
        "certificates": output_record(materialized["certificate_path"]),
        "summary": output_record(summary_path),
    }
    seed_manifest = {
        "schema_version": "p05-jsg-p3-seed-manifest-v1",
        "seed": seed,
        "status": "seed_completed",
        "context_dataset_manifest_path": str(contract["context_manifest_path"]),
        "context_dataset_manifest_sha256": sha256_file(contract["context_manifest_path"]),
        "fold_models": [
            {
                key: value
                for key, value in artifact.items()
                if key not in {"summary"}
            }
            for artifact in trained["fold_artifacts"]
        ],
        "outputs": outputs,
        "online_proposal_go": False,
        "production_go": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = seed_root / "p05_jsg_p3_oof_manifest.json"
    write_json(manifest_path, seed_manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


def run_jsg_p3_oof(config: JSGP3OOFConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    contract = _load_contract(config)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    seed_summaries = [
        _run_seed(target_root, seed=seed, contract=contract, config=config)
        for seed in config.seeds
    ]
    total_training_wall = sum(
        float(summary["training_wall_seconds"]) for summary in seed_summaries
    )
    all_seed_gate = all(bool(summary["gate_pass"]) for summary in seed_summaries)
    all_graph_safe = all(
        bool(summary["roadgraph_gate_pass"]) for summary in seed_summaries
    )
    decision = (
        "P3_SCORER_GO"
        if all_seed_gate and total_training_wall <= 21600.0
        else "P3_MODEL_NO_GO"
        if all_graph_safe
        else "P3_UPSTREAM_OR_IMPLEMENTATION_BLOCKED"
    )
    comparison = {
        "schema_version": "p05-jsg-p3-seed-comparison-v1",
        "seeds": list(config.seeds),
        "seed_gate_pass": {
            str(summary["seed"]): bool(summary["gate_pass"])
            for summary in seed_summaries
        },
        "seed_metrics": {
            str(summary["seed"]): {
                key: summary[key]
                for key in (
                    "jsg_top1_accuracy",
                    "jsg_semantic_macro_f1",
                    "review_unknown_recall",
                    "review_unknown_precision",
                    "jsg_ece_10_bin",
                    "road_f1",
                    "node_f1",
                )
            }
            for summary in seed_summaries
        },
        "all_seed_gate_pass": all_seed_gate,
        "total_training_wall_seconds": total_training_wall,
        "total_training_resource_gate_pass": total_training_wall <= 21600.0,
        "decision": decision,
        "online_proposal_go": False,
        "production_go": False,
    }
    comparison_path = target_root / "seed_comparison.json"
    write_json(comparison_path, comparison)
    manifest = {
        "schema_version": "p05-jsg-p3-oof-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "p3_oof_completed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "context_dataset_manifest_path": str(contract["context_manifest_path"]),
        "context_dataset_manifest_sha256": sha256_file(contract["context_manifest_path"]),
        "p2_dataset_manifest_path": str(contract["dataset_manifest_path"]),
        "p2_dataset_manifest_sha256": sha256_file(contract["dataset_manifest_path"]),
        "parameters": {
            key: value
            for key, value in vars(config).items()
            if key
            not in {
                "context_dataset_run_root",
                "p2_dataset_run_root",
                "p1_candidate_run_root",
                "p1_oracle_run_root",
                "p0_truth_run_root",
                "r2_oracle_run_root",
                "output_root",
            }
        },
        "environment": _environment(),
        "outputs": {
            "seed_comparison": output_record(comparison_path),
            **{
                f"seed_{summary['seed']}_manifest": output_record(
                    Path(summary["manifest_path"])
                )
                for summary in seed_summaries
            },
        },
        "decision": decision,
        "determinism_audit_pending": True,
        "online_proposal_go": False,
        "production_go": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
    }
    manifest_path = target_root / "p05_jsg_p3_oof_manifest.json"
    write_json(manifest_path, manifest)
    return {
        **comparison,
        "seed_summaries": seed_summaries,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
    }


__all__ = ["run_jsg_p3_oof"]
