from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .graph_builders import NodeCanonicalizer
from .io import read_features
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order


@dataclass(frozen=True)
class GroupReplacementAssignment:
    segment_id: str
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    plan_ids: list[str]
    source_segment_ids: list[str]
    group_segment_ids: list[str]
    buffer_distances_m: list[float]


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
    buffer_distance_m: float


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

    assignments = _component_assignments(candidates)
    stats = GroupReplacementStats(
        input_row_count=len(rows),
        passed_row_count=len(candidates),
        plan_count=len({plan_id for item in assignments.values() for plan_id in item.plan_ids}),
        assignment_segment_count=len(assignments),
        skipped_row_count=skipped,
    )
    return assignments, stats


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
    segment_ids = _path_corridor_replacement_segment_ids(props)
    rcsd_road_ids = _parse_list(props.get("group_probe_rcsd_road_ids"))
    if not source_segment_id or not segment_ids or not rcsd_road_ids:
        return None
    if any(segment_id not in segment_by_id for segment_id in segment_ids):
        return None
    if any(road_id not in rcsd_road_by_id for road_id in rcsd_road_ids):
        return None

    retained_node_ids = _canonical_road_endpoint_ids(rcsd_road_ids, rcsd_road_by_id, canonicalizer)
    rcsd_pair_nodes = _parse_list(props.get("rcsd_pair_nodes"))
    return _Candidate(
        source_segment_id=source_segment_id,
        segment_ids=segment_ids,
        rcsd_road_ids=rcsd_road_ids,
        retained_node_ids=retained_node_ids,
        rcsd_pair_nodes=rcsd_pair_nodes,
        buffer_distance_m=_float_or_zero(props.get("group_probe_buffer_distance_m")),
    )


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
    segment_ids = _parse_list(props.get("group_segment_ids"))
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
        buffer_distance_m=_first_float(props.get("buffer_distances_m")),
    )


def _component_assignments(candidates: list[_Candidate]) -> dict[str, GroupReplacementAssignment]:
    if not candidates:
        return {}

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
        distances = sorted({candidate.buffer_distance_m for _, candidate in component_rows})
        for segment_id in component_segment_ids:
            assignments[segment_id] = GroupReplacementAssignment(
                segment_id=segment_id,
                rcsd_road_ids=rcsd_road_ids,
                retained_node_ids=retained_node_ids,
                rcsd_pair_nodes=pair_nodes_by_source.get(segment_id, []),
                plan_ids=[plan_id],
                source_segment_ids=source_segment_ids,
                group_segment_ids=component_segment_ids,
                buffer_distances_m=distances,
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


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _path_corridor_replacement_segment_ids(props: dict[str, Any]) -> list[str]:
    segment_ids = _parse_list(props.get("path_corridor_group_segment_ids"))
    blocked_segment_ids = set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
    return [segment_id for segment_id in segment_ids if segment_id not in blocked_segment_ids]


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
