from __future__ import annotations

from dataclasses import dataclass
import json
import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, nearest_points, unary_union

from .segment_first_carrier_context import (
    longest_line as _longest_line,
    prepare_assignment_context,
    prepare_endpoint_surfaces_by_segment,
    prepare_reference_by_segment,
    prepare_road_by_id,
    prepare_through_surfaces_by_segment,
    reservation_overlap_fraction,
)
from .segment_first_corridors import (
    CorridorAssembly,
    assemble_directional_corridor,
    evidence_direction_role,
)
from .segment_first_geometry_cache import buffered_union
from .segment_first_geometry_metrics import (
    surface_coverage as _surface_coverage,
    surface_coverage_at_least as _surface_coverage_at_least,
)
from .segment_first_member_recovery import recover_dual_target_member_carriers
from .segment_first_partial_members import build_partial_member_carriers
from .segment_first_skeleton import canonical_id, parse_id_list
from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)
from .segment_first_surface_bridge import (
    build_endpoint_surface_bridge_assembly,
)
from .segment_first_surface_routing import (
    route_endpoint_to_surface,
    route_tangent_endpoint_to_surface,
)
from .segment_first_target_path_cache import (
    select_directed_target_path as _select_directed_target_path_cached,
)
from .segment_first_types import ReplacementScope, SegmentState, validate_publication_state


@dataclass(frozen=True)
class CarrierPlanResult:
    segment_plans: gpd.GeoDataFrame
    carriers: gpd.GeoDataFrame
    summary: dict[str, object]
    segment_summary_contributions: dict[str, dict[str, int]]
    segment_carrier_column_orders: dict[str, tuple[str, ...]]


