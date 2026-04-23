from __future__ import annotations

from ._runtime_step4_geometry_core import *

def _is_drivezone_position_source(source: str | None) -> bool:
    return str(source or "").startswith("drivezone_split")


def _build_ref_window_away_from_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    window = max(0.0, float(window_m))
    reference_s = float(ref_s)
    sign = -1.0 if reference_s < 0.0 else 1.0
    far_s = reference_s + sign * window
    return float(min(reference_s, far_s)), float(max(reference_s, far_s)), float(far_s)


def _build_ref_window_toward_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    window = max(0.0, float(window_m))
    reference_s = float(ref_s)
    sign = -1.0 if reference_s < 0.0 else 1.0
    near_s = reference_s - sign * window
    return float(min(reference_s, near_s)), float(max(reference_s, near_s)), float(near_s)


def _build_drivezone_backtrack_candidates(
    *,
    ref_s: float,
    start_s: float,
    probe_step: float,
    past_node_m: float,
) -> list[float]:
    step = max(0.05, abs(float(probe_step)))
    past = max(0.0, float(past_node_m))
    sign = -1.0 if float(ref_s) < 0.0 else 1.0
    candidates: list[float] = []
    current_s = float(start_s) - sign * step
    while (current_s >= -1e-9) if sign > 0.0 else (current_s <= 1e-9):
        value = 0.0 if abs(float(current_s)) <= 1e-9 else float(current_s)
        candidates.append(float(value))
        if abs(float(value)) <= 1e-9:
            break
        current_s -= sign * step
    if past > 1e-9:
        current_s = -sign * step
        while abs(float(current_s)) <= past + 1e-9:
            candidates.append(float(current_s))
            current_s -= sign * step
        if not candidates or abs(float(candidates[-1])) < past - 1e-9:
            candidates.append(float(-sign * past))
    deduped: list[float] = []
    seen: set[float] = set()
    for value in candidates:
        rounded = round(float(value), 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        deduped.append(float(value))
    return deduped


def _pick_divstrip_component_near_split(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    split_s: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    divstrip_components: list[Any],
) -> tuple[Any | None, float | None]:
    if not divstrip_components:
        return None, None
    split_crossline = _build_event_crossline(
        origin_point=scan_origin_point,
        axis_unit_vector=scan_axis_unit_vector,
        scan_dist_m=float(split_s),
        cross_half_len_m=float(cross_half_len_m),
    )
    split_center = split_crossline.interpolate(0.5, normalized=True)
    split_segment, split_diag = _build_between_branches_segment(
        crossline=split_crossline,
        center_point=split_center,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
    )
    reference_geometry = (
        split_segment
        if split_segment is not None and split_diag["ok"]
        else split_crossline
    )
    component_metrics: list[dict[str, Any]] = []
    min_distance = math.inf
    for component in divstrip_components:
        if component is None or component.is_empty:
            continue
        related_to_split, distance, overlap_measure = _component_reference_overlap_metrics(
            component_geometry=component,
            reference_geometry=reference_geometry,
            reference_buffer_m=max(float(DIVSTRIP_BRANCH_BUFFER_M), 2.0),
        )
        min_distance = min(float(min_distance), float(distance))
        tip_s = None
        tip_point = _tip_point_from_divstrip(
            divstrip_geometry=component,
            scan_axis_unit_vector=scan_axis_unit_vector,
            origin_point=scan_origin_point,
        )
        if tip_point is not None and not tip_point.is_empty:
            candidate_tip_s = _project_point_to_axis(
                tip_point,
                origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                axis_unit_vector=scan_axis_unit_vector,
            )
            if math.isfinite(float(candidate_tip_s)):
                tip_s = float(candidate_tip_s)
        tip_delta = None if tip_s is None else float(tip_s) - float(split_s)
        forward_tip = tip_delta is not None and float(tip_delta) >= -float(EVENT_REFERENCE_HARD_WINDOW_M)
        component_metrics.append(
            {
                "geometry": component,
                "distance": float(distance),
                "related_to_split": bool(related_to_split),
                "overlap_measure": float(overlap_measure),
                "tip_delta": tip_delta,
                "forward_tip": bool(forward_tip),
                "area": float(getattr(component, "area", 0.0) or 0.0),
            }
        )
    if not component_metrics:
        return None, None
    distance_band_m = float(min_distance) + 12.0
    best_geometry = None
    best_key = None
    best_distance = None
    for metric in component_metrics:
        distance = float(metric["distance"])
        tip_delta = metric["tip_delta"]
        forward_tip = bool(metric["forward_tip"])
        component_key = (
            0 if metric["related_to_split"] else 1,
            0 if distance <= distance_band_m else 1,
            -float(metric["area"]) if distance <= distance_band_m else 0.0,
            0 if forward_tip else 1,
            float(distance),
            -float(metric["overlap_measure"]),
            math.inf if tip_delta is None or not forward_tip else max(0.0, float(tip_delta)),
            math.inf if tip_delta is None else abs(float(tip_delta)),
        )
        if best_key is None or component_key < best_key:
            best_key = component_key
            best_distance = distance
            best_geometry = metric["geometry"]
    return best_geometry, best_distance


def _scan_first_divstrip_hit(
    *,
    scan_samples: list[tuple[float, Any]],
    divstrip_geometry,
    div_tol_m: float,
) -> tuple[float | None, float | None]:
    if divstrip_geometry is None or divstrip_geometry.is_empty:
        return None, None
    first_hit_s = None
    best_distance_m = None
    for scan_s, probe_geometry in scan_samples:
        if probe_geometry is None or probe_geometry.is_empty:
            continue
        distance = float(probe_geometry.distance(divstrip_geometry))
        if best_distance_m is None or distance < best_distance_m:
            best_distance_m = distance
        if first_hit_s is None and distance <= float(div_tol_m):
            first_hit_s = float(scan_s)
    return first_hit_s, best_distance_m

def _resolve_event_axis_unit_vector(
    *,
    axis_centerline,
    origin_point: Point,
) -> tuple[float, float] | None:
    if axis_centerline is None or axis_centerline.is_empty:
        return None
    centerline_length = float(axis_centerline.length)
    if centerline_length <= 1e-6:
        return None
    origin_dist = float(axis_centerline.project(origin_point))
    sample_half_span = min(EVENT_AXIS_TANGENT_SAMPLE_M, max(centerline_length / 4.0, 1.0))
    start_dist = max(0.0, origin_dist - sample_half_span)
    end_dist = min(centerline_length, origin_dist + sample_half_span)
    if end_dist - start_dist <= 1e-6:
        coords = list(axis_centerline.coords)
        if len(coords) < 2:
            return None
        return _normalize_axis_vector(
            (
                float(coords[-1][0]) - float(coords[0][0]),
                float(coords[-1][1]) - float(coords[0][1]),
            )
        )
    segment = substring(axis_centerline, start_dist, end_dist)
    segment_coords = []
    for geometry in _explode_component_geometries(segment):
        if getattr(geometry, "geom_type", None) == "LineString" and not geometry.is_empty:
            segment_coords = list(geometry.coords)
            if segment_coords:
                break
    if len(segment_coords) < 2:
        coords = list(axis_centerline.coords)
        if len(coords) < 2:
            return None
        segment_coords = coords
    return _normalize_axis_vector(
        (
            float(segment_coords[-1][0]) - float(segment_coords[0][0]),
            float(segment_coords[-1][1]) - float(segment_coords[0][1]),
        )
    )

def _build_axis_window_mask(
    *,
    grid,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
) -> np.ndarray:
    if axis_unit_vector is None:
        return np.ones_like(grid.xx, dtype=bool)
    u_coords = (
        (grid.xx - float(origin_point.x)) * float(axis_unit_vector[0])
        + (grid.yy - float(origin_point.y)) * float(axis_unit_vector[1])
    )
    return (u_coords >= float(start_offset_m)) & (u_coords <= float(end_offset_m))


def _build_axis_window_geometry(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
    cross_half_len_m: float,
):
    if axis_unit_vector is None:
        return GeometryCollection()
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    sx = float(origin_point.x) + ux * float(start_offset_m)
    sy = float(origin_point.y) + uy * float(start_offset_m)
    ex = float(origin_point.x) + ux * float(end_offset_m)
    ey = float(origin_point.y) + uy * float(end_offset_m)
    half = float(cross_half_len_m)
    from shapely.geometry import Polygon

    return Polygon(
        [
            (sx + vx * half, sy + vy * half),
            (sx - vx * half, sy - vy * half),
            (ex - vx * half, ey - vy * half),
            (ex + vx * half, ey + vy * half),
        ]
    )


def _rebalance_event_origin_for_rcsd_targets(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    target_rc_nodes: list[ParsedNode],
) -> tuple[Point, dict[str, Any]]:
    if axis_unit_vector is None or not target_rc_nodes:
        return origin_point, {"applied": False, "shift_m": 0.0, "direction": "none", "target_count": len(target_rc_nodes)}

    offsets = [
        _project_point_to_axis(
            node.geometry,
            origin_xy=(float(origin_point.x), float(origin_point.y)),
            axis_unit_vector=axis_unit_vector,
        )
        for node in target_rc_nodes
    ]
    if not offsets:
        return origin_point, {"applied": False, "shift_m": 0.0, "direction": "none", "target_count": 0}

    positive_overflow = max(0.0, max(offsets) - EVENT_SPAN_MAX_M)
    negative_overflow = max(0.0, abs(min(offsets)) - EVENT_SPAN_MAX_M)
    shift_m = 0.0
    direction = "none"
    if positive_overflow > 1e-6 and negative_overflow <= 1e-6:
        shift_m = min(float(positive_overflow), float(EVENT_RCSD_RECENTER_SHIFT_MAX_M))
        direction = "forward"
    elif negative_overflow > 1e-6 and positive_overflow <= 1e-6:
        shift_m = -min(float(negative_overflow), float(EVENT_RCSD_RECENTER_SHIFT_MAX_M))
        direction = "backward"
    if abs(float(shift_m)) <= 1e-6:
        return origin_point, {
            "applied": False,
            "shift_m": 0.0,
            "direction": direction,
            "target_count": len(offsets),
        }
    shifted_point = _point_from_axis_offset(
        origin_point=origin_point,
        axis_unit_vector=axis_unit_vector,
        offset_m=float(shift_m),
    )
    return shifted_point, {
        "applied": True,
        "shift_m": float(shift_m),
        "direction": direction,
        "target_count": len(offsets),
        "max_offset_m": float(max(offsets)),
        "min_offset_m": float(min(offsets)),
    }


def _collect_line_parts(geometry) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if getattr(geometry, "geom_type", None) == "LineString":
        return [geometry] if float(geometry.length) > 1e-6 else []
    parts: list[Any] = []
    for item in _explode_component_geometries(geometry):
        if getattr(item, "geom_type", None) == "LineString" and float(item.length) > 1e-6:
            parts.append(item)
    return parts


def _collect_axis_lateral_offsets(
    geometry,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
    axis_window_m: float | None = None,
) -> list[float]:
    if geometry is None or geometry.is_empty:
        return []
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    if axis_window_m is None or axis_window_m <= 1e-6:
        axis_window_m = None
    lateral_offsets: list[float] = []
    for item in _explode_component_geometries(geometry):
        geometry_type = getattr(item, "geom_type", None)
        if geometry_type == "Point":
            coordinates = [_coord_xy(item.coords[0])]
        elif geometry_type == "LineString":
            coordinates = list(item.coords)
        elif geometry_type == "Polygon":
            coordinates = list(item.exterior.coords)
            for ring in item.interiors:
                coordinates.extend(ring.coords)
        else:
            continue
        for x, y in (_coord_xy(coord) for coord in coordinates):
            dx = float(x) - float(origin_xy[0])
            dy = float(y) - float(origin_xy[1])
            axis_offset = dx * ux + dy * uy
            if axis_window_m is not None and abs(axis_offset) > float(axis_window_m):
                continue
            lateral_offsets.append(abs(dx * vx + dy * vy))
    return lateral_offsets


def _resolve_event_cross_half_len(
    *,
    origin_point: Point,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    event_anchor_geometry,
    branch_a_centerline,
    branch_b_centerline,
    selected_roads: list[ParsedRoad],
    selected_rcsd_roads: list[ParsedRoad],
    patch_size_m: float,
) -> float:
    if axis_unit_vector is None or axis_centerline is None or axis_centerline.is_empty:
        return float(EVENT_CROSS_HALF_LEN_FALLBACK_M)
    origin_xy = (float(origin_point.x), float(origin_point.y))
    axis_window_m = float(EVENT_CROSS_HALF_LEN_AXIS_SAMPLE_WINDOW_M)
    candidate_offsets: list[float] = []
    candidate_geometries = [
        event_anchor_geometry,
        branch_a_centerline,
        branch_b_centerline,
    ] + [road.geometry for road in selected_roads if road.geometry is not None and not road.geometry.is_empty]
    for road in selected_rcsd_roads:
        if road.geometry is not None and not road.geometry.is_empty:
            candidate_geometries.append(road.geometry)
    candidate_geometries = [geometry for geometry in candidate_geometries if geometry is not None and not geometry.is_empty]
    for geometry in candidate_geometries:
        candidate_offsets.extend(
            _collect_axis_lateral_offsets(
                geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
                axis_window_m=axis_window_m,
            )
        )

    max_lateral_offset = max(candidate_offsets) if candidate_offsets else None
    if max_lateral_offset is None:
        resolved_half_len = float(EVENT_CROSS_HALF_LEN_FALLBACK_M)
    else:
        resolved_half_len = float(max_lateral_offset + EVENT_CROSS_HALF_LEN_SIDE_MARGIN_M)
    resolved_half_len = max(float(EVENT_CROSS_HALF_LEN_MIN_M), min(float(EVENT_CROSS_HALF_LEN_MAX_M), resolved_half_len))
    patch_half_cap = max(
        float(EVENT_CROSS_HALF_LEN_MIN_M),
        min(float(EVENT_CROSS_HALF_LEN_MAX_M), float(patch_size_m) * float(EVENT_CROSS_HALF_LEN_PATCH_SCALE_RATIO)),
    )
    return float(min(resolved_half_len, patch_half_cap))


def _build_event_crossline(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float],
    scan_dist_m: float,
    cross_half_len_m: float,
) -> LineString:
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    cx = float(origin_point.x) + ux * float(scan_dist_m)
    cy = float(origin_point.y) + uy * float(scan_dist_m)
    hx = float(cross_half_len_m) * vx
    hy = float(cross_half_len_m) * vy
    return LineString([(cx - hx, cy - hy), (cx + hx, cy + hy)])


