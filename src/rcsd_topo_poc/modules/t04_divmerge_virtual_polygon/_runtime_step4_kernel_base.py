from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Mapping, Sequence

from shapely.geometry import GeometryCollection, Point
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_contracts import (
    Stage4EvidenceDecision,
    Stage4EventInterpretationResult,
    Stage4EventReference,
    Stage4LegacyStep5Bridge,
    Stage4LegacyStep5Readiness,
    Stage4ReverseTipDecision,
    resolve_stage4_continuous_chain_decision,
    wrap_stage4_divstrip_context,
    wrap_stage4_kind_resolution,
    wrap_stage4_multibranch_decision,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad

from ._runtime_step4_geometry_core import *
from ._runtime_step4_geometry_base import *
from ._runtime_step2_local_context import _validate_drivezone_containment
from ._runtime_step3_topology_skeleton import _build_stage4_road_branches_for_member_nodes
from ._runtime_step4_surface import _resolve_centerline_from_road_ids

from ._runtime_step4_kernel_geometry import *

def _evaluate_branch_middle_gate(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    candidate_point,
    candidate_scan_s: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    divstrip_geometry,
) -> dict[str, Any]:
    if (
        candidate_point is None
        or candidate_point.is_empty
        or divstrip_geometry is None
        or divstrip_geometry.is_empty
    ):
        return {
            "valid": False,
            "signal": "event_reference_outside_branch_middle",
            "reason": "missing_candidate_or_divstrip",
            "point": candidate_point,
            "chosen_s_m": float(candidate_scan_s),
            "point_distance_m": math.inf,
            "component_distance_m": math.inf,
            "branch_middle_overlap": 0.0,
        }

    search_offsets = [0.0, -1.0, 1.0, -2.0, 2.0, -4.0, 4.0]
    best_result: dict[str, Any] | None = None
    for offset in search_offsets:
        if abs(float(offset)) > float(EVENT_REFERENCE_BRANCH_MIDDLE_SCAN_WINDOW_M) + 1e-9:
            continue
        scan_s = float(candidate_scan_s) + float(offset)
        probe_point = (
            candidate_point
            if abs(float(offset)) <= 1e-9
            else _materialize_divstrip_core_point(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=float(scan_s),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                divstrip_geometry=divstrip_geometry,
            )
        )
        if probe_point is None or probe_point.is_empty:
            continue
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=float(scan_s),
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is None or not segment_diag["ok"]:
            continue
        point_distance_m = float(probe_point.distance(found_segment))
        component_related, component_distance_m, branch_middle_overlap = _component_reference_overlap_metrics(
            component_geometry=divstrip_geometry,
            reference_geometry=found_segment,
            reference_buffer_m=float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M),
        )
        point_related = point_distance_m <= float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M)
        valid = bool(
            point_related
            and (
                bool(component_related)
                or float(branch_middle_overlap) > 1e-6
                or float(component_distance_m) <= float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M)
            )
        )
        score = (
            1 if valid else 0,
            1 if point_related else 0,
            1 if component_related else 0,
            float(branch_middle_overlap),
            -float(point_distance_m),
            -float(component_distance_m),
            -abs(float(offset)),
        )
        candidate_result = {
            "valid": valid,
            "signal": None if valid else "event_reference_outside_branch_middle",
            "reason": "branch_middle_gate_pass" if valid else "outside_branch_middle_tolerance",
            "point": probe_point,
            "chosen_s_m": _project_point_to_axis(
                probe_point,
                origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                axis_unit_vector=scan_axis_unit_vector,
            ),
            "point_distance_m": float(point_distance_m),
            "component_distance_m": float(component_distance_m),
            "branch_middle_overlap": float(branch_middle_overlap),
            "_score": score,
        }
        if best_result is None or score > best_result["_score"]:
            best_result = candidate_result

    if best_result is None:
        return {
            "valid": False,
            "signal": "event_reference_outside_branch_middle",
            "reason": "missing_branch_middle_reference",
            "point": candidate_point,
            "chosen_s_m": float(candidate_scan_s),
            "point_distance_m": math.inf,
            "component_distance_m": math.inf,
            "branch_middle_overlap": 0.0,
        }
    best_result.pop("_score", None)
    return best_result