def plan_segment_carriers(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    *,
    run_id: str,
    explicit_pairs: pd.DataFrame | None = None,
    drivezones: gpd.GeoDataFrame | None = None,
    target_reference_axes: gpd.GeoDataFrame | None = None,
    required_endpoint_surfaces: gpd.GeoDataFrame | None = None,
    endpoint_surface_segment_ids: set[str] | None = None,
    required_through_surfaces: gpd.GeoDataFrame | None = None,
    forced_through_access_ids: set[str] | None = None,
    through_surface_max_distance_m: float = 20.0,
    minimum_member_coverage: float = 0.60,
    sample_spacing_m: float = 2.0,
    completion_min_coverage: float = 0.90,
    maximum_target_main_angle_deg: float = 35.0,
    forced_retained_segment_ids: set[str] | None = None,
    forced_suppressed_local_connector_keys: set[str] | None = None,
    directional_member_roles: dict[tuple[str, str, str], str] | None = None,
) -> CarrierPlanResult:
    forced_retained = forced_retained_segment_ids or set()
    endpoint_surface_segment_ids = endpoint_surface_segment_ids or set()
    forced_suppressed_local_connectors = (
        forced_suppressed_local_connector_keys or set()
    )
    directional_member_roles = directional_member_roles or {}
    road_by_id = prepare_road_by_id(swsd_roads)
    assignment_context = prepare_assignment_context(assignments)
    access_reservation_buffers = assignment_context.access_reservation_buffers
    evidence_by_member = assignment_context.evidence_by_member
    eligible_by_segment = assignment_context.eligible_by_segment
    recovery_by_segment = assignment_context.recovery_by_segment
    empty_eligible = assignment_context.empty_eligible
    empty_recovery = assignment_context.empty_recovery
    carrier_roles_by_member: dict[tuple[str, str], dict[str, str]] = {}
    required_roles_by_segment: dict[str, set[tuple[str, str]]] = {}
    for (
        role_segment_id,
        role_member_id,
        direction_role,
    ), carrier_role in directional_member_roles.items():
        carrier_roles_by_member.setdefault(
            (role_segment_id, role_member_id),
            {},
        )[direction_role] = carrier_role
        required_roles_by_segment.setdefault(role_segment_id, set()).add(
            (role_member_id, carrier_role)
        )
    connector_pair_counts = _connector_pair_counts(explicit_pairs)
    drivezone_surface = (
        buffered_union(drivezones, 1.0)
        if drivezones is not None and not drivezones.empty
        else None
    )
    reference_by_segment = prepare_reference_by_segment(target_reference_axes)
    through_surfaces_by_segment = prepare_through_surfaces_by_segment(
        required_through_surfaces
    )
    all_endpoint_surfaces_by_segment = prepare_endpoint_surfaces_by_segment(
        required_endpoint_surfaces
    )
    endpoint_surfaces_by_segment = {
        segment_id: surfaces
        for segment_id, surfaces in all_endpoint_surfaces_by_segment.items()
        if segment_id in endpoint_surface_segment_ids
    }
    plan_rows: list[dict[str, object]] = []
    carrier_rows: list[dict[str, object]] = []
    segment_summary_contributions: dict[str, dict[str, int]] = {}
    segment_carrier_column_orders: dict[str, tuple[str, ...]] = {}
    insufficient_members = 0
    suppressed_connectors = 0
    published_connectors = 0
    forced_suppressed_connectors = 0
    assembled_source_count = 0
    target_fragment_takeover_count = 0
    member_surface_inference_takeover_count = 0
    baseline_recovery_takeover_count = 0
    access_surface_recovery_takeover_count = 0
    access_support_carrier_count = 0
    progress_stage = "segment_carrier"
    progress_built_count = 0
    progress_retained_count = 0
    progress_review_count = 0
    begin_progress_stage(
        progress_stage,
        len(segment_units),
        detail="plan_segment_carriers",
    )
    for segment in segment_units.itertuples():
        segment_id = str(segment.segment_id)
        carrier_start = len(carrier_rows)
        counter_start = {
            "insufficient_member_count": insufficient_members,
            "assembled_patch_source_count": assembled_source_count,
            "published_local_connector_count": published_connectors,
            "suppressed_local_connector_count": suppressed_connectors,
            "forced_suppressed_local_connector_count": (
                forced_suppressed_connectors
            ),
            "target_fragment_takeover_count": target_fragment_takeover_count,
            "member_surface_inference_takeover_count": (
                member_surface_inference_takeover_count
            ),
            "baseline_recovery_takeover_count": (
                baseline_recovery_takeover_count
            ),
            "access_surface_recovery_takeover_count": (
                access_surface_recovery_takeover_count
            ),
            "access_support_carrier_count": access_support_carrier_count,
        }
        member_ids = parse_id_list(segment.swsd_road_ids)
        conflict_retained = segment_id in forced_retained
        built_count = 0
        retained_count = 0
        replaced_members = 0
        partial_member_takeover = False
        partial_member_ids: set[str] = set()
        segment_evidence = eligible_by_segment.get(segment_id, empty_eligible)
        segment_recovery = recovery_by_segment.get(segment_id, empty_recovery)

        for member_id in member_ids:
            member = road_by_id.loc[member_id] if member_id in road_by_id.index else None
            evidence = (
                None if conflict_retained else evidence_by_member.get((segment_id, member_id))
            )
            built_rows: list[dict[str, object]] = []
            if member is not None and evidence is not None and not evidence.empty:
                directional = evidence[evidence["carrier_role"].eq("directional_corridor")].copy()
                built_rows = _member_carriers(
                    segment_id,
                    member_id,
                    member,
                    directional,
                    run_id=run_id,
                    drivezone_surface=drivezone_surface,
                    minimum_member_coverage=minimum_member_coverage,
                    sample_spacing_m=sample_spacing_m,
                    completion_min_coverage=completion_min_coverage,
                    carrier_roles_by_direction=carrier_roles_by_member.get(
                        (segment_id, member_id),
                        {},
                    ),
                    allow_surface_inferred_counterpart=False,
                )
                if (
                    not built_rows
                    and not bool(getattr(segment, "target_required", False))
                ):
                    built_rows = build_partial_member_carriers(
                        segment_id,
                        member_id,
                        member,
                        directional,
                        run_id=run_id,
                        drivezone_surface=drivezone_surface,
                        full_minimum_coverage=minimum_member_coverage,
                        sample_spacing_m=sample_spacing_m,
                        completion_min_coverage=completion_min_coverage,
                        member_carrier_builder=_member_carriers,
                        carrier_roles_by_direction=carrier_roles_by_member.get(
                            (segment_id, member_id),
                            {},
                        ),
                    )
            if built_rows:
                carrier_rows.extend(built_rows)
                member_built_count = sum(
                    str(row.get("realization", "")) == "built"
                    for row in built_rows
                )
                member_retained_count = len(built_rows) - member_built_count
                built_count += member_built_count
                retained_count += member_retained_count
                assembled_source_count += sum(
                    len(str(row["source_patch_road_keys"]).split(","))
                    for row in built_rows
                    if str(row.get("realization", "")) == "built"
                )
                if member_retained_count:
                    partial_member_takeover = True
                    partial_member_ids.add(member_id)
                else:
                    replaced_members += 1
            else:
                if evidence is not None and not evidence.empty and not conflict_retained:
                    insufficient_members += 1
                if member is None:
                    continue
                carrier_rows.append(_retained_carrier(member, segment_id, member_id, run_id))
                retained_count += 1

        segment_rows = carrier_rows[carrier_start:]
        if partial_member_ids and any(
            str(row.get("realization", "")) == "built"
            and "partial_member" not in str(row.get("assembly_state", ""))
            for row in segment_rows
        ):
            removed = [
                row
                for row in segment_rows
                if str(row.get("member_swsd_road_id", ""))
                in partial_member_ids
            ]
            retained = [
                _retained_carrier(
                    road_by_id.loc[member_id],
                    segment_id,
                    member_id,
                    run_id,
                )
                for member_id in sorted(partial_member_ids)
            ]
            carrier_rows[carrier_start:] = [
                row
                for row in segment_rows
                if str(row.get("member_swsd_road_id", ""))
                not in partial_member_ids
            ] + retained
            assembled_source_count -= sum(
                len(str(row.get("source_patch_road_keys", "")).split(","))
                for row in removed
                if str(row.get("realization", "")) == "built"
            )
            built_count = sum(
                str(row.get("realization", "")) == "built"
                for row in carrier_rows[carrier_start:]
            )
            retained_count = sum(
                str(row.get("realization", "")) == "retained"
                for row in carrier_rows[carrier_start:]
            )
            partial_member_takeover = False
            partial_member_ids.clear()

        target_fragment_takeover = False
        member_surface_inference_takeover = False
        if (
            not conflict_retained
            and bool(getattr(segment, "target_required", False))
            and (
                str(getattr(segment, "target_class", "")) == "advance_right"
                or segment_id in endpoint_surface_segment_ids
                or not _mandatory_main_roles_complete(
                    carrier_rows[carrier_start:],
                    str(getattr(segment, "target_class", "")),
                    str(getattr(segment, "sgrade", "") or ""),
                    required_member_roles=required_roles_by_segment.get(
                        segment_id,
                        set(),
                    ),
                )
            )
        ):
            fragment_rows = _target_fragment_carriers(
                segment,
                segment_evidence,
                member_ids,
                run_id,
                road_by_id=road_by_id,
                drivezone_surface=drivezone_surface,
                minimum_member_coverage=minimum_member_coverage,
                sample_spacing_m=sample_spacing_m,
                completion_min_coverage=completion_min_coverage,
                explicit_pairs=explicit_pairs,
                reference_geometry=reference_by_segment.get(segment_id),
                required_surfaces=endpoint_surfaces_by_segment.get(
                    segment_id, ()
                ),
                surface_max_distance_m=through_surface_max_distance_m,
                maximum_main_angle_deg=maximum_target_main_angle_deg,
            )
            recovery_used = False
            access_recovery = segment_recovery[
                segment_recovery["assignment_source"].eq(
                    "target_access_surface_candidate"
                )
            ] if not segment_recovery.empty else segment_recovery
            permitted_recovery = (
                segment_recovery
                if str(getattr(segment, "sgrade", "") or "").endswith("双")
                else access_recovery
            )
            if (
                not _mandatory_main_roles_complete(
                    fragment_rows,
                    str(getattr(segment, "target_class", "")),
                    str(getattr(segment, "sgrade", "") or ""),
                )
                and str(getattr(segment, "target_class", "")) == "core_trunk"
                and not permitted_recovery.empty
            ):
                recovery_keys = set(permitted_recovery["patch_road_key"].astype(str))
                recovered_evidence = gpd.GeoDataFrame(
                    pd.concat(
                        [
                            segment_evidence[
                                ~segment_evidence["patch_road_key"].astype(str).isin(
                                    recovery_keys
                                )
                            ],
                            permitted_recovery,
                        ],
                        ignore_index=True,
                        sort=False,
                    ),
                    geometry="geometry",
                    crs=segment_evidence.crs,
                )
                recovered_rows = _target_fragment_carriers(
                    segment,
                    recovered_evidence,
                    member_ids,
                    run_id,
                    road_by_id=road_by_id,
                    drivezone_surface=drivezone_surface,
                    minimum_member_coverage=minimum_member_coverage,
                    sample_spacing_m=sample_spacing_m,
                    completion_min_coverage=completion_min_coverage,
                    explicit_pairs=explicit_pairs,
                    reference_geometry=reference_by_segment.get(segment_id),
                    required_surfaces=endpoint_surfaces_by_segment.get(
                        segment_id, ()
                    ),
                    surface_max_distance_m=through_surface_max_distance_m,
                    maximum_main_angle_deg=maximum_target_main_angle_deg,
                )
                if _mandatory_main_roles_complete(
                    recovered_rows,
                    str(getattr(segment, "target_class", "")),
                    str(getattr(segment, "sgrade", "") or ""),
                ):
                    fragment_rows = recovered_rows
                    recovery_used = True
                    recovery_sources = set(
                        permitted_recovery["assignment_source"].astype(str)
                    )
                    access_surface_used = (
                        "target_access_surface_candidate" in recovery_sources
                    )
                    for row in fragment_rows:
                        row["assembly_state"] = (
                            f"{row.get('assembly_state', '')}+"
                            f"{'access_surface_recovery' if access_surface_used else 'baseline_role_recovery'}"
                        )
                        row["reason_codes"] = (
                            "target_access_surface_recovered"
                            if access_surface_used
                            else "target_baseline_missing_role_recovered"
                        )
            if (
                not _mandatory_main_roles_complete(
                    fragment_rows,
                    str(getattr(segment, "target_class", "")),
                    str(getattr(segment, "sgrade", "") or ""),
                )
                and str(getattr(segment, "target_class", "")) == "core_trunk"
                and str(getattr(segment, "sgrade", "") or "").endswith("双")
                and drivezone_surface is not None
                and not _mandatory_main_roles_complete(
                    carrier_rows[carrier_start:],
                    str(getattr(segment, "target_class", "")),
                    str(getattr(segment, "sgrade", "") or ""),
                    required_member_roles=required_roles_by_segment.get(
                        segment_id,
                        set(),
                    ),
                )
            ):
                inferred_member_rows = recover_dual_target_member_carriers(
                    segment_id,
                    member_ids,
                    road_by_id,
                    evidence_by_member,
                    directional_member_roles,
                    run_id=run_id,
                    drivezone_surface=drivezone_surface,
                    minimum_member_coverage=minimum_member_coverage,
                    sample_spacing_m=sample_spacing_m,
                    completion_min_coverage=completion_min_coverage,
                    required_surfaces=endpoint_surfaces_by_segment.get(
                        segment_id, ()
                    ),
                    surface_max_distance_m=through_surface_max_distance_m,
                    member_carrier_builder=_member_carriers,
                )
                if inferred_member_rows:
                    fragment_rows = inferred_member_rows
                    member_surface_inference_takeover = True
            if _mandatory_main_roles_complete(
                fragment_rows,
                str(getattr(segment, "target_class", "")),
                str(getattr(segment, "sgrade", "") or ""),
            ):
                assembled_source_count -= sum(
                    len(str(row.get("source_patch_road_keys", "")).split(","))
                    for row in carrier_rows[carrier_start:]
                    if str(row.get("realization", "")) == "built"
                )
                retained_endpoint_rows = (
                    _target_function_retained_carriers(
                        segment,
                        member_ids,
                        road_by_id,
                        fragment_rows,
                        run_id,
                        forced_through_access_ids or set(),
                    )
                )
                del carrier_rows[carrier_start:]
                carrier_rows.extend(fragment_rows)
                carrier_rows.extend(retained_endpoint_rows)
                built_count = len(fragment_rows)
                retained_count = len(retained_endpoint_rows)
                retained_member_ids = {
                    str(row["member_swsd_road_id"])
                    for row in retained_endpoint_rows
                }
                replaced_members = len(member_ids) - len(retained_member_ids)
                assembled_source_count += sum(
                    len(str(row["source_patch_road_keys"]).split(","))
                    for row in fragment_rows
                )
                target_fragment_takeover = True
                if member_surface_inference_takeover:
                    member_surface_inference_takeover_count += 1
                else:
                    target_fragment_takeover_count += 1
                if recovery_used:
                    if any(
                        "access_surface_recovery" in str(
                            row.get("assembly_state", "")
                        )
                        for row in fragment_rows
                    ):
                        access_surface_recovery_takeover_count += 1
                    else:
                        baseline_recovery_takeover_count += 1

        if (
            not conflict_retained
            and not target_fragment_takeover
            and forced_through_access_ids
        ):
            (
                function_rows,
                locally_retained_member_ids,
                removed_source_count,
            ) = _retain_member_level_forced_through_functions(
                segment_id,
                member_ids,
                road_by_id,
                carrier_rows[carrier_start:],
                run_id,
                forced_through_access_ids,
            )
            carrier_rows[carrier_start:] = function_rows
            assembled_source_count -= removed_source_count
            replaced_members = max(
                0,
                replaced_members - len(locally_retained_member_ids),
            )
            built_count = sum(
                str(row.get("realization", "")) == "built"
                for row in function_rows
            )
            retained_count = sum(
                str(row.get("realization", "")) == "retained"
                for row in function_rows
            )

        if (
            not conflict_retained
            and bool(getattr(segment, "target_required", False))
            and str(getattr(segment, "target_class", "")) == "core_trunk"
            and not segment_evidence.empty
        ):
            support_reference = reference_by_segment.get(segment_id)
            if support_reference is None:
                support_reference = _longest_line(segment.geometry)
            support_rows = _target_access_support_carriers(
                segment_id,
                member_ids,
                segment_evidence,
                carrier_rows[carrier_start:],
                through_surfaces_by_segment.get(segment_id, ()),
                support_reference,
                run_id,
                surface_max_distance_m=through_surface_max_distance_m,
                reserved_access_candidates=access_reservation_buffers,
                reserved_access_segment_id=segment_id,
                reserved_access_candidates_prebuffered=True,
                forced_access_ids=forced_through_access_ids or set(),
                completion_surface=drivezone_surface,
                completion_min_coverage=completion_min_coverage,
            )
            carrier_rows.extend(support_rows)
            built_count += len(support_rows)
            access_support_carrier_count += len(support_rows)
            assembled_source_count += len(support_rows)

        if not conflict_retained and not segment_evidence.empty:
            for row in segment_evidence[segment_evidence["carrier_role"].eq("local_connector")].itertuples():
                key = str(row.patch_road_key)
                if key in forced_suppressed_local_connectors:
                    suppressed_connectors += 1
                    forced_suppressed_connectors += 1
                    continue
                pair_count = connector_pair_counts.get(str(row.patch_road_key), 0)
                if pair_count < 2:
                    suppressed_connectors += 1
                    continue
                carrier_rows.append(_local_connector_carrier(row, segment_id, run_id, pair_count))
                built_count += 1
                published_connectors += 1

        for row in carrier_rows[carrier_start:]:
            row["segment_type"] = str(
                getattr(segment, "segment_type", "normal") or "normal"
            )
            row["target_class"] = str(
                getattr(segment, "target_class", "not_target") or "not_target"
            )

        if conflict_retained:
            state = SegmentState.CONFLICT_RETAINED
            scope = ReplacementScope.NONE
        elif member_ids and replaced_members == len(member_ids):
            state = SegmentState.HP_FULL
            scope = ReplacementScope.ALL
        elif replaced_members or built_count:
            state = SegmentState.HP_PARTIAL
            scope = ReplacementScope.SUBSET
        else:
            state = SegmentState.SWSD_RETAINED
            scope = ReplacementScope.NONE
        validate_publication_state(state, scope, built_count, retained_count)
        plan_rows.append(
            {
                **segment._asdict(),
                "run_id": run_id,
                "segment_state": state.value,
                "replacement_scope": scope.value,
                "segment_publishable": True,
                "carrier_takeover_ready": state is SegmentState.HP_FULL,
                "built_road_count": built_count,
                "retained_road_count": retained_count,
                "reason_codes": (
                    "physical_handoff_failed_segment_atomic_fallback"
                    if state is SegmentState.CONFLICT_RETAINED
                    else "member_missing_direction_surface_inference_recovered"
                    if member_surface_inference_takeover
                    else "target_segment_patch_components_built"
                    if target_fragment_takeover
                    else "partial_member_observed_and_missing_span_retained"
                    if partial_member_takeover
                    else "all_required_member_roles_vector_built"
                    if state is SegmentState.HP_FULL
                    else "complete_member_level_built_retained_mix"
                    if state is SegmentState.HP_PARTIAL
                    else "no_complete_directional_member_takeover"
                ),
                "geometry": segment.geometry,
            }
        )
        segment_carrier_column_orders[segment_id] = tuple(
            dict.fromkeys(
                key
                for row in carrier_rows[carrier_start:]
                for key in row
            )
        )
        segment_summary_contributions[segment_id] = {
            "forced_retained_segment_count": int(conflict_retained),
            "endpoint_surface_scoped_segment_count": int(
                segment_id in endpoint_surfaces_by_segment
            ),
            "partial_member_takeover_count": sum(
                "partial_member" in str(row.get("assembly_state", ""))
                for row in carrier_rows[carrier_start:]
            ),
            "insufficient_member_count": int(
                insufficient_members
                - counter_start["insufficient_member_count"]
            ),
            "assembled_patch_source_count": int(
                assembled_source_count
                - counter_start["assembled_patch_source_count"]
            ),
            "published_local_connector_count": int(
                published_connectors
                - counter_start["published_local_connector_count"]
            ),
            "suppressed_local_connector_count": int(
                suppressed_connectors
                - counter_start["suppressed_local_connector_count"]
            ),
            "forced_suppressed_local_connector_count": int(
                forced_suppressed_connectors
                - counter_start["forced_suppressed_local_connector_count"]
            ),
            "target_fragment_takeover_count": int(
                target_fragment_takeover_count
                - counter_start["target_fragment_takeover_count"]
            ),
            "member_surface_inference_takeover_count": int(
                member_surface_inference_takeover_count
                - counter_start["member_surface_inference_takeover_count"]
            ),
            "baseline_recovery_takeover_count": int(
                baseline_recovery_takeover_count
                - counter_start["baseline_recovery_takeover_count"]
            ),
            "access_surface_recovery_takeover_count": int(
                access_surface_recovery_takeover_count
                - counter_start["access_surface_recovery_takeover_count"]
            ),
            "access_support_carrier_count": int(
                access_support_carrier_count
                - counter_start["access_support_carrier_count"]
            ),
        }
        progress_built_count += built_count
        progress_retained_count += retained_count
        progress_review_count += sum(
            bool(row.get("review_required", False))
            for row in carrier_rows[carrier_start:]
        )
        advance_progress(
            progress_stage,
            last_unit=segment_id,
            counters={
                "built": progress_built_count,
                "retained": progress_retained_count,
                "review": progress_review_count,
                "carrier_rows": len(carrier_rows),
            },
        )
    plans = gpd.GeoDataFrame(plan_rows, geometry="geometry", crs=segment_units.crs)
    carriers = gpd.GeoDataFrame(carrier_rows, geometry="geometry", crs=segment_units.crs)
    summary = {
        "segment_count": int(len(plans)),
        "state_counts": plans["segment_state"].value_counts().to_dict(),
        "built_carrier_count": int((carriers["realization"] == "built").sum()),
        "retained_carrier_count": int((carriers["realization"] == "retained").sum()),
        "forced_retained_segment_count": int(len(forced_retained)),
        "insufficient_member_count": int(insufficient_members),
        "assembled_patch_source_count": int(assembled_source_count),
        "published_local_connector_count": int(published_connectors),
        "suppressed_local_connector_count": int(suppressed_connectors),
        "forced_suppressed_local_connector_count": int(
            forced_suppressed_connectors
        ),
        "target_fragment_takeover_count": int(target_fragment_takeover_count),
        "member_surface_inference_takeover_count": int(
            member_surface_inference_takeover_count
        ),
        "baseline_recovery_takeover_count": int(baseline_recovery_takeover_count),
        "access_surface_recovery_takeover_count": int(
            access_surface_recovery_takeover_count
        ),
        "endpoint_surface_scoped_segment_count": int(
            len(endpoint_surfaces_by_segment)
        ),
        "access_support_carrier_count": int(access_support_carrier_count),
        "partial_member_takeover_count": int(
            carriers["assembly_state"]
            .fillna("")
            .astype(str)
            .str.contains("partial_member")
            .sum()
        ),
    }
    finish_progress_stage(
        progress_stage,
        counters={
            "built": summary["built_carrier_count"],
            "retained": summary["retained_carrier_count"],
            "review": progress_review_count,
            "carrier_rows": len(carriers),
        },
    )
    return CarrierPlanResult(
        plans,
        carriers,
        summary,
        segment_summary_contributions,
        segment_carrier_column_orders,
    )


