from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fiona
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerReadResult, read_vector_layer

from .phase2_models import PROCESS_CRS_TEXT


def produced_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"t05_phase2_{stamp}"


def prepare_run_root(out_root: str | Path, run_id: str | None) -> Path:
    root = Path(out_root) / (run_id or default_run_id())
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_vector_3857(
    path: str | Path,
    *,
    layer_name: str | None = None,
    crs_override: str | None = None,
) -> LayerReadResult:
    return read_vector_layer(path, layer_name=layer_name, crs_override=crs_override)


def read_table(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    table_path = Path(path)
    if not table_path.is_file():
        raise ValueError(f"Relation evidence input does not exist: {table_path}")
    if table_path.suffix.lower() == ".csv":
        with table_path.open("r", encoding="utf-8", newline="") as fp:
            return [dict(row) for row in csv.DictReader(fp)]
    payload = json.loads(table_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    raise ValueError(f"Unsupported relation evidence JSON shape: {table_path}")


def write_json(path: str | Path, payload: Any) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def write_gpkg(
    path: str | Path,
    features: Iterable[dict[str, Any]],
    *,
    empty_fields: list[str] | None = None,
    geometry_type: str = "Unknown",
) -> None:
    feature_list = list(features)
    out_path = Path(path)
    if feature_list:
        write_vector(out_path, feature_list, crs_text=PROCESS_CRS_TEXT)
        return
    _write_empty_gpkg(out_path, empty_fields or [], geometry_type=geometry_type)


def write_relation_geojson_crs84(path: str | Path, features: Iterable[dict[str, Any]]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    transformer = Transformer.from_crs(CRS.from_epsg(3857), CRS.from_epsg(4326), always_xy=True)
    payload = {
        "type": "FeatureCollection",
        "name": out_path.stem,
        "crs": {"type": "name", "properties": {"name": "CRS84"}},
        "features": [],
    }
    for feature in features:
        geometry = feature.get("geometry")
        if geometry is not None:
            geometry = shapely_transform(transformer.transform, geometry)
        payload["features"].append(
            {
                "type": "Feature",
                "properties": dict(feature.get("properties") or {}),
                "geometry": mapping(geometry) if isinstance(geometry, BaseGeometry) else geometry,
            }
        )
    write_json(out_path, payload)


def _write_empty_gpkg(path: Path, fields: list[str], *, geometry_type: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    schema = {"geometry": geometry_type, "properties": {field: "str" for field in fields}}
    with fiona.open(
        str(path),
        mode="w",
        driver="GPKG",
        layer=path.stem,
        schema=schema,
        crs=PROCESS_CRS_TEXT,
        encoding="utf-8",
    ):
        pass


def feature_from_mapping(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    return {
        "properties": dict(feature.get("properties") or {}),
        "geometry": shape(geometry) if isinstance(geometry, dict) else geometry,
    }


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