def _pick_cross_section_boundary_branches(
    *,
    road_branches,
    selected_branch_ids: set[str],
    kind_2: int,
):
    selected_branches = [branch for branch in road_branches if branch.branch_id in selected_branch_ids]
    if not selected_branches:
        selected_branches = list(road_branches)
    if kind_2 == 8:
        directional_candidates = [branch for branch in selected_branches if branch.has_incoming_support]
    else:
        directional_candidates = [branch for branch in selected_branches if branch.has_outgoing_support]
    if len(directional_candidates) < 2:
        directional_candidates = list(selected_branches)
    if len(directional_candidates) < 2:
        return None, None
    best_pair = None
    best_key = None
    for first_branch, second_branch in combinations(directional_candidates, 2):
        pair_key = (
            _branch_angle_gap_deg(first_branch, second_branch),
            _selected_branch_score(first_branch) + _selected_branch_score(second_branch),
        )
        if best_key is None or pair_key > best_key:
            best_key = pair_key
            best_pair = (first_branch, second_branch)
    if best_pair is None:
        return None, None
    return best_pair


def _pick_local_component_boundary_branches(
    *,
    road_branches,
    selected_branch_ids: set[str],
    kind_2: int,
    road_lookup: dict[str, ParsedRoad],
    reference_point: Point,
):
    fallback_pair = _pick_cross_section_boundary_branches(
        road_branches=road_branches,
        selected_branch_ids=selected_branch_ids,
        kind_2=kind_2,
    )
    selected_branches = list(road_branches)
    if kind_2 == 8:
        directional_candidates = [branch for branch in selected_branches if branch.has_incoming_support]
    else:
        directional_candidates = [branch for branch in selected_branches if branch.has_outgoing_support]
    if len(directional_candidates) < 2:
        directional_candidates = list(selected_branches)
    if len(directional_candidates) < 2:
        return fallback_pair

    local_candidates: list[tuple[Any, float, int]] = []
    for branch in directional_candidates:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if centerline is None or centerline.is_empty:
            continue
        local_candidates.append(
            (
                branch,
                float(centerline.distance(reference_point)),
                1 if branch.branch_id in selected_branch_ids else 0,
            )
        )
    if len(local_candidates) < 2:
        return fallback_pair

    nearby_candidates = [
        item
        for item in local_candidates
        if float(item[1]) <= float(EVENT_COMPONENT_BRANCH_LOCAL_DISTANCE_M)
    ]
    if len(nearby_candidates) < 2:
        nearby_candidates = sorted(
            local_candidates,
            key=lambda item: (
                float(item[1]),
                -int(item[2]),
                -_selected_branch_score(item[0]),
            ),
        )[:5]

    best_pair = None
    best_key = None
    for (first_branch, first_dist, first_preferred), (second_branch, second_dist, second_preferred) in combinations(nearby_candidates, 2):
        pair_key = (
            -max(float(first_dist), float(second_dist)),
            -(float(first_dist) + float(second_dist)),
            int(first_preferred) + int(second_preferred),
            _branch_angle_gap_deg(first_branch, second_branch),
            _selected_branch_score(first_branch) + _selected_branch_score(second_branch),
        )
        if best_key is None or pair_key > best_key:
            best_key = pair_key
            best_pair = (first_branch, second_branch)
    if best_pair is None:
        return fallback_pair
    return best_pair


