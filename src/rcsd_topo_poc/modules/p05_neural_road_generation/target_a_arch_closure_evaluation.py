from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_coordination import (
    COORDINATION_ACCEPT,
    ArchClosureSegmentPlan,
    coordinate_arch_closure_plans,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureJunctionCacheEntry,
    ArchClosureReferenceStores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_network import (
    _plan_proposal_compatibility,
)


DECISION_NAMES = {
    ORDINARY_DECISION_KEEP_SWSD: "KEEP_SWSD",
    ORDINARY_DECISION_USE_RCSD: "USE_RCSD",
    ORDINARY_DECISION_ABSTAIN: "ABSTAIN",
}


def arch_closure_batch_prediction_rows(
    outputs: Mapping[str, torch.Tensor],
    batch: Any,
) -> list[dict[str, Any]]:
    ordinary = batch.ordinary
    access = batch.access
    breaks = batch.breaks
    structured = batch.structured
    selected = outputs["ordinary_structured_plan_selected_indices"]
    selected_valid = outputs["ordinary_structured_plan_selected_valid"]
    acceptable = structured.acceptable_plan_mask
    task = structured.task_mask
    compatibility = _plan_proposal_compatibility(
        structured.plan_road_membership,
        structured.plan_access_road_membership,
        structured.access_group_arm_indices,
        access.proposal_road_indices,
    )
    access_logits = outputs["ordinary_access_collection_member_logits"][:, 0]
    access_cardinality = outputs[
        "ordinary_access_collection_cardinality_logits"
    ][:, 0].argmax(dim=-1)
    predicted_access = _decode_topk(
        access_logits,
        access.proposal_mask[:, 0],
        access_cardinality,
    )
    access_task = access.task_mask[:, 0]
    access_group_exact = access_task & predicted_access.eq(
        access.proposal_targets[:, 0]
    ).all(dim=-1)
    access_ready = access_task.any(dim=-1)
    access_exact = access_ready & (access_group_exact | ~access_task).all(dim=-1)

    break_presence = outputs["ordinary_break_presence_logits"][:, 0].gt(0.0)
    break_cardinality = outputs[
        "ordinary_break_cardinality_logits"
    ][:, 0].argmax(dim=-1)
    predicted_breaks = _decode_topk(
        outputs["ordinary_break_member_logits"][:, 0],
        breaks.candidate_mask[:, 0],
        break_cardinality,
    )
    predicted_ownership = outputs["ordinary_break_ownership_logits"][
        :, 0
    ].argmax(dim=-1)
    break_task = breaks.task_mask[:, 0] & breaks.parent_mask[:, 0]
    break_group_exact = break_task & (
        break_presence.eq(breaks.presence_targets[:, 0])
        & break_cardinality.eq(breaks.cardinality_targets[:, 0])
        & predicted_breaks.eq(breaks.candidate_targets[:, 0]).all(dim=-1)
        & predicted_ownership.eq(breaks.ownership_targets[:, 0])
    )
    break_ready = break_task.any(dim=-1)
    break_exact = break_ready & (break_group_exact | ~break_task).all(dim=-1)

    decision_prediction = outputs["ordinary_side_decision_logits"][
        :, 0
    ].argmax(dim=-1)
    effective_decision = outputs["ordinary_effective_business_decisions"][:, 0]
    anchor_state = outputs["ordinary_anchor_business_state"][:, 0]
    rows = []
    for index, example in enumerate(batch.examples):
        chosen = int(selected[index, 0])
        reachable = bool(task[index, 0])
        valid = bool(selected_valid[index, 0])
        exact = bool(
            reachable and valid and acceptable[index, 0, chosen]
        )
        plan_access = compatibility[index, 0, chosen]
        access_road_exact = bool(
            (
                (~access.proposal_targets[index, 0] | plan_access).all(dim=-1)
                | ~access_task[index]
            ).all()
        )
        coverage = example.ledger["field_coverage"]
        vacuous_access = bool(
            coverage["access_complete_for_required_junctions"]
            and not example.ledger["access_labels"]
        )
        vacuous_break = bool(
            coverage["break_complete_for_required_parent_roads"]
            and not example.ledger["break_labels"]
        )
        complete_access = bool(access_exact[index] or vacuous_access)
        complete_break = bool(break_exact[index] or vacuous_break)
        rows.append(
            {
                "case_key": example.joint.case_key,
                "segment_id": example.road_pool.segment_id,
                "fold": int(example.joint.fold),
                "predicted_decision": DECISION_NAMES[
                    int(decision_prediction[index])
                ],
                "effective_decision": DECISION_NAMES[
                    int(effective_decision[index])
                ],
                "anchor_business_state": int(anchor_state[index]),
                "structured_plan_ledger_task": bool(
                    example.ledger["plan_label"].get("task_mask")
                ),
                "structured_plan_reachable": reachable,
                "structured_plan_output": valid,
                "structured_plan_exact": exact,
                "structured_plan_access_road_exact": access_road_exact,
                "structured_plan_selected_id": (
                    structured.plan_ids[index][0][chosen] if valid else ""
                ),
                "complete_access_exact": complete_access,
                "complete_break_exact": complete_break,
                "strict_full_business_evaluable": bool(
                    coverage["full_business_evaluable"]
                ),
                "truth_road_count": len(example.road_pool.acceptable_road_ids),
            }
        )
    return rows


def evaluate_arch_closure_predictions(
    stores: ArchClosureReferenceStores,
    junction_cache: Mapping[
        tuple[str, str], ArchClosureJunctionCacheEntry
    ],
    predictions: Sequence[Mapping[str, Any]],
    *,
    fold: int,
    variant: str,
) -> dict[str, Any]:
    target_keys = {
        key for key, row in stores.segments.items() if row.example.fold == fold
    }
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source in predictions:
        key = (str(source["case_key"]), str(source["segment_id"]))
        if key in by_key:
            raise ValueError(f"prediction duplicates Segment output: {key}")
        if key not in target_keys:
            raise ValueError(f"prediction is outside target Fold: {key}")
        by_key[key] = dict(source)
    if set(by_key) != target_keys:
        missing = sorted(target_keys - set(by_key))
        raise ValueError(f"prediction misses target Segments: {missing[:20]}")

    anchor_truth = {
        key: _evaluate_anchor(record.example, junction_cache[key])
        for key, record in stores.junctions.items()
        if key in junction_cache
    }
    segment_rows = []
    selected_plans = []
    for key in sorted(target_keys):
        source = by_key[key]
        segment = stores.segments[key]
        required = [anchor_truth[value] for value in segment.required_junction_keys]
        anchor_ready = bool(required) and all(row["truth_ready"] for row in required)
        anchor_exact = anchor_ready and all(row["exact"] for row in required)
        anchor_scope = _segment_anchor_scope(required)
        structured_exact = bool(source.get("structured_plan_exact"))
        access_road_exact = bool(
            source.get("structured_plan_access_road_exact")
        )
        complete_access_exact = bool(source.get("complete_access_exact"))
        complete_break_exact = bool(source.get("complete_break_exact"))
        full_evaluable = bool(source.get("strict_full_business_evaluable"))
        component_full_exact = bool(
            full_evaluable
            and anchor_exact
            and structured_exact
            and access_road_exact
            and complete_access_exact
            and complete_break_exact
        )
        plan = _selected_plan(stores, key, source)
        selected_plans.append(plan)
        truth_road_count = int(
            source.get("truth_road_count")
            or len(stores.plans[key].road_pool.acceptable_road_ids)
        )
        segment_rows.append(
            {
                **source,
                "variant": variant,
                "case_key": key[0],
                "segment_id": key[1],
                "fold": fold,
                "anchor_truth_ready": anchor_ready,
                "anchor_exact": anchor_exact,
                "anchor_scope": anchor_scope,
                "component_full_exact": component_full_exact,
                "truth_road_count": truth_road_count,
                "road_bucket": _road_bucket(truth_road_count),
                "required_junction_count": len(segment.required_junction_keys),
                "shared_junction": any(
                    len(stores.junctions[junction_key].direct_segment_keys) > 1
                    for junction_key in segment.required_junction_keys
                ),
            }
        )

    coordination = coordinate_arch_closure_plans(stores, selected_plans)
    enriched = []
    for row in segment_rows:
        key = (str(row["case_key"]), str(row["segment_id"]))
        coordination_status = coordination.status_by_segment[key]
        automatic = bool(
            coordination_status == COORDINATION_ACCEPT
            and str(row.get("effective_decision")) in {"KEEP_SWSD", "USE_RCSD"}
            and row.get("structured_plan_output")
        )
        segment_full_exact = bool(row["component_full_exact"] and automatic)
        enriched.append(
            {
                **row,
                "coordination_status": coordination_status,
                "automatic_business_output": automatic,
                "segment_full_exact": segment_full_exact,
            }
        )
    segment_rows = enriched
    segment_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in segment_rows
    }

    junction_rows = []
    for junction_key, junction in sorted(stores.junctions.items()):
        direct = tuple(
            key for key in junction.direct_segment_keys if key in target_keys
        )
        if not direct:
            continue
        truth = anchor_truth[junction_key]
        full_evaluable = bool(
            truth["truth_ready"]
            and all(
                bool(segment_by_key[key]["strict_full_business_evaluable"])
                for key in direct
            )
        )
        exact = bool(
            full_evaluable
            and truth["exact"]
            and all(segment_by_key[key]["segment_full_exact"] for key in direct)
        )
        junction_rows.append(
            {
                "variant": variant,
                "case_key": junction_key[0],
                "semantic_junction_id": junction_key[1],
                "fold": fold,
                "direct_segment_ids": [key[1] for key in direct],
                "direct_segment_count": len(direct),
                "anchor_scope": truth["scope"],
                "anchor_truth_ready": truth["truth_ready"],
                "anchor_exact": truth["exact"],
                "junction_group_evaluable": full_evaluable,
                "junction_group_exact": exact,
                "has_coordination_fallback": any(
                    segment_by_key[key]["coordination_status"]
                    != COORDINATION_ACCEPT
                    for key in direct
                ),
            }
        )
    scoreboard = _scoreboard(
        segment_rows,
        junction_rows,
        duplicate_owner_road_count=len(coordination.duplicate_owner_roads),
        coordination_fallback_count=len(coordination.fallback_segment_keys),
    )
    return {
        "schema_version": "p05-target-a-arch-closure-scoreboard-v1",
        "variant": variant,
        "fold": fold,
        "scoreboard": scoreboard,
        "segment_rows": segment_rows,
        "junction_rows": junction_rows,
    }


