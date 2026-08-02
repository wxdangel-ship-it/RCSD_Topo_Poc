from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from shapely import is_prepared, union_all
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_metrics import (
    _surface_part_index,
    max_sample_turn,
    surface_coverage,
    surface_coverage_at_least,
    surface_coverage_runtime_stats,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_cache import (
    buffered_union,
)


def test_max_sample_turn_matches_original_sampling_contract() -> None:
    geometry = LineString([(0, 0), (4, 0), (4, 4), (8, 4)])
    spacing = 2.0
    count = max(3, int(math.ceil(geometry.length / spacing)) + 1)
    points = [
        geometry.interpolate(value)
        for value in np.linspace(0.0, geometry.length, count)
    ]
    expected = 0.0
    for index in range(1, len(points) - 1):
        first = np.array(
            [
                points[index].x - points[index - 1].x,
                points[index].y - points[index - 1].y,
            ]
        )
        second = np.array(
            [
                points[index + 1].x - points[index].x,
                points[index + 1].y - points[index].y,
            ]
        )
        denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
        if denominator <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
        expected = max(expected, math.degrees(math.acos(cosine)))

    first_result = max_sample_turn(geometry, spacing)
    second_result = max_sample_turn(geometry, spacing)

    assert first_result == expected
    assert second_result == first_result


def test_surface_coverage_preserves_exact_intersection_ratio() -> None:
    line = LineString([(0.0, 0.0), (10.0, 0.0)])
    surface = box(2.0, -1.0, 8.0, 1.0)

    first = surface_coverage(line, surface)
    second = surface_coverage(LineString(line.coords), surface)

    assert first == 0.6
    assert second == first


def test_surface_coverage_indexes_large_multipolygon_without_value_drift() -> None:
    surface = union_all(
        [
            box(index * 4.0, -1.0, index * 4.0 + 2.0, 1.0)
            for index in range(32)
        ]
    )
    line = LineString([(-1.0, 0.0), (129.0, 0.0)])
    expected = float(line.intersection(surface).length / line.length)

    first_index = _surface_part_index(surface)
    actual = surface_coverage(line, surface)
    second_index = _surface_part_index(surface)

    assert first_index is not None
    assert second_index is not None
    assert second_index[0] is first_index[0]
    assert second_index[1] is first_index[1]
    assert actual == expected


def test_surface_coverage_uses_native_component_terminal_predicates() -> None:
    surface = union_all(
        [
            box(index * 4.0, -1.0, index * 4.0 + 2.0, 1.0)
            for index in range(32)
        ]
    )
    lines = [
        LineString([(0.25, 0.0), (1.75, 0.0)]),
        LineString([(2.25, 0.0), (3.75, 0.0)]),
        LineString([(-1.0, 0.0), (3.0, 0.0)]),
    ]
    expected = [
        float(line.intersection(surface).length / line.length)
        for line in lines
    ]
    before = surface_coverage_runtime_stats()

    actual = [surface_coverage(line, surface) for line in lines]
    after = surface_coverage_runtime_stats()

    assert actual == expected
    assert after["terminal_covers_count"] == before["terminal_covers_count"] + 1
    assert after["terminal_disjoint_count"] == (
        before["terminal_disjoint_count"] + 1
    )
    assert after["multipolygon_index_query_count"] == (
        before["multipolygon_index_query_count"] + 1
    )
    assert after["native_component_prepare_count"] >= (
        before["native_component_prepare_count"] + 1
    )


def test_surface_coverage_preserves_buffered_union_numeric_value() -> None:
    frame = gpd.GeoDataFrame(
        {
            "geometry": [
                box(index * 2.0, -2.0, index * 2.0 + 3.0, 2.0)
                for index in range(32)
            ]
        },
        crs="EPSG:32650",
    )
    surface = buffered_union(frame, 1.0)
    lines = [
        LineString([(value, -3.0), (value + 1.0, 3.0)])
        for value in np.linspace(0.0, 62.0, 24)
    ]
    expected = [
        float(line.intersection(surface).length / line.length)
        for line in lines
    ]

    actual = [surface_coverage(line, surface) for line in lines]
    assert surface.geom_type == "Polygon"
    assert actual == expected


def test_surface_coverage_at_least_uses_exact_terminal_predicates() -> None:
    surface = box(0.0, 0.0, 10.0, 10.0)
    lines = [
        LineString([(1.0, 1.0), (9.0, 9.0)]),
        LineString([(20.0, 20.0), (30.0, 30.0)]),
        LineString([(-5.0, 5.0), (15.0, 5.0)]),
    ]
    threshold = 0.8
    expected = [
        float(line.intersection(surface).length / line.length) + 1e-9
        >= threshold
        for line in lines
    ]
    before = surface_coverage_runtime_stats()

    actual = [
        surface_coverage_at_least(
            line,
            surface,
            threshold,
            epsilon=1e-9,
        )
        for line in lines
    ]
    after = surface_coverage_runtime_stats()

    assert actual == expected
    assert is_prepared(surface)
    assert after["threshold_covers_count"] == before["threshold_covers_count"] + 1
    assert after["threshold_disjoint_count"] == before["threshold_disjoint_count"] + 1
    assert after["threshold_exact_fallback_count"] == (
        before["threshold_exact_fallback_count"] + 1
    )
    assert after["unsafe_local_reconstruction_count"] == 0
