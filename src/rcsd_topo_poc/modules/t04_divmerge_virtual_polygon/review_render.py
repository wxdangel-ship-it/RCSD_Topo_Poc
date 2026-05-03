from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .polygon_assembly import T04Step6Result
from .rcsd_alignment import RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES
from .review_audit import _candidate_entry_reference_zone, build_case_review_audit
from .surface_scenario import (
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
    SECTION_REFERENCE_SWSD,
)
from .support_domain import T04Step5CaseResult


CANVAS_WIDTH = 1720
CANVAS_HEIGHT = 1040
MAP_LEFT = 20
MAP_TOP = 20
MAP_SIZE = 980
PANEL_LEFT = 1040
PANEL_TOP = 20
BACKGROUND = (249, 246, 238, 255)
DRIVEZONE_FILL = (244, 239, 226, 255)
DRIVEZONE_EDGE = (214, 204, 182, 255)
DIVSTRIP_FILL = (120, 91, 170, 92)
DIVSTRIP_EDGE = (96, 71, 142, 138)
ROAD_COLOR = (82, 78, 74, 255)
BOUNDARY_ROAD_COLOR = (32, 103, 170, 255)
AXIS_ROAD_COLOR = (34, 34, 34, 255)
RCSD_ROAD_COLOR = (175, 33, 61, 255)
ALL_RCSD_ROAD_COLOR = (235, 170, 176, 150)
SELECTED_RCSD_ROAD_COLOR = (134, 23, 38, 255)
FIRST_HIT_RCSD_ROAD_COLOR = ALL_RCSD_ROAD_COLOR
SELECTED_RCSD_ROAD_HALO = (255, 255, 255, 0)
SECTION_WINDOW_FILL = None
SECTION_WINDOW_EDGE = (32, 103, 170, 92)
RCSD_NODE_FILL = (255, 255, 255, 255)
RCSD_NODE_RING = (189, 49, 49, 168)
SELECTED_RCSD_NODE_RING = (189, 49, 49, 255)
REQUIRED_RCSD_RING = (227, 181, 36, 255)
PRIMARY_RCSD_RING = (134, 23, 38, 255)
PAIR_REGION_FILL = (64, 128, 78, 18)
PAIR_REGION_EDGE = (64, 128, 78, 118)
STRUCTURE_FACE_FILL = (64, 128, 78, 28)
STRUCTURE_FACE_EDGE = (64, 128, 78, 158)
PAIR_MIDDLE_FILL = (23, 122, 84, 72)
PAIR_MIDDLE_EDGE = (18, 98, 68, 204)
THROAT_FILL = (214, 164, 38, 96)
THROAT_EDGE = (180, 124, 18, 210)
SELECTED_EVIDENCE_FILL = (57, 118, 189, 82)
SELECTED_CANDIDATE_EDGE = (32, 103, 170, 255)
RCSD_SCOPE_FILL = (189, 49, 49, 24)
RCSD_SCOPE_EDGE = (189, 49, 49, 138)
LOCAL_RCSD_UNIT_FILL = (189, 49, 49, 34)
LOCAL_RCSD_UNIT_EDGE = (134, 23, 38, 220)
SELECTED_COMPONENT_FILL = (114, 86, 165, 50)
SELECTED_COMPONENT_EDGE = (84, 55, 128, 186)
LOCALIZED_CORE_FILL = (84, 55, 128, 118)
LOCALIZED_CORE_EDGE = (58, 35, 97, 255)
FACT_POINT_FILL = (32, 103, 170, 255)
FACT_POINT_EDGE = (255, 255, 255, 255)
SECTION_REF_FILL = (255, 255, 255, 255)
SECTION_REF_EDGE = (35, 119, 90, 255)
REVIEW_POINT_EDGE = (32, 103, 170, 255)
NODE_COLOR = (64, 64, 64, 255)
GROUP_NODE_COLOR = (0, 0, 0, 255)
REP_RING_COLOR = (255, 255, 255, 255)
PANEL_FILL = (255, 255, 255, 236)
PANEL_EDGE = (220, 214, 203, 255)
PANEL_TEXT = (42, 42, 42, 255)
SUBTEXT = (90, 84, 78, 255)

CANDIDATE_COLORS = [
    ((214, 65, 52, 68), (214, 65, 52, 255)),
    ((42, 118, 170, 56), (32, 103, 170, 255)),
    ((128, 86, 184, 60), (98, 63, 150, 255)),
    ((210, 152, 42, 58), (184, 126, 18, 255)),
]

STATE_STYLE = {
    "STEP4_OK": {"banner": (38, 122, 72, 240), "label": "STEP4_OK"},
    "STEP4_REVIEW": {"banner": (185, 122, 17, 240), "label": "STEP4_REVIEW"},
    "STEP4_FAIL": {"banner": (170, 38, 38, 240), "label": "STEP4_FAIL"},
    "accepted": {"banner": (38, 122, 72, 240), "label": "ACCEPTED"},
    "rejected": {"banner": (170, 38, 38, 240), "label": "REJECTED"},
}

CONFLICT_COLORS = {
    "object": (160, 126, 74, 220),
    "region": (214, 98, 42, 240),
    "point": (190, 42, 42, 255),
}


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for child in geometry.geoms:
            yield from _iter_geometries(child)
        return
    yield geometry


