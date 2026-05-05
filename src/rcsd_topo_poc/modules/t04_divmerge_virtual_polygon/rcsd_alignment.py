from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Literal, TypeAlias

from ._runtime_types_io import BRANCH_MATCH_TOLERANCE_DEG, ParsedNode, ParsedRoad

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


# Keep these values aligned with the T04 module interface contract.
RCSD_ALIGNMENT_SEMANTIC_JUNCTION = "rcsd_semantic_junction"
RCSD_ALIGNMENT_JUNCTION_PARTIAL = "rcsd_junction_partial_alignment"
RCSD_ALIGNMENT_ROAD_ONLY = "rcsdroad_only_alignment"
RCSD_ALIGNMENT_NONE = "no_rcsd_alignment"
RCSD_ALIGNMENT_AMBIGUOUS = "ambiguous_rcsd_alignment"

RCSDAlignmentType: TypeAlias = Literal[
    "rcsd_semantic_junction",
    "rcsd_junction_partial_alignment",
    "rcsdroad_only_alignment",
    "no_rcsd_alignment",
    "ambiguous_rcsd_alignment",
]

RCSD_ALIGNMENT_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_AMBIGUOUS,
)

RCSD_ALIGNMENT_POSITIVE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
)
RCSD_ALIGNMENT_FALLBACK_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_NO_POSITIVE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_NONE,
)
RCSD_ALIGNMENT_BLOCKING_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_AMBIGUOUS,
)
RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_SECTION_REFERENCE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
)

RCSD_ALIGNMENT_SCOPE_EVENT_UNIT = "event_unit"
RCSD_ALIGNMENT_SCOPE_CASE = "case"

RCSDAlignmentScope: TypeAlias = Literal["event_unit", "case"]

RCSD_ALIGNMENT_SCOPES: tuple[RCSDAlignmentScope, ...] = (
    RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
    RCSD_ALIGNMENT_SCOPE_CASE,
)

RCSD_CONSISTENCY_RESULT_VALUES: tuple[str, ...] = (
    "positive_rcsd_strong_consistent",
    "positive_rcsd_partial_consistent",
    "positive_rcsd_direction_only_consistent",
    "positive_rcsd_inconsistent",
    "road_surface_fork_without_bound_target_rcsd",
    "missing_positive_rcsd",
    "none",
)