def _member_carriers(
    segment_id: str,
    member_id: str,
    member: pd.Series,
    evidence: gpd.GeoDataFrame,
    *,
    run_id: str,
    drivezone_surface: object | None,
    minimum_member_coverage: float,
    sample_spacing_m: float,
    completion_min_coverage: float,
    carrier_roles_by_direction: dict[str, str] | None = None,
    allow_surface_inferred_counterpart: bool = False,
    required_surfaces: tuple[object, ...] = (),
    surface_max_distance_m: float = 20.0,
) -> list[dict[str, object]]:
    if evidence.empty:
        return []
    reference = member.geometry
    working = evidence.copy()
    working["direction_role"] = working.geometry.map(
        lambda geometry: evidence_direction_role(geometry, reference)
    )
    direction = int(member.get("direction", 1) or 1)
    assemblies: list[CorridorAssembly] = []
    if direction in {0, 1}:
        assemblies_by_role: dict[str, CorridorAssembly] = {}
        for role in ("forward", "reverse"):
            assembly = assemble_directional_corridor(
                working[working["direction_role"].eq(role)],
                reference,
                direction_role=role,
                drivezone_surface=drivezone_surface,
                minimum_coverage=minimum_member_coverage,
                sample_spacing_m=sample_spacing_m,
                completion_min_coverage=completion_min_coverage,
            )
            if assembly is not None:
                assemblies_by_role[role] = assembly
        if (
            len(assemblies_by_role) == 1
            and allow_surface_inferred_counterpart
            and drivezone_surface is not None
        ):
            observed_role = next(iter(assemblies_by_role))
            missing_role = (
                "reverse" if observed_role == "forward" else "forward"
            )
            inferred = _surface_inferred_counterpart(
                assemblies_by_role[observed_role],
                working[
                    working["direction_role"].eq(observed_role)
                ],
                reference,
                drivezone_surface,
                missing_role=missing_role,
                completion_min_coverage=completion_min_coverage,
            )
            if inferred is not None:
                assemblies_by_role[missing_role] = inferred
        if not {"forward", "reverse"}.issubset(assemblies_by_role):
            return []
        assemblies = [
            assemblies_by_role["forward"],
            assemblies_by_role["reverse"],
        ]
    else:
        required_role = "reverse" if direction == 3 else "forward"
        required = working[working["direction_role"].eq(required_role)]
        selected_role = (
            required_role
            if not required.empty
            else "reverse"
            if required_role == "forward"
            else "forward"
        )
        assembly = assemble_directional_corridor(
            working[working["direction_role"].eq(selected_role)],
            reference,
            direction_role=selected_role,
            drivezone_surface=drivezone_surface,
            minimum_coverage=minimum_member_coverage,
            sample_spacing_m=sample_spacing_m,
            completion_min_coverage=completion_min_coverage,
        )
        if assembly is None:
            return []
        assemblies.append(
            _reoriented_corridor_assembly(assembly, required_role)
        )
    if required_surfaces:
        endpoint_completion_distance_m = max(
            surface_max_distance_m,
            float(reference.length)
            * (1.0 - min(0.50, minimum_member_coverage)),
        )
        completed_assemblies = [
            _complete_target_assembly_to_endpoint_surfaces(
                assembly,
                required_surfaces,
                completion_surface=drivezone_surface,
                maximum_distance_m=endpoint_completion_distance_m,
                minimum_surface_coverage=completion_min_coverage,
            )
            for assembly in assemblies
        ]
        if any(assembly is None for assembly in completed_assemblies):
            return []
        assemblies = [
            assembly
            for assembly in completed_assemblies
            if assembly is not None
        ]
    return [
        _built_carrier(
            segment_id,
            member_id,
            evidence,
            assembly,
            run_id,
            member_direction=direction,
            carrier_role=(carrier_roles_by_direction or {}).get(
                assembly.direction_role
            ),
        )
        for assembly in assemblies
    ]


