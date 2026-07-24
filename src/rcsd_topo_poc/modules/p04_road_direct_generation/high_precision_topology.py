from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd

from .directional_topology import build_directional_topology


@dataclass(frozen=True)
class HighPrecisionTopologyResult:
    portals: gpd.GeoDataFrame
    arms: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_high_precision_topology(
    road_candidates: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> HighPrecisionTopologyResult:
    roads = road_candidates.copy()
    roads["directional_road_id"] = roads["v3_road_id"].astype(str)
    result = build_directional_topology(roads, run_id=run_id)
    portals = _v3_names(result.portals)
    arms = _v3_names(result.arms)
    return HighPrecisionTopologyResult(
        portals=portals,
        arms=arms,
        summary={
            **result.summary,
            "topology_model": "v3_physical_road_portal_arm",
        },
    )


def _v3_names(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mapping = {
        column: column.replace("directional_road_id", "v3_road_id")
        .replace("directional_portal_id", "v3_portal_id")
        .replace("directional_arm_id", "v3_arm_id")
        for column in frame.columns
        if "directional_" in column
    }
    result = frame.rename(columns=mapping)
    if "decision" in result.columns:
        result["decision"] = result["decision"].astype(str).str.replace(
            "directional_", "high_precision_v3_", regex=False
        )
    return result


__all__ = ["HighPrecisionTopologyResult", "build_high_precision_topology"]
