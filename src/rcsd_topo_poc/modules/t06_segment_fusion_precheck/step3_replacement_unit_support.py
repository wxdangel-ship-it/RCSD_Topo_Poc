from __future__ import annotations

import json

from collections import defaultdict

from dataclasses import dataclass, field

from pathlib import Path

from typing import Any

from shapely.geometry import LineString, MultiLineString, Point

from shapely.ops import linemerge, unary_union

from .graph_builders import NodeCanonicalizer

from .io import prepare_run_roots, read_features, write_feature_triplet, write_json

from .parallel_output import FeatureTripletJob, publish_feature_triplets

from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order

from .road_attributes import is_near_advance_right_turn_duplicate as _is_adv_dup

from .schemas import (
    STEP2_GROUP_REPLACEMENT_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP3_ADDED_RCSD_NODES_STEM,
    STEP3_ADDED_RCSD_ROADS_STEM,
    STEP3_CHANGE_AUDIT_FIELDS,
    STEP3_DIR,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_ID_COLLISION_AUDIT_FIELDS,
    STEP3_ID_COLLISION_AUDIT_STEM,
    STEP3_JUNCTION_REBUILD_AUDIT_FIELDS,
    STEP3_JUNCTION_REBUILD_AUDIT_STEM,
    STEP3_REMOVED_SWSD_NODES_STEM,
    STEP3_REMOVED_SWSD_ROADS_STEM,
    STEP3_REPLACEMENT_UNIT_FIELDS,
    STEP3_REPLACEMENT_UNITS_STEM,
    STEP3_SUMMARY,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
    STEP3_UNREPLACED_RCSD_ROAD_FIELDS,
    STEP3_UNREPLACED_RCSD_ROADS_STEM,
    T06Step3Artifacts,
    feature,
)

from .step3_advance_right_contract import (
    RIGHT_ATTACH_AUDIT_FIELDS,
    RIGHT_ATTACH_AUDIT_STEM,
    _apply_post_advance_right_attachments,
    _is_advance_right_rcsd_road,
    _retain_post_advance_right_swsd_carriers,
    apply_junction_advance_right_contract,
    apply_retained_swsd_segment_attachment_contract,
)

from .step3_endpoint_nodes import ensure_added_rcsd_road_endpoint_nodes, ensure_retained_swsd_road_endpoint_nodes

from .step3_detached_carriers import retain_detached_junc_swsd_roads

from .step3_group_replacement import (
    apply_group_replacement_assignments,
    read_group_replacement_assignments,
    read_group_replacement_assignments_from_plan_rows,
)

from .step3_group_coverage_fallback import retain_group_coverage_fallback

from .step3_output_utils import (
    change_rows as _change_rows,
    feature_id_set as _feature_id_set,
    fieldnames as _fieldnames,
    id_collision_rows as _id_collision_rows,
    unreplaced_rcsd_road_rows as _unreplaced_rcsd_road_rows,
)

from .step3_relation_node_map import backfill_relation_node_maps_from_attachment_audit, sync_retained_swsd_carrier_mainnodes

from .step3_replacement_plan_reader import read_replacement_plan_rows as _read_replacement_plan_rows

from .step3_unreplaced_bridge_fallback import apply_unreplaced_second_degree_bridge_fallback

from .step3_special_junction_internal import apply_special_junction_internal_swsd_replacement as _apply_sji

from .step3_semantic_junction_groups import (
    SEMANTIC_JUNCTION_GROUP_FIELD,
    STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
    build_semantic_junction_groups,
    downgrade_semantic_junction_topology_rows,
)

from .step3_rcsd_advance_right_closure import (
    RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_FIELDS,
    RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM,
    apply_final_advance_right_endpoint_closure as _close_final_adv,
    apply_native_rcsd_advance_right_closure,
    append_advance_attachment_rcsd_nodes,
    final_swsd_road_endpoint_ids as _swsd_ep,
)

from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)