def _collect_crossline_projection_points(geometry, *, crossline: LineString, center_point: Point) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    geometry_type = getattr(geometry, "geom_type", None)
    if geometry_type == "Point":
        return [geometry]
    if geometry_type == "MultiPoint":
        return [item for item in geometry.geoms if item is not None and not item.is_empty]
    if geometry_type == "LineString":
        return [geometry.interpolate(float(geometry.project(center_point)))]
    if geometry_type == "MultiLineString":
        return [
            line.interpolate(float(line.project(center_point)))
            for line in geometry.geoms
            if line is not None and not line.is_empty
        ]
    if geometry_type == "GeometryCollection":
        points: list[Point] = []
        for item in geometry.geoms:
            points.extend(
                _collect_crossline_projection_points(
                    item,
                    crossline=crossline,
                    center_point=center_point,
                )
            )
        return points
    return []


def _pick_point_on_branch_centerline(
    *,
    branch_centerline,
    crossline: LineString,
    center_point: Point,
) -> tuple[Point, bool]:
    intersection_geometry = branch_centerline.intersection(crossline)
    candidates = _collect_crossline_projection_points(
        intersection_geometry,
        crossline=crossline,
        center_point=center_point,
    )
    if candidates:
        point = min(candidates, key=lambda item: float(item.distance(center_point)))
        return Point(float(point.x), float(point.y)), True
    branch_point, _ = nearest_points(branch_centerline, crossline)
    return Point(float(branch_point.x), float(branch_point.y)), False