def _built_carrier(
    segment_id: str,
    member_id: str,
    evidence: gpd.GeoDataFrame,
    assembly: CorridorAssembly,
    run_id: str,
    *,
    member_direction: int,
    carrier_role: str | None = None,
) -> dict[str, object]:
    first = evidence.sort_values("patch_road_key", kind="stable").iloc[0].to_dict()
    keys = ",".join(assembly.source_patch_road_keys)
    lane_counts = _numeric_series(evidence, "lane_count")
    lane_widths = _numeric_series(evidence, "median_lane_width_m")
    quality = set(evidence.get("evidence_quality_state", pd.Series(dtype=str)).astype(str))
    role = carrier_role or (
        f"main_{assembly.direction_role}"
        if member_direction == 1
        else "main_oneway"
    )
    surface_inferred = "surface_inferred_from_observed_direction" in (
        assembly.assembly_state
    )
    return {
        **first,
        "road_id": "",
        "run_id": run_id,
        "segment_id": segment_id,
        "member_swsd_road_id": member_id,
        "carrier_id": f"built:{segment_id}:{member_id}:{role}",
        "carrier_role": role,
        "direction_role": assembly.direction_role,
        "realization": "built",
        "geometry_source": (
            "hp_constrained_completion"
            if surface_inferred
            else "hp_observed+hp_constrained_completion"
            if assembly.completion_fraction > 1e-9
            else "hp_observed"
        ),
        "source_object_type": "PATCH_DIRECTIONAL_CORRIDOR",
        "source_patch_id": ",".join(assembly.source_patch_ids),
        "source_patch_ids": ",".join(assembly.source_patch_ids),
        "patch_road_key": assembly.source_patch_road_keys[0],
        "source_patch_road_keys": keys,
        "start_patch_road_keys": ",".join(assembly.start_patch_road_keys),
        "end_patch_road_keys": ",".join(assembly.end_patch_road_keys),
        "center_lane_id": ",".join(assembly.source_lane_ids),
        "source_lane_ids": ",".join(assembly.source_lane_ids),
        "lane_count": int(lane_counts.median()) if lane_counts.notna().any() else 0,
        "median_lane_width_m": float(lane_widths.median()) if lane_widths.notna().any() else None,
        "evidence_quality_state": (
            "surface_inferred_review"
            if surface_inferred
            else "usable"
            if quality == {"usable"}
            else "review"
        ),
        "observed_coverage_ratio": assembly.observed_coverage_ratio,
        "internal_completion_fraction": assembly.completion_fraction,
        "surface_inferred_fraction": 1.0 if surface_inferred else 0.0,
        "assembly_state": assembly.assembly_state,
        "evidence_spans_json": assembly.evidence_spans_json,
        "takeover_eligible": True,
        "reason_codes": (
            "member_missing_direction_surface_inferred"
            if surface_inferred
            else "segment_member_directional_corridor_assembled"
        ),
        "geometry": assembly.geometry,
    }


def _local_connector_carrier(
    row: object,
    segment_id: str,
    run_id: str,
    pair_count: int,
) -> dict[str, object]:
    record = row._asdict()
    key = str(row.patch_road_key)
    record.update(
        {
            "run_id": run_id,
            "segment_id": segment_id,
            "member_swsd_road_id": str(row.target_swsd_road_id),
            "carrier_id": f"built-local:{key}",
            "carrier_role": "local_connector",
            "direction_role": "local",
            "realization": "built",
            "geometry_source": "hp_observed",
            "source_object_type": "PATCH_LOCAL_CONNECTOR",
            "source_patch_ids": str(row.source_patch_id),
            "source_patch_road_keys": key,
            "start_patch_road_keys": key,
            "end_patch_road_keys": key,
            "source_lane_ids": canonical_id(getattr(row, "center_lane_id", "")),
            "observed_coverage_ratio": 1.0,
            "internal_completion_fraction": 0.0,
            "assembly_state": "local_connector_explicit_topology",
            "evidence_spans_json": json.dumps(
                [
                    {
                        "geometry_source": "hp_observed",
                        "source_object_ids": key,
                        "start_fraction": 0.0,
                        "end_fraction": 1.0,
                    }
                ],
                sort_keys=True,
            ),
            "reason_codes": f"local_connector_explicit_pair_count_{pair_count}",
        }
    )
    return record


def _retained_carrier(
    member: pd.Series,
    segment_id: str,
    member_id: str,
    run_id: str,
) -> dict[str, object]:
    return {
        **member.to_dict(),
        "run_id": run_id,
        "segment_id": segment_id,
        "member_swsd_road_id": member_id,
        "patch_road_key": "",
        "source_patch_road_keys": "",
        "start_patch_road_keys": "",
        "end_patch_road_keys": "",
        "carrier_id": f"retained:{member_id}",
        "carrier_role": "semantic_carrier",
        "realization": "retained",
        "geometry_source": "swsd_retained_whole",
        "source_object_type": "SWSD_ROAD_RETAINED",
        "observed_coverage_ratio": 0.0,
        "internal_completion_fraction": 0.0,
        "assembly_state": "retained_whole",
        "evidence_spans_json": "",
        "geometry": member.geometry,
    }


def _target_function_retained_carriers(
    segment: object,
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
    fragment_rows: list[dict[str, object]],
    run_id: str,
    forced_through_access_ids: set[str],
) -> list[dict[str, object]]:
    """Retain only the SWSD members needed for unrealized Segment functions."""
    built_roles = {
        str(row.get("carrier_role", ""))
        for row in fragment_rows
        if str(row.get("realization", "")) == "built"
    }
    endpoint_ids: set[str] = set()
    if (
        not str(getattr(segment, "sgrade", "") or "").endswith("双")
        and "main_oneway" in built_roles
    ):
        endpoint_ids = set(parse_id_list(getattr(segment, "pair_node_ids", "")))
    segment_id = str(segment.segment_id)
    access_prefix = f"{segment_id}:through:"
    forced_access_by_node: dict[str, set[str]] = {}
    for access_id in forced_through_access_ids:
        if not access_id.startswith(access_prefix):
            continue
        source_node_id = canonical_id(access_id.rsplit(":", maxsplit=1)[-1])
        if source_node_id:
            forced_access_by_node.setdefault(source_node_id, set()).add(access_id)
    rows_by_member: dict[str, dict[str, object]] = {}
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            continue
        member = road_by_id.loc[member_id]
        direction = int(member.get("direction", 1) or 1)
        member_endpoints = {
            canonical_id(member.get("snodeid")),
            canonical_id(member.get("enodeid")),
        }
        retain_endpoint_function = (
            direction in {0, 1}
            and bool(endpoint_ids.intersection(member_endpoints))
        )
        through_access_ids = sorted(
            {
                access_id
                for node_id in member_endpoints
                for access_id in forced_access_by_node.get(node_id, set())
            }
        )
        if not retain_endpoint_function and not through_access_ids:
            continue
        row = _retained_carrier(member, segment_id, member_id, run_id)
        reasons: list[str] = []
        if retain_endpoint_function:
            row["endpoint_function_retained"] = True
            reasons.append(
                "swsd_bidirectional_endpoint_function_not_realized_by_"
                "oneway_hp_main"
            )
        if through_access_ids:
            row["through_function_retained"] = True
            row["through_function_access_ids"] = ",".join(through_access_ids)
            reasons.append(
                "swsd_through_function_retained_after_hp_split_unresolved"
            )
        row["reason_codes"] = ",".join(reasons)
        rows_by_member[member_id] = row
    return list(rows_by_member.values())


