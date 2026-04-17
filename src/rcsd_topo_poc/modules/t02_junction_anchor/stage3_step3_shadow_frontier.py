from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def _attr(value: Any, name: str, default: Any = None) -> Any:
    return getattr(value, name, default)


def _normalized_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iter_points(geometry: BaseGeometry) -> Iterable[tuple[float, float]]:
    if geometry.is_empty:
        return ()
    def _xy_pairs(coords: Iterable[Any]) -> tuple[tuple[float, float], ...]:
        return tuple((float(coord[0]), float(coord[1])) for coord in coords)
    if isinstance(geometry, Point):
        return ((float(geometry.x), float(geometry.y)),)
    if isinstance(geometry, LineString):
        return _xy_pairs(geometry.coords)
    if isinstance(geometry, MultiLineString):
        return tuple(
            (float(coord[0]), float(coord[1]))
            for line in geometry.geoms
            for coord in line.coords
        )
    if isinstance(geometry, Polygon):
        return _xy_pairs(geometry.exterior.coords)
    if isinstance(geometry, MultiPolygon):
        return tuple(
            (float(coord[0]), float(coord[1]))
            for polygon in geometry.geoms
            for coord in polygon.exterior.coords
        )
    if hasattr(geometry, "geoms"):
        return tuple(
            point
            for part in geometry.geoms
            for point in _iter_points(part)
        )
    return ()


def _branch_ray_geometry(center: Point, *, angle_deg: float, length_m: float) -> LineString:
    radians = math.radians(angle_deg)
    end_x = float(center.x) + math.cos(radians) * length_m
    end_y = float(center.y) + math.sin(radians) * length_m
    return LineString([(float(center.x), float(center.y)), (end_x, end_y)])


def _branch_cap_clip_geometry(
    center: Point,
    *,
    angle_deg: float,
    length_m: float,
    half_width_m: float,
    drivezone_union: BaseGeometry,
    extension_m: float = 0.0,
    center_radius_m: float = 0.0,
) -> BaseGeometry:
    clip_parts: list[BaseGeometry] = []
    if half_width_m > 0.0:
        clip_parts.append(
            _branch_ray_geometry(
                center,
                angle_deg=angle_deg,
                length_m=max(1.0, float(length_m) + float(extension_m)),
            ).buffer(
                half_width_m,
                cap_style=2,
                join_style=2,
            )
        )
    if center_radius_m > 0.0:
        clip_parts.append(center.buffer(center_radius_m, join_style=1))
    if not clip_parts:
        return GeometryCollection()
    return unary_union(clip_parts).intersection(drivezone_union)


def _projection_and_lateral(
    *,
    center: Point,
    angle_deg: float,
    x: float,
    y: float,
) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    ux = math.cos(radians)
    uy = math.sin(radians)
    dx = float(x) - float(center.x)
    dy = float(y) - float(center.y)
    projection_m = dx * ux + dy * uy
    lateral_m = abs(-dx * uy + dy * ux)
    return projection_m, lateral_m


def _max_projection_from_geometries(
    *,
    geometries: Iterable[BaseGeometry],
    center: Point,
    angle_deg: float,
    lateral_tolerance_m: float,
) -> float | None:
    best: float | None = None
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        for x, y in _iter_points(geometry):
            projection_m, lateral_m = _projection_and_lateral(
                center=center,
                angle_deg=angle_deg,
                x=x,
                y=y,
            )
            if projection_m <= 0.0 or lateral_m > lateral_tolerance_m:
                continue
            if best is None or projection_m > best:
                best = projection_m
    return best


def _nearest_neighbor_projection(
    *,
    local_nodes: Sequence[Any],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str | None,
    center: Point,
    angle_deg: float,
    lateral_tolerance_m: float,
    min_projection_m: float,
) -> float | None:
    best: float | None = None
    for node in local_nodes:
        node_id = _normalized_id(_attr(node, "node_id"))
        if node_id is None or node_id in target_group_node_ids:
            continue
        node_mainnodeid = _normalized_id(_attr(node, "mainnodeid"))
        if node_mainnodeid is not None and node_mainnodeid == normalized_mainnodeid:
            continue
        geometry = _attr(node, "geometry")
        if geometry is None or geometry.is_empty:
            continue
        projection_m, lateral_m = _projection_and_lateral(
            center=center,
            angle_deg=angle_deg,
            x=float(geometry.x),
            y=float(geometry.y),
        )
        if projection_m < min_projection_m or lateral_m > lateral_tolerance_m:
            continue
        if best is None or projection_m < best:
            best = projection_m
    return best


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_normalized_id(value) for value in values if _normalized_id(value) is not None}))