def _resolve_event_reference_point(
    *,
    representative_node: ParsedNode,
    event_anchor_geometry,
    divstrip_constraint_geometry,
    all_divstrip_geometry,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    drivezone_union,
    branch_a_centerline,
    branch_b_centerline,
    cross_half_len_m: float,
    patch_size_m: float,
    excluded_axis_s_values: list[float] | None = None,
    excluded_axis_tolerance_m: float = 5.0,
) -> dict[str, Any]:
    fallback_point, fallback_source = _resolve_event_origin_point(
        representative_node=representative_node,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_centerline=axis_centerline,
    )
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": fallback_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_axis",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    scan_origin_point, _ = nearest_points(axis_centerline, fallback_point)
    base_scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_2,
    )
    if base_scan_axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_scan_dir",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    search_limit_m = min(
        float(EVENT_REFERENCE_SCAN_MAX_M),
        max(float(EVENT_SPAN_MAX_M * 2.0), float(patch_size_m) * 0.45),
    )
    step_m = max(float(EVENT_REFERENCE_SCAN_STEP_M), 0.5)
    scan_values = [0.0]
    cursor = step_m
    while cursor <= search_limit_m + 1e-9:
        scan_values.append(float(cursor))
        cursor += step_m

    selected_divstrip_geometry = (
        divstrip_constraint_geometry
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty
        else all_divstrip_geometry
    )

    def _tip_projection_for_scan(scan_vec: tuple[float, float] | None) -> float | None:
        if (
            scan_vec is None
            or selected_divstrip_geometry is None
            or selected_divstrip_geometry.is_empty
        ):
            return None
        tip_point = _tip_point_from_divstrip(
            divstrip_geometry=selected_divstrip_geometry,
            scan_axis_unit_vector=scan_vec,
            origin_point=scan_origin_point,
        )
        if tip_point is None or tip_point.is_empty:
            return None
        candidate_tip_s = _project_point_to_axis(
            tip_point,
            origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
            axis_unit_vector=scan_vec,
        )
        if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
            return float(candidate_tip_s)
        return None

    divstrip_components = _collect_polygon_components(all_divstrip_geometry)
    scan_axis_unit_vector = base_scan_axis_unit_vector
    tip_s_forward = _tip_projection_for_scan(base_scan_axis_unit_vector)
    tip_s = tip_s_forward

    first_divstrip_hit_s = None
    drivezone_split_s = None
    drivezone_split_source = "none"
    scan_samples: list[tuple[float, Any]] = []
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=scan_dist_m,
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        probe_geometry = (
            found_segment
            if found_segment is not None and segment_diag["ok"]
            else crossline
        )
        scan_samples.append((float(scan_dist_m), probe_geometry))
        if drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
            drivezone_pieces = _segment_drivezone_pieces(
                segment=found_segment,
                drivezone_union=drivezone_union,
                min_piece_len_m=0.5,
            )
            if len(drivezone_pieces) >= 2:
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                extended_segment = _extend_line_to_half_len(
                    line=found_segment,
                    half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                )
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=extended_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=crossline,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "full_crossline"
            if drivezone_split_s is not None and drivezone_split_source == "none":
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
        if (
            first_divstrip_hit_s is None
            and selected_divstrip_geometry is not None
            and not selected_divstrip_geometry.is_empty
            and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
        ):
            first_divstrip_hit_s = float(scan_dist_m)

    if (
        drivezone_split_s is not None
        and len(divstrip_components) > 1
        and abs(float(drivezone_split_s)) >= 5.0 - 1e-9
    ):
        split_component, _split_component_distance = _pick_divstrip_component_near_split(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            split_s=float(drivezone_split_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_components=divstrip_components,
        )
        if split_component is not None and not split_component.is_empty:
            selected_divstrip_geometry = split_component
            tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            tip_s = None
            if tip_point is not None and not tip_point.is_empty:
                candidate_tip_s = _project_point_to_axis(
                    tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
                    tip_s = float(candidate_tip_s)
            first_divstrip_hit_s, _best_divstrip_distance = _scan_first_divstrip_hit(
                scan_samples=scan_samples,
                divstrip_geometry=selected_divstrip_geometry,
                div_tol_m=float(EVENT_REFERENCE_DIVSTRIP_TOL_M),
            )

    divstrip_ref_s = None
    divstrip_ref_source = "none"
    if tip_s is not None:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"
    elif first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"

    if (
        drivezone_split_s is not None
        and drivezone_split_source == "full_crossline"
        and divstrip_ref_s is not None
        and abs(float(drivezone_split_s) - float(divstrip_ref_s)) > float(EVENT_REFERENCE_MAX_OFFSET_M)
    ):
        drivezone_split_s = None
        drivezone_split_source = "none"

    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=drivezone_split_s,
        max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
    )
    branch_middle_gate_signal: str | None = None
    branch_middle_gate_reason: str | None = None
    branch_middle_gate_phase: str | None = None
    force_reverse_probe = bool(
        divstrip_ref_s is None
        and selected_divstrip_geometry is not None
        and not selected_divstrip_geometry.is_empty
    )
    forward_drivezone_split_s = None if drivezone_split_s is None else float(drivezone_split_s)
    if force_reverse_probe:
        chosen_s = None
        position_source = "none"
        split_pick_source = "forward_divstrip_missing"
    resolved_candidate = None
    if chosen_s is not None:
        forward_candidate = _materialize_reference_candidate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            chosen_s=float(chosen_s),
            position_source=str(position_source),
            split_pick_source=str(split_pick_source),
            tip_s=None if tip_s is None else float(tip_s),
            first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            drivezone_split_s=None if drivezone_split_s is None else float(drivezone_split_s),
            divstrip_ref_s=None if divstrip_ref_s is None else float(divstrip_ref_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            selected_divstrip_geometry=selected_divstrip_geometry,
            drivezone_union=drivezone_union,
            all_divstrip_geometry=all_divstrip_geometry,
            step_m=step_m,
        )
        forward_gate = _evaluate_branch_middle_gate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            candidate_point=forward_candidate["origin_point"],
            candidate_scan_s=float(forward_candidate["chosen_s_m"]),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_geometry=selected_divstrip_geometry,
        )
        forward_axis_conflict = False
        if forward_gate["valid"] and excluded_axis_s_values:
            forward_chosen_s_value = float(forward_gate["chosen_s_m"])
            for prior_s in excluded_axis_s_values:
                if abs(float(prior_s) - forward_chosen_s_value) <= float(excluded_axis_tolerance_m) + 1e-9:
                    forward_axis_conflict = True
                    break
        if forward_gate["valid"] and not forward_axis_conflict:
            resolved_candidate = dict(forward_candidate)
            resolved_candidate["origin_point"] = forward_gate["point"]
            resolved_candidate["chosen_s_m"] = float(forward_gate["chosen_s_m"])
        else:
            if forward_axis_conflict:
                branch_middle_gate_signal = "event_reference_axis_conflict_with_prior_unit"
                branch_middle_gate_reason = "forward_axis_position_overlaps_prior_unit"
            else:
                branch_middle_gate_signal = str(forward_gate["signal"] or "event_reference_outside_branch_middle")
                branch_middle_gate_reason = str(forward_gate["reason"] or "outside_branch_middle_tolerance")
            branch_middle_gate_phase = "forward"
            chosen_s = None
            position_source = "none"
            split_pick_source = (
                f"{split_pick_source}_axis_conflict_with_prior_unit"
                if forward_axis_conflict
                else f"{split_pick_source}_outside_branch_middle"
            )
    if chosen_s is None:
        reverse_scan_axis_unit_vector = (-float(scan_axis_unit_vector[0]), -float(scan_axis_unit_vector[1]))
        reverse_tip_s = None
        if selected_divstrip_geometry is not None and not selected_divstrip_geometry.is_empty:
            reverse_tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=reverse_scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            if reverse_tip_point is not None and not reverse_tip_point.is_empty:
                candidate_reverse_tip_s = _project_point_to_axis(
                    reverse_tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if -float(search_limit_m) - 1e-9 <= float(candidate_reverse_tip_s) <= 1e-9:
                    reverse_tip_s = float(candidate_reverse_tip_s)

        reverse_first_divstrip_hit_s = None
        reverse_drivezone_split_s = None
        for scan_dist_m in scan_values:
            reverse_scan_dist = -float(scan_dist_m)
            crossline = _build_event_crossline(
                origin_point=scan_origin_point,
                axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=reverse_scan_dist,
                cross_half_len_m=cross_half_len_m,
            )
            center_point = crossline.interpolate(0.5, normalized=True)
            found_segment, segment_diag = _build_between_branches_segment(
                crossline=crossline,
                center_point=center_point,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
            )
            probe_geometry = (
                found_segment
                if found_segment is not None and segment_diag["ok"]
                else crossline
            )
            if reverse_drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=found_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) < 2:
                    extended_segment = _extend_line_to_half_len(
                        line=found_segment,
                        half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                    )
                    drivezone_pieces = _segment_drivezone_pieces(
                        segment=extended_segment,
                        drivezone_union=drivezone_union,
                        min_piece_len_m=0.5,
                    )
                if len(drivezone_pieces) >= 2:
                    reverse_drivezone_split_s = reverse_scan_dist
            if (
                reverse_first_divstrip_hit_s is None
                and selected_divstrip_geometry is not None
                and not selected_divstrip_geometry.is_empty
                and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
            ):
                reverse_first_divstrip_hit_s = reverse_scan_dist

        reverse_divstrip_ref_s = None
        reverse_divstrip_ref_source = "none"
        if reverse_tip_s is not None:
            reverse_divstrip_ref_s = float(reverse_tip_s)
            reverse_divstrip_ref_source = "tip_projection"
        elif reverse_first_divstrip_hit_s is not None:
            reverse_divstrip_ref_s = float(reverse_first_divstrip_hit_s)
            reverse_divstrip_ref_source = "first_hit"
        reverse_chosen_s, reverse_position_source, reverse_split_pick_source = _pick_reference_s(
            divstrip_ref_s=reverse_divstrip_ref_s,
            divstrip_ref_source=reverse_divstrip_ref_source,
            drivezone_split_s=reverse_drivezone_split_s,
            max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
        )
        if reverse_chosen_s is not None:
            chosen_s = float(reverse_chosen_s)
            position_source = str(reverse_position_source)
            split_pick_source = f"reverse_{reverse_split_pick_source}"
            tip_s = None if reverse_tip_s is None else float(reverse_tip_s)
            first_divstrip_hit_s = (
                None if reverse_first_divstrip_hit_s is None else float(reverse_first_divstrip_hit_s)
            )
            drivezone_split_s = (
                None if reverse_drivezone_split_s is None else float(reverse_drivezone_split_s)
            )
            divstrip_ref_source = str(reverse_divstrip_ref_source)
            reverse_candidate = _materialize_reference_candidate(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                chosen_s=float(chosen_s),
                position_source=str(position_source),
                split_pick_source=str(split_pick_source),
                tip_s=None if tip_s is None else float(tip_s),
                first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                drivezone_split_s=None if drivezone_split_s is None else float(drivezone_split_s),
                divstrip_ref_s=None if reverse_divstrip_ref_s is None else float(reverse_divstrip_ref_s),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                selected_divstrip_geometry=selected_divstrip_geometry,
                drivezone_union=drivezone_union,
                all_divstrip_geometry=all_divstrip_geometry,
                step_m=step_m,
            )
            reverse_gate = _evaluate_branch_middle_gate(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                candidate_point=reverse_candidate["origin_point"],
                candidate_scan_s=float(reverse_candidate["chosen_s_m"]),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                divstrip_geometry=selected_divstrip_geometry,
            )
            reverse_axis_conflict = False
            if reverse_gate["valid"] and excluded_axis_s_values:
                reverse_chosen_s_value = float(reverse_gate["chosen_s_m"])
                for prior_s in excluded_axis_s_values:
                    if abs(float(prior_s) - reverse_chosen_s_value) <= float(excluded_axis_tolerance_m) + 1e-9:
                        reverse_axis_conflict = True
                        break
            if reverse_gate["valid"] and not reverse_axis_conflict:
                resolved_candidate = dict(reverse_candidate)
                resolved_candidate["origin_point"] = reverse_gate["point"]
                resolved_candidate["chosen_s_m"] = float(reverse_gate["chosen_s_m"])
            else:
                chosen_s = None
                if reverse_axis_conflict:
                    branch_middle_gate_signal = "event_reference_axis_conflict_with_prior_unit"
                    branch_middle_gate_reason = "reverse_axis_position_overlaps_prior_unit"
                else:
                    branch_middle_gate_signal = str(reverse_gate["signal"] or "event_reference_outside_branch_middle")
                    branch_middle_gate_reason = str(reverse_gate["reason"] or "outside_branch_middle_tolerance")
                branch_middle_gate_phase = "reverse"
    if resolved_candidate is None and chosen_s is None and force_reverse_probe and forward_drivezone_split_s is not None:
        chosen_s = float(forward_drivezone_split_s)
        position_source = "drivezone_split"
        split_pick_source = "drivezone_split_window_after_reverse_probe"
        fallback_candidate = _materialize_reference_candidate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            chosen_s=float(chosen_s),
            position_source=str(position_source),
            split_pick_source=str(split_pick_source),
            tip_s=None if tip_s is None else float(tip_s),
            first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            drivezone_split_s=float(forward_drivezone_split_s),
            divstrip_ref_s=None if divstrip_ref_s is None else float(divstrip_ref_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            selected_divstrip_geometry=selected_divstrip_geometry,
            drivezone_union=drivezone_union,
            all_divstrip_geometry=all_divstrip_geometry,
            step_m=step_m,
        )
        fallback_gate = _evaluate_branch_middle_gate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            candidate_point=fallback_candidate["origin_point"],
            candidate_scan_s=float(fallback_candidate["chosen_s_m"]),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_geometry=selected_divstrip_geometry,
        )
        if fallback_gate["valid"]:
            resolved_candidate = dict(fallback_candidate)
            resolved_candidate["origin_point"] = fallback_gate["point"]
            resolved_candidate["chosen_s_m"] = float(fallback_gate["chosen_s_m"])
        else:
            chosen_s = None
            branch_middle_gate_signal = str(fallback_gate["signal"] or "event_reference_outside_branch_middle")
            branch_middle_gate_reason = str(fallback_gate["reason"] or "outside_branch_middle_tolerance")
            branch_middle_gate_phase = "fallback"
    if resolved_candidate is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "forward" if kind_2 == 16 else "backward",
            "chosen_s_m": None,
            "tip_s_m": None if tip_s is None else float(tip_s),
            "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
            "position_source": "fallback",
            "split_pick_source": f"{split_pick_source}_fallback",
            "divstrip_ref_source": str(divstrip_ref_source),
            "divstrip_ref_offset_m": None,
            "branch_middle_gate_signal": branch_middle_gate_signal,
            "branch_middle_gate_reason": branch_middle_gate_reason,
            "branch_middle_gate_phase": branch_middle_gate_phase,
            "branch_middle_gate_passed": False,
        }
    final_scan_s = float(resolved_candidate["chosen_s_m"])
    chosen_point = resolved_candidate["origin_point"]
    split_pick_source = str(resolved_candidate["split_pick_source"])
    divstrip_ref_offset_m = (
        None
        if divstrip_ref_s is None
        else float(abs(float(final_scan_s) - float(divstrip_ref_s)))
    )
    return {
        "origin_point": chosen_point,
        "event_origin_source": f"chosen_s_{position_source}",
        "scan_origin_point": scan_origin_point,
        "scan_dir_label": "forward" if kind_2 == 16 else "backward",
        "chosen_s_m": float(final_scan_s),
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
        "position_source": str(position_source),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source),
        "divstrip_ref_offset_m": divstrip_ref_offset_m,
        "branch_middle_gate_signal": branch_middle_gate_signal,
        "branch_middle_gate_reason": branch_middle_gate_reason,
        "branch_middle_gate_phase": branch_middle_gate_phase,
        "branch_middle_gate_passed": True,
    }




__all__ = [name for name in globals() if not name.startswith("__")]