def _retain_member_level_forced_through_functions(
    segment_id: str,
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
    existing_rows: list[dict[str, object]],
    run_id: str,
    forced_through_access_ids: set[str],
) -> tuple[list[dict[str, object]], set[str], int]:
    """Fallback only the local member Road needed by an unrealized THROUGH."""
    access_prefix = f"{segment_id}:through:"
    forced_access_by_node: dict[str, set[str]] = {}
    for access_id in forced_through_access_ids:
        if not access_id.startswith(access_prefix):
            continue
        source_node_id = canonical_id(access_id.rsplit(":", maxsplit=1)[-1])
        if source_node_id:
            forced_access_by_node.setdefault(source_node_id, set()).add(access_id)
    if not forced_access_by_node:
        return list(existing_rows), set(), 0

    member_endpoints: dict[str, set[str]] = {}
    member_lengths: dict[str, float] = {}
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            continue
        member = road_by_id.loc[member_id]
        member_endpoints[member_id] = {
            canonical_id(member.get("snodeid")),
            canonical_id(member.get("enodeid")),
        }
        geometry = _longest_line(member.geometry)
        member_lengths[member_id] = (
            float(geometry.length) if geometry is not None else math.inf
        )

    rows = [dict(row) for row in existing_rows]
    locally_retained_member_ids: set[str] = set()
    removed_source_count = 0
    for node_id, access_ids in sorted(forced_access_by_node.items()):
        candidates = sorted(
            (
                member_id
                for member_id, endpoints in member_endpoints.items()
                if node_id in endpoints
            ),
            key=lambda member_id: (member_lengths[member_id], member_id),
        )
        if not candidates:
            continue
        retained_candidates = {
            str(row.get("member_swsd_road_id", ""))
            for row in rows
            if str(row.get("realization", "")) == "retained"
        }
        built_candidates = {
            str(row.get("member_swsd_road_id", ""))
            for row in rows
            if str(row.get("realization", "")) == "built"
        }
        selected_member_id = next(
            (
                member_id
                for member_id in candidates
                if member_id in retained_candidates
            ),
            "",
        )
        if not selected_member_id:
            selected_member_id = next(
                (
                    member_id
                    for member_id in candidates
                    if member_id in built_candidates
                ),
                "",
            )
            if not selected_member_id:
                continue
            removed_rows = [
                row
                for row in rows
                if str(row.get("realization", "")) == "built"
                and str(row.get("member_swsd_road_id", ""))
                == selected_member_id
            ]
            removed_source_count += sum(
                len(str(row.get("source_patch_road_keys", "")).split(","))
                for row in removed_rows
            )
            rows = [
                row
                for row in rows
                if not (
                    str(row.get("realization", "")) == "built"
                    and str(row.get("member_swsd_road_id", ""))
                    == selected_member_id
                )
            ]
            member = road_by_id.loc[selected_member_id]
            rows.append(
                _retained_carrier(
                    member,
                    segment_id,
                    selected_member_id,
                    run_id,
                )
            )
            locally_retained_member_ids.add(selected_member_id)

        retained_row = next(
            row
            for row in rows
            if str(row.get("realization", "")) == "retained"
            and str(row.get("member_swsd_road_id", ""))
            == selected_member_id
        )
        current_access_ids = {
            value
            for value in str(
                retained_row.get("through_function_access_ids", "")
            ).split(",")
            if value
        }
        current_access_ids.update(access_ids)
        retained_row.update(
            {
                "through_function_retained": True,
                "through_function_access_ids": ",".join(
                    sorted(current_access_ids)
                ),
                "reason_codes": (
                    "swsd_through_function_retained_after_hp_split_unresolved"
                ),
            }
        )
    return rows, locally_retained_member_ids, removed_source_count


def _connector_pair_counts(explicit_pairs: pd.DataFrame | None) -> dict[str, int]:
    if explicit_pairs is None or explicit_pairs.empty:
        return {}
    counts: dict[str, set[tuple[str, str]]] = {}
    for row in explicit_pairs.itertuples():
        pair = (str(row.source_patch_road_key), str(row.target_patch_road_key))
        counts.setdefault(pair[0], set()).add(pair)
        counts.setdefault(pair[1], set()).add(pair)
    return {key: len(pairs) for key, pairs in counts.items()}


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _mandatory_main_roles_complete(
    rows: list[dict[str, object]],
    target_class: str,
    sgrade: str,
    *,
    required_member_roles: set[tuple[str, str]] | None = None,
) -> bool:
    if required_member_roles:
        built_member_roles = {
            (
                str(row.get("member_swsd_road_id", "")),
                str(row.get("carrier_role", "")),
            )
            for row in rows
            if str(row.get("realization", "")) == "built"
        }
        if not required_member_roles.issubset(built_member_roles):
            return False
    roles = {
        str(row.get("carrier_role", ""))
        for row in rows
        if str(row.get("realization", "")) == "built"
    }
    if target_class == "advance_right" or not sgrade.endswith("双"):
        return bool(roles.intersection({"main_oneway", "main_forward", "main_reverse"}))
    return {"main_forward", "main_reverse"}.issubset(roles)


def _target_access_support_carriers(
    segment_id: str,
    member_ids: tuple[str, ...],
    evidence: gpd.GeoDataFrame,
    existing_rows: list[dict[str, object]],
    required_access_surfaces: tuple[object, ...],
    reference: LineString | None,
    run_id: str,
    *,
    surface_max_distance_m: float,
    reserved_access_candidates: gpd.GeoDataFrame | None = None,
    reserved_access_segment_id: str = "",
    reserved_access_candidates_prebuffered: bool = False,
    forced_access_ids: set[str] | None = None,
    completion_surface: object | None = None,
    completion_min_coverage: float = 0.90,
) -> list[dict[str, object]]:
    if not required_access_surfaces or reference is None:
        return []
    surfaces = [
        (
            str(value[0]),
            value[1],
        )
        if isinstance(value, tuple) and len(value) == 2
        else (f"surface:{index}", value)
        for index, value in enumerate(required_access_surfaces)
    ]
    built_geometries = [
        row.get("geometry")
        for row in existing_rows
        if str(row.get("realization", "")) == "built"
        and row.get("geometry") is not None
    ]
    forced_access_ids = forced_access_ids or set()
    retained_access_ids = {
        access_id
        for row in existing_rows
        if str(row.get("realization", "")) == "retained"
        for access_id in str(
            row.get("through_function_access_ids", "")
        ).split(",")
        if access_id
    }
    uncovered = {
        index
        for index, (_, surface) in enumerate(surfaces)
        if (
            surfaces[index][0] in forced_access_ids
            and surfaces[index][0] not in retained_access_ids
        )
        or (
            surfaces[index][0] not in forced_access_ids
            and (
                not built_geometries
                or min(
                    float(geometry.distance(surface))
                    for geometry in built_geometries
                )
                > surface_max_distance_m
            )
        )
    }
    if not uncovered:
        return []
    candidates = evidence[
        evidence["assignment_source"].fillna("").eq("target_segment_fragment")
        & evidence["carrier_role"].eq("directional_corridor")
    ].copy()
    if candidates.empty:
        return []
    fragment_column = (
        "assignment_fragment_id"
        if "assignment_fragment_id" in candidates
        else "patch_road_key"
    )
    candidates = candidates.drop_duplicates(fragment_column, keep="first")
    selected: list[tuple[pd.Series, LineString, set[int]]] = []
    selected_ids: set[str] = set()
    while uncovered:
        choices: list[
            tuple[int, int, float, float, str, pd.Series, LineString, set[int]]
        ] = []
        for _, candidate in candidates.iterrows():
            fragment_id = str(candidate.get(fragment_column, ""))
            if fragment_id in selected_ids:
                continue
            geometry = _longest_line(candidate.geometry)
            if geometry is None or geometry.length <= 1e-6:
                continue
            overlap_fraction = max(
                (
                    float(geometry.intersection(main.buffer(1.0)).length)
                    / float(geometry.length)
                    for main in built_geometries
                ),
                default=0.0,
            )
            if overlap_fraction > 0.80:
                continue
            reservation_overlap = reservation_overlap_fraction(
                geometry,
                reserved_access_candidates,
                excluded_segment_id=reserved_access_segment_id,
                prebuffered=reserved_access_candidates_prebuffered,
                buffer_m=1.0,
            )
            if reservation_overlap > 0.80:
                continue
            coverage = {
                index
                for index in uncovered
                if float(geometry.distance(surfaces[index][1]))
                <= surface_max_distance_m
            }
            if not coverage:
                continue
            exact_count = sum(
                geometry.intersects(surfaces[index][1]) for index in coverage
            )
            maximum_distance = max(
                float(geometry.distance(surfaces[index][1])) for index in coverage
            )
            choices.append(
                (
                    len(coverage),
                    exact_count,
                    -maximum_distance,
                    float(geometry.length),
                    fragment_id,
                    candidate,
                    geometry,
                    coverage,
                )
            )
        if not choices:
            break
        _, _, _, _, fragment_id, candidate, geometry, coverage = max(
            choices,
            key=lambda value: value[:5],
        )
        selected.append((candidate, geometry, coverage))
        selected_ids.add(fragment_id)
        uncovered.difference_update(coverage)
    rows: list[dict[str, object]] = []
    for candidate, geometry, coverage in selected:
        direction_role = evidence_direction_role(geometry, reference)
        group = gpd.GeoDataFrame(
            [candidate.to_dict()],
            geometry="geometry",
            crs=evidence.crs,
        )
        row = _target_fragment_carrier(
            segment_id,
            member_ids,
            direction_role,
            "access_support",
            group,
            geometry,
            reference,
            run_id,
        )
        forced_targets = [
            surfaces[index]
            for index in coverage
            if surfaces[index][0] in forced_access_ids
        ]
        row = _complete_access_support_row(
            row,
            forced_targets,
            completion_surface,
            maximum_distance_m=surface_max_distance_m,
            minimum_surface_coverage=completion_min_coverage,
        )
        fragment_id = str(candidate.get(fragment_column, ""))
        row.update(
            {
                "carrier_id": f"target-access:{segment_id}:{fragment_id}",
                "source_object_type": "PATCH_TARGET_ACCESS_SUPPORT",
                "assembly_state": "target_segment_access_support_fragment",
                "reason_codes": "hard_required_through_access_support",
                "access_support_surface_count": len(coverage),
                "access_support_access_ids": ",".join(
                    sorted(surfaces[index][0] for index in coverage)
                ),
                "inherit_source_snodeid": not bool(forced_targets),
                "inherit_source_enodeid": not bool(forced_targets),
            }
        )
        rows.append(row)
    return rows


