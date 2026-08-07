from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder import (
    StructuredRoadGraphDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorDecision,
    AnchorStatus,
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    ScoredPlan,
    SegmentDecision,
    SegmentPlanDecision,
)


_SOURCE = {
    "SWSD": RoadSource.SWSD,
    "RCSD": RoadSource.RCSD,
}
_ROLE = {
    "MAIN": RoadRole.MAIN,
    "INTERNAL_CONNECTOR": RoadRole.INTERNAL_CONNECTOR,
    "ATTACHED_SWSD": RoadRole.ATTACHED_SWSD,
}


def adapt_joint_plan_prediction(
    prediction: Mapping[str, Any],
    *,
    required_anchor_ids: Sequence[str],
    pair_node_ids: Sequence[str] = (),
    release_top_k: int = 1,
) -> tuple[tuple[ScoredPlan, ...], tuple[str, ...]]:
    """Convert model top-k outputs into complete, ownership-safe plans."""
    if release_top_k < 1:
        raise ValueError("ordinary joint plan release_top_k is invalid")
    if not bool(prediction.get("accepted")):
        return (), ("MODEL_RELEASE_NOT_READY",)
    segment_id = str(prediction["segment_id"])
    plans = []
    failures = []
    alternatives = list(
        prediction.get("top_plan_candidates") or ()
    )[:release_top_k]
    for alternative in alternatives:
        decision_name = str(alternative.get("decision") or "")
        if decision_name == "ABSTAIN":
            continue
        try:
            plan = _plan_from_alternative(
                segment_id=segment_id,
                alternative=alternative,
                required_anchor_ids=required_anchor_ids,
                pair_node_ids=pair_node_ids,
            )
        except ValueError as exc:
            failures.append(
                f"{alternative.get('proposal_id')}:"
                f"{type(exc).__name__}:{exc}"
            )
            continue
        plans.append(
            ScoredPlan(
                plan=plan,
                score=float(alternative["probability"]),
            )
        )
    plans.sort(
        key=lambda row: (row.score, row.plan.plan_id),
        reverse=True,
    )
    if not plans and not failures:
        failures.append("NO_NON_ABSTAIN_TOP_PLAN")
    return tuple(plans), tuple(failures)


def multi_plan_conflict_components(
    candidates: Mapping[
        tuple[str, str],
        Sequence[ScoredPlan],
    ],
) -> list[tuple[tuple[str, str], ...]]:
    """Connect only Case-local Segments sharing a proposed owned Road."""
    parent = {key: key for key in candidates}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(
                left_root,
                right_root,
            )

    owners: dict[
        tuple[str, str],
        list[tuple[str, str]],
    ] = defaultdict(list)
    for key, plans in candidates.items():
        owned_keys = {
            road.ownership_key
            for scored in plans
            for road in scored.plan.roads
            if road.owner_segment_id
        }
        for road_id in owned_keys:
            owners[(key[0], road_id)].append(key)
    for values in owners.values():
        for value in values[1:]:
            union(values[0], value)
    groups: dict[
        tuple[str, str],
        list[tuple[str, str]],
    ] = defaultdict(list)
    for key in candidates:
        groups[find(key)].append(key)
    return [
        tuple(sorted(values))
        for _, values in sorted(groups.items())
    ]


def decode_joint_plan_candidates(
    candidates: Mapping[
        tuple[str, str],
        Sequence[ScoredPlan],
    ],
    *,
    max_search_states: int = 50_000,
) -> tuple[
    dict[tuple[str, str], SegmentPlanDecision],
    tuple[Mapping[str, Any], ...],
]:
    """Run the existing finite-scope decoder per direct conflict component."""
    decoder = StructuredRoadGraphDecoder(
        max_search_states=max_search_states
    )
    decoded = {}
    component_rows = []
    for component_id, keys in enumerate(
        multi_plan_conflict_components(candidates)
    ):
        case_keys = {case_key for case_key, _ in keys}
        if len(case_keys) != 1:
            raise ValueError("ordinary joint plan component crosses Cases")
        case_key = next(iter(case_keys))
        by_segment = {
            segment_id: tuple(candidates[(case_key, segment_id)])
            for _, segment_id in keys
        }
        anchors = {
            anchor_id: AnchorDecision(
                anchor_id=anchor_id,
                status=AnchorStatus.SUCCESS,
                selected_candidate_id=f"locked-oof:{anchor_id}",
            )
            for plans in by_segment.values()
            for scored in plans
            for anchor_id in scored.plan.required_anchor_ids
        }
        result = decoder.decode(
            ordinary_candidates=by_segment,
            advance_right_candidates={},
            anchor_decisions=anchors,
        )
        component_rows.append(
            {
                "component_id": component_id,
                "case_key": case_key,
                "segment_ids": [
                    segment_id for _, segment_id in keys
                ],
                "segment_count": len(keys),
                "candidate_count": sum(
                    len(values) for values in by_segment.values()
                ),
                "selected_count": sum(
                    decision.automatic
                    for decision in result.ordinary
                ),
                "fallback_count": len(result.fallback_segment_ids),
                "owned_road_ids": list(
                    result.used_ownership_keys
                ),
            }
        )
        for decision in result.ordinary:
            decoded[(case_key, decision.segment_id)] = decision
    return decoded, tuple(component_rows)