def _iter_polygons(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "Polygon":
            yield item


def _iter_lines(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "LineString":
            yield item


def _iter_points(geometry: BaseGeometry | None) -> Iterable[Point]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "Point":
            yield item


def _project(bounds, x: float, y: float) -> tuple[float, float]:
    minx, miny, maxx, maxy = bounds
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    px = MAP_LEFT + ((x - minx) / width) * (MAP_SIZE - 1)
    py = MAP_TOP + (1.0 - (y - miny) / height) * (MAP_SIZE - 1)
    return px, py


def _coord_xy(coord) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])


def _draw_polygon(draw, geometry, bounds, *, fill, outline=None, width=1):
    for polygon in _iter_polygons(geometry):
        coords = [_project(bounds, *_coord_xy(coord)) for coord in polygon.exterior.coords]
        draw.polygon(coords, fill=fill, outline=outline)
        if outline is not None and width > 1:
            draw.line(coords, fill=outline, width=width, joint="curve")


def _draw_line(draw, geometry, bounds, *, fill, width):
    for line in _iter_lines(geometry):
        points = [_project(bounds, *_coord_xy(coord)) for coord in line.coords]
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(draw, geometry, bounds, *, fill, radius, ring=None):
    for point in _iter_points(geometry):
        px, py = _project(bounds, float(point.x), float(point.y))
        if ring is not None:
            draw.ellipse((px - radius - 3, py - radius - 3, px + radius + 3, py + radius + 3), fill=ring)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)


def _first_point(geometry: BaseGeometry | None) -> Point | None:
    return next(_iter_points(geometry), None)


def _representative_point(geometry: BaseGeometry | None) -> Point | None:
    point = _first_point(geometry)
    if point is not None:
        return point
    if geometry is None or geometry.is_empty:
        return None
    try:
        result = geometry.representative_point()
    except Exception:
        return None
    return None if result is None or result.is_empty else result


def _draw_crosshair(draw, point: Point | None, bounds, *, fill, outline, radius: int = 7):
    if point is None:
        return
    px, py = _project(bounds, float(point.x), float(point.y))
    draw.line((px - radius - 4, py, px + radius + 4, py), fill=outline, width=3)
    draw.line((px, py - radius - 4, px, py + radius + 4), fill=outline, width=3)
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill, outline=outline, width=2)


def _draw_labeled_crosshair(
    draw,
    point: Point | None,
    bounds,
    *,
    label: str,
    fill,
    outline,
    radius: int = 7,
) -> None:
    if point is None:
        return
    _draw_crosshair(draw, point, bounds, fill=fill, outline=outline, radius=radius)
    px, py = _project(bounds, float(point.x), float(point.y))
    label_text = _truncate(label, limit=12)
    text_width = 14 + max(len(label_text), 2) * 8
    draw.rounded_rectangle((px + 9, py - 17, px + 9 + text_width, py + 8), radius=7, fill=outline)
    draw.text((px + 16, py - 15), label_text, font=_font(14), fill=(255, 255, 255, 255))


def _draw_hollow_marker(draw, point: Point | None, bounds, *, outline, radius: int = 7):
    if point is None:
        return
    px, py = _project(bounds, float(point.x), float(point.y))
    draw.ellipse((px - radius - 2, py - radius - 2, px + radius + 2, py + radius + 2), fill=(255, 255, 255, 255))
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), outline=outline, width=3)


def _draw_badge(draw, *, x: int, y: int, text: str, fill):
    left = x
    top = y
    width = 18 + max(len(text), 4) * 9
    height = 28
    draw.rounded_rectangle((left, top, left + width, top + height), radius=12, fill=fill)
    draw.text((left + 12, top + 5), text, font=_font(16), fill=(255, 255, 255, 255))


def _draw_legend(
    draw,
    *,
    x: int,
    y: int,
    items: list[tuple[str, tuple[int, int, int, int], str]],
) -> None:
    width = 320
    height = 24 + len(items) * 24
    draw.rounded_rectangle((x, y, x + width, y + height), radius=14, fill=(255, 255, 255, 230), outline=PANEL_EDGE)
    draw.text((x + 14, y + 6), "Legend", font=_font(16), fill=PANEL_TEXT)
    cursor_y = y + 30
    for label, color, item_type in items:
        if item_type == "point":
            draw.ellipse((x + 22, cursor_y + 2, x + 38, cursor_y + 18), fill=color)
        elif item_type == "poly":
            draw.rounded_rectangle((x + 18, cursor_y + 2, x + 42, cursor_y + 16), radius=4, fill=color)
        else:
            draw.line((x + 18, cursor_y + 8, x + 42, cursor_y + 8), fill=color, width=4 if item_type == "line" else 6)
        draw.text((x + 52, cursor_y), label, font=_font(14), fill=SUBTEXT)
        cursor_y += 22


