from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import nearest_points, substring, unary_union

from .segment_first_junctions import endpoint_surface_geometry
from .segment_first_skeleton import parse_id_list
from .segment_first_surface_routing import interior_surface_target


def build_required_endpoint_surfaces(
    segment_accesses: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    *,
    endpoint_inset_m: float,
) -> gpd.GeoDataFrame:
    if segment_accesses.empty or junction_units.empty:
        return junction_units.iloc[0:0].copy()
    accepted = junction_units[
        junction_units["junction_source"].isin(
            {"t07_accepted", "t03_accepted", "t04_accepted"}
        )
    ]
    surfaces = {
        str(group_id): interior_surface_target(
            unary_union(
                [
                    endpoint_surface_geometry(row)
                    for row in group.itertuples(index=False)
                ]
            ),
            inset_m=endpoint_inset_m,
        )
        for group_id, group in accepted.groupby("junction_group_id")
    }
    rows: list[dict[str, object]] = []
    selected = segment_accesses[segment_accesses["access_type"].eq("ENDPOINT")]
    for access in selected.itertuples(index=False):
        surface = surfaces.get(str(access.junction_group_id))
        if surface is None or surface.is_empty:
            continue
        rows.append(
            {
                "segment_id": str(access.segment_id),
                "access_id": str(access.access_id),
                "junction_group_id": str(access.junction_group_id),
                "geometry": surface,
            }
        )
    if not rows:
        return junction_units.iloc[0:0].copy()
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=junction_units.crs)


def build_required_through_surfaces(
    segment_accesses: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    *,
    endpoint_inset_m: float,
) -> gpd.GeoDataFrame:
    if segment_accesses.empty or junction_units.empty:
        return junction_units.iloc[0:0].copy()
    surfaces = {
        str(group_id): interior_surface_target(
            unary_union(
                [
                    endpoint_surface_geometry(row)
                    for row in group.itertuples(index=False)
                ]
            ),
            inset_m=endpoint_inset_m,
        )
        for group_id, group in junction_units.groupby("junction_group_id")
    }
    rows: list[dict[str, object]] = []
    selected = segment_accesses[segment_accesses["access_type"].eq("THROUGH")]
    for access in selected.itertuples(index=False):
        surface = surfaces.get(str(access.junction_group_id))
        if surface is None or surface.is_empty:
            continue
        rows.append(
            {
                "segment_id": str(access.segment_id),
                "access_id": str(access.access_id),
                "junction_group_id": str(access.junction_group_id),
                "geometry": surface,
            }
        )
    if not rows:
        return junction_units.iloc[0:0].copy()
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=junction_units.crs)