def _build_between_branches_segment(
    *,
    crossline: LineString,
    center_point: Point,
    branch_a_centerline,
    branch_b_centerline,
) -> tuple[LineString | None, dict[str, Any]]:
    if (
        branch_a_centerline is None
        or branch_a_centerline.is_empty
        or branch_b_centerline is None
        or branch_b_centerline.is_empty
    ):
        return None, {
            "ok": False,
            "reason": "missing_branch_centerline",
            "branch_a_crossline_hit": False,
            "branch_b_crossline_hit": False,
        }
    point_a, branch_a_hit = _pick_point_on_branch_centerline(
        branch_centerline=branch_a_centerline,
        crossline=crossline,
        center_point=center_point,
    )
    point_b, branch_b_hit = _pick_point_on_branch_centerline(
        branch_centerline=branch_b_centerline,
        crossline=crossline,
        center_point=center_point,
    )
    segment = LineString([(float(point_a.x), float(point_a.y)), (float(point_b.x), float(point_b.y))])
    return segment, {
        "ok": True,
        "reason": "ok",
        "seg_len_m": float(segment.length),
        "pa_center_dist_m": float(point_a.distance(center_point)),
        "pb_center_dist_m": float(point_b.distance(center_point)),
        "branch_a_crossline_hit": bool(branch_a_hit),
        "branch_b_crossline_hit": bool(branch_b_hit),
    }


def _trim_line_endcaps(
    *,
    line: LineString | None,
    trim_m: float,
):
    if line is None or line.is_empty:
        return GeometryCollection()
    line_length = float(line.length)
    if line_length <= 1e-6:
        return GeometryCollection()
    trim = max(0.0, float(trim_m))
    if trim <= 1e-6:
        return line
    if line_length <= float(trim) * 2.0 + 1e-6:
        return GeometryCollection()
    return substring(line, float(trim), float(line_length) - float(trim))


