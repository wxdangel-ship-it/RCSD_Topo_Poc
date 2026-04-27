from __future__ import annotations

from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_render import (
    BACKGROUND_COLOR,
    DRIVEZONE_EDGE,
    DRIVEZONE_FILL,
    IMAGE_SIZE,
    _draw_polygon,
)


def test_draw_polygon_preserves_interior_holes() -> None:
    image = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), BACKGROUND_COLOR)
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

    assert image.getpixel((512, 512)) == BACKGROUND_COLOR
    assert image.getpixel((205, 819)) == DRIVEZONE_FILL


def test_draw_polygon_preserves_holes_on_mask_images() -> None:
    image = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
    draw = ImageDraw.Draw(image)
    polygon = Polygon(
        [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0), (1.0, 1.0)],
        holes=[[(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]],
    )

    _draw_polygon(draw, polygon, (0.0, 0.0, 10.0, 10.0), fill=255)

    assert image.getpixel((512, 512)) == 0
    assert image.getpixel((205, 819)) == 255
