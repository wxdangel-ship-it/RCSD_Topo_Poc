from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import (
    _normalize_crs,
    _topology_audit,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError


def test_missing_crs_is_blocked() -> None:
    vectors = {"roads": gpd.GeoDataFrame({"geometry": [Point(0, 0)]})}

    with pytest.raises(T12ContractError, match="missing CRS"):
        _normalize_crs(vectors, None)


def test_explicit_crs_transform_is_audited() -> None:
    vectors = {
        "points": gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)]},
            crs="EPSG:4326",
        )
    }

    processing_crs, audit = _normalize_crs(vectors, "EPSG:3857")

    assert processing_crs == "EPSG:3857"
    assert audit["transform_applied"] == {"points": True}
    assert str(vectors["points"].crs) == "EPSG:3857"


def test_endpoint_gap_is_reported_without_fixing_geometry() -> None:
    roads = gpd.GeoDataFrame(
        {
            "id": ["r"],
            "snodeid": ["a"],
            "enodeid": ["missing"],
            "geometry": [LineString([(0, 0), (1, 0)])],
        },
        crs="EPSG:3857",
    )
    nodes = gpd.GeoDataFrame(
        {"id": ["a"], "geometry": [Point(0, 0)]},
        crs="EPSG:3857",
    )

    audit = _topology_audit(roads, nodes)

    assert audit["endpoint_missing_count"] == 1
    assert audit["endpoint_missing_node_ids"] == ["missing"]
    assert audit["silent_fix"] is False
