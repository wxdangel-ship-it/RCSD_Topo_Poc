from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_gpkg

from .schemas import PROCESS_CRS_TEXT


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"t06_segment_fusion_precheck_{stamp}"


def prepare_run_roots(out_root: str | Path, run_id: str | None, step_dir: str) -> tuple[str, Path, Path]:
    resolved_run_id = run_id or default_run_id()
    run_root = Path(out_root) / resolved_run_id
    step_root = run_root / step_dir
    step_root.mkdir(parents=True, exist_ok=True)
    return resolved_run_id, run_root, step_root


def read_features(path: str | Path, *, crs_override: str | None = None) -> list[dict[str, Any]]:
    result = read_vector_layer(path, crs_override=crs_override)
    return [{"properties": dict(item.properties), "geometry": item.geometry} for item in result.features]


def write_feature_triplet(
    *,
    step_root: Path,
    stem: str,
    features: list[dict[str, Any]],
    fieldnames: list[str],
    write_json_output: bool = True,
    progress: Callable[[str, str, Path], None] | None = None,
) -> dict[str, Path]:
    gpkg_path = step_root / f"{stem}.gpkg"
    csv_path = step_root / f"{stem}.csv"
    json_path = step_root / f"{stem}.json"
    paths = {"gpkg": gpkg_path, "csv": csv_path}
    _notify_output_progress(progress, "gpkg", "start", gpkg_path)
    write_gpkg(gpkg_path, features, empty_fields=fieldnames, geometry_type="Unknown")
    _notify_output_progress(progress, "gpkg", "end", gpkg_path)
    _notify_output_progress(progress, "csv", "start", csv_path)
    write_csv(csv_path, (feature.get("properties") or {} for feature in features), fieldnames)
    _notify_output_progress(progress, "csv", "end", csv_path)
    if write_json_output:
        _notify_output_progress(progress, "json", "start", json_path)
        write_json(
            json_path,
            {
                "row_count": len(features),
                "features": [_feature_json(feature) for feature in features],
            },
        )
        _notify_output_progress(progress, "json", "end", json_path)
        paths["json"] = json_path
    else:
        _notify_output_progress(progress, "json", "skipped", json_path)
    return paths


def _notify_output_progress(progress: Callable[[str, str, Path], None] | None, fmt: str, status: str, path: Path) -> None:
    if progress is not None:
        progress(fmt, status, path)


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _plain_value(row.get(field)) for field in fieldnames})


def write_json(path: str | Path, payload: Any) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(_plain_value(payload), fp, ensure_ascii=False, indent=2, allow_nan=False)


def _feature_json(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    return {
        "properties": _plain_value(feature.get("properties") or {}),
        "geometry": mapping(geometry) if isinstance(geometry, BaseGeometry) else geometry,
        "crs": PROCESS_CRS_TEXT,
    }


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseGeometry):
        return mapping(value)
    return value