@dataclass(frozen=True, kw_only=True)
class Stage3Step3ShadowFrontierConfig:
    enabled: bool = True
    alpha: float = 0.6
    buffer_m: float = 14.0
    fallback_strategy: str = "floor_20m"
    fallback_floor_m: float = 20.0
    fallback_cap_m: float = 50.0
    sidearm_cap_m: float = 50.0
    core_radius_m: float = 18.0
    group_node_buffer_m: float = 9.0
    main_half_width_m: float = 13.0
    side_half_width_m: float = 9.0
    rc_buffer_m: float = 5.0
    local_road_buffer_scale: float = 0.85
    neighbor_lateral_tolerance_m: float = 18.0
    neighbor_min_projection_m: float = 10.0


@dataclass(frozen=True, kw_only=True)
class Stage3Step3ShadowFrontierBranchRecord:
    branch_id: str
    angle_deg: float
    branch_type: str
    is_main_direction: bool
    selected_for_shadow: bool
    drivezone_limit_m: float
    support_projection_m: float | None
    neighbor_projection_m: float | None
    raw_frontier_length_m: float | None
    frontier_length_m: float | None
    fallback_applied: bool = False
    fallback_strategy_used: str | None = None
    sidearm_cap_applied: bool = False
    stop_reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3Step3ShadowFrontierResult:
    template_class: str
    shadow_legal_space_geometry: BaseGeometry
    baseline_legal_space_geometry: BaseGeometry
    baseline_area_m2: float
    shadow_area_m2: float
    shadow_area_ratio: float
    shadow_equals_baseline: bool
    trunk_frontier_defined: bool
    step3_shadow_frontier_unresolved: bool
    unresolved_reason: str | None
    selected_branch_ids: tuple[str, ...] = field(default_factory=tuple)
    stop_records: tuple[str, ...] = field(default_factory=tuple)
    branch_records: tuple[Stage3Step3ShadowFrontierBranchRecord, ...] = field(default_factory=tuple)


def _format_cap_stop_reason(prefix: str, cap_m: float) -> str:
    rounded_cap = round(float(cap_m), 3)
    if abs(rounded_cap - round(rounded_cap)) <= 1e-6:
        cap_token = str(int(round(rounded_cap)))
    else:
        cap_token = str(rounded_cap).replace(".", "p")
    return f"{prefix}_{cap_token}m"


def _resolve_fallback_frontier_length(
    *,
    config: Stage3Step3ShadowFrontierConfig,
    drivezone_limit_m: float,
    neighbor_projection_m: float | None,
) -> tuple[float | None, tuple[str, ...], str | None]:
    strategy = str(config.fallback_strategy or "floor_20m")
    floor_m = max(0.0, float(config.fallback_floor_m))
    cap_m = max(0.0, float(config.fallback_cap_m))

    if strategy == "floor_20m":
        return floor_m, ("fallback_floor_20m",), strategy

    drivezone_cap = None
    if drivezone_limit_m > 0.0 and cap_m > 0.0:
        drivezone_cap = min(drivezone_limit_m, cap_m)
    elif cap_m > 0.0:
        drivezone_cap = cap_m

    if strategy in {"min_drivezone_edge_cap", "min_drivezone_edge_30m", "min_drivezone_edge_50m"}:
        if drivezone_cap is None or drivezone_cap <= 0.0:
            return None, (), strategy
        return drivezone_cap, (_format_cap_stop_reason("fallback_drivezone_cap", drivezone_cap),), strategy

    if strategy in {"neighbor_then_cap", "neighbor_then_30m", "neighbor_then_50m"}:
        if neighbor_projection_m is not None and neighbor_projection_m > 0.0:
            neighbor_cap = neighbor_projection_m * float(config.alpha)
            if drivezone_limit_m > 0.0:
                neighbor_cap = min(neighbor_cap, drivezone_limit_m)
            if neighbor_cap > 0.0:
                return neighbor_cap, ("fallback_neighbor_semantic_alpha",), strategy
        if drivezone_cap is None or drivezone_cap <= 0.0:
            return None, (), strategy
        return drivezone_cap, (
            _format_cap_stop_reason("fallback_neighbor_missing_then_drivezone_cap", drivezone_cap),
        ), strategy

    raise ValueError(f"unsupported fallback_strategy: {strategy!r}")


