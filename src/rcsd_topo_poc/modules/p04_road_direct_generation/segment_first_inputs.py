from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd

from .geometry import to_2d
from .io import build_input_manifest, discover_patch_dirs, read_vector
from .segment_first_config import SegmentFirstConfig


@dataclass(frozen=True)
class SegmentInputBundle:
    patch_dirs: tuple[Path, ...]
    patch_ids: tuple[str, ...]
    swsd_roads: gpd.GeoDataFrame
    swsd_nodes: gpd.GeoDataFrame
    t01_roads: gpd.GeoDataFrame
    t01_nodes: gpd.GeoDataFrame
    t01_segments: gpd.GeoDataFrame
    t07_surfaces: gpd.GeoDataFrame
    t03_surfaces: gpd.GeoDataFrame
    t04_surfaces: gpd.GeoDataFrame
    full_rcsd_roads: gpd.GeoDataFrame
    full_rcsd_nodes: gpd.GeoDataFrame
    target_replaceability: pd.DataFrame
    patch_roads: gpd.GeoDataFrame
    patch_lanes: gpd.GeoDataFrame
    patch_boundaries: gpd.GeoDataFrame
    patch_lane_topo: gpd.GeoDataFrame
    patch_road_next_road: gpd.GeoDataFrame
    patch_intersections: gpd.GeoDataFrame
    drivezones: gpd.GeoDataFrame
    divstripzones: gpd.GeoDataFrame
    manifest: dict[str, object]


def load_segment_first_inputs(config: SegmentFirstConfig) -> SegmentInputBundle:
    cfg = config.resolved()
    cfg.validate_paths()
    patch_dirs = discover_patch_dirs(cfg.patch_root)
    external = {
        "swsd_roads": cfg.swsd_road_path,
        "swsd_nodes": cfg.swsd_node_path,
        "t01_roads": cfg.t01_road_path,
        "t01_nodes": cfg.t01_node_path,
        "t01_segments": cfg.t01_segment_path,
        "t07_surface": cfg.t07_surface_path,
        "t03_surface": cfg.t03_surface_path,
        "t04_surface": cfg.t04_surface_path,
        "full_rcsd_roads": cfg.full_rcsd_road_path,
        "full_rcsd_nodes": cfg.full_rcsd_node_path,
    }
    if cfg.target_replaceability_path is not None:
        external["target_replaceability"] = cfg.target_replaceability_path
    if cfg.target_disposition_path is not None:
        external["target_disposition"] = cfg.target_disposition_path
    swsd_roads = read_vector(cfg.swsd_road_path, cfg.analysis_crs)
    swsd_nodes = read_vector(cfg.swsd_node_path, cfg.analysis_crs)
    t01_roads = read_vector(cfg.t01_road_path, cfg.analysis_crs)
    t01_nodes = read_vector(cfg.t01_node_path, cfg.analysis_crs)
    t01_segments = read_vector(cfg.t01_segment_path, cfg.analysis_crs)
    t07 = accepted_surface(read_vector(cfg.t07_surface_path, cfg.analysis_crs), "t07")
    t03 = accepted_surface(read_vector(cfg.t03_surface_path, cfg.analysis_crs), "t03")
    t04 = accepted_surface(read_vector(cfg.t04_surface_path, cfg.analysis_crs), "t04")
    full_roads = read_vector(cfg.full_rcsd_road_path, cfg.analysis_crs)
    full_nodes = read_vector(cfg.full_rcsd_node_path, cfg.analysis_crs)
    target_replaceability = _read_target_replaceability(
        cfg.target_replaceability_path,
        cfg.analysis_crs,
    )

    require_columns(t01_segments, ("id", "sgrade", "pair_nodes", "junc_nodes", "roads"), "t01_segments")
    require_columns(t01_roads, ("id", "snodeid", "enodeid", "direction", "patch_id", "segmentid"), "t01_roads")
    require_columns(t01_nodes, ("id", "mainnodeid"), "t01_nodes")
    require_columns(full_roads, ("id", "snodeid", "enodeid", "direction", "source"), "full_rcsd_roads")
    require_columns(full_nodes, ("id", "mainnodeid", "source"), "full_rcsd_nodes")

    patch_roads = _load_patch_layer(patch_dirs, "Road.geojson", cfg.analysis_crs)
    patch_lanes = _load_patch_layer(patch_dirs, "Lane.geojson", cfg.analysis_crs)
    patch_boundaries = _load_patch_layer(patch_dirs, "LaneBoundary.geojson", cfg.analysis_crs)
    patch_lane_topo = _load_patch_layer(patch_dirs, "LaneNextLane.geojson", cfg.analysis_crs, geometry_optional=True)
    patch_rnr = _load_patch_layer(patch_dirs, "RoadNextRoad.geojson", cfg.analysis_crs, geometry_optional=True)
    patch_intersections = _load_patch_layer(
        patch_dirs,
        "Intersection.geojson",
        cfg.analysis_crs,
    )
    drivezones = _load_patch_layer(patch_dirs, "DriveZone_fix.geojson", cfg.analysis_crs)
    divstripzones = _load_patch_layer(patch_dirs, "DivStripZone_fix.geojson", cfg.analysis_crs)
    require_columns(patch_roads, ("Id",), "patch_roads")
    require_columns(patch_lanes, ("Id", "RoadId", "Width"), "patch_lanes")
    require_columns(patch_lane_topo, ("Id", "LaneId", "NextLaneId"), "patch_lane_topo")
    require_columns(patch_rnr, ("Id", "RoadId", "NextRoadId"), "patch_road_next_road")

    return SegmentInputBundle(
        patch_dirs=patch_dirs,
        patch_ids=tuple(path.name for path in patch_dirs),
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        t01_roads=t01_roads,
        t01_nodes=t01_nodes,
        t01_segments=t01_segments,
        t07_surfaces=t07,
        t03_surfaces=t03,
        t04_surfaces=t04,
        full_rcsd_roads=full_roads,
        full_rcsd_nodes=full_nodes,
        target_replaceability=target_replaceability,
        patch_roads=patch_roads,
        patch_lanes=patch_lanes,
        patch_boundaries=patch_boundaries,
        patch_lane_topo=patch_lane_topo,
        patch_road_next_road=patch_rnr,
        patch_intersections=patch_intersections,
        drivezones=drivezones,
        divstripzones=divstripzones,
        manifest=build_input_manifest(
            run_id=cfg.run_id,
            patch_dirs=patch_dirs,
            external_inputs=external,
            parameters=cfg.parameters(),
        ),
    )