from .step3_topology_supplement import (
    FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON,
    MIXED_REPLACEMENT_REQUIRES_SWSD_CARRIER_REASON,
    append_junction_surface_release_risk,
    coverage_failed_after_junction_surface_release,
    exclude_retained_swsd_carriers_from_formal_replacements,
    junction_surface_by_node_id_from_features,
    junction_surface_mask_for_unit,
    materialize_topology_supplement_rcsd_roads,
    swsd_buffer_corridor_release_allows_coverage_gap,
)

INHERITED_NODE_FIELDS = ["kind", "grade", "kind_2", "grade_2", "closed_con"]

TS_MAX_RATIO = 0.05

TS_MIN_LEN_M = 20.0

from .step3_replacement_models import (
    JunctionState,
    ReplacementUnit,
    SpecialJunctionGroup,
)

from .step3_replacement_primitives import (
    _coerce_id_value,
    _feature_id,
    _feature_length,
    _id_sort_key,
    _index_by_id,
    _parse_list,
    _replacement_unit_row,
    _road_endpoint_node_id_pair,
    _road_endpoint_node_ids,
    _road_endpoint_points,
    _round_length,
    _safe_normalize,
    _source_key,
    _with_source,
)

def _resolve_special_junction_group_audit_path(
    *,
    step2_replaceable_path: str | Path,
    explicit_path: str | Path | None,
) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"special junction group audit file does not exist: {path}")
        return path
    step2_dir = Path(step2_replaceable_path).parent
    for suffix in (".gpkg", ".json", ".geojson"):
        path = step2_dir / f"{STEP2_SPECIAL_JUNCTION_GROUPS_STEM}{suffix}"
        if path.is_file():
            return path
    return None

def _resolve_group_replacement_audit_path(
    *,
    step2_replaceable_path: str | Path,
    explicit_path: str | Path | None,
) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"group replacement audit file does not exist: {path}")
        return path
    step2_dir = Path(step2_replaceable_path).parent
    for suffix in (".json", ".geojson", ".gpkg"):
        path = step2_dir / f"{STEP2_GROUP_REPLACEMENT_AUDIT_STEM}{suffix}"
        if path.is_file():
            return path
    return None

def _resolve_replacement_plan_path(
    *,
    step2_replaceable_path: str | Path,
    explicit_path: str | Path | None,
) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"replacement plan file does not exist: {path}")
        return path
    step2_dir = Path(step2_replaceable_path).parent
    for suffix in (".json", ".geojson", ".gpkg"):
        path = step2_dir / f"{STEP2_REPLACEMENT_PLAN_STEM}{suffix}"
        if path.is_file():
            return path
    return None

def _replacement_plan_standard_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("plan_status") != "ready":
            continue
        if props.get("execution_action") != "replace":
            continue
        if props.get("execution_scope") != "standard_segment":
            continue
        result.append(row)
    return result

def _read_passed_special_junction_groups(path: Path | None) -> list[SpecialJunctionGroup]:
    if path is None:
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", []) if isinstance(payload, dict) else []
        rows = [{"properties": dict(item.get("properties") or {})} for item in features]
    else:
        rows = read_features(path)
    groups: list[SpecialJunctionGroup] = []
    for item in rows:
        props = dict(item.get("properties") or {})
        if str(props.get("gate_status") or "") != "passed":
            continue
        associated_segment_ids = _parse_list(props.get("associated_segment_ids"))
        if not associated_segment_ids:
            continue
        groups.append(
            SpecialJunctionGroup(
                special_junction_id=_safe_normalize(props.get("special_junction_id") or ""),
                associated_segment_ids=associated_segment_ids,
                rcsd_junction_node_ids=_parse_list(props.get("rcsd_junction_node_ids")),
                rcsd_junction_road_ids=_parse_list(props.get("rcsd_junction_road_ids")),
            )
        )
    return groups