def _evaluate_anchor(
    example: Any,
    cached: ArchClosureJunctionCacheEntry,
) -> dict[str, Any]:
    if not example.status_supervised:
        return {"scope": "UNKNOWN", "truth_ready": False, "exact": False}
    target = tuple(AnchorStatus)[int(example.status_label)]
    if target == AnchorStatus.SUCCESS:
        if not example.candidate_supervised:
            return {"scope": "UNKNOWN", "truth_ready": False, "exact": False}
        acceptable = {
            str(example.candidate_ids[index])
            for index in example.candidate_acceptable_indices
        }
        exact = bool(
            cached.business_state == ORDINARY_ANCHOR_SUCCESS
            and cached.candidate_id in acceptable
        )
        scope = (
            "MULTI_ROAD_ANCHOR"
            if any(len(values) > 1 for values in example.member_acceptable_sets)
            else "UNIQUE_ANCHOR"
        )
        return {"scope": scope, "truth_ready": True, "exact": exact}
    if target == AnchorStatus.NO_EVIDENCE:
        return {
            "scope": "PROVEN_NO_EVIDENCE",
            "truth_ready": True,
            "exact": cached.business_state == ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
        }
    return {
        "scope": "EXPLICIT_FALLBACK",
        "truth_ready": True,
        "exact": cached.business_state == ORDINARY_ANCHOR_UNRESOLVED,
    }


