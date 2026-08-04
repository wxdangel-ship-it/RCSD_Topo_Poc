from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely import force_2d

from .geometry import to_2d
from .io import (
    build_input_manifest,
    discover_patch_dirs,
    read_vector,
    sha256_file,
)
from .segment_first_config import SegmentFirstConfig
from .segment_first_performance import PATCH_IO_WORKERS_MAX
from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


PATCH_READ_WORKERS = PATCH_IO_WORKERS_MAX
SEGMENT_FIRST_PATCH_LAYER_FAMILIES = (
    ("Road.geojson",),
    ("Lane.geojson",),
    ("LaneBoundary.geojson",),
    ("LaneNextLane.geojson",),
    ("RoadNextRoad.geojson",),
    ("Intersection.geojson",),
    ("DriveZone_fix.geojson", "DriveZone.geojson"),
    ("DivStripZone_fix.geojson", "DivStripZone.geojson"),
)


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
    patch_dirs = discover_patch_dirs(
        cfg.patch_root,
        allow_equivalent_vector_fallback=True,
    )
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

    patch_manifest_by_path: dict[Path, dict[str, object]] = {}
    patch_roads = _load_patch_layer(
        patch_dirs,
        "Road.geojson",
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    patch_lanes = _load_patch_layer(
        patch_dirs,
        "Lane.geojson",
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    patch_boundaries = _load_patch_layer(
        patch_dirs,
        "LaneBoundary.geojson",
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    patch_lane_topo = _load_patch_layer(
        patch_dirs,
        "LaneNextLane.geojson",
        cfg.analysis_crs,
        geometry_optional=True,
        manifest_by_path=patch_manifest_by_path,
    )
    patch_rnr = _load_patch_layer(
        patch_dirs,
        "RoadNextRoad.geojson",
        cfg.analysis_crs,
        geometry_optional=True,
        manifest_by_path=patch_manifest_by_path,
    )
    patch_intersections = _load_patch_layer(
        patch_dirs,
        "Intersection.geojson",
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    drivezones = _load_patch_layer(
        patch_dirs,
        ("DriveZone_fix.geojson", "DriveZone.geojson"),
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    divstripzones = _load_patch_layer(
        patch_dirs,
        ("DivStripZone_fix.geojson", "DivStripZone.geojson"),
        cfg.analysis_crs,
        manifest_by_path=patch_manifest_by_path,
    )
    require_columns(patch_roads, ("Id",), "patch_roads")
    require_columns(patch_lanes, ("Id", "RoadId", "Width"), "patch_lanes")
    require_columns(patch_lane_topo, ("Id", "LaneId", "NextLaneId"), "patch_lane_topo")
    require_columns(patch_rnr, ("Id", "RoadId", "NextRoadId"), "patch_road_next_road")

    consumed_patch_inputs = _consumed_patch_inputs(patch_dirs)
    precomputed_patch_files = [
        patch_manifest_by_path[path]
        for _, path in consumed_patch_inputs
    ]
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
            patch_inputs=consumed_patch_inputs,
            precomputed_patch_files=precomputed_patch_files,
        ),
    )


def accepted_surface(frame: gpd.GeoDataFrame, source: str) -> gpd.GeoDataFrame:
    source = source.lower()
    if source == "t07":
        require_columns(frame, ("final_state",), "t07_surface")
        mask = frame["final_state"].fillna("").astype(str).str.lower().eq("accepted")
    elif source == "t03":
        if "step7_state" in frame.columns:
            mask = frame["step7_state"].fillna("").astype(str).str.lower().eq("accepted")
        else:
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
    filename: str | tuple[str, ...],
    analysis_crs: str,
    *,
    geometry_optional: bool = False,
    manifest_by_path: dict[Path, dict[str, object]] | None = None,
) -> gpd.GeoDataFrame:
    filenames = (filename,) if isinstance(filename, str) else filename
    stage = "input_patch_layer"
    detail = "/".join(filenames)
    stage_root = _patch_input_stage_root(patch_dirs)
    stage_directory: tempfile.TemporaryDirectory[str] | None = None
    staged_path: Path | None = None
    if stage_root is not None:
        try:
            stage_directory = tempfile.TemporaryDirectory(
                prefix="p04-patch-input-",
                dir=stage_root,
            )
            staged_path = Path(stage_directory.name)
        except OSError:
            stage_directory = None
            staged_path = None
    requests = [
        (
            patch_dir,
            filenames,
            analysis_crs,
            manifest_by_path is not None,
            staged_path,
        )
        for patch_dir in patch_dirs
    ]
    staged = staged_path is not None
    begin_progress_stage(
        stage,
        len(requests),
        detail=detail,
        counters={"staged": str(staged).lower()},
    )
    worker_count = min(PATCH_READ_WORKERS, max(1, len(requests)))
    frames: list[gpd.GeoDataFrame | None] = [None] * len(requests)
    row_count = 0
    empty_geometry_count = 0
    hashed_file_count = 0
    staged_bytes = 0
    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_read_patch_layer_request, request): index
                for index, request in enumerate(requests)
            }
            for completed_count, future in enumerate(
                as_completed(futures),
                start=1,
            ):
                index = futures[future]
                frame, path, manifest_row, copied_bytes = future.result()
                frames[index] = frame
                staged_bytes += copied_bytes
                if manifest_by_path is not None and manifest_row is not None:
                    manifest_by_path[path] = manifest_row
                    hashed_file_count += 1
                row_count += len(frame)
                empty_geometry_count += int(
                    (frame.geometry.isna() | frame.geometry.is_empty).sum()
                )
                advance_progress(
                    stage,
                    completed=completed_count,
                    last_unit=requests[index][0].name,
                    counters={
                        "rows": row_count,
                        "empty_geometry": empty_geometry_count,
                        "hashed_files": hashed_file_count,
                        "workers": worker_count,
                        "staged": str(staged).lower(),
                        "staged_bytes": staged_bytes,
                    },
                )
    finally:
        if stage_directory is not None:
            stage_directory.cleanup()
    if not frames:
        finish_progress_stage(stage)
        return gpd.GeoDataFrame(geometry=[], crs=analysis_crs)
    completed_frames = [frame for frame in frames if frame is not None]
    result, transform_batches, shared_source_crs = _project_patch_frames(
        completed_frames,
        analysis_crs,
    )
    if not geometry_optional:
        result = result[result.geometry.notna() & ~result.geometry.is_empty].copy()
    result = result.reset_index(drop=True)
    finish_progress_stage(
        stage,
        counters={
            "rows": len(result),
            "empty_geometry": empty_geometry_count,
            "hashed_files": hashed_file_count,
            "workers": worker_count,
            "crs_transform_batches": transform_batches,
            "shared_source_crs": str(shared_source_crs).lower(),
            "staged": str(staged).lower(),
            "staged_bytes": staged_bytes,
        },
    )
    return result


