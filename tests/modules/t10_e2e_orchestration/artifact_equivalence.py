from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

import fiona
from pyproj import CRS
from shapely import from_wkb, normalize, set_precision, to_wkb
from shapely.geometry import shape


VECTOR_SUFFIXES = {".gpkg", ".gpkt", ".geojson"}
STRUCTURED_SUFFIXES = VECTOR_SUFFIXES | {".csv", ".json"}
GEOMETRY_COMPARISON_GRID_SIZE_M = 1e-7

_NON_BUSINESS_KEYS = {
    "bootstrap_seconds",
    "command",
    "cwd",
    "duration_seconds",
    "elapsed_seconds",
    "ended_at_utc",
    "estimated_remaining_seconds",
    "finished_at_utc",
    "gc_collected_objects_after_stage",
    "git_sha",
    "input_dataset_id",
    "out_root",
    "payload_size_bytes",
    "per_file_compressed_size_bytes",
    "performance",
    "performance_verifiable",
    "python_executable",
    "run_id",
    "run_started_at",
    "runtime_environment",
    "size_bytes",
    "stage_timers",
    "stage_timings",
    "stage_durations_seconds",
    "started_at_utc",
    "stdout_log",
    "stdout_tail",
    "total_text_size_bytes",
    "total_wall_time_sec",
    "updated_at",
    "wall_time_sec",
    "workers",
}
_NON_BUSINESS_NAME_PATTERNS = (
    re.compile(r"(^|_)duration(_|$)"),
    re.compile(r"(^|_)elapsed(_|$)"),
    re.compile(r"(^|_)(started|ended|finished|created|updated|generated|produced)_at(_utc)?$"),
    re.compile(r"(^|_)(cases_per_minute|estimated_remaining_seconds)$"),
    re.compile(r"(^|_)sha256$"),
    re.compile(r"(^|_)size_bytes$"),
)
_EXCLUDED_RELATIVE_PATTERNS = (
    re.compile(r"(^|/)stdout\.log$"),
    re.compile(r"(^|/).*stdout.*\.json$"),
    re.compile(r"(^|/).*_performance\.json$"),
    re.compile(r"(^|/).*_perf\.json$"),
    re.compile(r"(^|/).*_progress\.json$"),
    re.compile(r"(^|/)t03_perf_audit_(config|samples|summary)\.(json|jsonl)$"),
)
_UNORDERED_ID_COLLECTION_KEYS = {
    "frcsd_road_ids",
    "rcsd_road_ids",
}


