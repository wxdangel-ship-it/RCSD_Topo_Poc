from __future__ import annotations

from shapely.geometry import LineString, Polygon

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_corridor_coverage_cache import (
    _corridor_coverage_decision_cache_size,
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
