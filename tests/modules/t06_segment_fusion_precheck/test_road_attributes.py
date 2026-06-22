from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.road_attributes import (
    is_near_advance_right_turn_duplicate,
)


def test_near_advance_right_duplicate_requires_bit_and_coverage() -> None:
    swsd_line = LineString([(0, 0), (10, 0)])
    rcsd_line = LineString([(0, 1), (10, 1)])
    crossing_line = LineString([(5, -20), (5, 20)])

    assert is_near_advance_right_turn_duplicate({"formway": 128}, swsd_line, [rcsd_line])
    assert not is_near_advance_right_turn_duplicate({"formway": 0}, swsd_line, [rcsd_line])
    assert not is_near_advance_right_turn_duplicate(
        {"formway": 128},
        swsd_line,
        [crossing_line],
        buffer_m=1.0,
        min_covered_ratio=0.5,
    )
