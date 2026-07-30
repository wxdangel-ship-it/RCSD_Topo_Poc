from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_metrics import (
    max_sample_turn,
    surface_coverage,
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