def _segment_anchor_scope(required: Sequence[Mapping[str, Any]]) -> str:
    if not required or any(row["scope"] == "UNKNOWN" for row in required):
        return "UNKNOWN"
    scopes = {str(row["scope"]) for row in required}
    if "EXPLICIT_FALLBACK" in scopes:
        return "EXPLICIT_FALLBACK"
    if "PROVEN_NO_EVIDENCE" in scopes:
        return "PROVEN_NO_EVIDENCE"
    if "MULTI_ROAD_ANCHOR" in scopes:
        return "MULTI_ROAD_ANCHOR"
    return "UNIQUE_ANCHOR"


def _selected_plan(
    stores: ArchClosureReferenceStores,
    key: tuple[str, str],
    prediction: Mapping[str, Any],
) -> ArchClosureSegmentPlan:
    selected_id = str(prediction.get("structured_plan_selected_id") or "")
    source = stores.segments[key].example
    if bool(prediction.get("structured_plan_output")) and selected_id in source.candidate_ids:
        index = source.candidate_ids.index(selected_id)
        decision = str(source.candidate_decisions[index])
        if decision == "T06_MAIN_RCSD_ATTACHED_SWSD":
            decision = "USE_RCSD"
        owned_sets = source.candidate_owned_road_ids or source.candidate_road_ids
        return ArchClosureSegmentPlan(
            key=key,
            plan_id=selected_id,
            decision=decision,
            road_ids=tuple(str(value) for value in source.candidate_road_ids[index]),
            owned_road_ids=tuple(str(value) for value in owned_sets[index]),
        )
    return ArchClosureSegmentPlan(
        key=key,
        plan_id=f"fallback:{key[0]}:{key[1]}",
        decision="ABSTAIN",
        road_ids=(),
        owned_road_ids=(),
    )


