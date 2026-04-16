from __future__ import annotations

import argparse
import json
import shutil
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_execution_contract import (
    build_stage4_representative_fields,
    evaluate_stage4_candidate_admission,
    resolve_stage4_output_kind,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    REASON_MISSING_REQUIRED_FIELD,
    Stage4RunError,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import *
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step2_step3_contract import (
    Stage4LegacyStep4Bridge,
    Stage4LegacyStep4Readiness,
    evaluate_stage4_legacy_step4_readiness,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step7_contract import (
    build_stage4_failure_step7_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    T02RunError,
    find_repo_root,
    normalize_id,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    _build_debug_focus_geometry,
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _resolve_group,
    _write_debug_rendered_map,
)


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tracemalloc_stats() -> dict[str, int]:
    if not tracemalloc.is_tracing():
        return {
            "python_tracemalloc_current_bytes": 0,
            "python_tracemalloc_peak_bytes": 0,
        }
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    return {
        "python_tracemalloc_current_bytes": current_bytes,
        "python_tracemalloc_peak_bytes": peak_bytes,
    }


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id("t02_stage4_divmerge_virtual_polygon")
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage4RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage4_divmerge_virtual_polygon" / resolved_run_id, resolved_run_id


def _write_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    current_stage: str | None,
    message: str,
    counts: dict[str, Any],
) -> None:
    write_json(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "current_stage": current_stage,
            "message": message,
            "counts": counts,
            **_tracemalloc_stats(),
        },
    )


def _record_perf_marker(
    *,
    out_path: Path,
    run_id: str,
    stage: str,
    elapsed_sec: float,
    counts: dict[str, Any],
    note: str | None = None,
) -> None:
    marker = {
        "event": "stage_marker",
        "run_id": run_id,
        "at": _now_text(),
        "stage": stage,
        "elapsed_sec": round(elapsed_sec, 6),
        "counts": counts,
        **_tracemalloc_stats(),
    }
    if note is not None:
        marker["note"] = note
    _append_jsonl(out_path, marker)

@dataclass(frozen=True)
class Stage4Artifacts:
    success: bool
    out_root: Path
    virtual_polygon_path: Path
    node_link_json_path: Path
    rcsdnode_link_json_path: Path
    audit_json_path: Path
    status_path: Path
    log_path: Path
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path
    debug_dir: Path | None = None
    rendered_map_path: Path | None = None
    status_doc: dict[str, Any] | None = None
    perf_doc: dict[str, Any] | None = None


def _make_link_doc(
    *,
    mainnodeid: str,
    kind_2: int,
    grade_2: int | None,
    target_node_ids: list[str],
    linked_node_ids: list[str],
    selected_branch_ids: list[str],
    selected_road_ids: list[str],
    coverage_missing_ids: list[str],
) -> dict[str, Any]:
    return {
        "mainnodeid": mainnodeid,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "target_node_ids": target_node_ids,
        "linked_node_ids": linked_node_ids,
        "selected_branch_ids": selected_branch_ids,
        "selected_road_ids": selected_road_ids,
        "coverage_missing_ids": coverage_missing_ids,
    }

