from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_pipeline import (
    _compare_current_rcsd,
    _comparison_summary,
)


def test_current_rcsd_comparison_uses_same_direction_multi_segment_corridor() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "directional_road_id": "road:forward",
                "parent_swsd_unit_id": "road",
                "travel_side": "forward",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    current_rcsd = gpd.GeoDataFrame(
        [
            {"id": "rcsd-a", "geometry": LineString([(0, 1), (50, 1)])},
            {"id": "rcsd-b", "geometry": LineString([(50, 1), (100, 1)])},
            {"id": "opposite", "geometry": LineString([(100, -1), (0, -1)])},
        ],
        crs=roads.crs,
    )

    comparison = _compare_current_rcsd(roads, current_rcsd)
    row = comparison.iloc[0]

    assert row["comparison_state"] == "corridor_matched_for_shape_audit"
    assert row["matched_rcsd_candidate_count"] == 2
    assert json.loads(row["matched_rcsd_road_ids_json"]) == ["rcsd-a", "rcsd-b"]
    assert row["corridor_distance_median_m"] == pytest.approx(1.0)
    assert row["corridor_distance_p95_m"] == pytest.approx(1.0)
    assert row["corridor_coverage_within_2m_ratio"] == pytest.approx(1.0)

    summary = _comparison_summary(comparison)
    assert summary["matched_count"] == 1
    assert summary["corridor_coverage_within_2m_ratio"] == pytest.approx(1.0)


def test_sd_parent_is_not_compared_as_high_precision_directional_road() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "directional_road_id": "road:sd_parent",
                "parent_swsd_unit_id": "road",
                "travel_side": "sd_parent",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    current_rcsd = gpd.GeoDataFrame(
        [{"id": "rcsd", "geometry": LineString([(0, 0), (10, 0)])}],
        crs=roads.crs,
    )

    comparison = _compare_current_rcsd(roads, current_rcsd)

    assert comparison.empty