def _project_patch_frames(
    frames: list[gpd.GeoDataFrame],
    analysis_crs: str,
) -> tuple[gpd.GeoDataFrame, int, bool]:
    """Project one layer family in a stable batch when all source CRS agree."""

    source_crs = frames[0].crs
    if all(frame.crs == source_crs for frame in frames):
        combined = pd.concat(frames, ignore_index=True)
        result = gpd.GeoDataFrame(
            combined,
            geometry="geometry",
            crs=source_crs,
        ).to_crs(analysis_crs)
        result.geometry = force_2d(result.geometry.array)
        return result, 1, True
    projected: list[gpd.GeoDataFrame] = []
    for frame in frames:
        transformed = frame.to_crs(analysis_crs)
        transformed.geometry = transformed.geometry.map(to_2d)
        projected.append(transformed)
    combined = pd.concat(projected, ignore_index=True)
    return (
        gpd.GeoDataFrame(
            combined,
            geometry="geometry",
            crs=analysis_crs,
        ),
        len(projected),
        False,
    )


def _read_patch_layer_request(
    request: tuple[Path, tuple[str, ...], str, bool, Path | None],
) -> tuple[gpd.GeoDataFrame, Path, dict[str, object] | None, int]:
    patch_dir, filenames, analysis_crs, capture_manifest, stage_directory = request
    path = _resolve_patch_layer_path(patch_dir, filenames)
    read_path = path
    digest: str | None = None
    copied_bytes = 0
    if stage_directory is not None:
        read_path = stage_directory / f"{patch_dir.name}-{path.name}"
        copied_bytes, digest = _copy_patch_input(
            path,
            read_path,
            calculate_sha256=capture_manifest,
        )
    try:
        frame = gpd.read_file(read_path)
    finally:
        if read_path != path and read_path.exists():
            read_path.unlink()
    if frame.crs is None:
        raise ValueError(f"input CRS is missing: {path}")
    frame["source_patch_id"] = patch_dir.name
    frame["source_vector_filename"] = path.name
    manifest_row = (
        {
            "role": "patch_vector",
            "patch_id": patch_dir.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": digest if digest is not None else sha256_file(path),
        }
        if capture_manifest
        else None
    )
    return frame, path, manifest_row, copied_bytes


def _copy_patch_input(
    source: Path,
    target: Path,
    *,
    calculate_sha256: bool,
) -> tuple[int, str | None]:
    digest = hashlib.sha256() if calculate_sha256 else None
    copied_bytes = 0
    with source.open("rb") as source_handle, target.open("wb") as target_handle:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            target_handle.write(chunk)
            copied_bytes += len(chunk)
            if digest is not None:
                digest.update(chunk)
    return copied_bytes, digest.hexdigest() if digest is not None else None


def _patch_input_stage_root(patch_dirs: tuple[Path, ...]) -> Path | None:
    mode = os.environ.get("P04_PATCH_INPUT_STAGING", "auto").strip().lower()
    if mode in {"0", "false", "no", "off", "disabled"}:
        return None
    forced = mode in {"1", "true", "yes", "on", "force"}
    if not forced and not all(_is_wsl_drvfs_path(path) for path in patch_dirs):
        return None
    root = Path(
        os.environ.get("P04_PATCH_STAGE_ROOT", tempfile.gettempdir())
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(root).free
    except OSError:
        return None
    if free_bytes < 2 * 1024**3 or not os.access(root, os.W_OK):
        return None
    return root


def _is_wsl_drvfs_path(path: Path) -> bool:
    parts = path.absolute().parts
    return bool(
        len(parts) >= 3
        and parts[0] == "/"
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    )


def _resolve_patch_layer_path(
    patch_dir: Path,
    filenames: tuple[str, ...],
) -> Path:
    path = next(
        (
            patch_dir / "Vector" / candidate_name
            for candidate_name in filenames
            if (patch_dir / "Vector" / candidate_name).is_file()
        ),
        None,
    )
    if path is None:
        raise FileNotFoundError(
            f"missing Patch Vector layer for {patch_dir.name}: "
            f"one of {list(filenames)}"
        )
    return path


def _consumed_patch_inputs(
    patch_dirs: tuple[Path, ...],
) -> tuple[tuple[str, Path], ...]:
    return tuple(
        (patch_dir.name, _resolve_patch_layer_path(patch_dir, filenames))
        for patch_dir in patch_dirs
        for filenames in SEGMENT_FIRST_PATCH_LAYER_FAMILIES
    )


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
