from __future__ import annotations

import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.geometry import (
    parse_patch_membership,
    sample_distances,
    swsd_direction_delta_deg,
    tangent_vector,
)


def test_patch_membership_is_a_deduplicated_set() -> None:
    assert parse_patch_membership(" p1,p2,p1, ") == frozenset({"p1", "p2"})


def test_lane_sampling_is_bounded_and_inset() -> None:
    line = LineString([(0, 0), (40, 0)])
    distances = sample_distances(line, spacing_m=8, min_samples=3, max_samples=9)

    assert len(distances) == 6
    assert distances[0] == pytest.approx(1.0)
    assert distances[-1] == pytest.approx(39.0)


def test_swsd_direction_three_reverses_geometry_direction() -> None:
    forward = tangent_vector(LineString([(0, 0), (10, 0)]), 5)
    reverse_geometry = tangent_vector(LineString([(0, 0), (10, 0)]), 5)

    assert swsd_direction_delta_deg(forward, reverse_geometry, 2) == pytest.approx(0)
    assert swsd_direction_delta_deg(forward, reverse_geometry, 3) == pytest.approx(180)
    assert swsd_direction_delta_deg(forward, reverse_geometry, 1) == pytest.approx(0)