def build_access_surface_recovery_candidates(
    target_segments: gpd.GeoDataFrame,
    patch_road_centers: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    *,
    run_id: str,
    maximum_surface_distance_m: float,
    minimum_drivezone_coverage: float,
    minimum_length_m: float = 4.0,
) -> gpd.GeoDataFrame:
    if (
        target_segments.empty
        or patch_road_centers.empty
        or segment_accesses.empty
        or junction_units.empty
    ):
        return patch_road_centers.iloc[0:0].copy()
    required = target_segments[
        target_segments["target_required"].fillna(False).astype(bool)
        & target_segments["target_class"].eq("core_trunk")
    ].copy()
    endpoint_accesses = segment_accesses[
        segment_accesses["access_type"].eq("ENDPOINT")
    ].copy()
    surfaces = {
        str(group_id): unary_union(
            [
                endpoint_surface_geometry(row)
                for row in group.itertuples(index=False)
            ]
        )
        for group_id, group in junction_units.groupby("junction_group_id")
    }
    drivezone_surface = (
        drivezones.geometry.union_all().buffer(1.0)
        if not drivezones.empty
        else None
    )
    rows: list[dict[str, object]] = []
    for segment in required.itertuples(index=False):
        accesses = endpoint_accesses[
            endpoint_accesses["segment_id"].astype(str).eq(str(segment.segment_id))
        ].sort_values("access_ordinal", kind="stable")
        if len(accesses) != 2:
            continue
        endpoint_surfaces = [
            surfaces.get(str(access.junction_group_id))
            for access in accesses.itertuples(index=False)
        ]
        if any(surface is None or surface.is_empty for surface in endpoint_surfaces):
            continue
        search_surface = gpd.GeoSeries(
            endpoint_surfaces,
            crs=patch_road_centers.crs,
        ).union_all()
        candidates = patch_road_centers[
            patch_road_centers.geometry.distance(search_surface)
            <= maximum_surface_distance_m
        ]
        member_ids = parse_id_list(segment.swsd_road_ids)
        member_id = member_ids[0] if member_ids else ""
        for center in candidates.itertuples(index=False):
            distances = [
                float(center.geometry.distance(surface))
                for surface in endpoint_surfaces
            ]
            if max(distances) > maximum_surface_distance_m:
                continue
            clipped = _clip_between_surfaces(center.geometry, endpoint_surfaces)
            if clipped is None or clipped.length < minimum_length_m:
                continue
            coverage = (
                float(clipped.intersection(drivezone_surface).length / clipped.length)
                if drivezone_surface is not None
                else 0.0
            )
            if coverage + 1e-9 < minimum_drivezone_coverage:
                continue
            row = center._asdict()
            row.update(
                {
                    "run_id": run_id,
                    "assigned_segment_id": str(segment.segment_id),
                    "target_swsd_road_id": member_id,
                    "assignment_fragment_id": (
                        f"{center.patch_road_key}@{segment.segment_id}@access-surface"
                    ),
                    "assignment_distance_m": max(distances),
                    "assignment_angle_deg": 0.0,
                    "assignment_score": max(distances),
                    "assignment_margin": None,
                    "carrier_role": "directional_corridor",
                    "takeover_eligible": False,
                    "assignment_state": "access_surface_recovery_candidate",
                    "assignment_source": "target_access_surface_candidate",
                    "target_anchor_source": "junction_unit_endpoint_surfaces",
                    "reason_codes": "patch_road_connects_both_segment_endpoint_surfaces",
                    "access_surface_coverage": coverage,
                    "geometry": clipped,
                }
            )
            rows.append(row)
    if not rows:
        return patch_road_centers.iloc[0:0].copy()
    result = gpd.GeoDataFrame(
        rows,
        geometry="geometry",
        crs=patch_road_centers.crs,
    )
    return result.sort_values(
        ["assigned_segment_id", "patch_road_key"],
        kind="stable",
    ).reset_index(drop=True)


def annotate_recovery_carrier_conflicts(
    candidates: gpd.GeoDataFrame,
    base_carriers: gpd.GeoDataFrame,
    *,
    ignored_segment_ids: set[str] | None = None,
    overlap_tolerance_m: float = 0.20,
    maximum_endpoint_overlap_m: float = 5.0,
    maximum_overlap_fraction: float = 0.20,
) -> gpd.GeoDataFrame:
    result = candidates.copy()
    ignored_segments = ignored_segment_ids or set()
    if "reason_codes" in result:
        result["reason_codes"] = (
            result["reason_codes"]
            .fillna("")
            .astype(str)
            .str.replace(
                ";published_carrier_source_overlap",
                "",
                regex=False,
            )
            .str.replace(
                ";recovery_conflict_released_after_segment_fallback",
                "",
                regex=False,
            )
        )
    if "assignment_state" in result:
        result["assignment_state"] = "access_surface_recovery_candidate"
    previous_released_conflicts = [
        {
            segment_id
            for segment_id in str(value or "").split(",")
            if segment_id in ignored_segments
        }
        for value in result.get(
            "recovery_released_conflict_segment_ids",
            pd.Series("", index=result.index),
        )
    ]
    if result.empty:
        result["recovery_eligible"] = False
        result["recovery_overlap_length_m"] = 0.0
        result["recovery_conflict_segment_ids"] = ""
        result["recovery_released_conflict_segment_ids"] = ""
        return result
    built = base_carriers[
        base_carriers.get("realization", "").astype(str).eq("built")
    ].copy()
    carriers_by_source: dict[str, list[object]] = {}
    for carrier in built.itertuples(index=False):
        for source_key in _source_keys(
            getattr(carrier, "source_patch_road_keys", "")
        ):
            carriers_by_source.setdefault(source_key, []).append(carrier)
    eligible: list[bool] = []
    overlap_lengths: list[float] = []
    conflict_segments: list[str] = []
    released_conflict_segments: list[str] = []
    for candidate, previous_released in zip(
        result.itertuples(index=False),
        previous_released_conflicts,
    ):
        candidate_segment = str(candidate.assigned_segment_id)
        geometry = candidate.geometry
        maximum_overlap = 0.0
        conflicts: set[str] = set()
        released_conflicts = set(previous_released)
        allowed_overlap = min(
            maximum_endpoint_overlap_m,
            maximum_overlap_fraction * float(geometry.length),
        )
        for carrier in carriers_by_source.get(str(candidate.patch_road_key), []):
            carrier_segment = str(getattr(carrier, "segment_id", ""))
            if carrier_segment == candidate_segment:
                continue
            overlap = float(
                geometry.intersection(
                    carrier.geometry.buffer(overlap_tolerance_m)
                ).length
            )
            maximum_overlap = max(maximum_overlap, overlap)
            if overlap > allowed_overlap + 1e-9:
                if carrier_segment in ignored_segments:
                    released_conflicts.add(carrier_segment)
                else:
                    conflicts.add(carrier_segment)
        eligible.append(not conflicts)
        overlap_lengths.append(maximum_overlap)
        conflict_segments.append(",".join(sorted(conflicts)))
        released_conflict_segments.append(",".join(sorted(released_conflicts)))
    result["recovery_eligible"] = eligible
    result["recovery_overlap_length_m"] = overlap_lengths
    result["recovery_conflict_segment_ids"] = conflict_segments
    result["recovery_released_conflict_segment_ids"] = (
        released_conflict_segments
    )
    conflict_mask = ~result["recovery_eligible"]
    result.loc[conflict_mask, "assignment_state"] = (
        "access_surface_recovery_conflict"
    )
    result.loc[conflict_mask, "reason_codes"] = result.loc[
        conflict_mask, "reason_codes"
    ].astype(str) + ";published_carrier_source_overlap"
    released_mask = (
        result["recovery_eligible"]
        & result["recovery_released_conflict_segment_ids"].ne("")
    )
    result.loc[released_mask, "reason_codes"] = result.loc[
        released_mask, "reason_codes"
    ].astype(str) + ";recovery_conflict_released_after_segment_fallback"
    return result


