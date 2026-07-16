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

from .step3_validation_publish import (
    are_step3_auxiliary_audits_deferred,
    expected_feature_triplet_paths,
    is_validation_step3_run,
    is_step3_initial_topology_audit_deferred,
    select_step3_publish_jobs,
)

from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order

from .road_attributes import is_near_advance_right_turn_duplicate as _is_adv_dup
from .rcsd_road_ownership import (
    build_and_write_rcsd_road_ownership,
    reconcile_final_road_segment_assignments,
    sync_segment_relation_ownership_fields,
)
from .segment_construction_audit import (
    apply_side_road_only_replacement_gate,
    build_and_write_segment_construction_audit,
)

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

from .step3_replacement_unit_support import (
    _UnitRoadGraph,
    _append_unique_segments,
    _attachment_rcsd_nodes_by_swsd_node,
    _build_replacement_units,
    _coerce_int,
    _compute_removed_swsd_maps,
    _directed_path_missing,
    _mapped_rcsd_semantic_by_c,
    _mapped_unit_rcsd_nodes,
    _peer_mapped_rcsd_nodes_by_swsd_node,
    _reachable_any,
    _read_passed_special_junction_groups,
    _read_passed_special_junction_groups_from_plan_rows,
    _replacement_plan_standard_rows,
    _replacement_unit_from_segment,
    _resolve_group_replacement_audit_path,
    _resolve_replacement_plan_path,
    _resolve_special_junction_group_audit_path,
    _retain_topology_supplement_swsd_roads,
    _retained_swsd_endpoint_node_ids,
    _road_corridor_coverage_failed,
    _road_union_corridor,
    _special_group_entity_segments,
)

