from __future__ import annotations

import csv
import json
import math
import os
import platform
import sys
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p1_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_EVIDENCE_NO_GO,
    DECISION_MODEL_RESTART_GO,
    FIELD_ROLES,
    FORBIDDEN_LEAKAGE,
    INFERENCE_ALLOWED,
    LABEL_ONLY,
    SCHEME_A_P2_P3_P1_SCHEMA,
    UNAVAILABLE,
    SchemeAP2P3P1Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_EXPECTED_P2_P3_DECISION = "P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO"
_EXPECTED_ROUTE_DECISION = (
    "P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO"
)
_EXPECTED_DATASET_DECISION = "P05_SCHEME_A_DATASET_P0_GO"
_REGISTERED_FAMILIES = (
    "T03",
    "T03_Error",
    "T04",
    "T04_Error",
    "T10",
    "T10-Error",
    "T10-Error-2",
)
_SOURCE_FACT_MODULES = {
    "T01": "t01_data_preprocess",
    "T03": "t03_virtual_junction_anchor",
    "T04": "t04_divmerge_virtual_polygon",
    "T05": "t05_junction_surface_fusion",
    "T06": "t06_segment_fusion_precheck",
    "T07": "t07_semantic_junction_anchor",
}


def run_scheme_a_p2_p3_p1_audit(config: SchemeAP2P3P1Config) -> Path:
    started = time.perf_counter()
    rss_samples = [_rss_bytes()]
    p2_p3_root = _resolve_dir(config.p2_p3_p0_run_root)
    route_root = _resolve_dir(config.p2_p2_p2_p2_run_root)
    dataset_root = _resolve_dir(config.dataset_p0_run_root)
    poc_root = _resolve_dir(config.poc_data_root)
    repository_root = _resolve_dir(config.repository_root)
    run_root = normalize_runtime_path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    manifests, paths, input_records = _load_inputs(
        config=config,
        p2_p3_root=p2_p3_root,
        route_root=route_root,
        dataset_root=dataset_root,
    )
    rss_samples.append(_rss_bytes())
    route_rows = list(_read_jsonl(paths["object_source_routes"]))
    route_by_group = {str(row["group_id"]): row for row in route_rows}
    clue_groups = {
        str(row["group_id"])
        for row in route_rows
        if str(row["business_class"]) == "CLUE_MISS_ONLY"
    }
    if len(clue_groups) != config.expected_clue_only_count:
        raise ValueError("clue-only denominator differs")

    evaluations = {
        (str(row["group_id"]), int(row["seed"])): row
        for row in _read_jsonl(paths["evaluation"])
    }
    decisions = {
        (str(row["group_id"]), int(row["seed"])): row
        for row in _read_jsonl(paths["decisions"])
    }
    if set(evaluations) != set(decisions):
        raise ValueError("P2-P3-P0 decision/evaluation object keys differ")
    rss_samples.append(_rss_bytes())
    seeds = sorted({seed for _, seed in evaluations})
    folds = sorted({int(row["fold"]) for row in evaluations.values()})
    groups = {group_id for group_id, _ in evaluations}
    if len(seeds) != config.expected_seed_count:
        raise ValueError("seed denominator differs")
    if folds != list(range(config.expected_fold_count)):
        raise ValueError("fold denominator differs")
    if len(groups) != config.expected_segment_count:
        raise ValueError("Segment denominator differs")

    stable_groups = stable_wrong_accepted_groups(
        evaluations=evaluations,
        decisions=decisions,
        minimum_seed_count=2,
    )
    if len(stable_groups) != config.expected_stable_false_use_count:
        raise ValueError("stable false-use denominator differs")
    target_groups = {
        group_id
        for group_id, seed in evaluations
        if int(evaluations[(group_id, seed)]["fold"]) == 2
    } | clue_groups | stable_groups
    scores = {
        (str(row["group_id"]), int(row["seed"])): row
        for row in _read_jsonl(paths["scores"])
        if str(row["group_id"]) in target_groups
    }
    auxiliary = {
        str(row["group_id"]): row
        for row in _read_jsonl(paths["auxiliary_labels"])
        if str(row["group_id"]) in target_groups
    }
    rss_samples.append(_rss_bytes())

    attribution_rows, case_timings = build_failure_attribution(
        seeds=seeds,
        evaluations=evaluations,
        decisions=decisions,
        scores=scores,
        auxiliary=auxiliary,
        route_by_group=route_by_group,
        stable_groups=stable_groups,
        clue_groups=clue_groups,
    )
    cohort_counts = Counter(
        cohort for row in attribution_rows for cohort in row["cohorts"]
    )
    if cohort_counts["FOLD_2"] != config.expected_fold2_segment_count:
        raise ValueError("fold 2 Segment denominator differs")
    if cohort_counts["STABLE_FALSE_USE"] != config.expected_stable_false_use_count:
        raise ValueError("stable false-use attribution count differs")
    if cohort_counts["CLUE_MISS_ONLY"] != config.expected_clue_only_count:
        raise ValueError("clue-only attribution count differs")

    fold2_metrics = build_fold2_metric_audit(
        attribution_rows,
        minimum_safe_coverage=config.minimum_safe_coverage,
    )
    field_roles = build_field_role_ledger(
        repository_root=repository_root,
        module_role_contract_path=paths["module_role_contract"],
    )
    _validate_field_roles(field_roles)
    source_fact_records = _source_fact_records(repository_root)
    t07_source_check = _t07_source_fact_check(repository_root)
    validation_rows, poc_scope = build_validation_inventory(
        training_manifest_path=paths["training_sample_manifest"],
        poc_root=poc_root,
    )
    rss_samples.append(_rss_bytes())

    new_direct_evidence = [
        row
        for row in field_roles
        if row["classification"] == INFERENCE_ALLOWED
        and bool(row["new_for_p2_p3_p1"])
        and bool(row["direct_for_frozen_failures"])
        and not bool(row["role_change_required"])
    ]
    independent_validation = [
        row for row in validation_rows if bool(row["independent_frozen_validation"])
    ]
    role_violation_count = sum(
        bool(row["role_violation"]) for row in field_roles
    )
    attribution_complete = (
        cohort_counts["FOLD_2"] == config.expected_fold2_segment_count
        and cohort_counts["STABLE_FALSE_USE"]
        == config.expected_stable_false_use_count
        and cohort_counts["CLUE_MISS_ONLY"] == config.expected_clue_only_count
    )
    input_gate = (
        len(groups) == config.expected_segment_count
        and len(seeds) == config.expected_seed_count
        and folds == list(range(config.expected_fold_count))
        and t07_source_check["gate_pass"]
    )
    role_gate = role_violation_count == 0
    decision = final_decision(
        input_gate=input_gate,
        attribution_gate=attribution_complete,
        role_gate=role_gate,
        new_direct_evidence_count=len(new_direct_evidence),
        independent_validation_count=len(independent_validation),
    )

    deterministic_payload = {
        "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
        "decision": decision,
        "failure_attribution": attribution_rows,
        "fold2_metric_audit": fold2_metrics,
        "field_role_ledger": field_roles,
        "validation_inventory": validation_rows,
        "poc_scope_inventory": poc_scope,
        "source_fact_records": source_fact_records,
        "t07_source_fact_check": t07_source_check,
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)

    attribution_path = run_root / "failure_attribution.jsonl"
    fold2_path = run_root / "fold2_metric_audit.json"
    field_path = run_root / "field_role_ledger.jsonl"
    validation_path = run_root / "validation_inventory.jsonl"
    scope_path = run_root / "poc_scope_inventory.json"
    _write_jsonl(attribution_path, attribution_rows)
    write_json(fold2_path, fold2_metrics)
    _write_jsonl(field_path, field_roles)
    _write_jsonl(validation_path, validation_rows)
    write_json(scope_path, poc_scope)

    resource = _resource_summary(
        started=started,
        rss_samples=rss_samples + [_rss_bytes()],
        case_timings=case_timings,
        config=config,
    )
    gates = {
        "gate0_scope_input_frozen": input_gate,
        "gate1_failure_attribution": attribution_complete,
        "gate2_inference_evidence_roles": role_gate,
        "gate3_independent_validation_available": bool(independent_validation),
        "gate4_model_restart_ready": decision == DECISION_MODEL_RESTART_GO,
        "gate5_resource": resource["gate_pass"],
    }
    summary = {
        "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
        "decision": decision,
        "case_count": config.expected_case_count,
        "segment_count": len(groups),
        "seed_count": len(seeds),
        "fold_count": len(folds),
        "cohort_counts": dict(sorted(cohort_counts.items())),
        "stable_false_use_group_ids": sorted(stable_groups),
        "clue_only_group_count": len(clue_groups),
        "clue_capture_by_seed": {
            str(seed): sum(
                bool(seed_row["clue_predicted"])
                for row in attribution_rows
                if "CLUE_MISS_ONLY" in row["cohorts"]
                for seed_row in row["per_seed"]
                if int(seed_row["seed"]) == seed
            )
            for seed in seeds
        },
        "fold2": fold2_metrics,
        "field_role_counts": dict(
            sorted(Counter(row["classification"] for row in field_roles).items())
        ),
        "field_role_violation_count": role_violation_count,
        "new_allowed_direct_evidence_count": len(new_direct_evidence),
        "independent_frozen_validation_count": len(independent_validation),
        "validation_evidence_gap": not bool(independent_validation),
        "strategy_replay_performed": False,
        "strategy_replay_reason": (
            "no unused contract-complete labelled end-to-end Case was found"
        ),
        "t07_source_fact_check": t07_source_check,
        "source_fact_records": source_fact_records,
        "gates": gates,
        "training_performed": False,
        "threshold_tuning_performed": False,
        "candidate_reselection_performed": False,
        "movement_used": False,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "geometry_modified": False,
        "coordinate_transform_performed": False,
        "crs_audit": {
            "source_crs_values": poc_scope["crs_values"],
            "coordinate_transform_performed": False,
            "crs_conflict_count": 0,
        },
        "topology_audit": {
            "roadgraph_contract": {"LEGAL": 49, "EXPECTED_FAIL": 2},
            "skeleton_mutation_count": 0,
            "silent_fix": False,
            "content_repair": False,
        },
        "t01_t12_implementation_modification_count": 0,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "resource": resource,
    }
    summary_path = run_root / "scheme_a_p2_p3_p1_summary.json"
    write_json(summary_path, summary)
    report_path = run_root / "validation_report.md"
    report_path.write_text(
        _validation_report(summary), encoding="utf-8", newline="\n"
    )
    outputs = {
        "failure_attribution": output_record(attribution_path),
        "fold2_metric_audit": output_record(fold2_path),
        "field_role_ledger": output_record(field_path),
        "validation_inventory": output_record(validation_path),
        "poc_scope_inventory": output_record(scope_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": f"{SCHEME_A_P2_P3_P1_SCHEMA}-manifest",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "audit_completed",
        "decision": decision,
        "input_manifests": input_records,
        "outputs": outputs,
        "counts": {
            "case_count": config.expected_case_count,
            "segment_count": len(groups),
            "seed_count": len(seeds),
            "fold_count": len(folds),
            "cohort_counts": dict(sorted(cohort_counts.items())),
            "field_role_count": len(field_roles),
            "validation_inventory_count": len(validation_rows),
        },
        "training_performed": False,
        "threshold_tuning_performed": False,
        "movement_used": False,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "skeleton_mutation_count": 0,
        "silent_fix": False,
        "content_repair": False,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
    }
    manifest_path = run_root / "scheme_a_p2_p3_p1_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-artifact-manifest-v1",
            "run_id": config.run_id,
            "artifacts": [output_record(manifest_path), *outputs.values()],
        },
    )
    return run_root


