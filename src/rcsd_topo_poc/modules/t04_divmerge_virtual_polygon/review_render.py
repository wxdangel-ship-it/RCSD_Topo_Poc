from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .review_audit import _candidate_entry_reference_zone, build_case_review_audit


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
DIVSTRIP_FILL = (120, 91, 170, 74)
DIVSTRIP_EDGE = None
ROAD_COLOR = (82, 78, 74, 255)
BOUNDARY_ROAD_COLOR = (32, 103, 170, 255)
AXIS_ROAD_COLOR = (34, 34, 34, 255)
RCSD_ROAD_COLOR = (175, 33, 61, 255)
ALL_RCSD_ROAD_COLOR = (189, 49, 49, 168)
SELECTED_RCSD_ROAD_COLOR = (189, 49, 49, 255)
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
SELECTED_COMPONENT_FILL = (114, 86, 165, 50)
SELECTED_COMPONENT_EDGE = (84, 55, 128, 186)
LOCALIZED_CORE_FILL = (84, 55, 128, 118)
LOCALIZED_CORE_EDGE = (58, 35, 97, 255)
FACT_POINT_FILL = (32, 103, 170, 255)
FACT_POINT_EDGE = (255, 255, 255, 255)
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


def _draw_legend(draw, *, x: int, y: int, items: list[tuple[str, tuple[int, int, int, int]]]) -> None:
    width = 320
    height = 24 + len(items) * 24
    draw.rounded_rectangle((x, y, x + width, y + height), radius=14, fill=(255, 255, 255, 230), outline=PANEL_EDGE)
    draw.text((x + 14, y + 6), "Legend", font=_font(16), fill=PANEL_TEXT)
    cursor_y = y + 30
    for label, color in items:
        draw.line((x + 18, cursor_y + 8, x + 42, cursor_y + 8), fill=color, width=4)
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


def _draw_context_layers(draw, event_unit: T04EventUnitResult, bounds) -> None:
    local_context = event_unit.unit_context.local_context
    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    for road in local_context.patch_roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=4)
    for road in local_context.local_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=2)
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=3)
    for node in local_context.local_rcsd_nodes:
        _draw_point(draw, node.geometry, bounds, fill=RCSD_NODE_FILL, radius=3, ring=RCSD_NODE_RING)
    _draw_point(draw, event_unit.unit_context.representative_node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=6, ring=REP_RING_COLOR)


def _draw_branch_overlays(draw, event_unit: T04EventUnitResult, bounds) -> None:
    _draw_line(draw, event_unit.positive_rcsd_road_geometry, bounds, fill=SELECTED_RCSD_ROAD_COLOR, width=7)
    _draw_point(draw, event_unit.positive_rcsd_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=6, ring=SELECTED_RCSD_NODE_RING)
    _draw_point(draw, event_unit.primary_main_rc_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=7, ring=PRIMARY_RCSD_RING)
    _draw_point(draw, event_unit.required_rcsd_node_geometry, bounds, fill=RCSD_NODE_FILL, radius=8, ring=REQUIRED_RCSD_RING)