def _draw_panel(draw, *, state: str, title: str, lines: list[str]):
    style = STATE_STYLE[state]
    draw.rounded_rectangle(
        (PANEL_LEFT, PANEL_TOP, CANVAS_WIDTH - 20, CANVAS_HEIGHT - 20),
        radius=18,
        fill=PANEL_FILL,
        outline=PANEL_EDGE,
        width=2,
    )
    draw.rounded_rectangle(
        (PANEL_LEFT + 16, PANEL_TOP + 16, CANVAS_WIDTH - 36, PANEL_TOP + 86),
        radius=16,
        fill=style["banner"],
    )
    draw.text((PANEL_LEFT + 32, PANEL_TOP + 30), style["label"], font=_font(28), fill=(255, 255, 255, 255))
    draw.text((PANEL_LEFT + 32, PANEL_TOP + 102), title, font=_font(24), fill=(28, 28, 28, 255))
    cursor_y = PANEL_TOP + 150
    wrapped_lines: list[str] = []
    for line in lines:
        wrapped_lines.extend(_wrap_line(line, max_chars=58))
    for line in wrapped_lines[:28]:
        fill = SUBTEXT if line.startswith("  ") else PANEL_TEXT
        draw.text((PANEL_LEFT + 28, cursor_y), line, font=_font(18), fill=fill)
        cursor_y += 30


def _truncate(text: str, *, limit: int = 58) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _pretty_reason_text(text: str) -> str:
    return str(text).replace("|", " | ")


def _wrap_line(text: str, *, max_chars: int) -> list[str]:
    text = str(text)
    if len(text) <= max_chars:
        return [text]
    indent = "  " if text.startswith("  ") else ""
    content = text[len(indent) :]
    words = content.split(" ")
    if len(words) <= 1:
        return [indent + _truncate(content, limit=max_chars - len(indent))]
    wrapped: list[str] = []
    current = indent
    for word in words:
        candidate = word if current.strip() == "" else f"{current.strip()} {word}"
        if len(indent + candidate) <= max_chars:
            current = indent + candidate
            continue
        wrapped.append(current)
        current = indent + word
    if current:
        wrapped.append(current)
    return [line for line in wrapped if line]


def _save_flattened_png(image: Image.Image, out_path: Path) -> None:
    matte = Image.new("RGBA", image.size, BACKGROUND)
    flattened = Image.alpha_composite(matte, image).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    flattened.save(out_path, format="PNG")


def _base_bounds(unit: T04EventUnitResult):
    patch_polygon = unit.unit_context.local_context.grid.patch_polygon
    minx, miny, maxx, maxy = patch_polygon.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def _road_lookup(event_unit: T04EventUnitResult):
    return {road.road_id: road for road in event_unit.unit_context.local_context.patch_roads}


def _road_lookup_by_id(roads: Iterable[Any]) -> dict[str, Any]:
    return {
        str(road.road_id): road
        for road in roads
        if str(getattr(road, "road_id", "")).strip()
    }


def _ordered_roads_by_ids(roads: Iterable[Any], road_ids: Iterable[str]) -> tuple[Any, ...]:
    lookup = _road_lookup_by_id(roads)
    seen: set[str] = set()
    ordered: list[Any] = []
    for road_id in road_ids:
        key = str(road_id).strip()
        if not key or key in seen or key not in lookup:
            continue
        seen.add(key)
        ordered.append(lookup[key])
    return tuple(ordered)


def _node_lookup_by_id(nodes: Iterable[Any]) -> dict[str, Any]:
    return {
        str(node.node_id): node
        for node in nodes
        if str(getattr(node, "node_id", "")).strip()
    }


def _ordered_nodes_by_ids(nodes: Iterable[Any], node_ids: Iterable[str]) -> tuple[Any, ...]:
    lookup = _node_lookup_by_id(nodes)
    seen: set[str] = set()
    ordered: list[Any] = []
    for node_id in node_ids:
        key = str(node_id).strip()
        if not key or key in seen or key not in lookup:
            continue
        seen.add(key)
        ordered.append(lookup[key])
    return tuple(ordered)


