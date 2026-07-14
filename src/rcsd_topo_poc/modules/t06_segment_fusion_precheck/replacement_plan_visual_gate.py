from __future__ import annotations

import ast
import heapq
from collections import defaultdict, deque
from typing import Any

from shapely.ops import unary_union

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .relation_mapping import RelationRecord
from .road_attributes import is_advance_right_turn_road
from .schemas import feature


MAX_FORMAL_REPLACEMENT_BUFFER_M = 75.0
GROUP_SOURCE_BLOCKED_REASON = "path_corridor_source_segment_blocked"
GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON = "path_corridor_source_segment_not_formal_replaceable"
GROUP_BUFFER_EXCEEDS_REASON = "group_probe_buffer_exceeds_topology_connectivity_audit_threshold"
MIN_VISUAL_REPAIR_GEOMETRY_OVERLAP_RATIO = 0.65
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO = 0.1
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M = 20.0
MAX_CONTROLLED_VISUAL_HIGH_DEVIATION_RATIO = 0.5
MAX_RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
MAX_VISUAL_MANUAL_RELEASE_PAIR_ATTACHMENT_GAP_M = 25.0
MAX_REPLACED_JUNCTION_MAPPING_DIVERGENCE_M = 5.0
MAX_JUNCTION_LOCAL_CONFLICT_ROAD_M = 30.0
RETAINED_JUNCTION_GATE_REASON = "junction_alignment_to_retained_swsd_exceeds_topology_gate"
T05_RELATION_JUNCTION_RELEASE_RISK = "junction_alignment_t05_relation_release"
VISUAL_CONFLICT_SWSD_BUFFER_M = 5.0
VISUAL_CONFLICT_CORRIDOR_BUFFER_M = 15.0
MIN_VISUAL_CONFLICT_PRUNE_OUTSIDE_RATIO = 0.5
VISUAL_CONSISTENCY_STRATEGIES = {
    "visual_consistency_high_confidence_repair",
    "visual_consistency_controlled_release",
    "swsd_buffer_corridor_controlled_release",
}
BUFFER_CORRIDOR_REVIEW_ISSUES = {
    "retained_geometry_outside_swsd_buffer_scope",
    "swsd_geometry_not_covered_by_retained_rcsd",
}
POST_REPLACEMENT_COVERAGE_REVIEW_ISSUES = {
    *BUFFER_CORRIDOR_REVIEW_ISSUES,
    "retained_geometry_outside_swsd_visual_consistency_scope",
    "swsd_visual_continuity_not_covered_by_retained_rcsd",
}


from .replacement_plan_support import (
    _canonicalize_node_id,
    _mark_plan_row_risk,
    _allow_t05_relation_attachment_gap,
    _incident_segments_by_swsd_node,
    _plan_node_mappings,
    _is_pair_anchor_mismatch_mapping,
    _feature_point,
    _ready_plan_segment_ids,
    _pair_anchor_bridges_by_segment,
    _pair_anchor_issues_by_segment,
    _props_by_segment,
    _visual_consistency_release_mode,
    _rcsd_corridor_stays_inside_swsd_buffer,
    _visual_consistency_plan_notes,
    _visual_release_pair_anchor_complete,
    _allow_visual_manual_release_pair_attachment_gap,
    _allow_pair_anchor_repair_attachment_gap,
    _has_high_visual_consistency_deviation,
    _visual_consistency_coverage_gate_failed,
    _coverage_metric,
    _reverse_pair_blockers,
    _blocker_for_pair,
    _pair_key,
    _hard_blocked_group_source_ids,
    _path_corridor_replacement_segment_ids,
    _problem_status,
    _is_same_rcsd_junction_non_replaceable,
    _upstream_directionality_status,
    _problem_owner,
    _recommended_module,
    _feedback_action,
    _replan_trigger,
    _problem_notes,
    _manual_review_required,
    _default_owner_for_reject,
    _index_by_id,
    _canonical_road_endpoint_ids,
    _parse_list,
    _parse_float_list,
    _coerce_float,
    _coerce_optional_float,
    _safe_id,
)
from .replacement_plan_junction_gate import (
    _block_plan_row,
    _is_replace_ready_plan,
    _is_visual_consistency_plan,
    _mark_visual_consistency_manual_audit_release,
)