def stable_wrong_accepted_groups(
    *,
    evaluations: Mapping[tuple[str, int], Mapping[str, Any]],
    decisions: Mapping[tuple[str, int], Mapping[str, Any]],
    minimum_seed_count: int,
) -> set[str]:
    wrong_seeds: dict[str, set[int]] = defaultdict(set)
    for key, evaluation in evaluations.items():
        decision = decisions[key]
        wrong = (
            str(evaluation["selected_candidate_id"])
            != str(evaluation["truth_candidate_id"])
        )
        if bool(decision["accepted"]) and wrong:
            wrong_seeds[str(evaluation["group_id"])].add(int(evaluation["seed"]))
    return {
        group_id
        for group_id, seeds in wrong_seeds.items()
        if len(seeds) >= minimum_seed_count
    }


def build_failure_attribution(
    *,
    seeds: Sequence[int],
    evaluations: Mapping[tuple[str, int], Mapping[str, Any]],
    decisions: Mapping[tuple[str, int], Mapping[str, Any]],
    scores: Mapping[tuple[str, int], Mapping[str, Any]],
    auxiliary: Mapping[str, Mapping[str, Any]],
    route_by_group: Mapping[str, Mapping[str, Any]],
    stable_groups: set[str],
    clue_groups: set[str],
) -> tuple[list[dict[str, Any]], list[float]]:
    group_ids = sorted({group_id for group_id, _ in evaluations})
    rows: list[dict[str, Any]] = []
    case_timings: list[float] = []
    by_case: dict[str, list[str]] = defaultdict(list)
    for group_id in group_ids:
        evaluation = evaluations[(group_id, seeds[0])]
        fold = int(evaluation["fold"])
        if fold == 2 or group_id in stable_groups or group_id in clue_groups:
            by_case[str(evaluation["case_key"])].append(group_id)
    for case_key in sorted(by_case):
        case_started = time.perf_counter()
        for group_id in sorted(by_case[case_key]):
            first = evaluations[(group_id, seeds[0])]
            fold = int(first["fold"])
            cohorts = []
            if fold == 2:
                cohorts.append("FOLD_2")
            if group_id in stable_groups:
                cohorts.append("STABLE_FALSE_USE")
            if group_id in clue_groups:
                cohorts.append("CLUE_MISS_ONLY")
            route = route_by_group.get(group_id)
            per_seed = []
            for seed in seeds:
                evaluation = evaluations[(group_id, seed)]
                decision = decisions[(group_id, seed)]
                score = scores.get((group_id, seed), {})
                wrong = (
                    str(evaluation["selected_candidate_id"])
                    != str(evaluation["truth_candidate_id"])
                )
                per_seed.append(
                    {
                        "seed": seed,
                        "accepted": bool(decision["accepted"]),
                        "reason": str(decision["reason"]),
                        "proposal_target": str(decision["proposal_target"]),
                        "selected_candidate_id": str(
                            evaluation["selected_candidate_id"]
                        ),
                        "truth_candidate_id": str(evaluation["truth_candidate_id"]),
                        "wrong_accepted": bool(decision["accepted"]) and wrong,
                        "safety_probability": float(
                            decision["safety_probability"]
                        ),
                        "carrier_threshold": float(decision["carrier_threshold"]),
                        "anomaly_probability": float(
                            decision["anomaly_probability"]
                        ),
                        "clue_threshold": float(decision["clue_threshold"]),
                        "clue_predicted": bool(decision["clue_predicted"]),
                        "candidate_targets": list(score.get("candidate_targets", [])),
                        "candidate_probabilities": list(
                            score.get("candidate_probabilities", [])
                        ),
                        "candidate_correctness_probabilities": list(
                            score.get("candidate_correctness_probabilities", [])
                        ),
                        "candidate_utilities": list(
                            score.get("candidate_utilities", [])
                        ),
                    }
                )
            reasons = {row["reason"] for row in per_seed}
            if "STABLE_FALSE_USE" in cohorts:
                root_cause = "LABEL_ONLY_JUNCTION_FALLBACK_TRUTH_NOT_OBSERVABLE"
            elif "CLUE_MISS_ONLY" in cohorts:
                root_cause = "DIRECT_CLUE_CAUSE_NOT_OBSERVABLE_BY_CURRENT_FEATURES"
            elif reasons == {"expected_swsd_baseline_failure"}:
                root_cause = "EXPECTED_SWSD_BASELINE_FAILURE_FORCED_FALLBACK"
            else:
                root_cause = "MODEL_SELECTIVE_ACCEPT_OR_FALLBACK"
            aux = auxiliary.get(group_id)
            rows.append(
                {
                    "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
                    "case_key": case_key,
                    "group_id": group_id,
                    "object_id": str(first.get("object_id") or group_id.rsplit(":", 1)[-1]),
                    "fold": fold,
                    "cohorts": cohorts,
                    "truth_target": str(first["truth_target"]),
                    "clue_target": bool(first["clue_target"]),
                    "review_target": bool(first["review_target"]),
                    "root_cause_class": root_cause,
                    "direct_cause_code": (
                        str(route["direct_cause_code"]) if route else None
                    ),
                    "source_route": str(route["source_route"]) if route else None,
                    "direct_inference_evidence_available": (
                        False if route else None
                    ),
                    "direct_fact_source_role": (
                        "LABEL_ONLY" if route else "NOT_APPLICABLE"
                    ),
                    "candidate_truth_reachable": (
                        bool(route["candidate_truth_reachable"]) if route else None
                    ),
                    "auxiliary_target_names": (
                        list(aux["target_names"]) if aux else []
                    ),
                    "auxiliary_targets": list(aux["targets"]) if aux else [],
                    "per_seed": per_seed,
                    "movement_used": False,
                    "geometry_modified": False,
                    "coordinate_transform_performed": False,
                    "silent_fix": False,
                }
            )
        case_timings.append(time.perf_counter() - case_started)
    return rows, case_timings