def _main_review_lines(event_unit: T04EventUnitResult, audit_summary: dict[str, object]) -> list[str]:
    selected = event_unit.selected_evidence_summary
    lines = [
        f"mainnodeid: {event_unit.unit_context.admission.mainnodeid}",
        f"event_unit_id: {event_unit.spec.event_unit_id}",
        f"event_type: {event_unit.spec.event_type}",
        f"split_mode: {event_unit.spec.split_mode}",
        f"boundary_pair: {_truncate(str(audit_summary.get('boundary_pair_signature') or ''))}",
        f"candidate_region: {_truncate(str(audit_summary.get('selected_candidate_region') or ''), limit=62)}",
        f"selected_evidence_state: {event_unit.selected_evidence_state}",
        f"selected_evidence: {_truncate(str(selected.get('candidate_id') or ''), limit=62)}",
        f"evidence_layer: {selected.get('layer_label', '')} / {selected.get('layer_reason', '')}",
        f"axis_position_m: {audit_summary.get('axis_position_m', '')}",
        f"ref_dist_to_origin_m: {audit_summary.get('reference_distance_to_origin_m', '')}",
        f"reference_zone: {audit_summary.get('selected_reference_zone', '')}",
        f"evidence_membership: {audit_summary.get('selected_evidence_membership', '')}",
        f"positive_rcsd: {event_unit.positive_rcsd_support_level} / {event_unit.positive_rcsd_consistency_level}",
        f"rcsd_counts: roads={len(event_unit.selected_rcsdroad_ids)} nodes={len(event_unit.selected_rcsdnode_ids)}",
        f"required_rcsd_node: {event_unit.required_rcsd_node or ''}",
        f"evidence_source: {event_unit.evidence_source}",
        f"position_source: {event_unit.position_source}",
        f"reverse_tip_used: {event_unit.reverse_tip_used}",
        f"conflict_level: {audit_summary.get('conflict_signal_level', '')}",
        f"manual_focus: {bool(audit_summary.get('needs_manual_review_focus'))}",
    ]
    best_alt_id = str(audit_summary.get("best_alternative_candidate_id") or "")
    if best_alt_id:
        lines.append(f"best_alt: {_truncate(best_alt_id, limit=58)}")
        lines.append(f"  alt_reason: {_pretty_reason_text(str(audit_summary.get('best_alternative_reason', '')))}")
    if event_unit.unit_envelope.degraded_scope_reason:
        lines.append(f"degraded_scope: {_pretty_reason_text(event_unit.unit_envelope.degraded_scope_reason)}")
    if event_unit.all_review_reasons():
        lines.append(f"key_reason: {_pretty_reason_text(event_unit.all_review_reasons()[0])}")
        for reason in event_unit.all_review_reasons()[1:4]:
            lines.append(f"  {_pretty_reason_text(reason)}")
    elif audit_summary.get("focus_reasons"):
        focus_reasons = list(audit_summary.get("focus_reasons") or [])
        lines.append(f"key_reason: {_pretty_reason_text(str(focus_reasons[0]))}")
        for reason in focus_reasons[1:4]:
            lines.append(f"  {_pretty_reason_text(reason)}")
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
    _draw_branch_overlays(draw, event_unit, bounds)
    primary_evidence_geometry = (
        event_unit.selected_evidence_region_geometry
        or event_unit.localized_evidence_core_geometry
        or event_unit.selected_component_union_geometry
    )
    _draw_polygon(draw, primary_evidence_geometry, bounds, fill=SELECTED_EVIDENCE_FILL, outline=SELECTED_CANDIDATE_EDGE, width=4)

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
        y=MAP_TOP + MAP_SIZE - 150,
        items=[
            ("SWSD Road", ROAD_COLOR),
            ("All RCSD Road", ALL_RCSD_ROAD_COLOR),
            ("Selected RCSD", SELECTED_RCSD_ROAD_COLOR),
            ("Primary Evidence", SELECTED_CANDIDATE_EDGE),
            ("Required RCSD Node", REQUIRED_RCSD_RING),
            ("SWSD Node", NODE_COLOR),
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
    _draw_branch_overlays(draw, event_unit, bounds)

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

    _draw_panel(
        draw,
        state=event_unit.review_state,
        title="Step4 Candidate Compare",
        lines=_candidate_compare_lines(event_unit, audit_summary, shortlisted_entries),
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
    for road in local_context.patch_roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=4)
    for road in local_context.local_rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=ALL_RCSD_ROAD_COLOR, width=2)
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=3)
    for node in local_context.local_rcsd_nodes:
        _draw_point(draw, node.geometry, bounds, fill=RCSD_NODE_FILL, radius=3, ring=RCSD_NODE_RING)
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

    drawn_pairs: set[tuple[str, str, str]] = set()
    for unit_id, audit_summary in audit_by_unit.items():
        lhs_point = unit_point_lookup.get(unit_id)
        if lhs_point is None:
            continue
        for conflict_level, key_name in (
            ("object", "shared_object_unit_ids"),
            ("region", "shared_region_unit_ids"),
            ("point", "shared_point_unit_ids"),
        ):
            for other_unit_id in audit_summary.get(key_name, []):
                rhs_point = unit_point_lookup.get(str(other_unit_id))
                if rhs_point is None:
                    continue
                pair_key = tuple(sorted([unit_id, str(other_unit_id)])) + (conflict_level,)
                if pair_key in drawn_pairs:
                    continue
                drawn_pairs.add(pair_key)
                lhs_px, lhs_py = _project(bounds, float(lhs_point.x), float(lhs_point.y))
                rhs_px, rhs_py = _project(bounds, float(rhs_point.x), float(rhs_point.y))
                draw.line(
                    (lhs_px, lhs_py, rhs_px, rhs_py),
                    fill=CONFLICT_COLORS[conflict_level],
                    width=4 if conflict_level == "point" else 3,
                )

    _draw_panel(
        draw,
        state=case_result.case_review_state,
        title="Step4 Case Overview",
        lines=overview_lines[:24],
    )
    _save_flattened_png(image, out_path)
