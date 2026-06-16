from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .relation_mapping import RelationRecord
from .schemas import feature

SPECIAL_JUNCTION_KIND_TYPES = {64: "roundabout", 128: "complex"}


def special_swsd_junction_types(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, str]:
    by_node: dict[str, set[str]] = defaultdict(set)
    for item in features:
        props = dict(item.get("properties") or {})
        try:
            semantic_id = canonicalizer.canonicalize(props.get("id"))
        except ParseError:
            continue
        kind_2 = _coerce_int(props.get("kind_2"))
        special_type = SPECIAL_JUNCTION_KIND_TYPES.get(kind_2)
        if special_type is not None:
            by_node[semantic_id].add(special_type)
    return {node_id: next(iter(types)) if len(types) == 1 else "mixed" for node_id, types in by_node.items()}


def segment_special_junction_ids(
    semantic_node_ids: list[str],
    special_swsd_junction_types: dict[str, str],
    canonicalizer: NodeCanonicalizer,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for node_id in semantic_node_ids:
        try:
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if semantic_id not in special_swsd_junction_types or semantic_id in seen:
            continue
        seen.add(semantic_id)
        result.append(semantic_id)
    return result


def special_gate_applies_to_segment(pair_nodes: list[str]) -> bool:
    return len(set(pair_nodes)) >= 2


def rcsd_semantic_node_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for item in features:
        props = dict(item.get("properties") or {})
        try:
            node_id = normalize_id(props.get("id"))
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if node_id not in result[semantic_id]:
            result[semantic_id].append(node_id)
    return dict(result)


def rcsd_internal_road_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for item in features:
        props = dict(item.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source != target or road_id in result[source]:
            continue
        result[source].append(road_id)
    return dict(result)


def rcsd_graph_edges(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> list[tuple[str, str, str, int | None]]:
    edges: list[tuple[str, str, str, int | None]] = []
    for item in features:
        props = dict(item.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source == target:
            continue
        edges.append((road_id, source, target, _coerce_int(props.get("direction"))))
    return edges


def special_junction_gate(
    *,
    special_junction_segments: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    replaceable_rows: list[dict[str, Any]],
    additional_replaceable_segment_ids: set[str] | None = None,
    relation_map: dict[str, RelationRecord],
    rcsd_junction_node_ids: dict[str, list[str]],
    rcsd_junction_road_ids: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], set[str], set[str], dict[str, list[str]]]:
    standard_replaceable_segment_ids = {
        str((row.get("properties") or {}).get("swsd_segment_id"))
        for row in replaceable_rows
        if (row.get("properties") or {}).get("swsd_segment_id") is not None
    }
    covered_segment_ids = set(standard_replaceable_segment_ids)
    covered_segment_ids.update(str(segment_id) for segment_id in (additional_replaceable_segment_ids or set()) if segment_id is not None)
    rows: list[dict[str, Any]] = []
    blocked_segment_ids: set[str] = set()
    removed_replaceable_segment_ids: set[str] = set()
    blocking_groups_by_segment: dict[str, list[str]] = defaultdict(list)

    for special_junction_id, associated_segment_ids in sorted(special_junction_segments.items()):
        associated = unique_preserve_order(associated_segment_ids)
        replaceable = [segment_id for segment_id in associated if segment_id in covered_segment_ids]
        missing = [segment_id for segment_id in associated if segment_id not in covered_segment_ids]
        gate_status = "passed" if not missing else "blocked"
        if missing:
            blocked_segment_ids.update(associated)
            for segment_id in associated:
                if special_junction_id not in blocking_groups_by_segment[segment_id]:
                    blocking_groups_by_segment[segment_id].append(special_junction_id)
            removed_replaceable_segment_ids.update(segment_id for segment_id in associated if segment_id in standard_replaceable_segment_ids)

        relation = relation_map.get(special_junction_id)
        rcsd_junction_id = ""
        relation_status = "missing_relation"
        if relation is not None:
            if relation.status == 0 and relation.base_id > 0:
                rcsd_junction_id = str(relation.base_id)
                relation_status = "accepted"
            else:
                relation_status = "invalid_relation_status"
        rows.append(
            feature(
                {
                    "special_junction_id": special_junction_id,
                    "special_junction_type": special_swsd_junction_types.get(special_junction_id, "unknown"),
                    "gate_status": gate_status,
                    "relation_status": relation_status,
                    "rcsd_junction_id": rcsd_junction_id,
                    "associated_segment_ids": associated,
                    "associated_segment_count": len(associated),
                    "replaceable_segment_ids": replaceable,
                    "replaceable_segment_count": len(replaceable),
                    "missing_replaceable_segment_ids": missing,
                    "removed_replaceable_segment_ids": [segment_id for segment_id in associated if segment_id in removed_replaceable_segment_ids],
                    "rcsd_junction_node_ids": rcsd_junction_node_ids.get(rcsd_junction_id, []),
                    "rcsd_junction_road_ids": rcsd_junction_road_ids.get(rcsd_junction_id, []),
                    "notes": "all associated Segments are replaceable" if gate_status == "passed" else "at least one associated Segment is not replaceable",
                },
                None,
            )
        )
    return rows, blocked_segment_ids, removed_replaceable_segment_ids, dict(blocking_groups_by_segment)


def annotate_special_junction_gate(
    rows: list[dict[str, Any]],
    *,
    segment_special_junctions: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    blocked_segment_ids: set[str],
    blocking_groups_by_segment: dict[str, list[str]],
) -> None:
    for row in rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        group_ids = segment_special_junctions.get(segment_id, [])
        if not group_ids:
            gate_status = "not_applicable"
        elif segment_id in blocked_segment_ids:
            gate_status = "blocked"
        else:
            gate_status = "passed"
        props["special_junction_group_ids"] = group_ids
        props["special_junction_group_types"] = [special_swsd_junction_types.get(group_id, "unknown") for group_id in group_ids]
        props["special_junction_gate_status"] = gate_status
        props["special_junction_blocking_group_ids"] = blocking_groups_by_segment.get(segment_id, [])
        row["properties"] = props


def rcsd_road_coverage_stats(*, rcsd_roads: list[dict[str, Any]], replaceable_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rcsd_road_by_id = _segment_index(rcsd_roads)
    replaceable_reference_ids: list[str] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        try:
            replaceable_reference_ids.extend(parse_id_list(props.get("rcsd_road_ids"), allow_empty=True))
        except ParseError:
            continue
    replaceable_unique_ids = unique_preserve_order(road_id for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id)
    return {
        "rcsd_road_total_count": len(rcsd_road_by_id),
        "rcsd_road_total_length_m": _round_length(sum(_feature_length(item) for item in rcsd_road_by_id.values())),
        "replaceable_rcsd_road_unique_count": len(replaceable_unique_ids),
        "replaceable_rcsd_road_unique_length_m": _round_length(sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_unique_ids)),
        "replaceable_rcsd_road_reference_count": len(replaceable_reference_ids),
        "replaceable_rcsd_road_reference_length_m": _round_length(
            sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id)
        ),
        "replaceable_rcsd_road_missing_count": sum(1 for road_id in replaceable_reference_ids if road_id not in rcsd_road_by_id),
        "rcsd_road_coverage_stats_basis": "unique_count_and_length_from_final_replaceable_rcsd_road_ids",
    }


def _segment_index(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        try:
            result[normalize_id((item.get("properties") or {}).get("id"))] = item
        except ParseError:
            continue
    return result


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _feature_length(item: dict[str, Any]) -> float:
    geometry = item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)