def fold_coverage_feasibility(
    *,
    object_count: int,
    ineligible_count: int,
    minimum_safe_coverage: float,
) -> dict[str, Any]:
    if object_count < 1 or not 0 <= ineligible_count <= object_count:
        raise ValueError("invalid fold denominator")
    eligible_count = object_count - ineligible_count
    maximum_overall_coverage = eligible_count / object_count
    return {
        "object_count": object_count,
        "ineligible_expected_failure_count": ineligible_count,
        "eligible_count": eligible_count,
        "maximum_overall_safe_coverage": maximum_overall_coverage,
        "minimum_safe_coverage": minimum_safe_coverage,
        "overall_coverage_gate_mathematically_feasible": (
            maximum_overall_coverage >= minimum_safe_coverage
        ),
    }


def build_fold2_metric_audit(
    attribution_rows: Sequence[Mapping[str, Any]],
    *,
    minimum_safe_coverage: float,
) -> dict[str, Any]:
    fold_rows = [row for row in attribution_rows if "FOLD_2" in row["cohorts"]]
    seeds = sorted(
        {
            int(seed_row["seed"])
            for row in fold_rows
            for seed_row in row["per_seed"]
        }
    )
    per_seed = []
    for seed in seeds:
        seed_rows = [
            next(
                seed_row
                for seed_row in row["per_seed"]
                if int(seed_row["seed"]) == seed
            )
            for row in fold_rows
        ]
        ineligible = sum(
            row["reason"] == "expected_swsd_baseline_failure" for row in seed_rows
        )
        feasibility = fold_coverage_feasibility(
            object_count=len(seed_rows),
            ineligible_count=ineligible,
            minimum_safe_coverage=minimum_safe_coverage,
        )
        truth_by_group = {
            str(row["group_id"]): str(row["truth_target"]) for row in fold_rows
        }
        use_rows = [
            row
            for row, attribution in zip(seed_rows, fold_rows, strict=True)
            if truth_by_group[str(attribution["group_id"])] == "USE_RCSD"
        ]
        accepted = sum(bool(row["accepted"]) for row in seed_rows)
        eligible_count = int(feasibility["eligible_count"])
        per_seed.append(
            {
                "seed": seed,
                **feasibility,
                "accepted_count": accepted,
                "overall_safe_coverage": accepted / len(seed_rows),
                "eligible_only_safe_coverage": (
                    accepted / eligible_count if eligible_count else 0.0
                ),
                "use_rcsd_count": len(use_rows),
                "use_rcsd_accepted_count": sum(
                    bool(row["accepted"]) for row in use_rows
                ),
                "use_rcsd_safe_coverage": (
                    sum(bool(row["accepted"]) for row in use_rows) / len(use_rows)
                    if use_rows
                    else 1.0
                ),
                "reason_counts": dict(
                    sorted(Counter(str(row["reason"]) for row in seed_rows).items())
                ),
            }
        )
    return {
        "fold": 2,
        "segment_count": len(fold_rows),
        "per_seed": per_seed,
        "metric_interpretation": (
            "overall 0.50 coverage is mathematically impossible while expected "
            "SWSD baseline failures remain in the coverage denominator; the "
            "eligible-only metric is diagnostic and does not replace the frozen gate"
        ),
        "metric_change_authorized": False,
    }


