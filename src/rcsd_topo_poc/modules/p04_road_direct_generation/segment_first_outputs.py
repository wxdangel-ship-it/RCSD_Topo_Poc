from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import geopandas as gpd

from .io import write_gpkg_layers


@dataclass(frozen=True)
class PublishedPaths:
    formal_gpkg: Path
    audit_gpkg: Path
    relations_gpkg: Path
    comparison_gpkg: Path


def publish_segment_first_layers(
    output_dir: Path,
    *,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    road_next_road: gpd.GeoDataFrame,
    audit_layers: Mapping[str, gpd.GeoDataFrame],
    relation_layers: Mapping[str, gpd.GeoDataFrame],
    comparison_layers: Mapping[str, gpd.GeoDataFrame],
) -> PublishedPaths:
    formal = output_dir / "p04_segment_first_rcsd.gpkg"
    audit = output_dir / "p04_segment_first_audit.gpkg"
    relations = output_dir / "p04_segment_first_relations.gpkg"
    comparison = output_dir / "p04_segment_first_comparison.gpkg"
    write_gpkg_layers(
        formal,
        {
            "Road": roads,
            "Node": nodes,
            "RoadNextRoad": road_next_road,
        },
    )
    write_gpkg_layers(audit, _casefold_safe_layers(audit_layers))
    write_gpkg_layers(relations, _casefold_safe_layers(relation_layers))
    write_gpkg_layers(comparison, _casefold_safe_layers(comparison_layers))
    return PublishedPaths(formal, audit, relations, comparison)


def _casefold_safe_layers(
    layers: Mapping[str, gpd.GeoDataFrame],
) -> dict[str, gpd.GeoDataFrame]:
    result: dict[str, gpd.GeoDataFrame] = {}
    for layer_name, frame in layers.items():
        renamed: dict[str, str] = {}
        seen: set[str] = set()
        for column in frame.columns:
            folded = column.casefold()
            if folded in seen:
                candidate = f"raw_{column}"
                suffix = 2
                while candidate.casefold() in seen:
                    candidate = f"raw_{column}_{suffix}"
                    suffix += 1
                renamed[column] = candidate
                seen.add(candidate.casefold())
            else:
                seen.add(folded)
        result[layer_name] = frame.rename(columns=renamed)
    return result


__all__ = ["PublishedPaths", "publish_segment_first_layers"]
