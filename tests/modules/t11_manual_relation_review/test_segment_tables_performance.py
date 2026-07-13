from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point

from rcsd_topo_poc.modules.t11_manual_relation_review.segment_tables import _rcsd_50m_context


def test_rcsd_50m_spatial_index_preserves_exact_threshold_and_order() -> None:
    features = gpd.GeoDataFrame(
        {"feature_id": ["road:z", "node:a", "road:b"]},
        geometry=[Point(50, 0), Point(3, 4), Point(-50, 0)],
        crs="EPSG:3857",
    )

    result = _rcsd_50m_context({"geometry": Point(0, 0)}, features)

    assert result == {
        "hint": "50m内有RCSD",
        "feature_count": 3,
        "nearest_ids": "node:a|road:b|road:z",
        "nearest_distance_m": 5.0,
    }


def test_rcsd_50m_spatial_index_preserves_exact_global_nearest_distance() -> None:
    features = gpd.GeoDataFrame(
        {"feature_id": ["node:far", "road:near"]},
        geometry=[Point(100, 0), Point(75, 0)],
        crs="EPSG:3857",
    )

    result = _rcsd_50m_context({"geometry": Point(0, 0)}, features)

    assert result == {
        "hint": "无RCSD",
        "feature_count": 0,
        "nearest_ids": "",
        "nearest_distance_m": 75.0,
    }