def _segment_intruding_road_ids(
    *,
    segment: LineString | None,
    scoped_roads: list[ParsedRoad],
    allowed_road_ids: set[str],
    event_road_ids: set[str],
    origin_point: Point | None,
    throat_radius_m: float,
    trim_m: float = 1.5,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    inner_segment = _trim_line_endcaps(line=segment, trim_m=trim_m)
    if inner_segment is None or inner_segment.is_empty:
        return (), ()
    if origin_point is not None and not origin_point.is_empty:
        inner_segment = inner_segment.difference(
            origin_point.buffer(max(0.0, float(throat_radius_m)), join_style=2)
        )
    if inner_segment is None or inner_segment.is_empty:
        return (), ()
    probe_geometry = inner_segment.buffer(max(0.4, float(trim_m) * 0.35), cap_style=2, join_style=2)
    pair_replacement_ids: set[str] = set()
    intrusion_ids: set[str] = set()
    for road in scoped_roads:
        road_id = str(road.road_id)
        if road_id in allowed_road_ids:
            continue
        geometry = road.geometry
        if geometry is None or geometry.is_empty or not geometry.intersects(probe_geometry):
            continue
        if road_id in event_road_ids:
            pair_replacement_ids.add(road_id)
        else:
            intrusion_ids.add(road_id)
    return tuple(sorted(pair_replacement_ids)), tuple(sorted(intrusion_ids))


def _build_pair_local_slice_diagnostic(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float],
    scan_dist_m: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    scoped_roads: list[ParsedRoad],
    allowed_road_ids: set[str],
    event_road_ids: set[str],
    branch_separation_threshold_m: float,
    throat_radius_m: float,
) -> dict[str, Any]:
    crossline = _build_event_crossline(
        origin_point=origin_point,
        axis_unit_vector=axis_unit_vector,
        scan_dist_m=float(scan_dist_m),
        cross_half_len_m=float(cross_half_len_m),
    )
    center_point = crossline.interpolate(0.5, normalized=True)
    segment, segment_diag = _build_between_branches_segment(
        crossline=crossline,
        center_point=center_point,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
    )
    diag = {
        "scan_s": float(scan_dist_m),
        "crossline": crossline,
        "center_point": center_point,
        "segment": segment,
        **dict(segment_diag),
        "pair_replacement_road_ids": (),
        "intruding_road_ids": (),
        "branch_separation_threshold_m": float(branch_separation_threshold_m),
        "branch_separation_exceeded": False,
        "stop_reason": "ok",
    }
    if segment is None or not bool(segment_diag.get("ok")):
        diag["stop_reason"] = str(segment_diag.get("reason") or "semantic_boundary_reached")
        return diag
    segment_length = float(segment_diag.get("seg_len_m", 0.0) or 0.0)
    diag["branch_separation_exceeded"] = bool(
        segment_length >= max(0.0, float(branch_separation_threshold_m)) - 1e-6
        or not bool(segment_diag.get("branch_a_crossline_hit"))
        or not bool(segment_diag.get("branch_b_crossline_hit"))
    )
    pair_replacement_ids, intrusion_ids = _segment_intruding_road_ids(
        segment=segment,
        scoped_roads=scoped_roads,
        allowed_road_ids=allowed_road_ids,
        event_road_ids=event_road_ids,
        origin_point=origin_point,
        throat_radius_m=throat_radius_m,
    )
    diag["pair_replacement_road_ids"] = pair_replacement_ids
    diag["intruding_road_ids"] = intrusion_ids
    if pair_replacement_ids:
        diag["stop_reason"] = "pair_relation_replaced"
        return diag
    if intrusion_ids:
        diag["stop_reason"] = "road_intrusion_between_branches"
        return diag
    if diag["branch_separation_exceeded"]:
        diag["stop_reason"] = "branch_separation_too_large"
        return diag
    if not bool(segment_diag.get("branch_a_crossline_hit")) or not bool(segment_diag.get("branch_b_crossline_hit")):
        diag["stop_reason"] = "semantic_boundary_reached"
        return diag
    return diag


def _extend_line_to_half_len(
    *,
    line: LineString,
    half_len_m: float,
):
    if line is None or line.is_empty:
        return line
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    start_x, start_y = _coord_xy(coords[0])
    end_x, end_y = _coord_xy(coords[-1])
    vector = _normalize_axis_vector((end_x - start_x, end_y - start_y))
    if vector is None:
        return line
    center_point = line.interpolate(0.5, normalized=True)
    ux, uy = vector
    half = max(0.1, float(half_len_m))
    return LineString(
        [
            (float(center_point.x) - ux * half, float(center_point.y) - uy * half),
            (float(center_point.x) + ux * half, float(center_point.y) + uy * half),
        ]
    )


def _segment_drivezone_pieces(
    *,
    segment: LineString,
    drivezone_union,
    min_piece_len_m: float = 0.5,
) -> list[Any]:
    pieces = _collect_line_parts(segment.intersection(drivezone_union))
    return [piece for piece in pieces if float(piece.length) >= float(min_piece_len_m)]

