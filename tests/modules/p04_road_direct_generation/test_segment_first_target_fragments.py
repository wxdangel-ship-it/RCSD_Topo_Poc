from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from shapely import get_x, get_y, line_interpolate_point
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_fragments import (
    _bearings_between_points,
    build_target_carrier_fragments,
)


def test_one_patch_road_is_partitioned_across_adjacent_target_segments() -> None:
    centers = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p1:r1",
                "source_patch_id": "p1",
                "road_id": "r1",
                "center_lane_id": "l1",
                "lane_count": 2,
                "geometry": LineString([(0, 1), (20, 1)]),
            }
        ],
        crs="EPSG:32650",
    )
    baseline = centers.copy()
    baseline["assigned_segment_id"] = "s1"
    baseline["target_swsd_road_id"] = "m1"
    baseline["carrier_role"] = "directional_corridor"
    baseline["takeover_eligible"] = True
    targets = gpd.GeoDataFrame(
        [
            _target("s1", "m1", 0, 10),
            _target("s2", "m2", 10, 20),
        ],
        crs=centers.crs,
    )
    members = gpd.GeoDataFrame(
        [
            _member("m1", "s1", 0, 10),
            _member("m2", "s2", 10, 20),
        ],
        crs=centers.crs,
    )
    anchors = gpd.GeoDataFrame(
        [
            _anchor("s1", 0, 10),
            _anchor("s2", 10, 20),
        ],
        crs=centers.crs,
    )

    result = build_target_carrier_fragments(
        centers,
        baseline,
        targets,
        anchors,
        members,
        sample_spacing_m=1.0,
        max_distance_m=5.0,
        max_angle_deg=45.0,
        run_id="target-fragments",
    )

    fragments = result.assignments[
        result.assignments["assignment_source"].eq("target_segment_fragment")
    ]
    assert set(fragments["assigned_segment_id"]) == {"s1", "s2"}
    assert set(fragments["target_swsd_road_id"]) == {"m1", "m2"}
    assert len(fragments) == 2
    for geometry in fragments.geometry:
        assert geometry.distance(centers.iloc[0].geometry) == 0.0
        assert geometry.length < centers.iloc[0].geometry.length
    assert result.summary["multi_target_patch_road_count"] == 1


def test_batch_point_bearings_preserve_scalar_operation_order() -> None:
    lines = np.asarray(
        [
            LineString([(0.0, 0.0), (9.75, 3.125), (20.0, -1.0)]),
            LineString([(4.0, 8.0), (-2.5, 13.25), (-9.0, 1.5)]),
        ],
        dtype=object,
    )
    starts = line_interpolate_point(lines, np.asarray([2.125, 3.75]))
    ends = line_interpolate_point(lines, np.asarray([10.875, 11.25]))
    expected = [
        math.degrees(
            math.atan2(
                float(get_y(end) - get_y(start)),
                float(get_x(end) - get_x(start)),
            )
        )
        % 180.0
        for start, end in zip(starts, ends)
    ]

    assert _bearings_between_points(starts, ends) == expected


def _target(segment_id: str, member_id: str, start: float, end: float) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "target_class": "core_trunk",
        "target_required": True,
        "swsd_road_ids": member_id,
        "geometry": LineString([(start, 0), (end, 0)]),
    }


def _member(member_id: str, segment_id: str, start: float, end: float) -> dict[str, object]:
    return {
        "id": member_id,
        "segmentid": segment_id,
        "geometry": LineString([(start, 0), (end, 0)]),
    }


def _anchor(segment_id: str, start: float, end: float) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "anchor_source": "t06_replaceability_geometry",
        "geometry": LineString([(start, 0), (end, 0)]),
    }
