from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Any

import fiona
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import substring

from .io import prepare_output_dir, write_json
from .segment_first_access_recovery import (
    annotate_recovery_carrier_conflicts,
    build_access_surface_recovery_candidates,
    build_required_endpoint_surfaces,
    build_required_through_surfaces,
    recoordinate_access_recovery_assignments,
)
from .segment_first_carriers import plan_segment_carriers
from .segment_first_config import SegmentFirstConfig
from .segment_first_evidence import build_segment_evidence
from .segment_first_fallback import (
    _audit_built_road_continuity,
    _fallback_segment_ids,
    _same_segment_rejected_mask,
    direct_build_rescue_segment_ids,
    with_direct_build_rescue_reference_axes,
)
from .segment_first_geometry import RoadGeometryResult
from .segment_first_geometry_quality import (
    apply_review_flags,
    audit_built_road_geometry,
)
from .segment_first_inputs import load_segment_first_inputs
from .segment_first_junctions import (
    build_endpoint_surface_audit,
    build_junction_units,
)
from .segment_first_junction_carriers import (
    JunctionCarrierResult,
)
from .segment_first_junction_topology import (
    materialize_swsd_junction_movement_contract,
)
from .segment_first_lane_topo import (
    LANE_TOPO_PAIR_SOURCES,
    _has_junction_carrier_path,
    _project_lane_topo,
    rejected_lane_topo_pairs,
)
from .segment_first_lineage import (
    attach_lineage_split_to_node_build,
    split_roads_at_stable_lineage_boundaries,
)
from .segment_first_movements import (
    split_carriers_at_movement_anchors,
    split_carriers_at_segment_accesses,
)
from .segment_first_network import materialize_network_geometry
from .segment_first_nodes import build_nodes_and_connect_roads
from .segment_first_outputs import publish_segment_first_layers
from .segment_first_qgis import build_qgis_project
from .segment_first_quality import run_independent_quality
from .segment_first_reference_axes import build_segment_reference_axes
from .segment_first_retained_overlap import (
    try_suppress_redundant_retained_roads,
)
from .segment_first_road_lane import (
    build_road_lane_relation as _road_lane_relation,
)
from .segment_first_skeleton import build_segment_skeleton, canonical_id, parse_id_list
from .segment_first_summary import build_run_summary, render_run_report
from .segment_first_swsd_topology import (
    audit_swsd_access_direction_topology,
)
from .segment_first_swsd_paths import (
    build_swsd_segment_directional_paths,
)
from .segment_first_swsd_junction_audit import (
    build_swsd_junction_structure_audit,
)
from .segment_first_target_coverage import build_target_coverage_contract
from .segment_first_target_realization import audit_target_realization
from .segment_first_topology import compile_road_next_road
from .segment_first_types import SegmentFirstResult


def _split_physical_carriers(
    carriers: gpd.GeoDataFrame,
    evidence: Any,
    junctions: Any,
    config: SegmentFirstConfig,
    endpoint_trim_segment_ids: set[str] | None = None,
):
    movement = split_carriers_at_movement_anchors(
        carriers,
        evidence.geometry_sources,
        evidence.explicit_road_pairs,
        run_id=config.run_id,
        maximum_anchor_distance_m=config.relation_endpoint_max_distance_m,
    )
    return split_carriers_at_segment_accesses(
        movement,
        junctions.access_relations,
        junctions.junction_units,
        evidence.geometry_sources,
        run_id=config.run_id,
        maximum_access_distance_m=config.relation_endpoint_max_distance_m,
        endpoint_trim_segment_ids=endpoint_trim_segment_ids,
        endpoint_surface_buffer_m=config.junction_endpoint_buffer_m,
    )