def _unique_texts(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return tuple(ordered)


def _related_swsd_road_ids(step5_result: T04Step5CaseResult) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for unit_result in step5_result.unit_results:
        for road_id in (*unit_result.support_road_ids, *unit_result.support_event_road_ids):
            key = str(road_id).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def _related_rcsd_road_ids(step5_result: T04Step5CaseResult) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for unit_result in step5_result.unit_results:
        for road_id in unit_result.positive_rcsd_road_ids:
            key = str(road_id).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def _event_unit_surface_doc(event_unit: T04EventUnitResult) -> dict[str, Any]:
    try:
        return event_unit.surface_scenario_doc()
    except ValueError:
        return {
            "surface_scenario_type": "ambiguous_rcsd_alignment",
            "section_reference_source": "none",
            "rcsd_alignment_type": event_unit.rcsd_alignment_type or "ambiguous_rcsd_alignment",
            "fallback_rcsdroad_ids": [],
        }


def _active_rcsd_alignment_ids(case_result: T04CaseResult) -> tuple[tuple[str, ...], tuple[str, ...]]:
    road_ids: list[Any] = []
    node_ids: list[Any] = []
    for event_unit in case_result.event_units:
        surface_doc = _event_unit_surface_doc(event_unit)
        alignment_type = str(surface_doc.get("rcsd_alignment_type") or event_unit.rcsd_alignment_type or "")
        if alignment_type not in RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES:
            continue
        audit = event_unit.positive_rcsd_audit
        fallback_road_ids = tuple(surface_doc.get("fallback_rcsdroad_ids") or ())
        road_ids.extend(event_unit.selected_rcsdroad_ids)
        road_ids.extend(fallback_road_ids)
        if not fallback_road_ids:
            road_ids.extend(audit.get("published_rcsdroad_ids") or ())
        node_ids.extend(event_unit.selected_rcsdnode_ids)
        node_ids.extend(audit.get("published_rcsdnode_ids") or ())
        if event_unit.required_rcsd_node:
            node_ids.append(event_unit.required_rcsd_node)
    return _unique_texts(road_ids), _unique_texts(node_ids)


def _related_rcsd_node_ids(step5_result: T04Step5CaseResult) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for unit_result in step5_result.unit_results:
        for node_id in unit_result.positive_rcsd_node_ids:
            key = str(node_id).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def _section_reference_markers(event_unit: T04EventUnitResult) -> tuple[tuple[str, Point], ...]:
    surface_doc = _event_unit_surface_doc(event_unit)
    section_reference_source = str(surface_doc.get("section_reference_source") or "")
    markers: list[tuple[str, Point]] = []
    if bool(surface_doc.get("reference_point_present")):
        point = _first_point(event_unit.fact_reference_point) or _first_point(event_unit.review_materialized_point)
        if point is not None:
            markers.append(("RP", point))
    if section_reference_source in {SECTION_REFERENCE_POINT_AND_RCSD, SECTION_REFERENCE_RCSD}:
        point = (
            _first_point(event_unit.required_rcsd_node_geometry)
            or _first_point(event_unit.positive_rcsd_node_geometry)
            or _representative_point(event_unit.local_rcsd_unit_geometry)
        )
        if point is not None:
            markers.append(("RCSD", point))
    elif section_reference_source == SECTION_REFERENCE_SWSD:
        point = _first_point(event_unit.unit_context.representative_node.geometry)
        if point is not None:
            markers.append(("SWSD", point))
    return tuple(markers)


def _draw_context_layers(draw, event_unit: T04EventUnitResult, bounds) -> None:
    local_context = event_unit.unit_context.local_context
    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    for feature in local_context.patch_divstrip_features:
        _draw_polygon(draw, feature.geometry, bounds, fill=DIVSTRIP_FILL, outline=DIVSTRIP_EDGE, width=2)
    for road in local_context.local_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=1)
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=4)
    _draw_point(draw, event_unit.unit_context.representative_node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=6, ring=REP_RING_COLOR)


def _draw_rcsd_scope_layers(draw, event_unit: T04EventUnitResult, bounds) -> None:
    return


def _draw_branch_overlays(draw, event_unit: T04EventUnitResult, bounds) -> None:
    _draw_line(draw, event_unit.positive_rcsd_road_geometry, bounds, fill=SELECTED_RCSD_ROAD_COLOR, width=10)


def _draw_positive_rcsd_audit_layers(draw, event_unit: T04EventUnitResult, bounds) -> None:
    local_context = event_unit.unit_context.local_context
    for road in local_context.patch_roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=3)
    for road in local_context.local_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=2)
    _draw_line(draw, event_unit.positive_rcsd_road_geometry, bounds, fill=SELECTED_RCSD_ROAD_COLOR, width=10)
    _draw_point(draw, event_unit.required_rcsd_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=7, ring=REQUIRED_RCSD_RING)
    _draw_point(draw, event_unit.primary_main_rc_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=5, ring=PRIMARY_RCSD_RING)


def _positive_rcsd_review_lines(event_unit: T04EventUnitResult, audit_summary: dict[str, object]) -> list[str]:
    return [
        f"mainnodeid: {event_unit.unit_context.admission.mainnodeid}",
        f"event_unit_id: {event_unit.spec.event_unit_id}",
        f"selected_evidence: {_truncate(str(event_unit.selected_evidence_summary.get('candidate_id') or ''), limit=58)}",
        f"candidate_region: {_truncate(str(audit_summary.get('selected_candidate_region') or ''), limit=58)}",
        f"positive_present: {event_unit.positive_rcsd_present} / {_truncate(event_unit.positive_rcsd_present_reason, limit=44)}",
        f"positive_rcsd: {event_unit.positive_rcsd_support_level} / {event_unit.positive_rcsd_consistency_level}",
        f"selection_mode: {event_unit.rcsd_selection_mode}",
        f"local_unit: {_truncate(str(event_unit.local_rcsd_unit_id or ''), limit=58)}",
        f"aggregated_unit: {_truncate(str(event_unit.aggregated_rcsd_unit_id or ''), limit=58)}",
        f"axis_polarity_inverted: {event_unit.axis_polarity_inverted}",
        f"first_hit_roads: {_truncate(';'.join(event_unit.first_hit_rcsdroad_ids), limit=58)}",
        f"selected_rcsd_roads: {_truncate(';'.join(event_unit.selected_rcsdroad_ids), limit=58)}",
        f"selected_rcsd_nodes: {_truncate(';'.join(event_unit.selected_rcsdnode_ids), limit=58)}",
        f"primary_main_rc_node: {event_unit.primary_main_rc_node_id or ''}",
        f"required_rcsd_node: {event_unit.required_rcsd_node or ''} / {event_unit.required_rcsd_node_source or ''}",
        f"rcsd_reason: {_truncate(str(event_unit.positive_rcsd_audit.get('rcsd_decision_reason') or ''), limit=58)}",
    ]