def _read_passed_special_junction_groups_from_plan_rows(rows: list[dict[str, Any]]) -> list[SpecialJunctionGroup]:
    groups: list[SpecialJunctionGroup] = []
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("plan_status") != "ready":
            continue
        if props.get("execution_action") != "include_context":
            continue
        if props.get("execution_scope") != "special_junction_group_internal":
            continue
        associated_segment_ids = _parse_list(props.get("group_segment_ids"))
        if not associated_segment_ids:
            continue
        groups.append(
            SpecialJunctionGroup(
                special_junction_id=_safe_normalize(props.get("special_junction_id") or ""),
                associated_segment_ids=associated_segment_ids,
                rcsd_junction_node_ids=_parse_list(props.get("retained_node_ids")),
                rcsd_junction_road_ids=_parse_list(props.get("rcsd_road_ids")),
            )
        )
    return groups

def _special_group_entity_segments(
    *,
    groups: list[SpecialJunctionGroup],
    entity_attr: str,
    passed_unit_ids: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for group in groups:
        segment_ids = [segment_id for segment_id in group.associated_segment_ids if segment_id in passed_unit_ids]
        if not segment_ids:
            continue
        for entity_id in getattr(group, entity_attr):
            _append_unique_segments(result[entity_id], segment_ids)
    return dict(result)

def _append_unique_segments(target: list[str], segment_ids: list[str]) -> None:
    for segment_id in segment_ids:
        if segment_id not in target:
            target.append(segment_id)

def _build_replacement_units(replaceable: list[dict[str, Any]], segment_by_id: dict[str, dict[str, Any]], *, progress: bool) -> list[ReplacementUnit]:
    units: list[ReplacementUnit] = []
    for index, item in enumerate(replaceable, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step3] parsed {index}/{len(replaceable)} replaceable rows", flush=True)
        props = dict(item.get("properties") or {})
        segment_id = _safe_normalize(props.get("swsd_segment_id") or props.get("id") or f"segment_{index}")
        segment = segment_by_id.get(segment_id)
        segment_props = dict(segment.get("properties") or {}) if segment is not None else {}
        pair_nodes = _parse_list(props.get("swsd_pair_nodes", segment_props.get("pair_nodes")))
        junc_nodes = _parse_list(props.get("swsd_junc_nodes", segment_props.get("junc_nodes")))
        original_junc_nodes = _parse_list(segment_props.get("junc_nodes"))
        swsd_road_ids = _parse_list(segment_props.get("roads"))
        detached_junc_nodes = [node_id for node_id in original_junc_nodes if node_id not in set(junc_nodes)]
        rcsd_road_ids = _parse_list(props.get("rcsd_road_ids") or props.get("retained_rcsd_road_ids"))
        retained_node_ids = _parse_list(props.get("retained_node_ids"))
        unit = ReplacementUnit(
            segment_id=segment_id,
            pair_nodes=pair_nodes,
            junc_nodes=junc_nodes,
            junc_kind2_exempt_nodes=_parse_list(props.get("junc_kind2_exempt_nodes")),
            original_junc_nodes=original_junc_nodes,
            original_swsd_road_ids=swsd_road_ids,
            swsd_road_ids=swsd_road_ids,
            retained_detached_swsd_road_ids=[],
            detached_junc_nodes=detached_junc_nodes,
            rcsd_road_ids=rcsd_road_ids,
            retained_node_ids=retained_node_ids,
            rcsd_pair_nodes=_parse_list(props.get("rcsd_pair_nodes")),
            rcsd_junc_nodes=_parse_list(props.get("rcsd_junc_nodes")),
            optional_allowed_rcsd_nodes=_parse_list(props.get("optional_allowed_rcsd_nodes")),
            geometry=item.get("geometry") or (segment or {}).get("geometry"),
            risk_flags=_parse_list(props.get("risk_flags")),
        )
        if segment is None:
            unit.status = "failed"
            unit.reason = "missing_swsd_segment"
        elif not swsd_road_ids:
            unit.status = "failed"
            unit.reason = "missing_swsd_segment_roads"
        elif not rcsd_road_ids:
            unit.status = "failed"
            unit.reason = "missing_rcsd_road_ids"
        units.append(unit)
    return units

def _replacement_unit_from_segment(segment: dict[str, Any]) -> ReplacementUnit:
    props = dict(segment.get("properties") or {})
    segment_id = _feature_id(segment)
    pair_nodes = _parse_list(props.get("pair_nodes"))
    junc_nodes = _parse_list(props.get("junc_nodes"))
    swsd_road_ids = _parse_list(props.get("roads"))
    unit = ReplacementUnit(
        segment_id=segment_id,
        pair_nodes=pair_nodes,
        junc_nodes=junc_nodes,
        junc_kind2_exempt_nodes=_parse_list(props.get("junc_kind2_exempt_nodes")),
        original_junc_nodes=junc_nodes,
        original_swsd_road_ids=swsd_road_ids,
        swsd_road_ids=swsd_road_ids,
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        rcsd_road_ids=[],
        retained_node_ids=[],
        rcsd_pair_nodes=[],
        rcsd_junc_nodes=[],
        optional_allowed_rcsd_nodes=[],
        geometry=segment.get("geometry"),
    )
    if not swsd_road_ids:
        unit.status = "failed"
        unit.reason = "missing_swsd_segment_roads"
    return unit

def _compute_removed_swsd_maps(
    units: list[ReplacementUnit],
    *,
    swsd_roads: list[dict[str, Any]],
    swsd_road_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]], int]:
    removed_road_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        for road_id in unit.swsd_road_ids:
            if road_id in swsd_road_by_id:
                removed_road_to_segments[road_id].append(unit.segment_id)

    removed_node_to_segments: dict[str, list[str]] = defaultdict(list)
    for road_id, segment_ids in removed_road_to_segments.items():
        for node_id in _road_endpoint_node_ids(swsd_road_by_id[road_id]):
            for segment_id in segment_ids:
                if segment_id not in removed_node_to_segments[node_id]:
                    removed_node_to_segments[node_id].append(segment_id)
    retained_swsd_endpoint_node_ids = _retained_swsd_endpoint_node_ids(
        swsd_roads=swsd_roads,
        removed_road_ids=set(removed_road_to_segments),
    )
    preserved_removed_node_ids = sorted(
        set(removed_node_to_segments).intersection(retained_swsd_endpoint_node_ids),
        key=_id_sort_key,
    )
    for node_id in preserved_removed_node_ids:
        removed_node_to_segments.pop(node_id, None)

    for unit in units:
        unit.removed_swsd_node_ids = unique_preserve_order(
            [
                node_id
                for road_id in unit.swsd_road_ids
                if road_id in swsd_road_by_id
                for node_id in _road_endpoint_node_ids(swsd_road_by_id[road_id])
                if node_id in removed_node_to_segments
            ]
        )
    return dict(removed_road_to_segments), dict(removed_node_to_segments), len(preserved_removed_node_ids)