def _scoreboard(
    segments: Sequence[Mapping[str, Any]],
    junctions: Sequence[Mapping[str, Any]],
    *,
    duplicate_owner_road_count: int,
    coordination_fallback_count: int,
) -> dict[str, Any]:
    full = [row for row in segments if row["strict_full_business_evaluable"]]
    groups = [row for row in junctions if row["junction_group_evaluable"]]
    automatic = [row for row in segments if row["automatic_business_output"]]
    unsafe = [
        row
        for row in automatic
        if row["anchor_scope"] == "EXPLICIT_FALLBACK"
    ]
    unknown = [row for row in automatic if row["anchor_scope"] == "UNKNOWN"]
    unreachable = [
        row
        for row in automatic
        if not bool(row.get("structured_plan_reachable"))
    ]
    automatic_keep = [
        row for row in automatic if row.get("effective_decision") == "KEEP_SWSD"
    ]
    automatic_use = [
        row for row in automatic if row.get("effective_decision") == "USE_RCSD"
    ]
    positive_keep = [
        row
        for row in automatic_keep
        if row["anchor_scope"] not in {"UNKNOWN", "EXPLICIT_FALLBACK"}
        and row["anchor_exact"]
        and row.get("structured_plan_exact")
    ]
    positive_use = [
        row
        for row in automatic_use
        if row["anchor_scope"] in {"UNIQUE_ANCHOR", "MULTI_ROAD_ANCHOR"}
        and row["anchor_exact"]
        and row.get("structured_plan_exact")
    ]
    abstain = [row for row in segments if not row["automatic_business_output"]]
    return {
        "segment_count": len(segments),
        "segment_full_exact_numerator": sum(row["segment_full_exact"] for row in full),
        "segment_full_exact_denominator": len(full),
        "segment_full_exact": _ratio(
            sum(row["segment_full_exact"] for row in full), len(full)
        ),
        "junction_group_count": len(junctions),
        "junction_group_exact_numerator": sum(
            row["junction_group_exact"] for row in groups
        ),
        "junction_group_exact_denominator": len(groups),
        "junction_group_exact": _ratio(
            sum(row["junction_group_exact"] for row in groups), len(groups)
        ),
        "structured_plan_exact": _ratio(
            sum(bool(row.get("structured_plan_exact")) for row in segments),
            len(segments),
        ),
        "structured_plan_exact_numerator": sum(
            bool(row.get("structured_plan_exact")) for row in segments
        ),
        "structured_plan_exact_denominator": len(segments),
        "positive_keep_swsd": len(positive_keep),
        "positive_use_rcsd": len(positive_use),
        "automatic_keep_swsd_total": len(automatic_keep),
        "automatic_use_rcsd_total": len(automatic_use),
        "abstain_or_coordination_fallback": len(abstain),
        "automatic_business_coverage": _ratio(len(automatic), len(segments)),
        "unsafe_automatic": len(unsafe),
        "review_automatic": len(unknown),
        "unknown_automatic": len(unknown),
        "unreachable_automatic": len(unreachable),
        "skeleton_mutation": 0,
        "silent_fix": 0,
        "roadgraph_hard_failure": 0,
        "duplicate_owner_road_count_before_coordination": duplicate_owner_road_count,
        "coordination_fallback_segment_count": coordination_fallback_count,
        "road_10_plus": _subset_summary(
            [row for row in segments if int(row["truth_road_count"]) >= 10]
        ),
        "by_case": _group_summary(segments, "case_key"),
        "by_road_bucket": _group_summary(segments, "road_bucket"),
        "by_anchor_scope": _group_summary(segments, "anchor_scope"),
        "shared_junction": _subset_summary(
            [row for row in segments if row["shared_junction"]]
        ),
    }


