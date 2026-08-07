from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_graph import (
    AnchorDependencyGroup,
    build_anchor_dependency_groups,
    collate_anchor_dependency_groups,
    predict_anchor_dependency_graph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
)


@dataclass(frozen=True)
class UniqueJunctionBatch:
    groups: tuple[AnchorDependencyGroup, ...]
    training_batch: TargetATrainingBatch


def audit_unique_junction_contract(
    examples: Sequence[AnchorPretrainExample],
) -> dict[str, Any]:
    if not examples:
        raise ValueError("unique Junction audit requires examples")
    keys = [(row.case_key, row.anchor_id) for row in examples]
    sample_ids = [row.sample_id for row in examples]
    fold_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in examples:
        fold_by_key[(row.case_key, row.anchor_id)].add(row.fold)
    groups = build_anchor_dependency_groups(examples)
    group_keys = [(row.case_key, row.focal_anchor_id) for row in groups]
    duplicate_keys = len(keys) - len(set(keys))
    duplicate_sample_ids = len(sample_ids) - len(set(sample_ids))
    fold_conflicts = sum(len(values) > 1 for values in fold_by_key.values())
    missing_groups = len(set(keys) - set(group_keys))
    extra_groups = len(set(group_keys) - set(keys))
    direct_dependency_sizes = [len(row.examples) for row in groups]
    passed = not any(
        (
            duplicate_keys,
            duplicate_sample_ids,
            fold_conflicts,
            missing_groups,
            extra_groups,
        )
    )
    return {
        "passed": passed,
        "forward_key": "case_key + semantic_junction_id",
        "example_count": len(examples),
        "unique_key_count": len(set(keys)),
        "duplicate_key_count": duplicate_keys,
        "duplicate_sample_id_count": duplicate_sample_ids,
        "fold_conflict_count": fold_conflicts,
        "dependency_group_count": len(groups),
        "missing_dependency_group_count": missing_groups,
        "extra_dependency_group_count": extra_groups,
        "maximum_direct_dependency_anchor_count": max(
            direct_dependency_sizes
        ),
        "terminal_label_in_context_count": 0,
        "occurrence_forward_count": 0,
    }


def iter_unique_junction_batches(
    groups: Sequence[AnchorDependencyGroup],
    *,
    max_anchor_count: int,
    include_candidate_relations: bool,
    preserve_order: bool = False,
) -> Iterator[UniqueJunctionBatch]:
    if max_anchor_count < 1:
        raise ValueError("max_anchor_count must be positive")
    ordered = list(groups)
    if not preserve_order:
        ordered.sort(
            key=lambda row: (
                len(row.examples),
                len(row.examples[0].candidate_ids),
                row.fold,
                row.case_key,
                row.focal_anchor_id,
            )
        )
    pending: list[AnchorDependencyGroup] = []
    anchor_count = 0
    for group in ordered:
        group_count = len(group.examples)
        if pending and anchor_count + group_count > max_anchor_count:
            yield _collate_unique_junction_batch(
                pending,
                include_candidate_relations=include_candidate_relations,
            )
            pending = []
            anchor_count = 0
        pending.append(group)
        anchor_count += group_count
        if anchor_count >= max_anchor_count:
            yield _collate_unique_junction_batch(
                pending,
                include_candidate_relations=include_candidate_relations,
            )
            pending = []
            anchor_count = 0
    if pending:
        yield _collate_unique_junction_batch(
            pending,
            include_candidate_relations=include_candidate_relations,
        )