from .step3_replacement_relation_support import (
    _apply_junction_rebuild,
    _backfill_missing_relation_node_maps_from_peer_segments,
    _build_frcsd_nodes,
    _build_frcsd_roads,
    _build_junction_states,
    _build_swsd_frcsd_segment_relation_rows,
    _choose_new_mainnode_id,
    _coord_with_point,
    _detached_junc_identity_node_map,
    _flatten_node_mainnode_chains,
    _mainnode_root_id,
    _max_point_distance,
    _node_indexes,
    _original_main_props,
    _retained_swsd_road_ids_for_segment,
    _retained_swsd_roads_by_segment,
    _segment_node_map,
    _select_added_rcsd_nodes,
    _selected_rcsd_raw_node_ids,
    _selected_rcsd_semantic_ids,
    _snap_final_road_endpoint,
    _stringify_final_road_id_fields,
    _swsd_group_members,
    _sync_attachment_swsd_mainnodes,
    _sync_generated_rcsd_endpoint_node_geometries,
)
from .step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    publish_step3_surface_runtime_state,
)

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
    special_junction_ids_by_road: dict[str, list[str]] = defaultdict(list)
    for group in special_groups:
        for road_id in group.rcsd_junction_road_ids:
            if group.special_junction_id not in special_junction_ids_by_road[road_id]:
                special_junction_ids_by_road[road_id].append(group.special_junction_id)
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
    special_internal_stats = _apply_sji(
        special_groups, passed_unit_ids, swsd_roads, swsd_nodes, removed_road_to_segments, removed_node_to_segments, added_road_to_segments
    )

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
    side_road_only_gate_stats = apply_side_road_only_replacement_gate(
        units=passed_units,
        segment_by_id=segment_by_id,
        swsd_road_by_id=swsd_road_by_id,
        swsd_nodes=swsd_nodes,
        added_road_to_segments=added_road_to_segments,
    )
    if side_road_only_gate_stats["blocked_non_side_segment_count"]:
        passed_units = [unit for unit in passed_units if unit.status == "passed"]
    passed_unit_ids = {unit.segment_id for unit in passed_units}
    if (
        topology_supplement_materialized_stats["materialized_road_count"]
        or topology_supplement_materialized_stats.get("reused_existing_rcsd_advance_count")
        or topology_supplement_materialized_stats.get("formal_body_retained_restored_count")
        or retained_swsd_excluded_stats["deactivated_segment_count"]
        or side_road_only_gate_stats["blocked_non_side_segment_count"]
    ):
        removed_road_to_segments, removed_node_to_segments, preserved_removed_node_count = _compute_removed_swsd_maps(
            passed_units,
            swsd_roads=swsd_roads,
            swsd_road_by_id=swsd_road_by_id,
        )
        removed_road_to_segments.update(retained_swsd_excluded_stats.get("extra_removed_road_to_segments", {}))
        special_internal_stats = _apply_sji(
            special_groups, passed_unit_ids, swsd_roads, swsd_nodes, removed_road_to_segments, removed_node_to_segments, added_road_to_segments
        )
    retained_swsd_roads = [road for road in swsd_roads if _feature_id(road) not in removed_road_to_segments]
    added_road_ids_before_connectivity_fallback = set(added_road_to_segments)
    second_degree_bridge_stats = apply_unreplaced_second_degree_bridge_fallback(
        passed_units,
        rcsd_roads=rcsd_roads,
        canonicalizer=canonicalizer,
        added_road_to_segments=added_road_to_segments,
        replacement_plan_rows=replacement_plan_rows,
    )
    connectivity_supplement_road_ids = (
        set(added_road_to_segments) - added_road_ids_before_connectivity_fallback
    )
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
    s2n = defaultdict(list)
    for nid, sids in added_node_to_segments.items():
        for sid in sids:
            s2n[str(sid)].append(nid)
    for unit in passed_units:
        unit.added_rcsd_node_ids = unique_preserve_order(s2n.get(unit.segment_id, []))

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
    final_attachment_mainnode_sync_stats = _sync_attachment_swsd_mainnodes(
        frcsd_nodes,
        attachment_audit_rows=right_attach_audit_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    attachment_mainnode_sync_stats["synced_node_count"] += final_attachment_mainnode_sync_stats[
        "synced_node_count"
    ]
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
    added_node_rows = _change_rows(added_node_to_segments, "node", rcsd_source_value, "retained_rcsd_segment_node")
    unreplaced_rcsd_road_rows = _unreplaced_rcsd_road_rows(
        rcsd_roads=rcsd_roads,
        added_road_ids=set(added_road_to_segments),
        source_value=rcsd_source_value,
    )
    semantic_junction_group_rows, semantic_junction_group_stats = build_semantic_junction_groups(
        step2_replaceable_path=step2_replaceable_path,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=segment_relation_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    validation_only = is_validation_step3_run()
    defer_auxiliary_audits = validation_only or are_step3_auxiliary_audits_deferred()
    ownership_summary: dict[str, Any] = {}
    final_assignment_stats: dict[str, Any] = {}
    construction_audit_summary: dict[str, Any] = {}
    ownership_paths: dict[str, Path] = {}
    connectivity_group_paths: dict[str, Path] = {}
    construction_audit_paths: dict[str, Path] = {}
    if not defer_auxiliary_audits:
        ownership_outputs = build_and_write_rcsd_road_ownership(
            step_root=step_root,
            rcsd_roads=rcsd_roads,
            frcsd_roads=frcsd_roads,
            swsd_segments=swsd_segments,
            added_road_to_segments=added_road_to_segments,
            connectivity_supplement_road_ids=connectivity_supplement_road_ids,
            special_junction_ids_by_road=special_junction_ids_by_road,
            canonicalizer=canonicalizer,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        sync_segment_relation_ownership_fields(
            segment_relation_rows,
            ownership_rows=ownership_outputs.ownership_rows,
            connectivity_group_rows=ownership_outputs.connectivity_group_rows,
        )
        final_assignment_stats = reconcile_final_road_segment_assignments(
            frcsd_roads=frcsd_roads,
            added_road_to_segments=added_road_to_segments,
            ownership_rows=ownership_outputs.ownership_rows,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        construction_audit_outputs = build_and_write_segment_construction_audit(
            step_root=step_root,
            swsd_segments=swsd_segments,
            swsd_roads=swsd_roads,
            swsd_nodes=swsd_nodes,
            step1_rejected_rows=(
                read_features(run_root / "step1_identify_fusion_units" / "t06_swsd_segment_rejected.gpkg")
                if (run_root / "step1_identify_fusion_units" / "t06_swsd_segment_rejected.gpkg").is_file()
                else []
            ),
            step2_replaceable_rows=replaceable,
            step2_rejected_rows=(
                read_features(run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_rejected.gpkg")
                if (run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_rejected.gpkg").is_file()
                else []
            ),
            segment_relation_rows=segment_relation_rows,
        )
        ownership_summary = ownership_outputs.summary
        construction_audit_summary = construction_audit_outputs.summary
        ownership_paths = ownership_outputs.ownership_paths
        connectivity_group_paths = ownership_outputs.connectivity_group_paths
        construction_audit_paths = construction_audit_outputs.paths
    added_road_rows = _change_rows(
        added_road_to_segments,
        "road",
        rcsd_source_value,
        "retained_rcsd_segment_road",
    )

    all_publish_jobs = {
        "road": FeatureTripletJob(STEP3_FRCSD_ROAD_STEM, frcsd_roads, _fieldnames(frcsd_roads, ["id", source_field_name])),
        "node": FeatureTripletJob(STEP3_FRCSD_NODE_STEM, frcsd_nodes, _fieldnames(frcsd_nodes, ["id", "mainnodeid", source_field_name, SEMANTIC_JUNCTION_GROUP_FIELD])),
        "replacement_unit": FeatureTripletJob(STEP3_REPLACEMENT_UNITS_STEM, replacement_unit_rows, STEP3_REPLACEMENT_UNIT_FIELDS),
        "segment_relation": FeatureTripletJob(STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM, segment_relation_rows, STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS),
        "semantic_junction_group": FeatureTripletJob(STEP3_SEMANTIC_JUNCTION_GROUPS_STEM, semantic_junction_group_rows, STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS),
        "junction": FeatureTripletJob(STEP3_JUNCTION_REBUILD_AUDIT_STEM, junction_audit_rows, STEP3_JUNCTION_REBUILD_AUDIT_FIELDS),
        "removed_road": FeatureTripletJob(STEP3_REMOVED_SWSD_ROADS_STEM, removed_road_rows, STEP3_CHANGE_AUDIT_FIELDS),
        "removed_node": FeatureTripletJob(STEP3_REMOVED_SWSD_NODES_STEM, removed_node_rows, STEP3_CHANGE_AUDIT_FIELDS),
        "added_road": FeatureTripletJob(STEP3_ADDED_RCSD_ROADS_STEM, added_road_rows, STEP3_CHANGE_AUDIT_FIELDS),
        "added_node": FeatureTripletJob(STEP3_ADDED_RCSD_NODES_STEM, added_node_rows, STEP3_CHANGE_AUDIT_FIELDS),
        "unreplaced_rcsd_road": FeatureTripletJob(STEP3_UNREPLACED_RCSD_ROADS_STEM, unreplaced_rcsd_road_rows, STEP3_UNREPLACED_RCSD_ROAD_FIELDS),
        "collision": FeatureTripletJob(STEP3_ID_COLLISION_AUDIT_STEM, collision_rows, STEP3_ID_COLLISION_AUDIT_FIELDS),
        "right_attach": FeatureTripletJob(RIGHT_ATTACH_AUDIT_STEM, right_attach_audit_rows, RIGHT_ATTACH_AUDIT_FIELDS),
        "advance_right_closure": FeatureTripletJob(RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM, adv_closure_stats["audit_rows"], RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_FIELDS),
    }
    published_paths = publish_feature_triplets(
        step_root=step_root,
        jobs=select_step3_publish_jobs(all_publish_jobs),
    )
    road_paths = published_paths.get(
        "road",
        expected_feature_triplet_paths(step_root, STEP3_FRCSD_ROAD_STEM),
    )
    node_paths = published_paths.get(
        "node",
        expected_feature_triplet_paths(step_root, STEP3_FRCSD_NODE_STEM),
    )
    replacement_unit_paths = published_paths.get(
        "replacement_unit",
        expected_feature_triplet_paths(step_root, STEP3_REPLACEMENT_UNITS_STEM),
    )
    segment_relation_paths = published_paths.get(
        "segment_relation",
        expected_feature_triplet_paths(step_root, STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM),
    )
    semantic_junction_group_paths = published_paths.get(
        "semantic_junction_group",
        expected_feature_triplet_paths(step_root, STEP3_SEMANTIC_JUNCTION_GROUPS_STEM),
    )
    junction_paths = published_paths.get(
        "junction",
        expected_feature_triplet_paths(step_root, STEP3_JUNCTION_REBUILD_AUDIT_STEM),
    )
    removed_road_paths = published_paths.get(
        "removed_road",
        expected_feature_triplet_paths(step_root, STEP3_REMOVED_SWSD_ROADS_STEM),
    )
    removed_node_paths = published_paths.get(
        "removed_node",
        expected_feature_triplet_paths(step_root, STEP3_REMOVED_SWSD_NODES_STEM),
    )
    added_road_paths = published_paths.get(
        "added_road",
        expected_feature_triplet_paths(step_root, STEP3_ADDED_RCSD_ROADS_STEM),
    )
    added_node_paths = published_paths.get(
        "added_node",
        expected_feature_triplet_paths(step_root, STEP3_ADDED_RCSD_NODES_STEM),
    )
    unreplaced_rcsd_road_paths = published_paths.get(
        "unreplaced_rcsd_road",
        expected_feature_triplet_paths(step_root, STEP3_UNREPLACED_RCSD_ROADS_STEM),
    )
    collision_paths = published_paths.get(
        "collision",
        expected_feature_triplet_paths(step_root, STEP3_ID_COLLISION_AUDIT_STEM),
    )
    right_attach_paths = published_paths.get(
        "right_attach",
        expected_feature_triplet_paths(step_root, RIGHT_ATTACH_AUDIT_STEM),
    )
    adv_closure_paths = published_paths.get(
        "advance_right_closure",
        expected_feature_triplet_paths(step_root, RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM),
    )

    if is_step3_initial_topology_audit_deferred():
        semantic_junction_topology_stats = {}
        topology_connectivity_paths = expected_feature_triplet_paths(
            step_root,
            STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        )
        topology_connectivity_summary = {}
    else:
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
        topology_connectivity_paths = publish_feature_triplets(
            step_root=step_root,
            jobs={
                "topology_connectivity": FeatureTripletJob(
                    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
                    topology_connectivity_audit_rows,
                    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
                ),
            },
        )["topology_connectivity"]
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
            "topology_supplement_materialized_candidate_road_count": topology_supplement_materialized_stats["candidate_road_count"],
            "topology_supplement_materialized_rcsd_road_count": topology_supplement_materialized_stats["materialized_road_count"],
            "topology_supplement_materialized_missing_attachment_node_count": topology_supplement_materialized_stats["missing_attachment_node_count"],
            "topology_supplement_formal_body_retained_restored_count": topology_supplement_materialized_stats.get("formal_body_retained_restored_count", 0),
            "side_road_only_gate_candidate_mixed_segment_count": side_road_only_gate_stats["candidate_mixed_segment_count"],
            "side_road_only_gate_allowed_segment_count": side_road_only_gate_stats["allowed_side_road_only_segment_count"],
            "side_road_only_gate_blocked_segment_count": side_road_only_gate_stats["blocked_non_side_segment_count"],
            "side_road_only_gate_blocked_segment_ids": side_road_only_gate_stats["blocked_segment_ids"],
            "external_retained_swsd_carrier_segment_count": side_road_only_gate_stats["external_carrier_segment_count"],
            "external_retained_swsd_carrier_road_count": side_road_only_gate_stats["external_carrier_road_count"],
            "removed_swsd_node_preserved_by_retained_road_count": preserved_removed_node_count,
            "removed_swsd_road_count": len(removed_road_to_segments),
            "removed_swsd_node_count": len(removed_node_to_segments),
            "retained_swsd_missing_endpoint_node_generated_count": retained_swsd_endpoint_node_stats["generated_node_count"],
            "added_rcsd_road_count": len(added_road_to_segments),
            "added_rcsd_node_count": len(added_node_to_segments),
            "post_advance_right_attachment_added_road_count": post_advance_right_attachment_stats["added_road_count"],
            "post_advance_right_attachment_component_count": post_advance_right_attachment_stats["component_count"],
            "post_advance_right_attachment_attached_road_count": post_advance_right_attachment_stats["attached_road_count"],
            "post_advance_right_swsd_carrier_retained_road_count": post_advance_right_swsd_carrier_stats["retained_road_count"],
            "post_advance_right_mixed_boundary_component_count": post_advance_right_attachment_stats["mixed_boundary_component_count"],
            "post_advance_right_paired_advance_road_count": post_advance_right_attachment_stats["paired_advance_road_count"],
            "post_advance_right_midroad_split_original_road_count": post_advance_right_attachment_stats["midroad_split_original_road_count"],
            "post_advance_right_midroad_split_road_count": post_advance_right_attachment_stats["midroad_split_road_count"],
            "post_advance_right_midroad_attached_road_count": post_advance_right_attachment_stats["midroad_attached_road_count"],
            "post_advance_right_swsd_carrier_rcsd_split_original_road_count": post_advance_right_attachment_stats["swsd_carrier_split_original_road_count"],
            "post_advance_right_swsd_carrier_rcsd_split_road_count": post_advance_right_attachment_stats["swsd_carrier_split_road_count"],
            "post_advance_right_swsd_carrier_rcsd_generated_node_count": post_advance_right_attachment_stats["swsd_carrier_generated_node_count"],
            "post_advance_right_swsd_carrier_snapped_node_count": post_advance_right_attachment_stats["swsd_carrier_snapped_node_count"],
            "generated_missing_rcsd_endpoint_node_count": generated_endpoint_node_stats["generated_node_count"],
            "rcsd_advance_right_closure_candidate_road_count": adv_closure_stats["candidate_road_count"],
            "rcsd_advance_right_closure_repaired_endpoint_count": adv_closure_stats["repaired_endpoint_count"],
            "rcsd_advance_right_closure_failed_endpoint_count": adv_closure_stats["failed_endpoint_count"],
            "generated_rcsd_endpoint_node_geometry_synced_count": generated_endpoint_geometry_sync_stats["synced_node_count"],
            "generated_rcsd_endpoint_node_geometry_conflict_count": generated_endpoint_geometry_sync_stats["conflict_node_count"],
            "generated_rcsd_endpoint_road_geometry_snapped_count": generated_endpoint_geometry_sync_stats["snapped_road_endpoint_count"],
            "advance_right_contract_candidate_road_count": right_attach_contract_stats["candidate_road_count"],
            "advance_right_contract_retained_candidate_road_count": right_attach_contract_stats["retained_candidate_road_count"],
            "advance_right_contract_swsd_mainnode_normalized_node_count": right_attach_contract_stats["swsd_mainnode_normalized_node_count"],
            "advance_right_contract_swsd_node_snapped_count": right_attach_contract_stats["swsd_node_snapped_count"],
            "advance_right_contract_rcsd_node_generated_count": right_attach_contract_stats["rcsd_node_generated_count"],
            "advance_right_contract_rcsd_split_original_road_count": right_attach_contract_stats["rcsd_split_original_road_count"],
            "advance_right_contract_rcsd_split_road_count": right_attach_contract_stats["rcsd_split_road_count"],
            "advance_right_contract_audit_row_count": len(right_attach_contract_stats["audit_rows"]),
            "advance_right_attachment_swsd_mainnode_synced_count": attachment_mainnode_sync_stats["synced_node_count"],
            "retained_swsd_attachment_candidate_road_count": retained_swsd_attach_contract_stats["candidate_road_count"],
            "retained_swsd_attachment_candidate_endpoint_count": retained_swsd_attach_contract_stats["candidate_endpoint_count"],
            "retained_swsd_attachment_swsd_node_snapped_count": retained_swsd_attach_contract_stats["swsd_node_snapped_count"],
            "retained_swsd_attachment_rcsd_node_generated_count": retained_swsd_attach_contract_stats["rcsd_node_generated_count"],
            "retained_swsd_attachment_rcsd_split_original_road_count": retained_swsd_attach_contract_stats["rcsd_split_original_road_count"],
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
            "segment_relation_mixed_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "replaced+retained_swsd"),
            "segment_relation_retained_swsd_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "retained_swsd"),
            "segment_relation_failed_count": sum(1 for row in segment_relation_rows if row["properties"].get("relation_status") == "failed"),
            **relation_node_map_backfill_stats,
            **retained_carrier_mainnode_sync_stats,
            **semantic_junction_group_stats,
            **gcf_stats,
            **second_degree_bridge_stats,
            **special_internal_stats,
            **semantic_junction_topology_stats,
            **topology_connectivity_summary,
            **ownership_summary,
            **final_assignment_stats,
            **construction_audit_summary,
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
                **{
                    f"rcsd_road_ownership_{key}": str(value)
                    for key, value in ownership_paths.items()
                },
                **{
                    f"multi_segment_connectivity_group_{key}": str(value)
                    for key, value in connectivity_group_paths.items()
                },
                **{
                    f"segment_construction_audit_{key}": str(value)
                    for key, value in construction_audit_paths.items()
                },
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

    if is_step3_initial_topology_audit_deferred():
        publish_step3_surface_runtime_state(
            Step3SurfaceRuntimeState(
                step_root=step_root,
                swsd_segments=swsd_segments,
                swsd_roads=swsd_roads,
                swsd_nodes=swsd_nodes,
                step2_replaceable_rows=replaceable,
                frcsd_roads=frcsd_roads,
                frcsd_nodes=frcsd_nodes,
                segment_relation_rows=segment_relation_rows,
                semantic_junction_group_rows=semantic_junction_group_rows,
                advance_right_audit_rows=right_attach_audit_rows,
                connectivity_supplement_road_ids=connectivity_supplement_road_ids,
                deferred_publish_jobs=all_publish_jobs,
                deferred_publish_fieldnames={
                    name: list(job.fieldnames)
                    for name, job in all_publish_jobs.items()
                },
            )
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
        rcsd_road_ownership_gpkg_path=(
            ownership_paths.get("gpkg") or step_root / "t06_rcsd_road_ownership.gpkg"
        ),
        multi_segment_connectivity_group_gpkg_path=(
            connectivity_group_paths.get("gpkg")
            or step_root / "t06_multi_segment_connectivity_group.gpkg"
        ),
        segment_construction_audit_gpkg_path=(
            construction_audit_paths.get("gpkg")
            or step_root / "t06_segment_construction_audit.gpkg"
        ),
    )

__all__ = ["run_t06_step3_segment_replacement"]