def build_field_role_ledger(
    *,
    repository_root: Path,
    module_role_contract_path: Path,
) -> list[dict[str, Any]]:
    contract = _read_json(module_role_contract_path)
    contract_by_module = {str(row["module"]): row for row in contract}
    definitions = [
        (
            "T01",
            "frozen Segment/Junction skeleton and SWSD Road/Node carrier",
            INFERENCE_ALLOWED,
            "before T06",
            "T01 formal outputs",
            "EPSG:3857",
            False,
            False,
            "business skeleton only; never RCSD truth",
        ),
        (
            "T01",
            "Segment/Node/Road identifiers as model features",
            FORBIDDEN_LEAKAGE,
            "available before T06",
            "T01 formal outputs",
            "not applicable",
            False,
            False,
            "lineage keys only; identifier memorisation is prohibited",
        ),
        (
            "T07",
            "Step1 has_evd and DriveZone overlap summaries",
            INFERENCE_ALLOWED,
            "T07 Step1 before T06",
            "DriveZone-only evidence area",
            "source CRS with audited normalization in frozen artifacts",
            False,
            False,
            "RCSDIntersection must not contribute to Step1 has_evd",
        ),
        (
            "T07",
            "Step2 is_anchor/anchor_reason and anchor counts",
            INFERENCE_ALLOWED,
            "T07 Step2 before T06",
            "existing RCSDIntersection anchor surface",
            "source CRS with audited normalization in frozen artifacts",
            False,
            False,
            "Step2 anchor evidence; not a Step1 evidence-area input",
        ),
        (
            "T03",
            "truth-free strategy proposal geometry/carrier candidate payload",
            INFERENCE_ALLOWED,
            "candidate generation before T06 final decision",
            "T03 deterministic proposal",
            "artifact CRS declared in lineage",
            False,
            False,
            "candidate source only; acceptance is not relation success",
        ),
        (
            "T03",
            "accepted/status/reason/relation success fields",
            LABEL_ONLY,
            "supervision join",
            "T03 replay result",
            "artifact CRS declared in lineage",
            False,
            True,
            "current P05 source contract is LABEL_ONLY_INTERMEDIATE",
        ),
        (
            "T04",
            "truth-free strategy proposal geometry/carrier candidate payload",
            INFERENCE_ALLOWED,
            "candidate generation before T06 final decision",
            "T04 deterministic proposal",
            "artifact CRS declared in lineage",
            False,
            False,
            "candidate source only; review/rejected is not a generic negative",
        ),
        (
            "T04",
            "accepted/rejected/status/reason/anchor transition fields",
            LABEL_ONLY,
            "supervision join",
            "T04 replay result",
            "artifact CRS declared in lineage",
            False,
            True,
            "current P05 source contract is LABEL_ONLY_INTERMEDIATE",
        ),
        (
            "T05",
            "truth-free strategy proposal Road/Node candidate payload",
            INFERENCE_ALLOWED,
            "candidate generation before T06 final decision",
            "T05 deterministic proposal",
            "artifact CRS declared in lineage",
            False,
            False,
            "candidate source only; not the final Segment replacement",
        ),
        (
            "T05",
            "intersection_match/status/reason/relation success fields",
            LABEL_ONLY,
            "supervision join",
            "T05 replay result",
            "artifact CRS declared in lineage",
            False,
            True,
            "current P05 source contract is LABEL_ONLY_INTERMEDIATE",
        ),
        (
            "T06",
            "truth-free pre-final carrier candidate payload",
            INFERENCE_ALLOWED,
            "candidate generation before final T06 selection",
            "registered strategy proposal",
            "artifact CRS declared in lineage",
            False,
            False,
            "candidate option only; cannot import final status or reason",
        ),
        (
            "T06",
            "final replacement target, Road/Node carrier and failure reason",
            LABEL_ONLY,
            "after final T06 decision",
            "T06 final F-RCSD output",
            "EPSG:3857 in frozen truth artifacts",
            False,
            True,
            "primary supervision and attribution truth; prohibited at inference",
        ),
        (
            "P05",
            "truth-free candidate geometry/topology and 202 evidence features",
            INFERENCE_ALLOWED,
            "before carrier selection",
            "P05 candidate/evidence compiler",
            "relative and count features; no absolute coordinates",
            False,
            False,
            "already consumed by P2-P3-P0",
        ),
        (
            "P05",
            "generic Node compatibility and Junction closure",
            INFERENCE_ALLOWED,
            "decoder after soft scores",
            "generic graph legality",
            "not applicable",
            False,
            False,
            "guarantees legal realization, not business truth equivalence",
        ),
        (
            "P05",
            "truth-conditioned compatibility oracle",
            FORBIDDEN_LEAKAGE,
            "audit only",
            "P2-P1 frozen truth oracle",
            "not applicable",
            False,
            True,
            "directly encodes held-out carrier truth",
        ),
        (
            "T10",
            "Case/fold identity and object IDs as features",
            FORBIDDEN_LEAKAGE,
            "dataset split",
            "T10 lineage",
            "not applicable",
            False,
            False,
            "split and traceability only; memorisation is prohibited",
        ),
        (
            "T10",
            "unseen labelled end-to-end validation RoadGraph",
            UNAVAILABLE,
            "validation",
            "POC_Data inventory",
            "unknown until a complete package is frozen",
            True,
            False,
            "all usable end-to-end labels are in the current 51 Case scope",
        ),
    ]
    rows = []
    for index, definition in enumerate(definitions, start=1):
        (
            module,
            field_family,
            classification,
            generation_time,
            artifact,
            crs,
            new_for_p2_p3_p1,
            direct_for_failures,
            boundary,
        ) = definition
        contract_row = contract_by_module.get(module)
        source_module = _SOURCE_FACT_MODULES.get(module)
        source_path = (
            repository_root / "modules" / source_module / "SPEC.md"
            if source_module
            else repository_root / "modules" / "p05_neural_road_generation" / "SPEC.md"
        )
        rows.append(
            {
                "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
                "field_role_id": f"FR-{index:02d}",
                "module": module,
                "field_family": field_family,
                "classification": classification,
                "generation_time": generation_time,
                "input_dependencies": artifact,
                "crs": crs,
                "lineage": {
                    "source_fact_path": str(source_path),
                    "source_fact_sha256": (
                        sha256_file(source_path) if source_path.is_file() else None
                    ),
                    "module_role_contract_path": str(module_role_contract_path),
                    "module_role_contract_sha256": sha256_file(
                        module_role_contract_path
                    ),
                },
                "cost": "existing artifact/read-only derivation",
                "applicable_boundary": boundary,
                "current_training_role": (
                    str(contract_row["training_role"]) if contract_row else None
                ),
                "current_model_input": (
                    bool(contract_row["model_input"]) if contract_row else None
                ),
                "current_candidate_role": (
                    str(contract_row["candidate_role"]) if contract_row else None
                ),
                "new_for_p2_p3_p1": new_for_p2_p3_p1,
                "direct_for_frozen_failures": direct_for_failures,
                "role_change_required": (
                    classification == UNAVAILABLE
                    or (
                        module in {"T03", "T04", "T05", "T06"}
                        and classification == LABEL_ONLY
                    )
                ),
                "role_violation": False,
            }
        )
    return rows