def _main_review_lines(event_unit: T04EventUnitResult, audit_summary: dict[str, object]) -> list[str]:
    selected = event_unit.selected_evidence_summary
    lines = [
        f"mainnodeid: {event_unit.unit_context.admission.mainnodeid}",
        f"event_unit_id: {event_unit.spec.event_unit_id}",
        f"selected_evidence_state: {event_unit.selected_evidence_state}",
        f"selected_evidence: {_truncate(str(selected.get('candidate_id') or ''), limit=62)}",
        f"candidate_region: {_truncate(str(audit_summary.get('selected_candidate_region') or ''), limit=62)}",
        f"reference_zone: {audit_summary.get('selected_reference_zone', '')}",
        f"positive_present: {event_unit.positive_rcsd_present} / {_truncate(event_unit.positive_rcsd_present_reason, limit=44)}",
        f"positive_rcsd: {event_unit.positive_rcsd_support_level} / {event_unit.positive_rcsd_consistency_level}",
        f"aggregated_unit: {_truncate(str(event_unit.aggregated_rcsd_unit_id or ''), limit=56)}",
        f"axis_polarity_inverted: {event_unit.axis_polarity_inverted}",
        f"first_hit_roads: {_truncate(';'.join(event_unit.first_hit_rcsdroad_ids), limit=56)}",
        f"rcsd_counts: roads={len(event_unit.selected_rcsdroad_ids)} nodes={len(event_unit.selected_rcsdnode_ids)}",
        f"required_rcsd_node: {event_unit.required_rcsd_node or ''} / {event_unit.required_rcsd_node_source or ''}",
        f"rcsd_reason: {_truncate(str(event_unit.positive_rcsd_audit.get('rcsd_decision_reason') or ''), limit=56)}",
    ]
    best_alt_id = str(audit_summary.get("best_alternative_candidate_id") or "")
    if best_alt_id:
        lines.append(f"best_alt: {_truncate(best_alt_id, limit=58)}")
    if event_unit.unit_envelope.degraded_scope_reason:
        lines.append(f"degraded_scope: {_pretty_reason_text(event_unit.unit_envelope.degraded_scope_reason)}")
    if event_unit.all_review_reasons():
        lines.append(f"key_reason: {_pretty_reason_text(event_unit.all_review_reasons()[0])}")
    return lines


def render_event_unit_review_png(
    out_path: Path,
    event_unit: T04EventUnitResult,
    *,
    audit_summary: dict[str, object] | None = None,
) -> None:
    audit_summary = audit_summary or {}
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(event_unit)

    _draw_context_layers(draw, event_unit, bounds)
    primary_evidence_geometry = (
        event_unit.selected_evidence_region_geometry
        or event_unit.localized_evidence_core_geometry
        or event_unit.selected_component_union_geometry
    )
    _draw_polygon(draw, primary_evidence_geometry, bounds, fill=SELECTED_EVIDENCE_FILL, outline=SELECTED_CANDIDATE_EDGE, width=4)
    _draw_rcsd_scope_layers(draw, event_unit, bounds)
    _draw_branch_overlays(draw, event_unit, bounds)

    fact_point = _first_point(event_unit.fact_reference_point)
    _draw_crosshair(draw, fact_point, bounds, fill=FACT_POINT_FILL, outline=FACT_POINT_EDGE, radius=6)

    _draw_badge(
        draw,
        x=MAP_LEFT + 18,
        y=MAP_TOP + 18,
        text=f"ref:{audit_summary.get('selected_reference_zone', 'missing')}",
        fill=STATE_STYLE[event_unit.review_state]["banner"],
    )
    _draw_badge(
        draw,
        x=MAP_LEFT + 190,
        y=MAP_TOP + 18,
        text=f"rcsd:{event_unit.positive_rcsd_consistency_level}",
        fill=RCSD_ROAD_COLOR,
    )
    _draw_legend(
        draw,
        x=MAP_LEFT + 18,
        y=MAP_TOP + MAP_SIZE - 132,
        items=[
            ("Road Surface", DRIVEZONE_EDGE, "poly"),
            ("Divstrip", DIVSTRIP_FILL, "poly"),
            ("Primary Evidence", SELECTED_CANDIDATE_EDGE, "poly"),
            ("Reference Point", FACT_POINT_FILL, "point"),
            ("SWSD Node", NODE_COLOR, "point"),
            ("RCSD", ALL_RCSD_ROAD_COLOR, "line"),
            ("Selected RCSD", SELECTED_RCSD_ROAD_COLOR, "strong_line"),
        ],
    )

    _draw_panel(
        draw,
        state=event_unit.review_state,
        title="Step4 Evidence Main Audit",
        lines=_main_review_lines(event_unit, audit_summary),
    )
    _save_flattened_png(image, out_path)


def _candidate_anchor_point(candidate_entry: T04CandidateAuditEntry) -> Point | None:
    return (
        _first_point(candidate_entry.fact_reference_point)
        or _first_point(candidate_entry.review_materialized_point)
        or _representative_point(candidate_entry.candidate_region_geometry)
    )


