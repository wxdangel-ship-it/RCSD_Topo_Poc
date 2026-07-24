from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_comparison import (
    compare_frozen_v2_roads,
)


def _roads(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32650")


def test_frozen_v2_comparison_prefers_same_parent_and_travel_side() -> None:
    v3 = _roads(
        [
            {
                "v3_road_id": "p:forward",
                "parent_swsd_unit_id": "p",
                "travel_side": "forward",
                "road_representation": "directional_carriageway",
                "support_state": "partial_hp_supported",
                "geometry": LineString([(0, 1), (100, 1)]),
            }
        ]
    )
    frozen = _roads(
        [
            {
                "directional_road_id": "p:forward",
                "parent_swsd_unit_id": "p",
                "travel_side": "forward",
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "directional_road_id": "p:reverse",
                "parent_swsd_unit_id": "p",
                "travel_side": "reverse",
                "geometry": LineString([(0, 1.1), (100, 1.1)]),
            },
        ]
    )

    result, summary = compare_frozen_v2_roads(v3, frozen, sample_spacing_m=5.0)

    row = result.iloc[0]
    assert row.frozen_v2_road_id == "p:forward"
    assert row.match_method == "same_parent_same_side"
    assert row.mean_sample_distance_m == pytest.approx(1.0)
    assert summary["matched_count"] == 1
    assert summary["unmatched_count"] == 0


def test_frozen_v2_comparison_keeps_unmatched_v3_road_visible() -> None:
    v3 = _roads(
        [
            {
                "v3_road_id": "missing",
                "parent_swsd_unit_id": "missing",
                "travel_side": "forward",
                "road_representation": "shared_physical",
                "support_state": "sd_only",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ]
    )
    frozen = _roads(
        [
            {
                "directional_road_id": "other",
                "parent_swsd_unit_id": "other",
                "travel_side": "forward",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ]
    )

    result, summary = compare_frozen_v2_roads(v3, frozen)

    assert result.iloc[0].comparison_state == "no_frozen_v2_parent_match"
    assert summary["matched_count"] == 0
    assert summary["unmatched_count"] == 1
