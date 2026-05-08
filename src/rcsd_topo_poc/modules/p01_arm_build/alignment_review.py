from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

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
    bounds_by_dataset = {
        dataset: _geometry_bounds(_profiles_review_geometries(result.profiles_by_dataset[dataset], loaded_by_dataset.get(dataset)))
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
) -> None:
    left, top, width, height = panel
    draw.rectangle((left, top, left + width - 1, top + height - 1), outline=(210, 210, 210, 255), width=1)
    _text(draw, (left + 8, top + 8), title, font=font)
    project = _projector(bounds, left=left, top=top + 28, width=width, height=height - 28)
    group_color = _group_color_map(result, dataset)
    for profile in profiles:
        color = group_color.get(profile.arm_id, GREY)
        for geom in _profile_review_road_geometries(profile, loaded):
            _draw_line(draw, geom, project, fill=color, width=4)
        point = _profile_review_point(profile, loaded)
        if point is not None:
            _text(draw, project(float(point.x), float(point.y)), profile.arm_id, font=font)


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
    road_ids = tuple(dict.fromkeys(profile.local_stub_road_ids + profile.seed_road_ids))
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
