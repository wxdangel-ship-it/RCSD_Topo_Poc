from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_dataset import (
    candidate_matches_label,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_node_carriers import (
    build_endpoint_node_carriers,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p4_models import (
    SCHEME_A_P2_P3_P4_SCHEMA,
)


def build_scope_first_truth(
    *,
    baseline_labels: Mapping[tuple[str, str], Mapping[str, Any]],
    segment_candidates: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    scope_rows: Sequence[Mapping[str, Any]],
    pto_candidate_path: Any,
    p1_lineage_path: Any,
    case_folds: Mapping[str, int],
    fallback_positive_segments: set[tuple[str, str]],
    expected_missing_nodes: Sequence[tuple[str, str]],
    iteration_limit: int,
) -> dict[str, Any]:
    scope_by_key = _scope_by_key(scope_rows)
    if set(scope_by_key) != set(baseline_labels):
        raise ValueError("Dataset-P1 scope and baseline Segment identities differ")
    if set(scope_by_key) != set(segment_candidates):
        raise ValueError("Dataset-P1 scope and candidate Segment identities differ")

    labels = {key: dict(value) for key, value in baseline_labels.items()}
    context_keys: set[tuple[str, str]] = set()
    for key, scope in sorted(scope_by_key.items()):
        candidates = segment_candidates[key]
        if not candidates or str(candidates[0]["group_id"]) != str(scope["group_id"]):
            raise ValueError(f"Dataset-P1 group identity differs: {key}")
        if bool(scope["label_eligible"]):
            continue
        if str(scope["scope_class"]) != "CONTEXT_ONLY_MASKED":
            raise ValueError(f"non-label Segment is not context-only: {key}")
        safe = _unique_safe_candidate(candidates, key)
        labels[key].update(
            {
                "carrier_target": "KEEP_SWSD",
                "target_kind": safe["target_kind"],
                "target_payload": safe["target_payload"],
                "available": True,
                "mask_reason": "dataset_p1_context_only_safe_materialization",
                "scope_first_context": True,
            }
        )
        context_keys.add(key)

    initial = build_endpoint_node_carriers(
        pto_candidate_path=pto_candidate_path,
        p1_lineage_path=p1_lineage_path,
        segment_candidates=segment_candidates,
        segment_labels=labels,
        case_folds=case_folds,
        expected_missing_nodes=expected_missing_nodes,
    )
    initial_conflicts = list(initial["shared_payload_conflicts"])
    closure_keys: set[tuple[str, str]] = set()
    node_bundle = initial
    for _ in range(iteration_limit):
        requested = {
            (str(case_key), str(segment_id))
            for case_key, segment_id in node_bundle[
                "junction_fallback_segment_keys"
            ]
        }
        new_keys = requested - closure_keys
        if not requested:
            break
        if not new_keys:
            raise ValueError("scope-first Junction fallback did not converge")
        for key in sorted(new_keys):
            safe = _unique_safe_candidate(segment_candidates[key], key)
            labels[key].update(
                {
                    "carrier_target": "KEEP_SWSD",
                    "target_kind": safe["target_kind"],
                    "target_payload": safe["target_payload"],
                    "available": True,
                    "mask_reason": (
                        "scope_first_shared_node_payload_conflict_junction_fallback"
                    ),
                    "junction_fallback": True,
                }
            )
        closure_keys.update(new_keys)
        node_bundle = build_endpoint_node_carriers(
            pto_candidate_path=pto_candidate_path,
            p1_lineage_path=p1_lineage_path,
            segment_candidates=segment_candidates,
            segment_labels=labels,
            case_folds=case_folds,
            expected_missing_nodes=expected_missing_nodes,
        )
    else:
        raise ValueError("scope-first Junction fallback iteration limit exceeded")

    if node_bundle["shared_payload_conflicts"] or node_bundle["missing"]:
        raise ValueError("scope-first Node/Junction truth closure is incomplete")

    segment_rows: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    target_counts: Counter[str] = Counter()
    for key in sorted(labels):
        label = labels[key]
        scope = scope_by_key[key]
        matches = [
            row
            for row in segment_candidates[key]
            if candidate_matches_label(row, label)
        ]
        if len(matches) != 1:
            raise ValueError(f"scope-first truth candidate is not unique: {key}")
        candidate_id = str(matches[0]["candidate_id"])
        if candidate_id in candidate_ids:
            raise ValueError(f"scope-first truth candidate is reused: {candidate_id}")
        candidate_ids.add(candidate_id)
        eligible = bool(scope["label_eligible"])
        anomaly = (
            key in fallback_positive_segments
            or key in closure_keys
            or not bool(label["available"])
        )
        target = str(label["carrier_target"])
        target_counts[target] += 1
        segment_rows.append(
            {
                "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
                "case_key": key[0],
                "object_type": "SEGMENT",
                "object_id": key[1],
                "group_id": str(scope["group_id"]),
                "fold": int(scope["fold"]),
                "scope_class": str(scope["scope_class"]),
                "label_eligible": eligible,
                "scorer_metric_eligible": bool(scope["scorer_metric_eligible"]),
                "label_weight": (
                    float(scope["label_weight"])
                    if scope.get("label_weight") is not None
                    else None
                ),
                "context_input_eligible": bool(scope["context_input_eligible"]),
                "context_input_weight": (
                    float(scope["context_input_weight"])
                    if scope.get("context_input_weight") is not None
                    else None
                ),
                "effective_truth_candidate_id": candidate_id,
                "effective_carrier_target": target,
                "effective_available": bool(label["available"]),
                "effective_anomaly_target": anomaly if eligible else None,
                "label_truth_contribution": 1 if eligible else 0,
                "safe_materialization_only": not eligible,
                "junction_fallback": key in closure_keys,
                "truth_source": (
                    "SCHEME_A_BASELINE_AFTER_SCOPE_FREEZE"
                    if eligible
                    else "DATASET_P1_CONTEXT_SAFE_KEEP"
                ),
            }
        )

    closure_rows = [
        {
            "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
            "case_key": key[0],
            "object_id": key[1],
            "group_id": str(scope_by_key[key]["group_id"]),
            "label_eligible": bool(scope_by_key[key]["label_eligible"]),
            "scope_class": str(scope_by_key[key]["scope_class"]),
            "effective_target": "KEEP_SWSD",
            "reason": "shared_node_payload_conflict_requires_junction_fallback",
        }
        for key in sorted(closure_keys)
    ]
    return {
        "segment_labels": segment_rows,
        "node_labels": list(node_bundle["labels"]),
        "initial_node_conflicts": initial_conflicts,
        "junction_fallback_closure": closure_rows,
        "target_counts": dict(sorted(target_counts.items())),
        "context_keys": context_keys,
        "closure_keys": closure_keys,
    }


def build_label_delta(
    corrected_rows: Sequence[Mapping[str, Any]],
    old_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    old_by_group = {
        str(row["group_id"]): row
        for row in old_rows
        if row.get("object_type") == "SEGMENT"
    }
    if len(old_by_group) != len(corrected_rows):
        raise ValueError("historical and corrected Segment label denominators differ")
    result: list[dict[str, Any]] = []
    for corrected in corrected_rows:
        group_id = str(corrected["group_id"])
        old = old_by_group.get(group_id)
        if old is None:
            raise ValueError(f"historical Segment label is missing: {group_id}")
        changed_fields: list[str] = []
        comparisons = {
            "carrier_target": (
                str(old["carrier_target"]),
                str(corrected["effective_carrier_target"]),
            ),
            "truth_candidate_id": (
                str(old["truth_candidate_id"]),
                str(corrected["effective_truth_candidate_id"]),
            ),
            "anomaly_target": (
                bool(old["anomaly_target"]),
                corrected["effective_anomaly_target"],
            ),
        }
        for field, (before, after) in comparisons.items():
            if after is not None and before != after:
                changed_fields.append(field)
        if not changed_fields:
            continue
        result.append(
            {
                "schema_version": SCHEME_A_P2_P3_P4_SCHEMA,
                "case_key": str(corrected["case_key"]),
                "object_id": str(corrected["object_id"]),
                "group_id": group_id,
                "scope_class": str(corrected["scope_class"]),
                "label_eligible": bool(corrected["label_eligible"]),
                "changed_fields": changed_fields,
                "old_carrier_target": str(old["carrier_target"]),
                "new_carrier_target": str(
                    corrected["effective_carrier_target"]
                ),
                "old_truth_candidate_id": str(old["truth_candidate_id"]),
                "new_truth_candidate_id": str(
                    corrected["effective_truth_candidate_id"]
                ),
                "old_anomaly_target": bool(old["anomaly_target"]),
                "new_anomaly_target": corrected["effective_anomaly_target"],
            }
        )
    return sorted(result, key=lambda row: str(row["group_id"]))


def rebaseline_metrics(
    *,
    corrected_rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    evaluations: Sequence[Mapping[str, Any]],
    effective_rows: Sequence[Mapping[str, Any]],
    model_seeds: Sequence[int],
    minimum_safe_coverage: float,
    minimum_use_coverage: float,
    minimum_clue_precision: float,
    minimum_clue_macro_f1: float,
) -> dict[str, Any]:
    truth = {
        str(row["group_id"]): row
        for row in corrected_rows
        if bool(row["label_eligible"])
    }
    decision_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in decisions
    }
    evaluation_by_key = {
        (int(row["seed"]), str(row["group_id"])): row for row in evaluations
    }
    effective_by_key = {
        (int(row["seed"]), str(row["group_id"])): row
        for row in effective_rows
        if row.get("object_type") == "SEGMENT"
        and str(row["group_id"]) in truth
    }
    expected = len(truth) * len(model_seeds)
    for name, values in (
        ("decision", decision_by_key),
        ("evaluation", evaluation_by_key),
        ("effective", effective_by_key),
    ):
        if len(values) != expected:
            raise ValueError(f"{name} metric denominator differs")

    seed_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    folds = sorted({int(row["fold"]) for row in truth.values()})
    for seed in model_seeds:
        seed_rows.append(
            _scope_metrics(
                seed=seed,
                fold=None,
                truth=truth,
                decisions=decision_by_key,
                evaluations=evaluation_by_key,
                effective=effective_by_key,
                minimum_safe_coverage=minimum_safe_coverage,
                minimum_use_coverage=minimum_use_coverage,
                minimum_clue_precision=minimum_clue_precision,
                minimum_clue_macro_f1=minimum_clue_macro_f1,
            )
        )
        for fold in folds:
            fold_rows.append(
                _scope_metrics(
                    seed=seed,
                    fold=fold,
                    truth=truth,
                    decisions=decision_by_key,
                    evaluations=evaluation_by_key,
                    effective=effective_by_key,
                    minimum_safe_coverage=minimum_safe_coverage,
                    minimum_use_coverage=minimum_use_coverage,
                    minimum_clue_precision=minimum_clue_precision,
                    minimum_clue_macro_f1=minimum_clue_macro_f1,
                )
            )
    model_gate = all(
        bool(row["carrier_gate_pass"]) and bool(row["clue_gate_pass"])
        for row in seed_rows + fold_rows
    )
    return {
        "seed_metrics": seed_rows,
        "fold_metrics": fold_rows,
        "accepted_wrong_by_seed": {
            str(row["seed"]): int(row["carrier_wrong_accepted_count"])
            for row in seed_rows
        },
        "review_auto_publish_by_seed": {
            str(row["seed"]): int(row["review_auto_publish_count"])
            for row in seed_rows
        },
        "carrier_safety_recall_by_seed": {
            str(row["seed"]): float(row["carrier_safety_recall"])
            for row in seed_rows
        },
        "model_gate_pass": model_gate,
        "model_decision": (
            "MODEL_GO" if model_gate else "MODEL_NO_GO_COVERAGE_OR_CLUE_UNSTABLE"
        ),
    }


def _scope_metrics(
    *,
    seed: int,
    fold: int | None,
    truth: Mapping[str, Mapping[str, Any]],
    decisions: Mapping[tuple[int, str], Mapping[str, Any]],
    evaluations: Mapping[tuple[int, str], Mapping[str, Any]],
    effective: Mapping[tuple[int, str], Mapping[str, Any]],
    minimum_safe_coverage: float,
    minimum_use_coverage: float,
    minimum_clue_precision: float,
    minimum_clue_macro_f1: float,
) -> dict[str, Any]:
    group_ids = [
        group_id
        for group_id, row in truth.items()
        if fold is None or int(row["fold"]) == fold
    ]
    wrong_accepted = review_auto = unsafe_count = 0
    correct_auto = non_review_count = use_count = use_correct_auto = 0
    tp = fp = fn = tn = 0
    for group_id in group_ids:
        row = truth[group_id]
        decision = decisions[(seed, group_id)]
        evaluation = evaluations[(seed, group_id)]
        final = effective[(seed, group_id)]
        truth_id = str(row["effective_truth_candidate_id"])
        truth_target = str(row["effective_carrier_target"])
        accepted = bool(final["accepted"])
        correct = str(final["effective_candidate_id"]) == truth_id
        wrong_accepted += int(accepted and not correct)
        review_auto += int(accepted and truth_target == "REVIEW_FALLBACK")
        raw_unsafe = (
            str(evaluation["selected_candidate_id"]) != truth_id
            or truth_target == "REVIEW_FALLBACK"
        )
        unsafe_count += int(raw_unsafe)
        if truth_target != "REVIEW_FALLBACK":
            non_review_count += 1
            correct_auto += int(accepted and correct)
        if truth_target == "USE_RCSD":
            use_count += 1
            use_correct_auto += int(accepted and correct)
        clue_truth = bool(row["effective_anomaly_target"])
        clue_predicted = bool(decision["clue_predicted"])
        tp += int(clue_truth and clue_predicted)
        fp += int(not clue_truth and clue_predicted)
        fn += int(clue_truth and not clue_predicted)
        tn += int(not clue_truth and not clue_predicted)
    safety_recall = 1.0 - (wrong_accepted + review_auto) / max(1, unsafe_count)
    safe_coverage = correct_auto / max(1, non_review_count)
    use_coverage = use_correct_auto / max(1, use_count)
    clue_recall = tp / max(1, tp + fn)
    clue_precision = tp / max(1, tp + fp)
    macro_f1 = (_f1(tp, fp, fn) + _f1(tn, fn, fp)) / 2
    carrier_gate = (
        wrong_accepted == 0
        and review_auto == 0
        and safety_recall == 1.0
        and safe_coverage >= minimum_safe_coverage
        and use_coverage >= minimum_use_coverage
    )
    clue_gate = (
        clue_recall == 1.0
        and clue_precision >= minimum_clue_precision
        and macro_f1 >= minimum_clue_macro_f1
    )
    return {
        "scope": "SEED" if fold is None else "FOLD",
        "seed": seed,
        "fold": fold,
        "group_count": len(group_ids),
        "carrier_wrong_accepted_count": wrong_accepted,
        "review_auto_publish_count": review_auto,
        "carrier_unsafe_count": unsafe_count,
        "carrier_safety_recall": safety_recall,
        "safe_coverage": safe_coverage,
        "use_rcsd_safe_coverage": use_coverage,
        "clue_true_positive": tp,
        "clue_false_positive": fp,
        "clue_false_negative": fn,
        "clue_true_negative": tn,
        "clue_recall": clue_recall,
        "clue_precision": clue_precision,
        "clue_macro_f1": macro_f1,
        "carrier_gate_pass": carrier_gate,
        "clue_gate_pass": clue_gate,
    }


def _scope_by_key(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["object_id"]))
        if key in result:
            raise ValueError(f"duplicate Dataset-P1 Segment scope identity: {key}")
        if not bool(row["context_input_eligible"]):
            raise ValueError(f"Segment is unavailable as context input: {key}")
        result[key] = row
    return result


def _unique_safe_candidate(
    rows: Sequence[Mapping[str, Any]],
    key: tuple[str, str],
) -> Mapping[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("candidate_target") == "KEEP_SWSD"
        and row.get("target_payload")
    ]
    if len(matches) != 1:
        raise ValueError(f"Segment has no unique safe SWSD carrier: {key}")
    return matches[0]


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return 2 * precision * recall / max(1e-12, precision + recall)


__all__ = [
    "build_label_delta",
    "build_scope_first_truth",
    "rebaseline_metrics",
]
