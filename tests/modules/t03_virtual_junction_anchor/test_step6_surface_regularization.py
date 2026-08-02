from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_surface_regularization import (
    regularize_surface_with_legal_edge_trace,
)


def test_fills_only_algorithmic_hole_inside_permitted_surface() -> None:
    allowed = box(0, 0, 20, 20)
    surface = allowed.difference(Point(10, 10).buffer(2))

    output, audit = regularize_surface_with_legal_edge_trace(
        surface=surface,
        allowed_surface=allowed,
        direction_boundary=allowed,
        foreign_mask=None,
        smoothing_distance_m=0,
    )

    assert output is not None
    assert len(output.interiors) == 0
    assert audit["filled_hole_count"] == 1


def test_retains_hole_excluded_by_legal_road_surface() -> None:
    hole = Point(10, 10).buffer(2)
    allowed = box(0, 0, 20, 20).difference(hole)
    surface = box(0, 0, 20, 20).difference(hole)

    output, audit = regularize_surface_with_legal_edge_trace(
        surface=surface,
        allowed_surface=allowed,
        direction_boundary=box(0, 0, 20, 20),
        foreign_mask=None,
        smoothing_distance_m=0,
    )

    assert output is not None
    assert len(output.interiors) == 1
    assert audit["filled_hole_count"] == 0
    assert audit["hole_decisions"][0]["decision"] == "retain_source_or_constraint_void"


def test_retains_hole_required_by_foreign_mask() -> None:
    allowed = box(0, 0, 20, 20)
    foreign = Point(10, 10).buffer(2)
    surface = allowed.difference(foreign)

    output, audit = regularize_surface_with_legal_edge_trace(
        surface=surface,
        allowed_surface=allowed,
        direction_boundary=allowed,
        foreign_mask=foreign,
        smoothing_distance_m=0,
    )

    assert output is not None
    assert len(output.interiors) == 1
    assert audit["filled_hole_count"] == 0


def test_does_not_force_disconnected_permitted_surfaces_into_one_polygon() -> None:
    allowed = unary_union([box(0, 0, 4, 4), box(10, 0, 14, 4)])

    output, audit = regularize_surface_with_legal_edge_trace(
        surface=allowed,
        allowed_surface=allowed,
        direction_boundary=allowed,
        foreign_mask=None,
        smoothing_distance_m=1.6,
    )

    assert output is not None
    assert output.geom_type == "MultiPolygon"
    assert len(output.geoms) == 2
    assert audit["forced_single_polygon"] is False


def test_invalid_input_is_blocked_without_buffer_zero_silent_fix() -> None:
    invalid_bowtie = Polygon([(0, 0), (4, 4), (0, 4), (4, 0), (0, 0)])
    assert invalid_bowtie.is_valid is False

    output, audit = regularize_surface_with_legal_edge_trace(
        surface=invalid_bowtie,
        allowed_surface=box(-1, -1, 5, 5),
        direction_boundary=box(-1, -1, 5, 5),
        foreign_mask=None,
        smoothing_distance_m=1,
    )

    assert output is None
    assert audit["applied"] is False
    assert audit["reason"] == "invalid_input_geometry"
    assert audit["invalid_input_roles"] == ["surface"]
    assert audit["silent_fix"] is False
    assert audit["source_geometry_modified"] is False