def run_t02_stage4_divmerge_virtual_polygon(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    divstripzone_path: Optional[Union[str, Path]] = None,
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    divstripzone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
    divstripzone_crs: Optional[str] = None,
    rcsdroad_crs: Optional[str] = None,
    rcsdnode_crs: Optional[str] = None,
    debug: bool = False,
    debug_render_root: Optional[Union[str, Path]] = None,
    trace_memory: bool = True,
) -> Stage4Artifacts:
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
        Stage4RunError,
        _cover_check,
        _is_stage4_supported_node_kind,
        _node_source_kind,
        _node_source_kind_2,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step2_local_context import (
        _build_stage4_local_context,
        _load_layer,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step3_topology_skeleton import (
        _build_stage4_topology_skeleton,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_event_interpretation import (
        _build_stage4_event_interpretation,
        _evaluate_primary_rcsdnode_tolerance,
        _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover,
        _resolve_effective_target_rc_nodes,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_geometric_support import (
        _build_stage4_geometric_support_domain,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step6_polygon_assembly import (
        _build_stage4_polygon_assembly,
    )
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step7_acceptance import (
        _build_stage4_step7_acceptance,
    )

    if trace_memory and not tracemalloc.is_tracing():
        tracemalloc.start()

    started_at = time.perf_counter()
    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)

    virtual_polygon_path = out_root_path / "stage4_virtual_polygon.gpkg"
    node_link_json_path = out_root_path / "stage4_node_link.json"
    rcsdnode_link_json_path = out_root_path / "stage4_rcsdnode_link.json"
    audit_json_path = out_root_path / "stage4_audit.json"
    status_path = out_root_path / "stage4_status.json"
    log_path = out_root_path / "stage4_divmerge_virtual_polygon.log"
    progress_path = out_root_path / "stage4_progress.json"
    perf_json_path = out_root_path / "stage4_perf.json"
    perf_markers_path = out_root_path / "stage4_perf_markers.jsonl"
    debug_dir = out_root_path / "stage4_debug" if debug else None
    debug_render_path = debug_dir / f"{normalize_id(mainnodeid) or 'unknown'}.png" if debug_dir is not None else None
    rendered_maps_root = (
        Path(debug_render_root)
        if debug_render_root is not None
        else out_root_path.parent / "_rendered_maps"
    )
    rendered_map_path = rendered_maps_root / f"{normalize_id(mainnodeid) or 'unknown'}.png" if debug else None

    logger = build_logger(log_path, f"t02_stage4_divmerge_virtual_polygon.{resolved_run_id}")
    counts: dict[str, Any] = {
        "mainnodeid": normalize_id(mainnodeid),
        "node_feature_count": 0,
        "road_feature_count": 0,
        "drivezone_feature_count": 0,
        "divstripzone_feature_count": 0,
        "rcsdroad_feature_count": 0,
        "rcsdnode_feature_count": 0,
        "target_node_count": 0,
        "target_rcsdnode_count": 0,
        "selected_branch_count": 0,
        "selected_road_count": 0,
        "selected_rcsdroad_count": 0,
        "selected_rcsdnode_count": 0,
        "audit_count": 0,
    }
    audit_rows: list[dict[str, Any]] = []
    stage_timings: list[dict[str, Any]] = []

    def _snapshot(status: str, current_stage: str | None, message: str) -> None:
        counts["audit_count"] = len(audit_rows)
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status=status,
            current_stage=current_stage,
            message=message,
            counts=dict(counts),
        )

    def _mark(stage_name: str, started_at_stage: float, note: str | None = None) -> None:
        elapsed_sec = time.perf_counter() - started_at_stage
        stage_timings.append(
            {
                "stage": stage_name,
                "elapsed_sec": round(elapsed_sec, 6),
                **_tracemalloc_stats(),
            }
        )
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage=stage_name,
            elapsed_sec=elapsed_sec,
            counts=dict(counts),
            note=note,
        )

    def _write_link_json(path: Path, payload: dict[str, Any]) -> None:
        write_json(path, payload)

    try:
        _snapshot("running", "bootstrap", "Stage4 bootstrap started.")
        announce(logger, f"[T02-Stage4] start run_id={resolved_run_id}")

        load_started_at = time.perf_counter()
        nodes_layer_data = _load_layer(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
        )
        roads_layer_data = _load_layer(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
        )
        drivezone_layer_data = _load_layer(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
        )
        rcsdroad_layer_data = _load_layer(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
        )
        rcsdnode_layer_data = _load_layer(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
        )
        counts["node_feature_count"] = len(nodes_layer_data.features)
        counts["road_feature_count"] = len(roads_layer_data.features)
        counts["drivezone_feature_count"] = len(drivezone_layer_data.features)
        counts["rcsdroad_feature_count"] = len(rcsdroad_layer_data.features)
        counts["rcsdnode_feature_count"] = len(rcsdnode_layer_data.features)
        _snapshot("running", "inputs_loaded", "Input layers loaded and projected to EPSG:3857.")
        _mark("inputs_loaded", load_started_at)

        nodes = _parse_nodes(nodes_layer_data, require_anchor_fields=True)
        roads = _parse_roads(roads_layer_data, label="Road")
        rcsd_roads = _parse_roads(rcsdroad_layer_data, label="RCSDRoad")
        rcsd_nodes = _parse_rc_nodes(rcsdnode_layer_data)

        mainnodeid_norm = normalize_id(mainnodeid)
        if mainnodeid_norm is None:
            raise Stage4RunError(REASON_MAINNODEID_NOT_FOUND, "mainnodeid is empty.")

        target_group = _resolve_group(mainnodeid=mainnodeid_norm, nodes=nodes)
        representative_node, group_nodes = target_group
        representative_source_kind = _node_source_kind(representative_node)
        representative_source_kind_2 = _node_source_kind_2(representative_node)
        representative_kind_2 = representative_source_kind_2
        representative_grade_2 = representative_node.grade_2
        representative_fields = build_stage4_representative_fields(
            mainnodeid=mainnodeid_norm,
            source_kind=representative_source_kind,
            source_kind_2=representative_source_kind_2,
            kind_2=representative_kind_2,
            grade_2=representative_grade_2,
        )
        admission = evaluate_stage4_candidate_admission(
            has_evd=representative_node.has_evd,
            is_anchor=representative_node.is_anchor,
            source_kind=representative_source_kind,
            source_kind_2=representative_source_kind_2,
            supported_kind=_is_stage4_supported_node_kind(representative_node),
            out_of_scope_reason=REASON_MAINNODEID_OUT_OF_SCOPE,
        )
        if not admission.admitted:
            raise Stage4RunError(
                str(admission.reason or REASON_MAINNODEID_OUT_OF_SCOPE),
                str(admission.detail or f"mainnodeid='{mainnodeid_norm}' is out of scope."),
            )

        step2_local_context = _build_stage4_local_context(
            representative_node=representative_node,
            group_nodes=group_nodes,
            nodes=nodes,
            roads=roads,
            drivezone_features=drivezone_layer_data.features,
            rcsd_roads=rcsd_roads,
            rcsd_nodes=rcsd_nodes,
            divstripzone_path=divstripzone_path,
            divstripzone_layer=divstripzone_layer,
            divstripzone_crs=divstripzone_crs,
        )
        counts["current_patch_id"] = step2_local_context.current_patch_id
        counts["divstripzone_feature_count"] = step2_local_context.queried_divstrip_feature_count
        counts["local_node_count"] = len(step2_local_context.local_nodes)
        counts["local_road_count"] = len(step2_local_context.local_roads)
        counts["local_rcsdroad_count"] = len(step2_local_context.local_rcsd_roads)
        counts["local_rcsdnode_count"] = len(step2_local_context.local_rcsd_nodes)
        counts["local_divstrip_feature_count"] = len(step2_local_context.local_divstrip_features)

        step3_topology_skeleton = _build_stage4_topology_skeleton(
            representative_node=representative_node,
            group_nodes=group_nodes,
            local_nodes=list(step2_local_context.local_nodes),
            local_roads=list(step2_local_context.local_roads),
            drivezone_union=step2_local_context.drivezone_union,
            support_center=step2_local_context.seed_center,
        )
        legacy_step4_readiness: Stage4LegacyStep4Readiness = evaluate_stage4_legacy_step4_readiness(
            step3_topology_skeleton
        )
        if not legacy_step4_readiness.ready:
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Legacy Step4 adapter requires a resolved main branch pair before event interpretation.",
            )
        seed_geometries = [
            representative_node.geometry,
            *[node.geometry for node in group_nodes],
            *[node.geometry for node in step2_local_context.exact_target_rc_nodes],
        ]
        seed_union = unary_union(seed_geometries)
        legacy_step4_bridge = Stage4LegacyStep4Bridge(
            local_context=step2_local_context,
            topology_skeleton=step3_topology_skeleton,
        )
        # Transitional adapter:
        # Round 2 formally externalizes Step2 / Step3 as structured outputs,
        # while legacy Step4~Step6 still consume a compatibility view.
        direct_target_rc_nodes = list(legacy_step4_bridge.local_context.direct_target_rc_nodes)
        primary_main_rc_node = legacy_step4_bridge.local_context.primary_main_rc_node
        exact_target_rc_nodes = list(legacy_step4_bridge.local_context.exact_target_rc_nodes)
        rcsdnode_seed_mode = legacy_step4_bridge.local_context.rcsdnode_seed_mode
        drivezone_union = legacy_step4_bridge.local_context.patch_drivezone_union
        seed_center = legacy_step4_bridge.local_context.seed_center
        patch_size_m = legacy_step4_bridge.local_context.patch_size_m
        grid = legacy_step4_bridge.local_context.grid
        drivezone_mask = legacy_step4_bridge.local_context.patch_drivezone_mask
        local_nodes = list(legacy_step4_bridge.local_context.local_nodes)
        local_roads = list(legacy_step4_bridge.local_context.patch_roads)
        local_rcsd_roads = list(legacy_step4_bridge.local_context.local_rcsd_roads)
        local_rcsd_nodes = list(legacy_step4_bridge.local_context.local_rcsd_nodes)
        local_divstrip_features = list(legacy_step4_bridge.local_context.patch_divstrip_features)
        local_divstrip_union = legacy_step4_bridge.local_context.patch_divstrip_union
        negative_exclusion_context = legacy_step4_bridge.local_context.negative_exclusion_context
        chain_context = legacy_step4_bridge.topology_skeleton.chain_context.to_legacy_dict()
        member_node_ids = set(legacy_step4_bridge.topology_skeleton.branch_result.augmented_member_node_ids)
        road_branches = list(legacy_step4_bridge.topology_skeleton.branch_result.road_branches)
        road_to_branch = dict(legacy_step4_bridge.topology_skeleton.branch_result.road_to_branch)
        road_branches_by_id = dict(legacy_step4_bridge.topology_skeleton.branch_result.road_branches_by_id)
        main_branch_ids = set(legacy_step4_bridge.topology_skeleton.branch_result.main_branch_ids)
        step4_event_interpretation = _build_stage4_event_interpretation(
            representative_node=representative_node,
            representative_source_kind_2=representative_source_kind_2,
            mainnodeid_norm=mainnodeid_norm,
            seed_union=seed_union,
            group_nodes=group_nodes,
            patch_size_m=patch_size_m,
            seed_center=seed_center,
            drivezone_union=drivezone_union,
            local_roads=local_roads,
            local_rcsd_roads=local_rcsd_roads,
            local_rcsd_nodes=local_rcsd_nodes,
            local_divstrip_features=local_divstrip_features,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            member_node_ids=member_node_ids,
            direct_target_rc_nodes=direct_target_rc_nodes,
            exact_target_rc_nodes=exact_target_rc_nodes,
            primary_main_rc_node=primary_main_rc_node,
            rcsdnode_seed_mode=rcsdnode_seed_mode,
            chain_context=chain_context,
        )
        operational_kind_2 = int(step4_event_interpretation.kind_resolution.operational_kind_2)
        divstrip_context = step4_event_interpretation.divstrip_context.to_legacy_dict()
        multibranch_context = step4_event_interpretation.multibranch_decision.to_legacy_dict()
        kind_resolution = step4_event_interpretation.kind_resolution.to_legacy_dict()
        reverse_tip_attempted = step4_event_interpretation.reverse_tip_decision.attempted
        reverse_tip_used = step4_event_interpretation.reverse_tip_decision.used
        reverse_trigger = step4_event_interpretation.reverse_tip_decision.trigger
        position_source_forward = step4_event_interpretation.reverse_tip_decision.position_source_forward
        position_source_reverse = step4_event_interpretation.reverse_tip_decision.position_source_reverse
        position_source_final = step4_event_interpretation.reverse_tip_decision.position_source_final
        legacy_step5_bridge = step4_event_interpretation.legacy_step5_bridge
        selected_side_branches = list(legacy_step5_bridge.selected_side_branches)
        selected_branch_ids = list(legacy_step5_bridge.selected_branch_ids)
        selected_event_branch_ids = list(legacy_step5_bridge.selected_event_branch_ids)
        selected_road_ids = list(legacy_step5_bridge.selected_road_ids)
        selected_event_road_ids = set(legacy_step5_bridge.selected_event_road_ids)
        selected_rcsdroad_ids = set(legacy_step5_bridge.selected_rcsdroad_ids)
        selected_rcsdnode_ids = set(legacy_step5_bridge.selected_rcsdnode_ids)
        rcsdroad_selection_mode = legacy_step5_bridge.rcsdroad_selection_mode
        rcsdnode_seed_mode = legacy_step5_bridge.rcsdnode_seed_mode
        primary_main_rc_node = legacy_step5_bridge.primary_main_rc_node
        selected_roads = list(legacy_step5_bridge.selected_roads)
        selected_event_roads = list(legacy_step5_bridge.selected_event_roads)
        selected_rcsd_roads = list(legacy_step5_bridge.selected_rcsd_roads)
        selected_rcsd_nodes = list(legacy_step5_bridge.selected_rcsd_nodes)
        effective_target_rc_nodes = list(legacy_step5_bridge.effective_target_rc_nodes)
        complex_local_support_roads = list(legacy_step5_bridge.complex_local_support_roads)
        seed_support_geometries = list(legacy_step5_bridge.seed_support_geometries)
        divstrip_constraint_geometry = legacy_step5_bridge.divstrip_constraint_geometry
        event_anchor_geometry = legacy_step5_bridge.event_anchor_geometry
        localized_divstrip_reference_geometry = legacy_step5_bridge.localized_divstrip_reference_geometry
        event_axis_branch = legacy_step5_bridge.event_axis_branch
        event_axis_branch_id = legacy_step5_bridge.event_axis_branch_id
        event_axis_centerline = legacy_step5_bridge.event_axis_centerline
        provisional_event_origin = legacy_step5_bridge.provisional_event_origin
        initial_event_axis_unit_vector = legacy_step5_bridge.initial_event_axis_unit_vector
        boundary_branch_a = legacy_step5_bridge.boundary_branch_a
        boundary_branch_b = legacy_step5_bridge.boundary_branch_b
        branch_a_centerline = legacy_step5_bridge.branch_a_centerline
        branch_b_centerline = legacy_step5_bridge.branch_b_centerline
        event_cross_half_len_m = legacy_step5_bridge.event_cross_half_len_m
        event_reference = dict(legacy_step5_bridge.event_reference_raw)
        event_origin_point = legacy_step5_bridge.event_origin_point
        event_origin_source = legacy_step5_bridge.event_origin_source
        event_axis_unit_vector = legacy_step5_bridge.event_axis_unit_vector
        event_recenter = (
            event_origin_point,
            {
                "applied": legacy_step5_bridge.event_recenter_applied,
                "shift_m": legacy_step5_bridge.event_recenter_shift_m,
                "direction": legacy_step5_bridge.event_recenter_direction,
            },
        )
        step5_geometric_support_domain = _build_stage4_geometric_support_domain(
            representative_node=representative_node,
            candidate_nodes=nodes,
            local_nodes=local_nodes,
            local_roads=local_roads,
            local_divstrip_union=local_divstrip_union,
            drivezone_union=drivezone_union,
            drivezone_mask=drivezone_mask,
            grid=grid,
            seed_union=seed_union,
            member_node_ids=member_node_ids,
            group_nodes=group_nodes,
            chain_context=chain_context,
            road_branches=road_branches,
            road_branches_by_id=road_branches_by_id,
            road_to_branch=road_to_branch,
            step4_event_interpretation=step4_event_interpretation,
            direct_target_rc_nodes=direct_target_rc_nodes,
        )
        event_span_window = dict(step5_geometric_support_domain.span_window.final)
        parallel_side_sign = step5_geometric_support_domain.exclusion_context.parallel_side_sign
        parallel_centerline_road_id = step5_geometric_support_domain.exclusion_context.parallel_centerline_road_id
        has_parallel_competitor = step5_geometric_support_domain.exclusion_context.parallel_competitor_present
        parallel_excluded_road_ids = list(step5_geometric_support_domain.exclusion_context.parallel_excluded_road_ids)
        allow_full_axis_drivezone_fill = step5_geometric_support_domain.surface_assembly.allow_full_axis_drivezone_fill
        cross_section_sample_count = step5_geometric_support_domain.surface_assembly.cross_section_sample_count
        selected_component_surface_diags = [
            dict(item)
            for item in step5_geometric_support_domain.surface_assembly.selected_component_surface_diags
        ]
        complex_multibranch_lobe_diags = [
            dict(item)
            for item in step5_geometric_support_domain.surface_assembly.complex_multibranch_lobe_diags
        ]
        step6_polygon_assembly = _build_stage4_polygon_assembly(
            grid=grid,
            drivezone_union=drivezone_union,
            seed_union=seed_union,
            local_divstrip_union=local_divstrip_union,
            step4_event_interpretation=step4_event_interpretation,
            step5_geometric_support_domain=step5_geometric_support_domain,
        )
        polygon_geometry = step6_polygon_assembly.legacy_step7_bridge.polygon_geometry
        support_clip_geometry = step6_polygon_assembly.legacy_step7_bridge.support_clip_geometry

        geometry_state = step6_polygon_assembly.geometry_state.value
        geometry_risk_signals = list(step6_polygon_assembly.geometry_risk_signals.signals)

        primary_rcsdnode_tolerance = _evaluate_primary_rcsdnode_tolerance(
            polygon_geometry=polygon_geometry,
            primary_main_rc_node=primary_main_rc_node,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            selected_roads=selected_roads,
            kind_2=operational_kind_2,
            drivezone_union=drivezone_union,
            support_clip_geometry=support_clip_geometry,
            preferred_trunk_branch_id=event_axis_branch_id,
        )
        primary_main_rc_node, primary_rcsdnode_tolerance = _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover(
            primary_main_rc_node=primary_main_rc_node,
            primary_rcsdnode_tolerance=primary_rcsdnode_tolerance,
            representative_node=representative_node,
            selected_rcsd_nodes=selected_rcsd_nodes,
            direct_target_rc_nodes=direct_target_rc_nodes,
            rcsdnode_seed_mode=rcsdnode_seed_mode,
            polygon_geometry=polygon_geometry,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            selected_roads=selected_roads,
            kind_2=operational_kind_2,
            drivezone_union=drivezone_union,
            support_clip_geometry=support_clip_geometry,
            preferred_trunk_branch_id=event_axis_branch_id,
        )
        polygon_geometry = primary_rcsdnode_tolerance["extended_polygon_geometry"]
        if (
            primary_main_rc_node is not None
            and str(primary_rcsdnode_tolerance.get("rcsdnode_coverage_mode") or "")
            == "selected_road_corridor_tolerated"
            and step6_polygon_assembly.expected_continuous_chain_multilobe_geometry
        ):
            refined_polygon_geometry, refined_after_rcsdnode_extension = (
                _refine_expected_continuous_chain_polygon_contour(
                    polygon_geometry=polygon_geometry,
                    preferred_clip_geometry=step6_polygon_assembly.legacy_step7_bridge.preferred_clip_geometry,
                    parallel_side_geometry=step6_polygon_assembly.legacy_step7_bridge.parallel_side_geometry,
                    drivezone_union=drivezone_union,
                )
            )
            if (
                refined_after_rcsdnode_extension
                and refined_polygon_geometry is not None
                and not refined_polygon_geometry.is_empty
                and refined_polygon_geometry.buffer(0).covers(primary_main_rc_node.geometry)
            ):
                polygon_geometry = _regularize_virtual_polygon_geometry(
                    geometry=refined_polygon_geometry,
                    drivezone_union=drivezone_union,
                    seed_geometry=(
                        step5_geometric_support_domain.event_seed_union
                        if step5_geometric_support_domain.event_seed_union is not None
                        and not step5_geometric_support_domain.event_seed_union.is_empty
                        else seed_union
                    ),
                )
                primary_rcsdnode_tolerance = dict(primary_rcsdnode_tolerance)
                primary_rcsdnode_tolerance["extended_polygon_geometry"] = polygon_geometry
                primary_rcsdnode_tolerance["rcsdnode_post_refined"] = True
        effective_target_rc_nodes = _resolve_effective_target_rc_nodes(
            direct_target_rc_nodes=direct_target_rc_nodes,
            primary_main_rc_node=primary_main_rc_node,
            primary_rcsdnode_tolerance=primary_rcsdnode_tolerance,
        )
        coverage_missing_ids = _cover_check(polygon_geometry, exact_target_rc_nodes)
        coverage_missing_ids = sorted(set(coverage_missing_ids))
        review_reasons: list[str] = []
        if multibranch_context["ambiguous"]:
            review_reasons.append(STATUS_MULTIBRANCH_EVENT_AMBIGUOUS)
        if divstrip_context["ambiguous"]:
            review_reasons.append(STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS)
        if (
            chain_context["is_in_continuous_chain"]
            and chain_context["sequential_ok"]
            and not kind_resolution["complex_junction"]
            and chain_context.get("chain_bidirectional", False)
        ):
            review_reasons.append(STATUS_CONTINUOUS_CHAIN_REVIEW)
        if kind_resolution["ambiguous"]:
            review_reasons.append(STATUS_COMPLEX_KIND_AMBIGUOUS)
        tolerance_reason = primary_rcsdnode_tolerance.get("reason")
        suppress_inferred_rcsdnode_review = (
            not direct_target_rc_nodes
            and rcsdnode_seed_mode == "inferred_local_trunk_window"
            and str(tolerance_reason) in {
                REASON_RCSDNODE_MAIN_OUT_OF_WINDOW,
                REASON_RCSDNODE_MAIN_OFF_TRUNK,
                REASON_RCSDNODE_MAIN_DIRECTION_INVALID,
            }
        )
        if tolerance_reason and not suppress_inferred_rcsdnode_review:
            review_reasons.append(str(tolerance_reason))
        if coverage_missing_ids:
            review_reasons.append(REASON_COVERAGE_INCOMPLETE)
        hard_rejection_reasons: list[str] = []
        if representative_fields.kind is None:
            hard_rejection_reasons.append(REASON_MISSING_REQUIRED_FIELD)
        step7_acceptance = _build_stage4_step7_acceptance(
            representative_node=representative_node,
            representative_fields=representative_fields,
            step4_event_interpretation=step4_event_interpretation,
            step6_polygon_assembly=step6_polygon_assembly,
            primary_main_rc_node=primary_main_rc_node,
            direct_target_rc_nodes=direct_target_rc_nodes,
            effective_target_rc_nodes=effective_target_rc_nodes,
            coverage_missing_ids=coverage_missing_ids,
            primary_rcsdnode_tolerance=primary_rcsdnode_tolerance,
            base_review_reasons=review_reasons,
            base_hard_rejection_reasons=hard_rejection_reasons,
            flow_success=True,
        )
        review_reasons = list(step7_acceptance.decision.review_reasons)
        hard_rejection_reasons = list(step7_acceptance.decision.hard_rejection_reasons)
        acceptance_class = step7_acceptance.decision.acceptance_class
        acceptance_reason = step7_acceptance.decision.acceptance_reason
        success = step7_acceptance.decision.success
        output_mainnodeid = step7_acceptance.output_mainnodeid
        business_outcome_class = step7_acceptance.decision.business_outcome_class
        visual_review_class = step7_acceptance.decision.visual_review_class
        root_cause_layer = step7_acceptance.decision.root_cause_layer
        root_cause_type = step7_acceptance.decision.root_cause_type
        decision_basis = list(step7_acceptance.decision_basis.items)
        frozen_constraints_conflict = step7_acceptance.frozen_constraints_conflict.has_conflict

        counts["target_node_count"] = len(group_nodes)
        counts["target_rcsdnode_count"] = len(effective_target_rc_nodes)
        counts["selected_branch_count"] = len(selected_branch_ids)
        counts["selected_road_count"] = len(selected_roads)
        counts["selected_rcsdroad_count"] = len(selected_rcsd_roads)
        counts["selected_rcsdnode_count"] = len(selected_rcsdnode_ids)

        polygon_feature = {
            "properties": {
                "mainnodeid": output_mainnodeid,
                "kind": representative_fields.kind,
                "source_kind": representative_fields.source_kind,
                "source_kind_2": representative_fields.source_kind_2,
                "kind_2": operational_kind_2,
                "grade_2": representative_fields.grade_2,
                "status": acceptance_reason,
                "acceptance_class": acceptance_class,
                "acceptance_reason": acceptance_reason,
                "business_outcome_class": business_outcome_class,
                "visual_review_class": visual_review_class,
                "root_cause_layer": root_cause_layer,
                "root_cause_type": root_cause_type,
                "decision_basis": json.dumps(decision_basis, ensure_ascii=False),
                "review_reasons": json.dumps(review_reasons, ensure_ascii=False),
                "hard_rejection_reasons": json.dumps(hard_rejection_reasons, ensure_ascii=False),
                "frozen_constraints_conflict": int(frozen_constraints_conflict),
                "target_node_count": len(group_nodes),
                "target_rcsdnode_count": len(effective_target_rc_nodes),
                "selected_branch_count": len(selected_branch_ids),
                "selected_road_count": len(selected_roads),
                "selected_rcsdroad_count": len(selected_rcsd_roads),
                "selected_rcsdnode_count": len(selected_rcsdnode_ids),
                "coverage_missing_count": len(coverage_missing_ids),
                "divstrip_present": int(divstrip_context["present"]),
                "divstrip_nearby": int(divstrip_context["nearby"]),
                "divstrip_component_count": int(divstrip_context["component_count"]),
                "divstrip_component_selected": json.dumps(divstrip_context["selected_component_ids"], ensure_ascii=False),
                "evidence_source": divstrip_context["evidence_source"],
                "selection_mode": divstrip_context["selection_mode"],
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "complex_junction": int(kind_resolution["complex_junction"]),
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": int(kind_resolution["ambiguous"]),
                "multibranch_enabled": int(multibranch_context["enabled"]),
                "multibranch_n": int(multibranch_context["n"]),
                "event_candidate_count": int(multibranch_context["event_candidate_count"]),
                "selected_event_index": multibranch_context["selected_event_index"],
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "semantic_protected_start_m": event_span_window.get("semantic_protected_start_m"),
                "semantic_protected_end_m": event_span_window.get("semantic_protected_end_m"),
                "semantic_prev_boundary_offset_m": event_span_window.get("semantic_prev_boundary_offset_m"),
                "semantic_next_boundary_offset_m": event_span_window.get("semantic_next_boundary_offset_m"),
                "geometry_state": geometry_state,
                "geometry_risk_signals": json.dumps(geometry_risk_signals, ensure_ascii=False),
                "cross_section_sample_count": cross_section_sample_count,
                "parallel_side_sign": parallel_side_sign,
                "parallel_centerline_road_id": parallel_centerline_road_id,
                "parallel_competitor_present": int(has_parallel_competitor),
                "parallel_excluded_road_count": len(parallel_excluded_road_ids),
                "allow_full_axis_drivezone_fill": int(allow_full_axis_drivezone_fill),
                "branches_used_count": len(selected_branch_ids),
                "reverse_tip_attempted": int(reverse_tip_attempted),
                "reverse_tip_used": int(reverse_tip_used),
                "is_in_continuous_chain": int(chain_context["is_in_continuous_chain"]),
                "chain_node_count": int(chain_context["chain_node_count"]),
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": int(primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"]),
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
                "rcsdnode_reselected_exact_cover": int(
                    bool(primary_rcsdnode_tolerance.get("rcsdnode_reselected_exact_cover", False))
                ),
            },
            "geometry": polygon_geometry,
        }
        write_vector(virtual_polygon_path, [polygon_feature], crs_text=TARGET_CRS.to_string())

        node_link_doc = _make_link_doc(
            mainnodeid=output_mainnodeid,
            kind_2=operational_kind_2,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in group_nodes],
            linked_node_ids=[node.node_id for node in group_nodes],
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=selected_road_ids,
            coverage_missing_ids=coverage_missing_ids,
        )
        node_link_doc.update(
            {
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_main_pair_item_ids": multibranch_context.get("main_pair_item_ids", []),
                "multibranch_event_candidates": multibranch_context.get("event_candidates", []),
                "multibranch_lobe_diags": complex_multibranch_lobe_diags,
                "selected_component_surface_diags": selected_component_surface_diags,
                "selected_event_branch_ids": selected_event_branch_ids,
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "semantic_protected_start_m": event_span_window.get("semantic_protected_start_m"),
                "semantic_protected_end_m": event_span_window.get("semantic_protected_end_m"),
                "semantic_prev_boundary_offset_m": event_span_window.get("semantic_prev_boundary_offset_m"),
                "semantic_next_boundary_offset_m": event_span_window.get("semantic_next_boundary_offset_m"),
                "cross_section_sample_count": cross_section_sample_count,
                "parallel_side_sign": parallel_side_sign,
                "parallel_centerline_road_id": parallel_centerline_road_id,
                "parallel_competitor_present": has_parallel_competitor,
                "parallel_excluded_road_count": len(parallel_excluded_road_ids),
                "allow_full_axis_drivezone_fill": allow_full_axis_drivezone_fill,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "primary_main_rc_node_id": None if primary_main_rc_node is None else primary_main_rc_node.node_id,
                "rcsdnode_reselected_exact_cover": bool(
                    primary_rcsdnode_tolerance.get("rcsdnode_reselected_exact_cover", False)
                ),
                "rcsdnode_reselected_from_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_from_node_id"),
                "rcsdnode_reselected_to_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_to_node_id"),
                "rcsdnode_reselected_reason": primary_rcsdnode_tolerance.get("rcsdnode_reselected_reason"),
            }
        )
        rcsdnode_link_doc = _make_link_doc(
            mainnodeid=output_mainnodeid,
            kind_2=operational_kind_2,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in effective_target_rc_nodes],
            linked_node_ids=sorted(selected_rcsdnode_ids),
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=sorted(selected_rcsdroad_ids),
            coverage_missing_ids=coverage_missing_ids,
        )
        rcsdnode_link_doc.update(
            {
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_main_pair_item_ids": multibranch_context.get("main_pair_item_ids", []),
                "multibranch_event_candidates": multibranch_context.get("event_candidates", []),
                "multibranch_lobe_diags": complex_multibranch_lobe_diags,
                "selected_component_surface_diags": selected_component_surface_diags,
                "selected_event_branch_ids": selected_event_branch_ids,
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "semantic_protected_start_m": event_span_window.get("semantic_protected_start_m"),
                "semantic_protected_end_m": event_span_window.get("semantic_protected_end_m"),
                "semantic_prev_boundary_offset_m": event_span_window.get("semantic_prev_boundary_offset_m"),
                "semantic_next_boundary_offset_m": event_span_window.get("semantic_next_boundary_offset_m"),
                "cross_section_sample_count": cross_section_sample_count,
                "parallel_side_sign": parallel_side_sign,
                "parallel_centerline_road_id": parallel_centerline_road_id,
                "parallel_competitor_present": has_parallel_competitor,
                "parallel_excluded_road_count": len(parallel_excluded_road_ids),
                "allow_full_axis_drivezone_fill": allow_full_axis_drivezone_fill,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
                "primary_main_rc_node_id": None if primary_main_rc_node is None else primary_main_rc_node.node_id,
                "rcsdnode_reselected_exact_cover": bool(
                    primary_rcsdnode_tolerance.get("rcsdnode_reselected_exact_cover", False)
                ),
                "rcsdnode_reselected_from_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_from_node_id"),
                "rcsdnode_reselected_to_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_to_node_id"),
                "rcsdnode_reselected_reason": primary_rcsdnode_tolerance.get("rcsdnode_reselected_reason"),
            }
        )
        _write_link_json(node_link_json_path, node_link_doc)
        _write_link_json(rcsdnode_link_json_path, rcsdnode_link_doc)

        if debug and debug_render_path is not None:
            debug_render_patch_size = max(patch_size_m, DEBUG_RENDER_PATCH_SIZE_M)
            debug_render_grid = _build_grid(
                seed_center,
                patch_size_m=debug_render_patch_size,
                resolution_m=DEFAULT_RESOLUTION_M,
            )
            debug_drivezone_mask = (
                _rasterize_geometries(debug_render_grid, [drivezone_union])
                if not drivezone_union.is_empty
                else np.zeros((debug_render_grid.height, debug_render_grid.width), dtype=bool)
            )
            debug_dir = debug_render_path.parent
            debug_dir.mkdir(parents=True, exist_ok=True)
            _write_debug_rendered_map(
                out_path=debug_render_path,
                grid=debug_render_grid,
                drivezone_mask=debug_drivezone_mask,
                polygon_geometry=polygon_geometry,
                representative_node=representative_node,
                group_nodes=group_nodes,
                # Render all available case geometry for review, not only the compact local subset,
                # so reviewers can validate full before/after road context without missing surrounding network.
                local_nodes=nodes,
                local_roads=roads,
                local_rc_nodes=rcsd_nodes,
                local_rc_roads=rcsd_roads,
                selected_rc_roads=selected_rcsd_roads,
                selected_rc_node_ids=selected_rcsdnode_ids,
                excluded_rc_road_ids={rcsd_road.road_id for rcsd_road in rcsd_roads if rcsd_road.road_id not in selected_rcsdroad_ids},
                excluded_rc_node_ids={node.node_id for node in rcsd_nodes if node.node_id not in selected_rcsdnode_ids},
                failure_reason=None if acceptance_class == "accepted" else acceptance_reason,
                failure_class=None if acceptance_class == "accepted" else acceptance_class,
                local_divstrip_geometries=[feature.geometry for feature in local_divstrip_features],
                selected_divstrip_geometry=divstrip_context["constraint_geometry"],
            )
            if rendered_map_path is not None:
                rendered_map_path.parent.mkdir(parents=True, exist_ok=True)
                if rendered_map_path != debug_render_path:
                    shutil.copy2(debug_render_path, rendered_map_path)

        status_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": step7_acceptance.decision.flow_success,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "business_outcome_class": business_outcome_class,
            "visual_review_class": visual_review_class,
            "root_cause_layer": root_cause_layer,
            "root_cause_type": root_cause_type,
            "decision_basis": decision_basis,
            "frozen_constraints_conflict": frozen_constraints_conflict,
            "mainnodeid": output_mainnodeid,
            "kind": representative_fields.kind,
            "source_kind": representative_source_kind,
            "source_kind_2": representative_source_kind_2,
            "kind_2": operational_kind_2,
            "grade_2": representative_grade_2,
            "counts": counts,
            "coverage_missing_ids": coverage_missing_ids,
            "review_reasons": review_reasons,
            "hard_rejection_reasons": hard_rejection_reasons,
            "step2_context": step2_local_context.to_audit_summary(),
            "step3_skeleton": step3_topology_skeleton.to_audit_summary(),
            "step3_legacy_step4_adapter": {
                "required": True,
                "ready": legacy_step4_readiness.ready,
                "reasons": list(legacy_step4_readiness.reasons),
            },
            "step4_interpretation": step4_event_interpretation.to_audit_summary(),
            "step4_legacy_step5_adapter": {
                "required": True,
                "ready": step4_event_interpretation.legacy_step5_readiness.ready,
                "reasons": list(step4_event_interpretation.legacy_step5_readiness.reasons),
            },
            "step5_geometric_support_domain": step5_geometric_support_domain.to_audit_summary(),
            "step6_polygon_assembly": step6_polygon_assembly.to_audit_summary(),
            "step6_legacy_step7_adapter": step6_polygon_assembly.legacy_step7_bridge.to_audit_summary(),
            "step7_acceptance": step7_acceptance.to_audit_summary(),
            "geometry_state": geometry_state,
            "geometry_risk_signals": geometry_risk_signals,
            "rcsdnode_seed_mode": rcsdnode_seed_mode,
            "rcsdroad_selection_mode": rcsdroad_selection_mode,
            "kind_resolution": {
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "merge_score": kind_resolution["merge_score"],
                "diverge_score": kind_resolution["diverge_score"],
                "merge_hits": kind_resolution["merge_hits"],
                "diverge_hits": kind_resolution["diverge_hits"],
            },
            "multibranch": {
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_n": multibranch_context["n"],
                "main_pair_item_ids": multibranch_context.get("main_pair_item_ids", []),
                "event_candidate_count": multibranch_context["event_candidate_count"],
                "event_candidates": multibranch_context.get("event_candidates", []),
                "selected_event_index": multibranch_context["selected_event_index"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "selected_component_surface_count": len(
                    [
                        item
                        for item in selected_component_surface_diags
                        if bool(item.get("ok", False)) and item.get("component_index") != "connector"
                    ]
                ),
                "selected_component_surface_diags": selected_component_surface_diags,
                "lobe_count": len(
                    [
                        item
                        for item in complex_multibranch_lobe_diags
                        if bool(item.get("ok", False))
                    ]
                ),
                "lobe_diags": complex_multibranch_lobe_diags,
                "event_axis_branch_id": event_axis_branch_id,
            "event_origin_source": event_origin_source,
            "event_recenter_applied": bool(event_recenter[1]["applied"]),
            "event_recenter_shift_m": event_recenter[1]["shift_m"],
            "event_recenter_direction": event_recenter[1]["direction"],
            "event_position_source": event_reference["position_source"],
            "event_split_pick_source": event_reference["split_pick_source"],
            "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
            },
            "reverse_tip": {
                "reverse_tip_attempted": reverse_tip_attempted,
                "reverse_tip_used": reverse_tip_used,
                "reverse_trigger": reverse_trigger,
                "position_source_forward": position_source_forward,
                "position_source_reverse": position_source_reverse,
                "position_source_final": position_source_final,
            },
            "event_shape": {
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "semantic_protected_start_m": event_span_window.get("semantic_protected_start_m"),
                "semantic_protected_end_m": event_span_window.get("semantic_protected_end_m"),
                "semantic_prev_boundary_offset_m": event_span_window.get("semantic_prev_boundary_offset_m"),
                "semantic_next_boundary_offset_m": event_span_window.get("semantic_next_boundary_offset_m"),
                "candidate_offset_count": event_span_window["candidate_offset_count"],
                "expansion_source": event_span_window["expansion_source"],
                "cross_section_sample_count": cross_section_sample_count,
                "parallel_side_sign": parallel_side_sign,
                "parallel_centerline_road_id": parallel_centerline_road_id,
                "parallel_competitor_present": has_parallel_competitor,
                "parallel_excluded_road_count": len(parallel_excluded_road_ids),
                "allow_full_axis_drivezone_fill": allow_full_axis_drivezone_fill,
            },
            "continuous_chain": {
                "chain_component_id": chain_context["chain_component_id"],
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "is_in_continuous_chain": chain_context["is_in_continuous_chain"],
                "chain_node_count": chain_context["chain_node_count"],
                "chain_node_offset_m": chain_context["chain_node_offset_m"],
                "sequential_ok": chain_context["sequential_ok"],
                "chain_bidirectional": chain_context.get("chain_bidirectional", False),
                "applied_to_event_interpretation": step4_event_interpretation.continuous_chain_decision.applied_to_event_interpretation,
                "influence_mode": step4_event_interpretation.continuous_chain_decision.influence_mode,
            },
            "divstrip": {
                "divstrip_present": divstrip_context["present"],
                "divstrip_nearby": divstrip_context["nearby"],
                "divstrip_component_count": divstrip_context["component_count"],
                "divstrip_component_selected": divstrip_context["selected_component_ids"],
                "selection_mode": divstrip_context["selection_mode"],
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "evidence_source": divstrip_context["evidence_source"],
                "preferred_branch_ids": divstrip_context.get("preferred_branch_ids", []),
            },
            "rcsdnode_tolerance": {
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
            },
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
                "rendered_map": str(rendered_map_path) if rendered_map_path is not None and rendered_map_path.is_file() else None,
            },
        }
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": (
                    "failed"
                    if acceptance_class == "rejected"
                    else ("warning" if acceptance_class == "review_required" else "info")
                ),
                "reason": acceptance_reason,
                "detail": (
                    "Stage4 polygon rejected by final acceptance contract."
                    if acceptance_class == "rejected"
                    else (
                        "Stage4 polygon requires manual review under the final acceptance contract."
                        if acceptance_class == "review_required"
                        else "Stage4 polygon accepted."
                    )
                ),
                "business_outcome_class": business_outcome_class,
                "visual_review_class": visual_review_class,
                "root_cause_layer": root_cause_layer,
                "root_cause_type": root_cause_type,
                "decision_basis": decision_basis,
                "frozen_constraints_conflict": frozen_constraints_conflict,
                "coverage_missing_ids": coverage_missing_ids,
                "review_reasons": review_reasons,
                "hard_rejection_reasons": hard_rejection_reasons,
                "step2_scene_drivezone_feature_count": step2_local_context.scene_drivezone_feature_count,
                "step2_scene_road_count": step2_local_context.scene_road_count,
                "step2_negative_rcsdnode_count": len(step2_local_context.negative_exclusion_context.rcsd_nodes),
                "step2_negative_rcsdroad_count": len(step2_local_context.negative_exclusion_context.rcsd_roads),
                "step2_negative_swsdnode_count": len(step2_local_context.negative_exclusion_context.swsd_nodes),
                "step2_negative_swsdroad_count": len(step2_local_context.negative_exclusion_context.swsd_roads),
                "step2_negative_road_geometry_only_count": len(step2_local_context.negative_exclusion_context.road_geometry_only_ids),
                "step3_through_node_policy": step3_topology_skeleton.branch_result.through_node_policy,
                "step3_through_node_candidate_count": len(step3_topology_skeleton.branch_result.through_node_candidate_ids),
                "step3_branch_count": step3_topology_skeleton.stability.branch_count,
                "step3_main_pair_resolved": step3_topology_skeleton.stability.main_pair_resolved,
                "step3_chain_augmented": step3_topology_skeleton.stability.chain_augmented,
                "step3_unstable_reasons": list(step3_topology_skeleton.stability.unstable_reasons),
                "step4_evidence_source": step4_event_interpretation.evidence_decision.primary_source,
                "step4_selection_mode": step4_event_interpretation.evidence_decision.selection_mode,
                "step4_fallback_used": step4_event_interpretation.evidence_decision.fallback_used,
                "step4_fallback_mode": step4_event_interpretation.evidence_decision.fallback_mode,
                "step4_review_signals": list(step4_event_interpretation.review_signals),
                "step4_hard_rejection_signals": list(step4_event_interpretation.hard_rejection_signals),
                "step4_risk_signals": list(step4_event_interpretation.risk_signals),
                "step4_kind_resolution_mode": step4_event_interpretation.kind_resolution.kind_resolution_mode,
                "step4_kind_resolution_ambiguous": step4_event_interpretation.kind_resolution.ambiguous,
                "step4_operational_kind_2": step4_event_interpretation.kind_resolution.operational_kind_2,
                "step4_multibranch_enabled": step4_event_interpretation.multibranch_decision.enabled,
                "step4_event_candidate_count": step4_event_interpretation.multibranch_decision.event_candidate_count,
                "step4_selected_event_index": step4_event_interpretation.multibranch_decision.selected_event_index,
                "step4_selected_event_branch_ids": list(step4_event_interpretation.multibranch_decision.selected_event_branch_ids),
                "step4_reverse_tip_attempted": step4_event_interpretation.reverse_tip_decision.attempted,
                "step4_reverse_tip_used": step4_event_interpretation.reverse_tip_decision.used,
                "step4_reverse_trigger": step4_event_interpretation.reverse_tip_decision.trigger,
                "step4_event_origin_source": step4_event_interpretation.event_reference.event_origin_source,
                "step4_event_position_source": step4_event_interpretation.event_reference.event_position_source,
                "step4_event_split_pick_source": step4_event_interpretation.event_reference.event_split_pick_source,
                "step4_event_chosen_s_m": step4_event_interpretation.event_reference.event_chosen_s_m,
                "step4_event_tip_s_m": step4_event_interpretation.event_reference.event_tip_s_m,
                "step4_event_first_divstrip_hit_s_m": step4_event_interpretation.event_reference.event_first_divstrip_hit_s_m,
                "step4_event_drivezone_split_s_m": step4_event_interpretation.event_reference.event_drivezone_split_s_m,
                "step4_divstrip_component_ambiguous": step4_event_interpretation.divstrip_context.ambiguous,
                "step4_multibranch_event_ambiguous": step4_event_interpretation.multibranch_decision.ambiguous,
                "step4_continuous_chain_applied": step4_event_interpretation.continuous_chain_decision.applied_to_event_interpretation,
                "step4_step5_contract_ready": step4_event_interpretation.legacy_step5_readiness.ready,
                "step4_step5_contract_reasons": list(step4_event_interpretation.legacy_step5_readiness.reasons),
                "step5_span_start_m": step5_geometric_support_domain.span_window.final.get("start_offset_m"),
                "step5_span_end_m": step5_geometric_support_domain.span_window.final.get("end_offset_m"),
                "step5_semantic_prev_boundary_offset_m": step5_geometric_support_domain.span_window.final.get("semantic_prev_boundary_offset_m"),
                "step5_semantic_next_boundary_offset_m": step5_geometric_support_domain.span_window.final.get("semantic_next_boundary_offset_m"),
                "step5_negative_exclusion_applied": step5_geometric_support_domain.exclusion_context.negative_exclusion_applied,
                "step5_preferred_clip_mode": step5_geometric_support_domain.exclusion_context.preferred_clip_mode,
                "step5_event_side_clip_mode": step5_geometric_support_domain.exclusion_context.event_side_clip_mode,
                "step5_parallel_excluded_road_count": len(step5_geometric_support_domain.exclusion_context.parallel_excluded_road_ids),
                "step5_cross_section_support_mode": step5_geometric_support_domain.surface_assembly.cross_section_support_mode,
                "step5_cross_section_sample_count": step5_geometric_support_domain.surface_assembly.cross_section_sample_count,
                "step5_component_mask_used_support_fallback": step5_geometric_support_domain.component_mask_used_support_fallback,
                "step5_component_mask_reseeded_after_clip": step5_geometric_support_domain.component_mask_reseeded_after_clip,
                "step5_component_mask_clipped": step5_geometric_support_domain.component_mask_clipped,
                "step6_geometry_state": geometry_state,
                "step6_geometry_risk_signals": geometry_risk_signals,
                "step6_polygon_built": step6_polygon_assembly.polygon_built,
                "step6_preferred_clip_mode": step6_polygon_assembly.preferred_clip_mode,
                "step6_divstrip_exclusion_applied": step6_polygon_assembly.divstrip_exclusion_applied,
                "step6_parallel_side_clip_applied": step6_polygon_assembly.parallel_side_clip_applied,
                "step6_full_fill_applied": step6_polygon_assembly.full_fill_applied,
                "step6_step7_contract_ready": step6_polygon_assembly.legacy_step7_bridge.ready,
                "step7_conditional_rcsd_required": step7_acceptance.conditional_rcsd_status.required,
                "step7_conditional_rcsd_applied": step7_acceptance.conditional_rcsd_status.applied,
                "step7_conditional_rcsd_review_reasons": list(step7_acceptance.conditional_rcsd_status.review_reasons),
                "step7_conditional_rcsd_hard_rejection_reasons": list(step7_acceptance.conditional_rcsd_status.hard_rejection_reasons),
                "divstrip_present": divstrip_context["present"],
                "divstrip_nearby": divstrip_context["nearby"],
                "divstrip_component_count": divstrip_context["component_count"],
                "divstrip_component_selected": divstrip_context["selected_component_ids"],
                "selection_mode": divstrip_context["selection_mode"],
                "evidence_source": divstrip_context["evidence_source"],
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "merge_score": kind_resolution["merge_score"],
                "diverge_score": kind_resolution["diverge_score"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
                "primary_main_rc_node_id": None if primary_main_rc_node is None else primary_main_rc_node.node_id,
                "rcsdnode_reselected_exact_cover": bool(
                    primary_rcsdnode_tolerance.get("rcsdnode_reselected_exact_cover", False)
                ),
                "rcsdnode_reselected_from_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_from_node_id"),
                "rcsdnode_reselected_to_node_id": primary_rcsdnode_tolerance.get("rcsdnode_reselected_to_node_id"),
                "rcsdnode_reselected_reason": primary_rcsdnode_tolerance.get("rcsdnode_reselected_reason"),
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_n": multibranch_context["n"],
                "event_candidate_count": multibranch_context["event_candidate_count"],
                "selected_event_index": multibranch_context["selected_event_index"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "cross_section_sample_count": cross_section_sample_count,
                "reverse_tip_attempted": reverse_tip_attempted,
                "reverse_tip_used": reverse_tip_used,
                "reverse_trigger": reverse_trigger,
                "position_source_forward": position_source_forward,
                "position_source_reverse": position_source_reverse,
                "position_source_final": position_source_final,
                "chain_component_id": chain_context["chain_component_id"],
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "is_in_continuous_chain": chain_context["is_in_continuous_chain"],
                "chain_node_count": chain_context["chain_node_count"],
                "chain_node_offset_m": chain_context["chain_node_offset_m"],
                "sequential_ok": chain_context["sequential_ok"],
            }
        )
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        write_json(status_path, status_doc)
        _snapshot(
            (
                "success"
                if acceptance_class == "accepted"
                else (
                    "completed_with_review_required_result"
                    if acceptance_class == "review_required"
                    else "completed_with_rejected_result"
                )
            ),
            "complete",
            "Stage4 completed.",
        )

        perf_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": step7_acceptance.decision.flow_success,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(perf_json_path, perf_doc)
        announce(
            logger,
            (
                "[T02-Stage4] complete "
                f"acceptance_class={acceptance_class} selected_road_count={counts['selected_road_count']} "
                f"selected_rcsdroad_count={counts['selected_rcsdroad_count']} out_root={out_root_path}"
            ),
        )
        return Stage4Artifacts(
            success=success,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            rendered_map_path=rendered_map_path if rendered_map_path is not None and rendered_map_path.is_file() else None,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    except Stage4RunError as exc:
        failure_output_mainnodeid = (
            representative_node.mainnodeid or representative_node.node_id
            if "representative_node" in locals()
            else (normalize_id(mainnodeid) or str(mainnodeid))
        )
        failure_kind = (
            representative_fields.kind
            if "representative_fields" in locals()
            else resolve_stage4_output_kind(
                source_kind=representative_source_kind if "representative_source_kind" in locals() else None,
                source_kind_2=representative_source_kind_2 if "representative_source_kind_2" in locals() else None,
            )
        )
        step7_acceptance = build_stage4_failure_step7_result(
            output_mainnodeid=failure_output_mainnodeid,
            kind=failure_kind,
            reason=exc.reason,
            flow_success=False,
        )
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": "failed",
                "reason": exc.reason,
                "detail": exc.detail,
                "mainnodeid": failure_output_mainnodeid,
                "business_outcome_class": step7_acceptance.decision.business_outcome_class,
                "visual_review_class": step7_acceptance.decision.visual_review_class,
                "root_cause_layer": step7_acceptance.decision.root_cause_layer,
                "root_cause_type": step7_acceptance.decision.root_cause_type,
                "decision_basis": list(step7_acceptance.decision_basis.items),
                "frozen_constraints_conflict": step7_acceptance.frozen_constraints_conflict.has_conflict,
            }
        )
        counts["audit_count"] = len(audit_rows)
        _snapshot("failed", "failed", exc.detail)
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        status_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": step7_acceptance.decision.acceptance_class,
            "acceptance_reason": step7_acceptance.decision.acceptance_reason,
            "business_outcome_class": step7_acceptance.decision.business_outcome_class,
            "visual_review_class": step7_acceptance.decision.visual_review_class,
            "root_cause_layer": step7_acceptance.decision.root_cause_layer,
            "root_cause_type": step7_acceptance.decision.root_cause_type,
            "decision_basis": list(step7_acceptance.decision_basis.items),
            "frozen_constraints_conflict": step7_acceptance.frozen_constraints_conflict.has_conflict,
            "mainnodeid": failure_output_mainnodeid,
            "kind": failure_kind,
            "source_kind": representative_source_kind if "representative_source_kind" in locals() else None,
            "source_kind_2": representative_source_kind_2 if "representative_source_kind_2" in locals() else None,
            "status": exc.reason,
            "detail": exc.detail,
            "counts": counts,
            "step7_acceptance": step7_acceptance.to_audit_summary(),
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
                "rendered_map": str(rendered_map_path) if rendered_map_path is not None and rendered_map_path.is_file() else None,
            },
        }
        if "step5_geometric_support_domain" in locals():
            status_doc["step5_geometric_support_domain"] = step5_geometric_support_domain.to_audit_summary()
        if "step6_polygon_assembly" in locals():
            status_doc["step6_polygon_assembly"] = step6_polygon_assembly.to_audit_summary()
            status_doc["step6_legacy_step7_adapter"] = step6_polygon_assembly.legacy_step7_bridge.to_audit_summary()
        perf_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": step7_acceptance.decision.acceptance_class,
            "acceptance_reason": step7_acceptance.decision.acceptance_reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(status_path, status_doc)
        write_json(perf_json_path, perf_doc)
        announce(logger, f"[T02-Stage4] failed reason={exc.reason} detail={exc.detail}")
        return Stage4Artifacts(
            success=False,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            rendered_map_path=rendered_map_path if rendered_map_path is not None and rendered_map_path.is_file() else None,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    finally:
        close_logger(logger)
        if trace_memory:
            tracemalloc.stop()

def run_t02_stage4_divmerge_virtual_polygon_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        divstripzone_path=args.divstripzone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_root=args.out_root,
        run_id=args.run_id,
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        divstripzone_layer=args.divstripzone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        divstripzone_crs=args.divstripzone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        debug=args.debug,
        debug_render_root=getattr(args, "debug_render_root", None),
    )
    acceptance_class = None
    if artifacts.status_doc is not None:
        acceptance_class = str(artifacts.status_doc.get("acceptance_class") or "")
    return 0 if acceptance_class in {"accepted", "review_required", "rejected"} else 2
