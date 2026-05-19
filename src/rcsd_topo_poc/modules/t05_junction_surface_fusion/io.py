from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerReadResult, read_vector_layer

from .models import TARGET_CRS_TEXT


def produced_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"t05_phase1_{stamp}"


def prepare_run_root(out_root: str | Path, run_id: str | None) -> Path:
    root = Path(out_root) / (run_id or default_run_id())
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_surfaces(
    path: str | Path,
    *,
    layer_name: str | None = None,
    crs_override: str | None = None,
) -> LayerReadResult:
    return read_vector_layer(path, layer_name=layer_name, crs_override=crs_override)


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
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def write_gpkg(path: str | Path, features: Iterable[dict[str, Any]]) -> None:
    write_vector(Path(path), features, crs_text=TARGET_CRS_TEXT)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
