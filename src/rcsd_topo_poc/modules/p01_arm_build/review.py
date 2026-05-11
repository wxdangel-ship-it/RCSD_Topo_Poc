from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.models import DatasetBuildResult, LoadedDataset


ROAD_GREY = (160, 160, 160, 255)
INTERNAL_ORANGE = (245, 147, 66, 255)
EXCLUDED_RED = (210, 45, 45, 255)
ADVANCE_LEFT_PURPLE = (126, 63, 178, 255)
ADVANCE_RIGHT_MAGENTA = (214, 39, 135, 255)
TRUNK_DARK = (25, 25, 25, 255)
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
    advance_left_ids = set(result.context.advance_left_turn_road_ids)
    advance_right_ids = set(result.context.advance_right_turn_road_ids)
    trunk_ids = {road_id for arm in result.initial_arms for road_id in arm.trunk_road_ids}
    corrected_trunk_ids = {road_id for correction in result.trunk_corrections for road_id in correction.corrected_trunk_road_ids}
    movement_excluded_ids = {
        road_id for correction in result.trunk_corrections for road_id in correction.movement_excluded_receiving_road_ids
    }
    member_nodes = set(result.context.member_node_ids)

    for road_id in sorted(road_ids):
        road = loaded.roads.get(road_id)
        if road is None:
            continue
        color = ROAD_GREY
        width_px = 2
        if road.road_id in advance_right_ids:
            color = ADVANCE_RIGHT_MAGENTA
            width_px = 5
        elif road.road_id in advance_left_ids:
            color = ADVANCE_LEFT_PURPLE
            width_px = 5
        elif road.road_id in trunk_ids:
            color = TRUNK_DARK
            width_px = 6
        elif road.road_id in corrected_trunk_ids:
            color = TRUNK_DARK
            width_px = 5
        elif road.road_id in internal_ids:
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

    for candidate in result.local_arm_candidates:
        first_road = loaded.roads.get(candidate.source_seed_road_ids[0]) if candidate.source_seed_road_ids else None
        if first_road:
            center = first_road.geometry.interpolate(0.7, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), candidate.local_arm_candidate_id, font=font)

    for road_id, role in seed_roles.items():
        road = loaded.roads.get(road_id)
        if road:
            center = road.geometry.interpolate(0.25, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), role, font=font)

    for road_id in sorted(trunk_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.55, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "TRUNK", font=font)
    for road_id in sorted(corrected_trunk_ids - trunk_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.5, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "Corrected trunk", font=font)
    for road_id in sorted(movement_excluded_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.45, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "AdvL-only recv", font=font, fill=EXCLUDED_RED)

    for road_id in sorted(advance_left_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.62, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "AdvL", font=font, fill=ADVANCE_LEFT_PURPLE)

    relation_by_road = {
        road_id: relation
        for relation in result.advance_right_turn_relations
        for road_id in relation.advance_right_turn_road_ids
    }
    for road_id in sorted(advance_right_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            relation = relation_by_road.get(road_id)
            label = "R7:?"
            if relation and relation.from_arm_id and relation.to_arm_id:
                label = f"R7:{relation.from_arm_id}->{relation.to_arm_id}"
            center = road.geometry.interpolate(0.7, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), label, font=font, fill=ADVANCE_RIGHT_MAGENTA)

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
        f"issue={metrics['issue_count']} R7={metrics['advance_right_turn_road_count']} "
        f"L8={metrics['advance_left_turn_road_count']} mov={metrics['arm_movement_count']} "
        f"corr={metrics['trunk_correction_count']} "
        f"valC={metrics['final_arm_validation_conflict_count']}"
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
            f"R7={metrics['advance_right_turn_road_count']} L8={metrics['advance_left_turn_road_count']}"
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