def build_stage3_step3_shadow_frontier(
    *,
    template_class: str,
    analysis_center: Point,
    drivezone_union: BaseGeometry,
    group_nodes: Sequence[Any],
    local_nodes: Sequence[Any],
    local_roads: Sequence[Any],
    selected_rc_roads: Sequence[Any],
    road_branches: Sequence[Any],
    positive_rc_groups: Iterable[str],
    analysis_member_node_ids: Iterable[str],
    normalized_mainnodeid: str | None,
    config: Stage3Step3ShadowFrontierConfig | None = None,
) -> Stage3Step3ShadowFrontierResult:
    config = config or Stage3Step3ShadowFrontierConfig()
    baseline_geometry = drivezone_union.buffer(0) if drivezone_union is not None else GeometryCollection()
    if (not config.enabled) or baseline_geometry.is_empty:
        baseline_area_m2 = float(baseline_geometry.area) if baseline_geometry is not None else 0.0
        return Stage3Step3ShadowFrontierResult(
            template_class=str(template_class or ""),
            shadow_legal_space_geometry=baseline_geometry,
            baseline_legal_space_geometry=baseline_geometry,
            baseline_area_m2=baseline_area_m2,
            shadow_area_m2=baseline_area_m2,
            shadow_area_ratio=1.0 if baseline_area_m2 > 0.0 else 0.0,
            shadow_equals_baseline=True,
            trunk_frontier_defined=False,
            step3_shadow_frontier_unresolved=not config.enabled,
            unresolved_reason=("shadow_disabled" if not config.enabled else "baseline_drivezone_empty"),
            selected_branch_ids=(),
            stop_records=(),
            branch_records=(),
        )

    positive_rc_group_ids = {str(value) for value in positive_rc_groups if _normalized_id(value) is not None}
    target_group_node_ids = {
        str(value)
        for value in analysis_member_node_ids
        if _normalized_id(value) is not None
    }
    local_roads_by_id = {
        str(road.road_id): road
        for road in local_roads
        if _normalized_id(_attr(road, "road_id")) is not None
    }
    selected_rc_geometries = [
        _attr(road, "geometry")
        for road in selected_rc_roads
        if _attr(road, "geometry") is not None and not _attr(road, "geometry").is_empty
    ]

    keep_geometries: list[BaseGeometry] = []
    stop_records: list[str] = []
    branch_records: list[Stage3Step3ShadowFrontierBranchRecord] = []
    selected_branch_ids: list[str] = []

    core_parts: list[BaseGeometry] = [
        analysis_center.buffer(config.core_radius_m, join_style=1).intersection(baseline_geometry)
    ]
    core_parts.extend(
        _attr(node, "geometry").buffer(config.group_node_buffer_m, join_style=1).intersection(baseline_geometry)
        for node in group_nodes
        if _attr(node, "geometry") is not None and not _attr(node, "geometry").is_empty
    )
    keep_geometries.append(unary_union(core_parts).intersection(baseline_geometry))

    if selected_rc_geometries:
        keep_geometries.append(
            unary_union(
                [
                    geometry.buffer(config.rc_buffer_m, cap_style=2, join_style=2)
                    for geometry in selected_rc_geometries
                ]
            ).intersection(baseline_geometry)
        )

    for branch in road_branches:
        branch_id = _normalized_id(_attr(branch, "branch_id"))
        if branch_id is None:
            continue
        is_main_direction = bool(_attr(branch, "is_main_direction", False))
        conflict_excluded = bool(_attr(branch, "conflict_excluded", False))
        branch_selected = bool(_attr(branch, "selected_for_polygon", False))
        branch_selected_rc = bool(_attr(branch, "selected_rc_group", False))
        matched_positive_groups = bool(
            positive_rc_group_ids.intersection(
                {str(value) for value in (_attr(branch, "rcsdroad_ids", []) or [])}
            )
        )
        selected_for_shadow = (
            not conflict_excluded
            and (is_main_direction or branch_selected or branch_selected_rc or matched_positive_groups)
        )
        drivezone_limit_m = float(
            max(
                float(_attr(branch, "drivezone_support_m", 0.0) or 0.0),
                float(_attr(branch, "road_support_m", 0.0) or 0.0),
                0.0,
            )
        )
        support_projection_m = None
        if branch_selected_rc or matched_positive_groups or is_main_direction:
            support_projection_m = _max_projection_from_geometries(
                geometries=selected_rc_geometries,
                center=analysis_center,
                angle_deg=float(_attr(branch, "angle_deg", 0.0) or 0.0),
                lateral_tolerance_m=max(
                    config.neighbor_lateral_tolerance_m,
                    (config.main_half_width_m if is_main_direction else config.side_half_width_m) * 2.0,
                ),
            )
            rc_support_m = float(_attr(branch, "rc_support_m", 0.0) or 0.0)
            if rc_support_m > 0.0:
                support_projection_m = (
                    rc_support_m
                    if support_projection_m is None
                    else max(support_projection_m, rc_support_m)
                )
        neighbor_projection_m = _nearest_neighbor_projection(
            local_nodes=local_nodes,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            center=analysis_center,
            angle_deg=float(_attr(branch, "angle_deg", 0.0) or 0.0),
            lateral_tolerance_m=config.neighbor_lateral_tolerance_m,
            min_projection_m=config.neighbor_min_projection_m,
        )
        frontier_candidates: list[tuple[float, str]] = []
        if drivezone_limit_m > 0.0:
            frontier_candidates.append((drivezone_limit_m, "drivezone_edge"))
        if support_projection_m is not None and support_projection_m > 0.0:
            frontier_candidates.append((support_projection_m + config.buffer_m, "required_support_plus_buffer"))
        if neighbor_projection_m is not None and neighbor_projection_m > 0.0:
            frontier_candidates.append((neighbor_projection_m * config.alpha, "neighbor_semantic_alpha"))

        raw_frontier_length_m: float | None = None
        stop_reasons: tuple[str, ...] = ()
        frontier_length_m: float | None = None
        fallback_applied = False
        fallback_strategy_used: str | None = None
        sidearm_cap_applied = False
        if frontier_candidates:
            raw_frontier_length_m = min(length_m for length_m, _ in frontier_candidates)
            stop_reasons = tuple(
                reason
                for length_m, reason in frontier_candidates
                if abs(length_m - raw_frontier_length_m) <= 0.75
            )
            frontier_length_m = raw_frontier_length_m
            no_earlier_boundary = support_projection_m is None and neighbor_projection_m is None
            if no_earlier_boundary and is_main_direction and frontier_length_m is not None:
                capped_frontier_length_m, capped_stop_reasons, fallback_strategy_used = _resolve_fallback_frontier_length(
                    config=config,
                    drivezone_limit_m=drivezone_limit_m,
                    neighbor_projection_m=neighbor_projection_m,
                )
                if (
                    capped_frontier_length_m is not None
                    and capped_frontier_length_m > 0.0
                    and capped_frontier_length_m < frontier_length_m - 1e-6
                ):
                    fallback_applied = True
                    frontier_length_m = capped_frontier_length_m
                    stop_reasons = capped_stop_reasons
            if (
                not fallback_applied
                and not is_main_direction
                and no_earlier_boundary
                and frontier_length_m is not None
            ):
                sidearm_cap_m = max(0.0, float(config.sidearm_cap_m))
                capped_frontier_length_m = (
                    min(frontier_length_m, sidearm_cap_m)
                    if sidearm_cap_m > 0.0
                    else frontier_length_m
                )
                if capped_frontier_length_m < frontier_length_m - 1e-6:
                    frontier_length_m = capped_frontier_length_m
                    sidearm_cap_applied = True
                    stop_reasons = ("sidearm_cap_50m",)

        if selected_for_shadow and frontier_length_m is not None and frontier_length_m > 0.0:
            branch_half_width_m = (
                config.main_half_width_m if is_main_direction else config.side_half_width_m
            )
            branch_clip = _branch_cap_clip_geometry(
                analysis_center,
                angle_deg=float(_attr(branch, "angle_deg", 0.0) or 0.0),
                length_m=frontier_length_m,
                half_width_m=branch_half_width_m,
                drivezone_union=baseline_geometry,
                extension_m=max(1.0, branch_half_width_m * 0.25),
                center_radius_m=max(config.core_radius_m, branch_half_width_m + 2.0),
            )
            branch_road_geometries = [
                _attr(local_roads_by_id[road_id], "geometry")
                for road_id in (_attr(branch, "road_ids", []) or [])
                if road_id in local_roads_by_id
                and _attr(local_roads_by_id[road_id], "geometry") is not None
                and not _attr(local_roads_by_id[road_id], "geometry").is_empty
            ]
            if branch_road_geometries:
                branch_road_geometry = unary_union(
                    [
                        geometry.buffer(
                            branch_half_width_m * config.local_road_buffer_scale,
                            cap_style=2,
                            join_style=2,
                        )
                        for geometry in branch_road_geometries
                    ]
                ).intersection(branch_clip)
                branch_clip = unary_union([branch_clip, branch_road_geometry]).intersection(
                    baseline_geometry
                )
            if not branch_clip.is_empty:
                keep_geometries.append(branch_clip)
                selected_branch_ids.append(branch_id)
                stop_records.append(
                    f"{branch_id}:{'|'.join(stop_reasons or ('drivezone_edge',))}:{frontier_length_m:.3f}"
                )

        branch_records.append(
            Stage3Step3ShadowFrontierBranchRecord(
                branch_id=branch_id,
                angle_deg=float(_attr(branch, "angle_deg", 0.0) or 0.0),
                branch_type=str(_attr(branch, "branch_type", "") or ""),
                is_main_direction=is_main_direction,
                selected_for_shadow=selected_for_shadow,
                drivezone_limit_m=drivezone_limit_m,
                support_projection_m=support_projection_m,
                neighbor_projection_m=neighbor_projection_m,
                raw_frontier_length_m=raw_frontier_length_m,
                frontier_length_m=frontier_length_m,
                fallback_applied=fallback_applied,
                fallback_strategy_used=fallback_strategy_used,
                sidearm_cap_applied=sidearm_cap_applied,
                stop_reasons=stop_reasons,
            )
        )

    shadow_geometry = unary_union(
        [geometry for geometry in keep_geometries if geometry is not None and not geometry.is_empty]
    ).intersection(baseline_geometry)
    unresolved_reason: str | None = None
    unresolved = False
    if shadow_geometry.is_empty:
        shadow_geometry = baseline_geometry
        unresolved = True
        unresolved_reason = "shadow_geometry_empty"

    baseline_area_m2 = float(baseline_geometry.area)
    shadow_area_m2 = float(shadow_geometry.area)
    shadow_equals_baseline = abs(shadow_area_m2 - baseline_area_m2) <= 1e-6
    trunk_frontier_defined = any(
        record.is_main_direction and record.frontier_length_m is not None
        for record in branch_records
    )
    if not trunk_frontier_defined and unresolved_reason is None:
        unresolved = True
        unresolved_reason = "main_trunk_frontier_missing"

    return Stage3Step3ShadowFrontierResult(
        template_class=str(template_class or ""),
        shadow_legal_space_geometry=shadow_geometry.buffer(0),
        baseline_legal_space_geometry=baseline_geometry.buffer(0),
        baseline_area_m2=baseline_area_m2,
        shadow_area_m2=shadow_area_m2,
        shadow_area_ratio=(shadow_area_m2 / baseline_area_m2 if baseline_area_m2 > 0.0 else 0.0),
        shadow_equals_baseline=shadow_equals_baseline,
        trunk_frontier_defined=trunk_frontier_defined,
        step3_shadow_frontier_unresolved=unresolved,
        unresolved_reason=unresolved_reason,
        selected_branch_ids=_sorted_unique(selected_branch_ids),
        stop_records=tuple(stop_records),
        branch_records=tuple(branch_records),
    )