def _candidate_compare_lines(
    event_unit: T04EventUnitResult,
    audit_summary: dict[str, object],
    shortlist: tuple[T04CandidateAuditEntry, ...],
) -> list[str]:
    selected_id = str(event_unit.selected_evidence_summary.get("candidate_id") or "")
    lines = [
        f"mainnodeid: {event_unit.unit_context.admission.mainnodeid}",
        f"event_unit_id: {event_unit.spec.event_unit_id}",
        f"candidate_region: {_truncate(str(audit_summary.get('selected_candidate_region') or ''), limit=58)}",
        f"selected_evidence_state: {event_unit.selected_evidence_state}",
        f"selected: {_truncate(selected_id, limit=58)}",
        f"selected_layer: {event_unit.selected_evidence_summary.get('layer_label', '')}",
        f"selected_ref_zone: {audit_summary.get('selected_reference_zone', '')}",
        f"positive_rcsd: {event_unit.positive_rcsd_support_level} / {event_unit.positive_rcsd_consistency_level}",
        f"best_alt_signal: {bool(audit_summary.get('better_alternative_signal'))}",
    ]
    for index, entry in enumerate(shortlist, start=1):
        selected_flag = "SELECTED" if entry.candidate_id == selected_id else "ALT"
        lines.append(
            f"{index}. {selected_flag} / pool#{entry.pool_rank} / {entry.candidate_summary.get('layer_label', '')}"
        )
        lines.append(f"  {_truncate(entry.candidate_id, limit=54)}")
        reference_zone = _candidate_entry_reference_zone(event_unit=event_unit, candidate_entry=entry)
        lines.append(
            "  "
            + f"priority={entry.priority_score} ref={reference_zone}"
        )
        if entry.candidate_id != selected_id:
            lines.append(
                "  "
                + f"decision={entry.decision_reason}"
            )
        else:
            lines.append("  " + f"decision={entry.decision_reason}")
    return lines


def render_event_unit_candidate_compare_png(
    out_path: Path,
    event_unit: T04EventUnitResult,
    *,
    audit_summary: dict[str, object] | None = None,
) -> None:
    audit_summary = audit_summary or {}
    shortlist_ids = list(audit_summary.get("candidate_shortlist_ids") or [])
    shortlisted_entries_list: list[T04CandidateAuditEntry] = []
    seen_candidate_ids: set[str] = set()
    for candidate_id in shortlist_ids:
        for entry in event_unit.candidate_audit_entries:
            if entry.candidate_id != candidate_id or entry.candidate_id in seen_candidate_ids:
                continue
            shortlisted_entries_list.append(entry)
            seen_candidate_ids.add(entry.candidate_id)
            break
    shortlisted_entries = tuple(shortlisted_entries_list)
    if not shortlisted_entries:
        fallback_entries: list[T04CandidateAuditEntry] = []
        for entry in event_unit.candidate_audit_entries:
            if entry.candidate_id in seen_candidate_ids:
                continue
            fallback_entries.append(entry)
            seen_candidate_ids.add(entry.candidate_id)
            if len(fallback_entries) >= 4:
                break
        shortlisted_entries = tuple(fallback_entries)

    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(event_unit)

    _draw_context_layers(draw, event_unit, bounds)

    for index, candidate_entry in enumerate(shortlisted_entries):
        fill, outline = CANDIDATE_COLORS[index % len(CANDIDATE_COLORS)]
        _draw_polygon(draw, candidate_entry.candidate_region_geometry, bounds, fill=fill, outline=outline, width=3)
        _draw_polygon(draw, candidate_entry.localized_evidence_core_geometry, bounds, fill=None, outline=outline, width=2)
        point = _candidate_anchor_point(candidate_entry)
        if point is not None:
            _draw_crosshair(draw, point, bounds, fill=(255, 255, 255, 255), outline=outline, radius=5)
            px, py = _project(bounds, float(point.x), float(point.y))
            label = str(index + 1)
            draw.rounded_rectangle((px + 8, py - 16, px + 34, py + 10), radius=8, fill=outline)
            draw.text((px + 16, py - 14), label, font=_font(16), fill=(255, 255, 255, 255))

    _draw_rcsd_scope_layers(draw, event_unit, bounds)
    _draw_branch_overlays(draw, event_unit, bounds)

    _draw_panel(
        draw,
        state=event_unit.review_state,
        title="Step4 Candidate Compare",
        lines=_candidate_compare_lines(event_unit, audit_summary, shortlisted_entries),
    )
    _save_flattened_png(image, out_path)


