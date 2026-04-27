from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_render import (
    BACKGROUND_COLOR,
    DRIVEZONE_EDGE,
    DRIVEZONE_FILL,
    FOREIGN_NODE_COLOR,
    GROUP_NODE_COLOR,
    IMAGE_SIZE,
    MAX_PATCH_SIZE_M,
    ROAD_COLOR,
    STATUS_STYLE,
    _draw_failure_overlay,
    _draw_line,
    _draw_point,
    _draw_polygon,
    _draw_text_with_shadow,
    _font,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationCaseResult,
    FinalizationContext,
)


STEP67_STYLE = {
    "V1 认可成功": {
        **STATUS_STYLE["established"],
        "overlay_key": "established",
    },
    "V2 业务正确但几何待修": {
        **STATUS_STYLE["review"],
        "overlay_key": "review",
    },
    "V3 漏包 required": {
        **STATUS_STYLE["not_established"],
        "overlay_key": "not_established",
    },
    "V4 误包 foreign": {
        **STATUS_STYLE["not_established"],
        "overlay_key": "not_established",
    },
    "V5 明确失败": {
        **STATUS_STYLE["not_established"],
        "overlay_key": "not_established",
    },
}

VISIBLE_RC_ROAD_EDGE = (222, 112, 124, 220)
REQUIRED_EDGE = (161, 13, 13, 255)
SUPPORT_EDGE = (189, 124, 9, 255)
FINAL_FILL = (40, 120, 85, 130)
FINAL_EDGE = (15, 80, 52, 255)
SEED_FILL = (54, 125, 181, 40)
SEED_EDGE = (24, 96, 151, 180)
FOREIGN_MASK_FILL = (164, 0, 0, 52)


def _patch_bounds(finalization_context: FinalizationContext, case_result: FinalizationCaseResult) -> tuple[float, float, float, float]:
    step1 = finalization_context.association_context.step1_context
    reference = step1.representative_node.geometry
    focus = [
        reference.buffer(16.0),
        step1.drivezone_geometry,
        finalization_context.association_context.step3_allowed_space_geometry,
        case_result.step6_result.output_geometries.polygon_seed_geometry,
        case_result.step6_result.output_geometries.polygon_final_geometry,
        case_result.step6_result.output_geometries.foreign_mask_geometry,
        finalization_context.association_case_result.output_geometries.required_hook_zone_geometry,
        finalization_context.association_case_result.output_geometries.required_rcsdroad_geometry,
        finalization_context.association_case_result.output_geometries.support_rcsdroad_geometry,
    ]
    merged = unary_union([geometry for geometry in focus if geometry is not None and not geometry.is_empty])
    minx, miny, maxx, maxy = merged.bounds
    span = min(MAX_PATCH_SIZE_M, max(180.0, max(maxx - minx, maxy - miny) + 30.0))
    half = span / 2.0
    return reference.x - half, reference.y - half, reference.x + half, reference.y + half


def render_finalization_review_png(
    *,
    out_path: Path,
    finalization_context: FinalizationContext,
    case_result: FinalizationCaseResult,
    debug_render: bool = False,
) -> None:
    step1 = finalization_context.association_context.step1_context
    association_result = finalization_context.association_case_result
    step6_result = case_result.step6_result
    step7_result = case_result.step7_result

    image = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _patch_bounds(finalization_context, case_result)
    _draw_polygon(draw, step1.drivezone_geometry, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    _draw_polygon(draw, step6_result.output_geometries.foreign_mask_geometry, bounds, fill=FOREIGN_MASK_FILL)
    _draw_polygon(
        draw,
        step6_result.output_geometries.polygon_final_geometry,
        bounds,
        fill=FINAL_FILL,
        outline=FINAL_EDGE,
        width=3,
    )

    for road in step1.roads:
        fill = ROAD_COLOR if road.road_id in set(finalization_context.association_context.selected_road_ids) else (95, 95, 95, 170)
        width = 8 if road.road_id in set(finalization_context.association_context.selected_road_ids) else 5
        _draw_line(draw, road.geometry, bounds, fill=fill, width=width)

    for rcsd_road in step1.rcsd_roads:
        _draw_line(draw, rcsd_road.geometry, bounds, fill=VISIBLE_RC_ROAD_EDGE, width=4)

    _draw_line(draw, association_result.output_geometries.support_rcsdroad_geometry, bounds, fill=SUPPORT_EDGE, width=5)
    _draw_line(draw, association_result.output_geometries.required_rcsdroad_geometry, bounds, fill=REQUIRED_EDGE, width=6)
    _draw_point(draw, association_result.output_geometries.required_rcsdnode_geometry, bounds, fill=REQUIRED_EDGE, radius=7)
    _draw_point(
        draw,
        step1.representative_node.geometry,
        bounds,
        fill=GROUP_NODE_COLOR,
        radius=8,
        ring=(255, 255, 255, 255),
        ring_width=2,
    )
    for group in step1.foreign_groups:
        for node in group.nodes:
            _draw_point(draw, node.geometry, bounds, fill=FOREIGN_NODE_COLOR, radius=4)

    overlay_style = STEP67_STYLE[step7_result.visual_review_class]
    _draw_failure_overlay(
        image,
        bounds=bounds,
        focus_geometry=unary_union(
            [
                geometry
                for geometry in (
                    step6_result.output_geometries.polygon_final_geometry,
                    step6_result.output_geometries.must_cover_geometry,
                    step1.representative_node.geometry.buffer(10.0),
                )
                if geometry is not None
            ]
        ),
        step3_state=overlay_style["overlay_key"],
    )

    draw.rectangle((24, 24, IMAGE_SIZE - 24, 120), fill=overlay_style["banner"])
    _draw_text_with_shadow(
        draw,
        xy=(44, 40),
        text=f"{step7_result.step7_state.upper()} / {'已接受' if step7_result.step7_state == 'accepted' else '失败'} / Finalization",
        font=_font(32),
        fill=overlay_style["text"],
        shadow=overlay_style["text_shadow"],
    )
    _draw_text_with_shadow(
        draw,
        xy=(44, 78),
        text=(
            f"case={case_result.case_id}  template={case_result.template_class}  "
            f"step6={step6_result.step6_state}  visual={step7_result.visual_review_class}  "
            f"reason={step7_result.reason}"
        ),
        font=_font(18),
        fill=overlay_style["text"],
        shadow=overlay_style["text_shadow"],
    )
    if debug_render:
        _draw_text_with_shadow(
            draw,
            xy=(44, IMAGE_SIZE - 64),
            text=(
                f"association={case_result.association_state}/{case_result.association_class}  "
                f"signals={len(step6_result.review_signals)}"
            ),
            font=_font(16),
            fill=(20, 20, 20, 255),
            shadow=(255, 255, 255, 255),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