def _build_axis_side_halfmask(
    *,
    grid,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    parallel_side_sign: int | None,
) -> np.ndarray | None:
    if axis_unit_vector is None or parallel_side_sign not in (-1, 1):
        return None
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    lateral_offset = (grid.xx - float(origin_point.x)) * float(vx) + (grid.yy - float(origin_point.y)) * float(vy)
    side_mask = np.where(
        lateral_offset * float(parallel_side_sign) >= -float(PARALLEL_SIDE_SIGN_EPS_M),
        True,
        False,
    )
    return side_mask.astype(bool)


def _clip_line_to_parallel_midline(
    *,
    line: LineString,
    crossline: LineString,
    axis_centerline,
    parallel_centerline,
):
    if (
        line is None
        or line.is_empty
        or axis_centerline is None
        or axis_centerline.is_empty
        or parallel_centerline is None
        or parallel_centerline.is_empty
    ):
        return line
    center_point = crossline.interpolate(0.5, normalized=True)
    axis_point, _ = nearest_points(axis_centerline, crossline)
    parallel_point, _ = nearest_points(parallel_centerline, crossline)
    axis_s = float(crossline.project(axis_point))
    parallel_s = float(crossline.project(parallel_point))
    if not math.isfinite(axis_s) or not math.isfinite(parallel_s):
        return line
    midpoint_s = 0.5 * (axis_s + parallel_s)
    line_coords = list(line.coords)
    if len(line_coords) < 2:
        return line
    start_s = float(crossline.project(Point(_coord_xy(line_coords[0]))))
    end_s = float(crossline.project(Point(_coord_xy(line_coords[-1]))))
    lo = min(start_s, end_s)
    hi = max(start_s, end_s)
    midpoint_s = max(lo + 1e-6, min(hi - 1e-6, midpoint_s))
    if midpoint_s <= lo + 1e-6 or midpoint_s >= hi - 1e-6:
        return line
    if axis_s <= parallel_s:
        clipped_lo, clipped_hi = lo, midpoint_s
    else:
        clipped_lo, clipped_hi = midpoint_s, hi
    start_point = crossline.interpolate(clipped_lo)
    end_point = crossline.interpolate(clipped_hi)
    return LineString([(float(start_point.x), float(start_point.y)), (float(end_point.x), float(end_point.y))])


def _resolve_event_reference_position(
    *,
    representative_node: ParsedNode,
    scan_origin_point: Point,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    scan_axis_unit_vector: tuple[float, float] | None,
    branch_a_centerline,
    branch_b_centerline,
    drivezone_union,
    divstrip_constraint_geometry,
    event_anchor_geometry,
    cross_half_len_m: float,
):
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None or scan_axis_unit_vector is None:
        return {
            "origin_point": scan_origin_point,
            "event_origin_source": "representative_axis_origin",
            "position_source": "representative_axis_origin",
            "chosen_s_m": 0.0,
            "scan_origin_point": scan_origin_point,
            "tip_s_m": None,
            "first_divstrip_hit_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "split_pick_source": "none",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    origin_xy = (float(scan_origin_point.x), float(scan_origin_point.y))
    candidate_offsets = _collect_axis_offsets_from_geometry(
        divstrip_constraint_geometry if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty else event_anchor_geometry,
        origin_xy=origin_xy,
        axis_unit_vector=axis_unit_vector,
    )
    if candidate_offsets:
        search_start = max(-EVENT_REFERENCE_SCAN_MAX_M, min(candidate_offsets) - EVENT_REFERENCE_SEARCH_MARGIN_M)
        search_end = min(EVENT_REFERENCE_SCAN_MAX_M, max(candidate_offsets) + EVENT_REFERENCE_SEARCH_MARGIN_M)
    else:
        search_start = -EVENT_REFERENCE_SEARCH_MARGIN_M
        search_end = EVENT_REFERENCE_SEARCH_MARGIN_M
    if search_end - search_start <= 1e-6:
        search_start = min(search_start, -EVENT_REFERENCE_SEARCH_MARGIN_M)
        search_end = max(search_end, EVENT_REFERENCE_SEARCH_MARGIN_M)

    tip_s = None
    first_divstrip_hit_s = None
    s_drivezone_split = None
    scan_samples: list[tuple[float, LineString]] = []
    split_pick_source = "none"
    divstrip_ref_source = "none"
    divstrip_ref_offset_m = None

    tip_point = _tip_point_from_divstrip(
        divstrip_geometry=divstrip_constraint_geometry,
        scan_axis_unit_vector=scan_axis_unit_vector,
        origin_point=scan_origin_point,
    )
    if tip_point is not None and not tip_point.is_empty:
        tip_s = _project_point_to_axis(
            tip_point,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )

    offset = float(search_start)
    while offset <= float(search_end) + 1e-6:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=axis_unit_vector,
            scan_dist_m=offset,
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is not None and segment_diag["ok"]:
            scan_samples.append((float(offset), found_segment))
            if (
                divstrip_constraint_geometry is not None
                and not divstrip_constraint_geometry.is_empty
                and first_divstrip_hit_s is None
                and float(found_segment.distance(divstrip_constraint_geometry)) <= EVENT_REFERENCE_DIVSTRIP_TOL_M
            ):
                first_divstrip_hit_s = float(offset)
            pieces = _segment_drivezone_pieces(
                segment=found_segment,
                drivezone_union=drivezone_union,
            )
            if len(pieces) < 2:
                extended_segment = _extend_line_to_half_len(
                    line=found_segment,
                    half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                )
                pieces = _segment_drivezone_pieces(
                    segment=extended_segment,
                    drivezone_union=drivezone_union,
                )
            if s_drivezone_split is None and len(pieces) >= 2:
                s_drivezone_split = float(offset)
        offset += EVENT_REFERENCE_SCAN_STEP_M

    divstrip_components = _collect_polygon_components(divstrip_constraint_geometry)
    if (
        len(divstrip_components) > 1
        and s_drivezone_split is not None
        and abs(float(s_drivezone_split)) >= float(EVENT_REFERENCE_DIVSTRIP_TARGET_BY_SPLIT_MIN_S_M) - 1e-9
        and scan_samples
    ):
        split_crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=axis_unit_vector,
            scan_dist_m=float(s_drivezone_split),
            cross_half_len_m=cross_half_len_m,
        )
        split_center_point = split_crossline.interpolate(0.5, normalized=True)
        split_segment, split_segment_diag = _build_between_branches_segment(
            crossline=split_crossline,
            center_point=split_center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if split_segment is not None and split_segment_diag["ok"]:
            selected_component = min(
                divstrip_components,
                key=lambda component: float(split_segment.distance(component)),
            )
            for sample_s, sample_segment in scan_samples:
                if float(sample_segment.distance(selected_component)) <= EVENT_REFERENCE_DIVSTRIP_TOL_M:
                    first_divstrip_hit_s = float(sample_s)
                    break

    divstrip_ref_s = None
    if tip_s is not None and search_start - 1e-6 <= float(tip_s) <= search_end + 1e-6:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"
    elif first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=s_drivezone_split,
        max_offset_m=EVENT_REFERENCE_MAX_OFFSET_M,
    )
    if chosen_s is None:
        chosen_s = 0.0
        position_source = "representative_axis_origin"
    if divstrip_ref_s is not None:
        divstrip_ref_offset_m = abs(float(chosen_s) - float(divstrip_ref_s))
    chosen_point = Point(
        float(scan_origin_point.x) + float(axis_unit_vector[0]) * float(chosen_s),
        float(scan_origin_point.y) + float(axis_unit_vector[1]) * float(chosen_s),
    )
    return {
        "origin_point": chosen_point,
        "event_origin_source": (
            "representative_axis_origin"
            if str(position_source) == "representative_axis_origin"
            else f"chosen_s_{position_source}"
        ),
        "position_source": str(position_source),
        "chosen_s_m": float(chosen_s),
        "scan_origin_point": scan_origin_point,
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_s_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if s_drivezone_split is None else float(s_drivezone_split),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source),
        "divstrip_ref_offset_m": None if divstrip_ref_offset_m is None else float(divstrip_ref_offset_m),
    }


