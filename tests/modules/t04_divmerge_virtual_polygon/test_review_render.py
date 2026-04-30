from __future__ import annotations

from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.review_render import (
    BACKGROUND,
    DRIVEZONE_EDGE,
    DRIVEZONE_FILL,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    _draw_polygon,
)


def test_draw_polygon_preserves_road_surface_interior_holes() -> None:
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    polygon = Polygon(
        [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0), (1.0, 1.0)],
        holes=[[(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]],
    )

    _draw_polygon(
        draw,
        polygon,
        (0.0, 0.0, 10.0, 10.0),
        fill=DRIVEZONE_FILL,
        outline=DRIVEZONE_EDGE,
        width=2,
    )

    assert image.getpixel((510, 510)) == BACKGROUND
    assert image.getpixel((216, 803)) == DRIVEZONE_FILL
