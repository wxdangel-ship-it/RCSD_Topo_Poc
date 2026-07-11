from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    write_vector as write_fiona_vector,
)


def _restore_declared_geometry_type(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE gpkg_geometry_columns
            SET geometry_type_name = 'GEOMETRY',
                z = CASE WHEN z = 1 THEN 2 ELSE z END
            """
        )
        connection.commit()


def write_case_polygon_vector(
    path: Path,
    features: Iterable[dict[str, Any]],
) -> None:
    output_path = Path(path)
    write_vector(output_path, features)
    _restore_declared_geometry_type(output_path)


def write_case_event_vector(
    path: Path,
    features: Iterable[dict[str, Any]],
) -> None:
    output_path = Path(path)
    records = list(features)
    if any(
        geometry is not None and bool(getattr(geometry, "has_z", False))
        for geometry in (record.get("geometry") for record in records)
    ):
        write_fiona_vector(output_path, records, crs_text="EPSG:3857")
        return
    write_vector(output_path, records)
    _restore_declared_geometry_type(output_path)


__all__ = ["write_case_event_vector", "write_case_polygon_vector"]
