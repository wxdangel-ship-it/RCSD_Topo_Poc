from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess import step5_staged_residual_graph as _facade


def Step5Artifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.Step5Artifacts(*args, **kwargs)


def _build_group_to_road_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_group_to_road_ids(*args, **kwargs)


def _build_mainnode_groups(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_mainnode_groups(*args, **kwargs)


def _build_phase_inputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_phase_inputs(*args, **kwargs)


def _build_step5c_adaptive_phase_inputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_step5c_adaptive_phase_inputs(*args, **kwargs)


def _coerce_int(*args: Any, **kwargs: Any) -> Any:
    return _facade._coerce_int(*args, **kwargs)


def _current_closed_con(*args: Any, **kwargs: Any) -> Any:
    return _facade._current_closed_con(*args, **kwargs)


def _current_grade_2(*args: Any, **kwargs: Any) -> Any:
    return _facade._current_grade_2(*args, **kwargs)


def _current_kind_2(*args: Any, **kwargs: Any) -> Any:
    return _facade._current_kind_2(*args, **kwargs)


def _current_segmentid(*args: Any, **kwargs: Any) -> Any:
    return _facade._current_segmentid(*args, **kwargs)


def _filter_active_road_ids_excluding_right_turn(*args: Any, **kwargs: Any) -> Any:
    return _facade._filter_active_road_ids_excluding_right_turn(*args, **kwargs)


def _filter_right_turn_only_side_boundary_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._filter_right_turn_only_side_boundary_ids(*args, **kwargs)


def _identify_right_turn_only_side_pseudojunction_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._identify_right_turn_only_side_pseudojunction_ids(*args, **kwargs)


def _load_nodes_and_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._load_nodes_and_roads(*args, **kwargs)


def _normalize_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._normalize_id(*args, **kwargs)


def _preserve_previous_stage_snapshots(*args: Any, **kwargs: Any) -> Any:
    return _facade._preserve_previous_stage_snapshots(*args, **kwargs)


def _require_working_layers(*args: Any, **kwargs: Any) -> Any:
    return _facade._require_working_layers(*args, **kwargs)


def _resolve_out_root(*args: Any, **kwargs: Any) -> Any:
    return _facade._resolve_out_root(*args, **kwargs)


def _road_flow_flags_for_group(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_flow_flags_for_group(*args, **kwargs)


def _run_phase(*args: Any, **kwargs: Any) -> Any:
    return _facade._run_phase(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> Any:
    return _facade._sort_key(*args, **kwargs)


def _step5a_base_match(*args: Any, **kwargs: Any) -> Any:
    return _facade._step5a_base_match(*args, **kwargs)


def _step5b_base_match(*args: Any, **kwargs: Any) -> Any:
    return _facade._step5b_base_match(*args, **kwargs)


def _write_boundary_node_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_boundary_node_outputs(*args, **kwargs)


def _write_merged_geojson(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_merged_geojson(*args, **kwargs)


def _write_merged_validated_pairs(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_merged_validated_pairs(*args, **kwargs)


def _write_refreshed_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_refreshed_outputs(*args, **kwargs)


def _write_step5c_target_pair_audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_step5c_target_pair_audit(*args, **kwargs)


def canonicalize_road_working_properties(*args: Any, **kwargs: Any) -> Any:
    return _facade.canonicalize_road_working_properties(*args, **kwargs)


def collect_endpoint_pool_mainnodes(*args: Any, **kwargs: Any) -> Any:
    return _facade.collect_endpoint_pool_mainnodes(*args, **kwargs)


def evaluate_mainnode_refresh_retype(*args: Any, **kwargs: Any) -> Any:
    return _facade.evaluate_mainnode_refresh_retype(*args, **kwargs)


def first_existing_vector_path(*args: Any, **kwargs: Any) -> Any:
    return _facade.first_existing_vector_path(*args, **kwargs)


def get_road_segmentid(*args: Any, **kwargs: Any) -> Any:
    return _facade.get_road_segmentid(*args, **kwargs)


def get_road_sgrade(*args: Any, **kwargs: Any) -> Any:
    return _facade.get_road_sgrade(*args, **kwargs)


def is_allowed_road_kind(*args: Any, **kwargs: Any) -> Any:
    return _facade.is_allowed_road_kind(*args, **kwargs)


def is_roundabout_mainnode_kind(*args: Any, **kwargs: Any) -> Any:
    return _facade.is_roundabout_mainnode_kind(*args, **kwargs)


def set_road_segmentid(*args: Any, **kwargs: Any) -> Any:
    return _facade.set_road_segmentid(*args, **kwargs)


def set_road_sgrade(*args: Any, **kwargs: Any) -> Any:
    return _facade.set_road_sgrade(*args, **kwargs)


def summarize_mainnode_retype_topology(*args: Any, **kwargs: Any) -> Any:
    return _facade.summarize_mainnode_retype_topology(*args, **kwargs)


def write_json(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_json(*args, **kwargs)


def write_step5c_barrier_audit_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_step5c_barrier_audit_outputs(*args, **kwargs)


def _refresh_after_step5(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    phase_a: PhaseRunArtifacts,
    phase_b: PhaseRunArtifacts,
    phase_c: PhaseRunArtifacts,
    out_root: Path,
    preserved_snapshots: dict[str, str],
    step5a_input: PhaseInputArtifacts,
    step5b_input: PhaseInputArtifacts,
    step5c_input: PhaseInputArtifacts,
    removed_historical_segment_road_count: int,
    removed_step5a_segment_road_count: int,
    removed_step5b_segment_road_count: int,
    debug: bool,
) -> Step5Artifacts:
    node_by_id = {node.node_id: node for node in nodes}
    road_by_id = {road.road_id: road for road in roads}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, representative_fallback_count = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = {
        node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids
    }

    all_validated_rows = list(phase_a.validated_rows) + list(phase_b.validated_rows) + list(phase_c.validated_rows)
    step5a_endpoint_ids: set[str] = set()
    step5b_endpoint_ids: set[str] = set()
    step5c_endpoint_ids: set[str] = set()
    all_endpoint_ids: set[str] = set()
    for row in phase_a.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5a_endpoint_ids.add(value)
                all_endpoint_ids.add(value)
    for row in phase_b.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5b_endpoint_ids.add(value)
                all_endpoint_ids.add(value)
    for row in phase_c.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5c_endpoint_ids.add(value)
                all_endpoint_ids.add(value)

    new_road_to_segmentid = dict(phase_a.road_to_segmentid)
    for road_id, segmentid in phase_b.road_to_segmentid.items():
        existing = new_road_to_segmentid.get(road_id)
        if existing is not None and existing != segmentid:
            raise ValueError(
                f"Road '{road_id}' is assigned to multiple Step5 segment ids: '{existing}' and '{segmentid}'."
            )
        new_road_to_segmentid[road_id] = segmentid
    for road_id, segmentid in phase_c.road_to_segmentid.items():
        existing = new_road_to_segmentid.get(road_id)
        if existing is not None and existing != segmentid:
            raise ValueError(
                f"Road '{road_id}' is assigned to multiple Step5 segment ids: '{existing}' and '{segmentid}'."
            )
        new_road_to_segmentid[road_id] = segmentid

    road_properties_map: dict[str, dict[str, Any]] = {}
    for road in roads:
        props = canonicalize_road_working_properties(road.properties)
        existing_segmentid = _current_segmentid(road)
        if existing_segmentid:
            set_road_segmentid(props, existing_segmentid)
            set_road_sgrade(props, get_road_sgrade(props))
        elif road.road_id in new_road_to_segmentid:
            set_road_segmentid(props, new_road_to_segmentid[road.road_id])
            set_road_sgrade(props, _facade.STEP5_NEW_SEGMENT_GRADE)
        else:
            set_road_segmentid(props, get_road_segmentid(props))
            set_road_sgrade(props, get_road_sgrade(props))
        road_properties_map[road.road_id] = props

    group_to_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids={road.road_id for road in roads},
        physical_to_semantic=physical_to_semantic,
    )
    group_to_allowed_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids={road.road_id for road in roads if is_allowed_road_kind(road.road_kind)},
        physical_to_semantic=physical_to_semantic,
    )

    node_properties_map: dict[str, dict[str, Any]] = {node.node_id: dict(node.properties) for node in nodes}
    node_rule_keep_pair_count = 0
    node_rule_single_segment_count = 0
    node_rule_right_turn_only_count = 0
    node_rule_retyped_grade2_kind2048_count = 0
    node_rule_retyped_grade2_kind4_count = 0
    multi_segment_mainnode_kept_count = 0
    mainnode_rows: list[dict[str, Any]] = []

    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        group = mainnode_groups[mainnode_id]
        representative = node_by_id[group.representative_node_id]
        current_grade_2 = _current_grade_2(representative)
        current_kind_2 = _current_kind_2(representative)
        current_closed_con = _current_closed_con(representative)

        associated_road_ids = sorted(group_to_road_ids.get(mainnode_id, set()), key=_sort_key)
        associated_roads = [road_by_id[road_id] for road_id in associated_road_ids]
        segment_ids = sorted(
            {
                road_properties_map[road.road_id].get("segmentid")
                for road in associated_roads
                if road_properties_map[road.road_id].get("segmentid")
            },
            key=_sort_key,
        )
        unique_segmentid_count = len(segment_ids)
        nonsegment_roads = [road for road in associated_roads if not road_properties_map[road.road_id].get("segmentid")]
        nonsegment_road_count = len(nonsegment_roads)
        nonsegment_all_right_turn_only = bool(nonsegment_roads) and all(
            (_coerce_int(road.properties.get("formway")) or 0) & (1 << _facade.RIGHT_TURN_FORMWAY_BIT) for road in nonsegment_roads
        )
        member_id_set = set(group.member_node_ids)
        nonsegment_has_in = False
        nonsegment_has_out = False
        for road in nonsegment_roads:
            has_in, has_out = _road_flow_flags_for_group(road, member_id_set)
            nonsegment_has_in = nonsegment_has_in or has_in
            nonsegment_has_out = nonsegment_has_out or has_out
        topology = summarize_mainnode_retype_topology(
            member_node_ids=group.member_node_ids,
            associated_roads=associated_roads,
            road_properties_map=road_properties_map,
            physical_to_semantic=physical_to_semantic,
            right_turn_formway_bit=_facade.RIGHT_TURN_FORMWAY_BIT,
            node_properties_map=node_properties_map,
        )

        new_grade_2 = current_grade_2
        new_kind_2 = current_kind_2
        applied_rule = "keep_current"
        if is_roundabout_mainnode_kind(current_kind_2):
            applied_rule = "protected_roundabout_mainnode"
        elif mainnode_id in all_endpoint_ids:
            applied_rule = "keep_step5_pair_endpoint"
            node_rule_keep_pair_count += 1
        elif unique_segmentid_count > 1:
            applied_rule = "multi_segment_kept_current"
            multi_segment_mainnode_kept_count += 1
        elif associated_roads and unique_segmentid_count == 1 and all(
            road_properties_map[road.road_id].get("segmentid") for road in associated_roads
        ):
            new_grade_2 = -1
            new_kind_2 = 1
            applied_rule = "single_segment_non_intersection"
            node_rule_single_segment_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_all_right_turn_only:
            new_grade_2 = 3
            new_kind_2 = 1
            applied_rule = "right_turn_only_side"
            node_rule_right_turn_only_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_has_in and nonsegment_has_out:
            retype_decision = evaluate_mainnode_refresh_retype(
                current_grade_2=current_grade_2,
                current_kind_2=current_kind_2,
                topology=topology,
            )
            if retype_decision is not None:
                new_grade_2 = retype_decision.grade_2
                new_kind_2 = retype_decision.kind_2
                applied_rule = retype_decision.applied_rule
                if retype_decision.kind_2 == 2048:
                    node_rule_retyped_grade2_kind2048_count += 1
                else:
                    node_rule_retyped_grade2_kind4_count += 1

        rep_props = dict(node_properties_map[group.representative_node_id])
        rep_props["grade_2"] = new_grade_2
        rep_props["kind_2"] = new_kind_2
        node_properties_map[group.representative_node_id] = rep_props

        mainnode_rows.append(
            {
                "mainnode_id": mainnode_id,
                "representative_node_id": group.representative_node_id,
                "participates_in_step5a_pair": mainnode_id in step5a_endpoint_ids,
                "participates_in_step5b_pair": mainnode_id in step5b_endpoint_ids,
                "participates_in_step5c_pair": mainnode_id in step5c_endpoint_ids,
                "current_grade_2": current_grade_2,
                "current_kind_2": current_kind_2,
                "current_closed_con": current_closed_con,
                "new_grade_2": new_grade_2,
                "new_kind_2": new_kind_2,
                "unique_segmentid_count": unique_segmentid_count,
                "nonsegment_road_count": nonsegment_road_count,
                "nonsegment_all_right_turn_only": nonsegment_all_right_turn_only,
                "nonsegment_has_in": nonsegment_has_in,
                "nonsegment_has_out": nonsegment_has_out,
                "neighbor_family_count": topology.total_neighbor_family_count,
                "segment_neighbor_family_count": topology.segment_neighbor_family_count,
                "residual_neighbor_family_count": topology.residual_neighbor_family_count,
                "simple_residual_neighbor_family_count": topology.simple_residual_neighbor_family_count,
                "neighbor_family_rows_json": list(topology.family_rows),
                "applied_rule": applied_rule,
            }
        )

    summary = {
        "run_id": out_root.name,
        "input_node_path": str(out_root.parent),  # overwritten below
        "input_road_path": str(out_root.parent),  # overwritten below
        "preserved_prev_s2_dir": preserved_snapshots.get("S2"),
        "preserved_prev_step4_dir": preserved_snapshots.get("STEP4"),
        "step5a_input_node_count": step5a_input.input_node_count,
        "step5a_seed_count": step5a_input.seed_count,
        "step5a_terminate_count": step5a_input.terminate_count,
        "step5a_validated_pair_count": phase_a.validated_pair_count,
        "step5a_new_segment_road_count": phase_a.new_segment_road_count,
        "step5b_input_node_count": step5b_input.input_node_count,
        "step5b_seed_count": step5b_input.seed_count,
        "step5b_terminate_count": step5b_input.terminate_count,
        "step5b_validated_pair_count": phase_b.validated_pair_count,
        "step5b_new_segment_road_count": phase_b.new_segment_road_count,
        "step5c_input_node_count": step5c_input.input_node_count,
        "step5c_seed_count": step5c_input.seed_count,
        "step5c_terminate_count": step5c_input.terminate_count,
        "step5c_validated_pair_count": phase_c.validated_pair_count,
        "step5c_new_segment_road_count": phase_c.new_segment_road_count,
        "step5_removed_historical_segment_road_count": removed_historical_segment_road_count,
        "step5_removed_step5a_segment_road_count": removed_step5a_segment_road_count,
        "step5_removed_step5b_segment_road_count": removed_step5b_segment_road_count,
        "step5_total_new_segment_road_count": len(new_road_to_segmentid),
        "node_rule_keep_pair_count": node_rule_keep_pair_count,
        "node_rule_single_segment_count": node_rule_single_segment_count,
        "node_rule_right_turn_only_count": node_rule_right_turn_only_count,
        "node_rule_new_t_count": node_rule_retyped_grade2_kind2048_count,
        "node_rule_retyped_grade2_kind2048_count": node_rule_retyped_grade2_kind2048_count,
        "node_rule_retyped_grade2_kind4_count": node_rule_retyped_grade2_kind4_count,
        "multi_segment_mainnode_kept_count": multi_segment_mainnode_kept_count,
        "mainnode_representative_fallback_count": representative_fallback_count,
    }

    return _write_refreshed_outputs(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        out_root=out_root,
        mainnode_rows=mainnode_rows,
        summary=summary,
        mainnode_groups=mainnode_groups,
        group_to_allowed_road_ids=group_to_allowed_road_ids,
        write_alias_outputs=debug,
    )


def run_step5_staged_residual_graph(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    formway_mode: str = "strict",
    left_turn_formway_bit: int = 8,
    debug: bool = True,
) -> Step5Artifacts:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    (nodes, _, _), (roads, _) = _load_nodes_and_roads(
        node_path=node_path,
        road_path=road_path,
        node_layer=node_layer,
        node_crs=node_crs,
        road_layer=road_layer,
        road_crs=road_crs,
    )
    _require_working_layers(nodes=nodes, roads=roads, stage_label="Step5")
    input_parent = Path(node_path).resolve().parent

    preserved_snapshots: dict[str, str] = {}
    if debug:
        preserved_snapshots = _preserve_previous_stage_snapshots(
            node_path=node_path,
            road_path=road_path,
            out_root=resolved_out_root,
        )
    historical_boundary_ids, historical_boundary_source_map = collect_endpoint_pool_mainnodes(
        base_dir=input_parent,
        source_specs=(
            ("S2", ("S2/validated_pairs.csv", "S2/endpoint_pool.csv")),
            ("STEP4", ("STEP4/validated_pairs.csv", "step4_validated_pairs.csv", "STEP4/endpoint_pool.csv", "step4_endpoint_pool.csv")),
        ),
    )

    historical_segment_road_ids = {road.road_id for road in roads if _current_segmentid(road)}
    used_segmentids = {
        segmentid
        for road in roads
        for segmentid in (_current_segmentid(road),)
        if segmentid is not None
    }
    active_road_ids_step5a_raw = {
        road.road_id
        for road in roads
        if road.road_id not in historical_segment_road_ids and is_allowed_road_kind(road.road_kind)
    }
    step5a_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5a_raw,
    )
    active_road_ids_step5a = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5a_raw,
    )
    historical_boundary_ids, _demoted_step5a_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=historical_boundary_ids,
        active_road_ids=active_road_ids_step5a_raw,
    )
    step5a_input = _build_phase_inputs(
        phase_id=_facade.STEP5A_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5a,
        pseudo_junction_ids=step5a_pseudo_junction_ids,
        out_root=resolved_out_root,
        base_match=_step5a_base_match,
        historical_seed_node_ids=historical_boundary_ids,
        historical_seed_source_map=historical_boundary_source_map,
        hard_stop_node_ids=historical_boundary_ids,
    )
    phase_a = _run_phase(
        phase_input=step5a_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_a.assigned_segment_ids)
    step5b_historical_seed_node_ids = set(step5a_input.endpoint_pool_ids)
    combined_boundary_source_map = dict(step5a_input.endpoint_pool_source_map)
    if debug:
        _write_boundary_node_outputs(
            out_root=resolved_out_root,
            nodes=nodes,
            boundary_source_map=combined_boundary_source_map,
        )

    active_road_ids_step5b_raw = set(active_road_ids_step5a_raw) - set(phase_a.road_to_segmentid)
    step5b_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5b_raw,
    )
    active_road_ids_step5b = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5b_raw,
    )
    step5b_historical_seed_node_ids, _demoted_step5b_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=step5b_historical_seed_node_ids,
        active_road_ids=active_road_ids_step5b_raw,
    )
    step5b_hard_stop_node_ids = set(step5b_historical_seed_node_ids)
    step5b_input = _build_phase_inputs(
        phase_id=_facade.STEP5B_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5b,
        pseudo_junction_ids=step5b_pseudo_junction_ids,
        out_root=resolved_out_root,
        base_match=_step5b_base_match,
        historical_seed_node_ids=step5b_historical_seed_node_ids,
        historical_seed_source_map=combined_boundary_source_map,
        hard_stop_node_ids=step5b_hard_stop_node_ids,
    )
    phase_b = _run_phase(
        phase_input=step5b_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_b.assigned_segment_ids)

    step5c_historical_seed_node_ids = set(step5b_input.endpoint_pool_ids)
    combined_boundary_source_map = dict(step5b_input.endpoint_pool_source_map)
    if debug:
        _write_boundary_node_outputs(
            out_root=resolved_out_root,
            nodes=nodes,
            boundary_source_map=combined_boundary_source_map,
        )

    active_road_ids_step5c_raw = set(active_road_ids_step5b_raw) - set(phase_b.road_to_segmentid)
    step5c_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5c_raw,
    )
    active_road_ids_step5c = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5c_raw,
    )
    step5c_historical_seed_node_ids, _demoted_step5c_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=step5c_historical_seed_node_ids,
        active_road_ids=active_road_ids_step5c_raw,
    )
    step5c_input, step5c_adaptive_context = _build_step5c_adaptive_phase_inputs(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5c,
        out_root=resolved_out_root,
        historical_seed_node_ids=step5c_historical_seed_node_ids,
        historical_seed_source_map=combined_boundary_source_map,
        pseudo_junction_ids=step5c_pseudo_junction_ids,
    )
    phase_c = _run_phase(
        phase_input=step5c_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_c.assigned_segment_ids)
    step5c_barrier_audit_paths = write_step5c_barrier_audit_outputs(
        phase_dir=phase_c.phase_dir,
        nodes=nodes,
        adaptive_context=step5c_adaptive_context,
    )
    step5c_target_pair_audit_path = _write_step5c_target_pair_audit(
        phase_dir=phase_c.phase_dir,
        adaptive_context=step5c_adaptive_context,
    )

    merged_validated_rows = _write_merged_validated_pairs(
        phase_rows=[
            ("STEP5A", phase_a.validated_rows),
            ("STEP5B", phase_b.validated_rows),
            ("STEP5C", phase_c.validated_rows),
        ],
        out_path=resolved_out_root / "step5_validated_pairs_merged.csv",
    )
    if debug:
        _write_merged_geojson(
            paths=[
                first_existing_vector_path(phase_a.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_a.phase_dir / "segment_body_roads.gpkg",
                first_existing_vector_path(phase_b.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_b.phase_dir / "segment_body_roads.gpkg",
                first_existing_vector_path(phase_c.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_c.phase_dir / "segment_body_roads.gpkg",
            ],
            out_path=resolved_out_root / "step5_segment_body_roads_merged.gpkg",
            phase_labels=["STEP5A", "STEP5B", "STEP5C"],
        )
        _write_merged_geojson(
            paths=[
                first_existing_vector_path(phase_a.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_a.phase_dir / "step3_residual_roads.gpkg",
                first_existing_vector_path(phase_b.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_b.phase_dir / "step3_residual_roads.gpkg",
                first_existing_vector_path(phase_c.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_c.phase_dir / "step3_residual_roads.gpkg",
            ],
            out_path=resolved_out_root / "step5_residual_roads_merged.gpkg",
            phase_labels=["STEP5A", "STEP5B", "STEP5C"],
        )
        write_json(
            resolved_out_root / "strategy_comparison.json",
            {
                "run_id": resolved_run_id,
                "strategies": [
                    {"strategy_id": phase_a.phase_id, **phase_a.segment_summary},
                    {"strategy_id": phase_b.phase_id, **phase_b.segment_summary},
                    {"strategy_id": phase_c.phase_id, **phase_c.segment_summary},
                ],
            },
        )

    artifacts = _refresh_after_step5(
        nodes=nodes,
        roads=roads,
        phase_a=phase_a,
        phase_b=phase_b,
        phase_c=phase_c,
        out_root=resolved_out_root,
        preserved_snapshots=preserved_snapshots,
        step5a_input=step5a_input,
        step5b_input=step5b_input,
        step5c_input=step5c_input,
        removed_historical_segment_road_count=len(historical_segment_road_ids),
        removed_step5a_segment_road_count=len(phase_a.road_to_segmentid),
        removed_step5b_segment_road_count=len(phase_b.road_to_segmentid),
        debug=debug,
    )
    refreshed_summary = dict(artifacts.summary)
    refreshed_summary["input_node_path"] = str(Path(node_path))
    refreshed_summary["input_road_path"] = str(Path(road_path))
    refreshed_summary["step5a_candidate_pair_count"] = phase_a.candidate_pair_count
    refreshed_summary["step5a_rejected_pair_count"] = phase_a.rejected_pair_count
    refreshed_summary["step5b_candidate_pair_count"] = phase_b.candidate_pair_count
    refreshed_summary["step5b_rejected_pair_count"] = phase_b.rejected_pair_count
    refreshed_summary["step5c_candidate_pair_count"] = phase_c.candidate_pair_count
    refreshed_summary["step5c_rejected_pair_count"] = phase_c.rejected_pair_count
    refreshed_summary["step5_merged_validated_pair_count"] = len(merged_validated_rows)
    refreshed_summary["historical_boundary_node_count"] = len(historical_boundary_ids)
    refreshed_summary["step5b_hard_stop_node_count"] = len(step5b_hard_stop_node_ids)
    refreshed_summary["step5c_hard_stop_node_count"] = len(step5c_input.protected_hard_stop_ids)
    refreshed_summary["step5c_rolling_endpoint_pool_count"] = len(step5c_input.endpoint_pool_ids)
    refreshed_summary["step5c_protected_hard_stop_count"] = len(step5c_input.protected_hard_stop_ids)
    refreshed_summary["step5c_demoted_endpoint_count"] = len(step5c_input.demoted_endpoint_ids)
    refreshed_summary["step5c_actual_barrier_count"] = len(step5c_input.actual_barrier_ids)
    refreshed_summary["step5c_rolling_endpoint_pool_path"] = step5c_barrier_audit_paths["rolling_endpoint_pool_csv"]
    refreshed_summary["step5c_protected_hard_stops_path"] = step5c_barrier_audit_paths["protected_hard_stops_csv"]
    refreshed_summary["step5c_demotable_endpoints_path"] = step5c_barrier_audit_paths["demotable_endpoints_csv"]
    refreshed_summary["step5c_actual_barriers_path"] = step5c_barrier_audit_paths["actual_barriers_csv"]
    refreshed_summary["step5c_endpoint_demote_audit_path"] = step5c_barrier_audit_paths["endpoint_demote_audit_json"]
    refreshed_summary["step5c_target_pair_audit_path"] = str(step5c_target_pair_audit_path.resolve())
    refreshed_summary["debug"] = debug
    write_json(artifacts.summary_path, refreshed_summary)
    return Step5Artifacts(
        out_root=artifacts.out_root,
        refreshed_nodes_path=artifacts.refreshed_nodes_path,
        refreshed_roads_path=artifacts.refreshed_roads_path,
        refreshed_nodes_alias_path=artifacts.refreshed_nodes_alias_path,
        refreshed_roads_alias_path=artifacts.refreshed_roads_alias_path,
        summary_path=artifacts.summary_path,
        mainnode_table_path=artifacts.mainnode_table_path,
        summary=refreshed_summary,
        step6_nodes=artifacts.step6_nodes,
        step6_roads=artifacts.step6_roads,
        step6_node_properties_map=artifacts.step6_node_properties_map,
        step6_road_properties_map=artifacts.step6_road_properties_map,
        step6_mainnode_groups=artifacts.step6_mainnode_groups,
        step6_group_to_allowed_road_ids=artifacts.step6_group_to_allowed_road_ids,
    )
