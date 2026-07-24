from __future__ import annotations

import json
import math
import resource
import time
from collections import Counter, defaultdict
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p6_models import (
    DECISION_ATTRIBUTION_GO,
    EXPECTED_P5_DECISION,
    SCHEME_A_P2_P3_P6_SCHEMA,
    SchemeAP2P3P6Config,
    choose_p6_decision,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_STABLE_WRONG_GROUP = (
    "SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080"
)


def run_scheme_a_p2_p3_p6_audit(config: SchemeAP2P3P6Config) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)

    source = _load_sources(config)
    joined, join_audit = _join_p5_rows(config, source)
    attributions = [build_object_attribution(row) for row in joined]
    dual_metrics = build_dual_layer_metrics(attributions)
    clue_errors, clue_summary = build_clue_error_audit(attributions)
    evidence = _build_evidence_separability(
        config,
        source,
        attributions,
        clue_errors,
        clue_summary,
    )
    expected_failure = build_expected_failure_audit(
        attributions,
        dict(config.expected_failure_case_counts),
    )

    metric_gate = _metric_gate(
        config,
        dual_metrics,
        clue_summary,
        expected_failure,
    )
    attribution_gate = (
        clue_summary["stable_false_positive_count"]
        == config.expected_stable_false_positive_count
        and clue_summary["stable_false_negative_count"]
        == config.expected_stable_false_negative_count
        and clue_summary["stable_carrier_wrong_accepted_group_ids"]
        == [_STABLE_WRONG_GROUP]
        and all(row["primary_attribution"] for row in attributions)
    )
    evidence_gate = (
        evidence["exact_opposite_evidence_collision_count"] == 0
        and evidence["exact_opposite_group_signature_collision_count"] == 0
        and evidence["held_out_case_neighbor_count"] == 0
        and evidence["stable_group_seed_audit_count"]
        == (
            config.expected_stable_false_positive_count
            + config.expected_stable_false_negative_count
        )
        * len(config.expected_seeds)
    )
    source_gate = (
        source["p5_manifest"]["decision"] == EXPECTED_P5_DECISION
        and source["dataset_manifest"]["decision"]
        == "P05_SCHEME_A_P2_P3_P5_DATASET_GO"
        and source["evidence_manifest"]["decision"]
        == "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO"
        and join_audit["gate_pass"]
    )
    calibration_problem = prove_calibration_problem(
        attributions,
        clue_summary,
    )
    representation_problem = prove_representation_problem(
        clue_summary,
        evidence,
    )
    audit_gate = (
        source_gate
        and metric_gate
        and attribution_gate
        and evidence_gate
    )
    decision = choose_p6_decision(
        audit_gate,
        calibration_problem,
        representation_problem,
    )

    deterministic_payload = {
        "source_lineage": source["lineage"],
        "join_audit": join_audit,
        "dual_metrics": dual_metrics,
        "clue_summary": clue_summary,
        "expected_failure": expected_failure,
        "evidence": evidence,
        "attributions": attributions,
        "clue_errors": clue_errors,
        "calibration_problem_proven": calibration_problem,
        "representation_problem_proven": representation_problem,
        "audit_gate_pass": audit_gate,
        "decision": decision,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    if reference_match is False:
        audit_gate = False
        decision = choose_p6_decision(False, calibration_problem, representation_problem)

    run_root.mkdir(parents=True)
    paths = {
        "object_attributions": run_root / "object_attributions.jsonl",
        "clue_errors": run_root / "clue_errors.jsonl",
        "dual_metrics": run_root / "dual_layer_metrics.json",
        "expected_failure": run_root / "expected_failure_publication_audit.json",
        "evidence": run_root / "evidence_separability.json",
        "summary": run_root / "scheme_a_p2_p3_p6_summary.json",
        "report": run_root / "validation_report.md",
    }
    _write_jsonl(paths["object_attributions"], attributions)
    _write_jsonl(paths["clue_errors"], clue_errors)
    write_json(paths["dual_metrics"], {"rows": dual_metrics})
    write_json(paths["expected_failure"], expected_failure)
    write_json(paths["evidence"], evidence)

    peak_rss = _peak_rss_bytes()
    resource_metrics = {
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss,
        "peak_rss_gib": peak_rss / (1024**3),
        "gpu_vram_bytes": 0,
    }
    resource_gate = (
        resource_metrics["wall_seconds"] <= 10 * 60
        and peak_rss <= 8 * 1024**3
    )
    if not resource_gate:
        audit_gate = False
        decision = choose_p6_decision(False, calibration_problem, representation_problem)

    summary = {
        "schema_version": SCHEME_A_P2_P3_P6_SCHEMA,
        "decision": decision,
        "preserved_p5_decision": EXPECTED_P5_DECISION,
        "audit_gate_pass": audit_gate,
        "source_gate_pass": source_gate,
        "metric_gate_pass": metric_gate,
        "attribution_gate_pass": attribution_gate,
        "evidence_gate_pass": evidence_gate,
        "resource_gate_pass": resource_gate,
        "reference_run_match": reference_match,
        "determinism_signature": signature,
        "join_audit": join_audit,
        "seed_metrics": [
            row for row in dual_metrics if row["scope"] == "SEED"
        ],
        "clue_summary": clue_summary,
        "expected_failure": expected_failure,
        "calibration_problem_proven": calibration_problem,
        "representation_problem_proven": representation_problem,
        "source_lineage": source["lineage"],
        "resource": resource_metrics,
        "model_training_count": 0,
        "threshold_tuning_count": 0,
        "movement_decision_count": 0,
        "t06_inference_feature_count": 0,
        "truth_inference_feature_count": 0,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "coordinate_transform_count": 0,
        "crs": "EPSG:3857",
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(paths["summary"], summary)
    paths["report"].write_text(
        _render_report(summary, dual_metrics, evidence),
        encoding="utf-8",
    )

    outputs = {key: output_record(path) for key, path in paths.items()}
    manifest_path = run_root / "scheme_a_p2_p3_p6_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P6_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "dual_layer_attribution_completed",
            "decision": decision,
            "preserved_p5_decision": EXPECTED_P5_DECISION,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "outputs": outputs,
            "model_training_count": 0,
            "threshold_tuning_count": 0,
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
            "schema_version": "p05-scheme-a-p2-p3-p6-artifacts-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def build_object_attribution(row: Mapping[str, Any]) -> dict[str, Any]:
    decision = row["decision"]
    evaluation = row["evaluation"]
    score = row["score"]
    effective = row["effective"]
    correct = (
        str(evaluation["selected_target"])
        == str(evaluation["truth_target"])
    )
    candidate_exact = (
        str(evaluation["selected_candidate_id"])
        == str(evaluation["truth_candidate_id"])
    )
    review = bool(evaluation["review_target"])
    clue_target = bool(evaluation["clue_target"])
    clue_predicted = bool(decision["clue_predicted"])
    scorer_accepted = bool(decision["accepted"])
    final_accepted = bool(effective["accepted"])
    selected_id = str(evaluation["selected_candidate_id"])
    truth_id = str(evaluation["truth_candidate_id"])
    score_margin = _candidate_margin(
        score,
        selected_id,
        truth_id,
        "candidate_scores",
    )
    utility_margin = _candidate_margin(
        score,
        selected_id,
        truth_id,
        "candidate_utilities",
    )
    scorer_attribution = _scorer_attribution(
        correct=correct,
        review=review,
        clue_target=clue_target,
        clue_predicted=clue_predicted,
        accepted=scorer_accepted,
        reason=str(decision["reason"]),
    )
    publication_attribution = (
        "EXPECTED_FAILURE_CASE_ATOMIC_BLOCK"
        if str(effective["reason"]) == "expected_swsd_baseline_failure"
        else (
            "PUBLISHED_CORRECT"
            if final_accepted and correct and not review
            else "FINAL_FALLBACK"
        )
    )
    return {
        "schema_version": SCHEME_A_P2_P3_P6_SCHEMA,
        "seed": int(decision["seed"]),
        "fold": int(decision["fold"]),
        "case_key": str(decision["case_key"]),
        "family": str(decision["case_key"]).split(":", 1)[0],
        "group_id": str(decision["group_id"]),
        "object_id": str(decision["object_id"]),
        "truth_candidate_id": truth_id,
        "truth_target": str(evaluation["truth_target"]),
        "selected_candidate_id": selected_id,
        "selected_target": str(evaluation["selected_target"]),
        "carrier_selection_correct": correct,
        "carrier_candidate_exact": candidate_exact,
        "review_target": review,
        "clue_target": clue_target,
        "clue_predicted": clue_predicted,
        "clue_probability": float(score["clue_probability"]),
        "clue_threshold": float(decision["clue_threshold"]),
        "clue_threshold_margin": (
            float(score["clue_probability"]) - float(decision["clue_threshold"])
        ),
        "carrier_score_margin_selected_minus_truth": score_margin,
        "carrier_utility_margin_selected_minus_truth": utility_margin,
        "scorer_accepted": scorer_accepted,
        "scorer_reason": str(decision["reason"]),
        "pre_gate_reason": str(decision.get("pre_gate_reason") or ""),
        "final_published": final_accepted,
        "final_reason": str(effective["reason"]),
        "expected_failure_atomic_block": (
            str(effective["reason"]) == "expected_swsd_baseline_failure"
        ),
        "primary_attribution": scorer_attribution,
        "publication_attribution": publication_attribution,
    }


def build_dual_layer_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scopes: dict[tuple[int, int | None], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        scopes[(int(row["seed"]), None)].append(row)
        scopes[(int(row["seed"]), int(row["fold"]))].append(row)
    result: list[dict[str, Any]] = []
    for (seed, fold), scoped in sorted(
        scopes.items(),
        key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1]),
    ):
        result.append(_scope_metrics(seed, fold, scoped))
    return result


def build_clue_error_audit(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    fp_by_seed: dict[int, set[str]] = defaultdict(set)
    fn_by_seed: dict[int, set[str]] = defaultdict(set)
    concentration: Counter[tuple[int, str, int, str]] = Counter()
    wrong_by_seed: dict[int, set[str]] = defaultdict(set)
    thresholds: dict[tuple[int, int], float] = {}
    for row in rows:
        seed = int(row["seed"])
        fold = int(row["fold"])
        thresholds[(seed, fold)] = float(row["clue_threshold"])
        if row["scorer_accepted"] and (
            row["review_target"] or not row["carrier_selection_correct"]
        ):
            wrong_by_seed[seed].add(str(row["group_id"]))
        error_type = ""
        if row["clue_predicted"] and not row["clue_target"]:
            error_type = "FALSE_POSITIVE"
            fp_by_seed[seed].add(str(row["group_id"]))
        elif not row["clue_predicted"] and row["clue_target"]:
            error_type = "FALSE_NEGATIVE"
            fn_by_seed[seed].add(str(row["group_id"]))
        if not error_type:
            continue
        concentration[(seed, error_type, fold, str(row["case_key"]))] += 1
        errors.append(
            {
                "schema_version": SCHEME_A_P2_P3_P6_SCHEMA,
                "seed": seed,
                "fold": fold,
                "case_key": str(row["case_key"]),
                "family": str(row["family"]),
                "group_id": str(row["group_id"]),
                "object_id": str(row["object_id"]),
                "error_type": error_type,
                "clue_probability": float(row["clue_probability"]),
                "clue_threshold": float(row["clue_threshold"]),
                "threshold_margin": float(row["clue_threshold_margin"]),
                "carrier_selection_correct": bool(
                    row["carrier_selection_correct"]
                ),
            }
        )
    seeds = sorted({int(row["seed"]) for row in rows})
    stable_fp = set.intersection(*(fp_by_seed[seed] for seed in seeds))
    stable_fn = set.intersection(*(fn_by_seed[seed] for seed in seeds))
    stable_wrong = set.intersection(*(wrong_by_seed[seed] for seed in seeds))
    return errors, {
        "false_positive_counts": {
            str(seed): len(fp_by_seed[seed]) for seed in seeds
        },
        "false_negative_counts": {
            str(seed): len(fn_by_seed[seed]) for seed in seeds
        },
        "stable_false_positive_count": len(stable_fp),
        "stable_false_positive_group_ids": sorted(stable_fp),
        "stable_false_negative_count": len(stable_fn),
        "stable_false_negative_group_ids": sorted(stable_fn),
        "stable_carrier_wrong_accepted_group_ids": sorted(stable_wrong),
        "thresholds": [
            {"seed": seed, "fold": fold, "clue_threshold": value}
            for (seed, fold), value in sorted(thresholds.items())
        ],
        "concentration": [
            {
                "seed": key[0],
                "error_type": key[1],
                "fold": key[2],
                "case_key": key[3],
                "count": count,
            }
            for key, count in sorted(concentration.items())
        ],
    }


def build_expected_failure_audit(
    rows: Sequence[Mapping[str, Any]],
    expected_case_counts: Mapping[str, int],
) -> dict[str, Any]:
    by_seed_case: Counter[tuple[int, str]] = Counter()
    non_review_by_seed: Counter[int] = Counter()
    actual_coverage_mask_by_seed: Counter[int] = Counter()
    localized_by_seed: Counter[int] = Counter()
    for row in rows:
        seed = int(row["seed"])
        case_key = str(row["case_key"])
        if row["expected_failure_atomic_block"]:
            by_seed_case[(seed, case_key)] += 1
            non_review_by_seed[seed] += int(not row["review_target"])
            actual_coverage_mask_by_seed[seed] += int(
                row["scorer_accepted"]
                and row["carrier_selection_correct"]
                and not row["review_target"]
            )
        localized_by_seed[seed] += int(
            row["scorer_reason"] == "dataset_p1_localized_expected_failure"
            or row.get("pre_gate_reason")
            == "dataset_p1_localized_expected_failure"
        )
    seeds = sorted({int(row["seed"]) for row in rows})
    return {
        "by_seed_case": [
            {
                "seed": seed,
                "case_key": case_key,
                "eligible_atomic_block_count": by_seed_case[(seed, case_key)],
                "expected_count": expected,
                "match": by_seed_case[(seed, case_key)] == expected,
            }
            for seed in seeds
            for case_key, expected in sorted(expected_case_counts.items())
        ],
        "eligible_atomic_block_counts": {
            str(seed): sum(
                by_seed_case[(seed, case_key)] for case_key in expected_case_counts
            )
            for seed in seeds
        },
        "non_review_atomic_block_counts": {
            str(seed): non_review_by_seed[seed] for seed in seeds
        },
        "actual_safe_coverage_mask_counts": {
            str(seed): actual_coverage_mask_by_seed[seed] for seed in seeds
        },
        "localized_failure_group_counts": {
            str(seed): localized_by_seed[seed] for seed in seeds
        },
    }


def prove_calibration_problem(
    rows: Sequence[Mapping[str, Any]],
    clue_summary: Mapping[str, Any],
) -> bool:
    thresholds = [
        float(row["clue_threshold"]) for row in clue_summary["thresholds"]
    ]
    fp = [int(value) for value in clue_summary["false_positive_counts"].values()]
    fn = [int(value) for value in clue_summary["false_negative_counts"].values()]
    return (
        min(thresholds) < 0.001
        and max(thresholds) > 0.99
        and max(fp) >= 2_000
        and max(fn) >= 100
        and any(float(row["clue_threshold_margin"]) > 0 for row in rows)
        and any(float(row["clue_threshold_margin"]) < 0 for row in rows)
    )


def prove_representation_problem(
    clue_summary: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    wrong = set(clue_summary["stable_carrier_wrong_accepted_group_ids"])
    rows = [
        row
        for row in evidence["stable_group_neighbors"]
        if row["group_id"] in wrong
    ]
    return (
        wrong == {_STABLE_WRONG_GROUP}
        and len(rows) == 3
        and all(row["neighbor_count"] == 20 for row in rows)
        and all(row["neighbor_clue_false_count"] == 20 for row in rows)
        and all(row["neighbor_truth_target_counts"].get("USE_RCSD") == 20 for row in rows)
    )


def _load_sources(config: SchemeAP2P3P6Config) -> dict[str, Any]:
    p5_root = normalize_runtime_path(config.p5_run_root).resolve(strict=True)
    dataset_root = normalize_runtime_path(
        config.scope_first_dataset_root
    ).resolve(strict=True)
    evidence_root = normalize_runtime_path(
        config.structural_evidence_root
    ).resolve(strict=True)
    p5_manifest_path = p5_root / "scheme_a_p2_p3_p5_manifest.json"
    dataset_manifest_path = dataset_root / "scheme_a_p2_p1_dataset_manifest.json"
    evidence_manifest_path = (
        evidence_root / "scheme_a_p2_p2_p2_p0_manifest.json"
    )
    p5_manifest = _read_json(p5_manifest_path)
    dataset_manifest = _read_json(dataset_manifest_path)
    evidence_manifest = _read_json(evidence_manifest_path)
    p5_paths = _verified_outputs(p5_manifest, config.strict_hashes)
    dataset_paths = _verified_outputs(dataset_manifest, config.strict_hashes)
    evidence_paths = _verified_outputs(evidence_manifest, config.strict_hashes)
    required_p5 = {"eligible_decisions", "evaluation", "scores", "effective", "folds", "metrics"}
    if not required_p5 <= set(p5_paths):
        raise ValueError("P5 required output set differs")
    if not {"features", "labels"} <= set(dataset_paths):
        raise ValueError("scope-first dataset output set differs")
    if not {"evidence", "evidence_contract"} <= set(evidence_paths):
        raise ValueError("structural evidence output set differs")
    return {
        "p5_manifest": p5_manifest,
        "dataset_manifest": dataset_manifest,
        "evidence_manifest": evidence_manifest,
        "p5_paths": p5_paths,
        "dataset_paths": dataset_paths,
        "evidence_paths": evidence_paths,
        "lineage": {
            "p5_manifest_sha256": sha256_file(p5_manifest_path),
            "p5_determinism_signature": str(
                p5_manifest["determinism_signature"]
            ),
            "scope_first_dataset_manifest_sha256": sha256_file(
                dataset_manifest_path
            ),
            "scope_first_dataset_signature": str(
                dataset_manifest["determinism_signature"]
            ),
            "structural_evidence_manifest_sha256": sha256_file(
                evidence_manifest_path
            ),
            "structural_evidence_signature": str(
                evidence_manifest["evidence_signature"]
            ),
        },
    }


def _join_p5_rows(
    config: SchemeAP2P3P6Config,
    source: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = source["p5_paths"]
    decisions = _index_seed_group(_read_jsonl(paths["eligible_decisions"]))
    evaluations = _index_seed_group(_read_jsonl(paths["evaluation"]))
    scores = _index_seed_group(_read_jsonl(paths["scores"]))
    eligible_groups = {key[1] for key in decisions}
    effective = _index_seed_group(
        row
        for row in _read_jsonl(paths["effective"])
        if row.get("object_type") == "SEGMENT"
        and str(row.get("group_id")) in eligible_groups
    )
    key_sets = [set(rows) for rows in (decisions, evaluations, scores, effective)]
    common = set.intersection(*key_sets)
    expected = len(config.expected_seeds) * config.expected_eligible_count
    if any(keys != common for keys in key_sets):
        raise ValueError("P5 scorer/evaluation/score/effective join scope differs")
    joined = [
        {
            "decision": decisions[key],
            "evaluation": evaluations[key],
            "score": scores[key],
            "effective": effective[key],
        }
        for key in sorted(common)
    ]
    seed_counts = Counter(key[0] for key in common)
    fold_counts = Counter(
        (key[0], int(decisions[key]["fold"])) for key in common
    )
    gate = (
        len(common) == expected
        and seed_counts
        == Counter({seed: config.expected_eligible_count for seed in config.expected_seeds})
        and all(0 <= fold < config.expected_fold_count for _, fold in fold_counts)
    )
    return joined, {
        "gate_pass": gate,
        "joined_seed_object_count": len(common),
        "expected_seed_object_count": expected,
        "seed_counts": dict(sorted(seed_counts.items())),
        "fold_counts": [
            {"seed": key[0], "fold": key[1], "count": count}
            for key, count in sorted(fold_counts.items())
        ],
        "duplicate_decision_count": decisions.duplicate_count,
        "duplicate_evaluation_count": evaluations.duplicate_count,
        "duplicate_score_count": scores.duplicate_count,
        "duplicate_effective_count": effective.duplicate_count,
    }


class _IndexedRows(dict[tuple[int, str], dict[str, Any]]):
    duplicate_count: int = 0


def _index_seed_group(rows: Iterable[Mapping[str, Any]]) -> _IndexedRows:
    result = _IndexedRows()
    result.duplicate_count = 0
    for source in rows:
        row = dict(source)
        key = (int(row["seed"]), str(row["group_id"]))
        if key in result:
            result.duplicate_count += 1
        result[key] = row
    return result


def _scope_metrics(
    seed: int,
    fold: int | None,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unsafe = [
        row
        for row in rows
        if row["review_target"] or not row["carrier_selection_correct"]
    ]
    scorer_wrong = sum(
        row["scorer_accepted"]
        and (row["review_target"] or not row["carrier_selection_correct"])
        for row in rows
    )
    final_wrong = sum(
        row["final_published"]
        and (row["review_target"] or not row["carrier_selection_correct"])
        for row in rows
    )
    scorer_safe = sum(
        row["scorer_accepted"]
        and row["carrier_selection_correct"]
        and not row["review_target"]
        for row in rows
    )
    final_safe = sum(
        row["final_published"]
        and row["carrier_selection_correct"]
        and not row["review_target"]
        for row in rows
    )
    automatable_rows = [row for row in rows if not row["review_target"]]
    use_rows = [row for row in rows if row["truth_target"] == "USE_RCSD"]
    scorer_use = sum(
        row["scorer_accepted"] and row["carrier_selection_correct"]
        for row in use_rows
    )
    final_use = sum(
        row["final_published"] and row["carrier_selection_correct"]
        for row in use_rows
    )
    return {
        "scope": "SEED" if fold is None else "FOLD",
        "seed": seed,
        "fold": fold,
        "group_count": len(rows),
        "unsafe_count": len(unsafe),
        "scorer_wrong_accepted_count": scorer_wrong,
        "final_wrong_published_count": final_wrong,
        "review_auto_publish_count": sum(
            row["scorer_accepted"] and row["review_target"] for row in rows
        ),
        "scorer_safety_recall": (
            (len(unsafe) - scorer_wrong) / len(unsafe) if unsafe else 1.0
        ),
        "final_publication_safety_recall": (
            (len(unsafe) - final_wrong) / len(unsafe) if unsafe else 1.0
        ),
        "scorer_safe_count": scorer_safe,
        "final_safe_count": final_safe,
        "automatable_group_count": len(automatable_rows),
        "scorer_safe_coverage": (
            scorer_safe / len(automatable_rows) if automatable_rows else 1.0
        ),
        "final_safe_coverage": (
            final_safe / len(automatable_rows) if automatable_rows else 1.0
        ),
        "use_rcsd_count": len(use_rows),
        "scorer_use_rcsd_safe_coverage": (
            scorer_use / len(use_rows) if use_rows else 1.0
        ),
        "final_use_rcsd_safe_coverage": (
            final_use / len(use_rows) if use_rows else 1.0
        ),
    }


def _build_evidence_separability(
    config: SchemeAP2P3P6Config,
    source: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    clue_errors: list[dict[str, Any]],
    clue_summary: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_by_group, evidence_fold = _load_evidence(
        source["evidence_paths"]["evidence"]
    )
    eligible = {str(row["group_id"]) for row in rows}
    evidence_by_group = {
        key: value for key, value in evidence_by_group.items() if key in eligible
    }
    evidence_fold = {
        key: value for key, value in evidence_fold.items() if key in eligible
    }
    target_by_group = {}
    truth_target_by_group = {}
    case_by_group = {}
    for row in rows:
        group_id = str(row["group_id"])
        target_by_group[group_id] = bool(row["clue_target"])
        truth_target_by_group[group_id] = str(row["truth_target"])
        case_by_group[group_id] = str(row["case_key"])
    group_signatures = _load_group_signatures(
        source["dataset_paths"]["features"],
        eligible,
    )
    evidence_signatures = {
        group_id: canonical_sha256(list(values))
        for group_id, values in evidence_by_group.items()
    }
    _annotate_collision_flags(
        clue_errors,
        evidence_signatures,
        group_signatures,
        target_by_group,
        evidence_fold,
    )
    stable_groups = sorted(
        set(clue_summary["stable_false_positive_group_ids"])
        | set(clue_summary["stable_false_negative_group_ids"])
    )
    neighbors: list[dict[str, Any]] = []
    held_out_case_neighbor_count = 0
    for seed in config.expected_seeds:
        for group_id in stable_groups:
            fold = evidence_fold[group_id]
            rows_for_group = _nearest_neighbors(
                group_id,
                fold,
                evidence_by_group,
                evidence_fold,
                target_by_group,
                truth_target_by_group,
                case_by_group,
                config.nearest_neighbor_count,
            )
            held_out_case_neighbor_count += sum(
                row["case_key"] == case_by_group[group_id]
                for row in rows_for_group
            )
            neighbors.append(
                {
                    "seed": seed,
                    "fold": fold,
                    "group_id": group_id,
                    "case_key": case_by_group[group_id],
                    "clue_target": target_by_group[group_id],
                    "neighbor_count": len(rows_for_group),
                    "nearest_distance": (
                        rows_for_group[0]["distance"] if rows_for_group else None
                    ),
                    "neighbor_clue_true_count": sum(
                        row["clue_target"] for row in rows_for_group
                    ),
                    "neighbor_clue_false_count": sum(
                        not row["clue_target"] for row in rows_for_group
                    ),
                    "neighbor_truth_target_counts": dict(
                        sorted(
                            Counter(
                                row["truth_target"] for row in rows_for_group
                            ).items()
                        )
                    ),
                    "neighbors": rows_for_group,
                }
            )
    wrong_rows = [
        row
        for row in rows
        if row["group_id"] == _STABLE_WRONG_GROUP
        and row["scorer_accepted"]
        and not row["carrier_selection_correct"]
    ]
    return {
        "evidence_dimension": (
            len(next(iter(evidence_by_group.values())))
            if evidence_by_group
            else 0
        ),
        "eligible_evidence_count": len(evidence_by_group),
        "group_signature_count": len(group_signatures),
        "clue_error_count": len(clue_errors),
        "exact_opposite_evidence_collision_count": sum(
            row["opposite_evidence_collision"] for row in clue_errors
        ),
        "exact_opposite_group_signature_collision_count": sum(
            row["opposite_group_signature_collision"] for row in clue_errors
        ),
        "stable_group_seed_audit_count": len(neighbors),
        "held_out_case_neighbor_count": held_out_case_neighbor_count,
        "stable_group_neighbors": neighbors,
        "stable_carrier_wrong_score_audit": [
            {
                "seed": int(row["seed"]),
                "group_id": str(row["group_id"]),
                "score_margin_selected_minus_truth": float(
                    row["carrier_score_margin_selected_minus_truth"]
                ),
                "utility_margin_selected_minus_truth": float(
                    row["carrier_utility_margin_selected_minus_truth"]
                ),
                "clue_probability": float(row["clue_probability"]),
                "clue_threshold": float(row["clue_threshold"]),
            }
            for row in wrong_rows
        ],
    }


def _load_evidence(
    path: Path,
) -> tuple[dict[str, tuple[float, ...]], dict[str, int]]:
    values: dict[str, tuple[float, ...]] = {}
    folds: dict[str, int] = {}
    for row in _read_jsonl(path):
        group_id = str(row["group_id"])
        if group_id in values:
            raise ValueError(f"duplicate structural evidence: {group_id}")
        values[group_id] = tuple(float(value) for value in row["features"])
        folds[group_id] = int(row["fold"])
    return values, folds


def _load_group_signatures(
    path: Path,
    eligible: set[str],
) -> dict[str, str]:
    candidate_hashes: dict[str, list[str]] = defaultdict(list)
    for row in _read_jsonl(path):
        group_id = str(row["group_id"])
        if group_id not in eligible or row.get("object_type") != "SEGMENT":
            continue
        payload = {
            "candidate_target": row.get("candidate_target"),
            "candidate_tokens": row.get("candidate_tokens"),
            "context_tokens": row.get("context_tokens"),
            "hard_unsafe": row.get("hard_unsafe"),
            "numeric_features": row.get("numeric_features"),
            "object_tokens": row.get("object_tokens"),
        }
        candidate_hashes[group_id].append(canonical_sha256(payload))
    result = {
        group_id: canonical_sha256(sorted(hashes))
        for group_id, hashes in candidate_hashes.items()
    }
    if set(result) != eligible:
        raise ValueError("eligible group signature scope differs")
    return result


def _annotate_collision_flags(
    errors: list[dict[str, Any]],
    evidence_signatures: Mapping[str, str],
    group_signatures: Mapping[str, str],
    targets: Mapping[str, bool],
    folds: Mapping[str, int],
) -> None:
    evidence_index: dict[tuple[int, str], set[bool]] = defaultdict(set)
    group_index: dict[tuple[int, str], set[bool]] = defaultdict(set)
    for held_out_fold in sorted(set(folds.values())):
        for group_id, fold in folds.items():
            if fold == held_out_fold:
                continue
            target = targets[group_id]
            evidence_index[(held_out_fold, evidence_signatures[group_id])].add(target)
            group_index[(held_out_fold, group_signatures[group_id])].add(target)
    for row in errors:
        group_id = str(row["group_id"])
        fold = int(row["fold"])
        opposite = not targets[group_id]
        row["opposite_evidence_collision"] = opposite in evidence_index[
            (fold, evidence_signatures[group_id])
        ]
        row["opposite_group_signature_collision"] = opposite in group_index[
            (fold, group_signatures[group_id])
        ]


def _nearest_neighbors(
    query_group: str,
    held_out_fold: int,
    evidence: Mapping[str, tuple[float, ...]],
    folds: Mapping[str, int],
    clue_targets: Mapping[str, bool],
    truth_targets: Mapping[str, str],
    cases: Mapping[str, str],
    count: int,
) -> list[dict[str, Any]]:
    training_ids = [
        group_id for group_id, fold in folds.items() if fold != held_out_fold
    ]
    dimension = len(evidence[query_group])
    means = [
        sum(evidence[group_id][index] for group_id in training_ids)
        / len(training_ids)
        for index in range(dimension)
    ]
    scales = []
    for index, mean in enumerate(means):
        variance = sum(
            (evidence[group_id][index] - mean) ** 2 for group_id in training_ids
        ) / len(training_ids)
        scale = math.sqrt(variance)
        scales.append(scale if scale > 1e-6 else 1.0)
    query = [
        (value - means[index]) / scales[index]
        for index, value in enumerate(evidence[query_group])
    ]
    distances = []
    for group_id in training_ids:
        distance = math.sqrt(
            sum(
                (
                    (value - means[index]) / scales[index] - query[index]
                )
                ** 2
                for index, value in enumerate(evidence[group_id])
            )
        )
        distances.append((distance, group_id))
    return [
        {
            "rank": rank,
            "group_id": group_id,
            "case_key": cases[group_id],
            "distance": distance,
            "clue_target": clue_targets[group_id],
            "truth_target": truth_targets[group_id],
        }
        for rank, (distance, group_id) in enumerate(
            sorted(distances)[:count],
            start=1,
        )
    ]


def _metric_gate(
    config: SchemeAP2P3P6Config,
    metrics: Sequence[Mapping[str, Any]],
    clue_summary: Mapping[str, Any],
    expected_failure: Mapping[str, Any],
) -> bool:
    seed_rows = {
        int(row["seed"]): row for row in metrics if row["scope"] == "SEED"
    }
    if set(seed_rows) != set(config.expected_seeds):
        return False
    for index, seed in enumerate(config.expected_seeds):
        row = seed_rows[seed]
        if row["group_count"] != config.expected_eligible_count:
            return False
        if row["scorer_wrong_accepted_count"] != config.expected_scorer_wrong_counts[index]:
            return False
        if row["final_wrong_published_count"] != config.expected_final_wrong_counts[index]:
            return False
        if not math.isclose(
            row["scorer_safe_coverage"],
            config.expected_scorer_safe_coverage[index],
            abs_tol=1e-10,
        ):
            return False
        if not math.isclose(
            row["final_safe_coverage"],
            config.expected_final_safe_coverage[index],
            abs_tol=1e-10,
        ):
            return False
        if clue_summary["false_positive_counts"][str(seed)] != (
            config.expected_clue_false_positive_counts[index]
        ):
            return False
        if clue_summary["false_negative_counts"][str(seed)] != (
            config.expected_clue_false_negative_counts[index]
        ):
            return False
        if expected_failure["eligible_atomic_block_counts"][str(seed)] != sum(
            dict(config.expected_failure_case_counts).values()
        ):
            return False
        if expected_failure["non_review_atomic_block_counts"][str(seed)] != 1_940:
            return False
        if expected_failure["localized_failure_group_counts"][str(seed)] != 2:
            return False
    return all(row["match"] for row in expected_failure["by_seed_case"])


def _scorer_attribution(
    *,
    correct: bool,
    review: bool,
    clue_target: bool,
    clue_predicted: bool,
    accepted: bool,
    reason: str,
) -> str:
    if accepted and (review or not correct):
        return "CARRIER_RANK_WRONG_CLUE_MISSED"
    if review:
        return "ACCESS_INVALID_REVIEW_HARD_FALLBACK"
    if reason == "dataset_p1_localized_expected_failure":
        return "LOCALIZED_EXPECTED_FAILURE"
    if clue_predicted and clue_target:
        return "CLUE_TRUE_POSITIVE_FALLBACK"
    if clue_predicted and not clue_target:
        return "CLUE_FALSE_POSITIVE_FALLBACK"
    if not clue_predicted and clue_target:
        return "CLUE_FALSE_NEGATIVE_ACCEPT" if accepted else "CLUE_FALSE_NEGATIVE_FALLBACK"
    if accepted and correct:
        return "CARRIER_ACCEPT_CORRECT"
    return "OTHER_SAFE_FALLBACK"


def _candidate_margin(
    score: Mapping[str, Any],
    selected_id: str,
    truth_id: str,
    value_key: str,
) -> float:
    ids = [str(value) for value in score["candidate_ids"]]
    values = [float(value) for value in score[value_key]]
    by_id = dict(zip(ids, values, strict=True))
    return by_id[selected_id] - by_id[truth_id]


def _verified_outputs(
    manifest: Mapping[str, Any],
    strict_hashes: bool,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key, value in dict(manifest.get("outputs") or {}).items():
        record = dict(value or {})
        path = normalize_runtime_path(str(record.get("path") or "")).resolve(
            strict=True
        )
        if path.stat().st_size != int(record.get("size_bytes") or -1):
            raise ValueError(f"output size mismatch: {key}")
        if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"output hash mismatch: {key}")
        result[str(key)] = path
    return result


def _reference_match(reference_root: Path | None, signature: str) -> bool | None:
    if reference_root is None:
        return None
    root = normalize_runtime_path(reference_root).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p6_manifest.json")
    return str(manifest.get("determinism_signature") or "") == signature


def _render_report(
    summary: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
) -> str:
    seed_rows = [row for row in metrics if row["scope"] == "SEED"]
    lines = [
        "# P05-Scheme-A-P2-P3-P6 验证报告",
        "",
        f"- decision: `{summary['decision']}`",
        f"- preserved P5: `{summary['preserved_p5_decision']}`",
        f"- signature: `{summary['determinism_signature']}`",
        f"- calibration problem proven: `{summary['calibration_problem_proven']}`",
        f"- representation problem proven: `{summary['representation_problem_proven']}`",
        "",
        "| seed | scorer wrong | final wrong | scorer coverage | final coverage |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in seed_rows:
        lines.append(
            f"| {row['seed']} | {row['scorer_wrong_accepted_count']} | "
            f"{row['final_wrong_published_count']} | "
            f"{row['scorer_safe_coverage']:.10f} | "
            f"{row['final_safe_coverage']:.10f} |"
        )
    lines.extend(
        [
            "",
            f"- exact opposite evidence collision: `{evidence['exact_opposite_evidence_collision_count']}`",
            f"- exact opposite group signature collision: `{evidence['exact_opposite_group_signature_collision_count']}`",
            f"- held-out Case neighbor leakage: `{evidence['held_out_case_neighbor_count']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            text = line.strip()
            if text:
                yield dict(json.loads(text))


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
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


__all__ = [
    "build_clue_error_audit",
    "build_dual_layer_metrics",
    "build_expected_failure_audit",
    "build_object_attribution",
    "prove_calibration_problem",
    "prove_representation_problem",
    "run_scheme_a_p2_p3_p6_audit",
]
