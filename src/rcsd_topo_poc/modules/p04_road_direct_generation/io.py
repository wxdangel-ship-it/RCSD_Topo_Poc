from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely

from .geometry import to_2d
from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


CORE_VECTOR_FILES = (
    "Lane.geojson",
    "LaneBoundary.geojson",
    "LaneNextLane.geojson",
    "Road.geojson",
    "RoadNextRoad.geojson",
    "DriveZone.geojson",
    "DriveZone_fix.geojson",
    "DivStripZone.geojson",
    "DivStripZone_fix.geojson",
    "ReferenceLane.geojson",
)

EQUIVALENT_VECTOR_FILE_FAMILIES = (
    ("DriveZone_fix.geojson", "DriveZone.geojson"),
    ("DivStripZone_fix.geojson", "DivStripZone.geojson"),
)


def discover_patch_dirs(
    patch_root: Path,
    *,
    allow_equivalent_vector_fallback: bool = False,
) -> tuple[Path, ...]:
    patch_dirs = tuple(sorted(path for path in patch_root.iterdir() if path.is_dir()))
    if not patch_dirs:
        raise ValueError(f"no Patch directories found: {patch_root}")
    for patch_dir in patch_dirs:
        vector_dir = patch_dir / "Vector"
        if not vector_dir.is_dir():
            raise FileNotFoundError(f"missing Vector directory: {vector_dir}")
        missing = _missing_core_vector_files(
            vector_dir,
            allow_equivalent_vector_fallback=allow_equivalent_vector_fallback,
        )
        if missing:
            raise FileNotFoundError(f"missing core Vector files for {patch_dir.name}: {missing}")
    return patch_dirs


def _missing_core_vector_files(
    vector_dir: Path,
    *,
    allow_equivalent_vector_fallback: bool,
) -> list[str]:
    if not allow_equivalent_vector_fallback:
        return [name for name in CORE_VECTOR_FILES if not (vector_dir / name).is_file()]

    equivalent_names = {
        name
        for family in EQUIVALENT_VECTOR_FILE_FAMILIES
        for name in family
    }
    missing = [
        name
        for name in CORE_VECTOR_FILES
        if name not in equivalent_names and not (vector_dir / name).is_file()
    ]
    for preferred_name, fallback_name in EQUIVALENT_VECTOR_FILE_FAMILIES:
        if not any(
            (vector_dir / candidate_name).is_file()
            for candidate_name in (preferred_name, fallback_name)
        ):
            missing.append(f"{preferred_name} or {fallback_name}")
    return missing


def read_vector(path: Path, analysis_crs: str, *, layer: str | None = None) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path, layer=layer)
    if frame.crs is None:
        raise ValueError(f"input CRS is missing: {path}")
    frame = frame.to_crs(analysis_crs)
    frame.geometry = frame.geometry.map(to_2d)
    return frame


