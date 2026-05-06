from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.models import DatasetBuildResult, LoadedDataset


ROAD_GREY = (160, 160, 160, 255)
INTERNAL_ORANGE = (245, 147, 66, 255)
EXCLUDED_RED = (210, 45, 45, 255)
NODE_BLUE = (35, 95, 190, 255)
TEXT = (20, 20, 20, 255)
ARM_COLORS = [
    (31, 119, 180, 255),
    (44, 160, 44, 255),
    (148, 103, 189, 255),
    (255, 127, 14, 255),
    (23, 190, 207, 255),
    (214, 39, 40, 255),
]


def _geometry_bounds(geometries: list[BaseGeometry]) -> tuple[float, float, float, float]:
    non_empty = [geom for geom in geometries if geom is not None and not geom.is_empty]
    if not non_empty:
        return (-1.0, -1.0, 1.0, 1.0)
    minx = min(geom.bounds[0] for geom in non_empty)
    miny = min(geom.bounds[1] for geom in non_empty)
    maxx = max(geom.bounds[2] for geom in non_empty)
    maxy = max(geom.bounds[3] for geom in non_empty)
    if minx == maxx:
        minx -= 1.0
        maxx += 1.0
    if miny == maxy:
        miny -= 1.0
        maxy += 1.0
    pad_x = (maxx - minx) * 0.12
    pad_y = (maxy - miny) * 0.12
    return (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)


def _projector(
    bounds: tuple[float, float, float, float],
    *,
    left: int,
    top: int,
    width: int,
    height: int,
    margin: int = 24,
):
    minx, miny, maxx, maxy = bounds
    sx = (width - margin * 2) / max(maxx - minx, 1e-9)
    sy = (height - margin * 2) / max(maxy - miny, 1e-9)
    scale = min(sx, sy)
    used_w = (maxx - minx) * scale
    used_h = (maxy - miny) * scale
    x0 = left + (width - used_w) / 2
    y0 = top + (height - used_h) / 2

    def project(x: float, y: float) -> tuple[int, int]:
        px = x0 + (x - minx) * scale
        py = y0 + (maxy - y) * scale
        return int(round(px)), int(round(py))

    return project


def _line_points(geometry: BaseGeometry, project) -> list[tuple[int, int]]:
    if geometry.geom_type == "LineString":
        return [_project_coord(coord, project) for coord in geometry.coords]
    if geometry.geom_type == "MultiLineString":
        points: list[tuple[int, int]] = []
        for part in geometry.geoms:
            points.extend(_project_coord(coord, project) for coord in part.coords)
        return points
    center = geometry.centroid
    return [project(float(center.x), float(center.y))]


def _project_coord(coord, project) -> tuple[int, int]:
    return project(float(coord[0]), float(coord[1]))


def _draw_line(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, project, *, fill, width: int = 3) -> None:
    points = _line_points(geometry, project)
    if len(points) >= 2:
        draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(draw: ImageDraw.ImageDraw, point: BaseGeometry, project, *, fill, radius: int = 5) -> None:
    center = point if point.geom_type == "Point" else point.centroid
    x, y = project(float(center.x), float(center.y))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=(255, 255, 255, 255), width=1)


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, font, fill=TEXT) -> None:
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1), fill=(255, 255, 255, 210))
    draw.text((x, y), text, font=font, fill=fill)


def _arm_color_map(result: DatasetBuildResult) -> dict[str, tuple[int, int, int, int]]:
    colors: dict[str, tuple[int, int, int, int]] = {}
    for idx, arm in enumerate(result.initial_arms):
        color = ARM_COLORS[idx % len(ARM_COLORS)]
        for road_id in arm.member_road_ids:
            colors[road_id] = color
    return colors


def _role_by_seed(result: DatasetBuildResult) -> dict[str, str]:
    roles: dict[str, str] = {}
    for trace in result.traces:
        roles[trace.seed_road_id] = {"inbound": "IN", "outbound": "OUT", "bidirectional": "BI"}.get(trace.seed_role, trace.seed_role)
    return roles


