from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .graph_builders import NodeCanonicalizer
from .io import read_features
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order


_GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON = "path_corridor_source_segment_not_formal_replaceable"


@dataclass(frozen=True)
class GroupReplacementAssignment:
    segment_id: str
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    plan_ids: list[str]
    source_segment_ids: list[str]
    group_segment_ids: list[str]
    buffer_distances_m: list[float]
    risk_flags: list[str]


@dataclass(frozen=True)
class GroupReplacementStats:
    input_row_count: int = 0
    passed_row_count: int = 0
    plan_count: int = 0
    assignment_segment_count: int = 0
    skipped_row_count: int = 0


@dataclass(frozen=True)
class _Candidate:
    source_segment_id: str
    segment_ids: list[str]
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    buffer_distance_m: float
    risk_flags: list[str]


def read_group_replacement_assignments(
    path: Path | None,
    *,
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> tuple[dict[str, GroupReplacementAssignment], GroupReplacementStats]:
    if path is None:
        return {}, GroupReplacementStats()

    rows = read_features(path)
    candidates: list[_Candidate] = []
    skipped = 0
    for row in rows:
        props = dict(row.get("properties") or {})
        candidate = _candidate_from_row(
            props,
            segment_by_id=segment_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
            canonicalizer=canonicalizer,
        )
        if candidate is None:
            skipped += 1
            continue
        candidates.append(candidate)

    assignments = _component_assignments(candidates)
    stats = GroupReplacementStats(
        input_row_count=len(rows),
        passed_row_count=len(candidates),
        plan_count=len({plan_id for item in assignments.values() for plan_id in item.plan_ids}),
        assignment_segment_count=len(assignments),
        skipped_row_count=skipped,
    )
    return assignments, stats


def read_group_replacement_assignments_from_plan_rows(
    rows: list[dict[str, Any]],
    *,
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> tuple[dict[str, GroupReplacementAssignment], GroupReplacementStats]:
    candidates: list[_Candidate] = []
    skipped = 0
    member_pair_nodes_by_segment = _standard_pair_nodes_by_segment(rows)
    member_junc_nodes_by_segment = _standard_junc_nodes_by_segment(rows)
    standard_ready_segment_ids = _standard_ready_segment_ids(rows)
    for row in rows:
        props = dict(row.get("properties") or {})
        candidate = _candidate_from_plan_row(
            props,
            segment_by_id=segment_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
            canonicalizer=canonicalizer,
        )
        if candidate is None:
            skipped += 1
            continue
        candidates.append(candidate)

    assignments = _component_assignments(
        candidates,
        member_pair_nodes_by_segment=member_pair_nodes_by_segment,
        member_junc_nodes_by_segment=member_junc_nodes_by_segment,
        standard_ready_segment_ids=standard_ready_segment_ids,
    )
    stats = GroupReplacementStats(
        input_row_count=len(rows),
        passed_row_count=len(candidates),
        plan_count=len({plan_id for item in assignments.values() for plan_id in item.plan_ids}),
        assignment_segment_count=len(assignments),
        skipped_row_count=skipped,
    )
    return assignments, stats


def apply_group_replacement_assignments(
    units: list[Any],
    assignments: dict[str, GroupReplacementAssignment],
    *,
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
    make_unit: Callable[[dict[str, Any]], Any],
) -> int:
    unit_by_segment_id = {unit.segment_id: unit for unit in units}
    created_count = 0
    for segment_id in sorted(assignments, key=_id_sort_key):
        assignment = assignments[segment_id]
        unit = unit_by_segment_id.get(segment_id)
        if unit is None:
            segment = segment_by_id.get(segment_id)
            if segment is None:
                continue
            unit = make_unit(segment)
            units.append(unit)
            unit_by_segment_id[segment_id] = unit
            created_count += 1

        scoped_road_ids = _member_scoped_assignment_road_ids(
            unit,
            assignment,
            segment=segment_by_id.get(segment_id),
            rcsd_road_by_id=rcsd_road_by_id,
        )
        unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, *scoped_road_ids])
        scoped_node_ids = _canonical_road_endpoint_ids(scoped_road_ids, rcsd_road_by_id, canonicalizer)
        unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, *scoped_node_ids])
        if not unit.rcsd_pair_nodes and assignment.rcsd_pair_nodes:
            unit.rcsd_pair_nodes = assignment.rcsd_pair_nodes
        if not unit.rcsd_junc_nodes and assignment.rcsd_junc_nodes:
            unit.rcsd_junc_nodes = assignment.rcsd_junc_nodes
        unit.group_replacement_plan_ids = unique_preserve_order([*unit.group_replacement_plan_ids, *assignment.plan_ids])
        unit.group_replacement_source_segment_ids = unique_preserve_order(
            [*unit.group_replacement_source_segment_ids, *assignment.source_segment_ids]
        )
        unit.group_replacement_segment_ids = unique_preserve_order(
            [*unit.group_replacement_segment_ids, *assignment.group_segment_ids]
        )
        unit.group_replacement_buffer_distances_m = sorted(
            {*unit.group_replacement_buffer_distances_m, *assignment.buffer_distances_m}
        )
        unit.risk_flags = unique_preserve_order([*unit.risk_flags, *assignment.risk_flags])
        if unit.status == "failed" and unit.reason == "missing_rcsd_road_ids" and unit.rcsd_road_ids:
            unit.status = "passed"
        if unit.status == "passed":
            unit.reason = "group_path_corridor_replacement"
    return created_count