def prepare_output_dir(path: Path) -> None:
    if path.exists():
        if any(path.iterdir()):
            raise FileExistsError(f"output directory must be new or empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_input_manifest(
    *,
    run_id: str,
    patch_dirs: Iterable[Path],
    external_inputs: Mapping[str, Path | None],
    parameters: Mapping[str, Any],
    patch_inputs: Iterable[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    requests: list[tuple[Path, str, str | None]] = []
    if patch_inputs is None:
        for patch_dir in patch_dirs:
            vector_dir = patch_dir / "Vector"
            requests.extend(
                (path, "patch_vector", patch_dir.name)
                for path in sorted(vector_dir.glob("*.geojson"))
            )
            requests.extend(
                (path, "patch_vector_derived", patch_dir.name)
                for path in sorted(vector_dir.glob("*.gpkg"))
            )
    else:
        requests.extend(
            (path, "patch_vector", patch_id)
            for patch_id, path in patch_inputs
        )
    requests.extend(
        (path, role, None)
        for role, path in external_inputs.items()
        if path is not None
    )
    worker_count = min(6, max(1, len(requests)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        files = list(executor.map(_manifest_row_request, requests))
    return {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_file_count": len(files),
        "input_total_bytes": sum(int(row["size_bytes"]) for row in files),
        "files": files,
        "parameters": dict(parameters),
        "runtime": runtime_metadata(),
    }


def profile_patch_vectors(patch_dirs: Iterable[Path]) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "file_count": 0,
            "nonempty_file_count": 0,
            "feature_count": 0,
            "fields": set(),
            "crs_values": set(),
            "schema_geometry_values": set(),
            "observed_geometry_counts": Counter(),
            "patch_counts": {},
        }
    )
    for patch_dir in patch_dirs:
        for path in sorted((patch_dir / "Vector").glob("*.geojson")):
            entry = by_type[path.stem]
            with fiona.open(path) as source:
                feature_count = len(source)
                geometry_counts: Counter[str] = Counter()
                for feature in source:
                    geometry = feature.get("geometry")
                    geometry_counts[geometry.get("type", "unknown") if geometry else "none"] += 1
                entry["file_count"] += 1
                entry["nonempty_file_count"] += int(feature_count > 0)
                entry["feature_count"] += feature_count
                entry["fields"].update(source.schema.get("properties", {}).keys())
                entry["crs_values"].add(source.crs_wkt or str(source.crs) or "missing")
                entry["schema_geometry_values"].add(str(source.schema.get("geometry")))
                entry["observed_geometry_counts"].update(geometry_counts)
                entry["patch_counts"][patch_dir.name] = feature_count
    materialized: dict[str, Any] = {}
    for object_type, entry in sorted(by_type.items()):
        materialized[object_type] = {
            **entry,
            "fields": sorted(entry["fields"]),
            "crs_values": sorted(entry["crs_values"]),
            "schema_geometry_values": sorted(entry["schema_geometry_values"]),
            "observed_geometry_counts": dict(sorted(entry["observed_geometry_counts"].items())),
        }
    return {
        "patch_count": len(tuple(patch_dirs)),
        "object_type_count": len(materialized),
        "nonempty_object_type_count": sum(1 for entry in materialized.values() if entry["feature_count"] > 0),
        "empty_object_type_count": sum(1 for entry in materialized.values() if entry["feature_count"] == 0),
        "object_types": materialized,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Iterable[str] | None = None) -> None:
    materialized = list(rows)
    names = tuple(fieldnames or (materialized[0].keys() if materialized else ()))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        if names:
            writer.writeheader()
            writer.writerows(materialized)


def write_gpkg_layers(path: Path, layers: Mapping[str, gpd.GeoDataFrame]) -> None:
    stage = "output_gpkg_layers"
    begin_progress_stage(
        stage,
        len(layers),
        detail=path.name,
        counters={"written_layers": 0, "written_rows": 0},
    )
    if path.exists():
        path.unlink()
    first = True
    written_layers = 0
    written_rows = 0
    skipped_layers = 0
    for layer_index, (layer_name, frame) in enumerate(layers.items()):
        if frame.empty:
            skipped_layers += 1
            advance_progress(
                stage,
                completed=layer_index + 1,
                last_unit=layer_name,
                counters={
                    "written_layers": written_layers,
                    "written_rows": written_rows,
                    "skipped_empty_layers": skipped_layers,
                },
            )
            continue
        sanitized = sanitize_for_vector(frame)
        sanitized.to_file(path, layer=layer_name, driver="GPKG", mode="w" if first else "a", index=False)
        first = False
        written_layers += 1
        written_rows += len(sanitized)
        advance_progress(
            stage,
            completed=layer_index + 1,
            last_unit=layer_name,
            counters={
                "written_layers": written_layers,
                "written_rows": written_rows,
                "skipped_empty_layers": skipped_layers,
            },
        )
    if first:
        raise ValueError(f"no nonempty layers to write: {path}")
    finish_progress_stage(
        stage,
        counters={
            "written_layers": written_layers,
            "written_rows": written_rows,
            "skipped_empty_layers": skipped_layers,
        },
    )


def sanitize_for_vector(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = frame.copy()
    for column in result.columns:
        if column == result.geometry.name:
            continue
        if result[column].map(lambda value: isinstance(value, (set, frozenset, list, tuple, dict))).any():
            result[column] = result[column].map(
                lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (set, frozenset, list, tuple, dict))
                else value
            )
    return result


def runtime_metadata() -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "geopandas": gpd.__version__,
        "fiona": fiona.__version__,
        "shapely": shapely.__version__,
        "pyproj": pyproj.__version__,
        "git_commit": _git_commit(),
    }


def _manifest_row(path: Path, *, role: str, patch_id: str | None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "role": role,
        "patch_id": patch_id,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _manifest_row_request(
    request: tuple[Path, str, str | None],
) -> dict[str, Any]:
    path, role, patch_id = request
    return _manifest_row(path, role=role, patch_id=patch_id)


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


__all__ = [
    "CORE_VECTOR_FILES",
    "EQUIVALENT_VECTOR_FILE_FAMILIES",
    "build_input_manifest",
    "discover_patch_dirs",
    "prepare_output_dir",
    "profile_patch_vectors",
    "read_vector",
    "runtime_metadata",
    "sanitize_for_vector",
    "sha256_file",
    "write_csv",
    "write_gpkg_layers",
    "write_json",
]