def _draw_dataset_panel(
    draw: ImageDraw.ImageDraw,
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    *,
    bounds: tuple[float, float, float, float],
    road_ids: set[str],
    node_ids: set[str],
    panel: tuple[int, int, int, int],
    title: str,
    font,
) -> None:
    left, top, width, height = panel
    project = _projector(bounds, left=left, top=top + 28, width=width, height=height - 28)
    draw.rectangle((left, top, left + width - 1, top + height - 1), outline=(210, 210, 210, 255), width=1)
    _text(draw, (left + 8, top + 6), title, font=font)

    arm_colors = _arm_color_map(result)
    seed_roles = _role_by_seed(result)
    internal_ids = set(result.context.internal_road_ids)
    excluded_ids = set(result.context.excluded_right_turn_road_ids)
    member_nodes = set(result.context.member_node_ids)

    for road_id in sorted(road_ids):
        road = loaded.roads.get(road_id)
        if road is None:
            continue
        color = ROAD_GREY
        width_px = 2
        if road.road_id in internal_ids:
            color = INTERNAL_ORANGE
            width_px = 5
        elif road.road_id in excluded_ids:
            color = EXCLUDED_RED
            width_px = 4
        elif road.road_id in arm_colors:
            color = arm_colors[road.road_id]
            width_px = 4
        _draw_line(draw, road.geometry, project, fill=color, width=width_px)

    for node_id in sorted(node_ids & member_nodes):
        node = loaded.nodes.get(node_id)
        if node:
            _draw_point(draw, node.geometry, project, fill=NODE_BLUE, radius=6)
            center = node.geometry.centroid
            _text(draw, project(float(center.x), float(center.y)), "J", font=font)

    for arm in result.initial_arms:
        first_road = loaded.roads.get(arm.seed_road_ids[0]) if arm.seed_road_ids else None
        if first_road:
            center = first_road.geometry.interpolate(0.5, normalized=True)
            _text(
                draw,
                project(float(center.x), float(center.y)),
                f"{arm.initial_arm_id} {arm.terminal_type}",
                font=font,
            )

    for road_id, role in seed_roles.items():
        road = loaded.roads.get(road_id)
        if road:
            center = road.geometry.interpolate(0.25, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), role, font=font)

    decision_labels = {
        "simple_through": "S",
        "t_mainline_through": "T",
        "t_side_terminal": "TS",
        "ambiguous_boundary": "?",
        "semantic_boundary": "X",
        "patch_boundary": "P",
        "dead_end": "D",
        "loop_to_current_junction": "L",
    }
    for decision in result.decisions:
        for node_id in decision.member_node_ids[:1]:
            if node_id not in node_ids:
                continue
            node = loaded.nodes.get(node_id)
            if node:
                center = node.geometry.centroid
                _text(draw, project(float(center.x), float(center.y)), decision_labels.get(decision.status, decision.status), font=font)


def render_dataset_review_png(path: Path, loaded: LoadedDataset, result: DatasetBuildResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 760
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    geometries, road_ids, node_ids = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)
    metrics = result.metrics
    title = (
        f"{result.dataset} junction={result.junction_id} "
        f"arms={metrics['initial_arm_count']} stable={metrics['stable_arm_count']} "
        f"issue={metrics['issue_count']} excluded_rt={metrics['excluded_right_turn_road_count']}"
    )
    _draw_dataset_panel(
        draw,
        loaded,
        result,
        bounds=bounds,
        road_ids=road_ids,
        node_ids=node_ids,
        panel=(0, 0, width, height),
        title=title,
        font=font,
    )
    image.convert("RGB").save(path)