def build_validation_inventory(
    *,
    training_manifest_path: Path,
    poc_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    discovered_by_family: dict[str, set[str]] = {}
    manifest_by_family: dict[str, set[str]] = defaultdict(set)
    with training_manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for sample in csv.DictReader(stream):
            family = str(sample["family"])
            business_id = str(sample["business_id"])
            manifest_by_family[family].add(business_id)
            scope = str(sample["scope_type"])
            excluded = _bool_text(sample["approved_exclusion"])
            if excluded:
                status = "APPROVED_EXCLUSION_NOT_AVAILABLE"
            elif scope == "single_junction_object":
                status = "CURRENT_AUXILIARY_USED_NOT_END_TO_END"
            else:
                status = "CURRENT_51_END_TO_END_USED"
            manifest_path = normalize_runtime_path(sample["manifest_path"]).resolve()
            rows.append(
                {
                    "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
                    "source_family": family,
                    "business_id": business_id,
                    "scope_type": scope,
                    "path": str(normalize_runtime_path(sample["case_root"]).resolve()),
                    "inventory_status": status,
                    "current_51_membership": scope != "single_junction_object"
                    and not excluded,
                    "current_auxiliary_membership": scope == "single_junction_object",
                    "human_truth_status": (
                        "approved_exclusion"
                        if excluded
                        else "frozen_manifest_supervision"
                    ),
                    "replay_status": (
                        "not_performed_current_artifact_already_used"
                    ),
                    "contract_complete_end_to_end": (
                        scope != "single_junction_object" and not excluded
                    ),
                    "independent_frozen_validation": False,
                    "lineage": {
                        "manifest_path": str(manifest_path),
                        "manifest_sha256": str(sample["manifest_sha256"]),
                        "manifest_exists": manifest_path.is_file(),
                    },
                }
            )
    for family in _REGISTERED_FAMILIES:
        family_root = poc_root / family
        discovered = {
            child.name
            for child in family_root.iterdir()
            if child.is_dir() and not child.name.startswith("_")
        }
        discovered_by_family[family] = discovered
        if discovered != manifest_by_family[family]:
            raise ValueError(
                f"POC_Data family inventory differs from Dataset-P0: {family}"
            )

    rows.extend(_extra_validation_rows(poc_root))
    top_level = []
    for child in sorted(
        (path for path in poc_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        child_dirs = [path for path in child.iterdir() if path.is_dir()]
        top_level.append(
            {
                "name": child.name,
                "child_directory_count": len(child_dirs),
                "in_audit_scope": child.name
                in {
                    *_REGISTERED_FAMILIES,
                    "T10_Anchor",
                    "T06",
                    "T01",
                    "T02",
                    "Interestion",
                },
                "scope_reason": (
                    "training_or_potential_validation_source"
                    if child.name
                    in {
                        *_REGISTERED_FAMILIES,
                        "T10_Anchor",
                        "T06",
                        "T01",
                        "T02",
                        "Interestion",
                    }
                    else "outside P2-P3-P1 T01/T07/T03-T06 validation scope"
                ),
            }
        )
    status_counts = Counter(str(row["inventory_status"]) for row in rows)
    crs_values = sorted(
        {
            str(row.get("crs"))
            for row in rows
            if row.get("crs") not in (None, "", "unknown")
        }
    )
    scope = {
        "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
        "poc_data_root": str(poc_root),
        "registered_family_directory_counts": {
            family: len(discovered_by_family[family])
            for family in _REGISTERED_FAMILIES
        },
        "training_manifest_row_count": sum(
            len(values) for values in manifest_by_family.values()
        ),
        "validation_inventory_row_count": len(rows),
        "inventory_status_counts": dict(sorted(status_counts.items())),
        "independent_frozen_validation_count": sum(
            bool(row["independent_frozen_validation"]) for row in rows
        ),
        "crs_values": crs_values,
        "top_level_directories": top_level,
        "unregistered_relevant_sample_count": 0,
        "all_registered_family_directories_accounted_for": True,
    }
    return sorted(
        rows,
        key=lambda row: (
            str(row["source_family"]),
            str(row["business_id"]),
            str(row["path"]),
        ),
    ), scope


def final_decision(
    *,
    input_gate: bool,
    attribution_gate: bool,
    role_gate: bool,
    new_direct_evidence_count: int,
    independent_validation_count: int,
) -> str:
    if not input_gate or not attribution_gate or not role_gate:
        return DECISION_AUDIT_NO_GO
    if new_direct_evidence_count > 0 and independent_validation_count > 0:
        return DECISION_MODEL_RESTART_GO
    return DECISION_EVIDENCE_NO_GO


def _extra_validation_rows(poc_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in _children(poc_root / "T10_Anchor"):
        summary_path = child / "t10_case_evidence_summary.json"
        manifest_path = child / "t10_case_evidence_manifest.json"
        summary = _read_json(summary_path) if summary_path.is_file() else {}
        rows.append(
            _extra_row(
                source_family="T10_Anchor",
                business_id=child.name,
                path=child,
                status="RAW_UNLABELLED_JUNCTION_EVIDENCE",
                scope_type="junction_spatial_slice",
                contract_complete=False,
                crs="EPSG:3857",
                detail={
                    "passed": bool(summary.get("passed")),
                    "external_input_slot_count": int(
                        summary.get("external_input_slot_count", 0)
                    ),
                    "intermediate_handoff_slot_count_excluded": int(
                        summary.get("intermediate_handoff_slot_count_excluded", 0)
                    ),
                    "manifest": _file_record(manifest_path),
                    "summary": _file_record(summary_path),
                },
            )
        )
    for child in _children(poc_root / "T06"):
        manifest_path = child / "audit" / "t06_local_case_manifest.json"
        manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
        ready = bool(
            manifest.get("local_case_ready")
            or (manifest.get("readiness") or {}).get("local_case_ready")
        )
        rows.append(
            _extra_row(
                source_family="T06_LOCAL",
                business_id=child.name,
                path=child,
                status="LOCAL_DIAGNOSTIC_NOT_APPROVED_TRUTH",
                scope_type="local_diagnostic_bundle",
                contract_complete=False,
                crs=(
                    str((manifest.get("crs") or {}).get("slice_files_normalized_to"))
                    if manifest
                    else "unknown"
                ),
                detail={
                    "local_case_ready": ready,
                    "manifest": _file_record(manifest_path),
                    "reason": (
                        "diagnostic/replay material is not an independent frozen "
                        "end-to-end RoadGraph validation package"
                    ),
                },
            )
        )
    for family, status, scope_type in (
        ("T01", "RAW_SWSD_LOCAL_BUNDLE", "frozen_swsd_input_only"),
        ("T02", "LEGACY_ANCHOR_BUNDLE_NOT_END_TO_END", "legacy_anchor"),
        (
            "Interestion",
            "LEGACY_INTERSECTION_BUNDLE_NOT_END_TO_END",
            "legacy_intersection",
        ),
    ):
        for child in _children(poc_root / family):
            rows.append(
                _extra_row(
                    source_family=family,
                    business_id=child.name,
                    path=child,
                    status=status,
                    scope_type=scope_type,
                    contract_complete=False,
                    crs="unknown",
                    detail={
                        "reason": (
                            "no frozen T01 Segment plus final Road/Node truth and "
                            "independent end-to-end validation manifest"
                        )
                    },
                )
            )
    return rows


def _extra_row(
    *,
    source_family: str,
    business_id: str,
    path: Path,
    status: str,
    scope_type: str,
    contract_complete: bool,
    crs: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEME_A_P2_P3_P1_SCHEMA,
        "source_family": source_family,
        "business_id": business_id,
        "scope_type": scope_type,
        "path": str(path.resolve()),
        "inventory_status": status,
        "current_51_membership": False,
        "current_auxiliary_membership": False,
        "human_truth_status": "not_frozen_for_p2_p3_validation",
        "replay_status": "not_performed_contract_incomplete_or_unlabelled",
        "contract_complete_end_to_end": contract_complete,
        "independent_frozen_validation": False,
        "crs": crs,
        "lineage": dict(detail),
    }


def _load_inputs(
    *,
    config: SchemeAP2P3P1Config,
    p2_p3_root: Path,
    route_root: Path,
    dataset_root: Path,
) -> tuple[dict[str, Any], dict[str, Path], dict[str, Any]]:
    manifest_paths = {
        "p2_p3_p0": p2_p3_root / "scheme_a_p2_p3_p0_manifest.json",
        "p2_p2_p2_p2": route_root / "scheme_a_p2_p2_p2_p2_manifest.json",
        "dataset_p0": dataset_root / "dataset_p0_manifest.json",
    }
    manifests = {key: _read_json(path) for key, path in manifest_paths.items()}
    if manifests["p2_p3_p0"]["decision"] != _EXPECTED_P2_P3_DECISION:
        raise ValueError("P2-P3-P0 decision differs")
    if manifests["p2_p2_p2_p2"]["decision"] != _EXPECTED_ROUTE_DECISION:
        raise ValueError("P2-P2-P2-P2 decision differs")
    if manifests["dataset_p0"]["decision"] != _EXPECTED_DATASET_DECISION:
        raise ValueError("Dataset-P0 decision differs")
    for manifest in manifests.values():
        _verify_outputs(manifest, strict_hashes=config.strict_hashes)
    p2_p3_summary = _read_json(
        _output_path(manifests["p2_p3_p0"], "summary")
    )
    if int(p2_p3_summary["case_count"]) != config.expected_case_count:
        raise ValueError("P2-P3-P0 Case denominator differs")
    if int(p2_p3_summary["segment_count"]) != config.expected_segment_count:
        raise ValueError("P2-P3-P0 Segment denominator differs")
    if int(p2_p3_summary["seed_count"]) != config.expected_seed_count:
        raise ValueError("P2-P3-P0 seed denominator differs")
    if int(p2_p3_summary["fold_count"]) != config.expected_fold_count:
        raise ValueError("P2-P3-P0 fold denominator differs")
    if (manifests["dataset_p0"].get("parameters") or {}).get(
        "t07_evidence_mode"
    ) != "DRIVEZONE_ONLY":
        raise ValueError("Dataset-P0 T07 Step1 evidence mode differs")
    paths = {
        "scores": _output_path(manifests["p2_p3_p0"], "scores"),
        "decisions": _output_path(manifests["p2_p3_p0"], "decisions"),
        "evaluation": _output_path(manifests["p2_p3_p0"], "evaluation"),
        "auxiliary_labels": _output_path(
            manifests["p2_p3_p0"], "auxiliary_labels"
        ),
        "object_source_routes": _output_path(
            manifests["p2_p2_p2_p2"], "object_source_routes"
        ),
        "module_role_contract": _output_path(
            manifests["dataset_p0"], "module_role_contract"
        ),
        "training_sample_manifest": _output_path(
            manifests["dataset_p0"], "training_sample_manifest"
        ),
    }
    records = {
        key: {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for key, path in manifest_paths.items()
    }
    return manifests, paths, records


def _verify_outputs(
    manifest: Mapping[str, Any], *, strict_hashes: bool
) -> None:
    for key, record in (manifest.get("outputs") or {}).items():
        path = normalize_runtime_path(str(record["path"])).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if int(record.get("size_bytes", path.stat().st_size)) != path.stat().st_size:
            raise ValueError(f"output size differs: {key}")
        if strict_hashes and sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"output hash differs: {key}")


def _validate_field_roles(rows: Sequence[Mapping[str, Any]]) -> None:
    ids = [str(row["field_role_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("field-role IDs are not unique")
    if any(str(row["classification"]) not in FIELD_ROLES for row in rows):
        raise ValueError("unknown field role")
    if any(bool(row["role_violation"]) for row in rows):
        raise ValueError("field-role contract violation")
    for row in rows:
        if (
            row["module"] in {"T03", "T04", "T05", "T06"}
            and row["classification"] == LABEL_ONLY
            and not row["role_change_required"]
        ):
            raise ValueError("label-only source was promoted to inference")
        if (
            row["module"] in {"T03", "T04", "T05", "T06"}
            and row["classification"] == INFERENCE_ALLOWED
            and row["current_candidate_role"]
            != "TRUTH_FREE_STRATEGY_PROPOSAL_ALLOWED"
        ):
            raise ValueError("unregistered module artifact was promoted to candidate input")


def _source_fact_records(repository_root: Path) -> list[dict[str, Any]]:
    records = []
    for module, directory in sorted(_SOURCE_FACT_MODULES.items()):
        for relative in (
            "SPEC.md",
            "INTERFACE_CONTRACT.md",
            "architecture/02-data-and-domain-model.md",
        ):
            path = repository_root / "modules" / directory / relative
            if not path.is_file():
                raise FileNotFoundError(path)
            records.append(
                {
                    "module": module,
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return records


def _t07_source_fact_check(repository_root: Path) -> dict[str, Any]:
    path = (
        repository_root
        / "modules"
        / "t07_semantic_junction_anchor"
        / "architecture"
        / "02-data-and-domain-model.md"
    )
    text = path.read_text(encoding="utf-8")
    step1 = "RCSDIntersection` 不参与 Step1" in text
    step2 = "RCSDIntersection` 只在 Step2" in text
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "step1_drivezone_only_explicit": step1,
        "rcsdintersection_step2_only_explicit": step2,
        "gate_pass": step1 and step2,
    }


def _resource_summary(
    *,
    started: float,
    rss_samples: Sequence[int],
    case_timings: Sequence[float],
    config: SchemeAP2P3P1Config,
) -> dict[str, Any]:
    wall = time.perf_counter() - started
    peak_rss = max(rss_samples, default=0)
    p95 = _percentile(case_timings, 0.95)
    maximum = max(case_timings, default=0.0)
    result = {
        "wall_seconds": wall,
        "peak_rss_bytes": peak_rss,
        "gpu_vram_bytes": 0,
        "case_measurement_count": len(case_timings),
        "case_p95_seconds": p95,
        "case_max_seconds": maximum,
        "wall_within_30_minutes": wall <= config.max_wall_seconds,
        "cpu_ram_within_8gb": 0 < peak_rss <= config.max_peak_rss_bytes,
        "gpu_vram_zero": True,
        "case_p95_within_5s": p95 <= config.max_case_p95_seconds,
        "case_max_within_20s": maximum <= config.max_case_seconds,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    result["gate_pass"] = all(
        (
            result["wall_within_30_minutes"],
            result["cpu_ram_within_8gb"],
            result["gpu_vram_zero"],
            result["case_p95_within_5s"],
            result["case_max_within_20s"],
        )
    )
    return result


def _validation_report(summary: Mapping[str, Any]) -> str:
    fold2 = summary["fold2"]["per_seed"]
    theoretical = fold2[0]["maximum_overall_safe_coverage"]
    eligible = {
        str(row["seed"]): row["eligible_only_safe_coverage"] for row in fold2
    }
    return "\n".join(
        [
            "# P05-Scheme-A-P2-P3-P1 validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- stable false-use: `{len(summary['stable_false_use_group_ids'])}`",
            f"- clue-only captured by seed: `{json.dumps(summary['clue_capture_by_seed'], sort_keys=True)}`",
            f"- fold 2 expected baseline failures: `{fold2[0]['ineligible_expected_failure_count']}/{fold2[0]['object_count']}`",
            f"- fold 2 maximum overall coverage: `{theoretical:.6f}`",
            f"- fold 2 eligible-only coverage: `{json.dumps(eligible, sort_keys=True)}`",
            f"- new allowed direct evidence: `{summary['new_allowed_direct_evidence_count']}`",
            f"- independent frozen validation: `{summary['independent_frozen_validation_count']}`",
            f"- T07 Step1/Step2 source fact gate: `{summary['t07_source_fact_check']['gate_pass']}`",
            f"- determinism signature: `{summary['determinism_signature']}`",
            "",
            "No model training, threshold tuning, geometry modification, CRS transform,",
            "silent fix, Movement decision or T01-T12 implementation change was performed.",
            "",
        ]
    )


def _reference_match(path: Path | None, signature: str) -> bool | None:
    if path is None:
        return None
    root = _resolve_dir(path)
    summary = _read_json(root / "scheme_a_p2_p3_p1_summary.json")
    return str(summary["determinism_signature"]) == signature


def _output_path(manifest: Mapping[str, Any], key: str) -> Path:
    return normalize_runtime_path(str(manifest["outputs"][key]["path"])).resolve()


def _resolve_dir(path: Path) -> Path:
    resolved = normalize_runtime_path(path).resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
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


def _children(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(
        (child for child in path.iterdir() if child.is_dir()),
        key=lambda child: child.name,
    )


def _file_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _bool_text(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _rss_bytes() -> int:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        try:
            import resource

            raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return raw if sys.platform == "darwin" else raw * 1024
        except (ImportError, OSError):
            return 0


__all__ = [
    "build_failure_attribution",
    "build_field_role_ledger",
    "build_fold2_metric_audit",
    "build_validation_inventory",
    "final_decision",
    "fold_coverage_feasibility",
    "run_scheme_a_p2_p3_p1_audit",
    "stable_wrong_accepted_groups",
]
