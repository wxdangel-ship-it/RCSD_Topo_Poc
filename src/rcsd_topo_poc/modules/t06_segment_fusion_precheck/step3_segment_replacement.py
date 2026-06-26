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
from .step3_semantic_junction_groups import (
    SEMANTIC_JUNCTION_GROUP_FIELD,
    STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
    build_semantic_junction_groups,
    downgrade_semantic_junction_topology_rows,
)
from .step3_rcsd_advance_right_closure import (
    apply_final_advance_right_endpoint_closure as _close_final_adv,
    apply_native_rcsd_advance_right_closure,
    append_advance_attachment_rcsd_nodes,
    final_swsd_road_endpoint_ids as _swsd_ep,
    write_rcsd_advance_right_closure_audit,
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
)


INHERITED_NODE_FIELDS = ["kind", "grade", "kind_2", "grade_2", "closed_con"]
TOPOLOGY_SUPPLEMENT_MAX_UNCOVERED_RATIO = 0.05
TOPOLOGY_SUPPLEMENT_MIN_UNCOVERED_LENGTH_M = 20.0


@dataclass
class ReplacementUnit:
    segment_id: str
    pair_nodes: list[str]
    junc_nodes: list[str]
    junc_kind2_exempt_nodes: list[str]
    original_junc_nodes: list[str]
    original_swsd_road_ids: list[str]
    swsd_road_ids: list[str]
    retained_detached_swsd_road_ids: list[str]
    detached_junc_nodes: list[str]
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    geometry: Any
    status: str = "passed"
    reason: str = "replaceable"
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)
    group_replacement_plan_ids: list[str] = field(default_factory=list)
    group_replacement_source_segment_ids: list[str] = field(default_factory=list)
    group_replacement_segment_ids: list[str] = field(default_factory=list)
    group_replacement_buffer_distances_m: list[float] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class SpecialJunctionGroup:
    special_junction_id: str
    associated_segment_ids: list[str]
    rcsd_junction_node_ids: list[str]
    rcsd_junction_road_ids: list[str]


@dataclass
class JunctionState:
    c_id: str
    replacement_segment_ids: list[str] = field(default_factory=list)
    retained_segment_ids: list[str] = field(default_factory=list)
    mapped_rcsd_semantic_ids: list[str] = field(default_factory=list)
    original_member_node_ids: list[str] = field(default_factory=list)
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    remaining_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)
    advance_attachment_rcsd_node_ids: list[str] = field(default_factory=list)
    original_main_props: dict[str, Any] = field(default_factory=dict)


