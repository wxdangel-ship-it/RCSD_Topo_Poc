from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .io import read_features


def read_replacement_plan_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    plan_path = Path(path)
    suffix = plan_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_with_vector_sidecar(plan_path)
    rows = _read_json_rows(plan_path) if suffix == ".json" else read_features(plan_path)
    return _merge_csv_sidecar(rows, plan_path.with_suffix(".csv"))


def _read_csv_with_vector_sidecar(path: Path) -> list[dict[str, Any]]:
    sidecar = path.with_suffix(".gpkg")
    if sidecar.is_file():
        return _merge_csv_sidecar(read_features(sidecar), path)
    json_sidecar = path.with_suffix(".json")
    if json_sidecar.is_file():
        return _merge_csv_sidecar(_read_json_rows(json_sidecar), path)
    return _csv_rows(path)


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", []) if isinstance(payload, dict) else []
    return [{"properties": dict(item.get("properties") or {}), "geometry": item.get("geometry")} for item in features]


def _merge_csv_sidecar(rows: list[dict[str, Any]], csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.is_file():
        return rows
    merged = list(rows)
    seen = {_plan_key(row) for row in merged}
    for row in _csv_rows(csv_path):
        key = _plan_key(row)
        if key and key in seen:
            continue
        merged.append(row)
        if key:
            seen.add(key)
    return merged


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        return [{"properties": dict(row), "geometry": None} for row in csv.DictReader(fp)]


def _plan_key(row: dict[str, Any]) -> str:
    props = row.get("properties") or {}
    return str(props.get("replacement_plan_id") or "")