def _build_cross_section_surface_geometry(
    *,
    drivezone_union,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
    cross_half_len_m: float,
    axis_centerline,
    branch_a_centerline,
    branch_b_centerline,
    parallel_centerline,
    resolution_m: float,
    support_geometry=None,
):
    if axis_unit_vector is None:
        return GeometryCollection(), 0
    step_m = max(EVENT_CROSSLINE_STEP_M, float(resolution_m))
    start_m = float(min(start_offset_m, end_offset_m))
    end_m = float(max(start_offset_m, end_offset_m))
    scan_values = [start_m]
    cursor = start_m + step_m
    while cursor < end_m - 1e-9:
        scan_values.append(float(cursor))
        cursor += step_m
    if abs(end_m - scan_values[-1]) > 1e-9:
        scan_values.append(end_m)
    strip_geometries: list[Any] = []
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=origin_point,
            axis_unit_vector=axis_unit_vector,
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
        if found_segment is None or not segment_diag["ok"]:
            continue
        drivezone_pieces = _collect_line_parts(crossline.intersection(drivezone_union))
        if support_geometry is None and drivezone_pieces:
            all_s_values: list[float] = []
            for piece in drivezone_pieces:
                for coord in list(piece.coords):
                    if len(coord) >= 2:
                        all_s_values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
            if all_s_values:
                full_start = crossline.interpolate(min(all_s_values))
                full_end = crossline.interpolate(max(all_s_values))
                clipped_line = LineString([
                    (float(full_start.x), float(full_start.y)),
                    (float(full_end.x), float(full_end.y)),
                ])
            else:
                clipped_line = None
        else:
            clipped_line = _build_continuous_line_from_crossline(
                crossline=crossline,
                pieces_raw=drivezone_pieces,
                center_point=center_point,
                found_segment=found_segment,
                drivezone_union=drivezone_union,
                edge_pad_m=max(step_m * 0.5, resolution_m * 0.75),
                support_geometry=support_geometry,
            )
        if clipped_line is None:
            continue
        clipped_line = _clip_line_to_parallel_midline(
            line=clipped_line,
            crossline=crossline,
            axis_centerline=axis_centerline,
            parallel_centerline=parallel_centerline,
        )
        if clipped_line is None or clipped_line.is_empty or float(clipped_line.length) <= 1e-6:
            continue
        strip_geometries.append(
            clipped_line.buffer(max(step_m * 0.55, resolution_m * 0.9), cap_style=2, join_style=2)
        )
    if not strip_geometries:
        return GeometryCollection(), 0
    surface_geometry = unary_union(strip_geometries).intersection(drivezone_union).buffer(0)
    return surface_geometry, len(strip_geometries)


