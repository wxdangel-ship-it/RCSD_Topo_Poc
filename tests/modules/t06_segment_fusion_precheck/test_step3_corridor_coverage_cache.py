from __future__ import annotations

from shapely.geometry import LineString, Polygon

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_replacement_unit_support as unit_support
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_corridor_coverage_cache import (
    _buffered_corridor_cache_size,
    _corridor_coverage_decision_cache_size,
    cached_buffered_road_corridor,
    cached_corridor_coverage_decision,
    preserve_corridor_coverage_decisions,
)


def test_corridor_decision_cache_is_scoped_and_geometry_sensitive() -> None:
    line = LineString([(0.0, 0.0), (10.0, 0.0)])
    road = LineString([(0.0, 0.0), (10.0, 0.0)])
    surface = Polygon([(0.0, -1.0), (1.0, -1.0), (1.0, 1.0), (0.0, 1.0)])
    calls = 0

    def compute() -> tuple[bool, bool]:
        nonlocal calls
        calls += 1
        return False, True

    with preserve_corridor_coverage_decisions():
        first = cached_corridor_coverage_decision(
            line=line,
            road_geometries=[road],
            allowed_surface=surface,
            buffer_m=15.0,
            compute=compute,
        )
        second = cached_corridor_coverage_decision(
            line=line,
            road_geometries=[road],
            allowed_surface=surface,
            buffer_m=15.0,
            compute=compute,
        )
        changed = cached_corridor_coverage_decision(
            line=line,
            road_geometries=[road],
            allowed_surface=surface,
            buffer_m=20.0,
            compute=compute,
        )

        assert first == second == changed == (False, True)
        assert calls == 2
        assert _corridor_coverage_decision_cache_size() == 2

    assert _corridor_coverage_decision_cache_size() == 0


def test_corridor_decision_cache_is_disabled_without_scope() -> None:
    line = LineString([(0.0, 0.0), (1.0, 0.0)])
    calls = 0

    def compute() -> tuple[bool, bool]:
        nonlocal calls
        calls += 1
        return False, False

    for _ in range(2):
        cached_corridor_coverage_decision(
            line=line,
            road_geometries=[line],
            allowed_surface=None,
            buffer_m=15.0,
            compute=compute,
        )

    assert calls == 2


def test_buffered_corridor_cache_is_bounded_to_scope_and_geometry_sensitive() -> None:
    road_a = LineString([(0.0, 0.0), (10.0, 0.0)])
    road_b = LineString([(10.0, 0.0), (20.0, 0.0)])
    calls = 0

    def compute(buffer_m: float) -> Polygon:
        nonlocal calls
        calls += 1
        return road_a.union(road_b).buffer(buffer_m)

    with preserve_corridor_coverage_decisions():
        first = cached_buffered_road_corridor(
            road_geometries=[road_a, road_b],
            buffer_m=15.0,
            compute=lambda: compute(15.0),
        )
        second = cached_buffered_road_corridor(
            road_geometries=[road_b, road_a],
            buffer_m=15.0,
            compute=lambda: compute(15.0),
        )
        changed = cached_buffered_road_corridor(
            road_geometries=[road_a, road_b],
            buffer_m=20.0,
            compute=lambda: compute(20.0),
        )

        assert first is second
        assert changed is not first
        assert calls == 2
        assert _buffered_corridor_cache_size() == 2

    assert _buffered_corridor_cache_size() == 0


def test_replacement_unit_corridor_reuses_scalar_decision_across_equal_replays(monkeypatch) -> None:
    calls = 0
    original_unary_union = unit_support.unary_union

    def counted_unary_union(geometries):
        nonlocal calls
        calls += 1
        return original_unary_union(geometries)

    monkeypatch.setattr(unit_support, "unary_union", counted_unary_union)
    with preserve_corridor_coverage_decisions():
        first = unit_support._road_corridor_coverage_failed_from_roads(
            {"geometry": LineString([(0.0, 0.0), (10.0, 0.0)])},
            [{"geometry": LineString([(0.0, 0.0), (10.0, 0.0)])}],
        )
        second = unit_support._road_corridor_coverage_failed_from_roads(
            {"geometry": LineString([(0.0, 0.0), (10.0, 0.0)])},
            [{"geometry": LineString([(0.0, 0.0), (10.0, 0.0)])}],
        )

    assert first == second == (False, False)
    assert calls == 1