def _group_summary(
    rows: Sequence[Mapping[str, Any]],
    key_name: str,
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key_name])].append(row)
    return {
        key: _subset_summary(values) for key, values in sorted(grouped.items())
    }


def _subset_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evaluable = [row for row in rows if row["strict_full_business_evaluable"]]
    return {
        "segment_count": len(rows),
        "full_evaluable_count": len(evaluable),
        "full_exact_count": sum(row["segment_full_exact"] for row in evaluable),
        "full_exact": _ratio(
            sum(row["segment_full_exact"] for row in evaluable), len(evaluable)
        ),
        "structured_plan_exact": _ratio(
            sum(bool(row.get("structured_plan_exact")) for row in rows), len(rows)
        ),
        "automatic_count": sum(row["automatic_business_output"] for row in rows),
    }


def _road_bucket(count: int) -> str:
    if count >= 10:
        return "10_PLUS"
    if count >= 5:
        return "5_TO_9"
    return "1_TO_4"


def _decode_topk(
    logits: torch.Tensor,
    mask: torch.Tensor,
    cardinality: torch.Tensor,
) -> torch.Tensor:
    valid_count = mask.sum(dim=-1)
    count = cardinality.clamp_min(0).minimum(valid_count)
    safe = logits.masked_fill(~mask, torch.finfo(logits.dtype).min)
    order = safe.argsort(dim=-1, descending=True)
    ranks = torch.arange(logits.shape[-1], device=logits.device)
    selected_by_rank = ranks.view(*([1] * count.ndim), -1) < count.unsqueeze(-1)
    result = torch.zeros_like(mask)
    result.scatter_(-1, order, selected_by_rank)
    return result & mask


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


__all__ = [
    "arch_closure_batch_prediction_rows",
    "evaluate_arch_closure_predictions",
]