def _build_continuous_line_from_crossline(
    *,
    crossline: LineString,
    pieces_raw: list[Any],
    center_point: Point,
    found_segment: LineString,
    drivezone_union,
    edge_pad_m: float,
    support_geometry=None,
):
    if not pieces_raw:
        return None
    center_s = float(crossline.project(center_point))
    piece_info: list[tuple[Any, float, float, float, float, float]] = []
    for piece in pieces_raw:
        values: list[float] = []
        for coord in list(piece.coords):
            if len(coord) < 2:
                continue
            values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
        if not values:
            continue
        s0 = float(min(values))
        s1 = float(max(values))
        overlap_len = 0.0
        support_distance = float("inf")
        if support_geometry is not None and not support_geometry.is_empty:
            overlap_geometry = piece.intersection(support_geometry)
            overlap_len = float(getattr(overlap_geometry, "length", 0.0))
            if overlap_len <= 1e-6:
                support_distance = float(piece.distance(support_geometry))
            else:
                support_distance = 0.0
        piece_info.append((piece, s0, s1, 0.5 * (s0 + s1), overlap_len, support_distance))
    if not piece_info:
        return None

    point_a = Point(float(found_segment.coords[0][0]), float(found_segment.coords[0][1]))
    point_b = Point(float(found_segment.coords[-1][0]), float(found_segment.coords[-1][1]))
    point_a_s = float(crossline.project(point_a))
    point_b_s = float(crossline.project(point_b))
    left_ref_s, right_ref_s = (
        (point_a_s, point_b_s)
        if point_a_s <= point_b_s
        else (point_b_s, point_a_s)
    )

    center_hits = [item for item in piece_info if float(item[1]) - 1e-6 <= center_s <= float(item[2]) + 1e-6]
    support_hits = [
        item
        for item in piece_info
        if float(item[4]) > 1e-6 or float(item[5]) <= max(float(edge_pad_m) * 2.0, 3.0)
    ]
    candidate_pool = support_hits or piece_info
    if center_hits:
        selected_piece = min(
            [item for item in center_hits if item in candidate_pool] or candidate_pool,
            key=lambda item: (
                0 if float(item[4]) > 1e-6 else 1,
                -float(item[4]),
                float(item[5]),
                abs(float(item[3]) - center_s),
                abs(float(item[3]) - 0.5 * (left_ref_s + right_ref_s)),
                -float(item[0].length),
            ),
        )
    else:
        selected_piece = min(
            candidate_pool,
            key=lambda item: (
                0 if float(item[4]) > 1e-6 else 1,
                -float(item[4]),
                float(item[5]),
                min(abs(center_s - float(item[1])), abs(center_s - float(item[2])), abs(center_s - float(item[3]))),
                abs(float(item[3]) - center_s),
                -float(item[0].length),
            ),
        )

    base_s0 = float(selected_piece[1])
    base_s1 = float(selected_piece[2])
    found_segment_hits_drivezone = bool(
        _segment_drivezone_pieces(
            segment=found_segment,
            drivezone_union=drivezone_union,
            min_piece_len_m=0.5,
        )
    )
    if not found_segment_hits_drivezone:
        span_start = base_s0
        span_end = base_s1
    else:
        span_start = max(base_s0, float(left_ref_s) - max(0.0, float(edge_pad_m)))
        span_end = min(base_s1, float(right_ref_s) + max(0.0, float(edge_pad_m)))
    span_start = max(base_s0, min(span_start, center_s))
    span_end = min(base_s1, max(span_end, center_s))
    if span_end - span_start <= 1e-6:
        span_start = base_s0
        span_end = base_s1

    edge_touch_tol_m = 0.1
    if drivezone_union is not None and not drivezone_union.is_empty:
        start_probe = crossline.interpolate(span_start)
        end_probe = crossline.interpolate(span_end)
        if float(start_probe.distance(drivezone_union.boundary)) > edge_touch_tol_m + 1e-9 and span_start > base_s0 + 1e-9:
            span_start = base_s0
        if float(end_probe.distance(drivezone_union.boundary)) > edge_touch_tol_m + 1e-9 and span_end < base_s1 - 1e-9:
            span_end = base_s1
    if span_end - span_start <= 1e-6:
        return None
    start_point = crossline.interpolate(span_start)
    end_point = crossline.interpolate(span_end)
    return LineString([(float(start_point.x), float(start_point.y)), (float(end_point.x), float(end_point.y))])

def _is_stage4_representative(node: ParsedNode) -> bool:
    representative_id = node.mainnodeid or node.node_id
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and _is_stage4_supported_node_kind(node)
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _stage4_chain_kind_2(node: ParsedNode) -> int | None:
    source_kind_2 = _node_source_kind_2(node)
    if source_kind_2 in STAGE4_KIND_2_VALUES or source_kind_2 == COMPLEX_JUNCTION_KIND:
        return source_kind_2
    if _node_source_kind(node) == COMPLEX_JUNCTION_KIND:
        return COMPLEX_JUNCTION_KIND
    return None

__all__ = [
    name
    for name, value in globals().items()
    if name.isupper() or name == 'Stage4RunError' or (name.startswith('_') and callable(value))
]


__all__ = [name for name in globals() if not name.startswith("__")]