def _plan_from_alternative(
    *,
    segment_id: str,
    alternative: Mapping[str, Any],
    required_anchor_ids: Sequence[str],
    pair_node_ids: Sequence[str],
) -> PlanCandidate:
    assignments = list(
        alternative.get("road_business_assignments") or ()
    )
    road_ids = [str(value) for value in alternative.get("road_ids") or ()]
    by_road = {
        str(row["road_id"]): row for row in assignments
    }
    if not road_ids or set(by_road) != set(road_ids):
        raise ValueError("complete Road business assignments are missing")
    roads = []
    for road_id in road_ids:
        row = by_road[road_id]
        if str(row.get("ownership")) != "OWNER_CURRENT_SEGMENT":
            raise ValueError(
                f"selected Road {road_id} lacks current-Segment ownership"
            )
        source_name = str(row.get("source") or "")
        role_name = str(row.get("business_role") or "")
        if source_name not in _SOURCE:
            raise ValueError(f"Road {road_id} source is invalid")
        if role_name not in _ROLE:
            raise ValueError(
                f"Road {road_id} lacks a formal selected role"
            )
        roads.append(
            RoadUse(
                source_kind=_SOURCE[source_name],
                source_road_id=road_id,
                role=_ROLE[role_name],
                owner_segment_id=segment_id,
                direction=0,
            )
        )
    decision = _formal_decision(
        str(alternative.get("decision") or ""),
        roads,
    )
    source_access = _unique_incident_road(
        assignments,
        str(pair_node_ids[0]) if pair_node_ids else "",
    )
    target_access = _unique_incident_road(
        assignments,
        str(pair_node_ids[-1]) if pair_node_ids else "",
    )
    plan = PlanCandidate(
        plan_id=str(alternative["proposal_id"]),
        segment_id=segment_id,
        decision=decision,
        roads=tuple(roads),
        source_access_road_id=source_access,
        target_access_road_id=target_access,
        required_anchor_ids=tuple(
            str(value) for value in required_anchor_ids
        ),
        hard_valid=True,
    )
    plan.validate()
    return plan


def _formal_decision(
    raw_decision: str,
    roads: Sequence[RoadUse],
) -> SegmentDecision:
    if raw_decision == "KEEP_SWSD":
        return SegmentDecision.KEEP_SWSD
    if raw_decision != "USE_RCSD":
        raise ValueError(f"unsupported decision {raw_decision}")
    swsd = [road for road in roads if road.source_kind is RoadSource.SWSD]
    if not swsd:
        return SegmentDecision.USE_RCSD
    if all(road.role is RoadRole.ATTACHED_SWSD for road in swsd):
        return SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD
    raise ValueError("USE plan contains non-attached SWSD Road")


def _unique_incident_road(
    assignments: Sequence[Mapping[str, Any]],
    node_id: str,
) -> str:
    if not node_id:
        return ""
    roads = {
        str(row["road_id"])
        for row in assignments
        if node_id
        in {
            str(row.get("start_node_id") or ""),
            str(row.get("end_node_id") or ""),
        }
    }
    return next(iter(roads)) if len(roads) == 1 else ""


__all__ = [
    "adapt_joint_plan_prediction",
    "decode_joint_plan_candidates",
    "multi_plan_conflict_components",
]
