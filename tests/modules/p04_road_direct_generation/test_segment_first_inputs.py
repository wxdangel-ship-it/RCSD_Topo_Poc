from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_inputs import (
    accepted_surface,
    require_columns,
)


def test_t07_review_surface_is_not_accepted() -> None:
    frame = gpd.GeoDataFrame(
        [
            {"id": "ok", "final_state": "accepted", "geometry": LineString([(0, 0), (1, 0)]).buffer(1)},
            {"id": "review", "final_state": "review_required", "geometry": LineString([(2, 0), (3, 0)]).buffer(1)},
        ],
        crs="EPSG:32650",
    )
    result = accepted_surface(frame, "t07")
    assert result["id"].tolist() == ["ok"]


def test_t03_requires_explicit_accepted_and_success() -> None:
    frame = gpd.GeoDataFrame(
        [
            {"id": "ok", "success": True, "acceptance_class": "accepted", "geometry": LineString([(0, 0), (1, 0)]).buffer(1)},
            {"id": "failed", "success": False, "acceptance_class": "accepted", "geometry": LineString([(2, 0), (3, 0)]).buffer(1)},
        ],
        crs="EPSG:32650",
    )
    assert accepted_surface(frame, "t03")["id"].tolist() == ["ok"]


def test_required_t01_contract_is_explicit() -> None:
    frame = gpd.GeoDataFrame(
        [{"id": "s1", "geometry": LineString([(0, 0), (1, 0)])}],
        crs="EPSG:32650",
    )
    with pytest.raises(ValueError, match="pair_nodes"):
        require_columns(
            frame,
            ("id", "sgrade", "pair_nodes", "junc_nodes", "roads"),
            "t01_segments",
        )