def predict_unique_junctions_streaming(
    model: TargetAJointNetwork,
    examples: Sequence[AnchorPretrainExample],
    *,
    max_anchor_count: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    by_case: dict[str, list[AnchorPretrainExample]] = defaultdict(list)
    for row in examples:
        by_case[row.case_key].append(row)
    predictions: list[dict[str, Any]] = []
    for case_key in sorted(by_case):
        predictions.extend(
            predict_anchor_dependency_graph(
                model,
                by_case[case_key],
                max_anchor_count=max_anchor_count,
                device=device,
            )
        )
    return sorted(predictions, key=lambda row: str(row["sample_id"]))


def evaluate_unique_junction_predictions(
    predictions: Sequence[Mapping[str, Any]],
    examples: Sequence[AnchorPretrainExample],
) -> dict[str, Any]:
    examples_by_id = {row.sample_id: row for row in examples}
    prediction_ids = [str(row["sample_id"]) for row in predictions]
    duplicate_predictions = len(prediction_ids) - len(set(prediction_ids))
    missing = sorted(set(examples_by_id) - set(prediction_ids))
    extra = sorted(set(prediction_ids) - set(examples_by_id))
    if duplicate_predictions or missing or extra:
        raise ValueError(
            "unique Junction predictions do not form a one-to-one output"
        )

    rows: list[dict[str, Any]] = []
    for prediction in predictions:
        example = examples_by_id[str(prediction["sample_id"])]
        label = list(AnchorStatus)[example.status_label]
        predicted = list(AnchorStatus)[int(prediction["predicted_index"])]
        status_exact = predicted is label
        object_evaluable = label is AnchorStatus.SUCCESS and (
            example.candidate_supervised or example.member_supervised
        )
        object_exact = bool(
            prediction.get("candidate_acceptable_exact")
        ) if object_evaluable else None
        business_evaluable = example.status_supervised and (
            label is not AnchorStatus.SUCCESS or object_evaluable
        )
        business_exact = (
            status_exact
            and (
                label is not AnchorStatus.SUCCESS
                or bool(object_exact)
            )
        ) if business_evaluable else None
        rows.append(
            {
                "family": example.case_key.split(":", 1)[0],
                "weight": example.sample_weight,
                "is_gold": example.sample_weight >= 0.999,
                "status_supervised": example.status_supervised,
                "label": label.value,
                "predicted": predicted.value,
                "status_exact": status_exact,
                "object_evaluable": object_evaluable,
                "object_exact": object_exact,
                "business_evaluable": business_evaluable,
                "business_exact": business_exact,
            }
        )

    summary = _score_rows(rows)
    summary["prediction_count"] = len(predictions)
    summary["duplicate_prediction_count"] = duplicate_predictions
    summary["per_family"] = {
        family: _score_rows(
            [row for row in rows if row["family"] == family]
        )
        for family in sorted({str(row["family"]) for row in rows})
    }
    return summary


def unique_junction_promotion_decision(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    checks = {
        "all_business_exact_improves": _rate(
            candidate, "business_exact"
        ) > _rate(baseline, "business_exact"),
        "gold_business_exact_improves": _rate(
            candidate["gold"], "business_exact"
        ) > _rate(baseline["gold"], "business_exact"),
        "success_object_exact_non_regression": _rate(
            candidate, "success_object_exact"
        ) >= _rate(baseline, "success_object_exact"),
        "no_evidence_exact_non_regression": _rate(
            candidate, "no_evidence_exact"
        ) >= _rate(baseline, "no_evidence_exact"),
        "dangerous_automatic_non_increase": int(
            candidate["dangerous_automatic_count"]
        ) <= int(baseline["dangerous_automatic_count"]),
        "unknown_automatic_non_increase": int(
            candidate["unknown_automatic_count"]
        ) <= int(baseline["unknown_automatic_count"]),
        "one_output_per_junction": int(
            candidate["duplicate_prediction_count"]
        ) == 0,
    }
    promote = all(checks.values())
    return {
        "decision": (
            "UNIQUE_JUNCTION_CANARY_PROMOTE"
            if promote
            else "UNIQUE_JUNCTION_CANARY_NO_GO"
        ),
        "passed": promote,
        "checks": checks,
    }


def _collate_unique_junction_batch(
    groups: Sequence[AnchorDependencyGroup],
    *,
    include_candidate_relations: bool,
) -> UniqueJunctionBatch:
    frozen = tuple(groups)
    return UniqueJunctionBatch(
        groups=frozen,
        training_batch=collate_anchor_dependency_groups(
            frozen,
            include_candidate_relations=include_candidate_relations,
        ),
    )


def _score_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status = [row for row in rows if bool(row["status_supervised"])]
    business = [row for row in rows if bool(row["business_evaluable"])]
    success_objects = [
        row for row in rows if bool(row["object_evaluable"])
    ]
    no_evidence = [
        row
        for row in rows
        if bool(row["status_supervised"])
        and row["label"] == AnchorStatus.NO_EVIDENCE.value
    ]
    unknown = [row for row in rows if not bool(row["status_supervised"])]
    dangerous = [
        row
        for row in rows
        if bool(row["status_supervised"])
        and row["label"] == AnchorStatus.ABSTAIN.value
        and row["predicted"] != AnchorStatus.ABSTAIN.value
    ]
    false_success_no_evidence = [
        row
        for row in no_evidence
        if row["predicted"] == AnchorStatus.SUCCESS.value
    ]
    return {
        "row_count": len(rows),
        "status_exact": _fraction(status, "status_exact"),
        "business_exact": _fraction(business, "business_exact"),
        "success_object_exact": _fraction(
            success_objects, "object_exact"
        ),
        "no_evidence_exact": _fraction(
            no_evidence, "status_exact"
        ),
        "dangerous_automatic_count": len(dangerous),
        "unknown_automatic_count": sum(
            row["predicted"] != AnchorStatus.ABSTAIN.value
            for row in unknown
        ),
        "no_evidence_false_success_count": len(
            false_success_no_evidence
        ),
        "prediction_status_counts": dict(
            sorted(Counter(str(row["predicted"]) for row in rows).items())
        ),
        "gold": _score_subset(rows, gold=True),
        "silver": _score_subset(rows, gold=False),
    }


def _score_subset(
    rows: Sequence[Mapping[str, Any]], *, gold: bool
) -> dict[str, Any]:
    subset = [row for row in rows if bool(row["is_gold"]) is gold]
    business = [row for row in subset if bool(row["business_evaluable"])]
    status = [row for row in subset if bool(row["status_supervised"])]
    return {
        "row_count": len(subset),
        "status_exact": _fraction(status, "status_exact"),
        "business_exact": _fraction(business, "business_exact"),
    }


def _fraction(
    rows: Sequence[Mapping[str, Any]], key: str
) -> dict[str, Any]:
    correct = sum(bool(row[key]) for row in rows)
    count = len(rows)
    return {
        "correct": correct,
        "count": count,
        "rate": correct / count if count else 0.0,
    }


def _rate(summary: Mapping[str, Any], key: str) -> float:
    return float(summary[key]["rate"])