def semantic_fingerprint(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    resolved = Path(path)
    suffix = resolved.suffix.lower()
    if suffix in VECTOR_SUFFIXES:
        payload = _vector_payload(resolved, root=root)
    elif suffix == ".csv":
        payload = _csv_payload(resolved, root=root)
    elif suffix == ".json":
        payload = _json_payload(resolved, root=root)
    else:
        raise ValueError(f"Unsupported structured artifact: {resolved}")
    canonical = _canonical_json(payload)
    return {
        "kind": payload["kind"],
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "payload": payload,
    }


def _fingerprint_manifest_path(args: tuple[str, str, str]) -> tuple[str, dict[str, Any]]:
    path_text, root_text, normalization_root_text = args
    path = Path(path_text)
    root = Path(root_text)
    relative = path.relative_to(root).as_posix()
    fingerprint = semantic_fingerprint(path, root=Path(normalization_root_text))
    return relative, {"kind": fingerprint["kind"], "sha256": fingerprint["sha256"]}


def build_tree_manifest(
    root: Path,
    *,
    workers: int = 4,
    normalization_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_root = Path(root)
    resolved_normalization_root = Path(normalization_root) if normalization_root is not None else resolved_root
    paths: list[Path] = []
    for directory, _, filenames in os.walk(resolved_root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in STRUCTURED_SUFFIXES:
                continue
            relative = path.relative_to(resolved_root).as_posix()
            if not _is_excluded_relative_path(relative):
                paths.append(path)
    paths.sort(key=lambda item: item.as_posix())

    effective_workers = max(1, int(workers))
    args = [
        (str(path), str(resolved_root), str(resolved_normalization_root))
        for path in paths
    ]
    if effective_workers == 1:
        entries = [_fingerprint_manifest_path(item) for item in args]
    else:
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            entries = list(executor.map(_fingerprint_manifest_path, args, chunksize=8))
    return dict(entries)


def compare_tree_manifests(
    reference: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    reference_paths = set(reference)
    candidate_paths = set(candidate)
    shared_paths = sorted(reference_paths & candidate_paths)
    changed = [
        path
        for path in shared_paths
        if reference[path].get("sha256") != candidate[path].get("sha256")
    ]
    return {
        "passed": not (reference_paths ^ candidate_paths) and not changed,
        "reference_artifact_count": len(reference),
        "candidate_artifact_count": len(candidate),
        "missing_in_candidate": sorted(reference_paths - candidate_paths),
        "extra_in_candidate": sorted(candidate_paths - reference_paths),
        "changed": changed,
    }


def _is_excluded_relative_path(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in _EXCLUDED_RELATIVE_PATTERNS)


def _json_payload(path: Path, *, root: Path | None) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    return {"kind": "json", "value": _normalize_value(value, root=root)}


def _csv_payload(path: Path, *, root: Path | None) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = [name for name in (reader.fieldnames or []) if not _is_non_business_key(name)]
        rows = [
            {
                name: _normalize_value(row.get(name), root=root, key=name)
                for name in fieldnames
            }
            for row in reader
        ]
    rows.sort(key=_canonical_json)
    return {"kind": "csv", "fieldnames": fieldnames, "rows": rows}


def _vector_payload(path: Path, *, root: Path | None) -> dict[str, Any]:
    if path.suffix.lower() in {".gpkg", ".gpkt"}:
        return _gpkg_payload(path, root=root)
    layers: list[dict[str, Any]] = []
    for layer_name in sorted(fiona.listlayers(path)):
        with fiona.open(path, layer=layer_name) as source:
            rows: list[dict[str, Any]] = []
            for feature in source:
                properties = {
                    str(key): _normalize_value(value, root=root, key=str(key))
                    for key, value in dict(feature["properties"]).items()
                    if not _is_non_business_key(str(key))
                }
                geometry_value = feature.get("geometry")
                geometry_hex = None
                if geometry_value is not None:
                    geometry = normalize(
                        set_precision(shape(geometry_value), GEOMETRY_COMPARISON_GRID_SIZE_M)
                    )
                    geometry_hex = to_wkb(geometry, hex=True, byte_order=1)
                rows.append({"properties": properties, "geometry_wkb": geometry_hex})
            rows.sort(key=_canonical_json)
            layers.append(
                {
                    "name": layer_name,
                    "crs": _normalize_crs(source.crs_wkt or source.crs),
                    "schema": {
                        "geometry": source.schema.get("geometry"),
                        "properties": list(source.schema.get("properties", {}).items()),
                    },
                    "rows": rows,
                }
            )
    return {"kind": "vector", "layers": layers}


def _gpkg_payload(path: Path, *, root: Path | None) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        layer_rows = connection.execute(
            """
            SELECT c.table_name, g.column_name, g.geometry_type_name, g.srs_id
            FROM gpkg_contents AS c
            JOIN gpkg_geometry_columns AS g ON g.table_name = c.table_name
            WHERE c.data_type = 'features'
            ORDER BY c.table_name
            """
        ).fetchall()
        for layer_row in layer_rows:
            table_name = str(layer_row["table_name"])
            geometry_column = str(layer_row["column_name"])
            table_info = connection.execute(
                f"PRAGMA table_info({_quote_identifier(table_name)})"
            ).fetchall()
            property_columns = [
                (str(column["name"]), _sqlite_schema_type(str(column["type"])))
                for column in table_info
                if str(column["name"]) != geometry_column and int(column["pk"] or 0) == 0
            ]
            selected_columns = [name for name, _ in property_columns] + [geometry_column]
            select_sql = (
                f"SELECT {', '.join(_quote_identifier(name) for name in selected_columns)} "
                f"FROM {_quote_identifier(table_name)}"
            )
            rows: list[dict[str, Any]] = []
            for feature_row in connection.execute(select_sql):
                properties = {
                    name: _normalize_value(feature_row[name], root=root, key=name)
                    for name, _ in property_columns
                    if not _is_non_business_key(name)
                }
                geometry_blob = feature_row[geometry_column]
                geometry_hex = None
                if geometry_blob is not None:
                    geometry = normalize(
                        set_precision(
                            from_wkb(_gpkg_geometry_wkb(bytes(geometry_blob))),
                            GEOMETRY_COMPARISON_GRID_SIZE_M,
                        )
                    )
                    geometry_hex = to_wkb(geometry, hex=True, byte_order=1)
                rows.append({"properties": properties, "geometry_wkb": geometry_hex})
            rows.sort(key=_canonical_json)
            layers.append(
                {
                    "name": table_name,
                    "crs": _gpkg_crs(connection, int(layer_row["srs_id"])),
                    "schema": {
                        "geometry": str(layer_row["geometry_type_name"]),
                        "properties": property_columns,
                    },
                    "rows": rows,
                }
            )
    return {"kind": "vector", "layers": layers}


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _sqlite_schema_type(declared_type: str) -> str:
    normalized = str(declared_type).upper()
    if "BOOL" in normalized:
        return "bool"
    if "INT" in normalized:
        return "int"
    if any(token in normalized for token in ("REAL", "FLOA", "DOUB")):
        return "float"
    if "DATETIME" in normalized:
        return "datetime"
    if "DATE" in normalized:
        return "date"
    return "str"


def _gpkg_crs(connection: sqlite3.Connection, srs_id: int) -> str | None:
    row = connection.execute(
        """
        SELECT organization, organization_coordsys_id, definition
        FROM gpkg_spatial_ref_sys
        WHERE srs_id = ?
        """,
        (srs_id,),
    ).fetchone()
    if row is None:
        return str(srs_id)
    organization = str(row["organization"] or "").strip()
    organization_id = row["organization_coordsys_id"]
    if organization and organization.upper() != "NONE" and organization_id is not None:
        authority = organization.upper()
        if authority == "EPSG":
            return f"EPSG:{int(organization_id)}"
        try:
            return CRS.from_user_input(f"{authority}:{int(organization_id)}").to_string()
        except Exception:
            pass
    definition = str(row["definition"] or "").strip()
    if definition and definition.lower() != "undefined":
        try:
            return CRS.from_user_input(definition).to_string()
        except Exception:
            return definition
    return str(srs_id)


def _gpkg_geometry_wkb(blob: bytes) -> bytes:
    if len(blob) < 8 or blob[:2] != b"GP":
        return blob
    flags = blob[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_sizes:
        raise ValueError(f"Unsupported GeoPackage envelope code: {envelope_code}")
    return blob[8 + envelope_sizes[envelope_code] :]


def _normalize_crs(value: Any) -> str | None:
    if not value:
        return None
    return CRS.from_user_input(value).to_string()


def _normalize_value(
    value: Any,
    *,
    root: Path | None,
    key: str | None = None,
    context: tuple[str, ...] = (),
) -> Any:
    if key is not None and _is_non_business_key(key):
        return None
    if isinstance(value, Mapping):
        return {
            str(item_key): _normalize_value(
                item_value,
                root=root,
                key=str(item_key),
                context=(*context, str(item_key)),
            )
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if not _is_non_business_key(str(item_key))
            and not _is_implementation_provenance_key(context, str(item_key))
        }
    if isinstance(value, (list, tuple, set)):
        normalized_items = [
            _normalize_value(item, root=root, context=context)
            for item in value
        ]
        if key in _UNORDERED_ID_COLLECTION_KEYS:
            return sorted(normalized_items, key=_canonical_json)
        return normalized_items
    if isinstance(value, Path):
        return _normalize_path_text(str(value), root=root)
    if isinstance(value, str):
        if key in _UNORDERED_ID_COLLECTION_KEYS:
            parsed_items = _parse_unordered_id_collection(value)
            if parsed_items is not None:
                return sorted(
                    (
                        _normalize_value(item, root=root, context=context)
                        for item in parsed_items
                    ),
                    key=_canonical_json,
                )
        return _normalize_path_text(value, root=root)
    if isinstance(value, float):
        if math.isnan(value):
            return "<NaN>"
        if math.isinf(value):
            return "<Infinity>" if value > 0 else "<-Infinity>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Iterable):
        return [_normalize_value(item, root=root) for item in value]
    return str(value)


def _parse_unordered_id_collection(value: str) -> list[Any] | None:
    text = str(value).strip()
    if not text:
        return []
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (SyntaxError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (list, tuple, set)):
            return list(parsed)
    return None


def _is_non_business_key(key: str) -> bool:
    normalized = str(key).strip().lower()
    if normalized in _NON_BUSINESS_KEYS:
        return True
    return any(pattern.search(normalized) for pattern in _NON_BUSINESS_NAME_PATTERNS)


def _is_implementation_provenance_key(context: tuple[str, ...], key: str) -> bool:
    return "dual_write_manifest" in context and str(key) in {"file", "line"}


def _normalize_path_text(value: str, *, root: Path | None) -> str:
    text = str(value).replace("\\", "/")
    text = re.sub(
        r"(?:/mnt/[a-z]/Users/[^/]+/AppData/Local/Temp|/tmp)/t01_[^/]+/",
        "<TEMP>/",
        text,
        flags=re.IGNORECASE,
    )
    if root is None:
        return text
    for alias in _root_aliases(root):
        normalized_alias = alias.rstrip("/")
        if normalized_alias and normalized_alias in text:
            text = text.replace(normalized_alias, "<ROOT>")
    return text


@lru_cache(maxsize=32)
def _root_aliases(root: Path) -> tuple[str, ...]:
    resolved = Path(root).resolve()
    windows = resolved.as_posix()
    aliases = {windows, str(resolved).replace("\\", "/")}
    for value in tuple(aliases):
        marker = "/outputs/"
        if marker in value:
            aliases.add(value.split(marker, 1)[0])
    drive_match = re.match(r"^([A-Za-z]):/(.*)$", windows)
    if drive_match:
        aliases.add(f"/mnt/{drive_match.group(1).lower()}/{drive_match.group(2)}")
    return tuple(sorted(aliases, key=len, reverse=True))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
