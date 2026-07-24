from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .segment_first_config import SegmentFirstConfig
from .segment_first_geometry import RoadGeometryResult, materialize_road_geometry
from .segment_first_junction_carriers import (
    JunctionCarrierResult,
    materialize_ordinary_junction_carriers,
)


def materialize_network_geometry(
    carriers: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    full_rcsd_roads: gpd.GeoDataFrame,
    explicit_pairs: pd.DataFrame,
    *,
    config: SegmentFirstConfig,
    semantic_endpoint_segment_ids: set[str] | None = None,
) -> tuple[RoadGeometryResult, JunctionCarrierResult]:
    segment_geometry = materialize_road_geometry(
        carriers,
        swsd_roads,
        config=config,
    )
    junction_carriers = materialize_ordinary_junction_carriers(
        segment_geometry.roads,
        junction_units,
        segment_accesses,
        drivezones,
        t01_nodes,
        config=config,
        semantic_endpoint_segment_ids=semantic_endpoint_segment_ids,
        full_rcsd_roads=full_rcsd_roads,
        explicit_pairs=explicit_pairs,
    )
    roads = gpd.GeoDataFrame(
        pd.concat(
            [segment_geometry.roads, junction_carriers.roads],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=segment_geometry.roads.crs,
    )
    sources = gpd.GeoDataFrame(
        pd.concat(
            [
                segment_geometry.geometry_sources,
                junction_carriers.geometry_sources,
            ],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=segment_geometry.roads.crs,
    )
    summary = dict(segment_geometry.summary)
    summary.update(
        {
            "road_count": int(len(roads)),
            "built_road_count": int(roads["realization"].eq("built").sum()),
            "retained_road_count": int(roads["realization"].eq("retained").sum()),
            "junction_carrier_road_count": int(len(junction_carriers.roads)),
        }
    )
    return RoadGeometryResult(roads, sources, summary), junction_carriers


__all__ = ["materialize_network_geometry"]