def render_compare_png(
    path: Path,
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    panel_w, height = 520, 600
    image = Image.new("RGBA", (panel_w * 3, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    contexts: dict[str, tuple[list[BaseGeometry], set[str], set[str]]] = {}
    geometries: list[BaseGeometry] = []
    for dataset in ("SWSD", "RCSD", "FRCSD"):
        contexts[dataset] = _dataset_review_context(loaded_by_dataset[dataset], result_by_dataset[dataset])
        geometries.extend(contexts[dataset][0])
    bounds = _geometry_bounds(geometries)
    for idx, dataset in enumerate(("SWSD", "RCSD", "FRCSD")):
        loaded = loaded_by_dataset[dataset]
        result = result_by_dataset[dataset]
        metrics = result.metrics
        title = (
            f"{dataset} arms={metrics['initial_arm_count']} stable={metrics['stable_arm_count']} "
            f"partial={metrics['partial_arm_count']} issue={metrics['issue_count']} "
            f"excluded_rt={metrics['excluded_right_turn_road_count']}"
        )
        _draw_dataset_panel(
            draw,
            loaded,
            result,
            bounds=bounds,
            road_ids=contexts[dataset][1],
            node_ids=contexts[dataset][2],
            panel=(idx * panel_w, 0, panel_w, height),
            title=title,
            font=font,
        )
    image.convert("RGB").save(path)


def render_trace_review_png(path: Path, loaded: LoadedDataset, result: DatasetBuildResult, trace_id: str) -> None:
    trace = next((item for item in result.traces if item.trace_id == trace_id), None)
    if trace is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 900, 620
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    geometries, context_road_ids, context_node_ids = _trace_review_context(loaded, result, trace_id)
    bounds = _geometry_bounds(geometries)
    project = _projector(bounds, left=0, top=36, width=width, height=height - 36)
    _text(draw, (8, 8), f"{result.dataset} {trace.trace_id} stop={trace.stop_type}", font=font)
    excluded_ids = set(result.context.excluded_right_turn_road_ids)
    for road_id in sorted(context_road_ids):
        road = loaded.roads.get(road_id)
        if road is None:
            continue
        color = (185, 185, 185, 180)
        width_px = 2
        if road.road_id in trace.traced_road_ids:
            color = (214, 39, 40, 255)
            width_px = 5
        elif road.road_id in excluded_ids:
            color = EXCLUDED_RED
            width_px = 4
        _draw_line(draw, road.geometry, project, fill=color, width=width_px)
    for node_id in sorted(context_node_ids & set(result.context.member_node_ids)):
        node = loaded.nodes.get(node_id)
        if node:
            _draw_point(draw, node.geometry, project, fill=NODE_BLUE, radius=6)
    for decision in result.decisions:
        if decision.trace_id != trace.trace_id:
            continue
        for node_id in decision.member_node_ids[:1]:
            node = loaded.nodes.get(node_id)
            if node:
                _draw_point(draw, node.geometry, project, fill=(255, 200, 0, 255), radius=7)
                center = node.geometry.centroid
                _text(draw, project(float(center.x), float(center.y)), decision.status, font=font)
    image.convert("RGB").save(path)


def _trace_review_context(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    trace_id: str,
) -> tuple[list[BaseGeometry], set[str], set[str]]:
    trace = next((item for item in result.traces if item.trace_id == trace_id), None)
    if trace is None:
        return [], set(), set()

    context_node_ids = set(result.context.member_node_ids)
    context_node_ids.update(trace.traced_node_ids)
    context_road_ids = set(trace.traced_road_ids)
    context_road_ids.update(result.context.excluded_right_turn_road_ids)

    for decision in result.decisions:
        if decision.trace_id != trace.trace_id:
            continue
        context_node_ids.update(decision.member_node_ids)
        context_road_ids.update(decision.incident_road_ids)

    # Add one-hop road context around the current trace nodes. This keeps the
    # trace review focused on the junction area without losing adjacent branch
    # evidence that can explain a boundary decision.
    for road in loaded.roads.values():
        if road.snodeid in context_node_ids or road.enodeid in context_node_ids:
            context_road_ids.add(road.road_id)

    geometries: list[BaseGeometry] = []
    for road_id in sorted(context_road_ids):
        road = loaded.roads.get(road_id)
        if road:
            geometries.append(road.geometry)
            context_node_ids.add(road.snodeid)
            context_node_ids.add(road.enodeid)
    for node_id in sorted(context_node_ids):
        node = loaded.nodes.get(node_id)
        if node:
            geometries.append(node.geometry)
    return geometries, context_road_ids, context_node_ids


def _dataset_review_context(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
) -> tuple[list[BaseGeometry], set[str], set[str]]:
    context_node_ids = set(result.context.member_node_ids)
    context_road_ids = set(result.context.internal_road_ids)
    context_road_ids.update(result.context.excluded_right_turn_road_ids)

    seed_road_ids = {trace.seed_road_id for trace in result.traces}
    context_road_ids.update(seed_road_ids)

    for trace in result.traces:
        context_node_ids.update(trace.traced_node_ids[:1])

    first_decisions: dict[str, Any] = {}
    for decision in result.decisions:
        first_decisions.setdefault(decision.trace_id, decision)
    for decision in first_decisions.values():
        context_node_ids.update(decision.member_node_ids)
        context_road_ids.update(decision.incident_road_ids)

    # Dataset review should explain the built arms, not render the whole source
    # layer. Keep this overview near the current junction: seed roads, one
    # continuation hop, and the first audited decision are enough for fast visual
    # review, while full trace details remain in trace_review images.
    for road in loaded.roads.values():
        if road.snodeid in context_node_ids or road.enodeid in context_node_ids:
            context_road_ids.add(road.road_id)

    geometries: list[BaseGeometry] = []
    for road_id in sorted(context_road_ids):
        road = loaded.roads.get(road_id)
        if road:
            geometries.append(road.geometry)
            context_node_ids.add(road.snodeid)
            context_node_ids.add(road.enodeid)
    for node_id in sorted(context_node_ids):
        node = loaded.nodes.get(node_id)
        if node:
            geometries.append(node.geometry)
    return geometries, context_road_ids, context_node_ids


def build_dataset_review_layers(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
) -> list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]]:
    member_nodes = [
        (loaded.nodes[node_id].geometry, {"node_id": node_id, "dataset": result.dataset})
        for node_id in result.context.member_node_ids
        if node_id in loaded.nodes
    ]
    internal_roads = [
        (loaded.roads[road_id].geometry, {"road_id": road_id, "dataset": result.dataset})
        for road_id in result.context.internal_road_ids
        if road_id in loaded.roads
    ]
    arm_roads = []
    for arm in result.initial_arms:
        for road_id in arm.member_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                arm_roads.append((road.geometry, {"road_id": road_id, "arm_id": arm.initial_arm_id, "terminal_type": arm.terminal_type}))
    traces = []
    for trace in result.traces:
        for road_id in trace.traced_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                traces.append((road.geometry, {"trace_id": trace.trace_id, "road_id": road_id, "stop_type": trace.stop_type}))
    terminal_nodes = []
    for arm in result.initial_arms:
        for node_id in arm.terminal_member_node_ids:
            node = loaded.nodes.get(node_id)
            if node:
                terminal_nodes.append((node.geometry, {"arm_id": arm.initial_arm_id, "node_id": node_id, "terminal_type": arm.terminal_type}))
    decision_nodes = []
    for decision in result.decisions:
        for node_id in decision.member_node_ids[:1]:
            node = loaded.nodes.get(node_id)
            if node:
                decision_nodes.append((node.geometry, {"trace_id": decision.trace_id, "status": decision.status, "node_group_id": decision.node_group_id}))
    excluded_roads = [
        (loaded.roads[road_id].geometry, {"road_id": road_id, "dataset": result.dataset, "reason": "right_turn"})
        for road_id in result.context.excluded_right_turn_road_ids
        if road_id in loaded.roads
    ]
    issue_points = []
    fallback_point = None
    if result.context.member_node_ids:
        node = loaded.nodes.get(result.context.member_node_ids[0])
        fallback_point = node.geometry if node else None
    for issue in result.issue_report.issues:
        point = fallback_point
        node_id = issue.get("node_id") or issue.get("missing_node_id")
        if node_id and node_id in loaded.nodes:
            point = loaded.nodes[node_id].geometry
        if point is None:
            point = Point(0.0, 0.0)
        issue_points.append((point, {"issue_type": issue.get("issue_type", ""), "detail": str(issue)[:180]}))
    return [
        ("current_junction_nodes", "Point", member_nodes),
        ("current_junction_internal_roads", "LineString", internal_roads),
        ("arm_roads", "LineString", arm_roads),
        ("arm_traces", "LineString", traces),
        ("terminal_nodes", "Point", terminal_nodes),
        ("through_decision_nodes", "Point", decision_nodes),
        ("excluded_right_turn_roads", "LineString", excluded_roads),
        ("issue_points", "Point", issue_points),
    ]


def build_compare_layers(
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
) -> list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]]:
    records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    for dataset, result in result_by_dataset.items():
        loaded = loaded_by_dataset[dataset]
        for arm in result.initial_arms:
            for road_id in arm.member_road_ids:
                road = loaded.roads.get(road_id)
                if road:
                    records.append((road.geometry, {"dataset": dataset, "arm_id": arm.initial_arm_id, "road_id": road_id, "status": arm.build_status}))
    return [("compare_arm_roads", "LineString", records)]
