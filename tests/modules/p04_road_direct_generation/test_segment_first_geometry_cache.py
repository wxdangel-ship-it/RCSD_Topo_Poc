from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_cache import (
    buffered_union,
)


def test_buffered_union_reuses_exact_geometry_for_same_live_frame() -> None:
    frame = gpd.GeoDataFrame(
        {"geometry": [Point(0, 0), Point(3, 0)]},
        geometry="geometry",
        crs="EPSG:32650",
    )

    first = buffered_union(frame, 1.0)
    second = buffered_union(frame, 1.0)

    assert second is first
    assert first.equals(frame.geometry.union_all().buffer(1.0))


def test_buffered_union_returns_empty_geometry_for_empty_frame() -> None:
    frame = gpd.GeoDataFrame(
        {"geometry": []},
        geometry="geometry",
        crs="EPSG:32650",
    )

    result = buffered_union(frame, 1.0)

    assert result.is_empty
