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
    batch_size: int = 10000,
) -> dict[str, Any]:
    feature_list = list(features)
    out_path = Path(path)
    if feature_list:
        return _write_gpkg_records(
            out_path,
            feature_list,
            geometry_type=geometry_type,
            batch_size=batch_size,
        )
    _write_empty_gpkg(out_path, empty_fields or [], geometry_type=geometry_type)
    return {"feature_count": 0, "size_bytes": out_path.stat().st_size if out_path.exists() else 0}


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


def _write_gpkg_records(
    path: Path,
    features: list[dict[str, Any]],
    *,
    geometry_type: str,
    batch_size: int,
) -> dict[str, Any]:
    records = [_prepare_fiona_record(feature) for feature in features]
    schema = _build_fiona_schema(records, geometry_type=geometry_type)
    schema_property_names = list(schema["properties"].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with fiona.open(
        str(path),
        mode="w",
        driver="GPKG",
        layer=path.stem,
        schema=schema,
        crs=PROCESS_CRS_TEXT,
        encoding="utf-8",
    ) as sink:
        batch: list[dict[str, Any]] = []
        batch_limit = max(1, int(batch_size))
        for record in records:
            batch.append(
                {
                    "type": "Feature",
                    "properties": {
                        key: record["properties"].get(key)
                        for key in schema_property_names
                    },
                    "geometry": _geometry_payload(record["geometry"]),
                }
            )
            if len(batch) >= batch_limit:
                sink.writerecords(batch)
                batch.clear()
        if batch:
            sink.writerecords(batch)
    return {"feature_count": len(records), "size_bytes": path.stat().st_size if path.exists() else 0}


def _prepare_fiona_record(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "properties": {
            str(key): _vector_property_value(value)
            for key, value in (feature.get("properties") or {}).items()
        },
        "geometry": feature.get("geometry"),
    }


def _build_fiona_schema(records: list[dict[str, Any]], *, geometry_type: str) -> dict[str, Any]:
    field_order: list[str] = []
    field_types: dict[str, str] = {}
    for record in records:
        for key, value in record["properties"].items():
            if key not in field_order:
                field_order.append(key)
            if key not in field_types and value is not None:
                field_types[key] = _vector_property_type(value)
    for key in field_order:
        field_types.setdefault(key, "str")
    return {
        "geometry": geometry_type,
        "properties": {key: field_types[key] for key in field_order},
    }


def _vector_property_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Path):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _vector_property_type(value: Any) -> str:
    if value is None:
        return "str"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _geometry_payload(geometry: Any) -> Any:
    if geometry is None:
        return None
    if isinstance(geometry, dict):
        return geometry
    return mapping(geometry)


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