def render_event_unit_positive_rcsd_review_png(
    out_path: Path,
    event_unit: T04EventUnitResult,
    *,
    audit_summary: dict[str, object] | None = None,
) -> None:
    audit_summary = audit_summary or {}
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(event_unit)

    _draw_polygon(
        draw,
        event_unit.unit_context.local_context.patch_drivezone_union,
        bounds,
        fill=DRIVEZONE_FILL,
        outline=DRIVEZONE_EDGE,
        width=2,
    )
    for feature in event_unit.unit_context.local_context.patch_divstrip_features:
        _draw_polygon(draw, feature.geometry, bounds, fill=DIVSTRIP_FILL, outline=DIVSTRIP_EDGE, width=2)
    primary_evidence_geometry = (
        event_unit.selected_evidence_region_geometry
        or event_unit.localized_evidence_core_geometry
        or event_unit.selected_component_union_geometry
    )
    _draw_polygon(
        draw,
        primary_evidence_geometry,
        bounds,
        fill=SELECTED_EVIDENCE_FILL,
        outline=SELECTED_CANDIDATE_EDGE,
        width=4,
    )
    _draw_positive_rcsd_audit_layers(draw, event_unit, bounds)
    fact_point = _first_point(event_unit.fact_reference_point)
    _draw_crosshair(draw, fact_point, bounds, fill=FACT_POINT_FILL, outline=FACT_POINT_EDGE, radius=6)
    for node in event_unit.unit_context.local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=4)
    _draw_point(
        draw,
        event_unit.unit_context.representative_node.geometry,
        bounds,
        fill=GROUP_NODE_COLOR,
        radius=6,
        ring=REP_RING_COLOR,
    )

    _draw_badge(
        draw,
        x=MAP_LEFT + 18,
        y=MAP_TOP + 18,
        text=f"positive:{event_unit.positive_rcsd_consistency_level}",
        fill=RCSD_ROAD_COLOR,
    )
    _draw_badge(
        draw,
        x=MAP_LEFT + 220,
        y=MAP_TOP + 18,
        text=f"required:{'yes' if event_unit.required_rcsd_node else 'no'}",
        fill=REQUIRED_RCSD_RING,
    )
    _draw_legend(
        draw,
        x=MAP_LEFT + 18,
        y=MAP_TOP + MAP_SIZE - 176,
        items=[
            ("Road Surface", DRIVEZONE_EDGE, "poly"),
            ("Divstrip", DIVSTRIP_FILL, "poly"),
            ("Primary Evidence", SELECTED_CANDIDATE_EDGE, "poly"),
            ("Reference Point", FACT_POINT_FILL, "point"),
            ("SWSD Node", NODE_COLOR, "point"),
            ("Other RCSD", ALL_RCSD_ROAD_COLOR, "line"),
            ("Selected RCSD", SELECTED_RCSD_ROAD_COLOR, "strong_line"),
        ],
    )
    _draw_panel(
        draw,
        state=event_unit.review_state,
        title="Step4 Positive RCSD Audit",
        lines=_positive_rcsd_review_lines(event_unit, audit_summary),
    )
    _save_flattened_png(image, out_path)


def render_case_overview_png(
    out_path: Path,
    case_result: T04CaseResult,
    *,
    audit_by_unit: dict[str, dict[str, Any]] | None = None,
) -> None:
    audit_by_unit = audit_by_unit or build_case_review_audit(case_result)
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(case_result.event_units[0])
    local_context = case_result.base_context.local_context

    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    for feature in local_context.patch_divstrip_features:
        _draw_polygon(draw, feature.geometry, bounds, fill=DIVSTRIP_FILL, outline=DIVSTRIP_EDGE, width=2)
    for road in local_context.local_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=1)
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=4)
    _draw_point(draw, case_result.base_context.representative_node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=6, ring=REP_RING_COLOR)

    unit_colors = [color[1] for color in CANDIDATE_COLORS]
    unit_point_lookup: dict[str, Point] = {}
    overview_lines = [
        f"case_id: {case_result.case_spec.case_id}",
        f"mainnodeid: {case_result.case_spec.mainnodeid}",
        f"event_unit_count: {len(case_result.event_units)}",
    ]
    for index, event_unit in enumerate(case_result.event_units, start=1):
        audit_summary = audit_by_unit.get(event_unit.spec.event_unit_id, {})
        color = unit_colors[(index - 1) % len(unit_colors)]
        highlight_geometry = (
            event_unit.selected_evidence_region_geometry
            or event_unit.localized_evidence_core_geometry
            or event_unit.selected_component_union_geometry
        )
        _draw_polygon(draw, highlight_geometry, bounds, fill=(color[0], color[1], color[2], 62), outline=color, width=3)
        point = _first_point(event_unit.fact_reference_point) or _first_point(event_unit.review_materialized_point)
        if point is not None:
            unit_point_lookup[event_unit.spec.event_unit_id] = point
            _draw_crosshair(draw, point, bounds, fill=(255, 255, 255, 255), outline=color, radius=5)
            px, py = _project(bounds, float(point.x), float(point.y))
            draw.text((px + 8, py - 10), str(index), font=_font(18), fill=(24, 24, 24, 255))
        focus_flag = "focus" if audit_summary.get("needs_manual_review_focus") else "ok"
        overview_lines.append(
            f"{index}. {event_unit.spec.event_unit_id} / {event_unit.review_state} / {focus_flag}"
        )
        overview_lines.append(
            "  "
            + f"ref={audit_summary.get('selected_reference_zone', '')} "
            + f"rcsd={event_unit.positive_rcsd_consistency_level} "
            + f"obj={_truncate(str(audit_summary.get('upper_evidence_object_id') or ''), limit=24)}"
        )
        key_reason = str(audit_summary.get("key_reason") or "")
        if key_reason:
            overview_lines.append(f"  {_truncate(key_reason, limit=58)}")

    _draw_panel(
        draw,
        state=case_result.case_review_state,
        title="Step4 Case Overview",
        lines=overview_lines[:24],
    )
    _save_flattened_png(image, out_path)


