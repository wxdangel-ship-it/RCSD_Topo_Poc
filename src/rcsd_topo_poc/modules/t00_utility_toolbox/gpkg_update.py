from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _feature_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _resolve_feature_table(
    connection: sqlite3.Connection,
    *,
    layer_name: str | None,
    fallback_stem: str,
) -> str:
    tables = _feature_tables(connection)
    if not tables:
        raise ValueError("GeoPackage has no feature table registered in gpkg_contents")
    if layer_name:
        if layer_name not in tables:
            raise ValueError(f"GeoPackage feature table not found: {layer_name}")
        return layer_name
    if fallback_stem in tables:
        return fallback_stem
    if "nodes" in tables:
        return "nodes"
    if len(tables) == 1:
        return tables[0]
    raise ValueError(f"Unable to infer GeoPackage feature table from candidates: {tables}")


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return {str(row[1]) for row in rows}


def _register_gpkg_trigger_functions(connection: sqlite3.Connection) -> None:
    # Fiona/GDAL GeoPackages commonly install RTree triggers that reference
    # SpatiaLite-style functions even when only non-geometry fields are updated.
    connection.create_function("ST_IsEmpty", 1, lambda _geometry: 0)
    connection.create_function("ST_MinX", 1, lambda _geometry: 0.0)
    connection.create_function("ST_MaxX", 1, lambda _geometry: 0.0)
    connection.create_function("ST_MinY", 1, lambda _geometry: 0.0)
    connection.create_function("ST_MaxY", 1, lambda _geometry: 0.0)


def copy_gpkg_and_update_field_by_id(
    *,
    source_path: str | Path,
    output_path: str | Path,
    updates_by_id: Mapping[str, Any],
    id_field: str = "id",
    update_field: str = "is_anchor",
    layer_name: str | None = None,
) -> dict[str, Any]:
    """Copy a GeoPackage and update one attribute column in a single SQLite transaction."""
    source = Path(source_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(f"source GeoPackage not found: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        _unlink_with_retry(output)
    shutil.copy2(source, output)

    return update_gpkg_field_by_id(
        path=output,
        updates_by_id=updates_by_id,
        id_field=id_field,
        update_field=update_field,
        layer_name=layer_name,
        strategy="sqlite_copy_update",
    )


def update_gpkg_field_by_id(
    *,
    path: str | Path,
    updates_by_id: Mapping[str, Any],
    id_field: str = "id",
    update_field: str = "is_anchor",
    layer_name: str | None = None,
    strategy: str = "sqlite_in_place_update",
) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"GeoPackage not found: {target}")

    normalized_updates = {
        str(key): value
        for key, value in updates_by_id.items()
        if str(key or "").strip()
    }
    if not normalized_updates:
        return {
            "strategy": strategy,
            "layer_name": "",
            "requested_update_count": 0,
            "sqlite_changed_row_count": 0,
        }

    with sqlite3.connect(str(target)) as connection:
        _register_gpkg_trigger_functions(connection)
        table_name = _resolve_feature_table(
            connection,
            layer_name=layer_name,
            fallback_stem=target.stem,
        )
        columns = _table_columns(connection, table_name)
        missing = [field for field in (id_field, update_field) if field not in columns]
        if missing:
            raise ValueError(f"GeoPackage table {table_name!r} missing required column(s): {missing}")

        quoted_table = _quote_identifier(table_name)
        quoted_update_field = _quote_identifier(update_field)
        quoted_id_field = _quote_identifier(id_field)
        before = connection.total_changes
        with connection:
            connection.executemany(
                f"UPDATE {quoted_table} SET {quoted_update_field} = ? WHERE {quoted_id_field} = ?",
                [(value, key) for key, value in normalized_updates.items()],
            )
        changed = connection.total_changes - before

    return {
        "strategy": strategy,
        "layer_name": table_name,
        "requested_update_count": len(normalized_updates),
        "sqlite_changed_row_count": changed,
    }


def _unlink_with_retry(path: Path, *, attempts: int = 5, delay_sec: float = 0.05) -> None:
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_sec)


__all__ = ["copy_gpkg_and_update_field_by_id"]