def recoordinate_access_recovery_assignments(
    candidates: gpd.GeoDataFrame,
    base_assignments: gpd.GeoDataFrame,
    current_carriers: gpd.GeoDataFrame,
    *,
    forced_retained_segment_ids: set[str],
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, frozenset[str]]:
    """Release only recovery conflicts owned by already-retained Segments."""

    if candidates.empty:
        return candidates.copy(), base_assignments.copy(), frozenset()
    fragment_column = (
        "assignment_fragment_id"
        if "assignment_fragment_id" in candidates
        else "patch_road_key"
    )
    previously_eligible = set(
        candidates.loc[
            candidates.get(
                "recovery_eligible",
                pd.Series(False, index=candidates.index),
            )
            .fillna(False)
            .astype(bool),
            fragment_column,
        ].astype(str)
    )
    coordinated = annotate_recovery_carrier_conflicts(
        candidates,
        current_carriers,
        ignored_segment_ids=forced_retained_segment_ids,
    )
    eligible = coordinated[
        coordinated["recovery_eligible"].fillna(False).astype(bool)
    ].copy()
    planning_assignments = gpd.GeoDataFrame(
        pd.concat(
            [base_assignments, eligible],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=base_assignments.crs,
    )
    newly_eligible = frozenset(
        set(eligible[fragment_column].astype(str)) - previously_eligible
    )
    return coordinated, planning_assignments, newly_eligible


def _clip_between_surfaces(
    geometry: LineString,
    surfaces: list[object],
) -> LineString | None:
    measures: list[float] = []
    for surface in surfaces:
        support = surface.buffer(1.0)
        intersection = geometry.intersection(support)
        if not intersection.is_empty:
            point = intersection.centroid
            measure = float(geometry.project(point))
        else:
            point, _ = nearest_points(geometry, support)
            measure = float(geometry.project(point))
        measures.append(measure)
    start, end = sorted(measures)
    if end - start <= 1e-6:
        return None
    clipped = substring(geometry, start, end)
    return clipped if isinstance(clipped, LineString) else None


def _source_keys(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


__all__ = [
    "annotate_recovery_carrier_conflicts",
    "build_access_surface_recovery_candidates",
    "build_required_endpoint_surfaces",
    "build_required_through_surfaces",
    "recoordinate_access_recovery_assignments",
]