def run_t06_step3_segment_replacement(
    *,
    step2_replaceable_path: str | Path,
    step2_special_junction_group_audit_path: str | Path | None = None,
    step2_group_replacement_audit_path: str | Path | None = None,
    step2_replacement_plan_path: str | Path | None = None,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    junction_surface_path: str | Path | None = None,
    source_field_name: str = "source",
    rcsd_source_value: int = 1,
    swsd_source_value: int = 2,
    progress: bool = False,
) -> T06Step3Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP3_DIR)
    replaceable = read_features(step2_replaceable_path)
    swsd_segments = read_features(swsd_segment_path)
    swsd_roads = read_features(swsd_roads_path)
    swsd_nodes = read_features(swsd_nodes_path)
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_nodes = read_features(rcsdnode_path)
    junction_surface_by_node_id = (
        junction_surface_by_node_id_from_features(read_features(junction_surface_path))
        if junction_surface_path is not None
        else {}
    )

    segment_by_id = _index_by_id(swsd_segments)
    swsd_road_by_id = _index_by_id(swsd_roads)
    swsd_node_by_id = _index_by_id(swsd_nodes)
    rcsd_road_by_id = _index_by_id(rcsd_roads)
    rcsd_node_by_id = _index_by_id(rcsd_nodes)
    canonicalizer = NodeCanonicalizer.from_node_features(rcsd_nodes)

    replacement_plan_path = _resolve_replacement_plan_path(
        step2_replaceable_path=step2_replaceable_path,
        explicit_path=step2_replacement_plan_path,
    )
    replacement_plan_rows = _read_replacement_plan_rows(replacement_plan_path)
    standard_plan_rows = _replacement_plan_standard_rows(replacement_plan_rows)
    replacement_unit_input = standard_plan_rows if replacement_plan_rows else replaceable
    units = _build_replacement_units(replacement_unit_input, segment_by_id, progress=progress)
    group_replacement_audit_path = None
    if replacement_plan_rows:
        group_replacement_assignments, group_replacement_stats = read_group_replacement_assignments_from_plan_rows(
            replacement_plan_rows,
            segment_by_id=segment_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
            canonicalizer=canonicalizer,
        )
    else:
        group_replacement_audit_path = _resolve_group_replacement_audit_path(
            step2_replaceable_path=step2_replaceable_path,
            explicit_path=step2_group_replacement_audit_path,
        )
        group_replacement_assignments, group_replacement_stats = read_group_replacement_assignments(
            group_replacement_audit_path,
            segment_by_id=segment_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
            canonicalizer=canonicalizer,
        )
    group_replacement_created_unit_count = apply_group_replacement_assignments(
        units,
        group_replacement_assignments,
        segment_by_id=segment_by_id,
        rcsd_road_by_id=rcsd_road_by_id,
        canonicalizer=canonicalizer,
        make_unit=_replacement_unit_from_segment,
    )
    passed_units = [unit for unit in units if unit.status == "passed"]
    retain_detached_junc_swsd_roads(passed_units, swsd_road_by_id)
    passed_unit_ids = {unit.segment_id for unit in passed_units}
    special_group_audit_path = None
    if replacement_plan_rows:
        special_groups = _read_passed_special_junction_groups_from_plan_rows(replacement_plan_rows)
    else:
        special_group_audit_path = _resolve_special_junction_group_audit_path(
            step2_replaceable_path=step2_replaceable_path,
            explicit_path=step2_special_junction_group_audit_path,
        )
        special_groups = _read_passed_special_junction_groups(special_group_audit_path)
    special_added_road_to_segments = _special_group_entity_segments(
        groups=special_groups,
        entity_attr="rcsd_junction_road_ids",
        passed_unit_ids=passed_unit_ids,
    )
    special_added_node_to_segments = _special_group_entity_segments(
        groups=special_groups,
        entity_attr="rcsd_junction_node_ids",
        passed_unit_ids=passed_unit_ids,
    )
    post_advance_right_swsd_carrier_stats = _retain_post_advance_right_swsd_carriers(
        passed_units,
        swsd_roads=swsd_roads,
        rcsd_roads=rcsd_roads,
    )
    topology_supplement_stats = _retain_topology_supplement_swsd_roads(
        passed_units,
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_nodes=rcsd_nodes,
        global_rcsd_road_ids=unique_preserve_order(
            road_id
            for unit in passed_units
            for road_id in unit.rcsd_road_ids
            if road_id in rcsd_road_by_id
        ),
        attachment_audit_rows=[],
        junction_surface_by_node_id=junction_surface_by_node_id,
    )

    removed_road_to_segments, removed_node_to_segments, preserved_removed_node_count = _compute_removed_swsd_maps(
        passed_units,
        swsd_roads=swsd_roads,
        swsd_road_by_id=swsd_road_by_id,
    )

    added_road_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in passed_units:
        for road_id in unit.rcsd_road_ids:
            if road_id in rcsd_road_by_id:
                added_road_to_segments[road_id].append(unit.segment_id)
    for road_id, segment_ids in special_added_road_to_segments.items():
        if road_id in rcsd_road_by_id:
            _append_unique_segments(added_road_to_segments[road_id], segment_ids)

    retained_swsd_roads = [road for road in swsd_roads if _feature_id(road) not in removed_road_to_segments]
    retained_swsd_endpoint_node_stats = ensure_retained_swsd_road_endpoint_nodes(
        swsd_roads=retained_swsd_roads,
        swsd_nodes=swsd_nodes,
        swsd_node_by_id=swsd_node_by_id,
    )
    post_advance_right_attachment_stats = _apply_post_advance_right_attachments(
        passed_units,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        swsd_node_by_id=swsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads,
        added_road_to_segments=added_road_to_segments,
        canonicalizer=canonicalizer,
    )
    right_attach_contract_stats = apply_junction_advance_right_contract(
        passed_units,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        swsd_node_by_id=swsd_node_by_id,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads,
        added_road_to_segments=added_road_to_segments,
    )
    retained_swsd_attach_contract_stats = apply_retained_swsd_segment_attachment_contract(
        passed_units,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        swsd_node_by_id=swsd_node_by_id,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads,
        added_road_to_segments=added_road_to_segments,
    )
    right_attach_audit_rows = [
        *right_attach_contract_stats["audit_rows"],
        *retained_swsd_attach_contract_stats["audit_rows"],
    ]
    topology_supplement_materialized_stats = materialize_topology_supplement_rcsd_roads(
        passed_units,
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id=swsd_node_by_id,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        attachment_audit_rows=right_attach_audit_rows,
        added_road_to_segments=added_road_to_segments,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
        retained_swsd_roads=retained_swsd_roads,
        junction_surface_by_node_id=junction_surface_by_node_id,
    )
    retained_swsd_excluded_stats = exclude_retained_swsd_carriers_from_formal_replacements(
        passed_units,
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments=removed_road_to_segments,
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id=rcsd_road_by_id,
        junction_surface_by_node_id=junction_surface_by_node_id,
    )
    if retained_swsd_excluded_stats["deactivated_segment_count"]:
        passed_units = [unit for unit in passed_units if unit.status == "passed"]
    if (
        topology_supplement_materialized_stats["materialized_road_count"]
        or topology_supplement_materialized_stats.get("reused_existing_rcsd_advance_count")
        or topology_supplement_materialized_stats.get("formal_body_retained_restored_count")
        or retained_swsd_excluded_stats["deactivated_segment_count"]
    ):
        removed_road_to_segments, removed_node_to_segments, preserved_removed_node_count = _compute_removed_swsd_maps(
            passed_units,
            swsd_roads=swsd_roads,
            swsd_road_by_id=swsd_road_by_id,
        )
        removed_road_to_segments.update(retained_swsd_excluded_stats.get("extra_removed_road_to_segments", {}))
    _flatten_node_mainnode_chains(rcsd_nodes, source_field_name=source_field_name)
    generated_endpoint_node_stats = ensure_added_rcsd_road_endpoint_nodes(
        units=passed_units,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        added_road_to_segments=added_road_to_segments,
    )
    adv_closure_stats = apply_native_rcsd_advance_right_closure(
        passed_units, rcsd_roads=rcsd_roads, rcsd_nodes=rcsd_nodes, rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id, swsd_roads=swsd_roads, swsd_nodes=swsd_nodes,
        swsd_road_by_id=swsd_road_by_id, swsd_node_by_id=swsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads, added_road_to_segments=added_road_to_segments,
    )

    selected_rcsd_semantic_ids = _selected_rcsd_semantic_ids(passed_units)
    selected_rcsd_raw_node_ids = _selected_rcsd_raw_node_ids(added_road_to_segments, rcsd_road_by_id)
    selected_rcsd_raw_node_ids.update(node_id for node_id in special_added_node_to_segments if node_id in rcsd_node_by_id)
    for node_id in special_added_node_to_segments:
        node = rcsd_node_by_id.get(node_id)
        if node is None:
            continue
        selected_rcsd_semantic_ids.add(canonicalizer.canonicalize(node_id))
    added_node_to_segments = _select_added_rcsd_nodes(
        rcsd_nodes=rcsd_nodes,
        selected_raw_node_ids=selected_rcsd_raw_node_ids,
        selected_semantic_node_ids=selected_rcsd_semantic_ids,
        canonicalizer=canonicalizer,
        units=passed_units,
    )
    for node_id, segment_ids in special_added_node_to_segments.items():
        if node_id in rcsd_node_by_id:
            _append_unique_segments(added_node_to_segments.setdefault(node_id, []), segment_ids)
    for unit in passed_units:
        unit.added_rcsd_node_ids = unique_preserve_order(
            [
                node_id
                for node_id, segment_ids in added_node_to_segments.items()
                if unit.segment_id in segment_ids
            ]
        )

    junctions = _build_junction_states(
        units=passed_units,
        swsd_segments=swsd_segments,
        swsd_nodes=swsd_nodes,
        removed_node_ids=set(removed_node_to_segments),
        added_node_to_segments=added_node_to_segments,
        added_road_to_segments=added_road_to_segments,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        canonicalizer=canonicalizer,
    )

    frcsd_roads = _build_frcsd_roads(
        swsd_roads=swsd_roads,
        rcsd_roads=rcsd_roads,
        removed_road_ids=set(removed_road_to_segments),
        added_road_ids=set(added_road_to_segments),
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    frcsd_nodes = _build_frcsd_nodes(
        swsd_nodes=swsd_nodes,
        rcsd_nodes=rcsd_nodes,
        removed_node_ids=set(removed_node_to_segments) - _swsd_ep(frcsd_roads, source_field_name, swsd_source_value),
        added_node_ids=set(added_node_to_segments),
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    junction_audit_rows = _apply_junction_rebuild(
        frcsd_nodes,
        junctions=junctions,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    _flatten_node_mainnode_chains(frcsd_nodes, source_field_name=source_field_name)
    attachment_mainnode_sync_stats = _sync_attachment_swsd_mainnodes(
        frcsd_nodes,
        attachment_audit_rows=right_attach_audit_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    generated_endpoint_geometry_sync_stats = _sync_generated_rcsd_endpoint_node_geometries(
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    _close_final_adv(frcsd_roads, frcsd_nodes, adv_closure_stats, passed_units, rcsd_roads, rcsd_road_by_id, added_road_to_segments, added_node_to_segments, source_field_name, rcsd_source_value)
    _stringify_final_road_id_fields(frcsd_roads)

    replacement_unit_rows = [feature(_replacement_unit_row(unit), unit.geometry) for unit in units]
    removed_road_rows = _change_rows(removed_road_to_segments, "road", swsd_source_value, "replaced_swsd_segment")
    removed_node_rows = _change_rows(removed_node_to_segments, "node", swsd_source_value, "removed_swsd_road_endpoint")
    added_road_rows = _change_rows(added_road_to_segments, "road", rcsd_source_value, "retained_rcsd_segment_road")
    added_node_rows = _change_rows(added_node_to_segments, "node", rcsd_source_value, "retained_rcsd_segment_node")
    unreplaced_rcsd_road_rows = _unreplaced_rcsd_road_rows(
        rcsd_roads=rcsd_roads,
        added_road_ids=set(added_road_to_segments),
        source_value=rcsd_source_value,
    )
    collision_rows = _id_collision_rows(
        retained_swsd_road_ids=_feature_id_set(frcsd_roads, source_field_name, swsd_source_value),
        retained_swsd_node_ids=_feature_id_set(frcsd_nodes, source_field_name, swsd_source_value),
        added_rcsd_road_ids=set(added_road_to_segments),
        added_rcsd_node_ids=set(added_node_to_segments),
    )
    segment_relation_rows = _build_swsd_frcsd_segment_relation_rows(
        swsd_segments=swsd_segments,
        units=units,
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    _backfill_missing_relation_node_maps_from_peer_segments(
        segment_relation_rows,
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    relation_node_map_backfill_stats = backfill_relation_node_maps_from_attachment_audit(
        segment_relation_rows,
        right_attach_audit_rows,
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
    )
    retained_carrier_mainnode_sync_stats = sync_retained_swsd_carrier_mainnodes(
        segment_relation_rows,
        frcsd_roads,
        frcsd_nodes,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    gcf_stats = retain_group_coverage_fallback(
        units=units,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=segment_relation_rows,
        advance_right_audit_rows=right_attach_audit_rows,
        removed_road_to_segments=removed_road_to_segments,
        removed_node_to_segments=removed_node_to_segments,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    if gcf_stats["group_path_corridor_coverage_fallback_segment_count"]:
        replacement_unit_rows = [feature(_replacement_unit_row(unit), unit.geometry) for unit in units]
        removed_road_rows = _change_rows(removed_road_to_segments, "road", swsd_source_value, "replaced_swsd_segment")
        removed_node_rows = _change_rows(removed_node_to_segments, "node", swsd_source_value, "removed_swsd_road_endpoint")
        collision_rows = _id_collision_rows(
            retained_swsd_road_ids=_feature_id_set(frcsd_roads, source_field_name, swsd_source_value),
            retained_swsd_node_ids=_feature_id_set(frcsd_nodes, source_field_name, swsd_source_value),
            added_rcsd_road_ids=set(added_road_to_segments),
            added_rcsd_node_ids=set(added_node_to_segments),
        )
    semantic_junction_group_rows, semantic_junction_group_stats = build_semantic_junction_groups(
        step2_replaceable_path=step2_replaceable_path,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=segment_relation_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )

    road_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_ROAD_STEM,
        features=frcsd_roads,
        fieldnames=_fieldnames(frcsd_roads, ["id", source_field_name]),
    )
    node_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        features=frcsd_nodes,
        fieldnames=_fieldnames(frcsd_nodes, ["id", "mainnodeid", source_field_name, SEMANTIC_JUNCTION_GROUP_FIELD]),
    )
    replacement_unit_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_REPLACEMENT_UNITS_STEM,
        features=replacement_unit_rows,
        fieldnames=STEP3_REPLACEMENT_UNIT_FIELDS,
    )
    segment_relation_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
        features=segment_relation_rows,
        fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    )
    semantic_junction_group_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
        features=semantic_junction_group_rows,
        fieldnames=STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    )
    junction_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_JUNCTION_REBUILD_AUDIT_STEM,
        features=junction_audit_rows,
        fieldnames=STEP3_JUNCTION_REBUILD_AUDIT_FIELDS,
    )
    removed_road_paths = write_feature_triplet(step_root=step_root, stem=STEP3_REMOVED_SWSD_ROADS_STEM, features=removed_road_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    removed_node_paths = write_feature_triplet(step_root=step_root, stem=STEP3_REMOVED_SWSD_NODES_STEM, features=removed_node_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    added_road_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ADDED_RCSD_ROADS_STEM, features=added_road_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    added_node_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ADDED_RCSD_NODES_STEM, features=added_node_rows, fieldnames=STEP3_CHANGE_AUDIT_FIELDS)
    unreplaced_rcsd_road_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_UNREPLACED_RCSD_ROADS_STEM,
        features=unreplaced_rcsd_road_rows,
        fieldnames=STEP3_UNREPLACED_RCSD_ROAD_FIELDS,
    )
    collision_paths = write_feature_triplet(step_root=step_root, stem=STEP3_ID_COLLISION_AUDIT_STEM, features=collision_rows, fieldnames=STEP3_ID_COLLISION_AUDIT_FIELDS)
    right_attach_paths = write_feature_triplet(
        step_root=step_root,
        stem=RIGHT_ATTACH_AUDIT_STEM,
        features=right_attach_audit_rows,
        fieldnames=RIGHT_ATTACH_AUDIT_FIELDS,
    )
    adv_closure_paths = write_rcsd_advance_right_closure_audit(step_root, adv_closure_stats["audit_rows"])
    topology_connectivity_audit_rows = build_topology_connectivity_audit_rows(
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=segment_relation_rows,
        advance_right_audit_rows=right_attach_audit_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    semantic_junction_topology_stats = downgrade_semantic_junction_topology_rows(
        topology_connectivity_audit_rows,
        semantic_junction_group_rows,
    )
    topology_connectivity_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        features=topology_connectivity_audit_rows,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    )
    topology_connectivity_summary = summarize_topology_connectivity_audit(topology_connectivity_audit_rows)

    summary_path = step_root / STEP3_SUMMARY
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {
                "step2_replaceable_path": str(step2_replaceable_path),
                "step2_special_junction_group_audit_path": str(special_group_audit_path) if special_group_audit_path is not None else None,
                "step2_group_replacement_audit_path": str(group_replacement_audit_path) if group_replacement_audit_path is not None else None,
                "step2_replacement_plan_path": str(replacement_plan_path) if replacement_plan_path is not None else None,
                "swsd_segment_path": str(swsd_segment_path),
                "swsd_roads_path": str(swsd_roads_path),
                "swsd_nodes_path": str(swsd_nodes_path),
                "rcsdroad_path": str(rcsdroad_path),
                "rcsdnode_path": str(rcsdnode_path),
                "junction_surface_path": str(junction_surface_path) if junction_surface_path is not None else None,
            },
            "params": {
                "source_field_name": source_field_name,
                "rcsd_source_value": rcsd_source_value,
                "swsd_source_value": swsd_source_value,
                "id_collision_policy": "keep_original_ids_and_audit_with_source_field",
                "new_mainnode_selection_priority": ["original_mainnode_if_retained", "remaining_swsd_node_min_id", "added_rcsd_node_min_id"],
            },
            "input_replaceable_count": len(replaceable),
            "input_replacement_plan_count": len(replacement_plan_rows),
            "input_standard_replacement_plan_count": len(standard_plan_rows),
            "replacement_plan_source": "step2_replacement_plan" if replacement_plan_rows else "legacy_step2_artifacts",
            "replacement_unit_count": len(units),
            "replacement_unit_success_count": len(passed_units),
            "replacement_unit_failure_count": len(units) - len(passed_units),
            "group_replacement_audit_input_row_count": group_replacement_stats.input_row_count,
            "group_replacement_passed_row_count": group_replacement_stats.passed_row_count,
            "group_replacement_plan_count": group_replacement_stats.plan_count,
            "group_replacement_assignment_segment_count": group_replacement_stats.assignment_segment_count,
            "group_replacement_created_unit_count": group_replacement_created_unit_count,
            "group_replacement_skipped_row_count": group_replacement_stats.skipped_row_count,
            "detached_junc_retained_segment_count": sum(1 for unit in passed_units if unit.retained_detached_swsd_road_ids),
            "detached_junc_retained_swsd_road_count": sum(len(unit.retained_detached_swsd_road_ids) for unit in passed_units),
            "topology_supplement_retained_segment_count": topology_supplement_stats["affected_segment_count"],
            "topology_supplement_retained_swsd_road_count": topology_supplement_stats["retained_swsd_road_count"],
            "topology_supplement_materialized_candidate_road_count": topology_supplement_materialized_stats[
                "candidate_road_count"
            ],
            "topology_supplement_materialized_rcsd_road_count": topology_supplement_materialized_stats[
                "materialized_road_count"
            ],
            "topology_supplement_materialized_missing_attachment_node_count": topology_supplement_materialized_stats[
                "missing_attachment_node_count"
            ],
            "topology_supplement_formal_body_retained_restored_count": topology_supplement_materialized_stats.get(
                "formal_body_retained_restored_count", 0
            ),
            "removed_swsd_node_preserved_by_retained_road_count": preserved_removed_node_count,
            "removed_swsd_road_count": len(removed_road_to_segments),
            "removed_swsd_node_count": len(removed_node_to_segments),
            "retained_swsd_missing_endpoint_node_generated_count": retained_swsd_endpoint_node_stats[
                "generated_node_count"
            ],
            "added_rcsd_road_count": len(added_road_to_segments),
            "added_rcsd_node_count": len(added_node_to_segments),
            "post_advance_right_attachment_added_road_count": post_advance_right_attachment_stats[
                "added_road_count"
            ],
            "post_advance_right_attachment_component_count": post_advance_right_attachment_stats[
                "component_count"
            ],
            "post_advance_right_attachment_attached_road_count": post_advance_right_attachment_stats[
                "attached_road_count"
            ],
            "post_advance_right_swsd_carrier_retained_road_count": post_advance_right_swsd_carrier_stats[
                "retained_road_count"
            ],
            "post_advance_right_mixed_boundary_component_count": post_advance_right_attachment_stats[
                "mixed_boundary_component_count"
            ],
            "post_advance_right_paired_advance_road_count": post_advance_right_attachment_stats[
                "paired_advance_road_count"
            ],
            "post_advance_right_midroad_split_original_road_count": post_advance_right_attachment_stats[
                "midroad_split_original_road_count"
            ],
            "post_advance_right_midroad_split_road_count": post_advance_right_attachment_stats[
                "midroad_split_road_count"
            ],
            "post_advance_right_midroad_attached_road_count": post_advance_right_attachment_stats[
                "midroad_attached_road_count"
            ],
            "post_advance_right_swsd_carrier_rcsd_split_original_road_count": post_advance_right_attachment_stats[
                "swsd_carrier_split_original_road_count"
            ],
            "post_advance_right_swsd_carrier_rcsd_split_road_count": post_advance_right_attachment_stats[
                "swsd_carrier_split_road_count"
            ],
            "post_advance_right_swsd_carrier_rcsd_generated_node_count": post_advance_right_attachment_stats[
                "swsd_carrier_generated_node_count"
            ],
            "post_advance_right_swsd_carrier_snapped_node_count": post_advance_right_attachment_stats[
                "swsd_carrier_snapped_node_count"
            ],
            "generated_missing_rcsd_endpoint_node_count": generated_endpoint_node_stats["generated_node_count"],
            "rcsd_advance_right_closure_candidate_road_count": adv_closure_stats[
                "candidate_road_count"
            ],
            "rcsd_advance_right_closure_repaired_endpoint_count": adv_closure_stats[
                "repaired_endpoint_count"
            ],
            "rcsd_advance_right_closure_failed_endpoint_count": adv_closure_stats[
                "failed_endpoint_count"
            ],
            "generated_rcsd_endpoint_node_geometry_synced_count": generated_endpoint_geometry_sync_stats[
                "synced_node_count"
            ],
            "generated_rcsd_endpoint_node_geometry_conflict_count": generated_endpoint_geometry_sync_stats[
                "conflict_node_count"
            ],
            "generated_rcsd_endpoint_road_geometry_snapped_count": generated_endpoint_geometry_sync_stats[
                "snapped_road_endpoint_count"
            ],
            "advance_right_contract_candidate_road_count": right_attach_contract_stats["candidate_road_count"],
            "advance_right_contract_retained_candidate_road_count": right_attach_contract_stats[
                "retained_candidate_road_count"
            ],
            "advance_right_contract_swsd_mainnode_normalized_node_count": right_attach_contract_stats[
                "swsd_mainnode_normalized_node_count"
            ],
            "advance_right_contract_swsd_node_snapped_count": right_attach_contract_stats["swsd_node_snapped_count"],
            "advance_right_contract_rcsd_node_generated_count": right_attach_contract_stats["rcsd_node_generated_count"],
            "advance_right_contract_rcsd_split_original_road_count": right_attach_contract_stats[
                "rcsd_split_original_road_count"
            ],
            "advance_right_contract_rcsd_split_road_count": right_attach_contract_stats["rcsd_split_road_count"],
            "advance_right_contract_audit_row_count": len(right_attach_contract_stats["audit_rows"]),
            "advance_right_attachment_swsd_mainnode_synced_count": attachment_mainnode_sync_stats[
                "synced_node_count"
            ],
            "retained_swsd_attachment_candidate_road_count": retained_swsd_attach_contract_stats[
                "candidate_road_count"
            ],
            "retained_swsd_attachment_candidate_endpoint_count": retained_swsd_attach_contract_stats[
                "candidate_endpoint_count"
            ],
            "retained_swsd_attachment_swsd_node_snapped_count": retained_swsd_attach_contract_stats[
                "swsd_node_snapped_count"
            ],
            "retained_swsd_attachment_rcsd_node_generated_count": retained_swsd_attach_contract_stats[
                "rcsd_node_generated_count"
            ],
            "retained_swsd_attachment_rcsd_split_original_road_count": retained_swsd_attach_contract_stats[
                "rcsd_split_original_road_count"
            ],
            "retained_swsd_attachment_rcsd_split_road_count": retained_swsd_attach_contract_stats[
                "rcsd_split_road_count"
            ],
            "retained_swsd_attachment_audit_row_count": len(retained_swsd_attach_contract_stats["audit_rows"]),
            "special_junction_group_consumed_count": len(special_groups),
            "special_junction_added_rcsd_road_count": len(
                {road_id for road_id in special_added_road_to_segments if road_id in rcsd_road_by_id}
            ),
            "special_junction_added_rcsd_node_count": len(
                {node_id for node_id in special_added_node_to_segments if node_id in rcsd_node_by_id}
            ),
            "unreplaced_rcsd_road_count": len(unreplaced_rcsd_road_rows),
            "unreplaced_rcsd_road_length_m": _round_length(sum(_feature_length(row) for row in unreplaced_rcsd_road_rows)),
            "junction_c_count": len(junctions),
            "junction_rebuilt_count": sum(1 for row in junction_audit_rows if row["properties"].get("new_mainnode_id")),
            "mainnode_reselected_count": sum(1 for row in junction_audit_rows if row["properties"].get("original_mainnode_removed")),
            "road_id_collision_count": sum(1 for row in collision_rows if row["properties"].get("entity_type") == "road"),
            "node_id_collision_count": sum(1 for row in collision_rows if row["properties"].get("entity_type") == "node"),
            "frcsd_road_count": len(frcsd_roads),
            "frcsd_node_count": len(frcsd_nodes),
            "segment_relation_count": len(segment_relation_rows),
            "segment_relation_replaced_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "replaced"),
            "segment_relation_retained_swsd_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "retained_swsd"),
            "segment_relation_failed_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "failed"),
            **relation_node_map_backfill_stats,
            **retained_carrier_mainnode_sync_stats,
            **semantic_junction_group_stats,
            **gcf_stats,
            **semantic_junction_topology_stats,
            **topology_connectivity_summary,
            "outputs": {
                **{f"frcsd_road_{key}": str(value) for key, value in road_paths.items()},
                **{f"frcsd_node_{key}": str(value) for key, value in node_paths.items()},
                **{f"replacement_units_{key}": str(value) for key, value in replacement_unit_paths.items()},
                **{f"swsd_frcsd_segment_relation_{key}": str(value) for key, value in segment_relation_paths.items()},
                **{f"semantic_junction_groups_{key}": str(value) for key, value in semantic_junction_group_paths.items()},
                **{f"junction_rebuild_audit_{key}": str(value) for key, value in junction_paths.items()},
                **{f"removed_swsd_roads_{key}": str(value) for key, value in removed_road_paths.items()},
                **{f"removed_swsd_nodes_{key}": str(value) for key, value in removed_node_paths.items()},
                **{f"added_rcsd_roads_{key}": str(value) for key, value in added_road_paths.items()},
                **{f"added_rcsd_nodes_{key}": str(value) for key, value in added_node_paths.items()},
                **{f"unreplaced_rcsd_roads_{key}": str(value) for key, value in unreplaced_rcsd_road_paths.items()},
                **{f"id_collision_audit_{key}": str(value) for key, value in collision_paths.items()},
                **{f"advance_right_attachment_audit_{key}": str(value) for key, value in right_attach_paths.items()},
                **{
                    f"rcsd_advance_right_closure_audit_{key}": str(value)
                    for key, value in adv_closure_paths.items()
                },
                **{f"topology_connectivity_audit_{key}": str(value) for key, value in topology_connectivity_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "copy-on-write; plan groups; junction audit; post-replacement connectivity audit",
                "geometry_semantics": "Step3 consumes Step2 plan",
                "audit_traceability": "plan, units, groups, changes, collisions, junction audit and topology connectivity audit are written",
                "segment_relation_traceability": "relations record road ids, sources and node maps",
                "performance_verifiable": "summary records counts",
            },
        },
    )

    return T06Step3Artifacts(
        run_id=resolved_run_id,
        run_root=run_root,
        step_root=step_root,
        frcsd_road_gpkg_path=road_paths["gpkg"],
        frcsd_node_gpkg_path=node_paths["gpkg"],
        replacement_units_gpkg_path=replacement_unit_paths["gpkg"],
        swsd_frcsd_segment_relation_gpkg_path=segment_relation_paths["gpkg"],
        junction_rebuild_audit_gpkg_path=junction_paths["gpkg"],
        summary_path=summary_path,
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


def _read_replacement_plan_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", []) if isinstance(payload, dict) else []
        return [{"properties": dict(item.get("properties") or {}), "geometry": item.get("geometry")} for item in features]
    return read_features(path)


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
            if _directed_path_missing(direction, path_forward, path_reverse, undirected_connected) or coverage_failed:
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
        max_uncovered_ratio=TOPOLOGY_SUPPLEMENT_MAX_UNCOVERED_RATIO,
        min_uncovered_length_m=TOPOLOGY_SUPPLEMENT_MIN_UNCOVERED_LENGTH_M,
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


def _build_junction_states(
    *,
    units: list[ReplacementUnit],
    swsd_segments: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    removed_node_ids: set[str],
    added_node_to_segments: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, JunctionState]:
    junctions: dict[str, JunctionState] = {}
    for unit in units:
        c_ids = unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes])
        mapped_by_c = _mapped_rcsd_semantic_by_c(unit)
        for c_id in c_ids:
            state = junctions.setdefault(c_id, JunctionState(c_id=c_id))
            if unit.segment_id not in state.replacement_segment_ids:
                state.replacement_segment_ids.append(unit.segment_id)
            state.mapped_rcsd_semantic_ids = unique_preserve_order(
                [
                    *state.mapped_rcsd_semantic_ids,
                    *[canonicalizer.canonicalize(node_id) for node_id in mapped_by_c.get(c_id, [])],
                ]
            )

    replaced_segment_ids = {unit.segment_id for unit in units}
    for segment in swsd_segments:
        segment_id = _feature_id(segment)
        if segment_id in replaced_segment_ids:
            continue
        props = dict(segment.get("properties") or {})
        for c_id in unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))]):
            state = junctions.get(c_id)
            if state is not None and segment_id not in state.retained_segment_ids:
                state.retained_segment_ids.append(segment_id)

    swsd_group_members = _swsd_group_members(swsd_nodes, set(junctions))
    for c_id, state in junctions.items():
        group = swsd_group_members.get(c_id, [])
        state.original_member_node_ids = [_feature_id(item) for item in group]
        state.removed_swsd_node_ids = [node_id for node_id in state.original_member_node_ids if node_id in removed_node_ids]
        state.remaining_swsd_node_ids = [node_id for node_id in state.original_member_node_ids if node_id not in removed_node_ids]
        state.original_main_props = _original_main_props(c_id, group)

    added_node_ids = set(added_node_to_segments)
    for node in rcsd_nodes:
        node_id = _feature_id(node)
        if node_id not in added_node_ids:
            continue
        canonical_id = canonicalizer.canonicalize(node_id)
        segment_ids = set(added_node_to_segments[node_id])
        for state in junctions.values():
            if canonical_id in state.mapped_rcsd_semantic_ids and segment_ids.intersection(state.replacement_segment_ids):
                state.added_rcsd_node_ids.append(node_id)
    for state in junctions.values():
        state.added_rcsd_node_ids = unique_preserve_order(state.added_rcsd_node_ids)
    append_advance_attachment_rcsd_nodes(
        junctions=junctions,
        rcsd_roads=rcsd_roads,
        added_road_to_segments=added_road_to_segments,
        added_node_ids=added_node_ids,
    )
    return junctions


