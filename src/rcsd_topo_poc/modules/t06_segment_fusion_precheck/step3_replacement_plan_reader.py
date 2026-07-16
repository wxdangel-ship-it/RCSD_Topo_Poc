from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .io import read_features, write_json


_DEFERRED_PLAN_WRITE_DEPTH = 0
_DEFERRED_PLAN_ROWS: dict[Path, list[dict[str, Any]]] = {}


@contextmanager
def defer_replacement_plan_writes() -> Iterator[None]:
    global _DEFERRED_PLAN_WRITE_DEPTH
    if _DEFERRED_PLAN_WRITE_DEPTH == 0:
        _DEFERRED_PLAN_ROWS.clear()
    _DEFERRED_PLAN_WRITE_DEPTH += 1
    try:
        yield
    finally:
        _DEFERRED_PLAN_WRITE_DEPTH -= 1
        if _DEFERRED_PLAN_WRITE_DEPTH == 0:
            _DEFERRED_PLAN_ROWS.clear()


def write_replacement_plan_json(path: Path, rows: list[dict[str, Any]]) -> None:
    if _DEFERRED_PLAN_WRITE_DEPTH <= 0:
        write_json(path, {"row_count": len(rows), "features": rows})
        return
    _DEFERRED_PLAN_ROWS[_resolved_plan_path(path)] = rows


def materialize_deferred_replacement_plan(path: Path | None) -> bool:
    if path is None:
        return False
    rows = _DEFERRED_PLAN_ROWS.get(_resolved_plan_path(path))
    if rows is None:
        return False
    write_json(path, {"row_count": len(rows), "features": rows})
    return True


def retire_deferred_replacement_plan(candidate_path: Path, final_path: Path) -> bool:
    if candidate_path == final_path:
        return False
    return _DEFERRED_PLAN_ROWS.pop(_resolved_plan_path(candidate_path), None) is not None


def is_deferred_replacement_plan(path: str | Path) -> bool:
    return _resolved_plan_path(Path(path)) in _DEFERRED_PLAN_ROWS


def read_replacement_plan_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    plan_path = Path(path)
    deferred_rows = _DEFERRED_PLAN_ROWS.get(_resolved_plan_path(plan_path))
    if deferred_rows is not None:
        return _plan_row_snapshots(deferred_rows)
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


def _plan_row_snapshots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"properties": dict(item.get("properties") or {}), "geometry": item.get("geometry")}
        for item in rows
    ]


def copy_replacement_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for row in rows:
        properties = {
            key: value
            for key, value in dict(row.get("properties") or {}).items()
            if value is not None and key != "absorbed_group_member_segments"
        }
        copied.append(
            {
                "type": row.get("type", "Feature"),
                "properties": properties,
                "geometry": row.get("geometry"),
            }
        )
    return copied


def _resolved_plan_path(path: Path) -> Path:
    return path.absolute()


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
