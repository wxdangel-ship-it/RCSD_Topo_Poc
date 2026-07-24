from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import fiona
from fiona.errors import UnsupportedGeometryTypeError
from pyproj import CRS
from shapely import from_wkb
from shapely.geometry import mapping, shape


ROAD_ACTIONS = ("COPY", "UPDATE", "SPLIT", "CREATE", "DROP")
NODE_ACTIONS = ("COPY", "UPDATE", "CREATE", "DROP")
ROAD_CORE_FIELDS = ("direction", "source", "snodeid", "enodeid")


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _property(properties: dict[str, Any], name: str) -> Any:
    folded = name.casefold()
    for key, value in properties.items():
        if str(key).casefold() == folded:
            return value
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _geometry_equal(first: dict[str, Any] | None, second: dict[str, Any] | None) -> bool:
    if first is None or second is None:
        return first is second
    return bool(shape(first).equals_exact(shape(second), tolerance=1.0e-9))


def _road_core_equal(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if not _geometry_equal(first.get("geometry"), second.get("geometry")):
        return False
    first_properties = dict(first.get("properties") or {})
    second_properties = dict(second.get("properties") or {})
    return all(
        _id_text(_property(first_properties, name)) == _id_text(_property(second_properties, name))
        for name in ROAD_CORE_FIELDS
    )


def _payload_id(payload: dict[str, Any]) -> str:
    identifier = _id_text(payload.get("id"))
    if not identifier:
        identifier = _id_text(_property(dict(payload.get("properties") or {}), "id"))
    if not identifier:
        raise ValueError("feature payload has no id")
    return identifier


def _edit(
    *,
    kind: str,
    action: str,
    base_id: str,
    outputs: list[dict[str, Any]],
    lineage_kind: str,
) -> dict[str, Any]:
    output_ids = [_payload_id(payload) for payload in outputs]
    anchor = base_id or (output_ids[0] if output_ids else "none")
    return {
        "edit_id": f"{kind.casefold()}:{action.casefold()}:{anchor}",
        "object_kind": kind,
        "action": action,
        "base_object_id": base_id,
        "output_object_ids": output_ids,
        "output_payloads": outputs,
        "lineage_kind": lineage_kind,
        "label_only": True,
    }


def _summary(edits: list[dict[str, Any]], truth_count: int) -> dict[str, Any]:
    action_counts = Counter(str(edit["action"]) for edit in edits)
    output_ids = {
        _payload_id(payload)
        for edit in edits
        for payload in list(edit.get("output_payloads") or [])
    }
    represented = len(output_ids)
    return {
        "action_counts": dict(sorted(action_counts.items())),
        "truth_count": truth_count,
        "represented_truth_count": represented,
        "coverage": represented / truth_count if truth_count else 1.0,
    }


def derive_road_edits(
    base_roads: dict[str, dict[str, Any]],
    truth_roads: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for truth in truth_roads.values():
        parent_id = _id_text(_property(dict(truth.get("properties") or {}), "t06_split_original_road_id"))
        if parent_id:
            children_by_parent[parent_id].append(truth)

    edits: list[dict[str, Any]] = []
    consumed_truth: set[str] = set()
    for base_id in sorted(base_roads):
        base = base_roads[base_id]
        exact = truth_roads.get(base_id)
        if exact is not None:
            action = "COPY" if _road_core_equal(base, exact) else "UPDATE"
            edits.append(
                _edit(
                    kind="Road",
                    action=action,
                    base_id=base_id,
                    outputs=[exact],
                    lineage_kind="same_id",
                )
            )
            consumed_truth.add(base_id)
            continue
        children = [item for item in children_by_parent.get(base_id, []) if _payload_id(item) not in consumed_truth]
        if children:
            children.sort(key=_payload_id)
            edits.append(
                _edit(
                    kind="Road",
                    action="SPLIT",
                    base_id=base_id,
                    outputs=children,
                    lineage_kind="split_parent",
                )
            )
            consumed_truth.update(_payload_id(item) for item in children)
            continue
        edits.append(_edit(kind="Road", action="DROP", base_id=base_id, outputs=[], lineage_kind="base_only"))

    for truth_id in sorted(set(truth_roads) - consumed_truth):
        edits.append(
            _edit(
                kind="Road",
                action="CREATE",
                base_id="",
                outputs=[truth_roads[truth_id]],
                lineage_kind="create",
            )
        )

    return edits, _summary(edits, len(truth_roads))


def derive_node_edits(
    base_nodes: dict[str, dict[str, Any]],
    truth_nodes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    edits: list[dict[str, Any]] = []
    consumed_truth: set[str] = set()
    for base_id in sorted(base_nodes):
        base = base_nodes[base_id]
        exact = truth_nodes.get(base_id)
        if exact is None:
            edits.append(_edit(kind="Node", action="DROP", base_id=base_id, outputs=[], lineage_kind="base_only"))
            continue
        action = "COPY" if _geometry_equal(base.get("geometry"), exact.get("geometry")) else "UPDATE"
        edits.append(
            _edit(kind="Node", action=action, base_id=base_id, outputs=[exact], lineage_kind="same_id")
        )
        consumed_truth.add(base_id)
    for truth_id in sorted(set(truth_nodes) - consumed_truth):
        edits.append(
            _edit(
                kind="Node",
                action="CREATE",
                base_id="",
                outputs=[truth_nodes[truth_id]],
                lineage_kind="create",
            )
        )
    return edits, _summary(edits, len(truth_nodes))


def materialize_edit_payloads(
    road_edits: Iterable[dict[str, Any]],
    node_edits: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    def collect(edits: Iterable[dict[str, Any]], *, kind: str, allowed: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for edit in edits:
            action = str(edit.get("action") or "")
            if action not in allowed:
                raise ValueError(f"invalid {kind} action: {action}")
            for payload in list(edit.get("output_payloads") or []):
                identifier = _payload_id(payload)
                if identifier in output:
                    raise ValueError(f"duplicate {kind} output id: {identifier}")
                output[identifier] = payload
        return output

    return (
        collect(road_edits, kind="Road", allowed=ROAD_ACTIONS),
        collect(node_edits, kind="Node", allowed=NODE_ACTIONS),
    )


def derive_t05_pointers(
    relation_rows: Iterable[dict[str, Any]],
    candidate_base_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in relation_rows:
        target_id = _id_text(_property(row, "target_id"))
        if target_id:
            grouped[target_id].append(row)

    pointers: list[dict[str, Any]] = []
    expressible = 0
    cardinality_errors = 0
    missing_bases = 0
    for target_id in sorted(grouped):
        rows = grouped[target_id]
        accepted = [row for row in rows if _id_text(_property(row, "status")) == "0"]
        accepted_base_ids = sorted({_id_text(_property(row, "base_id")) for row in accepted if _id_text(_property(row, "base_id"))})
        cardinality_error = len(accepted_base_ids) > 1
        selected = accepted_base_ids[0] if len(accepted_base_ids) == 1 else ""
        selected_exists = bool(selected and selected in candidate_base_ids)
        no_match = len(accepted_base_ids) == 0
        is_expressible = (no_match or selected_exists) and not cardinality_error
        if cardinality_error:
            cardinality_errors += 1
        if selected and not selected_exists:
            missing_bases += 1
        if is_expressible:
            expressible += 1
        pointers.append(
            {
                "target_id": target_id,
                "accepted_base_ids": accepted_base_ids,
                "selected_base_id": selected,
                "selected_base_exists": selected_exists,
                "no_match": no_match,
                "cardinality_error": cardinality_error,
                "candidate_pool_size": len(candidate_base_ids),
                "label_only": True,
            }
        )

    count = len(pointers)
    return pointers, {
        "target_count": count,
        "expressible_target_count": expressible,
        "coverage": expressible / count if count else 1.0,
        "cardinality_error_count": cardinality_errors,
        "missing_selected_base_count": missing_bases,
    }


def semantic_node_candidate_ids(payloads: dict[str, dict[str, Any]]) -> set[str]:
    candidate_ids = set(payloads)
    for payload in payloads.values():
        mainnode_id = _id_text(_property(dict(payload.get("properties") or {}), "mainnodeid"))
        if mainnode_id and mainnode_id not in {"0", "0.0"}:
            candidate_ids.add(mainnode_id)
    return candidate_ids


def _read_vector_payloads_fiona(
    path: Path,
    *,
    source_role: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    layers = fiona.listlayers(path)
    if len(layers) != 1:
        raise ValueError(f"expected one layer in {path}, got {len(layers)}")
    layer = layers[0]
    payloads: dict[str, dict[str, Any]] = {}
    with fiona.open(path, layer=layer) as source:
        meta = {
            "layer": layer,
            "driver": source.driver,
            "schema": _json_safe(dict(source.schema)),
            "crs_wkt": source.crs_wkt or "",
        }
        for feature in source:
            properties = _json_safe(dict(feature["properties"]))
            identifier = _id_text(_property(properties, "id"))
            if not identifier:
                raise ValueError(f"feature without id in {path}")
            if identifier in payloads:
                raise ValueError(f"duplicate feature id {identifier} in {path}")
            geometry = mapping(shape(feature["geometry"])) if feature["geometry"] is not None else None
            payloads[identifier] = {
                "id": identifier,
                "geometry": _json_safe(geometry),
                "properties": properties,
                "source_role": source_role,
            }
    return payloads, meta


def _sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _gpkg_wkb(blob: bytes) -> bytes:
    if len(blob) < 8 or blob[:2] != b"GP":
        raise ValueError("invalid GeoPackage geometry header")
    envelope_code = (blob[3] >> 1) & 0b111
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code)
    if envelope_bytes is None:
        raise ValueError(f"unsupported GeoPackage envelope code: {envelope_code}")
    header_bytes = 8 + envelope_bytes
    if len(blob) <= header_bytes:
        raise ValueError("GeoPackage geometry contains no WKB payload")
    return blob[header_bytes:]


def _sqlite_property_type(declared_type: str) -> str:
    folded = declared_type.upper()
    if "INT" in folded:
        return "int"
    if any(token in folded for token in ("REAL", "FLOA", "DOUB")):
        return "float"
    if "BLOB" in folded:
        return "bytes"
    return "str"


def _read_unknown_3d_gpkg(
    path: Path,
    *,
    source_role: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(path) as connection:
        geometry_rows = connection.execute(
            "SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns"
        ).fetchall()
        if len(geometry_rows) != 1:
            raise ValueError(f"expected one geometry layer in {path}, got {len(geometry_rows)}")
        layer, geometry_column, srs_id = geometry_rows[0]
        columns = connection.execute(f"PRAGMA table_info({_sqlite_identifier(str(layer))})").fetchall()
        property_columns = [
            (str(row[1]), str(row[2] or ""))
            for row in columns
            if str(row[1]) != str(geometry_column)
            and not (int(row[5] or 0) and str(row[1]).casefold() in {"fid", "ogc_fid"})
        ]
        selected_columns = [name for name, _ in property_columns] + [str(geometry_column)]
        query = "SELECT " + ", ".join(_sqlite_identifier(name) for name in selected_columns)
        query += " FROM " + _sqlite_identifier(str(layer))
        geometry_types: set[str] = set()
        has_z = False
        for row in connection.execute(query):
            properties = _json_safe(dict(zip((name for name, _ in property_columns), row[:-1], strict=True)))
            identifier = _id_text(_property(properties, "id"))
            if not identifier:
                raise ValueError(f"feature without id in {path}")
            if identifier in payloads:
                raise ValueError(f"duplicate feature id {identifier} in {path}")
            geometry_blob = row[-1]
            geometry = None
            if geometry_blob is not None:
                shapely_geometry = from_wkb(_gpkg_wkb(bytes(geometry_blob)))
                geometry = mapping(shapely_geometry)
                geometry_types.add(shapely_geometry.geom_type)
                has_z = has_z or bool(shapely_geometry.has_z)
            payloads[identifier] = {
                "id": identifier,
                "geometry": _json_safe(geometry),
                "properties": properties,
                "source_role": source_role,
            }
        if len(geometry_types) == 1:
            geometry_type = next(iter(geometry_types))
            if has_z:
                geometry_type = f"3D {geometry_type}"
        else:
            geometry_type = "Unknown"
        crs_wkt = ""
        try:
            crs_wkt = CRS.from_epsg(int(srs_id)).to_wkt()
        except (ValueError, TypeError):
            pass
        meta = {
            "layer": str(layer),
            "driver": "GPKG",
            "schema": {
                "properties": {name: _sqlite_property_type(kind) for name, kind in property_columns},
                "geometry": geometry_type,
            },
            "crs_wkt": crs_wkt,
        }
    return payloads, meta


def read_vector_payloads(
    path: Path,
    *,
    source_role: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        return _read_vector_payloads_fiona(path, source_role=source_role)
    except UnsupportedGeometryTypeError:
        if path.suffix.casefold() != ".gpkg":
            raise
        return _read_unknown_3d_gpkg(path, source_role=source_role)


def write_vector_payloads(
    path: Path,
    payloads: Iterable[dict[str, Any]],
    *,
    meta: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = dict(meta["schema"])
    property_names = list(dict(schema.get("properties") or {}))
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer=str(meta["layer"]),
        schema=schema,
        crs_wkt=str(meta.get("crs_wkt") or ""),
    ) as sink:
        for payload in sorted(payloads, key=_payload_id):
            properties = dict(payload.get("properties") or {})
            sink.write(
                {
                    "geometry": payload.get("geometry"),
                    "properties": {name: properties.get(name) for name in property_names},
                }
            )


__all__ = [
    "NODE_ACTIONS",
    "ROAD_ACTIONS",
    "derive_node_edits",
    "derive_road_edits",
    "derive_t05_pointers",
    "materialize_edit_payloads",
    "read_vector_payloads",
    "semantic_node_candidate_ids",
    "write_vector_payloads",
]
