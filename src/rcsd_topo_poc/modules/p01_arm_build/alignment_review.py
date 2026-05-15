from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import clip_by_rect

from rcsd_topo_poc.modules.p01_arm_build.alignment_models import ArmProfile, CaseAlignmentResult
from rcsd_topo_poc.modules.p01_arm_build.models import LoadedDataset
from rcsd_topo_poc.modules.p01_arm_build.review import _draw_line, _geometry_bounds, _projector, _text


COLORS = [
    (31, 119, 180, 255),
    (44, 160, 44, 255),
    (148, 103, 189, 255),
    (255, 127, 14, 255),
    (23, 190, 207, 255),
    (214, 39, 40, 255),
]
GREY = (170, 170, 170, 180)
TEXT = (20, 20, 20, 255)
COMPARE_LOCAL_VIEW_HALF_WIDTH = 200.0


def render_source_alignment_png(
    path: Path,
    *,
    source_dataset: str,
    loaded_by_dataset: dict[str, LoadedDataset],
    result: CaseAlignmentResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1160, 720
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    source_profiles = result.profiles_by_dataset[source_dataset]
    f_profiles = result.profiles_by_dataset["FRCSD"]
    source_bounds = _geometry_bounds(_profiles_review_geometries(source_profiles, loaded_by_dataset.get(source_dataset)))
    f_bounds = _geometry_bounds(_profiles_review_geometries(f_profiles, loaded_by_dataset.get("FRCSD")))
    _draw_profile_panel(
        draw,
        bounds=source_bounds,
        panel=(0, 0, width // 2, height),
        title=f"{source_dataset} alignment",
        dataset=source_dataset,
        profiles=source_profiles,
        loaded=loaded_by_dataset.get(source_dataset),
        result=result,
        font=font,
    )
    _draw_profile_panel(
        draw,
        bounds=f_bounds,
        panel=(width // 2, 0, width // 2, height),
        title="FRCSD target",
        dataset="FRCSD",
        profiles=f_profiles,
        loaded=loaded_by_dataset.get("FRCSD"),
        result=result,
        font=font,
    )
    y = 28
    for alignment in result.raw_alignments_by_source[source_dataset]:
        text = f"{alignment.f_arm_id} <-> {'/'.join(alignment.source_arm_ids) or 'missing'} {alignment.match_type} {alignment.confidence}"
        _text(draw, (12, y), text, font=font)
        y += 16
    image.convert("RGB").save(path)


def render_compare_alignment_png(
    path: Path,
    *,
    loaded_by_dataset: dict[str, LoadedDataset],
    result: CaseAlignmentResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    panel_w, height = 520, 660
    image = Image.new("RGBA", (panel_w * 3, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    panel_h = height - 24
    bounds_by_dataset = {
        dataset: _compare_local_bounds(
            result.profiles_by_dataset[dataset],
            loaded_by_dataset.get(dataset),
            panel_width=panel_w,
            panel_height=panel_h - 28,
        )
        for dataset in ("SWSD", "FRCSD", "RCSD")
    }
    summary = (
        f"FRCSD logical groups={result.metrics['logical_arm_group_count']} "
        f"acceptable={result.metrics['acceptable_logical_arm_group_count']} "
        f"source_extra={result.metrics['source_extra_count']}"
    )
    _text(draw, (8, 6), summary, font=font)
    for idx, dataset in enumerate(("SWSD", "FRCSD", "RCSD")):
        _draw_profile_panel(
            draw,
            bounds=bounds_by_dataset[dataset],
            panel=(idx * panel_w, 24, panel_w, height - 24),
            title=dataset,
            dataset=dataset,
            profiles=result.profiles_by_dataset[dataset],
            loaded=loaded_by_dataset.get(dataset),
            result=result,
            font=font,
            show_junction_center=True,
        )
    image.convert("RGB").save(path)


def build_alignment_layers(
    result: CaseAlignmentResult,
    loaded_by_dataset: dict[str, LoadedDataset],
) -> list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]]:
    logical_records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    for group in result.logical_arm_groups:
        for dataset, arm_ids in (
            ("FRCSD", group.frcsd_arm_ids),
            ("SWSD", group.swsd_arm_ids),
            ("RCSD", group.rcsd_arm_ids),
        ):
            for arm_id in arm_ids:
                profile = _profile_by_id(result, dataset, arm_id)
                logical_records.extend(
                    (
                        geom,
                        {
                            "dataset": dataset,
                            "arm_id": arm_id,
                            "logical_group_id": group.logical_arm_group_id,
                            "group_status": group.group_status,
                            "priority": group.review_priority,
                        },
                    )
                    for geom in _profile_road_geometries(profile, loaded_by_dataset.get(dataset))
                )

    raw_edges = _alignment_edge_records(result, loaded_by_dataset, selected_only=True)
    candidate_edges = _alignment_edge_records(result, loaded_by_dataset, selected_only=False)
    corridor_records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    for dataset, profiles in result.profiles_by_dataset.items():
        loaded = loaded_by_dataset.get(dataset)
        if loaded is None:
            continue
        for profile in profiles:
            for road_id in profile.corridor_support_road_ids:
                road = loaded.roads.get(road_id)
                if road is not None and road.geometry is not None and not road.geometry.is_empty:
                    corridor_records.append(
                        (
                            road.geometry,
                            {
                                "dataset": dataset,
                                "arm_id": profile.arm_id,
                                "road_id": road_id,
                                "corridor_status": profile.corridor_status,
                                "corridor_angle_deg": profile.corridor_angle_deg,
                            },
                        )
                    )
    source_extra_records = []
    for extra in result.source_extra_arms:
        profile = _profile_by_id(result, extra.dataset, extra.source_arm_id)
        for geom in _profile_road_geometries(profile, loaded_by_dataset.get(extra.dataset)):
            source_extra_records.append(
                (
                    geom,
                    {
                        "dataset": extra.dataset,
                        "arm_id": extra.source_arm_id,
                        "reason": extra.reason,
                        "priority": extra.review_priority,
                    },
                )
            )
    feedback_points = []
    for item in result.feedback:
        for arm_id in item.source_arm_ids:
            profile = _profile_by_id(result, item.dataset, arm_id)
            point = _profile_point(profile, loaded_by_dataset.get(item.dataset))
            if point is not None:
                feedback_points.append(
                    (
                        point,
                        {
                            "dataset": item.dataset,
                            "feedback_type": item.feedback_type,
                            "arm_ids": ",".join(item.source_arm_ids),
                            "priority": item.review_priority,
                        },
                    )
                )
    issue_points = []
    for group in result.logical_arm_groups:
        if group.review_priority not in {"P0", "P1"}:
            continue
        profile = _profile_by_id(result, "FRCSD", group.frcsd_arm_ids[0])
        point = _profile_point(profile, loaded_by_dataset.get("FRCSD"))
        if point is not None:
            issue_points.append(
                (
                    point,
                    {
                        "logical_group_id": group.logical_arm_group_id,
                        "group_status": group.group_status,
                        "priority": group.review_priority,
                    },
                )
            )

    return [
        ("logical_arm_groups", "LineString", logical_records),
        ("arm_corridor_support_roads", "LineString", corridor_records),
        ("raw_alignment_edges", "LineString", raw_edges),
        ("candidate_edges", "LineString", candidate_edges),
        ("source_extra_arms", "LineString", source_extra_records),
        ("feedback_points", "Point", feedback_points),
        ("issue_points", "Point", issue_points),
    ]


def _draw_profile_panel(
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[float, float, float, float],
    panel: tuple[int, int, int, int],
    title: str,
    dataset: str,
    profiles: tuple[ArmProfile, ...],
    loaded: LoadedDataset | None,
    result: CaseAlignmentResult,
    font,
    show_junction_center: bool = False,
) -> None:
    left, top, width, height = panel
    draw.rectangle((left, top, left + width - 1, top + height - 1), outline=(210, 210, 210, 255), width=1)
    _text(draw, (left + 8, top + 8), title, font=font)
    project = _projector(bounds, left=left, top=top + 28, width=width, height=height - 28)
    if show_junction_center:
        center = _junction_center(profiles, loaded)
        if center is not None:
            cx, cy = project(float(center.x), float(center.y))
            draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(20, 20, 20, 230), outline=(255, 255, 255, 255))
    group_color = _group_color_map(result, dataset)
    for profile in profiles:
        color = group_color.get(profile.arm_id, GREY)
        for geom in _profile_review_road_geometries(profile, loaded):
            _draw_line_in_bounds(draw, geom, bounds, project, fill=color, width=4)
        point = _profile_review_point(profile, loaded)
        if point is not None and _point_in_bounds(point, bounds):
            _text(draw, _panel_text_xy(project(float(point.x), float(point.y)), panel), profile.arm_id, font=font)


def _draw_line_in_bounds(
    draw: ImageDraw.ImageDraw,
    geometry: BaseGeometry,
    bounds: tuple[float, float, float, float],
    project,
    *,
    fill,
    width: int,
) -> None:
    if geometry is None or geometry.is_empty:
        return
    minx, miny, maxx, maxy = bounds
    clipped = clip_by_rect(geometry, minx, miny, maxx, maxy)
    if clipped.is_empty:
        return
    if clipped.geom_type == "LineString":
        _draw_line(draw, clipped, project, fill=fill, width=width)
        return
    if clipped.geom_type == "MultiLineString":
        for part in clipped.geoms:
            _draw_line(draw, part, project, fill=fill, width=width)
        return
    if hasattr(clipped, "geoms"):
        for part in clipped.geoms:
            _draw_line_in_bounds(draw, part, bounds, project, fill=fill, width=width)


def _point_in_bounds(point: Point, bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    return minx <= float(point.x) <= maxx and miny <= float(point.y) <= maxy


def _panel_text_xy(xy: tuple[int, int], panel: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, width, height = panel
    x, y = xy
    return min(max(x, left + 3), left + width - 42), min(max(y, top + 22), top + height - 18)


def _compare_local_bounds(
    profiles: tuple[ArmProfile, ...],
    loaded: LoadedDataset | None,
    *,
    panel_width: int,
    panel_height: int,
) -> tuple[float, float, float, float]:
    center = _junction_center(profiles, loaded) or _profiles_center(profiles, loaded)
    if center is None:
        return _geometry_bounds(_profiles_review_geometries(profiles, loaded))
    half_width, half_height = _local_view_half_spans(
        center,
        loaded,
        panel_width=panel_width,
        panel_height=panel_height,
    )
    return (
        float(center.x) - half_width,
        float(center.y) - half_height,
        float(center.x) + half_width,
        float(center.y) + half_height,
    )


def _local_view_half_spans(
    center: Point,
    loaded: LoadedDataset | None,
    *,
    panel_width: int,
    panel_height: int,
) -> tuple[float, float]:
    half_width_m = COMPARE_LOCAL_VIEW_HALF_WIDTH
    half_height_m = half_width_m * max(panel_height, 1) / max(panel_width, 1)
    if not _uses_geographic_coordinates(center, loaded):
        return half_width_m, half_height_m
    lat_rad = math.radians(float(center.y))
    meters_per_degree_x = max(111_320.0 * abs(math.cos(lat_rad)), 1.0)
    meters_per_degree_y = 110_540.0
    return half_width_m / meters_per_degree_x, half_height_m / meters_per_degree_y


def _uses_geographic_coordinates(center: Point, loaded: LoadedDataset | None) -> bool:
    crs_text = ""
    wkt_text = ""
    if loaded is not None:
        crs_text = f"{loaded.node_layer.crs or ''} {loaded.road_layer.crs or ''}"
        wkt_text = f"{loaded.node_layer.crs_wkt or ''} {loaded.road_layer.crs_wkt or ''}".lstrip()
    if "4326" in crs_text or "CRS84" in crs_text.upper():
        return True
    if wkt_text.upper().startswith("GEOGCRS") and ("4326" in wkt_text or "CRS84" in wkt_text.upper()):
        return True
    return -180.0 <= float(center.x) <= 180.0 and -90.0 <= float(center.y) <= 90.0


def _junction_center(profiles: tuple[ArmProfile, ...], loaded: LoadedDataset | None) -> Point | None:
    if loaded is None or not profiles:
        return None
    junction_id = profiles[0].current_junction_id
    candidate_ids = [junction_id]
    if loaded.dataset == "RCSD" and junction_id.startswith("R") and len(junction_id) > 1:
        candidate_ids.append(junction_id[1:])
    if loaded.dataset == "FRCSD" and junction_id.startswith("F") and len(junction_id) > 1:
        candidate_ids.append(junction_id[1:])
    for candidate_id in dict.fromkeys(candidate_ids):
        if candidate_id in loaded.nodes:
            group_id = _node_group_id(loaded.nodes[candidate_id])
            return _nodes_centroid(
                node
                for node in loaded.nodes.values()
                if _node_group_id(node) == group_id
            )
        matching_nodes = [node for node in loaded.nodes.values() if _node_group_id(node) == candidate_id]
        if matching_nodes:
            return _nodes_centroid(iter(matching_nodes))
    return None


def _profiles_center(profiles: tuple[ArmProfile, ...], loaded: LoadedDataset | None) -> Point | None:
    points = [point for profile in profiles if (point := _profile_point(profile, loaded)) is not None]
    if not points:
        return None
    return Point(
        sum(float(point.x) for point in points) / len(points),
        sum(float(point.y) for point in points) / len(points),
    )


def _node_group_id(node: Any) -> str:
    mainnodeid = str(node.mainnodeid or "").strip()
    if not mainnodeid or mainnodeid.lower() in {"0", "0.0", "none", "null", "nan"}:
        return str(node.node_id)
    return mainnodeid[:-2] if mainnodeid.endswith(".0") else mainnodeid


def _nodes_centroid(nodes: Any) -> Point | None:
    items = [node for node in nodes if node.geometry is not None and not node.geometry.is_empty]
    if not items:
        return None
    return Point(
        sum(float(node.geometry.x) for node in items) / len(items),
        sum(float(node.geometry.y) for node in items) / len(items),
    )


def _group_color_map(result: CaseAlignmentResult, dataset: str) -> dict[str, tuple[int, int, int, int]]:
    colors: dict[str, tuple[int, int, int, int]] = {}
    for index, group in enumerate(result.logical_arm_groups):
        color = COLORS[index % len(COLORS)]
        arm_ids = {
            "FRCSD": group.frcsd_arm_ids,
            "SWSD": group.swsd_arm_ids,
            "RCSD": group.rcsd_arm_ids,
        }[dataset]
        for arm_id in arm_ids:
            colors[arm_id] = color
    return colors


def _profiles_review_geometries(profiles: tuple[ArmProfile, ...], loaded: LoadedDataset | None) -> list[BaseGeometry]:
    geometries: list[BaseGeometry] = []
    for profile in profiles:
        geometries.extend(_profile_review_road_geometries(profile, loaded))
    return geometries


def _profile_review_road_geometries(profile: ArmProfile, loaded: LoadedDataset | None) -> list[BaseGeometry]:
    if loaded is None:
        return []
    road_ids = tuple(dict.fromkeys(profile.corridor_support_road_ids + profile.local_stub_road_ids + profile.seed_road_ids))
    if profile.corridor_status == "seed_only":
        road_ids = tuple(dict.fromkeys(road_ids + profile.member_road_ids))
    if not road_ids:
        road_ids = tuple(profile.member_road_ids[:2])
    geometries = []
    for road_id in road_ids:
        road = loaded.roads.get(road_id)
        if road is not None and road.geometry is not None and not road.geometry.is_empty:
            geometries.append(road.geometry)
    return geometries


def _profile_road_geometries(profile: ArmProfile, loaded: LoadedDataset | None) -> list[BaseGeometry]:
    if loaded is None:
        return []
    geometries = []
    for road_id in profile.member_road_ids or profile.seed_road_ids:
        road = loaded.roads.get(road_id)
        if road is not None and road.geometry is not None and not road.geometry.is_empty:
            geometries.append(road.geometry)
    return geometries


def _profile_review_point(profile: ArmProfile, loaded: LoadedDataset | None) -> Point | None:
    geometries = _profile_review_road_geometries(profile, loaded)
    if geometries:
        x = sum(float(geom.centroid.x) for geom in geometries) / len(geometries)
        y = sum(float(geom.centroid.y) for geom in geometries) / len(geometries)
        return Point(x, y)
    return _profile_point(profile, loaded)


def _profile_point(profile: ArmProfile, loaded: LoadedDataset | None) -> Point | None:
    geometries = _profile_road_geometries(profile, loaded)
    if geometries:
        x = sum(float(geom.centroid.x) for geom in geometries) / len(geometries)
        y = sum(float(geom.centroid.y) for geom in geometries) / len(geometries)
        return Point(x, y)
    centroid = profile.geometry_summary.get("centroid_xy")
    if centroid:
        return Point(float(centroid[0]), float(centroid[1]))
    return None


def _profile_by_id(result: CaseAlignmentResult, dataset: str, arm_id: str) -> ArmProfile:
    for profile in result.profiles_by_dataset[dataset]:
        if profile.arm_id == arm_id:
            return profile
    raise KeyError(f"Missing profile {dataset}/{arm_id}")


def _alignment_edge_records(
    result: CaseAlignmentResult,
    loaded_by_dataset: dict[str, LoadedDataset],
    *,
    selected_only: bool,
) -> list[tuple[BaseGeometry, dict[str, Any]]]:
    records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    for candidate in result.candidates:
        if selected_only and not candidate.selected:
            continue
        left = _profile_by_id(result, candidate.left_dataset, candidate.left_arm_id)
        right = _profile_by_id(result, candidate.right_dataset, candidate.right_arm_id)
        left_point = _profile_point(left, loaded_by_dataset.get(candidate.left_dataset))
        right_point = _profile_point(right, loaded_by_dataset.get(candidate.right_dataset))
        if left_point is None or right_point is None:
            continue
        records.append(
            (
                LineString([left_point, right_point]),
                {
                    "candidate_id": candidate.candidate_id,
                    "left": f"{candidate.left_dataset}:{candidate.left_arm_id}",
                    "right": f"{candidate.right_dataset}:{candidate.right_arm_id}",
                    "score": candidate.score,
                    "confidence": candidate.confidence,
                    "selected": str(candidate.selected),
                },
            )
        )
    return records
