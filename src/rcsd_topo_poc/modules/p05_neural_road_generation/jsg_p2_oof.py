from __future__ import annotations

import csv
import gc
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_compiler import _carrier_failures
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_solver import _load_p0_truth
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_features import (
    score_confidence,
    v0_weight_contract,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_linear import (
    fit_oof_additive_models,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    JSGP2OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import _environment, _rss_bytes
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    JSGP1OracleConfig,
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


SCORERS = ("V0", "V1")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield row


def _verified_output(
    outputs: Mapping[str, Any], role: str, *, strict_hashes: bool
) -> Path:
    record = dict(outputs.get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"artifact hash mismatch: {role}")
    return path


def _case_dir(case_key: str) -> str:
    return canonical_sha256(case_key)[:20]


def _grouped_rows(path: Path) -> Iterator[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    active_key: tuple[str, str, str] | None = None
    active: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in _read_jsonl(path):
        key = (str(row["domain"]), str(row["case_key"]), str(row["group_id"]))
        if active_key is None:
            active_key = key
        if key != active_key:
            if active_key in seen:
                raise ValueError(f"feature group is not contiguous: {active_key}")
            seen.add(active_key)
            yield active_key, active
            active_key = key
            active = []
        active.append(row)
    if active_key is not None:
        yield active_key, active


def _softmax_confidences(costs: list[float]) -> list[float]:
    if not costs:
        return []
    best = min(costs)
    values = [math.exp(-min(60.0, max(0.0, cost - best))) for cost in costs]
    total = sum(values)
    return [value / total for value in values]


def _selected_jsg_payload(
    case_key: str,
    scorer: str,
    rows: list[dict[str, Any]],
    selection_signature: str,
) -> dict[str, Any]:
    return {
        "schema_version": "p05-jsg-p2-selected-v1",
        "case_key": case_key,
        "scorer": scorer,
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
        "selection_signature": selection_signature,
        "label_only": False,
        "content_repair": False,
        "silent_fix": False,
    }


def _validate_pto_a(rows: list[dict[str, Any]]) -> tuple[list[str], int]:
    selected_groups = {str(row["group_id"]) for row in rows}
    failures: list[str] = []
    through: Counter[str] = Counter()
    for row in rows:
        for dependency in row.get("dependencies") or []:
            if str(dependency) not in selected_groups:
                failures.append(f"{row['candidate_id']} missing dependency {dependency}")
        payload = dict(row.get("payload") or {})
        if (
            row.get("object_type") == "RELATION"
            and payload.get("structural_role") == "THROUGH"
            and payload.get("state") == "PUBLISHABLE"
        ):
            through[str(payload.get("junction_id") or "")] += 1
    multi = sum(value > 1 for value in through.values())
    if multi:
        failures.append("multiple publishable THROUGH relations selected")
    return failures, multi


def _aggregate_graph_metrics(case_rows: list[dict[str, Any]]) -> dict[str, float]:
    truth_roads = candidate_roads = matched_roads = 0
    truth_nodes = candidate_nodes = matched_nodes = 0
    attribute_weight = 0
    direction = source = 0.0
    for row in case_rows:
        evaluation = dict(row.get("evaluation") or {})
        counts = dict(evaluation.get("counts") or {})
        truth_roads += int(counts.get("truth_roads") or 0)
        candidate_roads += int(counts.get("candidate_roads") or 0)
        matched_roads += int(counts.get("matched_roads") or 0)
        truth_nodes += int(counts.get("truth_nodes") or 0)
        candidate_nodes += int(counts.get("candidate_nodes") or 0)
        matched_nodes += int(counts.get("matched_nodes") or 0)
        weight = int(counts.get("matched_roads") or 0)
        attributes = dict(evaluation.get("attributes") or {})
        attribute_weight += weight
        direction += weight * float(attributes.get("direction_accuracy") or 0.0)
        source += weight * float(attributes.get("source_accuracy") or 0.0)

    def f1(matched: int, candidate: int, truth: int) -> float:
        precision = matched / candidate if candidate else (1.0 if not truth else 0.0)
        recall = matched / truth if truth else (1.0 if not candidate else 0.0)
        return 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "road_f1": f1(matched_roads, candidate_roads, truth_roads),
        "node_f1": f1(matched_nodes, candidate_nodes, truth_nodes),
        "direction_accuracy": direction / attribute_weight if attribute_weight else 0.0,
        "source_accuracy": source / attribute_weight if attribute_weight else 0.0,
    }


def _load_contract(config: JSGP2OOFConfig) -> dict[str, Any]:
    dataset_root = normalize_runtime_path(config.dataset_run_root).resolve(strict=True)
    dataset_manifest_path = dataset_root / "p05_jsg_p2_dataset_manifest.json"
    dataset_manifest = _read_json(dataset_manifest_path)
    if dataset_manifest.get("status") != "dataset_passed":
        raise ValueError("P2 dataset did not pass")
    dataset_outputs = dict(dataset_manifest.get("outputs") or {})
    feature_path = _verified_output(
        dataset_outputs, "features", strict_hashes=config.strict_hashes
    )
    case_index_path = _verified_output(
        dataset_outputs, "case_index", strict_hashes=config.strict_hashes
    )
    leakage_path = _verified_output(
        dataset_outputs, "leakage_audit", strict_hashes=config.strict_hashes
    )
    if not bool(_read_json(leakage_path).get("passed")):
        raise ValueError("P2 dataset leakage audit failed")
    case_rows = _read_csv(case_index_path)
    if len(case_rows) != config.expected_case_count:
        raise ValueError("P2 dataset Case scope mismatch")
    case_folds = {row["case_key"]: int(row["fold"]) for row in case_rows}
    if set(case_folds.values()) != set(range(config.expected_fold_count)):
        raise ValueError("P2 dataset fold scope mismatch")

    candidate_root = normalize_runtime_path(config.p1_candidate_run_root).resolve(strict=True)
    candidate_manifest_path = candidate_root / "p05_jsg_p1_candidate_manifest.json"
    if config.strict_hashes and sha256_file(candidate_manifest_path) != str(
        dataset_manifest.get("p1_candidate_manifest_sha256") or ""
    ):
        raise ValueError("P2/P1 candidate manifest mismatch")
    candidate_manifest = _read_json(candidate_manifest_path)
    jsg_candidate_path = _verified_output(
        dict(candidate_manifest.get("outputs") or {}),
        "candidates",
        strict_hashes=config.strict_hashes,
    )

    oracle_root = normalize_runtime_path(config.p1_oracle_run_root).resolve(strict=True)
    oracle_manifest_path = oracle_root / "p05_jsg_p1_solve_manifest.json"
    if config.strict_hashes and sha256_file(oracle_manifest_path) != str(
        dataset_manifest.get("p1_oracle_manifest_sha256") or ""
    ):
        raise ValueError("P2/P1 Oracle manifest mismatch")
    oracle_manifest = _read_json(oracle_manifest_path)
    nested_manifest_path = normalize_runtime_path(
        str(oracle_manifest.get("nested_pto_b_manifest_path") or "")
    ).resolve(strict=True)
    nested_manifest = _read_json(nested_manifest_path)
    roadgraph_candidate_manifest_path = normalize_runtime_path(
        str(nested_manifest.get("candidate_manifest_path") or "")
    ).resolve(strict=True)
    roadgraph_candidate_manifest = _read_json(roadgraph_candidate_manifest_path)
    roadgraph_candidate_path = _verified_output(
        dict(roadgraph_candidate_manifest.get("outputs") or {}),
        "candidates",
        strict_hashes=config.strict_hashes,
    )

    r2_root = normalize_runtime_path(config.r2_oracle_run_root).resolve(strict=True)
    r2_manifest_path = r2_root / "p05_r2_oracle_manifest.json"
    r2_manifest = _read_json(r2_manifest_path)
    if r2_manifest.get("status") != "gate1_passed":
        raise ValueError("R2 Oracle run did not pass")
    r2_case_path = _verified_output(
        dict(r2_manifest.get("outputs") or {}), "case_index", strict_hashes=config.strict_hashes
    )
    r2_cases = {
        f"{row['family']}:{row['business_id']}": row for row in _read_csv(r2_case_path)
    }
    if set(r2_cases) != set(case_folds):
        raise ValueError("P2/R2 Case scope differs")

    p1_config = JSGP1OracleConfig(
        candidate_run_root=config.p1_candidate_run_root,
        p0_truth_run_root=config.p0_truth_run_root,
        r2_oracle_run_root=config.r2_oracle_run_root,
        output_root=config.output_root,
        run_id="p2-read-only-contract",
        expected_case_count=config.expected_case_count,
        strict_hashes=config.strict_hashes,
        emit_reconstructed_gpkg=False,
    )
    _, _, p0_truth = _load_p0_truth(p1_config)
    if set(p0_truth) != set(case_folds):
        raise ValueError("P2/P0 JSG truth Case scope differs")
    return {
        "dataset_manifest_path": dataset_manifest_path,
        "dataset_manifest": dataset_manifest,
        "feature_path": feature_path,
        "case_rows": case_rows,
        "case_folds": case_folds,
        "jsg_candidate_path": jsg_candidate_path,
        "roadgraph_candidate_path": roadgraph_candidate_path,
        "r2_cases": r2_cases,
        "p0_truth": p0_truth,
        "p1_candidate_manifest_path": candidate_manifest_path,
        "p1_oracle_manifest_path": oracle_manifest_path,
        "roadgraph_candidate_manifest_path": roadgraph_candidate_manifest_path,
        "r2_manifest_path": r2_manifest_path,
    }


def run_jsg_p2_oof(config: JSGP2OOFConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    contract = _load_contract(config)
    dataset_manifest_sha = sha256_file(contract["dataset_manifest_path"])
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    model_root = target_root / "p05_jsg_p2_models"
    model_root.mkdir()
    v0_model = v0_weight_contract()
    v0_model["model_signature"] = canonical_sha256(v0_model)
    v0_model_path = model_root / "v0.json"
    write_json(v0_model_path, v0_model)
    train_started = time.perf_counter()
    train_cpu_started = time.process_time()
    models = fit_oof_additive_models(
        _read_jsonl(contract["feature_path"]),
        fold_count=config.expected_fold_count,
        smoothing=config.smoothing,
        dataset_manifest_sha256=dataset_manifest_sha,
        all_case_folds=contract["case_folds"],
    )
    model_paths: dict[int, Path] = {}
    for fold, model in models.items():
        path = model_root / f"fold_{fold}.json"
        write_json(path, model.to_dict())
        model_paths[fold] = path
    training_wall_seconds = time.perf_counter() - train_started
    training_cpu_seconds = time.process_time() - train_cpu_started

    score_path = target_root / "p05_jsg_p2_scores.jsonl"
    group_path = target_root / "p05_jsg_p2_group_metrics.csv"
    score_stream = score_path.open("w", encoding="utf-8", newline="\n")
    group_stream = group_path.open("w", encoding="utf-8-sig", newline="")
    group_fields = [
        "case_key",
        "fold",
        "domain",
        "stage",
        "object_type",
        "group_id",
        "scorer",
        "candidate_count",
        "truth_candidate_count",
        "selected_candidate_id",
        "selected_truth_equivalent",
        "best_cost",
        "second_cost",
        "margin",
        "confidence",
        "uncertainty",
    ]
    group_writer = csv.DictWriter(group_stream, fieldnames=group_fields)
    group_writer.writeheader()
    selected_ids: dict[str, dict[str, dict[str, set[str]]]] = {
        scorer: defaultdict(lambda: defaultdict(set)) for scorer in SCORERS
    }
    selected_costs: dict[tuple[str, str, str, str], float] = {}
    group_counts: Counter[tuple[str, str]] = Counter()
    correct_counts: Counter[tuple[str, str]] = Counter()
    type_group_counts: Counter[tuple[str, str]] = Counter()
    type_correct_counts: Counter[tuple[str, str]] = Counter()
    review_counts: Counter[str] = Counter()
    review_correct_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    split_correct_counts: Counter[str] = Counter()
    score_seconds_by_case: Counter[str] = Counter()
    score_signature_rows: dict[str, list[tuple[str, str, float]]] = {
        scorer: [] for scorer in SCORERS
    }
    score_record_counts: Counter[str] = Counter()
    explanation_record_counts: Counter[str] = Counter()
    unknown_feature_occurrence_counts: Counter[str] = Counter()
    unknown_feature_sets: dict[str, set[str]] = {scorer: set() for scorer in SCORERS}
    v1_unknown_occurrence_by_fold: Counter[int] = Counter()
    v1_unknown_unique_by_fold: dict[int, set[str]] = defaultdict(set)
    rss_samples = [_rss_bytes()]
    try:
        for (domain, case_key, group_id), rows in _grouped_rows(contract["feature_path"]):
            group_started = time.perf_counter()
            fold = int(rows[0]["fold"])
            if any(int(row["fold"]) != fold for row in rows):
                raise ValueError(f"mixed fold group: {case_key}/{group_id}")
            model = models[fold]
            for scorer in SCORERS:
                costs = [
                    float(row["v0_cost"])
                    if scorer == "V0"
                    else -model.score(list(row["feature_tokens"]))
                    for row in rows
                ]
                ordered = sorted(
                    range(len(rows)), key=lambda index: (costs[index], rows[index]["candidate_id"])
                )
                best_index = ordered[0]
                second_cost = costs[ordered[1]] if len(ordered) > 1 else None
                selected = rows[best_index]
                confidence, uncertainty, margin = score_confidence(
                    costs[best_index], second_cost
                )
                probabilities = _softmax_confidences(costs)
                model_signature = (
                    str(v0_model["model_signature"])
                    if scorer == "V0"
                    else model.model_signature
                )
                for index, row in enumerate(rows):
                    feature_tokens = tuple(row["feature_tokens"])
                    feature_weights = (
                        v0_model["feature_weights"]
                        if scorer == "V0"
                        else model.feature_weights
                    )
                    unknown_tokens = sorted(
                        token for token in set(feature_tokens) if token not in feature_weights
                    )
                    score_record = {
                        "candidate_id": row["candidate_id"],
                        "case_key": case_key,
                        "fold": fold,
                        "domain": domain,
                        "stage": row["stage"],
                        "object_type": row["object_type"],
                        "group_id": group_id,
                        "cost": costs[index],
                        "confidence": probabilities[index],
                        "uncertainty": 1.0 - probabilities[index],
                        "group_margin": margin,
                        "selected": index == best_index,
                        "score_source": f"{scorer}_{'EXPLICIT' if scorer == 'V0' else 'LINEAR_OOF'}",
                        "model_signature": model_signature,
                        "feature_signature": row["feature_signature"],
                        "unknown_feature_count": len(unknown_tokens),
                        "explanation_reconstructable": True,
                    }
                    score_stream.write(
                        json.dumps(
                            score_record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    score_signature_rows[scorer].append(
                        (case_key, str(row["candidate_id"]), round(costs[index], 12))
                    )
                    score_record_counts[scorer] += 1
                    explanation_record_counts[scorer] += 1
                    unknown_feature_occurrence_counts[scorer] += len(unknown_tokens)
                    unknown_feature_sets[scorer].update(unknown_tokens)
                    if scorer == "V1":
                        v1_unknown_occurrence_by_fold[fold] += len(unknown_tokens)
                        v1_unknown_unique_by_fold[fold].update(unknown_tokens)
                truth_count = sum(bool(row["truth_equivalent"]) for row in rows)
                selected_truth = bool(selected["truth_equivalent"])
                object_type = str(rows[0]["object_type"])
                group_writer.writerow(
                    {
                        "case_key": case_key,
                        "fold": fold,
                        "domain": domain,
                        "stage": rows[0]["stage"],
                        "object_type": object_type,
                        "group_id": group_id,
                        "scorer": scorer,
                        "candidate_count": len(rows),
                        "truth_candidate_count": truth_count,
                        "selected_candidate_id": selected["candidate_id"],
                        "selected_truth_equivalent": selected_truth,
                        "best_cost": costs[best_index],
                        "second_cost": "" if second_cost is None else second_cost,
                        "margin": margin,
                        "confidence": confidence,
                        "uncertainty": uncertainty,
                    }
                )
                selected_ids[scorer][case_key][domain].add(str(selected["candidate_id"]))
                selected_costs[(scorer, case_key, domain, str(selected["candidate_id"]))] = costs[
                    best_index
                ]
                group_counts[(scorer, domain)] += 1
                correct_counts[(scorer, domain)] += selected_truth
                if domain == "JSG":
                    type_group_counts[(scorer, object_type)] += 1
                    type_correct_counts[(scorer, object_type)] += selected_truth
                    truth_tokens = {
                        token
                        for row in rows
                        if bool(row["truth_equivalent"])
                        for token in row["feature_tokens"]
                    }
                    if truth_tokens & {"payload:state=REVIEW", "payload:state=UNKNOWN"}:
                        review_counts[scorer] += 1
                        review_correct_counts[scorer] += selected_truth
                elif any(
                    "action:SPLIT" in row["feature_tokens"] and bool(row["truth_equivalent"])
                    for row in rows
                ):
                    split_counts[scorer] += 1
                    split_correct_counts[scorer] += selected_truth
            score_seconds_by_case[case_key] += time.perf_counter() - group_started
    finally:
        score_stream.close()
        group_stream.close()
    rss_samples.append(_rss_bytes())

    selected_candidates: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        scorer: defaultdict(lambda: defaultdict(list)) for scorer in SCORERS
    }
    for candidate in _read_jsonl(contract["jsg_candidate_path"]):
        if candidate.get("stage") == "PTO_B":
            continue
        case_key = str(candidate["case_key"])
        candidate_id = str(candidate["candidate_id"])
        for scorer in SCORERS:
            if candidate_id in selected_ids[scorer][case_key]["JSG"]:
                selected_candidates[scorer][case_key]["JSG"].append(candidate)
    rss_samples.append(_rss_bytes())
    for candidate in _read_jsonl(contract["roadgraph_candidate_path"]):
        case_key = f"{candidate['family']}:{candidate['business_id']}"
        candidate_id = str(candidate["candidate_id"])
        for scorer in SCORERS:
            if candidate_id in selected_ids[scorer][case_key]["ROADGRAPH"]:
                selected_candidates[scorer][case_key]["ROADGRAPH"].append(candidate)
    rss_samples.append(_rss_bytes())

    certificate_path = target_root / "p05_jsg_p2_certificates.jsonl"
    certificate_stream = certificate_path.open("w", encoding="utf-8", newline="\n")
    case_rows: list[dict[str, Any]] = []
    case_evaluations: dict[str, list[dict[str, Any]]] = {scorer: [] for scorer in SCORERS}
    multi_through: Counter[str] = Counter()
    scorer_hard_failures: Counter[str] = Counter()
    materialize_seconds: Counter[tuple[str, str]] = Counter()
    for case_key in sorted(contract["case_folds"]):
        family, business_id = case_key.split(":", 1)
        r2_case = contract["r2_cases"][case_key]
        truth_road_path = normalize_runtime_path(r2_case["truth_road_path"]).resolve(strict=True)
        truth_node_path = normalize_runtime_path(r2_case["truth_node_path"]).resolve(strict=True)
        _, road_meta = read_vector_payloads(truth_road_path, source_role="p2_truth_schema")
        _, node_meta = read_vector_payloads(truth_node_path, source_role="p2_truth_schema")
        p0_truth = contract["p0_truth"][case_key][0]
        for scorer in SCORERS:
            materialize_started = time.perf_counter()
            jsg_rows = selected_candidates[scorer][case_key]["JSG"]
            roadgraph_rows = selected_candidates[scorer][case_key]["ROADGRAPH"]
            pto_a_failures, multi = _validate_pto_a(jsg_rows)
            multi_through[scorer] += multi
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
            case_root = target_root / "cases" / _case_dir(case_key) / scorer
            case_root.mkdir(parents=True)
            pto_a_selection_signature = canonical_sha256(
                sorted(row["candidate_id"] for row in jsg_rows)
            )
            pto_b_selection_signature = canonical_sha256(
                sorted(row["candidate_id"] for row in roadgraph_rows)
            )
            selected_jsg_path = case_root / "selected_jsg.json"
            write_json(
                selected_jsg_path,
                _selected_jsg_payload(
                    case_key, scorer, jsg_rows, pto_a_selection_signature
                ),
            )
            evaluation: dict[str, Any] = {}
            carrier_failures: list[str] = []
            selected_road_path = case_root / "selected_road.gpkg"
            selected_node_path = case_root / "selected_node.gpkg"
            if not graph_failures and config.emit_reconstructed_gpkg:
                write_vector_payloads(selected_road_path, roads.values(), meta=road_meta)
                write_vector_payloads(selected_node_path, nodes.values(), meta=node_meta)
                evaluation = evaluate_frcsd(
                    selected_road_path, selected_node_path, truth_road_path, truth_node_path
                )
                carrier_failures, _ = _carrier_failures(p0_truth, set(roads), set(nodes))
                write_json(case_root / "roadgraph_evaluation.json", evaluation)
            hard_failures = (
                pto_a_failures
                + graph_failures
                + carrier_failures
                + list(evaluation.get("hard_failures") or [])
            )
            scorer_hard_failures[scorer] += len(hard_failures)
            pto_a_status = "OPTIMAL" if not pto_a_failures else "INFEASIBLE"
            pto_b_status = "OPTIMAL" if not graph_failures else "INFEASIBLE"
            objective_a = sum(
                selected_costs[(scorer, case_key, "JSG", str(row["candidate_id"]))]
                for row in jsg_rows
            )
            objective_b = sum(
                selected_costs[(scorer, case_key, "ROADGRAPH", str(row["candidate_id"]))]
                for row in roadgraph_rows
            )
            certificate = {
                "case_key": case_key,
                "family": family,
                "business_id": business_id,
                "fold": contract["case_folds"][case_key],
                "scorer": scorer,
                "pto_a_status": pto_a_status,
                "pto_b_status": pto_b_status,
                "pto_a_objective": objective_a,
                "pto_b_objective": objective_b,
                "pto_a_gap": 0.0 if pto_a_status == "OPTIMAL" else None,
                "pto_b_gap": 0.0 if pto_b_status == "OPTIMAL" else None,
                "pto_a_selection_signature": pto_a_selection_signature,
                "pto_b_selection_signature": pto_b_selection_signature,
                "roadgraph_signature": canonical_sha256(
                    {
                        "roads": sorted(
                            row["canonical_payload_sha256"] for row in road_edits
                        ),
                        "nodes": sorted(
                            row["canonical_payload_sha256"] for row in node_edits
                        ),
                    }
                ),
                "pto_a_failures": pto_a_failures,
                "pto_b_failures": graph_failures,
                "carrier_failures": carrier_failures,
                "hard_failure_count": len(hard_failures),
                "relaxation": False,
                "content_repair": False,
                "silent_fix": False,
            }
            certificate_stream.write(
                json.dumps(certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
            evaluation_exact = bool(evaluation) and _evaluation_exact(evaluation)
            materialize_seconds[(scorer, case_key)] = time.perf_counter() - materialize_started
            row = {
                "case_key": case_key,
                "family": family,
                "business_id": business_id,
                "fold": contract["case_folds"][case_key],
                "scorer": scorer,
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
                "pto_a_selection_signature": pto_a_selection_signature,
                "pto_b_selection_signature": pto_b_selection_signature,
                "roadgraph_signature": certificate["roadgraph_signature"],
                "score_seconds": score_seconds_by_case[case_key],
                "materialize_evaluate_seconds": materialize_seconds[(scorer, case_key)],
                "p2_incremental_seconds": score_seconds_by_case[case_key]
                + materialize_seconds[(scorer, case_key)],
                "selected_jsg_path": str(selected_jsg_path.resolve()),
                "selected_road_path": str(selected_road_path.resolve()) if evaluation else "",
                "selected_node_path": str(selected_node_path.resolve()) if evaluation else "",
            }
            case_rows.append(row)
            case_evaluations[scorer].append({**row, "evaluation": evaluation})
            rss_samples.append(_rss_bytes())
    certificate_stream.close()
    gc.collect()
    rss_samples.append(_rss_bytes())

    scorer_summaries: dict[str, dict[str, Any]] = {}
    for scorer in SCORERS:
        rows = [row for row in case_rows if row["scorer"] == scorer]
        graph_metrics = _aggregate_graph_metrics(case_evaluations[scorer])
        type_accuracy = {
            object_type: type_correct_counts[(scorer, object_type)]
            / type_group_counts[(scorer, object_type)]
            for scorer_name, object_type in sorted(type_group_counts)
            if scorer_name == scorer
        }
        jsg_accuracy = correct_counts[(scorer, "JSG")] / group_counts[(scorer, "JSG")]
        roadgraph_accuracy = correct_counts[(scorer, "ROADGRAPH")] / group_counts[
            (scorer, "ROADGRAPH")
        ]
        macro = sum(type_accuracy.values()) / len(type_accuracy) if type_accuracy else 0.0
        review_recall = (
            review_correct_counts[scorer] / review_counts[scorer]
            if review_counts[scorer]
            else 1.0
        )
        split_recall = (
            split_correct_counts[scorer] / split_counts[scorer]
            if split_counts[scorer]
            else 1.0
        )
        score_times = [float(row["score_seconds"]) for row in rows]
        incremental = [float(row["p2_incremental_seconds"]) for row in rows]
        pto_a_optimal = sum(row["pto_a_status"] == "OPTIMAL" for row in rows)
        pto_b_optimal = sum(row["pto_b_status"] == "OPTIMAL" for row in rows)
        minimum_road = min((float(row["road_f1"]) for row in rows), default=0.0)
        ranking_gate = (
            jsg_accuracy >= 0.90
            and min(type_accuracy.values(), default=0.0) >= 0.80
            and jsg_accuracy >= 0.90
            and macro >= 0.85
            and review_recall >= 0.90
        )
        graph_gate = (
            pto_a_optimal == config.expected_case_count
            and pto_b_optimal == config.expected_case_count
            and graph_metrics["road_f1"] >= 0.85
            and graph_metrics["node_f1"] >= 0.90
            and minimum_road >= 0.70
            and graph_metrics["direction_accuracy"] >= 0.95
            and graph_metrics["source_accuracy"] >= 0.95
            and split_recall >= 0.70
            and scorer_hard_failures[scorer] == 0
        )
        resource_gate = (
            _percentile(score_times, 0.95) <= 5.0
            and max(score_times, default=0.0) <= 20.0
            and _percentile(incremental, 0.95) <= 60.0
            and max(incremental, default=0.0) <= 300.0
        )
        scorer_summaries[scorer] = {
            "jsg_top1_accuracy": jsg_accuracy,
            "jsg_semantic_micro_f1": jsg_accuracy,
            "jsg_semantic_macro_f1": macro,
            "jsg_type_accuracy": type_accuracy,
            "review_unknown_recall": review_recall,
            "roadgraph_group_top1_accuracy": roadgraph_accuracy,
            "split_recall": split_recall,
            **graph_metrics,
            "worst_case_road_f1": minimum_road,
            "pto_a_optimal_case_count": pto_a_optimal,
            "pto_b_optimal_case_count": pto_b_optimal,
            "exact_case_count": sum(bool(row["evaluation_exact"]) for row in rows),
            "hard_failure_count": scorer_hard_failures[scorer],
            "multi_through_auto_selected_count": multi_through[scorer],
            "score_p95_seconds": _percentile(score_times, 0.95),
            "score_max_seconds": max(score_times, default=0.0),
            "p2_incremental_p95_seconds": _percentile(incremental, 0.95),
            "p2_incremental_max_seconds": max(incremental, default=0.0),
            "score_signature": canonical_sha256(sorted(score_signature_rows[scorer])),
            "score_record_count": score_record_counts[scorer],
            "explanation_record_count": explanation_record_counts[scorer],
            "explanation_coverage_ratio": (
                explanation_record_counts[scorer] / score_record_counts[scorer]
                if score_record_counts[scorer]
                else 0.0
            ),
            "unknown_feature_occurrence_count": unknown_feature_occurrence_counts[scorer],
            "unknown_feature_unique_count": len(unknown_feature_sets[scorer]),
            "pto_a_selection_signature": canonical_sha256(
                {row["case_key"]: row["pto_a_selection_signature"] for row in rows}
            ),
            "pto_b_selection_signature": canonical_sha256(
                {row["case_key"]: row["pto_b_selection_signature"] for row in rows}
            ),
            "roadgraph_signature": canonical_sha256(
                {row["case_key"]: row["roadgraph_signature"] for row in rows}
            ),
            "ranking_gate_pass": ranking_gate,
            "roadgraph_gate_pass": graph_gate,
            "resource_gate_pass": resource_gate,
            "gate_pass": ranking_gate and graph_gate and resource_gate,
        }

    v0_pass = bool(scorer_summaries["V0"]["gate_pass"])
    v1_improvement = float(scorer_summaries["V1"]["road_f1"]) - float(
        scorer_summaries["V0"]["road_f1"]
    )
    v1_pass = bool(scorer_summaries["V1"]["gate_pass"]) and (
        v0_pass or v1_improvement >= 0.05
    )
    p2_go = v0_pass or v1_pass
    p3_justified = (
        not p2_go
        and scorer_summaries["V1"]["pto_a_optimal_case_count"]
        == config.expected_case_count
        and scorer_summaries["V1"]["pto_b_optimal_case_count"]
        == config.expected_case_count
        and scorer_summaries["V1"]["hard_failure_count"] == 0
    )
    summary = {
        "schema_version": "p05-jsg-p2-oof-summary-v1",
        "case_count": config.expected_case_count,
        "fold_count": config.expected_fold_count,
        "candidate_count": sum(int(row["jsg_candidate_count"]) + int(row["roadgraph_candidate_count"]) for row in contract["case_rows"]),
        "scorers": scorer_summaries,
        "v1_unknown_feature_audit_by_fold": {
            str(fold): {
                "occurrence_count": v1_unknown_occurrence_by_fold[fold],
                "unique_count": len(v1_unknown_unique_by_fold[fold]),
            }
            for fold in range(config.expected_fold_count)
        },
        "v1_road_f1_improvement_over_v0": v1_improvement,
        "training_wall_seconds": training_wall_seconds,
        "training_cpu_seconds": training_cpu_seconds,
        "peak_rss_bytes": max(rss_samples, default=0),
        "p2_baseline_go": p2_go,
        "p3_scoring_model_justified": p3_justified,
        "decision": (
            "P2_BASELINE_GO"
            if p2_go
            else "P2_COMPLETE_P3_JUSTIFIED"
            if p3_justified
            else "P2_NO_GO_UPSTREAM_OR_CONSTRAINT_BLOCKER"
        ),
        "historical_proposal_replay_seconds": 5751.192058,
        "online_proposal_go": False,
        "gpu_required": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
    }
    case_index_path = target_root / "p05_jsg_p2_case_index.csv"
    summary_path = target_root / "p05_jsg_p2_oof_summary.json"
    write_csv(case_index_path, case_rows, list(case_rows[0]))
    write_json(summary_path, summary)
    outputs = {
        "scores": output_record(score_path),
        "group_metrics": output_record(group_path),
        "case_index": output_record(case_index_path),
        "certificates": output_record(certificate_path),
        "summary": output_record(summary_path),
        "model_v0": output_record(v0_model_path),
        **{
            f"model_fold_{fold}": output_record(path) for fold, path in sorted(model_paths.items())
        },
    }
    manifest = {
        "schema_version": "p05-jsg-p2-oof-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "p2_completed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_manifest_path": str(contract["dataset_manifest_path"]),
        "dataset_manifest_sha256": dataset_manifest_sha,
        "p1_candidate_manifest_path": str(contract["p1_candidate_manifest_path"]),
        "p1_candidate_manifest_sha256": sha256_file(contract["p1_candidate_manifest_path"]),
        "p1_oracle_manifest_path": str(contract["p1_oracle_manifest_path"]),
        "p1_oracle_manifest_sha256": sha256_file(contract["p1_oracle_manifest_path"]),
        "roadgraph_candidate_manifest_path": str(
            contract["roadgraph_candidate_manifest_path"]
        ),
        "roadgraph_candidate_manifest_sha256": sha256_file(
            contract["roadgraph_candidate_manifest_path"]
        ),
        "r2_manifest_path": str(contract["r2_manifest_path"]),
        "r2_manifest_sha256": sha256_file(contract["r2_manifest_path"]),
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "expected_fold_count": config.expected_fold_count,
            "smoothing": config.smoothing,
            "strict_hashes": config.strict_hashes,
            "emit_reconstructed_gpkg": config.emit_reconstructed_gpkg,
        },
        "environment": _environment(),
        "outputs": outputs,
        "neural_model_trained": False,
        "online_proposal_go": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p2_oof_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["run_jsg_p2_oof"]