def _complete_access_support_row(
    row: dict[str, object],
    targets: list[tuple[str, object]],
    completion_surface: object | None,
    *,
    maximum_distance_m: float,
    minimum_surface_coverage: float,
) -> dict[str, object]:
    geometry = row["geometry"]
    start_completion = 0.0
    end_completion = 0.0
    completed_ids: list[str] = []
    for access_id, surface in targets:
        if geometry.intersects(surface):
            continue
        start = Point(geometry.coords[0])
        end = Point(geometry.coords[-1])
        endpoint, target = min(
            ((start, nearest_points(start, surface)[1]), (end, nearest_points(end, surface)[1])),
            key=lambda value: float(value[0].distance(value[1])),
        )
        distance = float(endpoint.distance(target))
        if distance <= 1e-6 or distance > maximum_distance_m:
            continue
        completion = LineString([endpoint, target])
        if completion_surface is None or completion.length <= 1e-6:
            continue
        if not _surface_coverage_at_least(
            completion,
            completion_surface,
            minimum_surface_coverage,
        ):
            continue
        coords = list(geometry.coords)
        if endpoint.equals(start):
            geometry = LineString([target.coords[0], *coords])
            start_completion += distance
        else:
            geometry = LineString([*coords, target.coords[0]])
            end_completion += distance
        if not geometry.is_valid or not geometry.is_simple:
            return row
        completed_ids.append(access_id)
    completion_length = start_completion + end_completion
    if completion_length <= 1e-6:
        return row
    total = float(geometry.length)
    observed_start = start_completion / total
    observed_end = 1.0 - end_completion / total
    spans: list[dict[str, object]] = []
    if start_completion > 0.0:
        spans.append(
            {
                "geometry_source": "hp_constrained_completion",
                "source_object_ids": ",".join(sorted(completed_ids)),
                "start_fraction": 0.0,
                "end_fraction": observed_start,
            }
        )
    spans.append(
        {
            "geometry_source": "hp_observed",
            "source_object_ids": str(row.get("source_patch_road_keys", "")),
            "start_fraction": observed_start,
            "end_fraction": observed_end,
        }
    )
    if end_completion > 0.0:
        spans.append(
            {
                "geometry_source": "hp_constrained_completion",
                "source_object_ids": ",".join(sorted(completed_ids)),
                "start_fraction": observed_end,
                "end_fraction": 1.0,
            }
        )
    row.update(
        {
            "geometry": geometry,
            "geometry_source": "hp_observed+hp_constrained_completion",
            "observed_coverage_ratio": 1.0 - completion_length / total,
            "internal_completion_fraction": completion_length / total,
            "evidence_quality_state": "constrained_completion_review",
            "assembly_state": (
                f"{row.get('assembly_state', '')}+access_constrained_completion"
            ),
            "evidence_spans_json": json.dumps(spans, sort_keys=True),
            "constrained_completion_access_ids": ",".join(sorted(completed_ids)),
        }
    )
    return row


def _target_fragment_carriers(
    segment: object,
    segment_evidence: gpd.GeoDataFrame,
    member_ids: tuple[str, ...],
    run_id: str,
    *,
    road_by_id: gpd.GeoDataFrame,
    drivezone_surface: object | None,
    minimum_member_coverage: float,
    sample_spacing_m: float,
    completion_min_coverage: float,
    explicit_pairs: pd.DataFrame | None,
    reference_geometry: LineString | None,
    required_surfaces: tuple[object, ...],
    surface_max_distance_m: float,
    maximum_main_angle_deg: float,
) -> list[dict[str, object]]:
    if segment_evidence.empty or "assignment_source" not in segment_evidence:
        return []
    evidence = segment_evidence[
        segment_evidence["assignment_source"]
        .fillna("")
        .isin(
            {
                "target_segment_fragment",
                "target_lane_fragment",
                "target_baseline_recovery_candidate",
                "target_access_surface_candidate",
            }
        )
        & segment_evidence["carrier_role"].eq("directional_corridor")
    ].copy()
    assignment_angles = pd.to_numeric(
        evidence.get(
            "assignment_angle_deg",
            pd.Series(math.nan, index=evidence.index),
        ),
        errors="coerce",
    )
    evidence = evidence[
        assignment_angles.isna()
        | assignment_angles.le(maximum_main_angle_deg + 1e-9)
    ].copy()
    if evidence.empty:
        return []
    reference = reference_geometry
    if reference is None:
        reference = _longest_line(segment.geometry)
    if reference is None:
        return []
    minimum_target_coverage = min(0.50, minimum_member_coverage)
    endpoint_completion_distance_m = max(
        surface_max_distance_m,
        float(reference.length) * (1.0 - minimum_target_coverage),
    )
    evidence["target_direction_role"] = evidence.geometry.map(
        lambda geometry: evidence_direction_role(geometry, reference)
    )
    dual = str(getattr(segment, "sgrade", "") or "").endswith("双")
    target_class = str(getattr(segment, "target_class", ""))
    required_oneway_role = (
        _swsd_oneway_direction_role(member_ids, road_by_id, reference)
        if target_class == "advance_right" or not dual
        else None
    )
    selected: list[
        tuple[str, str, gpd.GeoDataFrame, LineString, CorridorAssembly | None]
    ] = []
    for direction_role in ("forward", "reverse"):
        role_evidence = evidence[
            evidence["target_direction_role"].eq(direction_role)
        ].copy()
        group = role_evidence
        group = _select_directed_target_path(
            group,
            reference,
            explicit_pairs,
            required_surfaces=required_surfaces,
            surface_max_distance_m=surface_max_distance_m,
        )
        if required_surfaces and not _covers_required_surfaces(
            group,
            required_surfaces,
            maximum_distance_m=endpoint_completion_distance_m,
        ):
            continue
        geometry = _longest_observed_component(group)
        if geometry is not None:
            assembly = assemble_directional_corridor(
                group,
                reference,
                direction_role=direction_role,
                drivezone_surface=drivezone_surface,
                minimum_coverage=minimum_target_coverage,
                sample_spacing_m=sample_spacing_m,
                completion_min_coverage=completion_min_coverage,
            )
            if assembly is None and required_surfaces:
                surface_bridge = build_endpoint_surface_bridge_assembly(
                    role_evidence,
                    direction_role=direction_role,
                    required_surfaces=required_surfaces,
                    completion_surface=drivezone_surface,
                    maximum_distance_m=endpoint_completion_distance_m,
                    minimum_observed_fraction=minimum_target_coverage,
                    minimum_surface_coverage=completion_min_coverage,
                    assembly_completer=(
                        _complete_target_assembly_to_endpoint_surfaces
                    ),
                )
                if surface_bridge is not None:
                    group, assembly = surface_bridge
                    geometry = assembly.geometry
            if assembly is not None and required_surfaces:
                assembly = _complete_target_assembly_to_endpoint_surfaces(
                    assembly,
                    required_surfaces,
                    completion_surface=drivezone_surface,
                    maximum_distance_m=endpoint_completion_distance_m,
                    minimum_surface_coverage=completion_min_coverage,
                )
            if required_surfaces and (
                assembly is None
                or not _geometry_covers_required_surfaces(
                    assembly.geometry,
                    required_surfaces,
                    maximum_distance_m=endpoint_completion_distance_m,
                )
            ):
                continue
            selected.append((direction_role, "", group, geometry, assembly))
    if target_class == "advance_right" or not dual:
        if not selected:
            return []
        direction_role, _, group, geometry, assembly = max(
            selected,
            key=lambda item: (
                float(item[4].observed_coverage_ratio) if item[4] is not None else 0.0,
                float(item[3].length),
                item[0] == "forward",
            ),
        )
        if required_oneway_role is not None and direction_role != required_oneway_role:
            geometry = LineString(list(geometry.coords)[::-1])
            if assembly is not None:
                assembly = _reoriented_corridor_assembly(
                    assembly,
                    required_oneway_role,
                )
            direction_role = required_oneway_role
        selected = [(direction_role, "main_oneway", group, geometry, assembly)]
    else:
        by_role = {item[0]: item for item in selected}
        if (
            target_class == "core_trunk"
            and len(by_role) == 1
            and drivezone_surface is not None
        ):
            observed_role = next(iter(by_role))
            observed = by_role[observed_role]
            if observed[4] is not None:
                missing_role = "reverse" if observed_role == "forward" else "forward"
                inferred = _surface_inferred_counterpart(
                    observed[4],
                    observed[2],
                    reference,
                    drivezone_surface,
                    missing_role=missing_role,
                    completion_min_coverage=completion_min_coverage,
                )
                if (
                    inferred is not None
                    and required_surfaces
                    and "endpoint_surface_bridge_observed"
                    in observed[4].assembly_state
                ):
                    inferred = _complete_target_assembly_to_endpoint_surfaces(
                        inferred,
                        required_surfaces,
                        completion_surface=drivezone_surface,
                        maximum_distance_m=endpoint_completion_distance_m,
                        minimum_surface_coverage=completion_min_coverage,
                    )
                    if (
                        inferred is not None
                        and not _geometry_covers_required_surfaces(
                            inferred.geometry,
                            required_surfaces,
                            maximum_distance_m=0.0,
                        )
                    ):
                        inferred = None
                if inferred is not None:
                    selected.append(
                        (
                            missing_role,
                            "",
                            observed[2],
                            inferred.geometry,
                            inferred,
                        )
                    )
                    by_role[missing_role] = selected[-1]
        if not {"forward", "reverse"}.issubset(by_role):
            return []
        selected = [
            (
                "forward",
                "main_forward",
                by_role["forward"][2],
                by_role["forward"][3],
                by_role["forward"][4],
            ),
            (
                "reverse",
                "main_reverse",
                by_role["reverse"][2],
                by_role["reverse"][3],
                by_role["reverse"][4],
            ),
        ]
    return [
        (
            _target_corridor_carrier(
                str(segment.segment_id),
                member_ids,
                carrier_role,
                group,
                assembly,
                run_id,
            )
            if assembly is not None
            else _target_fragment_carrier(
                str(segment.segment_id),
                member_ids,
                direction_role,
                carrier_role,
                group,
                geometry,
                reference,
                run_id,
            )
        )
        for direction_role, carrier_role, group, geometry, assembly in selected
    ]


