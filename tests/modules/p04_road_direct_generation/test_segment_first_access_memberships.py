from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_nodes import (
    resolve_road_endpoint_junctions,
)


CRS = "EPSG:32650"


def _config() -> SegmentFirstConfig:
    paths = [Path(f"input-{index}") for index in range(11)]
    return SegmentFirstConfig(
        patch_root=paths[0],
        swsd_road_path=paths[1],
        swsd_node_path=paths[2],
        t01_road_path=paths[3],
        t01_node_path=paths[4],
        t01_segment_path=paths[5],
        t07_surface_path=paths[6],
        t03_surface_path=paths[7],
        t04_surface_path=paths[8],
        full_rcsd_road_path=paths[9],
        full_rcsd_node_path=paths[10],
        output_dir=Path("output"),
        run_id="missing-access-geometry",
        relation_endpoint_max_distance_m=20.0,
    )


def _roads() -> gpd.GeoDataFrame:
    geometry = LineString([(1.5, 0.0), (10.0, 0.0)])
    return gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "segment-1",
                "segment_type": "normal",
                "patch_road_key": "patch:1",
                "carrier_role": "main_oneway",
                "realization": "built",
                "source_snodeid": "",
                "source_enodeid": "",
                "snodeid": 0,
                "enodeid": 0,
                "length": geometry.length,
                "geometry": geometry,
            }
        ],
        crs=CRS,
    )


def _accesses_without_source_geometry() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:endpoint:0:missing-node",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "missing-node",
                "junction_group_id": "100",
                "source_exists": False,
                "geometry": None,
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _empty_nodes() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": pd.Series(dtype="int64"),
            "geometry": gpd.GeoSeries([], crs=CRS),
        },
        geometry="geometry",
        crs=CRS,
    )


def test_missing_access_geometry_uses_accepted_junction_surface(
    caplog,
) -> None:
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 3,
                "source_object_id": "accepted-surface",
                "geometry": box(-1.0, -1.0, 0.0, 1.0),
            }
        ],
        crs=CRS,
    )

    with caplog.at_level(
        "INFO",
        logger=(
            "rcsd_topo_poc.modules.p04_road_direct_generation."
            "segment_first_access_memberships"
        ),
    ):
        resolution = resolve_road_endpoint_junctions(
            _roads(),
            junctions,
            _accesses_without_source_geometry(),
            _empty_nodes(),
            config=_config(),
        )

    assert resolution.memberships[0]["junction_group_id"] == "100"
    assert resolution.built_access_handoff_count == 1
    assert "missing_access_geometry=1" in caplog.text
    assert "unresolved_target=0" in caplog.text


def test_missing_access_geometry_without_surface_remains_unmaterialized(
    caplog,
) -> None:
    junctions = gpd.GeoDataFrame(
        {
            "junction_group_id": pd.Series(dtype=str),
            "junction_source": pd.Series(dtype=str),
            "junction_kind": pd.Series(dtype=str),
            "source_priority": pd.Series(dtype="int64"),
            "source_object_id": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=CRS),
        },
        geometry="geometry",
        crs=CRS,
    )

    with caplog.at_level(
        "INFO",
        logger=(
            "rcsd_topo_poc.modules.p04_road_direct_generation."
            "segment_first_access_memberships"
        ),
    ):
        resolution = resolve_road_endpoint_junctions(
            _roads(),
            junctions,
            _accesses_without_source_geometry(),
            _empty_nodes(),
            config=_config(),
        )

    assert resolution.memberships == {}
    assert resolution.built_access_handoff_count == 0
    assert "missing_access_geometry=1" in caplog.text
    assert "unresolved_target=1" in caplog.text