def build_stage3_step3_shadow_summary_dict(
    *,
    mainnodeid: str,
    result: Stage3Step3ShadowFrontierResult,
    final_polygon_geometry: BaseGeometry | None = None,
) -> dict[str, Any]:
    final_polygon_area_m2 = (
        float(final_polygon_geometry.area)
        if final_polygon_geometry is not None and not final_polygon_geometry.is_empty
        else 0.0
    )
    final_polygon_coverage_ratio = None
    if final_polygon_area_m2 > 0.0:
        final_polygon_coverage_ratio = float(
            result.shadow_legal_space_geometry.intersection(final_polygon_geometry).area
            / final_polygon_area_m2
        )
    return {
        "mainnodeid": str(mainnodeid),
        "template_class": result.template_class,
        "baseline_area_m2": round(result.baseline_area_m2, 3),
        "shadow_area_m2": round(result.shadow_area_m2, 3),
        "shadow_area_ratio": round(result.shadow_area_ratio, 6),
        "shadow_equals_baseline": result.shadow_equals_baseline,
        "trunk_frontier_defined": result.trunk_frontier_defined,
        "step3_shadow_frontier_unresolved": result.step3_shadow_frontier_unresolved,
        "unresolved_reason": result.unresolved_reason,
        "selected_branch_ids": list(result.selected_branch_ids),
        "stop_records": list(result.stop_records),
        "final_polygon_coverage_ratio": (
            round(final_polygon_coverage_ratio, 6)
            if final_polygon_coverage_ratio is not None
            else None
        ),
        "branch_records": [
            {
                "branch_id": record.branch_id,
                "angle_deg": round(record.angle_deg, 3),
                "branch_type": record.branch_type,
                "is_main_direction": record.is_main_direction,
                "selected_for_shadow": record.selected_for_shadow,
                "drivezone_limit_m": round(record.drivezone_limit_m, 3),
                "support_projection_m": (
                    round(record.support_projection_m, 3)
                    if record.support_projection_m is not None
                    else None
                ),
                "neighbor_projection_m": (
                    round(record.neighbor_projection_m, 3)
                    if record.neighbor_projection_m is not None
                    else None
                ),
                "raw_frontier_length_m": (
                    round(record.raw_frontier_length_m, 3)
                    if record.raw_frontier_length_m is not None
                    else None
                ),
                "frontier_length_m": (
                    round(record.frontier_length_m, 3)
                    if record.frontier_length_m is not None
                    else None
                ),
                "fallback_applied": record.fallback_applied,
                "fallback_strategy_used": record.fallback_strategy_used,
                "sidearm_cap_applied": record.sidearm_cap_applied,
                "stop_reasons": list(record.stop_reasons),
            }
            for record in result.branch_records
        ],
    }


