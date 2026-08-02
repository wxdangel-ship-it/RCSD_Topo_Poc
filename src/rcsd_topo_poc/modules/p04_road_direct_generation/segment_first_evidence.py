from __future__ import annotations

from dataclasses import dataclass
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from .segment_first_config import SegmentFirstConfig
from .segment_first_skeleton import canonical_id, parse_id_list
from .segment_first_target_assignment import apply_target_segment_anchors
from .segment_first_target_fragments import build_target_carrier_fragments


@dataclass(frozen=True)
class SegmentEvidenceResult:
    patch_road_centers: gpd.GeoDataFrame
    geometry_sources: gpd.GeoDataFrame
    road_lane_relations: gpd.GeoDataFrame
    assignments: gpd.GeoDataFrame
    carrier_assignments: gpd.GeoDataFrame
    rejections: gpd.GeoDataFrame
    lane_topo_audit: gpd.GeoDataFrame
    explicit_road_pairs: pd.DataFrame
    target_anchor_audit: gpd.GeoDataFrame
    target_fragment_audit: gpd.GeoDataFrame
    summary: dict[str, object]


def _ensure_assignment_source(
    frame: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Keep the internal assignment-source contract stable across empty branches."""

    result = frame.copy()
    if "assignment_source" not in result:
        result["assignment_source"] = pd.Series(
            "member_assignment",
            index=result.index,
            dtype="object",
        )
    else:
        result["assignment_source"] = result["assignment_source"].fillna(
            "member_assignment"
        )
    return result


def build_segment_evidence(
    patch_roads: gpd.GeoDataFrame,
    patch_lanes: gpd.GeoDataFrame,
    patch_lane_topo: gpd.GeoDataFrame,
    patch_road_next_road: gpd.GeoDataFrame,
    scoped_swsd_roads: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    target_anchors: gpd.GeoDataFrame | None = None,
    target_segments: gpd.GeoDataFrame | None = None,
    full_rcsd_roads: gpd.GeoDataFrame | None = None,
) -> SegmentEvidenceResult:
    centers, relations = build_patch_road_centers(
        patch_roads, patch_lanes, run_id=config.run_id
    )
    centers = orient_patch_road_centers(centers, patch_road_next_road)
    assignments, rejections = assign_patch_roads_to_segments(
        centers,
        scoped_swsd_roads,
        max_distance_m=config.assignment_max_distance_m,
        max_angle_deg=config.assignment_max_angle_deg,
        run_id=config.run_id,
    )
    target_assignment = apply_target_segment_anchors(
        centers,
        assignments,
        rejections,
        scoped_swsd_roads,
        (
            target_anchors
            if target_anchors is not None
            else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
        ),
        max_distance_m=config.assignment_max_distance_m,
        max_angle_deg=config.assignment_max_angle_deg,
        run_id=config.run_id,
        protected_segment_ids=(
            set(
                target_segments.loc[
                    target_segments["target_required"].fillna(False).astype(bool),
                    "segment_id",
                ].astype(str)
            )
            if target_segments is not None and not target_segments.empty
            else set()
        ),
    )
    assignments = _ensure_assignment_source(target_assignment.assignments)
    rejections = target_assignment.rejections
    lane_centers = _target_lane_centers(patch_lanes, config.run_id)
    geometry_sources = gpd.GeoDataFrame(
        pd.concat([centers, lane_centers], ignore_index=True, sort=False),
        geometry="geometry",
        crs=centers.crs,
    )
    full_rcsd_support = _full_rcsd_patch_anchor_support(
        centers,
        (
            full_rcsd_roads
            if full_rcsd_roads is not None
            else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
        ),
        (
            target_segments
            if target_segments is not None
            else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
        ),
        max_distance_m=config.full_rcsd_anchor_max_distance_m,
        max_angle_deg=config.full_rcsd_anchor_max_angle_deg,
    )
    if target_segments is not None and not target_segments.empty:
        target_fragments = build_target_carrier_fragments(
            centers,
            assignments,
            target_segments,
            (
                target_anchors
                if target_anchors is not None
                else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
            ),
            scoped_swsd_roads,
            sample_spacing_m=config.smoothing_sample_spacing_m,
            max_distance_m=config.assignment_max_distance_m,
            max_angle_deg=config.assignment_max_angle_deg,
            run_id=config.run_id,
        )
        carrier_assignments = _mark_full_rcsd_support(
            target_fragments.assignments.copy(), full_rcsd_support
        )
        target_fragment_audit = _mark_full_rcsd_support(
            target_fragments.audit.copy(), full_rcsd_support
        )
        target_fragment_summary = target_fragments.summary
        lane_baseline = lane_centers.iloc[0:0].copy()
        for column in (
            "assigned_segment_id",
            "target_swsd_road_id",
            "carrier_role",
            "takeover_eligible",
        ):
            lane_baseline[column] = pd.Series(dtype="object")
        target_lane_fragments = build_target_carrier_fragments(
            lane_centers,
            lane_baseline,
            target_segments,
            (
                target_anchors
                if target_anchors is not None
                else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
            ),
            scoped_swsd_roads,
            sample_spacing_m=config.smoothing_sample_spacing_m,
            max_distance_m=config.lane_recovery_max_distance_m,
            max_angle_deg=config.lane_recovery_max_angle_deg,
            run_id=config.run_id,
        )
        lane_fragment_audit = target_lane_fragments.audit.copy()
        if not lane_fragment_audit.empty:
            lane_fragment_audit["assignment_source"] = "target_lane_fragment"
            lane_fragment_audit["assignment_state"] = "target_lane_fragmented"
            lane_fragment_audit["reason_codes"] = (
                "lane_geometry_partitioned_by_target_segment"
            )
            lane_fragment_audit["full_rcsd_anchor_supported"] = False
            lane_fragment_audit["full_rcsd_anchor_ids"] = ""
            carrier_assignments = gpd.GeoDataFrame(
                pd.concat(
                    [carrier_assignments, lane_fragment_audit],
                    ignore_index=True,
                    sort=False,
                ),
                geometry="geometry",
                crs=centers.crs,
            )
            target_fragment_audit = gpd.GeoDataFrame(
                pd.concat(
                    [target_fragment_audit, lane_fragment_audit],
                    ignore_index=True,
                    sort=False,
                ),
                geometry="geometry",
                crs=centers.crs,
            )
        target_fragment_summary["target_lane_fragments"] = (
            target_lane_fragments.summary
        )
        target_fragment_summary["full_rcsd_patch_anchor_pair_count"] = int(
            len(full_rcsd_support)
        )
        target_fragment_summary["full_rcsd_anchored_segment_count"] = int(
            len({segment_id for segment_id, _ in full_rcsd_support})
        )
    else:
        carrier_assignments = assignments
        target_fragment_audit = target_assignment.audit.iloc[0:0].copy()
        target_fragment_summary = {
            "fragmentation_enabled": False,
            "fragment_count": 0,
            "fragmented_patch_road_count": 0,
            "covered_target_segment_count": 0,
            "multi_target_patch_road_count": 0,
        }
    lane_topo_audit = _lane_topo_audit(patch_lane_topo, relations, config.run_id)
    explicit_pairs = _explicit_road_pairs(
        patch_road_next_road,
        carrier_assignments,
        lane_topo_audit,
    )
    recovery_candidates = _target_baseline_recovery_candidates(
        assignments,
        (
            target_segments
            if target_segments is not None
            else gpd.GeoDataFrame(geometry=[], crs=centers.crs)
        ),
    )
    if not recovery_candidates.empty:
        carrier_assignments = gpd.GeoDataFrame(
            pd.concat(
                [carrier_assignments, recovery_candidates],
                ignore_index=True,
                sort=False,
            ),
            geometry="geometry",
            crs=centers.crs,
        )
        target_fragment_audit = gpd.GeoDataFrame(
            pd.concat(
                [target_fragment_audit, recovery_candidates],
                ignore_index=True,
                sort=False,
            ),
            geometry="geometry",
            crs=centers.crs,
        )
        target_fragment_summary["baseline_recovery_candidate_count"] = int(
            len(recovery_candidates)
        )
    carrier_assignments = _ensure_assignment_source(carrier_assignments)
    target_fragment_audit = _ensure_assignment_source(target_fragment_audit)
    summary = {
        "patch_road_count": int(len(centers)),
        "assigned_patch_road_count": int(len(assignments)),
        "rejected_patch_road_count": int(len(rejections)),
        "central_lane_not_leftmost_count": int(
            assignments.get("center_lane_is_leftmost", pd.Series(dtype=bool)).eq(False).sum()
        ),
        "lane_topo_count": int(len(lane_topo_audit)),
        "explicit_patch_road_pair_count": int(len(explicit_pairs)),
        "target_anchor_assignment": target_assignment.summary,
        "target_carrier_fragments": target_fragment_summary,
    }
    return SegmentEvidenceResult(
        centers,
        geometry_sources,
        relations,
        assignments,
        carrier_assignments,
        rejections,
        lane_topo_audit,
        explicit_pairs,
        target_assignment.audit,
        target_fragment_audit,
        summary,
    )


def _target_baseline_recovery_candidates(
    assignments: gpd.GeoDataFrame,
    target_segments: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if assignments.empty or target_segments.empty:
        return assignments.iloc[0:0].copy()
    recoverable_ids = set(
        target_segments.loc[
            target_segments["target_required"].fillna(False).astype(bool)
            & target_segments["target_class"].eq("core_trunk")
            & target_segments["sgrade"].fillna("").astype(str).str.endswith("双"),
            "segment_id",
        ].astype(str)
    )
    result = assignments[
        assignments["assigned_segment_id"].astype(str).isin(recoverable_ids)
        & assignments["carrier_role"].eq("directional_corridor")
    ].copy()
    if result.empty:
        return result
    result["takeover_eligible"] = False
    result["assignment_source"] = "target_baseline_recovery_candidate"
    result["assignment_state"] = "recovery_candidate"
    result["reason_codes"] = "complete_baseline_reserved_for_missing_role_recovery"
    if "full_rcsd_anchor_supported" not in result:
        result["full_rcsd_anchor_supported"] = False
    if "full_rcsd_anchor_ids" not in result:
        result["full_rcsd_anchor_ids"] = ""
    return result.reset_index(drop=True)


def _target_lane_centers(
    lanes: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    frame = lanes[
        lanes.geometry.notna()
        & ~lanes.geometry.is_empty
        & lanes.geometry.geom_type.eq("LineString")
    ].copy()
    frame["lane_id"] = frame["Id"].map(canonical_id)
    frame["road_id"] = frame.get("RoadId", pd.Series(index=frame.index)).map(
        canonical_id
    )
    frame["patch_road_key"] = frame.apply(
        lambda row: f"{row['source_patch_id']}:lane:{row['lane_id']}", axis=1
    )
    frame["run_id"] = run_id
    frame["source_patch_ids"] = frame["source_patch_id"].astype(str)
    frame["center_lane_id"] = frame["lane_id"]
    frame["center_lane_is_leftmost"] = frame.get(
        "IsLeftmost", pd.Series(False, index=frame.index)
    ).fillna(False).astype(bool)
    frame["centerline_method"] = "lane_centerline_direct_evidence"
    frame["center_offset_m"] = 0.0
    frame["center_lane_span_ratio"] = 1.0
    frame["lane_count"] = 1
    frame["median_lane_width_m"] = pd.to_numeric(
        frame.get("Width", pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )
    frame["evidence_quality_state"] = "usable"
    frame["orientation_state"] = "lane_native_direction"
    frame["orientation_score_margin_m"] = math.nan
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=lanes.crs)


def _full_rcsd_patch_anchor_support(
    centers: gpd.GeoDataFrame,
    full_rcsd_roads: gpd.GeoDataFrame,
    target_segments: gpd.GeoDataFrame,
    *,
    max_distance_m: float,
    max_angle_deg: float,
) -> dict[tuple[str, str], tuple[str, ...]]:
    if centers.empty or full_rcsd_roads.empty or target_segments.empty:
        return {}
    full = full_rcsd_roads[
        full_rcsd_roads.geometry.notna()
        & ~full_rcsd_roads.geometry.is_empty
        & full_rcsd_roads.geometry.geom_type.eq("LineString")
    ].copy()
    full["canonical_road_id"] = full["id"].map(canonical_id)
    full_by_id = {
        road_id: group.iloc[0]
        for road_id, group in full.groupby("canonical_road_id", sort=True)
    }
    center_index = centers.sindex
    support: dict[tuple[str, str], set[str]] = {}
    for segment in target_segments.itertuples(index=False):
        if not bool(getattr(segment, "target_required", False)):
            continue
        segment_id = canonical_id(segment.segment_id)
        for road_id in parse_id_list(getattr(segment, "t06_rcsd_road_ids", "")):
            road = full_by_id.get(road_id)
            if road is None:
                continue
            indexes = list(center_index.query(road.geometry.buffer(max_distance_m)))
            candidates: list[tuple[float, float, float, str]] = []
            for index in indexes:
                center = centers.iloc[index]
                distance = _sample_distance(road.geometry, center.geometry)
                angle = _line_angle_delta(road.geometry, center.geometry)
                if distance > max_distance_m or angle > max_angle_deg:
                    continue
                candidates.append(
                    (
                        distance + angle * 0.08,
                        distance,
                        angle,
                        str(center.patch_road_key),
                    )
                )
            if candidates:
                patch_key = min(candidates)[3]
                support.setdefault((segment_id, patch_key), set()).add(road_id)
    return {
        key: tuple(sorted(road_ids)) for key, road_ids in support.items()
    }


def _mark_full_rcsd_support(
    frame: gpd.GeoDataFrame,
    support: dict[tuple[str, str], tuple[str, ...]],
) -> gpd.GeoDataFrame:
    if frame.empty:
        frame["full_rcsd_anchor_supported"] = pd.Series(dtype=bool)
        frame["full_rcsd_anchor_ids"] = pd.Series(dtype=str)
        return frame
    anchor_ids = frame.apply(
        lambda row: support.get(
            (
                canonical_id(row.get("assigned_segment_id")),
                str(row.get("patch_road_key", "")),
            ),
            (),
        ),
        axis=1,
    )
    frame["full_rcsd_anchor_supported"] = anchor_ids.map(bool)
    frame["full_rcsd_anchor_ids"] = anchor_ids.map(lambda values: ",".join(values))
    return frame


def build_patch_road_centers(
    roads: gpd.GeoDataFrame,
    lanes: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    lane_frame = lanes.copy()
    lane_frame["lane_id"] = lane_frame["Id"].map(canonical_id)
    lane_frame["road_id"] = lane_frame["RoadId"].map(canonical_id)
    lane_frame["patch_road_key"] = lane_frame.apply(
        lambda row: f"{row['source_patch_id']}:{row['road_id']}", axis=1
    )
    road_frame = roads.copy()
    road_frame["road_id"] = road_frame["Id"].map(canonical_id)
    road_frame["patch_road_key"] = road_frame.apply(
        lambda row: f"{row['source_patch_id']}:{row['road_id']}", axis=1
    )
    lane_groups = {key: group for key, group in lane_frame.groupby("patch_road_key")}
    center_rows: list[dict[str, object]] = []
    relation_rows: list[dict[str, object]] = []
    for road in road_frame.itertuples():
        group = lane_groups.get(road.patch_road_key)
        if group is None or group.empty:
            center_rows.append(
                {
                    **road._asdict(),
                    "run_id": run_id,
                    "center_lane_id": "",
                    "center_lane_is_leftmost": None,
                    "lane_count": 0,
                    "evidence_quality_state": "patch_road_without_lane",
                    "geometry": road.geometry,
                }
            )
            continue
        center = _medoid_lane(group)
        centered_geometry, centerline_method, center_offset, center_span_ratio = (
            _centered_patch_road_geometry(road.geometry, group, center.geometry)
        )
        widths = pd.to_numeric(group.get("Width"), errors="coerce")
        quality = "usable"
        if widths.notna().any() and ((widths < 2.0) | (widths > 6.0)).any():
            quality = "lane_width_quality_isolated"
        center_rows.append(
            {
                **road._asdict(),
                "run_id": run_id,
                "center_lane_id": canonical_id(center["Id"]),
                "center_lane_is_leftmost": bool(center.get("IsLeftmost", False)),
                "centerline_method": centerline_method,
                "center_offset_m": center_offset,
                "center_lane_span_ratio": center_span_ratio,
                "lane_count": int(len(group)),
                "median_lane_width_m": float(widths.median()) if widths.notna().any() else None,
                "evidence_quality_state": quality,
                "geometry": centered_geometry,
            }
        )
        for lane in group.itertuples():
            relation_rows.append(
                {
                    "run_id": run_id,
                    "patch_road_key": road.patch_road_key,
                    "source_patch_id": road.source_patch_id,
                    "road_id": road.road_id,
                    "lane_id": canonical_id(lane.Id),
                    "lane_key": f"{road.source_patch_id}:{canonical_id(lane.Id)}",
                    "is_center_lane": canonical_id(lane.Id) == canonical_id(center["Id"]),
                    "geometry": lane.geometry,
                }
            )
    centers = gpd.GeoDataFrame(center_rows, geometry="geometry", crs=roads.crs)
    relations = gpd.GeoDataFrame(relation_rows, geometry="geometry", crs=roads.crs)
    return centers.reset_index(drop=True), relations.reset_index(drop=True)


def assign_patch_roads_to_segments(
    centers: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    *,
    max_distance_m: float,
    max_angle_deg: float,
    run_id: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    targets = swsd_roads.copy()
    targets["target_swsd_road_id"] = targets["id"].map(canonical_id)
    targets["assigned_segment_id"] = targets["segmentid"].map(canonical_id)
    targets = targets[targets["assigned_segment_id"] != ""].reset_index(drop=True)
    assigned_rows: list[dict[str, object]] = []
    rejected_rows: list[dict[str, object]] = []
    sindex = targets.sindex
    for center in centers.itertuples():
        search = center.geometry.buffer(max_distance_m)
        candidate_indexes = list(sindex.query(search))
        candidates: list[tuple[float, float, float, object]] = []
        for index in candidate_indexes:
            target = targets.iloc[int(index)]
            distance = _sample_distance(center.geometry, target.geometry)
            angle = _line_angle_delta(center.geometry, target.geometry)
            score = distance + angle * 0.08
            candidates.append((score, distance, angle, target))
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]["target_swsd_road_id"]))
        if not candidates:
            rejected_rows.append(_decision_row(center, run_id, "no_segment_candidate"))
            continue
        score, distance, angle, target = candidates[0]
        second_score = candidates[1][0] if len(candidates) > 1 else math.inf
        local_structure = angle > max_angle_deg and distance <= max_distance_m * 0.35
        if distance > max_distance_m or (angle > max_angle_deg and not local_structure):
            rejected_rows.append(
                _decision_row(center, run_id, "distance_or_direction_gate", distance, angle)
            )
            continue
        row = center._asdict()
        row.update(
            {
                "run_id": run_id,
                "assigned_segment_id": target["assigned_segment_id"],
                "target_swsd_road_id": target["target_swsd_road_id"],
                "assignment_distance_m": float(distance),
                "assignment_angle_deg": float(angle),
                "assignment_score": float(score),
                "assignment_margin": float(second_score - score) if math.isfinite(second_score) else None,
                "carrier_role": "local_connector" if local_structure else "directional_corridor",
                "takeover_eligible": True,
                "assignment_state": "assigned_local_structure" if local_structure else "assigned",
                "assignment_source": "member_assignment",
                "reason_codes": "segment_member_search_primitive",
            }
        )
        assigned_rows.append(row)
    assigned = gpd.GeoDataFrame(assigned_rows, geometry="geometry", crs=centers.crs)
    rejected = gpd.GeoDataFrame(rejected_rows, geometry="geometry", crs=centers.crs)
    return assigned.reset_index(drop=True), rejected.reset_index(drop=True)


def orient_patch_road_centers(
    centers: gpd.GeoDataFrame,
    patch_road_next_road: gpd.GeoDataFrame,
    *,
    minimum_score_margin_m: float = 0.5,
) -> gpd.GeoDataFrame:
    result = centers.copy()
    result["orientation_state"] = "retained_without_topology_direction"
    result["orientation_score_margin_m"] = None
    if result.empty or patch_road_next_road.empty:
        return result
    geometry_by_key = {
        str(row.patch_road_key): row.geometry
        for row in result.itertuples(index=False)
    }
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    for relation in patch_road_next_road.itertuples(index=False):
        patch_id = str(relation.source_patch_id)
        source = f"{patch_id}:{canonical_id(relation.RoadId)}"
        target = f"{patch_id}:{canonical_id(relation.NextRoadId)}"
        if source not in geometry_by_key or target not in geometry_by_key:
            continue
        outgoing.setdefault(source, set()).add(target)
        incoming.setdefault(target, set()).add(source)
    for index, row in result.iterrows():
        key = str(row["patch_road_key"])
        line = row.geometry
        if line is None or line.is_empty or line.geom_type != "LineString":
            continue
        start = Point(line.coords[0])
        end = Point(line.coords[-1])
        normal_parts: list[float] = []
        reverse_parts: list[float] = []
        for target_key in sorted(outgoing.get(key, set())):
            target = geometry_by_key[target_key]
            normal_parts.append(float(end.distance(target)))
            reverse_parts.append(float(start.distance(target)))
        for source_key in sorted(incoming.get(key, set())):
            source = geometry_by_key[source_key]
            normal_parts.append(float(start.distance(source)))
            reverse_parts.append(float(end.distance(source)))
        if not normal_parts:
            continue
        normal_score = float(np.mean(normal_parts))
        reverse_score = float(np.mean(reverse_parts))
        margin = abs(normal_score - reverse_score)
        result.at[index, "orientation_score_margin_m"] = margin
        if reverse_score + minimum_score_margin_m < normal_score:
            result.at[index, "geometry"] = LineString(list(line.coords)[::-1])
            result.at[index, "orientation_state"] = "reversed_by_road_topology"
        elif normal_score + minimum_score_margin_m < reverse_score:
            result.at[index, "orientation_state"] = "confirmed_by_road_topology"
        else:
            result.at[index, "orientation_state"] = "topology_direction_ambiguous"
    return result.reset_index(drop=True)


def _medoid_lane(group: gpd.GeoDataFrame) -> pd.Series:
    if len(group) == 1:
        return group.iloc[0]
    points = [geometry.interpolate(0.5, normalized=True) for geometry in group.geometry]
    distances = [sum(point.distance(other) for other in points) for point in points]
    lengths = [float(geometry.length) for geometry in group.geometry]
    index = min(range(len(group)), key=lambda item: (distances[item], -lengths[item], canonical_id(group.iloc[item]["Id"])))
    return group.iloc[index]


def _centered_patch_road_geometry(
    source_road: LineString,
    lanes: gpd.GeoDataFrame,
    medoid_lane: LineString,
) -> tuple[LineString, str, float, float]:
    if source_road is None or source_road.is_empty or source_road.length <= 1e-6:
        return medoid_lane, "medoid_lane_invalid_patch_road", 0.0, 1.0
    span_ratio = float(medoid_lane.length / source_road.length)
    sample_count = max(3, int(math.ceil(source_road.length / 5.0)) + 1)
    sample_distances = np.linspace(0.0, source_road.length, sample_count)
    sample_offsets: list[float] = []
    for distance in sample_distances:
        point = source_road.interpolate(float(distance))
        tangent = _local_tangent(source_road, float(distance))
        normal = np.array([-tangent[1], tangent[0]])
        offsets: list[float] = []
        for lane in lanes.geometry:
            nearest = lane.interpolate(lane.project(point))
            vector = np.array([nearest.x - point.x, nearest.y - point.y])
            longitudinal = abs(float(np.dot(vector, tangent)))
            lateral = float(np.dot(vector, normal))
            if abs(lateral) > 30.0:
                continue
            if longitudinal > max(2.5, abs(lateral) * 0.35):
                continue
            offsets.append(lateral)
        if offsets:
            sample_offsets.append(float(np.median(offsets)))
    if not sample_offsets:
        if span_ratio >= 0.90:
            return medoid_lane, "medoid_lane_no_cross_section", 0.0, span_ratio
        return source_road, "patch_road_center_offset_unresolved", 0.0, span_ratio
    stable_offset = float(np.median(sample_offsets))
    geometry = _sampled_offset_line(source_road, stable_offset)
    if (
        geometry is None
        or geometry.is_empty
        or not geometry.is_valid
        or not geometry.is_simple
        or geometry.length < source_road.length * 0.75
    ):
        if span_ratio >= 0.90:
            return medoid_lane, "medoid_lane_offset_rejected", 0.0, span_ratio
        return source_road, "patch_road_offset_rejected", 0.0, span_ratio
    return geometry, "patch_road_lane_median_offset", stable_offset, span_ratio


def _local_tangent(line: LineString, distance: float) -> np.ndarray:
    delta = min(1.0, max(line.length / 100.0, 0.10))
    start = line.interpolate(max(0.0, distance - delta))
    end = line.interpolate(min(line.length, distance + delta))
    vector = np.array([end.x - start.x, end.y - start.y])
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return np.array([1.0, 0.0])
    return vector / norm


def _sampled_offset_line(line: LineString, offset: float) -> LineString:
    count = max(3, int(math.ceil(line.length / 2.0)) + 1)
    coords: list[tuple[float, float]] = []
    for distance in np.linspace(0.0, line.length, count):
        point = line.interpolate(float(distance))
        tangent = _local_tangent(line, float(distance))
        normal = np.array([-tangent[1], tangent[0]])
        coords.append(
            (
                float(point.x + normal[0] * offset),
                float(point.y + normal[1] * offset),
            )
        )
    return LineString(coords).simplify(0.05, preserve_topology=True)


def _sample_distance(source: LineString, target: LineString) -> float:
    samples = [source.interpolate(value, normalized=True) for value in np.linspace(0.1, 0.9, 5)]
    return float(np.median([point.distance(target) for point in samples]))


def _line_angle_delta(first: LineString, second: LineString) -> float:
    a = _bearing(first)
    b = _bearing(second)
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def _bearing(line: LineString) -> float:
    start = line.interpolate(0.4, normalized=True)
    end = line.interpolate(0.6, normalized=True)
    return math.degrees(math.atan2(end.y - start.y, end.x - start.x)) % 180.0


def _decision_row(
    center: object,
    run_id: str,
    reason: str,
    distance: float | None = None,
    angle: float | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "patch_road_key": center.patch_road_key,
        "source_patch_id": center.source_patch_id,
        "road_id": center.road_id,
        "decision": "rejected",
        "reason_codes": reason,
        "assignment_distance_m": distance,
        "assignment_angle_deg": angle,
        "geometry": center.geometry,
    }


def _lane_topo_audit(
    topology: gpd.GeoDataFrame,
    relations: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    road_by_lane = {
        str(row.lane_key): str(row.patch_road_key) for row in relations.itertuples()
    }
    rows: list[dict[str, object]] = []
    for row in topology.itertuples():
        source_lane_key = f"{row.source_patch_id}:{canonical_id(row.LaneId)}"
        target_lane_key = f"{row.source_patch_id}:{canonical_id(row.NextLaneId)}"
        source_road = road_by_lane.get(source_lane_key, "")
        target_road = road_by_lane.get(target_lane_key, "")
        state = "mapped_candidate" if source_road and target_road else "review_missing_lane"
        rows.append(
            {
                "run_id": run_id,
                "lane_topo_id": f"{row.source_patch_id}:{canonical_id(row.Id)}",
                "source_patch_id": row.source_patch_id,
                "source_lane_key": source_lane_key,
                "target_lane_key": target_lane_key,
                "source_lane_carrier_key": (
                    f"{row.source_patch_id}:lane:{canonical_id(row.LaneId)}"
                ),
                "target_lane_carrier_key": (
                    f"{row.source_patch_id}:lane:{canonical_id(row.NextLaneId)}"
                ),
                "source_patch_road_key": source_road,
                "target_patch_road_key": target_road,
                "projection_state": state,
                "geometry": row.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=topology.crs)


def _explicit_road_pairs(
    relations: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    lane_topo_audit: gpd.GeoDataFrame,
) -> pd.DataFrame:
    published = set(assignments["patch_road_key"].astype(str))
    rows: list[dict[str, object]] = []
    for row in relations.itertuples():
        source = f"{row.source_patch_id}:{canonical_id(row.RoadId)}"
        target = f"{row.source_patch_id}:{canonical_id(row.NextRoadId)}"
        if source in published and target in published:
            rows.append(
                {
                    "source_patch_road_key": source,
                    "target_patch_road_key": target,
                    "source_relation_id": f"{row.source_patch_id}:{canonical_id(row.Id)}",
                    "pair_source": "patch_road_next_road",
                    "source_priority": 1,
                }
            )
    for row in lane_topo_audit.itertuples():
        source = str(row.source_patch_road_key)
        target = str(row.target_patch_road_key)
        source_lane = str(getattr(row, "source_lane_carrier_key", ""))
        target_lane = str(getattr(row, "target_lane_carrier_key", ""))
        if (
            source_lane
            and target_lane
            and source_lane != target_lane
        ):
            rows.append(
                {
                    "source_patch_road_key": source_lane,
                    "target_patch_road_key": target_lane,
                    "source_relation_id": str(row.lane_topo_id),
                    "pair_source": "lane_topo_lane",
                    "source_priority": 3,
                }
            )
        if source == target:
            continue
        rows.append(
            {
                "source_patch_road_key": source,
                "target_patch_road_key": target,
                "source_relation_id": str(row.lane_topo_id),
                "pair_source": "lane_topo",
                "source_priority": 2,
            }
        )
    columns = [
        "source_patch_road_key",
        "target_patch_road_key",
        "source_relation_id",
        "pair_source",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(rows).sort_values(
        [
            "source_patch_road_key",
            "target_patch_road_key",
            "source_priority",
            "source_relation_id",
        ],
        ascending=[True, True, False, True],
    )
    return result.drop_duplicates(
        ["source_patch_road_key", "target_patch_road_key"],
        keep="first",
    )[columns].reset_index(drop=True)


__all__ = [
    "SegmentEvidenceResult",
    "assign_patch_roads_to_segments",
    "build_patch_road_centers",
    "build_segment_evidence",
    "orient_patch_road_centers",
]