def _apply_junction_rebuild(
    frcsd_nodes: list[dict[str, Any]],
    *,
    junctions: dict[str, JunctionState],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    node_by_key = {(_source_key(item, source_field_name), _feature_id(item)): item for item in frcsd_nodes}
    rows: list[dict[str, Any]] = []
    for state in junctions.values():
        swsd_member_keys = [
            (str(swsd_source_value), node_id)
            for node_id in state.remaining_swsd_node_ids
            if (str(swsd_source_value), node_id) in node_by_key
        ]
        rcsd_member_keys = [
            (str(rcsd_source_value), node_id)
            for node_id in state.added_rcsd_node_ids
            if (str(rcsd_source_value), node_id) in node_by_key
        ]
        advance_attachment_keys = [
            (str(rcsd_source_value), node_id)
            for node_id in state.advance_attachment_rcsd_node_ids
            if (str(rcsd_source_value), node_id) in node_by_key
        ]
        member_keys = [*swsd_member_keys, *rcsd_member_keys, *advance_attachment_keys]
        original_main_key = (str(swsd_source_value), state.c_id)
        original_main_removed = state.c_id in state.removed_swsd_node_ids or original_main_key not in swsd_member_keys
        source_boundary_split = bool(swsd_member_keys and rcsd_member_keys)
        rebuild_keys = swsd_member_keys if source_boundary_split else member_keys
        new_main_id, reason = _choose_new_mainnode_id(state, rebuild_keys, original_main_key)
        if source_boundary_split:
            reason = f"{reason}+source_boundary_split"
        inherited = {field: state.original_main_props.get(field) for field in INHERITED_NODE_FIELDS}
        if new_main_id is not None:
            for key in rebuild_keys:
                props = node_by_key[key]["properties"]
                props["mainnodeid"] = new_main_id
                if key not in advance_attachment_keys:
                    for field, value in inherited.items():
                        props[field] = value
        rows.append(
            feature(
                {
                    "junction_c_id": state.c_id,
                    "replacement_segment_ids": state.replacement_segment_ids,
                    "original_mainnode_id": state.c_id,
                    "original_mainnode_removed": original_main_removed,
                    "new_mainnode_id": new_main_id,
                    "mainnode_selection_reason": reason,
                    "original_member_node_ids": state.original_member_node_ids,
                    "removed_swsd_node_ids": state.removed_swsd_node_ids,
                    "remaining_swsd_node_ids": state.remaining_swsd_node_ids,
                    "added_rcsd_node_ids": state.added_rcsd_node_ids,
                    "advance_attachment_rcsd_node_ids": state.advance_attachment_rcsd_node_ids,
                    "rebuilt_node_ids": [key[1] for key in member_keys],
                    "inherited_kind": inherited.get("kind"),
                    "inherited_grade": inherited.get("grade"),
                    "inherited_kind_2": inherited.get("kind_2"),
                    "inherited_grade_2": inherited.get("grade_2"),
                    "inherited_closed_con": inherited.get("closed_con"),
                },
                None,
            )
        )
    return rows


def _flatten_node_mainnode_chains(nodes: list[dict[str, Any]], *, source_field_name: str) -> None:
    node_by_key, node_by_id = _node_indexes(nodes, source_field_name=source_field_name)
    for node in nodes:
        props = node.get("properties") or {}
        source = _source_key(node, source_field_name)
        node_id = _safe_normalize(props.get("id"))
        mainnode_id = _safe_normalize(props.get("mainnodeid"))
        if not node_id or not mainnode_id or mainnode_id in {"0", node_id}:
            continue
        root_id = _mainnode_root_id(
            mainnode_id,
            source=source,
            node_by_key=node_by_key,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
        )
        if root_id and root_id != mainnode_id:
            props["mainnodeid"] = _coerce_id_value(root_id)


def _sync_attachment_swsd_mainnodes(
    nodes: list[dict[str, Any]],
    *,
    attachment_audit_rows: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> dict[str, int]:
    node_by_key, node_by_id = _node_indexes(nodes, source_field_name=source_field_name)
    swsd_source = str(swsd_source_value)
    rcsd_source = str(rcsd_source_value)
    synced = 0
    for row in attachment_audit_rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        swsd_node_id = _safe_normalize(props.get("swsd_node_id"))
        rcsd_node_id = _safe_normalize(props.get("rcsd_node_id") or props.get("generated_rcsd_node_id"))
        if not swsd_node_id or not rcsd_node_id:
            continue
        swsd_node = node_by_key.get((swsd_source, swsd_node_id))
        rcsd_node = node_by_key.get((rcsd_source, rcsd_node_id))
        if swsd_node is None or rcsd_node is None:
            continue
        swsd_point = swsd_node.get("geometry")
        rcsd_point = rcsd_node.get("geometry")
        if swsd_point is None or rcsd_point is None or swsd_point.distance(rcsd_point) > 1.0:
            continue
        root_id = _mainnode_root_id(
            rcsd_node_id,
            source=rcsd_source,
            node_by_key=node_by_key,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
        )
        if not root_id:
            continue
        swsd_props = swsd_node.get("properties") or {}
        if _safe_normalize(swsd_props.get("mainnodeid")) == root_id:
            continue
        swsd_props["mainnodeid"] = _coerce_id_value(root_id)
        synced += 1
    if synced:
        _flatten_node_mainnode_chains(nodes, source_field_name=source_field_name)
    return {"synced_node_count": synced}


def _sync_generated_rcsd_endpoint_node_geometries(
    *,
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, int]:
    endpoint_refs_by_node: dict[str, list[tuple[dict[str, Any], Point]]] = defaultdict(list)
    rcsd_source = str(rcsd_source_value)
    for road in frcsd_roads:
        if _source_key(road, source_field_name) != rcsd_source:
            continue
        for node_id, point in zip(_road_endpoint_node_id_pair(road), _road_endpoint_points(road)):
            endpoint_refs_by_node[node_id].append((road, point))
    synced = 0
    conflicts = 0
    snapped = 0
    for node in frcsd_nodes:
        if _source_key(node, source_field_name) != rcsd_source:
            continue
        props = node.get("properties") or {}
        if props.get("t06_generated_reason") != "selected_rcsd_road_missing_endpoint_node":
            continue
        node_id = _feature_id(node)
        refs = endpoint_refs_by_node.get(node_id, [])
        points = [point for _road, point in refs]
        if not points:
            continue
        current = node.get("geometry")
        if _max_point_distance(points) > 1.0 and isinstance(current, Point):
            for road, point in refs:
                if point.distance(current) > 1.0 and _snap_final_road_endpoint(road, node_id, current):
                    snapped += 1
            continue
        if _max_point_distance(points) > 1.0:
            conflicts += 1
            continue
        point = points[0]
        if not isinstance(current, Point) or current.distance(point) > 1.0:
            node["geometry"] = point
            synced += 1
    return {
        "synced_node_count": synced,
        "conflict_node_count": conflicts,
        "snapped_road_endpoint_count": snapped,
    }


def _stringify_final_road_id_fields(frcsd_roads: list[dict[str, Any]]) -> None:
    for road in frcsd_roads:
        props = road.get("properties") or {}
        for field_name in ("id", "snodeid", "enodeid", "t06_split_original_road_id"):
            value = props.get(field_name)
            if value not in (None, ""):
                props[field_name] = _safe_normalize(value)


def _max_point_distance(points: list[Point]) -> float:
    if len(points) < 2:
        return 0.0
    first = points[0]
    return max(float(first.distance(point)) for point in points[1:])


def _snap_final_road_endpoint(road: dict[str, Any], node_id: str, point: Point) -> bool:
    geometry = road.get("geometry")
    if geometry is None or geometry.is_empty:
        return False
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if not isinstance(merged, LineString):
            return False
        geometry = merged
    if not isinstance(geometry, LineString):
        return False
    endpoints = _road_endpoint_node_id_pair(road)
    coords = list(geometry.coords)
    changed = False
    if endpoints and endpoints[0] == node_id:
        coords[0] = _coord_with_point(coords[0], point)
        changed = True
    if len(endpoints) > 1 and endpoints[-1] == node_id:
        coords[-1] = _coord_with_point(coords[-1], point)
        changed = True
    if changed:
        road["geometry"] = LineString(coords)
    return changed


def _coord_with_point(coord: tuple[float, ...], point: Point) -> tuple[float, ...]:
    x, y = point.coords[0][:2]
    if len(coord) <= 2:
        return (x, y)
    return (x, y, *coord[2:])


def _node_indexes(
    nodes: list[dict[str, Any]],
    *,
    source_field_name: str,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    node_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    node_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        node_id = _feature_id(node)
        source = _source_key(node, source_field_name)
        node_by_key[(source, node_id)] = node
        node_by_id[node_id].append(node)
    return node_by_key, dict(node_by_id)


def _mainnode_root_id(
    node_id: str,
    *,
    source: str,
    node_by_key: dict[tuple[str, str], dict[str, Any]],
    node_by_id: dict[str, list[dict[str, Any]]],
    source_field_name: str,
) -> str:
    current = node_id
    current_source = source
    seen: set[tuple[str, str]] = set()
    while current and (current_source, current) not in seen:
        seen.add((current_source, current))
        node = node_by_key.get((current_source, current))
        if node is None:
            candidates = node_by_id.get(current, [])
            node = candidates[0] if candidates else None
        if node is None:
            return current
        current_source = _source_key(node, source_field_name)
        props = dict(node.get("properties") or {})
        next_id = _safe_normalize(props.get("mainnodeid"))
        if not next_id or next_id == "0" or next_id == current:
            return current
        current = next_id
    return node_id


def _choose_new_mainnode_id(state: JunctionState, member_keys: list[tuple[str, str]], original_main_key: tuple[str, str]) -> tuple[str | None, str]:
    if original_main_key in member_keys:
        return state.c_id, "original_mainnode_retained"
    remaining = sorted(state.remaining_swsd_node_ids, key=_id_sort_key)
    for node_id in remaining:
        if any(key[1] == node_id for key in member_keys):
            return node_id, "remaining_swsd_node_min_id"
    added = sorted(state.added_rcsd_node_ids, key=_id_sort_key)
    for node_id in added:
        if any(key[1] == node_id for key in member_keys):
            return node_id, "added_rcsd_node_min_id"
    return None, "no_nodes_to_rebuild"


def _build_frcsd_roads(
    *,
    swsd_roads: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    removed_road_ids: set[str],
    added_road_ids: set[str],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    adv_geometries = [
        road.get("geometry")
        for road in rcsd_roads
        if _feature_id(road) in added_road_ids and _is_advance_right_rcsd_road(road)
    ]
    for road in swsd_roads:
        if _feature_id(road) not in removed_road_ids and not _is_adv_dup(dict(road.get("properties") or {}), road.get("geometry"), adv_geometries):
            rows.append(_with_source(road, source_field_name, swsd_source_value))
    for road in rcsd_roads:
        if _feature_id(road) in added_road_ids:
            rows.append(_with_source(road, source_field_name, rcsd_source_value))
    return rows


def _retained_swsd_endpoint_node_ids(*, swsd_roads: list[dict[str, Any]], removed_road_ids: set[str]) -> set[str]:
    retained: set[str] = set()
    for road in swsd_roads:
        if _feature_id(road) in removed_road_ids:
            continue
        retained.update(_road_endpoint_node_ids(road))
    return retained


def _build_frcsd_nodes(
    *,
    swsd_nodes: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    removed_node_ids: set[str],
    added_node_ids: set[str],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in swsd_nodes:
        if _feature_id(node) not in removed_node_ids:
            rows.append(_with_source(node, source_field_name, swsd_source_value))
    for node in rcsd_nodes:
        if _feature_id(node) in added_node_ids:
            rows.append(_with_source(node, source_field_name, rcsd_source_value))
    return rows


def _build_swsd_frcsd_segment_relation_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    units: list[ReplacementUnit],
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    unit_by_segment = {
        unit.segment_id: unit
        for unit in units
        if unit.reason not in {MIXED_REPLACEMENT_REQUIRES_SWSD_CARRIER_REASON, FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON}
    }
    frcsd_road_by_source_id = {(_source_key(road, source_field_name), _feature_id(road)): road for road in frcsd_roads}
    retained_by_segment = _retained_swsd_roads_by_segment(
        frcsd_roads=frcsd_roads,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
    )
    rows: list[dict[str, Any]] = []
    for segment in swsd_segments:
        segment_id = _feature_id(segment)
        props = dict(segment.get("properties") or {})
        pair_nodes = _parse_list(props.get("pair_nodes"))
        junc_nodes = _parse_list(props.get("junc_nodes"))
        swsd_road_ids = _parse_list(props.get("roads"))
        unit = unit_by_segment.get(segment_id)
        if unit is not None:
            pair_nodes = unit.pair_nodes or pair_nodes
            junc_nodes = unit.junc_nodes or junc_nodes
        relation_status = "failed"
        relation_reason = "missing_frcsd_carrier_roads"
        removed_swsd_road_ids: list[str] = []
        frcsd_road_ids: list[str] = []
        frcsd_road_source_values: list[int] = []
        rcsd_pair_nodes: list[str] = []
        rcsd_junc_nodes: list[str] = []
        node_map: list[dict[str, Any]] = []
        risk_flags: list[str] = []
        retained_swsd_road_ids: list[str] = []
        if unit is not None:
            risk_flags.extend(unit.risk_flags)

        if unit is not None and unit.status == "passed":
            removed_swsd_road_ids = unit.swsd_road_ids
            rcsd_pair_nodes = unit.rcsd_pair_nodes
            rcsd_junc_nodes = unit.rcsd_junc_nodes
            present_rcsd_road_ids = [
                road_id
                for road_id in unit.rcsd_road_ids
                if (str(rcsd_source_value), road_id) in frcsd_road_by_source_id
            ]
            missing_rcsd_road_ids = [road_id for road_id in unit.rcsd_road_ids if road_id not in present_rcsd_road_ids]
            retained_swsd_road_ids = [
                road_id
                for road_id in unit.retained_detached_swsd_road_ids
                if (str(swsd_source_value), road_id) in frcsd_road_by_source_id
            ]
            frcsd_road_ids = unique_preserve_order(present_rcsd_road_ids)
            frcsd_road_source_values = []
            if present_rcsd_road_ids:
                frcsd_road_source_values.append(rcsd_source_value)
            if present_rcsd_road_ids and retained_swsd_road_ids:
                relation_status = "replaced+retained_swsd"
                relation_reason = "replacement_unit_passed_with_retained_swsd_topology_supplement"
                risk_flags.append("retained_swsd_topology_supplement")
                risk_flags.append("retained_swsd_excluded_from_formal_replacement")
            else:
                relation_status = "replaced" if present_rcsd_road_ids else "failed"
                relation_reason = "replacement_unit_passed" if present_rcsd_road_ids else "replacement_roads_missing_in_frcsd"
            if missing_rcsd_road_ids:
                risk_flags.append("missing_replacement_frcsd_roads")
            if unit.group_replacement_plan_ids:
                relation_reason = "group_path_corridor_replacement"
                risk_flags.append("group_path_corridor_replacement")
            node_map = _segment_node_map(
                swsd_pair_nodes=unit.pair_nodes,
                swsd_junc_nodes=unit.junc_nodes,
                junc_kind2_exempt_nodes=unit.junc_kind2_exempt_nodes,
                mapped_by_swsd_node=_mapped_rcsd_semantic_by_c(unit),
                identity=False,
            )
            if retained_swsd_road_ids:
                node_map.extend(_detached_junc_identity_node_map(unit.detached_junc_nodes))
        elif unit is not None:
            relation_reason = unit.reason
            risk_flags.append("replacement_unit_failed")
            node_map = _segment_node_map(
                swsd_pair_nodes=pair_nodes,
                swsd_junc_nodes=junc_nodes,
                junc_kind2_exempt_nodes=unit.junc_kind2_exempt_nodes,
                mapped_by_swsd_node={},
                identity=False,
            )
        else:
            retained_ids = _retained_swsd_road_ids_for_segment(
                segment_id=segment_id,
                swsd_road_ids=swsd_road_ids,
                retained_by_segment=retained_by_segment,
                frcsd_road_by_source_id=frcsd_road_by_source_id,
                swsd_source_value=swsd_source_value,
            )
            frcsd_road_ids = retained_ids
            frcsd_road_source_values = [swsd_source_value] if retained_ids else []
            relation_status = "retained_swsd" if retained_ids else "failed"
            relation_reason = "retained_swsd_segment" if retained_ids else "retained_swsd_roads_missing_in_frcsd"
            if not retained_ids:
                risk_flags.append("missing_retained_swsd_frcsd_roads")
            node_map = _segment_node_map(
                swsd_pair_nodes=pair_nodes,
                swsd_junc_nodes=junc_nodes,
                junc_kind2_exempt_nodes=_parse_list(props.get("junc_kind2_exempt_nodes")),
                mapped_by_swsd_node={},
                identity=True,
            )

        source_values = unique_preserve_order([str(value) for value in frcsd_road_source_values])
        rows.append(
            feature(
                {
                    "swsd_segment_id": segment_id,
                    "relation_status": relation_status,
                    "relation_reason": relation_reason,
                    "swsd_pair_nodes": pair_nodes,
                    "swsd_junc_nodes": junc_nodes,
                    "junc_kind2_exempt_nodes": (unit.junc_kind2_exempt_nodes if unit is not None else _parse_list(props.get("junc_kind2_exempt_nodes"))),
                    "detached_junc_nodes": (unit.detached_junc_nodes if unit is not None else []),
                    "swsd_road_ids": swsd_road_ids,
                    "removed_swsd_road_ids": removed_swsd_road_ids,
                    "retained_detached_swsd_road_ids": retained_swsd_road_ids,
                    "frcsd_road_ids": frcsd_road_ids,
                    "frcsd_road_source_values": frcsd_road_source_values,
                    "rcsd_pair_nodes": rcsd_pair_nodes,
                    "rcsd_junc_nodes": rcsd_junc_nodes,
                    "junction_c_ids": unique_preserve_order([*pair_nodes, *junc_nodes]),
                    "group_replacement_plan_ids": (unit.group_replacement_plan_ids if unit is not None else []),
                    "group_replacement_source_segment_ids": (unit.group_replacement_source_segment_ids if unit is not None else []),
                    "group_replacement_segment_ids": (unit.group_replacement_segment_ids if unit is not None else []),
                    "swsd_to_frcsd_node_map": node_map,
                    "source_mix": "+".join(f"source_{value}" for value in source_values),
                    "risk_flags": unique_preserve_order(risk_flags),
                },
                segment.get("geometry"),
            )
        )
    return rows


def _retained_swsd_roads_by_segment(
    *,
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in frcsd_roads:
        if _source_key(road, source_field_name) != str(swsd_source_value):
            continue
        props = dict(road.get("properties") or {})
        road_id = _feature_id(road)
        for segment_id in _parse_list(props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id")):
            result[segment_id].append(road_id)
    return {segment_id: unique_preserve_order(road_ids) for segment_id, road_ids in result.items()}


def _retained_swsd_road_ids_for_segment(
    *,
    segment_id: str,
    swsd_road_ids: list[str],
    retained_by_segment: dict[str, list[str]],
    frcsd_road_by_source_id: dict[tuple[str, str], dict[str, Any]],
    swsd_source_value: int,
) -> list[str]:
    retained_ids = list(retained_by_segment.get(segment_id, []))
    for road_id in swsd_road_ids:
        if (str(swsd_source_value), road_id) in frcsd_road_by_source_id and road_id not in retained_ids:
            retained_ids.append(road_id)
    return retained_ids


def _backfill_missing_relation_node_maps_from_peer_segments(
    rows: list[dict[str, Any]],
    *,
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> None:
    mapped_rcsd_nodes_by_swsd_node: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        for entry in props.get("swsd_to_frcsd_node_map") or []:
            if not isinstance(entry, dict):
                continue
            mapping_status = str(entry.get("mapping_status") or "")
            if mapping_status == "missing" or mapping_status.startswith("identity"):
                continue
            swsd_node_id = str(entry.get("swsd_node_id") or "")
            if not swsd_node_id:
                continue
            for node_id in _parse_list(entry.get("frcsd_node_ids")):
                mapped_rcsd_nodes_by_swsd_node[swsd_node_id] = unique_preserve_order(
                    [*mapped_rcsd_nodes_by_swsd_node[swsd_node_id], node_id]
                )
    if not mapped_rcsd_nodes_by_swsd_node:
        return

    road_endpoint_nodes = {
        _feature_id(road): set(_road_endpoint_node_ids(road))
        for road in frcsd_roads
        if _source_key(road, source_field_name) == str(rcsd_source_value)
    }
    for row in rows:
        props = row.get("properties") or {}
        node_map = props.get("swsd_to_frcsd_node_map") or []
        if not isinstance(node_map, list):
            continue
        selected_endpoint_nodes: set[str] = set()
        for road_id in _parse_list(props.get("frcsd_road_ids")):
            selected_endpoint_nodes.update(road_endpoint_nodes.get(road_id, set()))
        if not selected_endpoint_nodes:
            continue
        backfilled = False
        for entry in node_map:
            if not isinstance(entry, dict) or str(entry.get("mapping_status") or "") != "missing":
                continue
            swsd_node_id = str(entry.get("swsd_node_id") or "")
            candidates = [
                node_id
                for node_id in mapped_rcsd_nodes_by_swsd_node.get(swsd_node_id, [])
                if node_id in selected_endpoint_nodes
            ]
            if not candidates:
                continue
            entry["frcsd_node_ids"] = unique_preserve_order(candidates)
            entry["mapping_status"] = "peer_mapped"
            backfilled = True
        if backfilled:
            props["risk_flags"] = unique_preserve_order(
                [*_parse_list(props.get("risk_flags")), "peer_backfilled_junc_node_map"]
            )


def _segment_node_map(
    *,
    swsd_pair_nodes: list[str],
    swsd_junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    mapped_by_swsd_node: dict[str, list[str]],
    identity: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exempt_nodes = set(junc_kind2_exempt_nodes)
    node_roles = [(node_id, "pair_node") for node_id in swsd_pair_nodes] + [
        (node_id, "junc_kind2_exempt_node" if node_id in exempt_nodes else "junc_node")
        for node_id in swsd_junc_nodes
    ]
    for swsd_node_id, node_role in node_roles:
        frcsd_node_ids = [swsd_node_id] if identity else mapped_by_swsd_node.get(swsd_node_id, [])
        rows.append(
            {
                "swsd_node_id": swsd_node_id,
                "frcsd_node_ids": frcsd_node_ids,
                "node_role": node_role,
                "mapping_status": "identity" if identity else ("mapped" if frcsd_node_ids else "missing"),
            }
        )
    return rows


def _detached_junc_identity_node_map(detached_junc_nodes: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "swsd_node_id": node_id,
            "frcsd_node_ids": [node_id],
            "node_role": "detached_junc_retained_swsd_node",
            "mapping_status": "identity_retained_swsd",
        }
        for node_id in detached_junc_nodes
    ]


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


def _selected_rcsd_semantic_ids(units: list[ReplacementUnit]) -> set[str]:
    selected: set[str] = set()
    for unit in units:
        selected.update(unit.retained_node_ids)
        selected.update(unit.rcsd_pair_nodes)
        selected.update(unit.rcsd_junc_nodes)
        selected.update(unit.optional_allowed_rcsd_nodes)
    return selected


def _selected_rcsd_raw_node_ids(added_road_to_segments: dict[str, list[str]], rcsd_road_by_id: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for road_id in added_road_to_segments:
        road = rcsd_road_by_id.get(road_id)
        if road is not None:
            result.update(_road_endpoint_node_ids(road))
    return result


def _select_added_rcsd_nodes(
    *,
    rcsd_nodes: list[dict[str, Any]],
    selected_raw_node_ids: set[str],
    selected_semantic_node_ids: set[str],
    canonicalizer: NodeCanonicalizer,
    units: list[ReplacementUnit],
) -> dict[str, list[str]]:
    semantic_to_segments: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        for semantic_id in unique_preserve_order([*unit.retained_node_ids, *unit.rcsd_pair_nodes, *unit.rcsd_junc_nodes, *unit.optional_allowed_rcsd_nodes]):
            semantic_to_segments[semantic_id].append(unit.segment_id)
    result: dict[str, list[str]] = {}
    for node in rcsd_nodes:
        node_id = _feature_id(node)
        canonical_id = canonicalizer.canonicalize(node_id)
        if node_id not in selected_raw_node_ids and canonical_id not in selected_semantic_node_ids:
            continue
        segment_ids = semantic_to_segments.get(canonical_id, [])
        if not segment_ids:
            segment_ids = [unit.segment_id for unit in units if node_id in unit.retained_node_ids]
        result[node_id] = unique_preserve_order(segment_ids)
    return result


def _swsd_group_members(swsd_nodes: list[dict[str, Any]], c_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in swsd_nodes:
        props = dict(node.get("properties") or {})
        node_id = _feature_id(node)
        semantic_ids = {node_id}
        mainnodeid = parse_positive_int(props.get("mainnodeid"))
        if mainnodeid is not None:
            semantic_ids.add(str(mainnodeid))
        for c_id in semantic_ids.intersection(c_ids):
            groups[c_id].append(node)
    return groups


def _original_main_props(c_id: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    for node in group:
        if _feature_id(node) == c_id:
            return dict(node.get("properties") or {})
    return dict((group[0].get("properties") or {}) if group else {})


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)


def _road_endpoint_node_id_pair(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return result


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    geometry = road.get("geometry")
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            geometry = merged
        else:
            geometry = max(geometry.geoms, key=lambda item: item.length)
    if not isinstance(geometry, LineString):
        return []
    coords = list(geometry.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _index_by_id(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        try:
            result.setdefault(_feature_id(item), item)
        except ParseError:
            continue
    return result


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _safe_normalize(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)


def _coerce_id_value(node_id: str) -> Any:
    return int(node_id) if node_id.isdigit() else node_id


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _with_source(item: dict[str, Any], source_field_name: str, source_value: int) -> dict[str, Any]:
    props = dict(item.get("properties") or {})
    props[source_field_name] = source_value
    return feature(props, item.get("geometry"))


def _source_key(item: dict[str, Any], source_field_name: str) -> str:
    return str((item.get("properties") or {}).get(source_field_name))


def _replacement_unit_row(unit: ReplacementUnit) -> dict[str, Any]:
    return {
        "swsd_segment_id": unit.segment_id,
        "unit_status": unit.status,
        "unit_reason": unit.reason,
        "swsd_pair_nodes": unit.pair_nodes,
        "swsd_junc_nodes": unit.junc_nodes,
        "junc_kind2_exempt_nodes": unit.junc_kind2_exempt_nodes,
        "detached_junc_nodes": unit.detached_junc_nodes,
        "retained_detached_swsd_road_ids": unit.retained_detached_swsd_road_ids,
        "swsd_road_ids": unit.original_swsd_road_ids,
        "removed_swsd_road_ids": unit.swsd_road_ids if unit.status == "passed" else [],
        "removed_swsd_node_ids": unit.removed_swsd_node_ids,
        "rcsd_road_ids": unit.rcsd_road_ids,
        "rcsd_node_ids": unit.added_rcsd_node_ids,
        "rcsd_pair_nodes": unit.rcsd_pair_nodes,
        "rcsd_junc_nodes": unit.rcsd_junc_nodes,
        "junction_c_ids": unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes]),
        "group_replacement_plan_ids": unit.group_replacement_plan_ids,
        "group_replacement_source_segment_ids": unit.group_replacement_source_segment_ids,
        "group_replacement_segment_ids": unit.group_replacement_segment_ids,
        "group_replacement_buffer_distances_m": unit.group_replacement_buffer_distances_m,
    }


def _feature_length(feature_item: dict[str, Any]) -> float:
    geometry = feature_item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


def _id_sort_key(value: str) -> tuple[int, int | str]:
    parsed = parse_positive_int(value)
    if parsed is not None:
        return (0, parsed)
    return (1, value)
