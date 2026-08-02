from shapely.geometry import Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_road_surface_portal import (
    build_road_surface_portal_boundary,
)


def test_portal_restores_connectivity_inside_allowed_surface() -> None:
    boundary, portal, audit = build_road_surface_portal_boundary(
        allowed_surface=box(0, 0, 30, 10),
        direction_boundary=unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)]),
        terminals={"left": Point(5, 5), "right": Point(25, 5)},
        bridge_half_width_m=5.0,
    )

    assert boundary.geom_type == "Polygon"
    assert portal is not None
    assert audit["applied"] is True
    assert audit["reason"] == "connectivity_restored"
    assert audit["after"]["equivalent"] is True
    assert boundary.difference(box(0, 0, 30, 10)).area == 0.0


def test_portal_preserves_legitimate_split_allowed_surface() -> None:
    allowed = unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)])
    boundary, portal, audit = build_road_surface_portal_boundary(
        allowed_surface=allowed,
        direction_boundary=allowed,
        terminals={"left": Point(5, 5), "right": Point(25, 5)},
        bridge_half_width_m=5.0,
    )

    assert boundary.geom_type == "MultiPolygon"
    assert portal is None
    assert audit["applied"] is False
    assert audit["before"]["equivalent"] is True


def test_portal_does_not_operate_when_terminal_is_outside_allowed_surface() -> None:
    boundary, portal, audit = build_road_surface_portal_boundary(
        allowed_surface=box(0, 0, 10, 10),
        direction_boundary=box(0, 0, 10, 10),
        terminals={"inside": Point(5, 5), "outside": Point(25, 5)},
        bridge_half_width_m=5.0,
    )

    assert boundary.equals(box(0, 0, 10, 10))
    assert portal is None
    assert audit["reason"] == "connectivity_not_comparable"


def test_portal_seeds_missing_required_terminal_then_connects_inside_surface() -> None:
    boundary, portal, audit = build_road_surface_portal_boundary(
        allowed_surface=box(0, 0, 40, 10),
        direction_boundary=box(0, 0, 10, 10),
        terminals={"existing": Point(5, 5), "missing": Point(35, 5)},
        bridge_half_width_m=4.0,
    )

    assert boundary is not None
    assert portal is not None
    assert audit["missing_terminal_seed_count"] == 1
    assert audit["reason"] == "connectivity_restored"
    assert audit["after"]["equivalent"] is True


def test_portal_falls_back_to_complete_constrained_component_without_overlay_slit() -> None:
    allowed = unary_union(
        [
            box(0, 0, 4, 20),
            box(0, 0, 30, 4),
            box(26, 0, 30, 20),
        ]
    )
    boundary, portal, audit = build_road_surface_portal_boundary(
        allowed_surface=allowed,
        direction_boundary=unary_union(
            [
                box(0, 16, 4, 20),
                box(26, 16, 30, 20),
            ]
        ),
        terminals={"left": Point(2, 18), "right": Point(28, 18)},
        bridge_half_width_m=1.0,
        seed_missing_terminals=False,
        allow_geodesic_growth=True,
        geodesic_step_m=1.0,
        geodesic_max_iterations=1,
    )

    assert boundary.geom_type == "Polygon"
    assert boundary.equals(allowed)
    assert portal is not None
    assert audit["allowed_component_fallback_applied"] is True
    assert audit["after"]["equivalent"] is True
    fallback = audit["allowed_component_fallback_audit"]
    assert fallback["candidate_basis"].startswith("complete_constrained_allowed")
    assert fallback["relevant_component_missing_area_m2"] == 0.0