def _retain_topology_supplement_swsd_roads(
    units: list[ReplacementUnit],
    *,
    swsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    global_rcsd_road_ids: list[str],
    attachment_audit_rows: list[dict[str, Any]],
    junction_surface_by_node_id: dict[str, Any] | None = None,
) -> dict[str, int]:
    canonicalizer = NodeCanonicalizer.from_node_features(rcsd_nodes)
    attachment_node_by_swsd = _attachment_rcsd_nodes_by_swsd_node(attachment_audit_rows)
    peer_node_by_swsd = _peer_mapped_rcsd_nodes_by_swsd_node(units)
    global_rcsd_roads = [
        rcsd_road_by_id[road_id]
        for road_id in global_rcsd_road_ids
        if road_id in rcsd_road_by_id
    ]
    global_graph = _UnitRoadGraph(global_rcsd_roads, canonicalizer=canonicalizer)
    retained_count = 0
    affected_unit_count = 0
    for unit in units:
        if unit.group_replacement_plan_ids and unit.segment_id in set(unit.group_replacement_source_segment_ids):
            continue
        semantic_nodes = set(unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes]))
        if not semantic_nodes:
            continue
        unit_corridor = _road_union_corridor(
            [rcsd_road_by_id[road_id] for road_id in unit.rcsd_road_ids if road_id in rcsd_road_by_id]
        )
        retained: list[str] = []
        allowed_surface = junction_surface_mask_for_unit(unit, junction_surface_by_node_id)
        for road_id in unit.swsd_road_ids:
            road = swsd_road_by_id.get(road_id)
            endpoints = _road_endpoint_node_ids(road) if road is not None else []
            if len(endpoints) < 2 or not all(endpoint in semantic_nodes for endpoint in endpoints[:2]):
                continue
            start_nodes = [
                canonicalizer.canonicalize(node_id)
                for node_id in _mapped_unit_rcsd_nodes(unit, endpoints[0], attachment_node_by_swsd, peer_node_by_swsd)
            ]
            end_nodes = [
                canonicalizer.canonicalize(node_id)
                for node_id in _mapped_unit_rcsd_nodes(unit, endpoints[1], attachment_node_by_swsd, peer_node_by_swsd)
            ]
            path_forward = global_graph.reachable_any(start_nodes, end_nodes)
            path_reverse = global_graph.reachable_any(end_nodes, start_nodes)
            undirected_connected = global_graph.undirected_reachable_any(start_nodes, end_nodes)
            direction = _coerce_int((road.get("properties") or {}).get("direction")) if road is not None else None
            coverage_failed, coverage_released = _road_corridor_coverage_failed(
                road,
                unit_corridor,
                allowed_surface=allowed_surface,
            )
            if coverage_released:
                append_junction_surface_release_risk(unit)
            if _directed_path_missing(direction, path_forward, path_reverse, undirected_connected) or (
                coverage_failed and not swsd_buffer_corridor_release_allows_coverage_gap(unit)
            ):
                retained.append(road_id)
        if retained:
            unit.retained_detached_swsd_road_ids = unique_preserve_order([*unit.retained_detached_swsd_road_ids, *retained])
            retained_count += len(retained)
            affected_unit_count += 1
    return {
        "retained_swsd_road_count": retained_count,
        "affected_segment_count": affected_unit_count,
    }