def _apply_visual_consistency_road_conflict_gate(
    rows: list[dict[str, Any]],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    swsd_segments: list[dict[str, Any]],
) -> None:
    primary_road_owner: dict[str, str] = {}
    primary_plan_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or _is_visual_consistency_plan(props):
            continue
        if props.get("execution_scope") not in {"standard_segment", "path_corridor_group"}:
            continue
        plan_id = str(props.get("replacement_plan_id") or props.get("swsd_segment_id") or "")
        if plan_id:
            primary_plan_by_id[plan_id] = props
        for road_id in _parse_list(props.get("rcsd_road_ids")):
            primary_road_owner.setdefault(road_id, plan_id)
    if not primary_road_owner:
        return

    swsd_geometry_by_segment = _geometry_by_segment_id(swsd_segments)
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or not _is_visual_consistency_plan(props):
            continue
        rcsd_road_ids = _parse_list(props.get("rcsd_road_ids"))
        segment_id = _safe_id(props.get("swsd_segment_id"))
        conflict_road_ids: list[str] = []
        same_group_member_road_ids: list[str] = []
        for road_id in rcsd_road_ids:
            owner_plan_id = primary_road_owner.get(road_id)
            if not owner_plan_id:
                continue
            owner_plan = primary_plan_by_id.get(owner_plan_id, {})
            if _is_same_path_group_member_owner(segment_id, owner_plan):
                same_group_member_road_ids.append(road_id)
                continue
            conflict_road_ids.append(road_id)
        if same_group_member_road_ids:
            props["risk_flags"] = unique_preserve_order(
                [
                    *_parse_list(props.get("risk_flags")),
                    "visual_consistency_same_path_group_member_conflict_accepted",
                ]
            )
            notes = str(props.get("notes") or "")
            suffix = f"accepted_same_path_group_member_rcsd_road_ids={same_group_member_road_ids}"
            props["notes"] = f"{notes}; {suffix}" if notes else suffix
        if not conflict_road_ids:
            continue
        swsd_geometry = swsd_geometry_by_segment.get(_safe_id(props.get("swsd_segment_id")))
        if _reassign_parallel_corridor_from_primary(
            props,
            conflict_road_ids=conflict_road_ids,
            primary_road_owner=primary_road_owner,
            primary_plan_by_id=primary_plan_by_id,
            swsd_geometry=swsd_geometry,
            swsd_geometry_by_segment=swsd_geometry_by_segment,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        ):
            continue
        pruned_road_ids = [
            road_id
            for road_id in conflict_road_ids
            if _is_prunable_junction_local_conflict(
                props,
                road_id,
                swsd_geometry=swsd_geometry,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
        ]
        if pruned_road_ids:
            _prune_plan_roads(
                props,
                pruned_road_ids,
                risk_flag="visual_consistency_junction_connector_conflict_pruned",
                notes_suffix=f"pruned_junction_local_conflict_rcsd_road_ids={pruned_road_ids}",
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
        remaining_conflict_road_ids = [road_id for road_id in conflict_road_ids if road_id not in set(pruned_road_ids)]
        junction_context_pruned_road_ids = _prunable_primary_body_conflict_ids(
            props,
            remaining_conflict_road_ids,
            swsd_geometry=swsd_geometry,
            primary_road_owner=primary_road_owner,
            primary_plan_by_id=primary_plan_by_id,
            swsd_geometry_by_segment=swsd_geometry_by_segment,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
        if junction_context_pruned_road_ids:
            _prune_plan_roads(
                props,
                junction_context_pruned_road_ids,
                risk_flag="visual_consistency_primary_body_conflict_pruned_to_junction_context",
                notes_suffix=(
                    "pruned_primary_body_conflict_rcsd_road_ids="
                    f"{junction_context_pruned_road_ids}"
                ),
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
            remaining_conflict_road_ids = [
                road_id for road_id in remaining_conflict_road_ids if road_id not in set(junction_context_pruned_road_ids)
            ]
        blocking_conflict_road_ids = [
            road_id
            for road_id in remaining_conflict_road_ids
            if not _is_junction_local_conflict_road(
                props,
                road_id,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
        ]
        if remaining_conflict_road_ids and not blocking_conflict_road_ids:
            props["risk_flags"] = unique_preserve_order(
                [
                    *_parse_list(props.get("risk_flags")),
                    "visual_consistency_shared_junction_connector_conflict",
                ]
            )
            notes = str(props.get("notes") or "")
            suffix = f"accepted_shared_junction_connector_rcsd_road_ids={remaining_conflict_road_ids}"
            props["notes"] = f"{notes}; {suffix}" if notes else suffix
            continue
        if (pruned_road_ids or junction_context_pruned_road_ids) and not blocking_conflict_road_ids:
            continue
        _block_plan_row(
            props,
            reason="visual_consistency_road_conflict_with_primary_replacement_plan",
            risk_flag="visual_consistency_road_conflict_with_primary_replacement_plan",
        )
        notes = str(props.get("notes") or "")
        suffix = f"conflict_rcsd_road_ids={blocking_conflict_road_ids or conflict_road_ids}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix


def _reassign_parallel_corridor_from_primary(
    props: dict[str, Any],
    *,
    conflict_road_ids: list[str],
    primary_road_owner: dict[str, str],
    primary_plan_by_id: dict[str, dict[str, Any]],
    swsd_geometry: Any,
    swsd_geometry_by_segment: dict[str, Any],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    if props.get("swsd_directionality") != "single" or not conflict_road_ids:
        return False
    owner_plan_ids = unique_preserve_order(
        [primary_road_owner.get(road_id, "") for road_id in conflict_road_ids if primary_road_owner.get(road_id)]
    )
    if len(owner_plan_ids) != 1:
        return False
    owner_plan_id = owner_plan_ids[0]
    owner_props = primary_plan_by_id.get(owner_plan_id)
    if not owner_props:
        return False
    owner_segment_id = _safe_id(owner_props.get("swsd_segment_id"))
    owner_geometry = swsd_geometry_by_segment.get(owner_segment_id)
    if owner_geometry is None or getattr(owner_geometry, "is_empty", False):
        return False

    current_road_ids = _parse_list(props.get("rcsd_road_ids"))
    owner_road_ids = _parse_list(owner_props.get("rcsd_road_ids"))
    owner_candidate_road_ids = [road_id for road_id in owner_road_ids if road_id not in set(current_road_ids)]
    required_junction_nodes = unique_preserve_order(
        [
            _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
            for node_id in _parse_list(props.get("rcsd_junc_nodes"))
            if _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        ]
    )
    current_anchor_path = _directed_parallel_path_road_ids(
        props,
        current_road_ids,
        require_ordered_junctions=True,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    alternative_pair_path = _directed_parallel_path_road_ids(
        props,
        owner_candidate_road_ids,
        require_ordered_junctions=False,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    alternative_anchor_path = _directed_parallel_path_road_ids(
        props,
        owner_candidate_road_ids,
        require_ordered_junctions=True,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    if not alternative_pair_path:
        return False

    if required_junction_nodes and current_anchor_path and not alternative_anchor_path:
        owner_remaining_road_ids = [road_id for road_id in owner_road_ids if road_id not in set(conflict_road_ids)]
        if not _plan_required_nodes_connected(
            owner_props,
            owner_remaining_road_ids,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        ):
            return False
        owner_props["rcsd_road_ids"] = owner_remaining_road_ids
        owner_props["retained_node_ids"] = _plan_retained_node_ids(
            owner_props,
            rcsd_road_by_id,
            rcsd_node_canonicalizer,
        )
        owner_props["risk_flags"] = unique_preserve_order(
            [
                *_parse_list(owner_props.get("risk_flags")),
                "primary_parallel_corridor_released_to_anchored_segment",
            ]
        )
        owner_notes = str(owner_props.get("notes") or "")
        owner_suffix = (
            f"released_anchor_priority_rcsd_road_ids={conflict_road_ids}; "
            f"released_to_segment_id={_safe_id(props.get('swsd_segment_id'))}"
        )
        owner_props["notes"] = f"{owner_notes}; {owner_suffix}" if owner_notes else owner_suffix

        props["rcsd_road_ids"] = current_anchor_path
        props["parallel_corridor_peer_road_ids"] = []
        props["retained_node_ids"] = _plan_retained_node_ids(
            props,
            rcsd_road_by_id,
            rcsd_node_canonicalizer,
        )
        props["risk_flags"] = unique_preserve_order(
            [
                *_parse_list(props.get("risk_flags")),
                "anchor_priority_parallel_corridor_retained",
            ]
        )
        notes = str(props.get("notes") or "")
        suffix = (
            f"anchor_priority_rcsd_road_ids={current_anchor_path}; "
            "priority=anchor_relation>relative_position>distance"
        )
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
        for road_id in conflict_road_ids:
            primary_road_owner.pop(road_id, None)
        return True

    if required_junction_nodes and alternative_anchor_path and not current_anchor_path:
        alternative_set = set(alternative_anchor_path)
        owner_remaining_road_ids = [road_id for road_id in owner_road_ids if road_id not in alternative_set]
        if not _plan_required_nodes_connected(
            owner_props,
            owner_remaining_road_ids,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        ):
            return False
        owner_props["rcsd_road_ids"] = owner_remaining_road_ids
        owner_props["retained_node_ids"] = _plan_retained_node_ids(
            owner_props,
            rcsd_road_by_id,
            rcsd_node_canonicalizer,
        )
        props["rcsd_road_ids"] = alternative_anchor_path
        props["parallel_corridor_peer_road_ids"] = []
        props["retained_node_ids"] = _plan_retained_node_ids(
            props,
            rcsd_road_by_id,
            rcsd_node_canonicalizer,
        )
        props["risk_flags"] = unique_preserve_order(
            [
                *_parse_list(props.get("risk_flags")),
                "anchor_priority_parallel_corridor_reassigned_from_primary",
            ]
        )
        notes = str(props.get("notes") or "")
        suffix = (
            f"anchor_priority_rcsd_road_ids={alternative_anchor_path}; "
            "priority=anchor_relation>relative_position>distance"
        )
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
        for road_id in alternative_anchor_path:
            primary_road_owner.pop(road_id, None)
        return True

    if required_junction_nodes and not current_anchor_path and not alternative_anchor_path:
        return False

    alternative_road_ids = alternative_anchor_path or alternative_pair_path
    owner_baseline_uncovered = _plan_uncovered_length_after_prune(
        owner_props,
        [],
        swsd_geometry=owner_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
    )
    alternative_owner_uncovered = _plan_uncovered_length_after_prune(
        owner_props,
        alternative_road_ids,
        swsd_geometry=owner_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
    )
    current_owner_uncovered = _plan_uncovered_length_after_prune(
        owner_props,
        conflict_road_ids,
        swsd_geometry=owner_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
    )
    remaining_owner_road_ids = [road_id for road_id in owner_road_ids if road_id not in set(alternative_road_ids)]
    if (
        alternative_owner_uncovered > owner_baseline_uncovered + 1e-6
        or not _plan_pair_nodes_directionally_connected(
            owner_props,
            remaining_owner_road_ids,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
    ):
        return False
    if alternative_owner_uncovered + 1e-6 >= current_owner_uncovered:
        return False

    alternative_set = set(alternative_road_ids)
    owner_props["rcsd_road_ids"] = [road_id for road_id in owner_road_ids if road_id not in alternative_set]
    owner_props["retained_node_ids"] = _plan_retained_node_ids(
        owner_props,
        rcsd_road_by_id,
        rcsd_node_canonicalizer,
    )
    owner_props["risk_flags"] = unique_preserve_order(
        [
            *_parse_list(owner_props.get("risk_flags")),
            "primary_parallel_corridor_transferred_to_visual_segment",
        ]
    )
    owner_notes = str(owner_props.get("notes") or "")
    owner_suffix = (
        f"transferred_parallel_corridor_rcsd_road_ids={alternative_road_ids}; "
        f"transferred_to_segment_id={_safe_id(props.get('swsd_segment_id'))}"
    )
    owner_props["notes"] = f"{owner_notes}; {owner_suffix}" if owner_notes else owner_suffix

    props["rcsd_road_ids"] = alternative_road_ids
    props["parallel_corridor_peer_road_ids"] = current_road_ids
    props["retained_node_ids"] = _plan_retained_node_ids(
        props,
        rcsd_road_by_id,
        rcsd_node_canonicalizer,
    )
    props["risk_flags"] = unique_preserve_order(
        [
            *_parse_list(props.get("risk_flags")),
            "visual_consistency_parallel_corridor_reassigned_from_primary",
        ]
    )
    notes = str(props.get("notes") or "")
    suffix = (
        f"reassigned_parallel_corridor_from_plan_id={owner_plan_id}; "
        f"previous_rcsd_road_ids={current_road_ids}; "
        f"reassigned_rcsd_road_ids={alternative_road_ids}"
    )
    props["notes"] = f"{notes}; {suffix}" if notes else suffix
    for road_id in alternative_road_ids:
        primary_road_owner.pop(road_id, None)
    return True


def _directed_parallel_path_road_ids(
    props: dict[str, Any],
    candidate_road_ids: list[str],
    *,
    require_ordered_junctions: bool = False,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    pair_nodes = [
        _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        for node_id in _parse_list(props.get("rcsd_pair_nodes"))
    ]
    pair_nodes = [node_id for node_id in pair_nodes if node_id]
    if len(pair_nodes) != 2 or swsd_geometry is None or getattr(swsd_geometry, "is_empty", False):
        return []
    search_buffer = swsd_geometry.buffer(MAX_FORMAL_REPLACEMENT_BUFFER_M)
    adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for road_id in candidate_road_ids:
        road = rcsd_road_by_id.get(road_id)
        geometry = (road or {}).get("geometry")
        if road is None or geometry is None or getattr(geometry, "is_empty", False):
            continue
        if not geometry.intersects(search_buffer):
            continue
        road_props = dict(road.get("properties") or {})
        source = _canonicalize_node_id(
            rcsd_node_canonicalizer,
            road_props.get("snodeid") or road_props.get("snode_id") or road_props.get("source"),
        )
        target = _canonicalize_node_id(
            rcsd_node_canonicalizer,
            road_props.get("enodeid") or road_props.get("enode_id") or road_props.get("target"),
        )
        if not source or not target:
            continue
        direction = _coerce_optional_int(road_props.get("direction"))
        weight = max(float(getattr(geometry, "length", 0.0) or 0.0), 1.0)
        if direction in {0, 1, 2}:
            adjacency[source].append((target, weight, road_id))
        if direction in {0, 1, 3}:
            adjacency[target].append((source, weight, road_id))

    junction_nodes = (
        unique_preserve_order(
            [
                _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
                for node_id in _parse_list(props.get("rcsd_junc_nodes"))
                if _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
            ]
        )
        if require_ordered_junctions
        else []
    )
    checkpoints = unique_preserve_order([pair_nodes[0], *junction_nodes, pair_nodes[1]])
    path: list[str] = []
    for checkpoint_index, (source, target) in enumerate(zip(checkpoints, checkpoints[1:])):
        blocked_future_nodes = set(checkpoints[checkpoint_index + 2 :])
        leg = _shortest_directed_path_road_ids(
            adjacency,
            source,
            target,
            blocked_nodes=blocked_future_nodes,
        )
        if not leg:
            return []
        path.extend(leg)
    return unique_preserve_order(path)


def _shortest_directed_path_road_ids(
    adjacency: dict[str, list[tuple[str, float, str]]],
    source: str,
    target: str,
    *,
    blocked_nodes: set[str],
) -> list[str]:
    if source == target:
        return []
    queue: list[tuple[float, int, str]] = [(0.0, 0, source)]
    distances = {source: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    sequence = 0
    while queue:
        distance, _sequence, node_id = heapq.heappop(queue)
        if distance > distances.get(node_id, float("inf")):
            continue
        if node_id == target:
            break
        for next_id, weight, road_id in sorted(adjacency.get(node_id, []), key=lambda item: (item[0], item[2])):
            if next_id in blocked_nodes:
                continue
            next_distance = distance + weight
            if next_distance >= distances.get(next_id, float("inf")):
                continue
            distances[next_id] = next_distance
            previous[next_id] = (node_id, road_id)
            sequence += 1
            heapq.heappush(queue, (next_distance, sequence, next_id))
    if target not in distances:
        return []
    path: list[str] = []
    node_id = target
    while node_id != source:
        step = previous.get(node_id)
        if step is None:
            return []
        node_id, road_id = step
        path.append(road_id)
    path.reverse()
    return path


def _plan_uncovered_length_after_prune(
    props: dict[str, Any],
    road_ids_to_prune: list[str],
    *,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> float:
    prune_set = set(road_ids_to_prune)
    geometries = [
        road.get("geometry")
        for road_id in _parse_list(props.get("rcsd_road_ids"))
        if road_id not in prune_set
        for road in [rcsd_road_by_id.get(road_id)]
        if road is not None and road.get("geometry") is not None and not getattr(road.get("geometry"), "is_empty", False)
    ]
    if not geometries:
        return float("inf")
    retained_geometry = unary_union(geometries)
    return float(swsd_geometry.difference(retained_geometry.buffer(VISUAL_CONFLICT_CORRIDOR_BUFFER_M)).length)


def _plan_pair_nodes_directionally_connected(
    props: dict[str, Any],
    road_ids: list[str],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    pair_nodes = [
        _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        for node_id in _parse_list(props.get("rcsd_pair_nodes"))
    ]
    pair_nodes = [node_id for node_id in pair_nodes if node_id]
    if len(pair_nodes) != 2:
        return False
    adjacency: dict[str, set[str]] = defaultdict(set)
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        road_props = dict((road or {}).get("properties") or {})
        source = _canonicalize_node_id(
            rcsd_node_canonicalizer,
            road_props.get("snodeid") or road_props.get("snode_id") or road_props.get("source"),
        )
        target = _canonicalize_node_id(
            rcsd_node_canonicalizer,
            road_props.get("enodeid") or road_props.get("enode_id") or road_props.get("target"),
        )
        if not source or not target:
            continue
        direction = _coerce_optional_int(road_props.get("direction"))
        if direction in {0, 1, 2}:
            adjacency[source].add(target)
        if direction in {0, 1, 3}:
            adjacency[target].add(source)

    def reachable(source: str, target: str) -> bool:
        queue: deque[str] = deque([source])
        seen = {source}
        while queue:
            node_id = queue.popleft()
            if node_id == target:
                return True
            for next_id in adjacency.get(node_id, set()):
                if next_id in seen:
                    continue
                seen.add(next_id)
                queue.append(next_id)
        return False

    source, target = pair_nodes
    if props.get("swsd_directionality") == "dual":
        return reachable(source, target) and reachable(target, source)
    return reachable(source, target)


def _plan_required_nodes_connected(
    props: dict[str, Any],
    road_ids: list[str],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    required_nodes = unique_preserve_order(
        [
            _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
            for node_id in [
                *_parse_list(props.get("rcsd_pair_nodes")),
                *_parse_list(props.get("rcsd_junc_nodes")),
            ]
            if _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        ]
    )
    if len(required_nodes) < 2:
        return False
    undirected: dict[str, set[str]] = defaultdict(set)
    vertices: set[str] = set()
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        road_props = dict((road or {}).get("properties") or {})
        source = _canonicalize_node_id(rcsd_node_canonicalizer, road_props.get("snodeid"))
        target = _canonicalize_node_id(rcsd_node_canonicalizer, road_props.get("enodeid"))
        if not source or not target:
            continue
        vertices.update((source, target))
        undirected[source].add(target)
        undirected[target].add(source)
    if any(node_id not in vertices for node_id in required_nodes):
        return False
    queue: deque[str] = deque([required_nodes[0]])
    seen = {required_nodes[0]}
    while queue:
        node_id = queue.popleft()
        for next_id in undirected.get(node_id, set()):
            if next_id in seen:
                continue
            seen.add(next_id)
            queue.append(next_id)
    return all(node_id in seen for node_id in required_nodes) and _plan_pair_nodes_directionally_connected(
        props,
        road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_same_path_group_member_owner(segment_id: str | None, owner_plan: dict[str, Any]) -> bool:
    if not segment_id or owner_plan.get("execution_scope") != "path_corridor_group":
        return False
    return segment_id in _parse_list(owner_plan.get("group_segment_ids"))


def _prunable_primary_body_conflict_ids(
    props: dict[str, Any],
    conflict_road_ids: list[str],
    *,
    swsd_geometry: Any,
    primary_road_owner: dict[str, str],
    primary_plan_by_id: dict[str, dict[str, Any]],
    swsd_geometry_by_segment: dict[str, Any],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    if not conflict_road_ids or swsd_geometry is None or getattr(swsd_geometry, "is_empty", False):
        return []
    candidate_road_ids = [road_id for road_id in conflict_road_ids if primary_road_owner.get(road_id)]
    if not candidate_road_ids:
        return []
    if _plan_safe_after_road_prune(
        props,
        candidate_road_ids,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    ):
        return candidate_road_ids
    clear_foreign_ids = [
        road_id
        for road_id in candidate_road_ids
        if _is_clear_primary_body_conflict(
            road_id,
            swsd_geometry=swsd_geometry,
            primary_road_owner=primary_road_owner,
            primary_plan_by_id=primary_plan_by_id,
            swsd_geometry_by_segment=swsd_geometry_by_segment,
            rcsd_road_by_id=rcsd_road_by_id,
        )
    ]
    if not clear_foreign_ids:
        return []
    if _plan_safe_after_road_prune(
        props,
        clear_foreign_ids,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    ):
        return clear_foreign_ids
    pruned_road_ids: list[str] = []
    for road_id in clear_foreign_ids:
        trial = [*pruned_road_ids, road_id]
        if _plan_safe_after_road_prune(
            props,
            trial,
            swsd_geometry=swsd_geometry,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        ):
            pruned_road_ids.append(road_id)
    return pruned_road_ids


def _is_clear_primary_body_conflict(
    road_id: str,
    *,
    swsd_geometry: Any,
    primary_road_owner: dict[str, str],
    primary_plan_by_id: dict[str, dict[str, Any]],
    swsd_geometry_by_segment: dict[str, Any],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> bool:
    road = rcsd_road_by_id.get(road_id)
    geometry = (road or {}).get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return False
    owner_plan = primary_plan_by_id.get(primary_road_owner.get(road_id, ""))
    owner_segment_id = _safe_id((owner_plan or {}).get("swsd_segment_id"))
    owner_geometry = swsd_geometry_by_segment.get(owner_segment_id)
    if owner_geometry is None or getattr(owner_geometry, "is_empty", False):
        return False
    target_overlap = float(geometry.intersection(swsd_geometry.buffer(VISUAL_CONFLICT_SWSD_BUFFER_M)).length)
    owner_overlap = float(geometry.intersection(owner_geometry.buffer(VISUAL_CONFLICT_SWSD_BUFFER_M)).length)
    target_distance = float(geometry.distance(swsd_geometry))
    owner_distance = float(geometry.distance(owner_geometry))
    if owner_overlap > 0.0 and target_overlap <= 1e-9:
        return True
    if owner_overlap >= target_overlap * 1.5 and owner_distance + 1.0 <= target_distance:
        return True
    return target_distance > VISUAL_CONFLICT_SWSD_BUFFER_M and owner_distance <= VISUAL_CONFLICT_SWSD_BUFFER_M


def _plan_safe_after_road_prune(
    props: dict[str, Any],
    road_ids_to_prune: list[str],
    *,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    prune_set = set(road_ids_to_prune)
    remaining_road_ids = [road_id for road_id in _parse_list(props.get("rcsd_road_ids")) if road_id not in prune_set]
    if len(remaining_road_ids) == len(_parse_list(props.get("rcsd_road_ids"))) or not remaining_road_ids:
        return False
    return _plan_pair_nodes_connected(
        props,
        remaining_road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    ) and _plan_corridor_covered(
        remaining_road_ids,
        swsd_geometry=swsd_geometry,
        rcsd_road_by_id=rcsd_road_by_id,
    )


def _plan_pair_nodes_connected(
    props: dict[str, Any],
    road_ids: list[str],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    pair_nodes = [_canonicalize_node_id(rcsd_node_canonicalizer, node_id) for node_id in _parse_list(props.get("rcsd_pair_nodes"))]
    pair_nodes = [node_id for node_id in pair_nodes if node_id]
    if len(pair_nodes) < 2:
        return False
    adjacency: dict[str, set[str]] = defaultdict(set)
    for road_id in road_ids:
        endpoints = _canonical_road_endpoint_ids([road_id], rcsd_road_by_id, rcsd_node_canonicalizer)
        if len(endpoints) < 2:
            continue
        source, target = endpoints[0], endpoints[-1]
        adjacency[source].add(target)
        adjacency[target].add(source)
    source, target = pair_nodes[0], pair_nodes[1]
    if source not in adjacency or target not in adjacency:
        return False
    queue: deque[str] = deque([source])
    seen = {source}
    while queue:
        node_id = queue.popleft()
        if node_id == target:
            return True
        for next_id in adjacency.get(node_id, set()):
            if next_id in seen:
                continue
            seen.add(next_id)
            queue.append(next_id)
    return False


def _plan_corridor_covered(
    road_ids: list[str],
    *,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> bool:
    if swsd_geometry is None or getattr(swsd_geometry, "is_empty", False):
        return False
    geometries = [
        road.get("geometry")
        for road_id in road_ids
        for road in [rcsd_road_by_id.get(road_id)]
        if road is not None and road.get("geometry") is not None and not getattr(road.get("geometry"), "is_empty", False)
    ]
    if not geometries:
        return False
    retained_geometry = unary_union(geometries)
    segment_length = float(getattr(swsd_geometry, "length", 0.0) or 0.0)
    if segment_length <= 0.0:
        return False
    uncovered_length = float(swsd_geometry.difference(retained_geometry.buffer(VISUAL_CONFLICT_CORRIDOR_BUFFER_M)).length)
    uncovered_ratio = uncovered_length / segment_length
    return (
        uncovered_length <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M
        and uncovered_ratio <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO
    )


def _prune_plan_roads(
    props: dict[str, Any],
    road_ids: list[str],
    *,
    risk_flag: str,
    notes_suffix: str,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> None:
    road_id_set = set(road_ids)
    props["rcsd_road_ids"] = [road_id for road_id in _parse_list(props.get("rcsd_road_ids")) if road_id not in road_id_set]
    props["retained_node_ids"] = _plan_retained_node_ids(props, rcsd_road_by_id, rcsd_node_canonicalizer)
    props["risk_flags"] = unique_preserve_order([*_parse_list(props.get("risk_flags")), risk_flag])
    notes = str(props.get("notes") or "")
    props["notes"] = f"{notes}; {notes_suffix}" if notes else notes_suffix
    if not _parse_list(props.get("rcsd_road_ids")):
        _block_plan_row(
            props,
            reason="visual_consistency_pruned_empty_rcsd_road_ids",
            risk_flag="visual_consistency_pruned_empty_rcsd_road_ids",
        )


def _plan_retained_node_ids(
    props: dict[str, Any],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    return unique_preserve_order(
        [
            *_canonical_road_endpoint_ids(_parse_list(props.get("rcsd_road_ids")), rcsd_road_by_id, rcsd_node_canonicalizer),
            *_parse_list(props.get("rcsd_pair_nodes")),
            *_parse_list(props.get("rcsd_junc_nodes")),
            *_parse_list(props.get("optional_junc_rcsd_nodes")),
        ]
    )


def _geometry_by_segment_id(swsd_segments: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for segment in swsd_segments:
        props = dict(segment.get("properties") or {})
        segment_id = _safe_id(props.get("id") or props.get("swsd_segment_id"))
        geometry = segment.get("geometry")
        if segment_id and geometry is not None and not getattr(geometry, "is_empty", False):
            result.setdefault(segment_id, geometry)
    return result


def _visual_outside_swsd_buffer_road_ids(
    road_ids: list[str],
    *,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    if swsd_geometry is None or getattr(swsd_geometry, "is_empty", False):
        return []
    outside_road_ids: list[str] = []
    swsd_buffer = swsd_geometry.buffer(VISUAL_CONFLICT_CORRIDOR_BUFFER_M)
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        road_geometry = (road or {}).get("geometry")
        if road_geometry is None or getattr(road_geometry, "is_empty", False):
            continue
        outside_length = float(road_geometry.difference(swsd_buffer).length)
        if outside_length > 1e-6:
            outside_road_ids.append(road_id)
    return outside_road_ids


def _is_prunable_junction_local_conflict(
    props: dict[str, Any],
    road_id: str,
    *,
    swsd_geometry: Any,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    if swsd_geometry is None:
        return False
    if not _is_junction_local_conflict_road(
        props,
        road_id,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    ):
        return False
    road = rcsd_road_by_id.get(road_id)
    geometry = (road or {}).get("geometry")
    length = float(getattr(geometry, "length", 0.0) or 0.0)
    if geometry is None or length <= 0.0:
        return False
    outside_length = float(geometry.difference(swsd_geometry.buffer(VISUAL_CONFLICT_SWSD_BUFFER_M)).length)
    return outside_length / length >= MIN_VISUAL_CONFLICT_PRUNE_OUTSIDE_RATIO


def _is_junction_local_conflict_road(
    props: dict[str, Any],
    road_id: str,
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    road = rcsd_road_by_id.get(road_id)
    if road is None:
        return False
    geometry = road.get("geometry")
    if geometry is None or float(getattr(geometry, "length", 0.0) or 0.0) > MAX_JUNCTION_LOCAL_CONFLICT_ROAD_M:
        return False
    road_props = dict(road.get("properties") or {})
    endpoints = {
        _canonicalize_node_id(rcsd_node_canonicalizer, road_props.get("snodeid")),
        _canonicalize_node_id(rcsd_node_canonicalizer, road_props.get("enodeid")),
    }
    endpoints.discard("")
    if not endpoints:
        return False
    mapped_semantic_nodes = {
        _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        for node_id in [
            *_parse_list(props.get("rcsd_pair_nodes")),
            *_parse_list(props.get("rcsd_junc_nodes")),
            *_parse_list(props.get("optional_junc_rcsd_nodes")),
        ]
    }
    mapped_semantic_nodes.discard("")
    if endpoints & mapped_semantic_nodes:
        return True
    retained_nodes = {
        _canonicalize_node_id(rcsd_node_canonicalizer, node_id)
        for node_id in _parse_list(props.get("retained_node_ids"))
    }
    retained_nodes.discard("")
    return is_advance_right_turn_road(road_props) and bool(endpoints & retained_nodes)


def _apply_visual_consistency_high_deviation_gate(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or not _is_visual_consistency_plan(props):
            continue
        if "visual_consistency_high_deviation" not in _parse_list(props.get("risk_flags")):
            continue
        _mark_visual_consistency_manual_audit_release(
            props,
            reason="visual_consistency_high_deviation_manual_audit",
        )


def _apply_visual_consistency_coverage_gate(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or props.get("replacement_strategy") != "visual_consistency_controlled_release":
            continue
        swsd_uncovered_length = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_length_m")
        swsd_uncovered_ratio = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_ratio")
        if swsd_uncovered_length is None or swsd_uncovered_ratio is None:
            continue
        if (
            swsd_uncovered_length <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M
            and swsd_uncovered_ratio <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO
        ):
            continue
        _mark_visual_consistency_manual_audit_release(
            props,
            reason="visual_consistency_release_exceeds_formal_replacement_corridor_gate",
        )