def build_stage3_step3_shadow_frontier_features(
    *,
    mainnodeid: str,
    analysis_center: Point,
    result: Stage3Step3ShadowFrontierResult,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for record in result.branch_records:
        if record.frontier_length_m is None or record.frontier_length_m <= 0.0:
            continue
        features.append(
            {
                "properties": {
                    "mainnodeid": str(mainnodeid),
                    "branch_id": record.branch_id,
                    "branch_type": record.branch_type,
                    "is_main_direction": bool(record.is_main_direction),
                    "selected_for_shadow": bool(record.selected_for_shadow),
                    "frontier_length_m": round(record.frontier_length_m, 3),
                    "fallback_applied": bool(record.fallback_applied),
                    "fallback_strategy_used": record.fallback_strategy_used or "",
                    "sidearm_cap_applied": bool(record.sidearm_cap_applied),
                    "stop_reasons": "|".join(record.stop_reasons),
                },
                "geometry": _branch_ray_geometry(
                    analysis_center,
                    angle_deg=record.angle_deg,
                    length_m=record.frontier_length_m,
                ),
            }
        )
    return features


def build_stage3_step3_shadow_diff_features(
    *,
    mainnodeid: str,
    baseline_geometry: BaseGeometry,
    shadow_geometry: BaseGeometry,
) -> list[dict[str, Any]]:
    overlap_geometry = baseline_geometry.intersection(shadow_geometry).buffer(0)
    baseline_only_geometry = baseline_geometry.difference(shadow_geometry).buffer(0)
    shadow_only_geometry = shadow_geometry.difference(baseline_geometry).buffer(0)
    features: list[dict[str, Any]] = []
    for zone, geometry in (
        ("overlap", overlap_geometry),
        ("baseline_only", baseline_only_geometry),
        ("shadow_only", shadow_only_geometry),
    ):
        if geometry.is_empty:
            continue
        features.append(
            {
                "properties": {
                    "mainnodeid": str(mainnodeid),
                    "zone": zone,
                    "area_m2": round(float(geometry.area), 3),
                },
                "geometry": geometry,
            }
        )
    return features