def run_segment_first_road_direct(config: SegmentFirstConfig) -> SegmentFirstResult:
    started = time.perf_counter()
    cfg = config.resolved()
    cfg.validate_paths()
    prepare_output_dir(cfg.output_dir)
    inputs = load_segment_first_inputs(cfg)
    write_json(cfg.output_dir / "p04_segment_first_input_manifest.json", inputs.manifest)

    skeleton = build_segment_skeleton(
        inputs.t01_segments,
        inputs.t01_roads,
        inputs.t01_nodes,
        patch_ids=inputs.patch_ids,
        run_id=cfg.run_id,
    )
    target_coverage = build_target_coverage_contract(
        skeleton.segment_units,
        skeleton.scoped_roads,
        inputs.target_replaceability,
        patch_ids=inputs.patch_ids,
        target_disposition_path=cfg.target_disposition_path,
        run_id=cfg.run_id,
    )
    junctions = build_junction_units(
        inputs.t07_surfaces,
        inputs.t03_surfaces,
        inputs.t04_surfaces,
        skeleton.accesses,
        t01_nodes=inputs.t01_nodes,
        run_id=cfg.run_id,
    )
    segment_reference_axes = build_segment_reference_axes(
        target_coverage.segments,
        skeleton.scoped_roads,
        inputs.swsd_nodes,
        run_id=cfg.run_id,
        junction_units=junctions.junction_units,
    )
    carrier_reference_axes = segment_reference_axes.axes[
        segment_reference_axes.axes["carrier_guidance_eligible"]
        .fillna(False)
        .astype(bool)
    ].copy()
    swsd_directional_paths = build_swsd_segment_directional_paths(
        target_coverage.segments,
        skeleton.scoped_roads,
        inputs.t01_nodes,
        junctions.access_relations,
        run_id=cfg.run_id,
    )
    directional_member_roles_for_publication = (
        swsd_directional_paths.member_roles
    )
    required_through_surfaces = build_required_through_surfaces(
        junctions.access_relations,
        junctions.junction_units,
        endpoint_inset_m=cfg.junction_endpoint_buffer_m,
    )
    required_endpoint_surfaces = build_required_endpoint_surfaces(
        junctions.access_relations,
        junctions.junction_units,
        endpoint_inset_m=cfg.junction_endpoint_buffer_m,
    )
    evidence = build_segment_evidence(
        inputs.patch_roads,
        inputs.patch_lanes,
        inputs.patch_lane_topo,
        inputs.patch_road_next_road,
        skeleton.scoped_roads,
        config=cfg,
        target_anchors=target_coverage.anchors,
        target_segments=target_coverage.segments,
        full_rcsd_roads=inputs.full_rcsd_roads,
    )
    access_recovery = build_access_surface_recovery_candidates(
        target_coverage.segments,
        evidence.patch_road_centers,
        junctions.access_relations,
        junctions.junction_units,
        inputs.drivezones,
        run_id=cfg.run_id,
        maximum_surface_distance_m=cfg.endpoint_snap_distance_m,
        minimum_drivezone_coverage=cfg.completion_surface_min_coverage,
    )
    endpoint_surface_rescue_ids: set[str] = set()
    base_carrier_plan = plan_segment_carriers(
        target_coverage.segments,
        skeleton.scoped_roads,
        evidence.carrier_assignments,
        run_id=cfg.run_id,
        explicit_pairs=evidence.explicit_road_pairs,
        drivezones=inputs.drivezones,
        target_reference_axes=carrier_reference_axes,
        directional_member_roles=directional_member_roles_for_publication,
        minimum_member_coverage=cfg.member_takeover_min_coverage,
        sample_spacing_m=cfg.smoothing_sample_spacing_m,
        completion_min_coverage=cfg.completion_surface_min_coverage,
        maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
        required_endpoint_surfaces=required_endpoint_surfaces,
        endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
    )
    planning_assignments = evidence.carrier_assignments
    if not access_recovery.empty:
        access_recovery = annotate_recovery_carrier_conflicts(
            access_recovery,
            base_carrier_plan.carriers,
        )
        eligible_access_recovery = access_recovery[
            access_recovery["recovery_eligible"].fillna(False).astype(bool)
        ].copy()
        evidence_summary = dict(evidence.summary)
        evidence_summary["access_surface_recovery_candidate_count"] = int(
            len(access_recovery)
        )
        evidence_summary["access_surface_recovery_eligible_count"] = int(
            len(eligible_access_recovery)
        )
        evidence_summary["access_surface_recovery_conflict_count"] = int(
            len(access_recovery) - len(eligible_access_recovery)
        )
        planning_assignments = gpd.GeoDataFrame(
            pd.concat(
                [evidence.carrier_assignments, eligible_access_recovery],
                ignore_index=True,
                sort=False,
            ),
            geometry="geometry",
            crs=evidence.carrier_assignments.crs,
        )
        evidence = replace(
            evidence,
            target_fragment_audit=gpd.GeoDataFrame(
                pd.concat(
                    [evidence.target_fragment_audit, access_recovery],
                    ignore_index=True,
                    sort=False,
                ),
                geometry="geometry",
                crs=evidence.target_fragment_audit.crs,
            ),
            summary=evidence_summary,
        )
    carrier_plan = plan_segment_carriers(
        target_coverage.segments,
        skeleton.scoped_roads,
        planning_assignments,
        run_id=cfg.run_id,
        explicit_pairs=evidence.explicit_road_pairs,
        drivezones=inputs.drivezones,
        target_reference_axes=carrier_reference_axes,
        directional_member_roles=directional_member_roles_for_publication,
        minimum_member_coverage=cfg.member_takeover_min_coverage,
        sample_spacing_m=cfg.smoothing_sample_spacing_m,
        completion_min_coverage=cfg.completion_surface_min_coverage,
        maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
        required_endpoint_surfaces=required_endpoint_surfaces,
        endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
        required_through_surfaces=required_through_surfaces,
    )
    core_target_ids = set(
        target_coverage.segments.loc[
            target_coverage.segments["target_class"].eq("core_trunk")
            & target_coverage.segments["direct_build_required"],
            "segment_id",
        ].astype(str)
    )
    endpoint_trim_segment_ids = set(
        target_coverage.segments.loc[
            target_coverage.segments["target_class"].isin(
                {"core_trunk", "advance_right"}
            ),
            "segment_id",
        ].astype(str)
    )
    semantic_endpoint_retry_ids: set[str] = set()
    movement_split = _split_physical_carriers(
        carrier_plan.carriers,
        evidence,
        junctions,
        cfg,
        endpoint_trim_segment_ids,
    )
    geometry, junction_carriers = materialize_network_geometry(
        movement_split.carriers,
        skeleton.scoped_roads,
        junctions.junction_units,
        junctions.access_relations,
        inputs.drivezones,
        inputs.t01_nodes,
        inputs.full_rcsd_roads,
        evidence.explicit_road_pairs,
        config=cfg,
        semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
    )
    node_build = build_nodes_and_connect_roads(
        geometry.roads,
        junctions.junction_units,
        junctions.access_relations,
        evidence.explicit_road_pairs,
        inputs.drivezones,
        inputs.t01_nodes,
        inputs.full_rcsd_nodes,
        config=cfg,
        materialized_ordinary_group_ids=set(
            junction_carriers.materialized_group_ids
        ),
    )
    initial_access_probe = _audit_segment_access_realization(
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        cfg.run_id,
    )
    probe_semantic_endpoint_ids = set(
        initial_access_probe.loc[
            ~initial_access_probe["access_realized"]
            & initial_access_probe["access_type"].eq("ENDPOINT"),
            "segment_id",
        ].astype(str)
    ).intersection(core_target_ids)
    if probe_semantic_endpoint_ids:
        probe_node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=probe_semantic_endpoint_ids,
        )
        initial_access_probe = _audit_segment_access_realization(
            junctions.access_relations,
            probe_node_build.roads,
            probe_node_build.nodes,
            cfg.run_id,
        )
    endpoint_trim_segment_ids.update(
        set(
            initial_access_probe.loc[
                ~initial_access_probe["access_realized"]
                & initial_access_probe["access_type"].eq("ENDPOINT"),
                "segment_id",
            ].astype(str)
        ).intersection(core_target_ids)
    )
    if endpoint_trim_segment_ids:
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
        )
    if not access_recovery.empty:
        (
            access_recovery,
            coordinated_assignments,
            newly_eligible_recovery_ids,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=set(),
        )
        if newly_eligible_recovery_ids:
            planning_assignments = coordinated_assignments
            carrier_plan = plan_segment_carriers(
                target_coverage.segments,
                skeleton.scoped_roads,
                planning_assignments,
                run_id=cfg.run_id,
                explicit_pairs=evidence.explicit_road_pairs,
                drivezones=inputs.drivezones,
                target_reference_axes=carrier_reference_axes,
                directional_member_roles=directional_member_roles_for_publication,
                minimum_member_coverage=cfg.member_takeover_min_coverage,
                sample_spacing_m=cfg.smoothing_sample_spacing_m,
                completion_min_coverage=cfg.completion_surface_min_coverage,
                maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
                required_endpoint_surfaces=required_endpoint_surfaces,
                endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
                required_through_surfaces=required_through_surfaces,
            )
            movement_split = _split_physical_carriers(
                carrier_plan.carriers,
                evidence,
                junctions,
                cfg,
                endpoint_trim_segment_ids,
            )
            geometry, junction_carriers = materialize_network_geometry(
                movement_split.carriers,
                skeleton.scoped_roads,
                junctions.junction_units,
                junctions.access_relations,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_roads,
                evidence.explicit_road_pairs,
                config=cfg,
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            node_build = build_nodes_and_connect_roads(
                geometry.roads,
                junctions.junction_units,
                junctions.access_relations,
                evidence.explicit_road_pairs,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_nodes,
                config=cfg,
                materialized_ordinary_group_ids=set(
                    junction_carriers.materialized_group_ids
                ),
            )
    rejected_lane_connections = node_build.connection_evidence[
        node_build.connection_evidence["connection_decision"].eq("rejected")
        & node_build.connection_evidence["pair_source"].isin(
            LANE_TOPO_PAIR_SOURCES
        )
    ].copy()
    same_segment_rejection_mask = _same_segment_rejected_mask(
        rejected_lane_connections,
        evidence.carrier_assignments,
    )
    fallback_triggers = rejected_lane_connections[
        same_segment_rejection_mask
    ].copy()
    lane_topo_connection_exclusions = rejected_lane_connections[
        ~same_segment_rejection_mask
    ].copy()
    direct_build_rescue_ids = direct_build_rescue_segment_ids(
        fallback_triggers,
        evidence.carrier_assignments,
        direct_build_core_segment_ids=core_target_ids,
        already_rescued_segment_ids=endpoint_surface_rescue_ids,
    )
    if direct_build_rescue_ids:
        endpoint_surface_rescue_ids.update(direct_build_rescue_ids)
        carrier_reference_axes = (
            with_direct_build_rescue_reference_axes(
                carrier_reference_axes,
                segment_reference_axes.axes,
                direct_build_rescue_ids,
            )
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
        )
        rejected_lane_connections = node_build.connection_evidence[
            node_build.connection_evidence[
                "connection_decision"
            ].eq("rejected")
            & node_build.connection_evidence["pair_source"].isin(
                LANE_TOPO_PAIR_SOURCES
            )
        ].copy()
        same_segment_rejection_mask = _same_segment_rejected_mask(
            rejected_lane_connections,
            evidence.carrier_assignments,
        )
        fallback_triggers = rejected_lane_connections[
            same_segment_rejection_mask
        ].copy()
        lane_topo_connection_exclusions = rejected_lane_connections[
            ~same_segment_rejection_mask
        ].copy()
    fallback_segments = _fallback_segment_ids(
        fallback_triggers,
        evidence.carrier_assignments,
    )
    if fallback_segments:
        fallback_triggers["pipeline_stage"] = "pre_fallback"
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
        )
    initial_access_realization = _audit_segment_access_realization(
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        cfg.run_id,
    )
    semantic_endpoint_retry_ids.update(
        set(
            initial_access_realization.loc[
                ~initial_access_realization["access_realized"], "segment_id"
            ].astype(str)
        ).intersection(core_target_ids)
    )
    if semantic_endpoint_retry_ids:
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    continuity_probe = _audit_built_road_continuity(
        node_build.roads,
        node_build.nodes,
        junctions.access_relations,
        node_build.endpoint_audit,
        run_id=cfg.run_id,
        maximum_endpoint_shift_m=cfg.relation_endpoint_max_distance_m,
    )
    main_road_ids = set(
        node_build.roads.loc[
            node_build.roads["carrier_role"].fillna("").astype(str).str.startswith(
                "main_"
            ),
            "id",
        ].astype(str)
    )
    continuity_semantic_retry_ids = set(
        continuity_probe.loc[
            continuity_probe["hard_failure"]
            & continuity_probe["road_id"].astype(str).isin(main_road_ids),
            "segment_id",
        ].astype(str)
    ).intersection(core_target_ids) - semantic_endpoint_retry_ids
    if continuity_semantic_retry_ids:
        semantic_endpoint_retry_ids.update(continuity_semantic_retry_ids)
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    directional_probe = audit_target_realization(
        target_coverage.segments,
        node_build.roads,
        segment_plans=carrier_plan.segment_plans,
        nodes=node_build.nodes,
        segment_accesses=junctions.access_relations,
        junction_units=junctions.junction_units,
        run_id=cfg.run_id,
    )
    directional_chain_retry_ids = set(
        directional_probe.audit.loc[
            ~directional_probe.audit["target_realized"]
            & directional_probe.audit["direct_build_required"]
            & directional_probe.audit["target_class"].eq("core_trunk"),
            "segment_id",
        ].astype(str)
    )
    semantic_endpoint_retry_ids.update(directional_chain_retry_ids)
    access_probe = _audit_segment_access_realization(
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        cfg.run_id,
    )
    endpoint_surface_retry_ids = set(
        access_probe.loc[
            ~access_probe["access_realized"]
            & access_probe["access_type"].eq("ENDPOINT"),
            "segment_id",
        ].astype(str)
    ).union(directional_chain_retry_ids).intersection(
        core_target_ids
    ).difference(fallback_segments)
    if endpoint_surface_retry_ids:
        endpoint_surface_rescue_ids.update(endpoint_surface_retry_ids)
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    junction_carrier_fallback_frames: list[gpd.GeoDataFrame] = []
    junction_carrier_fallback_iteration = 0
    endpoint_surface_recovery_ids = set(
        planning_assignments.loc[
            planning_assignments["assignment_source"].eq(
                "target_access_surface_candidate"
            ),
            "assigned_segment_id",
        ].astype(str)
    )
    while True:
        additional_junction_fallbacks = (
            set(junction_carriers.fallback_segment_ids) - fallback_segments
        )
        if not additional_junction_fallbacks:
            break
        retryable_endpoint_surface_ids = (
            additional_junction_fallbacks
            .intersection(endpoint_surface_recovery_ids)
            .difference(endpoint_surface_rescue_ids)
        )
        if retryable_endpoint_surface_ids:
            endpoint_surface_rescue_ids.update(retryable_endpoint_surface_ids)
            carrier_plan = plan_segment_carriers(
                target_coverage.segments,
                skeleton.scoped_roads,
                planning_assignments,
                run_id=cfg.run_id,
                explicit_pairs=evidence.explicit_road_pairs,
                drivezones=inputs.drivezones,
                target_reference_axes=carrier_reference_axes,
                directional_member_roles=directional_member_roles_for_publication,
                minimum_member_coverage=cfg.member_takeover_min_coverage,
                sample_spacing_m=cfg.smoothing_sample_spacing_m,
                completion_min_coverage=cfg.completion_surface_min_coverage,
                maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
                required_endpoint_surfaces=required_endpoint_surfaces,
                endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
                required_through_surfaces=required_through_surfaces,
                forced_retained_segment_ids=fallback_segments,
            )
            movement_split = _split_physical_carriers(
                carrier_plan.carriers,
                evidence,
                junctions,
                cfg,
                endpoint_trim_segment_ids,
            )
            geometry, junction_carriers = materialize_network_geometry(
                movement_split.carriers,
                skeleton.scoped_roads,
                junctions.junction_units,
                junctions.access_relations,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_roads,
                evidence.explicit_road_pairs,
                config=cfg,
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            node_build = build_nodes_and_connect_roads(
                geometry.roads,
                junctions.junction_units,
                junctions.access_relations,
                evidence.explicit_road_pairs,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_nodes,
                config=cfg,
                materialized_ordinary_group_ids=set(
                    junction_carriers.materialized_group_ids
                ),
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            continue
        junction_carrier_fallback_iteration += 1
        rejected_spokes = junction_carriers.audit[
            junction_carriers.audit["carrier_decision"].eq("rejected")
            & junction_carriers.audit["fallback_segment_ids"].fillna("").map(
                lambda value: bool(
                    set(str(value).split(",")).intersection(
                        additional_junction_fallbacks
                    )
                )
            )
        ].copy()
        rejected_spokes["pipeline_stage"] = (
            "post_semantic_junction_fallback_"
            f"{junction_carrier_fallback_iteration}"
        )
        junction_carrier_fallback_frames.append(rejected_spokes)
        fallback_segments.update(additional_junction_fallbacks)
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    junction_carrier_fallback_triggers = (
        gpd.GeoDataFrame(
            pd.concat(junction_carrier_fallback_frames, ignore_index=True),
            geometry="geometry",
            crs=junction_carriers.audit.crs,
        )
        if junction_carrier_fallback_frames
        else junction_carriers.audit.iloc[0:0].copy()
    )
    forced_through_access_ids = set(
        _audit_segment_access_realization(
            junctions.access_relations,
            node_build.roads,
            node_build.nodes,
            cfg.run_id,
        ).loc[
            lambda frame: ~frame["access_realized"]
            & frame["access_type"].eq("THROUGH")
            & frame["segment_id"].astype(str).isin(core_target_ids),
            "access_id",
        ].astype(str)
    )
    if forced_through_access_ids:
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_through_access_ids=forced_through_access_ids,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    geometry_quality = audit_built_road_geometry(
        node_build.roads,
        evidence.geometry_sources,
        node_build.completion_sources,
        config=cfg,
    )
    geometry_fallback_triggers = geometry_quality.audit[
        geometry_quality.audit["hard_failure"]
    ].copy()
    additional_geometry_fallbacks = (
        geometry_quality.fallback_segment_ids - fallback_segments
    )
    if additional_geometry_fallbacks:
        geometry_fallback_triggers["pipeline_stage"] = "pre_geometry_fallback"
        fallback_segments.update(additional_geometry_fallbacks)
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_through_access_ids=forced_through_access_ids,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        geometry_quality = audit_built_road_geometry(
            node_build.roads,
            evidence.geometry_sources,
            node_build.completion_sources,
            config=cfg,
        )
    access_realization = _audit_segment_access_realization(
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        cfg.run_id,
    )
    pre_access_roads = node_build.roads.copy()
    pre_access_nodes = node_build.nodes.copy()
    pre_access_carriers = movement_split.carriers.copy()
    pre_access_movement_audit = movement_split.audit.copy()
    pre_access_realization = access_realization.copy()
    access_fallback_triggers = access_realization[
        ~access_realization["access_realized"]
    ].copy()
    additional_access_fallbacks = set(
        access_fallback_triggers["segment_id"].astype(str)
    ) - fallback_segments
    if additional_access_fallbacks:
        access_fallback_triggers["pipeline_stage"] = "pre_access_fallback"
        fallback_segments.update(additional_access_fallbacks)
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_through_access_ids=forced_through_access_ids,
            forced_retained_segment_ids=fallback_segments,
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        geometry_quality = audit_built_road_geometry(
            node_build.roads,
            evidence.geometry_sources,
            node_build.completion_sources,
            config=cfg,
        )
        access_realization = _audit_segment_access_realization(
            junctions.access_relations,
            node_build.roads,
            node_build.nodes,
            cfg.run_id,
        )
    continuity_fallback_frames: list[gpd.GeoDataFrame] = []
    local_connector_suppression_frames: list[gpd.GeoDataFrame] = []
    junction_carrier_suppression_frames: list[gpd.GeoDataFrame] = []
    suppressed_local_connector_keys: set[str] = set()
    suppressed_junction_carrier_ids: set[str] = set()
    continuity_iteration = 0
    while True:
        continuity_audit = _audit_built_road_continuity(
            node_build.roads,
            node_build.nodes,
            junctions.access_relations,
            node_build.endpoint_audit,
            run_id=cfg.run_id,
            maximum_endpoint_shift_m=cfg.relation_endpoint_max_distance_m,
        )
        continuity_failures = continuity_audit[
            continuity_audit["hard_failure"]
        ].copy()
        road_by_id = {
            str(row.id): row
            for row in node_build.roads.itertuples()
        }
        failed_local_connector_ids = {
            str(row.road_id)
            for row in continuity_failures.itertuples()
            if str(getattr(road_by_id.get(str(row.road_id)), "carrier_role", ""))
            == "local_connector"
        }
        new_suppressed_local_connector_keys = {
            str(getattr(road_by_id[road_id], "patch_road_key", ""))
            for road_id in failed_local_connector_ids
            if str(getattr(road_by_id[road_id], "patch_road_key", ""))
        } - suppressed_local_connector_keys
        if new_suppressed_local_connector_keys:
            suppressed_local_connector_keys.update(
                new_suppressed_local_connector_keys
            )
            suppression = continuity_failures[
                continuity_failures["road_id"]
                .astype(str)
                .isin(failed_local_connector_ids)
            ].copy()
            suppression["patch_road_key"] = suppression["road_id"].astype(str).map(
                {
                    road_id: str(
                        getattr(road_by_id[road_id], "patch_road_key", "")
                    )
                    for road_id in failed_local_connector_ids
                }
            )
            suppression["original_reason_codes"] = suppression["reason_codes"]
            suppression["reason_codes"] = (
                "incomplete_local_connector_suppressed_current_scope"
            )
            suppression["pipeline_stage"] = "pre_continuity_local_suppression"
            local_connector_suppression_frames.append(suppression)
            carrier_plan = plan_segment_carriers(
                target_coverage.segments,
                skeleton.scoped_roads,
                planning_assignments,
                run_id=cfg.run_id,
                explicit_pairs=evidence.explicit_road_pairs,
                drivezones=inputs.drivezones,
                target_reference_axes=carrier_reference_axes,
                directional_member_roles=directional_member_roles_for_publication,
                minimum_member_coverage=cfg.member_takeover_min_coverage,
                sample_spacing_m=cfg.smoothing_sample_spacing_m,
                completion_min_coverage=cfg.completion_surface_min_coverage,
                maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
                required_endpoint_surfaces=required_endpoint_surfaces,
                endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
                required_through_surfaces=required_through_surfaces,
                forced_through_access_ids=forced_through_access_ids,
                forced_retained_segment_ids=fallback_segments,
                forced_suppressed_local_connector_keys=(
                    suppressed_local_connector_keys
                ),
            )
            movement_split = _split_physical_carriers(
                carrier_plan.carriers,
                evidence,
                junctions,
                cfg,
                endpoint_trim_segment_ids,
            )
            geometry, junction_carriers = materialize_network_geometry(
                movement_split.carriers,
                skeleton.scoped_roads,
                junctions.junction_units,
                junctions.access_relations,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_roads,
                evidence.explicit_road_pairs,
                config=cfg,
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            geometry, junction_carriers = _suppress_junction_carrier_roads(
                geometry,
                junction_carriers,
                suppressed_junction_carrier_ids,
            )
            node_build = build_nodes_and_connect_roads(
                geometry.roads,
                junctions.junction_units,
                junctions.access_relations,
                evidence.explicit_road_pairs,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_nodes,
                config=cfg,
                materialized_ordinary_group_ids=set(
                    junction_carriers.materialized_group_ids
                ),
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            continue
        failed_junction_carrier_ids = _orphan_junction_carrier_ids(
            continuity_failures,
            node_build.roads,
        )
        new_suppressed_junction_carrier_ids = (
            failed_junction_carrier_ids - suppressed_junction_carrier_ids
        )
        if new_suppressed_junction_carrier_ids:
            suppressed_junction_carrier_ids.update(
                new_suppressed_junction_carrier_ids
            )
            suppression = continuity_failures[
                continuity_failures["road_id"]
                .astype(str)
                .isin(new_suppressed_junction_carrier_ids)
            ].copy()
            suppression["original_reason_codes"] = suppression["reason_codes"]
            suppression["reason_codes"] = (
                "orphan_junction_carrier_suppressed_after_endpoint_coordination"
            )
            suppression["pipeline_stage"] = (
                "pre_continuity_junction_carrier_suppression"
            )
            junction_carrier_suppression_frames.append(suppression)
            geometry, junction_carriers = _suppress_junction_carrier_roads(
                geometry,
                junction_carriers,
                suppressed_junction_carrier_ids,
            )
            node_build = build_nodes_and_connect_roads(
                geometry.roads,
                junctions.junction_units,
                junctions.access_relations,
                evidence.explicit_road_pairs,
                inputs.drivezones,
                inputs.t01_nodes,
                inputs.full_rcsd_nodes,
                config=cfg,
                materialized_ordinary_group_ids=set(
                    junction_carriers.materialized_group_ids
                ),
                semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
            )
            continue
        additional_continuity_fallbacks = set(
            continuity_failures["segment_id"].astype(str)
        ) - fallback_segments
        if not additional_continuity_fallbacks:
            break
        continuity_iteration += 1
        iteration_failures = continuity_failures[
            continuity_failures["segment_id"]
            .astype(str)
            .isin(additional_continuity_fallbacks)
        ].copy()
        iteration_failures["pipeline_stage"] = (
            f"pre_continuity_fallback_{continuity_iteration}"
        )
        continuity_fallback_frames.append(iteration_failures)
        fallback_segments.update(additional_continuity_fallbacks)
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_through_access_ids=forced_through_access_ids,
            forced_retained_segment_ids=fallback_segments,
            forced_suppressed_local_connector_keys=(
                suppressed_local_connector_keys
            ),
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        geometry, junction_carriers = _suppress_junction_carrier_roads(
            geometry,
            junction_carriers,
            suppressed_junction_carrier_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
    continuity_fallback_triggers = (
        gpd.GeoDataFrame(
            pd.concat(continuity_fallback_frames, ignore_index=True),
            geometry="geometry",
            crs=continuity_audit.crs,
        )
        if continuity_fallback_frames
        else continuity_audit.iloc[0:0].copy()
    )
    local_connector_suppressions = (
        gpd.GeoDataFrame(
            pd.concat(local_connector_suppression_frames, ignore_index=True),
            geometry="geometry",
            crs=continuity_audit.crs,
        )
        if local_connector_suppression_frames
        else continuity_audit.iloc[0:0].copy()
    )
    junction_carrier_suppressions = (
        gpd.GeoDataFrame(
            pd.concat(junction_carrier_suppression_frames, ignore_index=True),
            geometry="geometry",
            crs=continuity_audit.crs,
        )
        if junction_carrier_suppression_frames
        else continuity_audit.iloc[0:0].copy()
    )
    swsd_topology_fallback_frames: list[gpd.GeoDataFrame] = []
    swsd_topology_iteration = 0
    while True:
        swsd_topology = audit_swsd_access_direction_topology(
            target_coverage.segments,
            skeleton.scoped_roads,
            inputs.t01_nodes,
            junctions.access_relations,
            node_build.roads,
            node_build.nodes,
            run_id=cfg.run_id,
        )
        additional_topology_fallbacks = (
            set(swsd_topology.fallback_segment_ids)
            - fallback_segments
        )
        if not additional_topology_fallbacks:
            break
        swsd_topology_iteration += 1
        iteration_failures = swsd_topology.audit[
            ~swsd_topology.audit["topology_preserved"]
            & swsd_topology.audit["segment_id"]
            .astype(str)
            .isin(additional_topology_fallbacks)
        ].copy()
        iteration_failures["pipeline_stage"] = (
            "pre_swsd_topology_fallback_"
            f"{swsd_topology_iteration}"
        )
        swsd_topology_fallback_frames.append(iteration_failures)
        fallback_segments.update(additional_topology_fallbacks)
        (
            access_recovery,
            planning_assignments,
            _,
        ) = recoordinate_access_recovery_assignments(
            access_recovery,
            evidence.carrier_assignments,
            node_build.roads,
            forced_retained_segment_ids=fallback_segments,
        )
        carrier_plan = plan_segment_carriers(
            target_coverage.segments,
            skeleton.scoped_roads,
            planning_assignments,
            run_id=cfg.run_id,
            explicit_pairs=evidence.explicit_road_pairs,
            drivezones=inputs.drivezones,
            target_reference_axes=carrier_reference_axes,
            directional_member_roles=directional_member_roles_for_publication,
            minimum_member_coverage=cfg.member_takeover_min_coverage,
            sample_spacing_m=cfg.smoothing_sample_spacing_m,
            completion_min_coverage=cfg.completion_surface_min_coverage,
            maximum_target_main_angle_deg=cfg.lane_recovery_max_angle_deg,
            required_endpoint_surfaces=required_endpoint_surfaces,
            endpoint_surface_segment_ids=endpoint_surface_rescue_ids,
            required_through_surfaces=required_through_surfaces,
            forced_through_access_ids=forced_through_access_ids,
            forced_retained_segment_ids=fallback_segments,
            forced_suppressed_local_connector_keys=(
                suppressed_local_connector_keys
            ),
        )
        movement_split = _split_physical_carriers(
            carrier_plan.carriers,
            evidence,
            junctions,
            cfg,
            endpoint_trim_segment_ids,
        )
        geometry, junction_carriers = materialize_network_geometry(
            movement_split.carriers,
            skeleton.scoped_roads,
            junctions.junction_units,
            junctions.access_relations,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_roads,
            evidence.explicit_road_pairs,
            config=cfg,
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        geometry, junction_carriers = _suppress_junction_carrier_roads(
            geometry,
            junction_carriers,
            suppressed_junction_carrier_ids,
        )
        node_build = build_nodes_and_connect_roads(
            geometry.roads,
            junctions.junction_units,
            junctions.access_relations,
            evidence.explicit_road_pairs,
            inputs.drivezones,
            inputs.t01_nodes,
            inputs.full_rcsd_nodes,
            config=cfg,
            materialized_ordinary_group_ids=set(
                junction_carriers.materialized_group_ids
            ),
            semantic_endpoint_segment_ids=semantic_endpoint_retry_ids,
        )
        continuity_audit = _audit_built_road_continuity(
            node_build.roads,
            node_build.nodes,
            junctions.access_relations,
            node_build.endpoint_audit,
            run_id=cfg.run_id,
            maximum_endpoint_shift_m=cfg.relation_endpoint_max_distance_m,
        )
    swsd_topology_fallback_triggers = (
        gpd.GeoDataFrame(
            pd.concat(
                swsd_topology_fallback_frames,
                ignore_index=True,
            ),
            geometry="geometry",
            crs=swsd_topology.audit.crs,
        )
        if swsd_topology_fallback_frames
        else swsd_topology.audit.iloc[0:0].copy()
    )
    if not access_recovery.empty:
        eligible_recovery = access_recovery[
            access_recovery["recovery_eligible"].fillna(False).astype(bool)
        ]
        released_recovery = access_recovery[
            access_recovery[
                "recovery_released_conflict_segment_ids"
            ].fillna("").ne("")
        ]
        evidence_summary = dict(evidence.summary)
        evidence_summary["access_surface_recovery_eligible_count"] = int(
            len(eligible_recovery)
        )
        evidence_summary["access_surface_recovery_conflict_count"] = int(
            len(access_recovery) - len(eligible_recovery)
        )
        evidence_summary[
            "access_surface_recovery_released_after_fallback_count"
        ] = int(len(released_recovery))
        target_fragment_audit = evidence.target_fragment_audit[
            ~evidence.target_fragment_audit["assignment_source"].eq(
                "target_access_surface_candidate"
            )
        ].copy()
        evidence = replace(
            evidence,
            target_fragment_audit=gpd.GeoDataFrame(
                pd.concat(
                    [target_fragment_audit, access_recovery],
                    ignore_index=True,
                    sort=False,
                ),
                geometry="geometry",
                crs=evidence.target_fragment_audit.crs,
            ),
            summary=evidence_summary,
        )
    lineage_split = split_roads_at_stable_lineage_boundaries(
        node_build.roads,
        geometry.geometry_sources,
        evidence.geometry_sources,
        run_id=cfg.run_id,
        minimum_part_length_m=cfg.lineage_split_min_part_length_m,
        maximum_handoff_gap_m=cfg.lineage_split_max_handoff_gap_m,
        maximum_handoff_overlap_m=cfg.lineage_split_max_handoff_overlap_m,
        lane_group_relations=evidence.road_lane_relations,
        maximum_lane_group_distance_m=cfg.lineage_lane_group_max_distance_m,
        protected_split_surface=junctions.junction_units.geometry.union_all().buffer(
            cfg.junction_endpoint_buffer_m
        ),
        existing_node_ids=set(node_build.nodes["id"]),
    )
    if lineage_split.summary["split_boundary_count"]:
        geometry_summary = dict(geometry.summary)
        geometry_summary.update(
            {
                "road_count": int(len(lineage_split.roads)),
                "built_road_count": int(
                    lineage_split.roads["realization"].eq("built").sum()
                ),
                "retained_road_count": int(
                    lineage_split.roads["realization"].eq("retained").sum()
                ),
            }
        )
        geometry = RoadGeometryResult(
            lineage_split.roads,
            lineage_split.geometry_sources,
            geometry_summary,
        )
        node_build = attach_lineage_split_to_node_build(
            node_build,
            lineage_split,
            run_id=cfg.run_id,
        )
        continuity_audit = _audit_built_road_continuity(
            node_build.roads,
            node_build.nodes,
            junctions.access_relations,
            node_build.endpoint_audit,
            run_id=cfg.run_id,
            maximum_endpoint_shift_m=cfg.relation_endpoint_max_distance_m,
        )
    redundant_retained = try_suppress_redundant_retained_roads(
        geometry,
        node_build,
        continuity_audit,
        movement_split.carriers,
        target_coverage.segments,
        skeleton.scoped_roads,
        inputs.t01_nodes,
        junctions.access_relations,
        config=cfg,
    )
    geometry = redundant_retained.geometry
    node_build = redundant_retained.node_build
    continuity_audit = redundant_retained.continuity_audit
    swsd_topology = audit_swsd_access_direction_topology(
        target_coverage.segments,
        skeleton.scoped_roads,
        inputs.t01_nodes,
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        run_id=cfg.run_id,
    )
    geometry_quality = audit_built_road_geometry(
        node_build.roads,
        evidence.geometry_sources,
        node_build.completion_sources,
        config=cfg,
    )
    node_build = replace(
        node_build,
        roads=apply_review_flags(
            node_build.roads,
            node_build.endpoint_audit,
            geometry_quality.audit,
        ),
    )
    access_realization = _audit_segment_access_realization(
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        cfg.run_id,
    )
    topology = compile_road_next_road(
        node_build.roads,
        node_build.nodes,
        evidence.explicit_road_pairs,
        run_id=cfg.run_id,
    )
    junction_movement = materialize_swsd_junction_movement_contract(
        target_coverage.segments,
        skeleton.scoped_roads,
        inputs.t01_nodes,
        junctions.junction_units,
        junctions.access_relations,
        node_build.roads,
        node_build.nodes,
        topology,
        run_id=cfg.run_id,
        maximum_surface_distance_m=(
            cfg.relation_endpoint_max_distance_m
        ),
        connection_evidence=node_build.connection_evidence,
    )
    topology = junction_movement.topology
    swsd_junction_structure = build_swsd_junction_structure_audit(
        junctions.junction_units,
        junctions.access_relations,
        swsd_topology.audit,
        junction_movement.audit,
        run_id=cfg.run_id,
    )
    road_lane_relation = _road_lane_relation(
        evidence.road_lane_relations,
        node_build.roads,
    )
    lane_topo = _project_lane_topo(
        evidence.lane_topo_audit,
        node_build.roads,
        topology.road_next_road,
        fallback_patch_road_keys=set(
            evidence.carrier_assignments.loc[
                evidence.carrier_assignments["assigned_segment_id"]
                .astype(str)
                .isin(fallback_segments),
                "patch_road_key",
            ].astype(str)
        ),
        rejected_patch_road_pairs=rejected_lane_topo_pairs(
            lane_topo_connection_exclusions,
            node_build.connection_evidence,
        ),
        connection_evidence=node_build.connection_evidence,
        road_lane_relation=road_lane_relation,
    )
    segment_road_relation = _segment_road_relation(node_build.roads)
    geometry_sources = _final_geometry_sources(
        node_build.roads,
        geometry.geometry_sources,
        node_build.completion_sources,
        cfg.run_id,
    )
    soft_review = _soft_review_features(
        node_build.roads,
        node_build.endpoint_audit,
        geometry_quality.audit,
        cfg.run_id,
    )
    target_realization = audit_target_realization(
        target_coverage.segments,
        node_build.roads,
        segment_plans=carrier_plan.segment_plans,
        nodes=node_build.nodes,
        segment_accesses=junctions.access_relations,
        junction_units=junctions.junction_units,
        road_next_road=topology.road_next_road,
        run_id=cfg.run_id,
    )
    node_connection_evidence = node_build.connection_evidence.copy()
    node_connection_evidence["pipeline_stage"] = "final"
    if not rejected_lane_connections.empty:
        rejected_lane_connections["pipeline_stage"] = "pre_fallback"
        node_connection_evidence = gpd.GeoDataFrame(
            pd.concat(
                [rejected_lane_connections, node_connection_evidence],
                ignore_index=True,
            ),
            geometry="geometry",
            crs=node_build.connection_evidence.crs,
        )
    original_rcsd_roads = _scope_to_drivezones(
        inputs.full_rcsd_roads,
        inputs.drivezones,
    )
    comparison = {
        "new_built_roads": node_build.roads[
            node_build.roads["realization"].eq("built")
        ].copy(),
        "new_retained_roads": node_build.roads[
            node_build.roads["realization"].eq("retained")
        ].copy(),
        "original_swsd_roads": skeleton.scoped_roads,
        "original_swsd_nodes": _nodes_for_road_endpoints(
            inputs.swsd_nodes,
            skeleton.scoped_roads,
        ),
        "original_rcsd_roads": original_rcsd_roads,
        "original_rcsd_nodes": _nodes_for_road_endpoints(
            inputs.full_rcsd_nodes,
            original_rcsd_roads,
        ),
        "original_patch_roads": inputs.patch_roads,
        "patch_road_centers": evidence.patch_road_centers,
        "patch_lanes": inputs.patch_lanes,
        "patch_boundaries": inputs.patch_boundaries,
        "drivezones": inputs.drivezones,
        "patch_intersections": inputs.patch_intersections,
        "t07_accepted_surfaces": inputs.t07_surfaces,
        "t03_accepted_surfaces": inputs.t03_surfaces,
        "t04_accepted_surfaces": inputs.t04_surfaces,
    }
    if target_coverage.summary["contract_enabled"]:
        comparison["target_core_segments"] = target_coverage.segments[
            target_coverage.segments["target_class"].eq("core_trunk")
        ].copy()
        comparison["target_advance_right_segments"] = target_coverage.segments[
            target_coverage.segments["target_class"].eq("advance_right")
        ].copy()
        comparison["target_boundary_review_segments"] = target_coverage.segments[
            target_coverage.segments["target_class"].eq("boundary_review")
        ].copy()
        comparison["target_direct_build_required"] = target_coverage.segments[
            target_coverage.segments["direct_build_required"]
        ].copy()
        comparison["target_patch_data_insufficient"] = target_coverage.segments[
            target_coverage.segments["direct_build_eligibility"].eq(
                "patch_data_insufficient"
            )
        ].copy()
        comparison["target_reality_change_clues"] = target_coverage.segments[
            target_coverage.segments["direct_build_eligibility"].eq(
                "reality_change"
            )
        ].copy()
        if not target_coverage.anchors.empty:
            comparison["target_rcsd_anchor_segments"] = target_coverage.anchors
        if not target_realization.audit.empty:
            comparison["target_realization"] = target_realization.audit
        if not swsd_directional_paths.audit.empty:
            comparison["swsd_directional_paths"] = (
                swsd_directional_paths.audit
            )
    frozen_v3 = _read_frozen_v3(cfg.frozen_v3_root, cfg.analysis_crs)
    if frozen_v3 is not None and not frozen_v3.empty:
        comparison["frozen_v3_roads"] = frozen_v3
    published = publish_segment_first_layers(
        cfg.output_dir,
        roads=node_build.roads,
        nodes=node_build.nodes,
        road_next_road=topology.road_next_road,
        audit_layers={
            "target_coverage_contract": target_coverage.segments,
            "segment_reference_axis_audit": segment_reference_axes.audit,
            "swsd_segment_directional_paths": (
                swsd_directional_paths.audit
            ),
            **(
                {"target_realization": target_realization.audit}
                if not target_realization.audit.empty
                else {}
            ),
            **(
                {"target_rcsd_segment_anchors": target_coverage.anchors}
                if not target_coverage.anchors.empty
                else {}
            ),
            **(
                {"target_anchor_assignment": evidence.target_anchor_audit}
                if not evidence.target_anchor_audit.empty
                else {}
            ),
            **(
                {"target_carrier_fragments": evidence.target_fragment_audit}
                if not evidence.target_fragment_audit.empty
                else {}
            ),
            "segment_build_units": carrier_plan.segment_plans,
            "junction_units": junctions.junction_units,
            "junction_endpoint_surfaces": build_endpoint_surface_audit(
                junctions.junction_units
            ),
            "segment_accesses": junctions.access_relations,
            "junction_source_conflicts": junctions.source_conflicts,
            **(
                {
                    "junction_carrier_fallback_triggers": (
                        junction_carrier_fallback_triggers
                    )
                }
                if not junction_carrier_fallback_triggers.empty
                else {}
            ),
            "road_carriers": movement_split.carriers,
            **(
                {"junction_internal_carriers": junction_carriers.audit}
                if not junction_carriers.audit.empty
                else {}
            ),
            **(
                {"movement_split_audit": movement_split.audit}
                if not movement_split.audit.empty
                else {}
            ),
            **(
                {"road_lineage_split_audit": lineage_split.audit}
                if not lineage_split.audit.empty
                else {}
            ),
            **(
                {
                    "redundant_retained_suppressions": (
                        redundant_retained.audit
                    )
                }
                if not redundant_retained.audit.empty
                else {}
            ),
            "road_geometry_sources": geometry_sources,
            "endpoint_coordination": node_build.endpoint_audit,
            "node_connection_evidence": node_connection_evidence,
            "road_geometry_quality": geometry_quality.audit,
            "built_road_continuity": continuity_audit,
            "segment_access_realization": access_realization,
            "swsd_topology_contract": swsd_topology.audit,
            "swsd_junction_movement_contract": (
                junction_movement.audit
            ),
            "swsd_junction_structure": swsd_junction_structure,
            "pre_access_roads": pre_access_roads,
            "pre_access_nodes": pre_access_nodes,
            "pre_access_carriers": pre_access_carriers,
            "pre_access_realization": pre_access_realization,
            **(
                {"pre_access_movement_audit": pre_access_movement_audit}
                if not pre_access_movement_audit.empty
                else {}
            ),
            **(
                {"segment_fallback_triggers": fallback_triggers}
                if not fallback_triggers.empty
                else {}
            ),
            **(
                {
                    "lane_topo_connection_exclusions": (
                        lane_topo_connection_exclusions
                    )
                }
                if not lane_topo_connection_exclusions.empty
                else {}
            ),
            **(
                {"access_fallback_triggers": access_fallback_triggers}
                if not access_fallback_triggers.empty
                else {}
            ),
            **(
                {"geometry_fallback_triggers": geometry_fallback_triggers}
                if not geometry_fallback_triggers.empty
                else {}
            ),
            **(
                {"continuity_fallback_triggers": continuity_fallback_triggers}
                if not continuity_fallback_triggers.empty
                else {}
            ),
            **(
                {
                    "swsd_topology_fallback_triggers": (
                        swsd_topology_fallback_triggers
                    )
                }
                if not swsd_topology_fallback_triggers.empty
                else {}
            ),
            **(
                {
                    "local_connector_suppressions": (
                        local_connector_suppressions
                    )
                }
                if not local_connector_suppressions.empty
                else {}
            ),
            **(
                {
                    "junction_carrier_suppressions": (
                        junction_carrier_suppressions
                    )
                }
                if not junction_carrier_suppressions.empty
                else {}
            ),
            "lane_topo_projection": lane_topo,
            "patch_road_assignment": evidence.assignments,
            "patch_road_rejection": evidence.rejections,
            **({"soft_review_features": soft_review} if not soft_review.empty else {}),
        },
        relation_layers={
            "segment_road_relation": segment_road_relation,
            "road_lane_relation": road_lane_relation,
            "junction_node_relation": _junction_node_relation(node_build.nodes),
        },
        comparison_layers=comparison,
    )
    quality = run_independent_quality(
        published.formal_gpkg,
        published.audit_gpkg,
        cfg.output_dir,
        expected_crs=cfg.analysis_crs,
        expected_segment_count=len(skeleton.segment_units),
        run_id=cfg.run_id,
    )
    qgis = build_qgis_project(cfg.output_dir, run_id=cfg.run_id)
    core_gates = {
        "all_t01_segments_in_skeleton": len(skeleton.segment_units) == len(carrier_plan.segment_plans),
        "all_segments_publishable": bool(carrier_plan.segment_plans["segment_publishable"].all()),
        "every_segment_has_road": set(carrier_plan.segment_plans["segment_id"].astype(str)).issubset(
            set(node_build.roads["segment_id"].astype(str))
        ),
        "built_road_swsd_splice_zero": geometry.summary["built_swsd_splice_count"] == 0,
        "road_node_reference_complete": node_build.summary["missing_node_reference_count"] == 0,
        "junction_access_resolved": junctions.summary["unresolved_access_count"] == 0,
        "formal_layers_written": published.formal_gpkg.is_file(),
        "final_connection_rejection_accounted": set(
            node_build.connection_evidence.loc[
                node_build.connection_evidence["connection_decision"].eq("rejected")
                & node_build.connection_evidence["pair_source"].isin(
                    LANE_TOPO_PAIR_SOURCES
                ),
                "source_relation_id",
            ].astype(str)
        ).issubset(
            set(
                lane_topo.loc[
                    lane_topo["projection_state"].isin(
                        {
                            "excluded_physical_connection_evidence_rejected",
                            "excluded_segment_conflict_retained",
                        }
                    ),
                    "lane_topo_id",
                ].astype(str)
            )
        ),
        "lane_topo_projection_unresolved_zero": int(
            lane_topo["projection_state"].eq("review_shared_node_relation_missing").sum()
        )
        == 0,
        "geometry_hard_failure_zero": geometry_quality.summary["hard_failure_count"]
        == 0,
        "segment_access_realization_complete": bool(
            access_realization["access_realized"].all()
        ),
        "movement_anchor_rejection_zero": movement_split.summary[
            "rejected_anchor_count"
        ]
        == 0,
        "junction_carrier_rejection_resolved": not bool(
            junction_carriers.fallback_segment_ids
        ),
        "built_road_continuity_complete": bool(
            not continuity_audit["hard_failure"].any()
        ),
        "swsd_access_direction_topology_preserved": bool(
            swsd_topology.summary["gate_pass"]
        ),
        "swsd_junction_movement_topology_preserved": bool(
            junction_movement.summary["gate_pass"]
        ),
        "mandatory_target_high_precision_complete": (
            bool(target_realization.summary["target_gate_pass"])
            if target_coverage.summary["contract_enabled"]
            else True
        ),
    }
    core_gate_pass = all(core_gates.values())
    elapsed = time.perf_counter() - started
    terminal_status = (
        "technical_passed"
        if core_gate_pass and quality.gate_pass and qgis.readback_pass
        else "failed"
    )
    summary = build_run_summary(
        run_id=cfg.run_id,
        analysis_crs=cfg.analysis_crs,
        terminal_status=terminal_status,
        core_gate_pass=core_gate_pass,
        core_gates=core_gates,
        skeleton=skeleton.summary,
        target_coverage=target_coverage.summary,
        target_realization=target_realization.summary,
        junctions=junctions.summary,
        evidence=evidence.summary,
        carrier_plan=carrier_plan.summary,
        movement_split=movement_split.summary,
        road_lineage_split=lineage_split.summary,
        swsd_topology=swsd_topology.summary,
        swsd_junction_movements=junction_movement.summary,
        junction_internal_carriers=junction_carriers.summary,
        junction_carrier_fallback_triggers=(
            junction_carrier_fallback_triggers
        ),
        geometry=geometry.summary,
        geometry_quality=geometry_quality.summary,
        continuity_audit=continuity_audit,
        suppressed_local_connector_keys=suppressed_local_connector_keys,
        suppressed_junction_carrier_ids=suppressed_junction_carrier_ids,
        access_realization=access_realization,
        nodes=node_build.summary,
        topology=topology.summary,
        lane_topo=lane_topo,
        soft_review=soft_review,
        independent_quality=quality.payload,
        qgis_project=qgis.project_path,
        qgis_layer_count=qgis.layer_count,
        qgis_readback_pass=qgis.readback_pass,
        qgis_missing_layers=qgis.missing_layers,
        elapsed_seconds=elapsed,
        formal_gpkg=published.formal_gpkg,
        audit_gpkg=published.audit_gpkg,
        relations_gpkg=published.relations_gpkg,
        comparison_gpkg=published.comparison_gpkg,
        independent_quality_json=quality.json_path,
    )
    summary_path = cfg.output_dir / "p04_segment_first_summary.json"
    report_path = cfg.output_dir / "p04_segment_first_report.md"
    write_json(summary_path, summary)
    report_path.write_text(render_run_report(summary), encoding="utf-8")
    return SegmentFirstResult(
        run_id=cfg.run_id,
        output_dir=cfg.output_dir,
        formal_gpkg=published.formal_gpkg,
        audit_gpkg=published.audit_gpkg,
        relations_gpkg=published.relations_gpkg,
        summary_path=summary_path,
        report_path=report_path,
        independent_quality_path=quality.json_path,
        qgis_project_path=qgis.project_path,
        terminal_status=terminal_status,
        core_gate_pass=core_gate_pass,
    )


def _orphan_junction_carrier_ids(
    continuity_failures: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> set[str]:
    if continuity_failures.empty or roads.empty:
        return set()
    road_by_id = {
        str(row.id): row
        for row in roads.itertuples()
    }
    return {
        str(row.road_id)
        for row in continuity_failures.itertuples()
        if str(getattr(road_by_id.get(str(row.road_id)), "owner_type", ""))
        == "JUNCTION_UNIT"
        and str(
            getattr(road_by_id.get(str(row.road_id)), "carrier_role", "")
        )
        == "junction_surface_carrier"
    }


def _suppress_junction_carrier_roads(
    geometry: RoadGeometryResult,
    junction_carriers: JunctionCarrierResult,
    suppressed_ids: set[str],
) -> tuple[RoadGeometryResult, JunctionCarrierResult]:
    if not suppressed_ids:
        return geometry, junction_carriers
    roads = geometry.roads[
        ~geometry.roads["id"].astype(str).isin(suppressed_ids)
    ].copy()
    sources = geometry.geometry_sources[
        ~geometry.geometry_sources["road_id"].astype(str).isin(suppressed_ids)
    ].copy()
    geometry_summary = dict(geometry.summary)
    geometry_summary.update(
        {
            "road_count": int(len(roads)),
            "built_road_count": int(roads["realization"].eq("built").sum()),
            "retained_road_count": int(roads["realization"].eq("retained").sum()),
            "junction_carrier_road_count": int(
                roads["owner_type"].fillna("").eq("JUNCTION_UNIT").sum()
            ),
        }
    )
    carrier_roads = junction_carriers.roads[
        ~junction_carriers.roads["id"].astype(str).isin(suppressed_ids)
    ].copy()
    carrier_sources = junction_carriers.geometry_sources[
        ~junction_carriers.geometry_sources["road_id"]
        .astype(str)
        .isin(suppressed_ids)
    ].copy()
    carrier_summary = dict(junction_carriers.summary)
    carrier_summary["junction_carrier_road_count"] = int(len(carrier_roads))
    carrier_summary["orphan_suppressed_count"] = int(
        len(set(junction_carriers.roads["id"].astype(str)) & suppressed_ids)
    )
    return (
        RoadGeometryResult(roads, sources, geometry_summary),
        replace(
            junction_carriers,
            roads=carrier_roads,
            geometry_sources=carrier_sources,
            summary=carrier_summary,
        ),
    )


def _segment_road_relation(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = [
        "run_id",
        "segment_id",
        "owner_type",
        "junction_group_id",
        "id",
        "realization",
        "geometry_source",
        "patch_road_key",
        "source_patch_road_keys",
        "member_swsd_road_id",
        "geometry",
    ]
    result = roads[columns].copy().rename(columns={"id": "road_id"})
    result["relation_state"] = "published"
    return result


def _junction_node_relation(nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = nodes[nodes["junction_group_ids"].fillna("").astype(str) != ""].copy()
    result = result[["run_id", "id", "mainnodeid", "junction_group_ids", "geometry"]]
    return result.rename(columns={"id": "node_id"})


def _audit_segment_access_realization(
    accesses: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    node_groups: dict[object, set[str]] = {}
    for node in nodes.itertuples():
        groups = {
            value
            for value in str(getattr(node, "junction_group_ids", "") or "").split(",")
            if value
        }
        mainnode = str(getattr(node, "mainnodeid", "") or "")
        if mainnode and mainnode != "0":
            groups.add(mainnode)
        node_groups[node.id] = groups
    segment_nodes: dict[str, set[object]] = {}
    for road in roads.itertuples():
        segment_nodes.setdefault(str(road.segment_id), set()).update(
            {road.snodeid, road.enodeid}
        )
    rows: list[dict[str, object]] = []
    for access in accesses.itertuples():
        candidate_nodes = segment_nodes.get(str(access.segment_id), set())
        matched = sorted(
            node_id
            for node_id in candidate_nodes
            if str(access.junction_group_id) in node_groups.get(node_id, set())
        )
        realized = bool(matched)
        rows.append(
            {
                "run_id": run_id,
                "access_id": str(access.access_id),
                "segment_id": str(access.segment_id),
                "access_type": str(access.access_type),
                "access_ordinal": int(access.access_ordinal),
                "source_node_id": str(access.source_node_id),
                "junction_group_id": str(access.junction_group_id),
                "access_realized": realized,
                "matched_node_ids": ",".join(str(value) for value in matched),
                "reason_codes": (
                    "segment_road_endpoint_in_junction_group"
                    if realized
                    else "segment_access_not_materialized"
                ),
                "geometry": access.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=accesses.crs)


def _final_geometry_sources(
    roads: gpd.GeoDataFrame,
    base_sources: gpd.GeoDataFrame,
    completions: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    completion_by_road = {
        road_id: group
        for road_id, group in completions.groupby("road_id")
    } if not completions.empty else {}
    base_by_road = {
        road_id: group.sort_values("start_fraction", kind="stable")
        for road_id, group in base_sources.groupby("road_id")
    } if not base_sources.empty else {}
    rows: list[dict[str, object]] = []
    for road in roads.itertuples():
        group = completion_by_road.get(road.id)
        start_length = 0.0
        end_length = 0.0
        source_ids: dict[str, str] = {"start": "", "end": ""}
        source_kinds: dict[str, str] = {}
        if group is not None:
            for endpoint, endpoint_group in group.groupby("endpoint"):
                length = float(endpoint_group["length_m"].sum())
                if endpoint == "start":
                    start_length = length
                elif endpoint == "end":
                    end_length = length
                source_ids[str(endpoint)] = ",".join(
                    sorted(set(endpoint_group["source_object_ids"].astype(str)))
                )
                source_kinds[str(endpoint)] = str(
                    endpoint_group.iloc[0]["geometry_source"]
                )
        total_length = float(road.geometry.length)
        completion_total = start_length + end_length
        if completion_total > total_length and completion_total > 0.0:
            scale = total_length / completion_total
            start_length *= scale
            end_length *= scale
        base_start = start_length
        base_end = max(start_length, total_length - end_length)

        def append_span(
            label: str,
            start_m: float,
            end_m: float,
            source_ids_value: str,
        ) -> None:
            if end_m - start_m <= 1e-9:
                return
            geometry = substring(road.geometry, start_m, end_m)
            rows.append(
                {
                    "run_id": run_id,
                    "road_id": road.id,
                    "segment_id": str(road.segment_id),
                    "source_span_id": f"{road.id}:{len(rows)}",
                    "geometry_source": label,
                    "source_object_ids": source_ids_value,
                    "start_fraction": start_m / total_length,
                    "end_fraction": end_m / total_length,
                    "length_m": float(geometry.length),
                    "geometry": geometry,
                }
            )

        append_span(
            source_kinds.get("start", "hp_constrained_completion"),
            0.0,
            start_length,
            source_ids["start"],
        )
        base_group = base_by_road.get(road.id)
        if base_group is None or base_group.empty:
            append_span(
                "hp_observed" if road.realization == "built" else "swsd_retained_whole",
                base_start,
                base_end,
                str(road.patch_road_key or road.member_swsd_road_id),
            )
        else:
            base_length = max(0.0, base_end - base_start)
            for base in base_group.itertuples():
                append_span(
                    str(base.geometry_source),
                    base_start + float(base.start_fraction) * base_length,
                    base_start + float(base.end_fraction) * base_length,
                    str(base.source_object_ids),
                )
        append_span(
            source_kinds.get("end", "hp_constrained_completion"),
            base_end,
            total_length,
            source_ids["end"],
        )
    return gpd.GeoDataFrame(
        rows,
        geometry="geometry",
        crs=roads.crs,
    )


def _soft_review_features(
    roads: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    geometry_quality: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    rows = []
    for road in roads[roads["review_required"].fillna(False)].itertuples():
        rows.append(
            {
                "run_id": run_id,
                "object_type": "Road",
                "object_id": str(road.id),
                "reason_codes": "input_quality_isolated",
                "geometry": road.geometry.centroid,
            }
        )
    for quality in geometry_quality[
        geometry_quality["review_required"].fillna(False)
    ].itertuples():
        rows.append(
            {
                "run_id": run_id,
                "object_type": "RoadGeometry",
                "object_id": str(quality.road_id),
                "reason_codes": str(quality.reason_codes),
                "geometry": quality.geometry.centroid,
            }
        )
    for endpoint in endpoint_audit[
        endpoint_audit["review_required"].fillna(False)
    ].itertuples():
        reason = (
            "segment_access_surface_handoff"
            if endpoint.junction_membership_source
            == "segment_access_surface_handoff"
            else "long_constrained_completion"
        )
        rows.append(
            {
                "run_id": run_id,
                "object_type": "RoadEndpoint",
                "object_id": f"{endpoint.road_id}:{endpoint.endpoint}",
                "reason_codes": reason,
                "geometry": endpoint.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)


def _scope_to_drivezones(
    roads: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if roads.empty or drivezones.empty:
        return roads
    scope = drivezones.geometry.union_all()
    indexes = list(roads.sindex.query(scope))
    return roads.iloc[indexes].copy().reset_index(drop=True)


def _nodes_for_road_endpoints(
    nodes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if nodes.empty or roads.empty:
        return nodes.iloc[0:0].copy()
    endpoint_ids = {
        canonical_id(value)
        for column in ("snodeid", "enodeid")
        if column in roads.columns
        for value in roads[column]
        if canonical_id(value)
    }
    if not endpoint_ids or "id" not in nodes.columns:
        return nodes.iloc[0:0].copy()
    return nodes[
        nodes["id"].map(canonical_id).isin(endpoint_ids)
    ].copy().reset_index(drop=True)


def _read_frozen_v3(root: Path | None, crs: str) -> gpd.GeoDataFrame | None:
    if root is None:
        return None
    path = root / "p04_hp_v3_road_graph.gpkg"
    if not path.is_file():
        return None
    layers = fiona.listlayers(path)
    layer = next((name for name in layers if "road" in name.lower() and "parent" not in name.lower()), None)
    if layer is None:
        return None
    frame = gpd.read_file(path, layer=layer)
    return frame.to_crs(crs)


__all__ = ["run_segment_first_road_direct"]