def _candidate_from_row(
    props: dict[str, Any],
    *,
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> _Candidate | None:
    if props.get("group_probe_status") != "passed":
        return None
    if props.get("group_probe_repair_owner") != "T06_path_corridor_group_replacement":
        return None

    source_segment_id = _safe_id(props.get("swsd_segment_id"))
    member_segment_ids = _path_corridor_replacement_segment_ids(props)
    segment_ids = _candidate_segment_ids(
        source_segment_id,
        member_segment_ids,
        include_source=source_segment_id in set(member_segment_ids),
    )
    rcsd_road_ids = _parse_list(props.get("group_probe_rcsd_road_ids"))
    if not source_segment_id or not segment_ids or not rcsd_road_ids:
        return None
    if any(segment_id not in segment_by_id for segment_id in segment_ids):
        return None
    if any(road_id not in rcsd_road_by_id for road_id in rcsd_road_ids):
        return None

    retained_node_ids = _canonical_road_endpoint_ids(rcsd_road_ids, rcsd_road_by_id, canonicalizer)
    rcsd_pair_nodes = _parse_list(props.get("rcsd_pair_nodes"))
    rcsd_junc_nodes = _parse_list(props.get("optional_junc_rcsd_nodes")) or _parse_list(props.get("rcsd_junc_nodes"))
    return _Candidate(
        source_segment_id=source_segment_id,
        segment_ids=segment_ids,
        rcsd_road_ids=rcsd_road_ids,
        retained_node_ids=retained_node_ids,
        rcsd_pair_nodes=rcsd_pair_nodes,
        rcsd_junc_nodes=rcsd_junc_nodes,
        buffer_distance_m=_float_or_zero(props.get("group_probe_buffer_distance_m")),
        risk_flags=[],
    )


def _member_scoped_assignment_road_ids(
    unit: Any,
    assignment: GroupReplacementAssignment,
    *,
    segment: dict[str, Any] | None,
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    if str(getattr(unit, "segment_id", "")) in set(assignment.source_segment_ids):
        return assignment.rcsd_road_ids
    if unit.rcsd_road_ids:
        return []
    if segment is None:
        return assignment.rcsd_road_ids
    segment_geometry = segment.get("geometry")
    if segment_geometry is None or segment_geometry.is_empty:
        return assignment.rcsd_road_ids
    max_distance = min(max(assignment.buffer_distances_m or [50.0]), 50.0)
    scoped = [
        road_id
        for road_id in assignment.rcsd_road_ids
        if _road_within_member_corridor(rcsd_road_by_id.get(road_id), segment_geometry, max_distance=max_distance)
    ]
    return scoped or assignment.rcsd_road_ids


def _road_within_member_corridor(road: dict[str, Any] | None, segment_geometry: Any, *, max_distance: float) -> bool:
    if road is None:
        return False
    road_geometry = road.get("geometry")
    if road_geometry is None or road_geometry.is_empty:
        return True
    try:
        return road_geometry.distance(segment_geometry) <= max_distance
    except Exception:
        return True


def _candidate_from_plan_row(
    props: dict[str, Any],
    *,
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> _Candidate | None:
    if props.get("plan_status") != "ready":
        return None
    if props.get("execution_action") != "replace":
        return None
    if props.get("execution_scope") != "path_corridor_group":
        return None

    source_segment_id = _safe_id(props.get("swsd_segment_id"))
    absorbed_member_segment_ids = set(_parse_list(props.get("absorbed_group_member_segments")))
    member_segment_ids = [
        segment_id
        for segment_id in _parse_list(props.get("group_segment_ids"))
        if segment_id == source_segment_id or segment_id not in absorbed_member_segment_ids
    ]
    segment_ids = _candidate_segment_ids(
        source_segment_id,
        member_segment_ids,
        include_source=source_segment_id in set(member_segment_ids),
    )
    rcsd_road_ids = _parse_list(props.get("rcsd_road_ids"))
    if not source_segment_id or not segment_ids or not rcsd_road_ids:
        return None
    if any(segment_id not in segment_by_id for segment_id in segment_ids):
        return None
    if any(road_id not in rcsd_road_by_id for road_id in rcsd_road_ids):
        return None

    retained_node_ids = _parse_list(props.get("retained_node_ids")) or _canonical_road_endpoint_ids(
        rcsd_road_ids,
        rcsd_road_by_id,
        canonicalizer,
    )
    return _Candidate(
        source_segment_id=source_segment_id,
        segment_ids=segment_ids,
        rcsd_road_ids=rcsd_road_ids,
        retained_node_ids=retained_node_ids,
        rcsd_pair_nodes=_parse_list(props.get("rcsd_pair_nodes")),
        rcsd_junc_nodes=_parse_list(props.get("optional_junc_rcsd_nodes")) or _parse_list(props.get("rcsd_junc_nodes")),
        buffer_distance_m=_first_float(props.get("buffer_distances_m")),
        risk_flags=_group_assignment_risk_flags(props.get("risk_flags")),
    )


def _group_assignment_risk_flags(value: Any) -> list[str]:
    risk_flags = _parse_list(value)
    if _GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON in risk_flags:
        return [_GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON]
    return []


def _component_assignments(
    candidates: list[_Candidate],
    *,
    member_pair_nodes_by_segment: dict[str, list[str]] | None = None,
    member_junc_nodes_by_segment: dict[str, list[str]] | None = None,
    standard_ready_segment_ids: set[str] | None = None,
) -> dict[str, GroupReplacementAssignment]:
    if not candidates:
        return {}
    member_pair_nodes_by_segment = member_pair_nodes_by_segment or {}
    member_junc_nodes_by_segment = member_junc_nodes_by_segment or {}
    standard_ready_segment_ids = standard_ready_segment_ids or set()

    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, candidate in enumerate(candidates):
        group_key = f"group:{index}"
        for segment_id in candidate.segment_ids:
            union(group_key, f"segment:{segment_id}")

    components: dict[str, list[tuple[int, _Candidate]]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        components[find(f"group:{index}")].append((index, candidate))

    assignments: dict[str, GroupReplacementAssignment] = {}
    for component_rows in components.values():
        plan_id = "group_path_corridor_" + "_".join(str(index) for index, _ in component_rows)
        source_segment_ids = unique_preserve_order(candidate.source_segment_id for _, candidate in component_rows)
        component_segment_ids = unique_preserve_order(
            segment_id for _, candidate in component_rows for segment_id in candidate.segment_ids
        )
        rcsd_road_ids = unique_preserve_order(
            road_id for _, candidate in component_rows for road_id in candidate.rcsd_road_ids
        )
        retained_node_ids = unique_preserve_order(
            node_id for _, candidate in component_rows for node_id in candidate.retained_node_ids
        )
        pair_nodes_by_source = {
            candidate.source_segment_id: candidate.rcsd_pair_nodes
            for _, candidate in component_rows
            if candidate.rcsd_pair_nodes
        }
        junc_nodes_by_source = {
            candidate.source_segment_id: candidate.rcsd_junc_nodes
            for _, candidate in component_rows
            if candidate.rcsd_junc_nodes
        }
        distances = sorted({candidate.buffer_distance_m for _, candidate in component_rows})
        risk_flags = unique_preserve_order(
            risk_flag for _, candidate in component_rows for risk_flag in candidate.risk_flags
        )
        for segment_id in component_segment_ids:
            if segment_id in standard_ready_segment_ids:
                continue
            assignments[segment_id] = GroupReplacementAssignment(
                segment_id=segment_id,
                rcsd_road_ids=rcsd_road_ids,
                retained_node_ids=retained_node_ids,
                rcsd_pair_nodes=pair_nodes_by_source.get(segment_id) or member_pair_nodes_by_segment.get(segment_id, []),
                rcsd_junc_nodes=junc_nodes_by_source.get(segment_id) or member_junc_nodes_by_segment.get(segment_id, []),
                plan_ids=[plan_id],
                source_segment_ids=source_segment_ids,
                group_segment_ids=component_segment_ids,
                buffer_distances_m=distances,
                risk_flags=risk_flags,
            )
    return assignments


def _canonical_road_endpoint_ids(
    road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> list[str]:
    result: list[str] = []
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        props = dict(road.get("properties") or {}) if road is not None else {}
        for field_name in ("snodeid", "enodeid"):
            try:
                result.append(canonicalizer.canonicalize(props.get(field_name)))
            except ParseError:
                continue
    return unique_preserve_order(result)


def _id_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return 0, f"{int(text):020d}"
    except ValueError:
        return 1, text


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _path_corridor_replacement_segment_ids(props: dict[str, Any]) -> list[str]:
    segment_ids = _parse_list(props.get("path_corridor_group_segment_ids"))
    blocked_segment_ids = set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
    return [segment_id for segment_id in segment_ids if segment_id not in blocked_segment_ids]


def _standard_pair_nodes_by_segment(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("execution_scope") != "standard_segment":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        pair_nodes = _parse_list(props.get("rcsd_pair_nodes"))
        if segment_id and pair_nodes:
            result.setdefault(segment_id, pair_nodes)
    return result


def _standard_junc_nodes_by_segment(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("execution_scope") != "standard_segment":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        junc_nodes = _parse_list(props.get("optional_junc_rcsd_nodes")) or _parse_list(props.get("rcsd_junc_nodes"))
        if segment_id and junc_nodes:
            result.setdefault(segment_id, junc_nodes)
    return result


def _standard_ready_segment_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("plan_status") != "ready":
            continue
        if props.get("execution_action") != "replace":
            continue
        if props.get("execution_scope") != "standard_segment":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            result.add(segment_id)
    return result


def _candidate_segment_ids(source_segment_id: str, segment_ids: list[str], *, include_source: bool) -> list[str]:
    return unique_preserve_order([source_segment_id, *segment_ids]) if source_segment_id and include_source else segment_ids


def _safe_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_float(value: Any) -> float:
    if isinstance(value, (list, tuple)) and value:
        return _float_or_zero(value[0])
    return _float_or_zero(value)