def _dataset_review_context(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
) -> tuple[list[BaseGeometry], set[str], set[str]]:
    context_node_ids = set(result.context.member_node_ids)
    context_road_ids = set(result.context.internal_road_ids)
    context_road_ids.update(result.context.excluded_right_turn_road_ids)
    context_road_ids.update(result.context.advance_left_turn_road_ids)
    context_road_ids.update(result.context.advance_right_turn_road_ids)
    for arm in result.initial_arms:
        context_road_ids.update(arm.trunk_road_ids)
    for relation in result.advance_right_turn_relations:
        context_road_ids.update(relation.trace_road_ids)
        context_node_ids.update(relation.trace_node_ids[:2])
    for evidence in result.road_movement_evidence:
        context_road_ids.add(evidence.road_id)
        context_road_ids.add(evidence.next_road_id)
    for correction in result.trunk_corrections:
        context_road_ids.update(correction.corrected_trunk_road_ids)
        context_road_ids.update(correction.movement_excluded_receiving_road_ids)
    for validation in result.final_arm_validation:
        for road_ids in validation.relaxed_trace_road_ids_by_initial_arm.values():
            context_road_ids.update(road_ids)
        for node_ids in validation.relaxed_trace_node_ids_by_initial_arm.values():
            context_node_ids.update(node_ids[-1:])

    seed_road_ids = {trace.seed_road_id for trace in result.traces}
    context_road_ids.update(seed_road_ids)
    for candidate in result.local_arm_candidates:
        context_road_ids.update(candidate.local_stub_road_ids)

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
    # review.
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
    arm_trunk_roads = []
    for arm in result.initial_arms:
        for road_id in arm.trunk_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                arm_trunk_roads.append(
                    (
                        road.geometry,
                        {
                            "dataset": result.dataset,
                            "junction_id": result.junction_id,
                            "arm_id": arm.initial_arm_id,
                            "road_id": road_id,
                            "trunk_status": arm.trunk_status,
                        },
                    )
                )
    local_candidate_roads = []
    for candidate in result.local_arm_candidates:
        for road_id in candidate.local_stub_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                local_candidate_roads.append(
                    (
                        road.geometry,
                        {
                            "road_id": road_id,
                            "candidate_id": candidate.local_arm_candidate_id,
                            "source_seeds": ",".join(candidate.source_seed_road_ids),
                            "status": candidate.build_status,
                        },
                    )
                )
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
    road_to_arm = {road_id: arm.initial_arm_id for arm in result.initial_arms for road_id in arm.member_road_ids}
    advance_left_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "dataset": result.dataset,
                "junction_id": result.junction_id,
                "road_id": road_id,
                "arm_id": road_to_arm.get(road_id, ""),
                "formway": loaded.roads[road_id].formway,
                "in_trunk": road_id in {item for arm in result.initial_arms for item in arm.trunk_road_ids},
            },
        )
        for road_id in result.context.advance_left_turn_road_ids
        if road_id in loaded.roads
    ]
    relation_by_road = {
        road_id: relation
        for relation in result.advance_right_turn_relations
        for road_id in relation.advance_right_turn_road_ids
    }
    advance_right_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "dataset": result.dataset,
                "junction_id": result.junction_id,
                "road_id": road_id,
                "formway": loaded.roads[road_id].formway,
                "relation_id": relation_by_road[road_id].relation_id if road_id in relation_by_road else "",
                "trace_status": relation_by_road[road_id].trace_status if road_id in relation_by_road else "target_arm_not_found",
            },
        )
        for road_id in result.context.advance_right_turn_road_ids
        if road_id in loaded.roads
    ]
    advance_right_relations = []
    for relation in result.advance_right_turn_relations:
        for road_id in relation.trace_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                advance_right_relations.append(
                    (
                        road.geometry,
                        {
                            "relation_id": relation.relation_id,
                            "from_arm_id": relation.from_arm_id or "",
                            "to_arm_id": relation.to_arm_id or "",
                            "trace_status": relation.trace_status,
                            "confidence": relation.confidence,
                        },
                    )
                )
    road_centroids = {road_id: road.geometry.centroid for road_id, road in loaded.roads.items()}
    arm_anchor: dict[str, Point] = {}
    for arm in result.final_arms:
        road_ids = list(arm.trunk_road_ids) or list(arm.initial_arm.get("seed_road_ids", []))
        points = [road_centroids[road_id] for road_id in road_ids if road_id in road_centroids]
        if points:
            arm_anchor[arm.final_arm_id] = Point(
                sum(point.x for point in points) / len(points),
                sum(point.y for point in points) / len(points),
            )
    arm_movements = []
    for movement in result.arm_movements:
        from_point = arm_anchor.get(movement.from_arm_id)
        to_point = arm_anchor.get(movement.to_arm_id)
        if from_point and to_point:
            arm_movements.append(
                (
                    LineString([from_point, to_point]),
                    {
                        "movement_id": movement.movement_id,
                        "from_arm_id": movement.from_arm_id,
                        "to_arm_id": movement.to_arm_id,
                        "movement_type": movement.movement_type,
                        "permission": movement.permission_evidence_status,
                    },
                )
            )
    road_movement_evidence = []
    for evidence in result.road_movement_evidence:
        from_point = road_centroids.get(evidence.road_id)
        to_point = road_centroids.get(evidence.next_road_id)
        if from_point and to_point:
            road_movement_evidence.append(
                (
                    LineString([from_point, to_point]),
                    {
                        "evidence_id": evidence.evidence_id,
                        "from_arm_id": evidence.from_arm_id or "",
                        "to_arm_id": evidence.to_arm_id or "",
                        "mapping_status": evidence.mapping_status,
                    },
                )
            )
    straight_receiving_roads = []
    advance_left_receiving_roads = []
    for role in result.arm_receiving_road_roles:
        road = loaded.roads.get(role.road_id)
        if not road:
            continue
        record = (
            road.geometry,
            {
                "target_arm": role.target_arm_id,
                "road_id": role.road_id,
                "roles": ",".join(role.receiving_roles),
                "exclude": role.exclude_from_trunk,
                "reason": role.exclude_reason,
            },
        )
        if role.straight_evidence_count > 0:
            straight_receiving_roads.append(record)
        if role.advance_left_evidence_count > 0:
            advance_left_receiving_roads.append(record)
    trunk_excluded_by_movement_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "target_arm": correction.arm_id,
                "road_id": road_id,
                "reason": "advance_left_receiving_only_not_straight_receiving",
            },
        )
        for correction in result.trunk_corrections
        for road_id in correction.movement_excluded_receiving_road_ids
        if road_id in loaded.roads
    ]
    corrected_trunk_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "arm_id": correction.arm_id,
                "road_id": road_id,
                "status": correction.trunk_correction_status,
                "reason": correction.trunk_correction_reason,
            },
        )
        for correction in result.trunk_corrections
        for road_id in correction.corrected_trunk_road_ids
        if road_id in loaded.roads
    ]
    fallback_point = None
    if result.context.member_node_ids:
        node = loaded.nodes.get(result.context.member_node_ids[0])
        fallback_point = node.geometry if node else None
    final_arm_validation = []
    relaxed_trace_roads = []
    relaxed_trace_terminals = []
    for validation in result.final_arm_validation:
        anchor_point = None
        arm = next((item for item in result.final_arms if item.final_arm_id == validation.final_arm_id), None)
        if arm:
            anchor_ids = list(arm.trunk_road_ids) or list(arm.initial_arm.get("seed_road_ids", []))
            anchor_points = [road_centroids[road_id] for road_id in anchor_ids if road_id in road_centroids]
            if anchor_points:
                anchor_point = Point(
                    sum(point.x for point in anchor_points) / len(anchor_points),
                    sum(point.y for point in anchor_points) / len(anchor_points),
                )
        if anchor_point is None:
            anchor_point = fallback_point or Point(0.0, 0.0)
        final_arm_validation.append(
            (
                anchor_point,
                {
                    "validation_id": validation.validation_id,
                    "final_arm_id": validation.final_arm_id,
                    "validation_status": validation.validation_status,
                    "convergence_status": validation.convergence_status,
                    "source_initial_arm_ids": ",".join(validation.source_initial_arm_ids),
                    "terminal_ids": ",".join(validation.relaxed_trace_terminal_junction_ids),
                    "risk_flags": ",".join(validation.risk_flags),
                },
            )
        )
        for initial_id, road_ids in validation.relaxed_trace_road_ids_by_initial_arm.items():
            for road_id in road_ids:
                road = loaded.roads.get(road_id)
                if road:
                    relaxed_trace_roads.append(
                        (
                            road.geometry,
                            {
                                "validation_id": validation.validation_id,
                                "final_arm_id": validation.final_arm_id,
                                "initial_arm_id": initial_id,
                                "validation_status": validation.validation_status,
                                "road_id": road_id,
                            },
                        )
                    )
        for initial_id, node_ids in validation.relaxed_trace_node_ids_by_initial_arm.items():
            terminal_node_id = node_ids[-1] if node_ids else ""
            node = loaded.nodes.get(terminal_node_id)
            if node:
                relaxed_trace_terminals.append(
                    (
                        node.geometry,
                        {
                            "validation_id": validation.validation_id,
                            "final_arm_id": validation.final_arm_id,
                            "initial_arm_id": initial_id,
                            "validation_status": validation.validation_status,
                            "terminal_node_id": terminal_node_id,
                        },
                    )
                )
    issue_points = []
    special_issue_points = []
    for issue in result.issue_report.issues:
        point = fallback_point
        node_id = issue.get("node_id") or issue.get("missing_node_id")
        if node_id and node_id in loaded.nodes:
            point = loaded.nodes[node_id].geometry
        road_id = issue.get("road_id")
        if road_id and road_id in loaded.roads:
            point = loaded.roads[road_id].geometry.centroid
        if point is None:
            point = Point(0.0, 0.0)
        issue_points.append((point, {"issue_type": issue.get("issue_type", ""), "detail": str(issue)[:180]}))
        if str(issue.get("issue_type", "")).startswith(("formway_", "advance_right_turn_", "trunk_", "final_arm_validation_", "relaxed_trace_")):
            special_issue_points.append((point, {"issue_type": issue.get("issue_type", ""), "detail": str(issue)[:180]}))
    return [
        ("current_junction_nodes", "Point", member_nodes),
        ("current_junction_internal_roads", "LineString", internal_roads),
        ("arm_roads", "LineString", arm_roads),
        ("arm_trunk_roads", "LineString", arm_trunk_roads),
        ("local_arm_candidate_roads", "LineString", local_candidate_roads),
        ("arm_traces", "LineString", traces),
        ("terminal_nodes", "Point", terminal_nodes),
        ("through_decision_nodes", "Point", decision_nodes),
        ("excluded_right_turn_roads", "LineString", excluded_roads),
        ("advance_left_turn_roads", "LineString", advance_left_roads),
        ("advance_right_turn_roads", "LineString", advance_right_roads),
        ("advance_right_turn_relations", "LineString", advance_right_relations),
        ("arm_movements", "LineString", arm_movements),
        ("road_movement_evidence", "LineString", road_movement_evidence),
        ("straight_receiving_roads", "LineString", straight_receiving_roads),
        ("advance_left_receiving_roads", "LineString", advance_left_receiving_roads),
        ("trunk_excluded_by_movement_roads", "LineString", trunk_excluded_by_movement_roads),
        ("corrected_trunk_roads", "LineString", corrected_trunk_roads),
        ("final_arm_validation", "Point", final_arm_validation),
        ("relaxed_trace_roads", "LineString", relaxed_trace_roads),
        ("relaxed_trace_terminals", "Point", relaxed_trace_terminals),
        ("special_formway_issue_points", "Point", special_issue_points),
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