class ConsistencyVerdict(StrEnum):
    STRONG_CONSISTENT = "strong_consistent"
    PARTIAL_CONSISTENT = "partial_consistent"
    DIRECTION_ONLY_CONSISTENT = "direction_only_consistent"
    NOT_APPLICABLE = "not_applicable"
    INCONSISTENT = "inconsistent"
    BLOCKED = "blocked"

    def __str__(self) -> str:
        return self.value


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_ids(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def validate_rcsd_consistency_result(value: Any) -> str:
    text = _clean_text(value) or "none"
    if text not in RCSD_CONSISTENCY_RESULT_VALUES:
        raise ValueError(f"rcsd_consistency_result outside frozen value domain: {text}")
    return text


def compute_consistency_verdict(
    *,
    rcsd_alignment_type: Any,
    positive_rcsd_consistency_level: Any,
    axis_polarity_inverted: bool,
    rcsdroad_only_chain: Any = None,
) -> ConsistencyVerdict:
    alignment_type = normalize_rcsd_alignment_type(rcsd_alignment_type)
    consistency_level = _clean_text(positive_rcsd_consistency_level)
    if alignment_type == RCSD_ALIGNMENT_AMBIGUOUS:
        return ConsistencyVerdict.BLOCKED
    if alignment_type == RCSD_ALIGNMENT_NONE:
        return ConsistencyVerdict.NOT_APPLICABLE
    if axis_polarity_inverted:
        return ConsistencyVerdict.INCONSISTENT
    if alignment_type == RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
        if consistency_level == "A":
            return ConsistencyVerdict.STRONG_CONSISTENT
        if consistency_level == "B":
            return ConsistencyVerdict.PARTIAL_CONSISTENT
        return ConsistencyVerdict.INCONSISTENT
    if alignment_type == RCSD_ALIGNMENT_JUNCTION_PARTIAL:
        return ConsistencyVerdict.PARTIAL_CONSISTENT
    if alignment_type == RCSD_ALIGNMENT_ROAD_ONLY:
        return (
            ConsistencyVerdict.DIRECTION_ONLY_CONSISTENT
            if bool(getattr(rcsdroad_only_chain, "swsd_direction_consistent", False))
            else ConsistencyVerdict.INCONSISTENT
        )
    return ConsistencyVerdict.INCONSISTENT


def normalize_rcsd_alignment_type(
    value: Any,
    *,
    default: RCSDAlignmentType = RCSD_ALIGNMENT_NONE,
) -> RCSDAlignmentType:
    text = _clean_text(value)
    if text in RCSD_ALIGNMENT_TYPES:
        return text  # type: ignore[return-value]
    return default


def rcsd_match_type_for_alignment(rcsd_alignment_type: Any) -> str:
    alignment = normalize_rcsd_alignment_type(rcsd_alignment_type)
    if alignment == RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
        return "rcsd_junction"
    if alignment in RCSD_ALIGNMENT_FALLBACK_TYPES:
        return "rcsdroad_fallback"
    return "none"


def rcsd_alignment_type_from_selection(
    *,
    positive_rcsd_present: bool,
    required_rcsd_node: Any = None,
    selected_rcsdroad_ids: Iterable[Any] | None = None,
    fallback_rcsdroad_ids: Iterable[Any] | None = None,
    local_rcsd_unit_kind: Any = None,
    positive_rcsd_support_level: Any = None,
    positive_rcsd_consistency_level: Any = None,
    rcsd_decision_reason: Any = None,
    rcsd_selection_mode: Any = None,
) -> RCSDAlignmentType:
    reason = _clean_text(rcsd_decision_reason)
    mode = _clean_text(rcsd_selection_mode)
    support_level = _clean_text(positive_rcsd_support_level)
    consistency_level = _clean_text(positive_rcsd_consistency_level)
    unit_kind = _clean_text(local_rcsd_unit_kind)
    selected_roads = _clean_ids(selected_rcsdroad_ids)
    fallback_roads = _clean_ids(fallback_rcsdroad_ids)
    required_node = _clean_text(required_rcsd_node)
    decision_text = f"{reason}|{mode}".lower()

    if "ambiguous" in decision_text:
        return RCSD_ALIGNMENT_AMBIGUOUS
    if positive_rcsd_present:
        if required_node:
            if "junction_partial" in decision_text or "partial_alignment" in decision_text:
                return RCSD_ALIGNMENT_JUNCTION_PARTIAL
            if len(selected_roads) >= 3:
                return RCSD_ALIGNMENT_SEMANTIC_JUNCTION
            if (
                "partial" in decision_text
                or support_level == "secondary_support"
                or consistency_level == "B"
            ):
                return RCSD_ALIGNMENT_JUNCTION_PARTIAL
            return RCSD_ALIGNMENT_SEMANTIC_JUNCTION
        if selected_roads or unit_kind == "road_only":
            return RCSD_ALIGNMENT_ROAD_ONLY
    if fallback_roads:
        return RCSD_ALIGNMENT_ROAD_ONLY
    if reason in {"positive_rcsd_absent_after_local_units", "local_rcsd_unit_not_constructed"}:
        return RCSD_ALIGNMENT_NONE
    return RCSD_ALIGNMENT_NONE


@dataclass(frozen=True)
class RCSDAlignmentSelection:
    selected_rcsdnode_ids: tuple[str, ...] = ()
    selected_rcsdroad_ids: tuple[str, ...] = ()
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    selected_rcsd_group_id: str | None = None
    required_rcsd_node: str | None = None


@dataclass(frozen=True)
class RCSDAlignmentDecision:
    scope: RCSDAlignmentScope
    scope_id: str
    rcsd_alignment_type: RCSDAlignmentType
    selection: RCSDAlignmentSelection = field(default_factory=RCSDAlignmentSelection)
    decision_reason: str = ""
    candidate_ids: tuple[str, ...] = ()
    audit_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RCSDAlignmentResult:
    scope: RCSDAlignmentScope
    scope_id: str
    rcsd_alignment_type: RCSDAlignmentType
    positive_rcsdroad_ids: tuple[str, ...] = ()
    positive_rcsdnode_ids: tuple[str, ...] = ()
    unrelated_rcsdroad_ids: tuple[str, ...] = ()
    unrelated_rcsdnode_ids: tuple[str, ...] = ()
    candidate_rcsdroad_ids: tuple[str, ...] = ()
    candidate_rcsdnode_ids: tuple[str, ...] = ()
    candidate_alignment_ids: tuple[str, ...] = ()
    ambiguity_reasons: tuple[str, ...] = ()
    conflict_reasons: tuple[str, ...] = ()
    decision_reason: str = ""
    source: str = "step4_frozen_result"

    def to_doc(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "rcsd_alignment_type": self.rcsd_alignment_type,
            "positive_rcsdroad_ids": list(self.positive_rcsdroad_ids),
            "positive_rcsdnode_ids": list(self.positive_rcsdnode_ids),
            "unrelated_rcsdroad_ids": list(self.unrelated_rcsdroad_ids),
            "unrelated_rcsdnode_ids": list(self.unrelated_rcsdnode_ids),
            "candidate_rcsdroad_ids": list(self.candidate_rcsdroad_ids),
            "candidate_rcsdnode_ids": list(self.candidate_rcsdnode_ids),
            "candidate_alignment_ids": list(self.candidate_alignment_ids),
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "conflict_reasons": list(self.conflict_reasons),
            "decision_reason": self.decision_reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class RCSDSemanticArm:
    arm_id: str
    direction: str
    angle_deg: float
    first_rcsdroad_ids: tuple[str, ...]
    inter_junction_connector_rcsdroad_ids: tuple[str, ...]
    terminal_rcsdnode_id: str
    terminal_kind: str
    neighbor_rcsd_junction_id: str | None

    def to_doc(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "direction": self.direction,
            "angle_deg": self.angle_deg,
            "first_rcsdroad_ids": list(self.first_rcsdroad_ids),
            "inter_junction_connector_rcsdroad_ids": list(self.inter_junction_connector_rcsdroad_ids),
            "terminal_rcsdnode_id": self.terminal_rcsdnode_id,
            "terminal_kind": self.terminal_kind,
            "neighbor_rcsd_junction_id": self.neighbor_rcsd_junction_id,
        }


@dataclass(frozen=True)
class RCSDSemanticJunction:
    junction_id: str
    member_rcsdnode_ids: tuple[str, ...]
    intra_junction_rcsdroad_ids: tuple[str, ...]
    semantic_arms: tuple[RCSDSemanticArm, ...]
    paired_swsd_arm_mapping: dict[str, str | None]
    alignment_partial_missing_swsd_arm_ids: tuple[str, ...]
    pairing_ambiguous_arm_ids: tuple[str, ...] = ()
    source: str = "step4_rcsd_alignment"

    def to_doc(self) -> dict[str, Any]:
        return {
            "junction_id": self.junction_id,
            "member_rcsdnode_ids": list(self.member_rcsdnode_ids),
            "intra_junction_rcsdroad_ids": list(self.intra_junction_rcsdroad_ids),
            "semantic_arms": [arm.to_doc() for arm in self.semantic_arms],
            "paired_swsd_arm_mapping": dict(self.paired_swsd_arm_mapping),
            "alignment_partial_missing_swsd_arm_ids": list(self.alignment_partial_missing_swsd_arm_ids),
            "pairing_ambiguous_arm_ids": list(self.pairing_ambiguous_arm_ids),
            "source": self.source,
        }


@dataclass(frozen=True)
class RCSDRoadOnlyChain:
    chain_road_ids: tuple[str, ...]
    chain_endpoint_node_ids: tuple[str, str]
    chain_endpoint_kinds: tuple[str, str]
    closure_status: str
    swsd_direction_consistent: bool
    swsd_direction_evidence: dict[str, Any]
    selection_uniqueness_proof: dict[str, Any]
    source: str = "step4_rcsdroad_only_alignment"

    def to_doc(self) -> dict[str, Any]:
        return {
            "chain_road_ids": list(self.chain_road_ids),
            "chain_endpoint_node_ids": list(self.chain_endpoint_node_ids),
            "chain_endpoint_kinds": list(self.chain_endpoint_kinds),
            "closure_status": self.closure_status,
            "swsd_direction_consistent": self.swsd_direction_consistent,
            "swsd_direction_evidence": dict(self.swsd_direction_evidence),
            "selection_uniqueness_proof": dict(self.selection_uniqueness_proof),
            "source": self.source,
        }


def _semantic_group_id(node: ParsedNode) -> str:
    mainnodeid = _clean_text(getattr(node, "mainnodeid", None))
    if mainnodeid and mainnodeid != "0":
        return mainnodeid
    return _clean_text(getattr(node, "node_id", None))


def _semantic_group_id_for_node_id(node_id: str, *, node_by_id: dict[str, ParsedNode]) -> str:
    normalized_node_id = _clean_text(node_id)
    node = node_by_id.get(normalized_node_id)
    if node is not None:
        return _semantic_group_id(node)
    return normalized_node_id


def _road_endpoint_ids(road: ParsedRoad) -> tuple[str, str]:
    return (
        _clean_text(getattr(road, "snodeid", None)),
        _clean_text(getattr(road, "enodeid", None)),
    )


def _angle_gap_deg(left: float, right: float) -> float:
    return abs((float(left) - float(right) + 180.0) % 360.0 - 180.0)


def _road_angle_from_member_node(road: ParsedRoad, member_node_id: str) -> float:
    coords = list(getattr(getattr(road, "geometry", None), "coords", []) or [])
    if len(coords) < 2:
        return 0.0
    snodeid, enodeid = _road_endpoint_ids(road)
    if member_node_id == enodeid:
        start_x, start_y = coords[-1][:2]
        end_x, end_y = coords[0][:2]
    else:
        start_x, start_y = coords[0][:2]
        end_x, end_y = coords[-1][:2]
    return float(math.degrees(math.atan2(float(end_y) - float(start_y), float(end_x) - float(start_x))) % 360.0)


def _road_angle_toward_node(road: ParsedRoad, target_node_id: str) -> float:
    return float((_road_angle_from_member_node(road, target_node_id) + 180.0) % 360.0)


def _other_endpoint_id(road: ParsedRoad, node_id: str) -> str:
    snodeid, enodeid = _road_endpoint_ids(road)
    return enodeid if snodeid == node_id else snodeid


def _direction_for_rcsdroad(road_id: str, audit: dict[str, Any]) -> str:
    for assignment in audit.get("selected_unit_role_assignments") or ():
        if (
            not isinstance(assignment, dict)
            or _clean_text(assignment.get("road_id")) != road_id
        ):
            continue
        role = _clean_text(assignment.get("role"))
        if role == "entering":
            return "incoming"
        if role == "exiting":
            return "outgoing"
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        if road_id in {str(item) for item in aggregate.get("entering_road_ids") or ()}:
            return "incoming"
        if road_id in {str(item) for item in aggregate.get("exiting_road_ids") or ()}:
            return "outgoing"
        for assignment in aggregate.get("role_assignments") or ():
            if not isinstance(assignment, dict) or _clean_text(assignment.get("road_id")) != road_id:
                continue
            role = _clean_text(assignment.get("role"))
            if role == "entering":
                return "incoming"
            if role == "exiting":
                return "outgoing"
    return "unknown"


def _selected_aggregate(unit_result: Any, audit: dict[str, Any]) -> dict[str, Any] | None:
    selected_ids = {
        _clean_text(getattr(unit_result, "aggregated_rcsd_unit_id", None)),
        *_clean_ids(getattr(unit_result, "aggregated_rcsd_unit_ids", ())),
    }
    aggregates = [item for item in audit.get("aggregated_rcsd_units") or () if isinstance(item, dict)]
    for aggregate in aggregates:
        if _clean_text(aggregate.get("unit_id")) in selected_ids:
            return aggregate
    return aggregates[0] if aggregates else None


def _member_rcsdnode_ids(unit_result: Any, local_nodes: tuple[ParsedNode, ...]) -> tuple[str, ...]:
    audit = dict(getattr(unit_result, "positive_rcsd_audit", {}) or {})
    aggregate = _selected_aggregate(unit_result, audit)
    published_node_ids = set(_clean_ids(audit.get("published_rcsdnode_ids")))
    if published_node_ids:
        seed_node_ids = set(published_node_ids)
    else:
        seed_node_ids = set(_clean_ids(getattr(unit_result, "selected_rcsdnode_ids", ())))
    for key in ("required_rcsd_node", "primary_main_rc_node_id"):
        text = _clean_text(getattr(unit_result, key, None))
        if text:
            seed_node_ids.add(text)
    if aggregate is not None:
        if not published_node_ids and not _clean_ids(audit.get("published_member_unit_ids")):
            seed_node_ids.update(_clean_ids(aggregate.get("node_ids")))
        seed_node_ids.update(_clean_ids([aggregate.get("required_node_id"), aggregate.get("primary_node_id")]))
    node_by_id = {_clean_text(node.node_id): node for node in local_nodes}
    seed_group_ids = {
        _semantic_group_id(node_by_id[node_id])
        for node_id in seed_node_ids
        if node_id in node_by_id
    }
    member_ids = {
        _clean_text(node.node_id)
        for node in local_nodes
        if _semantic_group_id(node) in seed_group_ids
    }
    member_ids.update(seed_node_ids)
    return tuple(sorted(node_id for node_id in member_ids if node_id))


def _collect_intra_rcsdroad_ids(roads: tuple[ParsedRoad, ...], member_node_ids: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            _clean_text(road.road_id)
            for road in roads
            if (endpoints := _road_endpoint_ids(road))
            and endpoints[0] in member_node_ids
            and endpoints[1] in member_node_ids
            and _clean_text(road.road_id)
        )
    )


def _semantic_boundary_degree_by_node(
    roads: tuple[ParsedRoad, ...],
    *,
    node_by_id: dict[str, ParsedNode],
) -> dict[str, int]:
    node_ids = set(node_by_id)
    boundary_road_ids_by_group: dict[str, set[str]] = {}
    for road in roads:
        road_id = _clean_text(road.road_id)
        if not road_id:
            continue
        snodeid, enodeid = _road_endpoint_ids(road)
        if snodeid:
            node_ids.add(snodeid)
        if enodeid:
            node_ids.add(enodeid)
        source_group_id = _semantic_group_id_for_node_id(snodeid, node_by_id=node_by_id)
        target_group_id = _semantic_group_id_for_node_id(enodeid, node_by_id=node_by_id)
        if not source_group_id or not target_group_id or source_group_id == target_group_id:
            continue
        boundary_road_ids_by_group.setdefault(source_group_id, set()).add(road_id)
        boundary_road_ids_by_group.setdefault(target_group_id, set()).add(road_id)
    degree_by_node_id: dict[str, int] = {}
    for node_id in node_ids:
        group_id = _semantic_group_id_for_node_id(node_id, node_by_id=node_by_id)
        degree_by_node_id[node_id] = len(boundary_road_ids_by_group.get(group_id, set()))
    return degree_by_node_id


def _walk_rcsd_connector(
    seed_road: ParsedRoad,
    *,
    roads_by_id: dict[str, ParsedRoad],
    roads_by_node: dict[str, list[ParsedRoad]],
    local_node_ids: set[str],
    member_node_ids: set[str],
    node_by_id: dict[str, ParsedNode],
    semantic_degree_by_node: dict[str, int],
) -> tuple[tuple[str, ...], str, str, str | None, str]:
    seed_road_id = _clean_text(seed_road.road_id)
    snodeid, enodeid = _road_endpoint_ids(seed_road)
    if snodeid in member_node_ids and enodeid not in member_node_ids:
        member_node_id, current_node_id = snodeid, enodeid
    elif enodeid in member_node_ids and snodeid not in member_node_ids:
        member_node_id, current_node_id = enodeid, snodeid
    else:
        return (tuple([seed_road_id] if seed_road_id else ()), enodeid or snodeid, "unresolved", None, snodeid)

    connector_ids: list[str] = [seed_road_id] if seed_road_id else []
    previous_node_id = member_node_id
    previous_road_id = seed_road_id
    visited_road_ids = {seed_road_id}
    while True:
        if current_node_id not in local_node_ids:
            return tuple(connector_ids), current_node_id, "patch_boundary", None, member_node_id
        incident_roads = roads_by_node.get(current_node_id, [])
        degree = int(
            semantic_degree_by_node.get(
                current_node_id,
                len({_clean_text(road.road_id) for road in incident_roads if _clean_text(road.road_id)}),
            )
        )
        if degree <= 1:
            return tuple(connector_ids), current_node_id, "dead_end", None, member_node_id
        if degree >= 3:
            neighbor_id = _semantic_group_id_for_node_id(current_node_id, node_by_id=node_by_id)
            return tuple(connector_ids), current_node_id, "semantic_neighbor", neighbor_id, member_node_id
        candidates: list[ParsedRoad] = []
        for road in incident_roads:
            road_id = _clean_text(road.road_id)
            if not road_id or road_id == previous_road_id or road_id in visited_road_ids:
                continue
            next_snodeid, next_enodeid = _road_endpoint_ids(road)
            next_node_id = next_enodeid if next_snodeid == current_node_id else next_snodeid
            if next_node_id == previous_node_id or next_node_id in member_node_ids:
                continue
            candidates.append(road)
        if len(candidates) != 1:
            return tuple(connector_ids), current_node_id, "semantic_neighbor", None, member_node_id
        next_road = candidates[0]
        next_road_id = _clean_text(next_road.road_id)
        connector_ids.append(next_road_id)
        visited_road_ids.add(next_road_id)
        next_snodeid, next_enodeid = _road_endpoint_ids(next_road)
        previous_node_id = current_node_id
        previous_road_id = next_road_id
        current_node_id = next_enodeid if next_snodeid == previous_node_id else next_snodeid


def _unique_ordered_ids(*sources: Iterable[Any] | None) -> tuple[str, ...]:
    result: list[str] = []
    for source in sources:
        for item in _clean_ids(source):
            if item not in result:
                result.append(item)
    return tuple(result)


def _chain_components(
    road_ids: tuple[str, ...],
    roads_by_id: dict[str, ParsedRoad],
) -> tuple[tuple[str, ...], ...]:
    remaining = {road_id for road_id in road_ids if road_id in roads_by_id}
    components: list[tuple[str, ...]] = []
    while remaining:
        seed = sorted(remaining)[0]
        stack = [seed]
        component: list[str] = []
        remaining.remove(seed)
        while stack:
            road_id = stack.pop()
            component.append(road_id)
            endpoints = set(_road_endpoint_ids(roads_by_id[road_id]))
            for other_id in sorted(tuple(remaining)):
                if endpoints & set(_road_endpoint_ids(roads_by_id[other_id])):
                    remaining.remove(other_id)
                    stack.append(other_id)
        components.append(tuple(road_id for road_id in road_ids if road_id in component))
    return tuple(components)


def _order_chain_road_ids(
    road_ids: tuple[str, ...],
    roads_by_id: dict[str, ParsedRoad],
) -> tuple[tuple[str, ...], str, str, tuple[str, ...]]:
    valid_road_ids = tuple(road_id for road_id in road_ids if road_id in roads_by_id)
    if not valid_road_ids:
        return (), "", "", ("no_chain_candidate_road",)
    node_to_road_ids: dict[str, list[str]] = {}
    for road_id in valid_road_ids:
        for node_id in _road_endpoint_ids(roads_by_id[road_id]):
            if node_id:
                node_to_road_ids.setdefault(node_id, []).append(road_id)
    endpoint_nodes = sorted(node_id for node_id, ids in node_to_road_ids.items() if len(set(ids)) <= 1)
    start_node_id = endpoint_nodes[0] if endpoint_nodes else _road_endpoint_ids(roads_by_id[valid_road_ids[0]])[0]
    current_node_id = start_node_id
    previous_road_id = ""
    ordered: list[str] = []
    unresolved_reasons: list[str] = []
    while True:
        candidate_ids = [
            road_id
            for road_id in node_to_road_ids.get(current_node_id, [])
            if road_id != previous_road_id and road_id not in ordered
        ]
        if not candidate_ids:
            break
        if len(candidate_ids) > 1:
            unresolved_reasons.append("branching_chain_candidate")
            break
        road_id = candidate_ids[0]
        ordered.append(road_id)
        previous_road_id = road_id
        current_node_id = _other_endpoint_id(roads_by_id[road_id], current_node_id)
    for road_id in valid_road_ids:
        if road_id not in ordered:
            ordered.append(road_id)
            unresolved_reasons.append("disconnected_chain_candidate")
    end_node_id = current_node_id
    if ordered:
        first_snodeid, first_enodeid = _road_endpoint_ids(roads_by_id[ordered[0]])
        if start_node_id not in {first_snodeid, first_enodeid}:
            start_node_id = first_snodeid
        last_snodeid, last_enodeid = _road_endpoint_ids(roads_by_id[ordered[-1]])
        if end_node_id not in {last_snodeid, last_enodeid}:
            end_node_id = last_enodeid
    if len(set(ordered)) != len(valid_road_ids):
        unresolved_reasons.append("duplicate_chain_visit")
    return tuple(ordered), start_node_id, end_node_id, tuple(dict.fromkeys(unresolved_reasons))


def _rcsd_endpoint_kind(
    node_id: str,
    *,
    local_node_ids: set[str],
    roads_by_node: dict[str, list[ParsedRoad]],
    semantic_degree_by_node: dict[str, int],
) -> str:
    if node_id not in local_node_ids:
        return "rcsd_patch_boundary"
    degree = int(
        semantic_degree_by_node.get(
            node_id,
            len({_clean_text(road.road_id) for road in roads_by_node.get(node_id, ()) if _clean_text(road.road_id)}),
        )
    )
    if degree >= 3:
        return "rcsd_semantic_junction_member"
    if degree <= 1:
        return "rcsd_dead_end"
    return "rcsd_patch_boundary"


def _closure_status(endpoint_kinds: tuple[str, str], unresolved_reasons: tuple[str, ...]) -> str:
    if unresolved_reasons:
        return "unresolved"
    if endpoint_kinds == ("rcsd_semantic_junction_member", "rcsd_semantic_junction_member"):
        return "closed_between_two_rcsd_junctions"
    if "rcsd_dead_end" in endpoint_kinds:
        return "open_dead_end"
    if "rcsd_patch_boundary" in endpoint_kinds:
        return "open_patch_boundary"
    return "unresolved"


def _direction_evidence_for_chain(
    *,
    chain_road_ids: tuple[str, ...],
    start_node_id: str,
    end_node_id: str,
    roads_by_id: dict[str, ParsedRoad],
    swsd_semantic_junction: Any,
) -> tuple[bool, dict[str, Any]]:
    if not chain_road_ids:
        return False, {
            "chain_head_angle_deg": None,
            "chain_tail_angle_deg": None,
            "matched_swsd_arm_id": None,
            "angle_gap_deg": None,
            "consistency_decision_reason": "no_chain_road",
        }
    head_angle = _road_angle_from_member_node(roads_by_id[chain_road_ids[0]], start_node_id)
    tail_angle = _road_angle_toward_node(roads_by_id[chain_road_ids[-1]], end_node_id)
    best: tuple[float, str] | None = None
    for swsd_arm in tuple(getattr(swsd_semantic_junction, "semantic_arms", ()) or ()):
        arm_id = _clean_text(getattr(swsd_arm, "arm_id", ""))
        if not arm_id:
            continue
        arm_angle = float(getattr(swsd_arm, "angle_deg", 0.0))
        gap = min(_angle_gap_deg(head_angle, arm_angle), _angle_gap_deg(tail_angle, arm_angle))
        if best is None or gap < best[0]:
            best = (gap, arm_id)
    if best is None:
        return False, {
            "chain_head_angle_deg": head_angle,
            "chain_tail_angle_deg": tail_angle,
            "matched_swsd_arm_id": None,
            "angle_gap_deg": None,
            "consistency_decision_reason": "no_swsd_semantic_arm",
        }
    consistent = best[0] <= BRANCH_MATCH_TOLERANCE_DEG
    return consistent, {
        "chain_head_angle_deg": head_angle,
        "chain_tail_angle_deg": tail_angle,
        "matched_swsd_arm_id": best[1],
        "angle_gap_deg": best[0],
        "consistency_decision_reason": (
            "within_branch_match_tolerance"
            if consistent
            else "exceeds_branch_match_tolerance"
        ),
    }


def build_rcsdroad_only_chain(
    *,
    unit_result: Any,
    swsd_semantic_junction: Any,
    rcsd_alignment_result: RCSDAlignmentResult,
) -> RCSDRoadOnlyChain | None:
    alignment_type = normalize_rcsd_alignment_type(rcsd_alignment_result.rcsd_alignment_type)
    if alignment_type != RCSD_ALIGNMENT_ROAD_ONLY:
        return None
    local_context = unit_result.unit_context.local_context
    local_roads = tuple(getattr(local_context, "local_rcsd_roads", ()) or ())
    local_nodes = tuple(getattr(local_context, "local_rcsd_nodes", ()) or ())
    roads_by_id = {_clean_text(road.road_id): road for road in local_roads if _clean_text(road.road_id)}
    candidate_road_ids = _unique_ordered_ids(
        rcsd_alignment_result.positive_rcsdroad_ids,
        getattr(unit_result, "first_hit_rcsdroad_ids", ()),
        getattr(unit_result, "selected_rcsdroad_ids", ()),
    )
    candidate_road_ids = tuple(road_id for road_id in candidate_road_ids if road_id in roads_by_id)
    if not candidate_road_ids:
        return None
    ordered_road_ids, start_node_id, end_node_id, unresolved_reasons = _order_chain_road_ids(
        candidate_road_ids,
        roads_by_id,
    )
    roads_by_node: dict[str, list[ParsedRoad]] = {}
    for road in local_roads:
        for node_id in _road_endpoint_ids(road):
            if node_id:
                roads_by_node.setdefault(node_id, []).append(road)
    local_node_ids = {_clean_text(node.node_id) for node in local_nodes if _clean_text(node.node_id)}
    node_by_id = {_clean_text(node.node_id): node for node in local_nodes if _clean_text(node.node_id)}
    semantic_degree_by_node = _semantic_boundary_degree_by_node(local_roads, node_by_id=node_by_id)
    endpoint_kinds = (
        _rcsd_endpoint_kind(
            start_node_id,
            local_node_ids=local_node_ids,
            roads_by_node=roads_by_node,
            semantic_degree_by_node=semantic_degree_by_node,
        ),
        _rcsd_endpoint_kind(
            end_node_id,
            local_node_ids=local_node_ids,
            roads_by_node=roads_by_node,
            semantic_degree_by_node=semantic_degree_by_node,
        ),
    )
    direction_consistent, direction_evidence = _direction_evidence_for_chain(
        chain_road_ids=ordered_road_ids,
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        roads_by_id=roads_by_id,
        swsd_semantic_junction=swsd_semantic_junction,
    )
    components = _chain_components(candidate_road_ids, roads_by_id)
    return RCSDRoadOnlyChain(
        chain_road_ids=ordered_road_ids,
        chain_endpoint_node_ids=(start_node_id, end_node_id),
        chain_endpoint_kinds=endpoint_kinds,
        closure_status=_closure_status(endpoint_kinds, unresolved_reasons),
        swsd_direction_consistent=direction_consistent,
        swsd_direction_evidence=direction_evidence,
        selection_uniqueness_proof={
            "candidate_rcsdroad_ids": list(candidate_road_ids),
            "selected_chain_component_count": len(components),
            "selected_chain_road_count": len(ordered_road_ids),
            "unresolved_reasons": list(unresolved_reasons),
            "angle_tolerance_deg": BRANCH_MATCH_TOLERANCE_DEG,
            "source": "fallback_rcsdroad_ids_union_first_hit_rcsdroad_ids",
        },
    )


def _pair_swsd_arms(
    rcsd_arms: tuple[RCSDSemanticArm, ...],
    swsd_semantic_junction: Any,
) -> tuple[dict[str, str | None], tuple[str, ...], tuple[str, ...]]:
    swsd_arms = tuple(getattr(swsd_semantic_junction, "semantic_arms", ()) or ())
    mapping: dict[str, str | None] = {}
    ambiguous_arm_ids: list[str] = []
    matched_swsd_arm_ids: set[str] = set()
    for rcsd_arm in rcsd_arms:
        candidates: list[tuple[float, str]] = []
        for swsd_arm in swsd_arms:
            swsd_direction = _clean_text(getattr(swsd_arm, "direction", "unknown"))
            direction_ok = (
                rcsd_arm.direction in {"unknown", "bidirectional"}
                or swsd_direction in {"unknown", "bidirectional"}
                or rcsd_arm.direction == swsd_direction
            )
            if not direction_ok:
                continue
            gap = _angle_gap_deg(rcsd_arm.angle_deg, float(getattr(swsd_arm, "angle_deg", 0.0)))
            if gap <= BRANCH_MATCH_TOLERANCE_DEG:
                candidates.append((gap, _clean_text(getattr(swsd_arm, "arm_id", ""))))
        unique_candidates = sorted({arm_id for _gap, arm_id in candidates if arm_id})
        if len(unique_candidates) == 1:
            mapping[rcsd_arm.arm_id] = unique_candidates[0]
            matched_swsd_arm_ids.add(unique_candidates[0])
        elif len(unique_candidates) > 1:
            mapping[rcsd_arm.arm_id] = None
            ambiguous_arm_ids.append(rcsd_arm.arm_id)
        else:
            mapping[rcsd_arm.arm_id] = None
    swsd_arm_ids = {_clean_text(getattr(arm, "arm_id", "")) for arm in swsd_arms}
    return mapping, tuple(sorted(swsd_arm_ids - matched_swsd_arm_ids)), tuple(ambiguous_arm_ids)


def build_rcsd_semantic_junction(
    *,
    unit_result: Any,
    swsd_semantic_junction: Any,
    rcsd_alignment_result: RCSDAlignmentResult,
) -> RCSDSemanticJunction | None:
    alignment_type = normalize_rcsd_alignment_type(rcsd_alignment_result.rcsd_alignment_type)
    if alignment_type not in RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES:
        return None
    local_context = unit_result.unit_context.local_context
    local_roads = tuple(getattr(local_context, "local_rcsd_roads", ()) or ())
    local_nodes = tuple(getattr(local_context, "local_rcsd_nodes", ()) or ())
    if not local_roads:
        return None
    audit = dict(getattr(unit_result, "positive_rcsd_audit", {}) or {})
    member_rcsdnode_ids = _member_rcsdnode_ids(unit_result, local_nodes)
    member_node_set = set(member_rcsdnode_ids)
    if not member_node_set:
        return None

    roads_by_id = {_clean_text(road.road_id): road for road in local_roads if _clean_text(road.road_id)}
    roads_by_node: dict[str, list[ParsedRoad]] = {}
    for road in local_roads:
        for node_id in _road_endpoint_ids(road):
            if node_id:
                roads_by_node.setdefault(node_id, []).append(road)
    node_by_id = {_clean_text(node.node_id): node for node in local_nodes if _clean_text(node.node_id)}
    local_node_ids = set(node_by_id)
    semantic_degree_by_node = _semantic_boundary_degree_by_node(local_roads, node_by_id=node_by_id)
    positive_road_ids = _clean_ids(rcsd_alignment_result.positive_rcsdroad_ids)
    semantic_arms: list[RCSDSemanticArm] = []
    for road_id in positive_road_ids:
        road = roads_by_id.get(road_id)
        if road is None:
            continue
        snodeid, enodeid = _road_endpoint_ids(road)
        if not ((snodeid in member_node_set) ^ (enodeid in member_node_set)):
            continue
        connector_ids, terminal_node_id, terminal_kind, neighbor_id, member_node_id = _walk_rcsd_connector(
            road,
            roads_by_id=roads_by_id,
            roads_by_node=roads_by_node,
            local_node_ids=local_node_ids,
            member_node_ids=member_node_set,
            node_by_id=node_by_id,
            semantic_degree_by_node=semantic_degree_by_node,
        )
        semantic_arms.append(
            RCSDSemanticArm(
                arm_id=f"rcsd_arm_{len(semantic_arms) + 1:02d}",
                direction=_direction_for_rcsdroad(road_id, audit),
                angle_deg=_road_angle_from_member_node(road, member_node_id),
                first_rcsdroad_ids=(road_id,),
                inter_junction_connector_rcsdroad_ids=connector_ids,
                terminal_rcsdnode_id=terminal_node_id,
                terminal_kind=terminal_kind,
                neighbor_rcsd_junction_id=neighbor_id,
            )
        )
    paired_mapping, missing_swsd_arm_ids, ambiguous_arm_ids = _pair_swsd_arms(
        tuple(semantic_arms),
        swsd_semantic_junction,
    )
    aggregate = _selected_aggregate(unit_result, audit)
    junction_id = (
        _clean_text(getattr(unit_result, "aggregated_rcsd_unit_id", None))
        or _clean_text((aggregate or {}).get("unit_id"))
        or _clean_text(getattr(unit_result, "required_rcsd_node", None))
        or member_rcsdnode_ids[0]
    )
    return RCSDSemanticJunction(
        junction_id=junction_id,
        member_rcsdnode_ids=member_rcsdnode_ids,
        intra_junction_rcsdroad_ids=_collect_intra_rcsdroad_ids(local_roads, member_node_set),
        semantic_arms=tuple(semantic_arms),
        paired_swsd_arm_mapping=paired_mapping,
        alignment_partial_missing_swsd_arm_ids=missing_swsd_arm_ids,
        pairing_ambiguous_arm_ids=ambiguous_arm_ids,
    )


__all__ = [
    "ConsistencyVerdict",
    "RCSDRoadOnlyChain",
    "RCSDSemanticArm",
    "RCSDSemanticJunction",
    "RCSDAlignmentDecision",
    "RCSDAlignmentResult",
    "RCSDAlignmentScope",
    "RCSDAlignmentSelection",
    "RCSDAlignmentType",
    "RCSD_ALIGNMENT_AMBIGUOUS",
    "RCSD_ALIGNMENT_BLOCKING_TYPES",
    "RCSD_ALIGNMENT_FALLBACK_TYPES",
    "RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES",
    "RCSD_ALIGNMENT_JUNCTION_PARTIAL",
    "RCSD_ALIGNMENT_NONE",
    "RCSD_ALIGNMENT_NO_POSITIVE_TYPES",
    "RCSD_ALIGNMENT_POSITIVE_TYPES",
    "RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES",
    "RCSD_ALIGNMENT_ROAD_ONLY",
    "RCSD_ALIGNMENT_SCOPE_CASE",
    "RCSD_ALIGNMENT_SCOPE_EVENT_UNIT",
    "RCSD_ALIGNMENT_SCOPES",
    "RCSD_ALIGNMENT_SECTION_REFERENCE_TYPES",
    "RCSD_ALIGNMENT_SEMANTIC_JUNCTION",
    "RCSD_ALIGNMENT_TYPES",
    "RCSD_CONSISTENCY_RESULT_VALUES",
    "compute_consistency_verdict",
    "build_rcsd_semantic_junction",
    "build_rcsdroad_only_chain",
    "normalize_rcsd_alignment_type",
    "rcsd_alignment_type_from_selection",
    "rcsd_match_type_for_alignment",
    "validate_rcsd_consistency_result",
]
