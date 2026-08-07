from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_teacher import (
    GeometryRoad,
    build_mixed_geometry_variant,
    build_rcsd_only_geometry_variant,
)


def _road(
    road_id: str,
    start: str,
    end: str,
    coordinates,
) -> GeometryRoad:
    return GeometryRoad(
        road_id=road_id,
        start_node_id=start,
        end_node_id=end,
        geometry=LineString(coordinates),
    )


def test_rcsd_only_teacher_assigns_two_distinct_boundary_endpoints() -> None:
    roads = {
        "ar": _road("ar", "a", "b", [(0, 0), (10, 0)]),
        "source": _road("source", "s0", "s1", [(-5, 0), (0, 0)]),
        "target": _road("target", "t0", "t1", [(10, 0), (15, 0)]),
    }
    result = build_rcsd_only_geometry_variant(
        ["ar"],
        source_plan_road_ids=["source"],
        target_plan_road_ids=["target"],
        roads=roads,
        max_gap_m=1.0,
    )
    assert result["teacher_complete"]
    assert result["source_attachment"]["selected_endpoint_index"] == 0
    assert result["target_attachment"]["selected_endpoint_index"] == 1
    assert result["source_attachment"]["gap_m"] == 0.0
    assert result["target_attachment"]["gap_m"] == 0.0


def test_mixed_teacher_emits_rcsd_attachment_and_middle_splice() -> None:
    roads = {
        "ar": _road("ar", "a", "b", [(0, 0), (5, 0)]),
        "ordinary": _road(
            "ordinary",
            "s0",
            "s1",
            [(-5, 0), (0, 0)],
        ),
        "swsd": _road("swsd", "w0", "w1", [(5, 1), (10, 1)]),
    }
    result = build_mixed_geometry_variant(
        ["ar"],
        rcsd_side="source",
        rcsd_plan_road_ids=["ordinary"],
        fixed_swsd_road_ids=["swsd"],
        roads=roads,
        max_gap_m=2.0,
    )
    assert result["teacher_complete"]
    assert result["source_attachment"]["target_ordinary_road_id"] == "ordinary"
    assert result["target_attachment"] is None
    assert result["middle_splice"]["rcsd_road_id"] == "ar"
    assert result["middle_splice"]["swsd_road_id"] == "swsd"
    assert result["middle_splice"]["gap_m"] == 1.0


def test_teacher_masks_large_geometry_gap() -> None:
    roads = {
        "ar": _road("ar", "a", "b", [(0, 0), (1, 0)]),
        "source": _road("source", "s0", "s1", [(100, 0), (101, 0)]),
        "target": _road("target", "t0", "t1", [(200, 0), (201, 0)]),
    }
    result = build_rcsd_only_geometry_variant(
        ["ar"],
        source_plan_road_ids=["source"],
        target_plan_road_ids=["target"],
        roads=roads,
        max_gap_m=5.0,
    )
    assert not result["teacher_complete"]
    assert result["reason"] == "ATTACHMENT_GAP_EXCEEDS_LIMIT"