class _UnitRoadGraph:
    def __init__(self, roads: list[dict[str, Any]], *, canonicalizer: NodeCanonicalizer) -> None:
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.undirected: dict[str, set[str]] = defaultdict(set)
        for road in roads:
            endpoints = _road_endpoint_node_ids(road)
            if len(endpoints) < 2:
                continue
            source = canonicalizer.canonicalize(endpoints[0])
            target = canonicalizer.canonicalize(endpoints[-1])
            direction = _coerce_int((road.get("properties") or {}).get("direction"))
            if direction in {0, 1, 2}:
                self.forward[source].add(target)
            if direction in {0, 1, 3}:
                self.forward[target].add(source)
            self.undirected[source].add(target)
            self.undirected[target].add(source)

    def reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        return _reachable_any(self.forward, starts, targets)

    def undirected_reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        return _reachable_any(self.undirected, starts, targets)

def _reachable_any(graph: dict[str, set[str]], starts: list[str], targets: list[str]) -> bool:
    if not starts or not targets:
        return False
    target_set = set(targets)
    queue = list(dict.fromkeys(starts))
    seen = set(queue)
    while queue:
        node_id = queue.pop(0)
        if node_id in target_set:
            return True
        for next_id in graph.get(node_id, set()):
            if next_id in seen:
                continue
            seen.add(next_id)
            queue.append(next_id)
    return False