def _swsd_oneway_direction_role(
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
    reference: LineString,
) -> str | None:
    weighted_roles = {"forward": 0.0, "reverse": 0.0}
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            continue
        member = road_by_id.loc[member_id]
        direction = int(member.get("direction", 1) or 1)
        geometry = _longest_line(member.geometry)
        if direction not in {2, 3} or geometry is None:
            continue
        role = evidence_direction_role(geometry, reference)
        if direction == 3:
            role = "reverse" if role == "forward" else "forward"
        weighted_roles[role] += float(geometry.length)
    if weighted_roles["forward"] <= 1e-9 and weighted_roles["reverse"] <= 1e-9:
        return None
    if abs(weighted_roles["forward"] - weighted_roles["reverse"]) <= 1e-9:
        return None
    return max(weighted_roles, key=weighted_roles.get)


def _reoriented_corridor_assembly(
    assembly: CorridorAssembly,
    direction_role: str,
) -> CorridorAssembly:
    if assembly.direction_role == direction_role:
        return assembly
    spans: list[dict[str, object]] = []
    try:
        decoded = json.loads(assembly.evidence_spans_json)
    except (json.JSONDecodeError, TypeError):
        decoded = []
    if isinstance(decoded, list):
        for span in reversed(decoded):
            if not isinstance(span, dict):
                continue
            item = dict(span)
            old_start = float(item.get("start_fraction", 0.0))
            old_end = float(item.get("end_fraction", 1.0))
            item["start_fraction"] = 1.0 - old_end
            item["end_fraction"] = 1.0 - old_start
            spans.append(item)
    return CorridorAssembly(
        geometry=LineString(list(assembly.geometry.coords)[::-1]),
        direction_role=direction_role,
        observed_coverage_ratio=assembly.observed_coverage_ratio,
        completion_fraction=assembly.completion_fraction,
        source_patch_road_keys=assembly.source_patch_road_keys,
        start_patch_road_keys=assembly.end_patch_road_keys,
        end_patch_road_keys=assembly.start_patch_road_keys,
        source_patch_ids=assembly.source_patch_ids,
        source_lane_ids=assembly.source_lane_ids,
        evidence_spans_json=json.dumps(spans, sort_keys=True),
        assembly_state=f"{assembly.assembly_state}+swsd_direction_normalized",
    )


def _select_directed_target_path(
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    explicit_pairs: pd.DataFrame | None,
    *,
    required_surfaces: tuple[object, ...] = (),
    surface_max_distance_m: float = 20.0,
) -> gpd.GeoDataFrame:
    return _select_directed_target_path_cached(
        evidence,
        reference,
        explicit_pairs,
        required_surfaces=required_surfaces,
        surface_max_distance_m=surface_max_distance_m,
    )


def _covers_required_surfaces(
    evidence: gpd.GeoDataFrame,
    required_surfaces: tuple[object, ...],
    *,
    maximum_distance_m: float,
) -> bool:
    return not evidence.empty and all(
        float(evidence.geometry.distance(surface).min())
        <= maximum_distance_m + 1e-9
        for surface in required_surfaces
    )


def _geometry_covers_required_surfaces(
    geometry: LineString,
    required_surfaces: tuple[object, ...],
    *,
    maximum_distance_m: float,
) -> bool:
    if not required_surfaces:
        return True
    if len(required_surfaces) > 2:
        return False
    start = Point(geometry.coords[0])
    end = Point(geometry.coords[-1])
    if len(required_surfaces) == 1:
        return min(
            float(start.distance(required_surfaces[0])),
            float(end.distance(required_surfaces[0])),
        ) <= maximum_distance_m + 1e-9
    first, second = required_surfaces
    direct = (
        float(start.distance(first)) <= maximum_distance_m + 1e-9
        and float(end.distance(second)) <= maximum_distance_m + 1e-9
    )
    reverse = (
        float(start.distance(second)) <= maximum_distance_m + 1e-9
        and float(end.distance(first)) <= maximum_distance_m + 1e-9
    )
    return direct or reverse