def accepted_surface(frame: gpd.GeoDataFrame, source: str) -> gpd.GeoDataFrame:
    source = source.lower()
    if source == "t07":
        require_columns(frame, ("final_state",), "t07_surface")
        mask = frame["final_state"].fillna("").astype(str).str.lower().eq("accepted")
    elif source == "t03":
        require_columns(frame, ("success", "acceptance_class"), "t03_surface")
        success = frame["success"].map(_truthy)
        accepted = frame["acceptance_class"].fillna("").astype(str).str.lower().eq("accepted")
        mask = success & accepted
    elif source == "t04":
        require_columns(frame, ("final_state",), "t04_surface")
        mask = frame["final_state"].fillna("").astype(str).str.lower().eq("accepted")
    else:
        raise ValueError(f"unsupported surface source: {source}")
    result = frame.loc[mask & frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    result["accepted_source"] = f"{source}_accepted"
    return result.reset_index(drop=True)


def _read_target_replaceability(
    path: Path | None,
    analysis_crs: str,
) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return read_vector(path, analysis_crs)


def require_columns(frame: pd.DataFrame, columns: Iterable[str], role: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{role} missing required columns: {', '.join(missing)}")


def _load_patch_layer(
    patch_dirs: tuple[Path, ...],
    filename: str,
    analysis_crs: str,
    *,
    geometry_optional: bool = False,
) -> gpd.GeoDataFrame:
    frames: list[gpd.GeoDataFrame] = []
    for patch_dir in patch_dirs:
        path = patch_dir / "Vector" / filename
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError(f"input CRS is missing: {path}")
        frame = frame.to_crs(analysis_crs)
        frame.geometry = frame.geometry.map(to_2d)
        frame["source_patch_id"] = patch_dir.name
        frames.append(frame)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=analysis_crs)
    combined = pd.concat(frames, ignore_index=True)
    result = gpd.GeoDataFrame(combined, geometry="geometry", crs=analysis_crs)
    if not geometry_optional:
        result = result[result.geometry.notna() & ~result.geometry.is_empty].copy()
    return result.reset_index(drop=True)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


__all__ = [
    "SegmentInputBundle",
    "accepted_surface",
    "load_segment_first_inputs",
    "require_columns",
]