def _attachment_rcsd_nodes_by_swsd_node(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        swsd_node_id = _safe_normalize(props.get("swsd_node_id") or "")
        rcsd_node_id = _safe_normalize(props.get("rcsd_node_id") or props.get("generated_rcsd_node_id") or "")
        if not swsd_node_id or not rcsd_node_id:
            continue
        if rcsd_node_id not in result[swsd_node_id]:
            result[swsd_node_id].append(rcsd_node_id)
    return dict(result)

def _peer_mapped_rcsd_nodes_by_swsd_node(units: list[ReplacementUnit]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        if unit.status != "passed":
            continue
        for swsd_node_id, rcsd_node_ids in _mapped_rcsd_semantic_by_c(unit).items():
            result[swsd_node_id] = unique_preserve_order([*result[swsd_node_id], *rcsd_node_ids])
    return dict(result)

def _mapped_unit_rcsd_nodes(
    unit: ReplacementUnit,
    swsd_node_id: str,
    attachment_node_by_swsd: dict[str, list[str]],
    peer_node_by_swsd: dict[str, list[str]],
) -> list[str]:
    if swsd_node_id in attachment_node_by_swsd:
        return attachment_node_by_swsd[swsd_node_id]
    result: list[str] = []
    for source_node_id, rcsd_node_id in zip(unit.pair_nodes, unit.rcsd_pair_nodes):
        if source_node_id == swsd_node_id:
            result.append(rcsd_node_id)
    exempt_nodes = set(unit.junc_kind2_exempt_nodes)
    relation_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id not in exempt_nodes]
    for source_node_id, rcsd_node_id in zip(relation_junc_nodes, unit.rcsd_junc_nodes):
        if source_node_id == swsd_node_id:
            result.append(rcsd_node_id)
    optional_nodes = unit.optional_allowed_rcsd_nodes
    exempt_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id in exempt_nodes]
    if len(exempt_junc_nodes) == len(optional_nodes):
        for source_node_id, rcsd_node_id in zip(exempt_junc_nodes, optional_nodes):
            if source_node_id == swsd_node_id:
                result.append(rcsd_node_id)
    for rcsd_node_id in peer_node_by_swsd.get(swsd_node_id, []):
        if rcsd_node_id not in result:
            result.append(rcsd_node_id)
    return unique_preserve_order(result)

def _road_union_corridor(roads: list[dict[str, Any]]) -> Any:
    geometries = [
        road.get("geometry")
        for road in roads
        if road.get("geometry") is not None and not road.get("geometry").is_empty
    ]
    if not geometries:
        return None
    return unary_union(geometries).buffer(2.0)

def _road_corridor_coverage_failed(
    swsd_road: dict[str, Any] | None,
    selected_corridor: Any,
    *,
    allowed_surface: Any | None = None,
) -> tuple[bool, bool]:
    if swsd_road is None or selected_corridor is None:
        return False, False
    geometry = swsd_road.get("geometry")
    if geometry is None or geometry.is_empty or geometry.length <= 0:
        return False, False
    return coverage_failed_after_junction_surface_release(
        geometry,
        selected_corridor,
        max_uncovered_ratio=TS_MAX_RATIO,
        min_uncovered_length_m=TS_MIN_LEN_M,
        allowed_surface=allowed_surface,
    )

def _directed_path_missing(
    direction: int | None,
    path_forward: bool,
    path_reverse: bool,
    undirected_connected: bool,
) -> bool:
    if direction in {0, 1}:
        return not (path_forward and path_reverse)
    if direction == 2:
        return not path_forward
    if direction == 3:
        return not path_reverse
    return not undirected_connected

def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _retained_swsd_endpoint_node_ids(*, swsd_roads: list[dict[str, Any]], removed_road_ids: set[str]) -> set[str]:
    retained: set[str] = set()
    for road in swsd_roads:
        if _feature_id(road) in removed_road_ids:
            continue
        retained.update(_road_endpoint_node_ids(road))
    return retained

def _mapped_rcsd_semantic_by_c(unit: ReplacementUnit) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for swsd_node, rcsd_node in zip(unit.pair_nodes, unit.rcsd_pair_nodes):
        result[swsd_node].append(rcsd_node)
    exempt = set(unit.junc_kind2_exempt_nodes)
    relation_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id not in exempt]
    for swsd_node, rcsd_node in zip(relation_junc_nodes, unit.rcsd_junc_nodes):
        result[swsd_node].append(rcsd_node)
    exempt_junc_nodes = [node_id for node_id in unit.junc_nodes if node_id in exempt]
    if len(exempt_junc_nodes) == len(unit.optional_allowed_rcsd_nodes):
        for swsd_node, rcsd_node in zip(exempt_junc_nodes, unit.optional_allowed_rcsd_nodes):
            result[swsd_node].append(rcsd_node)
    return {key: unique_preserve_order(value) for key, value in result.items()}