def render_case_final_review_png(
    out_path: Path,
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
    step6_result: T04Step6Result,
    *,
    final_state: str,
    reject_reasons: Iterable[str] = (),
    publish_target: str = "",
) -> None:
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(case_result.event_units[0])
    local_context = case_result.base_context.local_context

    related_swsd_road_ids = set(_related_swsd_road_ids(step5_result))
    active_rcsd_road_ids, active_rcsd_node_ids = _active_rcsd_alignment_ids(case_result)
    related_rcsd_road_ids = set(active_rcsd_road_ids)
    related_rcsd_node_ids = set(active_rcsd_node_ids)
    related_swsd_roads = _ordered_roads_by_ids(local_context.local_roads, related_swsd_road_ids)
    related_rcsd_roads = _ordered_roads_by_ids(local_context.local_rcsd_roads, related_rcsd_road_ids)
    related_rcsd_nodes = _ordered_nodes_by_ids(local_context.local_rcsd_nodes, related_rcsd_node_ids)
    other_swsd_roads = tuple(
        road for road in local_context.local_roads if str(road.road_id) not in related_swsd_road_ids
    )
    other_rcsd_roads = tuple(
        road for road in local_context.local_rcsd_roads if str(road.road_id) not in related_rcsd_road_ids
    )

    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    for feature in local_context.patch_divstrip_features:
        _draw_polygon(draw, feature.geometry, bounds, fill=DIVSTRIP_FILL, outline=DIVSTRIP_EDGE, width=2)
    _draw_polygon(
        draw,
        step5_result.case_terminal_window_domain,
        bounds,
        fill=SECTION_WINDOW_FILL,
        outline=SECTION_WINDOW_EDGE,
        width=1,
    )
    for road in other_swsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=AXIS_ROAD_COLOR, width=2)
    for road in related_swsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=AXIS_ROAD_COLOR, width=6)
    for road in other_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=2)
    for road in related_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=SELECTED_RCSD_ROAD_COLOR, width=9)
    for node in related_rcsd_nodes:
        _draw_point(draw, node.geometry, bounds, fill=RCSD_NODE_FILL, radius=6, ring=SELECTED_RCSD_NODE_RING)
    for event_unit in case_result.event_units:
        _draw_point(draw, event_unit.required_rcsd_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=8, ring=REQUIRED_RCSD_RING)
    if step6_result.final_case_polygon is not None and not step6_result.final_case_polygon.is_empty:
        _draw_line(draw, step6_result.final_case_polygon.boundary, bounds, fill=BOUNDARY_ROAD_COLOR, width=3)
    for event_unit in case_result.event_units:
        for label, point in _section_reference_markers(event_unit):
            _draw_labeled_crosshair(
                draw,
                point,
                bounds,
                label=label,
                fill=SECTION_REF_FILL,
                outline=SECTION_REF_EDGE,
                radius=6,
            )

    _draw_legend(
        draw,
        x=MAP_LEFT + 18,
        y=MAP_TOP + 18,
        items=[
            ("Road Surface", DRIVEZONE_FILL, "poly"),
            ("Divstrip", DIVSTRIP_EDGE, "poly"),
            ("SWSD Other", AXIS_ROAD_COLOR, "line"),
            ("SWSD Current", AXIS_ROAD_COLOR, "strong_line"),
            ("RCSD Other", ALL_RCSD_ROAD_COLOR, "line"),
            ("RCSD Positive", SELECTED_RCSD_ROAD_COLOR, "strong_line"),
            ("Section Ref", SECTION_REF_EDGE, "point"),
            ("Section Window", SECTION_WINDOW_EDGE, "line"),
            ("Final Boundary", BOUNDARY_ROAD_COLOR, "strong_line"),
        ],
    )
    reject_reason_list = [str(reason).strip() for reason in reject_reasons if str(reason).strip()]
    scenario_types = _unique_texts(
        _event_unit_surface_doc(event_unit).get("surface_scenario_type")
        for event_unit in case_result.event_units
    )
    alignment_types = _unique_texts(
        _event_unit_surface_doc(event_unit).get("rcsd_alignment_type")
        for event_unit in case_result.event_units
    )
    section_references = _unique_texts(
        _event_unit_surface_doc(event_unit).get("section_reference_source")
        for event_unit in case_result.event_units
    )
    final_review_lines = [
        f"case_id: {case_result.case_spec.case_id}",
        f"mainnodeid: {case_result.case_spec.mainnodeid}",
        f"final_state: {final_state}",
        f"publish_target: {publish_target or '-'}",
        f"surface_scenarios: {_truncate(';'.join(scenario_types), limit=56)}",
        f"rcsd_alignments: {_truncate(';'.join(alignment_types), limit=56)}",
        f"section_refs: {_truncate(';'.join(section_references), limit=56)}",
        f"event_unit_count: {len(case_result.event_units)}",
        f"assembly_state: {step6_result.assembly_state}",
        f"component_count: {step6_result.component_count}",
        f"swsd_current_roads: {len(related_swsd_roads)} / other={len(other_swsd_roads)}",
        f"positive_rcsd_roads: {len(related_rcsd_roads)} / other={len(other_rcsd_roads)}",
        f"positive_rcsd_nodes: {len(related_rcsd_nodes)}",
        f"final_boundary_present: {bool(step6_result.final_case_polygon is not None and not step6_result.final_case_polygon.is_empty)}",
    ]
    if reject_reason_list:
        final_review_lines.append(
            f"reject_reasons: {_truncate('|'.join(reject_reason_list), limit=56)}"
        )

    _draw_panel(
        draw,
        state=final_state,
        title="Step7 Final Review",
        lines=final_review_lines,
    )
    _save_flattened_png(image, out_path)
