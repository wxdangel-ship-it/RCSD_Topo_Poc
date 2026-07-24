from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_quality import (
    apply_review_flags,
    audit_built_road_geometry,
)


def test_completion_introduced_hairpin_requires_segment_fallback() -> None:
    source = LineString([(0, 0), (10, 0)])
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "s",
                "patch_road_key": "p:1",
                "realization": "built",
                "geometry": LineString([(0, 0), (10, 0), (1, 1)]),
            }
        ],
        crs="EPSG:32650",
    )
    centers = gpd.GeoDataFrame(
        [{"patch_road_key": "p:1", "geometry": source}],
        crs="EPSG:32650",
    )
    config = SegmentFirstConfig(
        **{
            name: Path(name)
            for name in (
                "patch_root",
                "swsd_road_path",
                "swsd_node_path",
                "t01_road_path",
                "t01_node_path",
                "t01_segment_path",
                "t07_surface_path",
                "t03_surface_path",
                "t04_surface_path",
                "full_rcsd_road_path",
                "full_rcsd_node_path",
                "output_dir",
            )
        },
        run_id="run",
    )
    completions = gpd.GeoDataFrame(
        columns=["road_id", "length_m", "geometry"],
        geometry="geometry",
        crs="EPSG:32650",
    )
    result = audit_built_road_geometry(
        roads,
        centers,
        completions,
        config=config,
    )
    assert result.fallback_segment_ids == {"s"}
    assert result.summary["hard_failure_count"] == 1


def test_surface_inferred_road_is_supported_but_not_counted_as_observed() -> None:
    source = LineString([(0, 0), (10, 0)])
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 2,
                "segment_id": "s",
                "patch_road_key": "p:1",
                "realization": "built",
                "surface_inferred_fraction": 1.0,
                "geometry": LineString([(0, 3.5), (10, 3.5)]),
            }
        ],
        crs="EPSG:32650",
    )
    centers = gpd.GeoDataFrame(
        [{"patch_road_key": "p:1", "geometry": source}],
        crs="EPSG:32650",
    )
    config = SegmentFirstConfig(
        **{
            name: Path(name)
            for name in (
                "patch_root",
                "swsd_road_path",
                "swsd_node_path",
                "t01_road_path",
                "t01_node_path",
                "t01_segment_path",
                "t07_surface_path",
                "t03_surface_path",
                "t04_surface_path",
                "full_rcsd_road_path",
                "full_rcsd_node_path",
                "output_dir",
            )
        },
        run_id="run",
    )
    completions = gpd.GeoDataFrame(
        columns=["road_id", "length_m", "geometry"],
        geometry="geometry",
        crs="EPSG:32650",
    )

    result = audit_built_road_geometry(
        roads,
        centers,
        completions,
        config=config,
    )

    assert not result.fallback_segment_ids
    assert result.audit.iloc[0]["observed_fraction"] == 0.0
    assert result.audit.iloc[0]["surface_inferred_fraction"] == 1.0


def test_soft_findings_propagate_to_formal_road_review_flag() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "review_required": False,
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 2,
                "review_required": False,
                "geometry": LineString([(0, 1), (1, 1)]),
            },
            {
                "id": 3,
                "review_required": True,
                "geometry": LineString([(0, 2), (1, 2)]),
            },
        ],
        crs="EPSG:32650",
    )
    endpoint = gpd.GeoDataFrame(
        [
            {
                "road_id": 1,
                "review_required": True,
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ],
        crs=roads.crs,
    )
    quality = gpd.GeoDataFrame(
        [
            {
                "road_id": 2,
                "review_required": True,
                "geometry": LineString([(0, 1), (1, 1)]),
            }
        ],
        crs=roads.crs,
    )

    result = apply_review_flags(roads, endpoint, quality)

    assert result["review_required"].tolist() == [True, True, True]