def _complete_target_assembly_to_endpoint_surfaces(
    assembly: CorridorAssembly,
    required_surfaces: tuple[object, ...],
    *,
    completion_surface: object | None,
    maximum_distance_m: float,
    minimum_surface_coverage: float,
) -> CorridorAssembly | None:
    if not required_surfaces:
        return assembly
    if len(required_surfaces) > 2:
        return None
    geometry = assembly.geometry
    start = Point(geometry.coords[0])
    end = Point(geometry.coords[-1])
    if len(required_surfaces) == 1:
        assignments = [
            (
                "start" if start.distance(required_surfaces[0]) <= end.distance(required_surfaces[0]) else "end",
                required_surfaces[0],
            )
        ]
    else:
        first, second = required_surfaces
        direct_cost = float(start.distance(first) + end.distance(second))
        reverse_cost = float(start.distance(second) + end.distance(first))
        assignments = (
            [("start", first), ("end", second)]
            if direct_cost <= reverse_cost
            else [("start", second), ("end", first)]
        )
    start_path = None
    end_path = None
    start_completion = 0.0
    end_completion = 0.0
    routed_completion = False
    tangent_completion = False
    for endpoint_name, surface in assignments:
        endpoint = start if endpoint_name == "start" else end
        distance = float(endpoint.distance(surface))
        if distance <= 1e-9:
            continue
        if (
            distance > maximum_distance_m + 1e-9
            or completion_surface is None
        ):
            return None
        completion = route_tangent_endpoint_to_surface(
            geometry,
            endpoint_name,
            surface,
            completion_surface,
            maximum_distance_m=maximum_distance_m,
            minimum_coverage=minimum_surface_coverage,
        )
        tangent_completion = tangent_completion or completion is not None
        target = nearest_points(endpoint, surface)[1]
        if completion is None:
            completion = LineString([endpoint, target])
        if (
            completion.length <= 1e-9
            or not _surface_coverage_at_least(
                completion,
                completion_surface,
                minimum_surface_coverage,
                epsilon=1e-9,
            )
        ):
            completion = route_endpoint_to_surface(
                endpoint,
                surface,
                completion_surface,
                maximum_distance_m=maximum_distance_m,
                minimum_coverage=minimum_surface_coverage,
            )
            if completion is None:
                return None
            routed_completion = True
        if endpoint_name == "start":
            start_path = completion
            start_completion = float(completion.length)
        else:
            end_path = completion
            end_completion = float(completion.length)
    if start_completion <= 1e-9 and end_completion <= 1e-9:
        return assembly
    coords = list(geometry.coords)
    if start_path is not None:
        coords = list(start_path.coords)[::-1][:-1] + coords
    if end_path is not None:
        coords.extend(list(end_path.coords)[1:])
    completed = LineString(coords)
    if not completed.is_valid or not completed.is_simple:
        return None
    old_length = float(geometry.length)
    total_length = float(completed.length)
    spans = []
    if start_completion > 1e-9:
        spans.append(
            {
                "geometry_source": "hp_constrained_completion",
                "source_object_ids": "junction_endpoint_surface",
                "start_fraction": 0.0,
                "end_fraction": start_completion / total_length,
            }
        )
    try:
        original_spans = json.loads(assembly.evidence_spans_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        original_spans = []
    for span in original_spans:
        item = dict(span)
        item["start_fraction"] = (
            start_completion
            + float(span.get("start_fraction", 0.0)) * old_length
        ) / total_length
        item["end_fraction"] = (
            start_completion
            + float(span.get("end_fraction", 1.0)) * old_length
        ) / total_length
        spans.append(item)
    if end_completion > 1e-9:
        spans.append(
            {
                "geometry_source": "hp_constrained_completion",
                "source_object_ids": "junction_endpoint_surface",
                "start_fraction": 1.0 - end_completion / total_length,
                "end_fraction": 1.0,
            }
        )
    observed_length = assembly.observed_coverage_ratio * old_length
    existing_completion = assembly.completion_fraction * old_length
    added_completion = start_completion + end_completion
    return CorridorAssembly(
        geometry=completed,
        direction_role=assembly.direction_role,
        observed_coverage_ratio=observed_length / total_length,
        completion_fraction=(existing_completion + added_completion)
        / total_length,
        source_patch_road_keys=assembly.source_patch_road_keys,
        start_patch_road_keys=assembly.start_patch_road_keys,
        end_patch_road_keys=assembly.end_patch_road_keys,
        source_patch_ids=assembly.source_patch_ids,
        source_lane_ids=assembly.source_lane_ids,
        evidence_spans_json=json.dumps(spans, sort_keys=True),
        assembly_state=(
            f"{assembly.assembly_state}+endpoint_surface_constrained_"
            f"{'completion+tangent_surface_portal' if tangent_completion else 'routing' if routed_completion else 'completion'}"
        ),
    )


def _target_corridor_carrier(
    segment_id: str,
    member_ids: tuple[str, ...],
    carrier_role: str,
    evidence: gpd.GeoDataFrame,
    assembly: CorridorAssembly,
    run_id: str,
) -> dict[str, object]:
    member_id = next(
        (
            value
            for value in sorted(set(evidence["target_swsd_road_id"].astype(str)))
            if value
        ),
        member_ids[0] if member_ids else "",
    )
    row = _built_carrier(
        segment_id,
        member_id,
        evidence,
        assembly,
        run_id,
        member_direction=0 if carrier_role == "main_oneway" else 1,
    )
    row.update(
        {
            "carrier_id": f"target-corridor:{segment_id}:{carrier_role}",
            "carrier_role": carrier_role,
            "source_object_type": (
                "PATCH_LANE_TARGET_CORRIDOR"
                if set(evidence["assignment_source"].astype(str))
                == {"target_lane_fragment"}
                else "PATCH_TARGET_SEGMENT_CORRIDOR"
            ),
            "assembly_state": f"target_segment_{assembly.assembly_state}",
            "reason_codes": "target_segment_patch_corridor_assembled",
            "full_rcsd_anchor_supported": bool(
                evidence.get(
                    "full_rcsd_anchor_supported",
                    pd.Series(False, index=evidence.index),
                ).dropna().astype(bool).any()
            ),
            "full_rcsd_anchor_ids": ",".join(
                sorted(
                    {
                        value
                        for values in evidence.get(
                            "full_rcsd_anchor_ids",
                            pd.Series("", index=evidence.index),
                        ).astype(str)
                        for value in str(values).split(",")
                        if value and value.lower() != "nan"
                    }
                )
            ),
        }
    )
    if "surface_inferred_from_observed_direction" in assembly.assembly_state:
        row.update(
            {
                "geometry_source": "hp_constrained_completion",
                "surface_inferred_fraction": 1.0,
                "evidence_quality_state": "surface_inferred_review",
                "reason_codes": "target_missing_direction_surface_inferred",
            }
        )
    return row


def _surface_inferred_counterpart(
    observed: CorridorAssembly,
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    drivezone_surface: object,
    *,
    missing_role: str,
    completion_min_coverage: float,
) -> CorridorAssembly | None:
    lane_counts = _numeric_series(evidence, "lane_count")
    lane_widths = _numeric_series(evidence, "median_lane_width_m")
    lane_count = int(round(float(lane_counts.median()))) if lane_counts.notna().any() else 1
    lane_width = float(lane_widths.median()) if lane_widths.notna().any() else 3.5
    separation = max(3.5, lane_count * lane_width)
    candidates: list[tuple[float, float, int, LineString]] = []
    for side in (-1, 1):
        geometry = _longest_line(observed.geometry.offset_curve(side * separation))
        if geometry is None or geometry.is_empty or not geometry.is_valid or not geometry.is_simple:
            continue
        coverage = _surface_coverage(geometry, drivezone_surface)
        if coverage + 1e-9 < completion_min_coverage:
            continue
        if missing_role != observed.direction_role:
            geometry = LineString(list(geometry.coords)[::-1])
        sample_distances = sorted(
            float(geometry.interpolate(value, normalized=True).distance(reference))
            for value in (0.1, 0.3, 0.5, 0.7, 0.9)
        )
        median_reference_distance = sample_distances[len(sample_distances) // 2]
        candidates.append(
            (-coverage, median_reference_distance, side, geometry)
        )
    if not candidates:
        return None
    geometry = min(candidates, key=lambda item: item[:3])[3]
    source_keys = observed.source_patch_road_keys
    start_keys = observed.end_patch_road_keys
    end_keys = observed.start_patch_road_keys
    return CorridorAssembly(
        geometry=geometry,
        direction_role=missing_role,
        observed_coverage_ratio=observed.observed_coverage_ratio,
        completion_fraction=0.0,
        source_patch_road_keys=source_keys,
        start_patch_road_keys=start_keys,
        end_patch_road_keys=end_keys,
        source_patch_ids=observed.source_patch_ids,
        source_lane_ids=observed.source_lane_ids,
        evidence_spans_json=json.dumps(
            [
                {
                    "geometry_source": "hp_constrained_completion",
                    "source_object_ids": ",".join(source_keys),
                    "constraint_source": "road_surface_direction_offset",
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                }
            ],
            sort_keys=True,
        ),
        assembly_state=(
            "surface_inferred_from_observed_direction"
            + (
                "+endpoint_surface_bridge_counterpart"
                if "endpoint_surface_bridge_observed"
                in observed.assembly_state
                else ""
            )
        ),
    )


def _target_fragment_carrier(
    segment_id: str,
    member_ids: tuple[str, ...],
    direction_role: str,
    carrier_role: str,
    evidence: gpd.GeoDataFrame,
    geometry: LineString,
    reference: LineString,
    run_id: str,
) -> dict[str, object]:
    if evidence_direction_role(geometry, reference) != direction_role:
        geometry = LineString(list(geometry.coords)[::-1])
    selected = _component_evidence(evidence, geometry)
    if selected.empty:
        selected = evidence.copy()
    selected = selected.sort_values("patch_road_key", kind="stable")
    first = selected.iloc[0].to_dict()
    keys = tuple(sorted(set(selected["patch_road_key"].astype(str))))
    start_keys = _endpoint_patch_keys(selected, Point(geometry.coords[0]))
    end_keys = _endpoint_patch_keys(selected, Point(geometry.coords[-1]))
    patch_ids = tuple(sorted(set(selected["source_patch_id"].astype(str))))
    lane_ids = tuple(
        sorted(
            value
            for value in set(selected.get("center_lane_id", pd.Series(dtype=str)).astype(str))
            if value
        )
    )
    lane_counts = _numeric_series(selected, "lane_count")
    lane_widths = _numeric_series(selected, "median_lane_width_m")
    member_id = next(
        (
            value
            for value in sorted(set(selected["target_swsd_road_id"].astype(str)))
            if value
        ),
        member_ids[0] if member_ids else "",
    )
    return {
        **first,
        "road_id": "",
        "run_id": run_id,
        "segment_id": segment_id,
        "member_swsd_road_id": member_id,
        "carrier_id": f"target-fragment:{segment_id}:{carrier_role}",
        "carrier_role": carrier_role,
        "direction_role": direction_role,
        "realization": "built",
        "geometry_source": "hp_observed",
        "source_object_type": "PATCH_TARGET_SEGMENT_COMPONENT",
        "source_patch_id": ",".join(patch_ids),
        "source_patch_ids": ",".join(patch_ids),
        "patch_road_key": keys[0],
        "source_patch_road_keys": ",".join(keys),
        "start_patch_road_keys": ",".join(start_keys),
        "end_patch_road_keys": ",".join(end_keys),
        "center_lane_id": ",".join(lane_ids),
        "source_lane_ids": ",".join(lane_ids),
        "lane_count": int(lane_counts.median()) if lane_counts.notna().any() else 0,
        "median_lane_width_m": float(lane_widths.median())
        if lane_widths.notna().any()
        else None,
        "evidence_quality_state": "usable",
        "observed_coverage_ratio": 1.0,
        "internal_completion_fraction": 0.0,
        "assembly_state": "target_segment_patch_component",
        "evidence_spans_json": json.dumps(
            [
                {
                    "geometry_source": "hp_observed",
                    "source_object_ids": ",".join(keys),
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                }
            ],
            sort_keys=True,
        ),
        "takeover_eligible": True,
        "reason_codes": "target_segment_patch_component_selected",
        "geometry": geometry,
    }


def _component_evidence(
    evidence: gpd.GeoDataFrame,
    geometry: LineString,
) -> gpd.GeoDataFrame:
    overlap_lengths = evidence.geometry.map(
        lambda candidate: float(candidate.intersection(geometry).length)
    )
    minimum_overlap = evidence.geometry.length.map(
        lambda length: max(1e-6, min(float(length) * 0.5, 1.0))
    )
    return evidence[overlap_lengths >= minimum_overlap].copy()


def _endpoint_patch_keys(
    evidence: gpd.GeoDataFrame,
    endpoint: Point,
) -> tuple[str, ...]:
    distances = evidence.geometry.distance(endpoint)
    minimum = float(distances.min())
    return tuple(
        sorted(
            set(
                evidence.loc[distances <= minimum + 1e-6, "patch_road_key"].astype(str)
            )
        )
    )


def _longest_observed_component(
    evidence: gpd.GeoDataFrame,
) -> LineString | None:
    if evidence.empty:
        return None
    merged = unary_union(list(evidence.geometry))
    if merged.geom_type == "LineString":
        return merged
    if merged.geom_type == "MultiLineString":
        merged = linemerge(merged)
    return _longest_line(merged)


def _orient_like(geometry: LineString, reference: LineString) -> LineString:
    same = geometry.coords[0]
    reverse = geometry.coords[-1]
    reference_start = reference.coords[0]
    same_distance = (same[0] - reference_start[0]) ** 2 + (same[1] - reference_start[1]) ** 2
    reverse_distance = (reverse[0] - reference_start[0]) ** 2 + (reverse[1] - reference_start[1]) ** 2
    return (
        geometry
        if same_distance <= reverse_distance
        else LineString(list(geometry.coords)[::-1])
    )


__all__ = ["CarrierPlanResult", "plan_segment_carriers"]
