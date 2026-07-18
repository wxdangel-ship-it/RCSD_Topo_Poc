from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    read_vector,
    resolve_field_name,
    write_gpkg,
)
from rcsd_topo_poc.utils.field_names import normalize_field_name, normalize_property_keys


REQUIRED_OVERRIDE_FIELDS = (
    "road_id",
    "endpoint_field",
    "expected_old_node_id",
    "replacement_node_id",
)


@dataclass(frozen=True)
class EndpointOverrideArtifacts:
    corrected_roads: Path
    confirmed_overrides: Path
    audit: Path


def apply_confirmed_endpoint_overrides(
    *,
    roads_path: str | Path,
    nodes_path: str | Path,
    override_list_path: str | Path,
    out_dir: str | Path,
    expected_override_count: int | None = None,
) -> EndpointOverrideArtifacts:
    roads_input = Path(roads_path).expanduser().resolve()
    nodes_input = Path(nodes_path).expanduser().resolve()
    overrides_input = Path(override_list_path).expanduser().resolve()
    output_root = Path(out_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    roads_output = output_root / "RCSDRoad_endpoint_override.gpkg"
    overrides_output = output_root / "p02_confirmed_endpoint_overrides.csv"
    audit_output = output_root / "p02_rcsd_endpoint_override_audit.json"
    for path in (roads_output, overrides_output, audit_output):
        if path.exists():
            raise FileExistsError(f"endpoint override output already exists: {path}")

    overrides = _load_overrides(overrides_input)
    if expected_override_count is not None and len(overrides) != expected_override_count:
        raise ValueError(
            f"expected {expected_override_count} confirmed endpoint overrides, got {len(overrides)}"
        )

    roads = read_vector(roads_input, target_epsg=None)
    nodes = read_vector(nodes_input, target_epsg=None)
    road_id_field = resolve_field_name(roads.features, ["id"], "RCSDRoad")
    snode_field = resolve_field_name(roads.features, ["snodeid"], "RCSDRoad")
    enode_field = resolve_field_name(roads.features, ["enodeid"], "RCSDRoad")
    endpoint_fields = {"snodeid": snode_field, "enodeid": enode_field}
    node_id_field = resolve_field_name(nodes.features, ["id"], "RCSDNode")
    node_ids = {_text(feature.properties.get(node_id_field)) for feature in nodes.features}

    replacement_node_match_counts = {
        item["replacement_node_id"]: sum(
            _text(feature.properties.get(node_id_field)) == item["replacement_node_id"]
            for feature in nodes.features
        )
        for item in overrides
    }
    invalid_replacements = {
        node_id: count
        for node_id, count in replacement_node_match_counts.items()
        if count != 1
    }
    if invalid_replacements:
        raise ValueError(f"replacement RCSDNode must exist exactly once: {invalid_replacements}")

    overrides_by_road: dict[str, list[dict[str, str]]] = {}
    for item in overrides:
        overrides_by_road.setdefault(item["road_id"], []).append(item)
    target_match_counts = {
        _override_key(item): 0
        for item in overrides
    }
    output_features: list[dict[str, Any]] = []
    applied_overrides: list[dict[str, Any]] = []
    for feature in roads.features:
        properties = dict(feature.properties)
        road_id = _text(properties.get(road_id_field))
        for override in overrides_by_road.get(road_id, []):
            key = _override_key(override)
            target_match_counts[key] += 1
            endpoint_field = endpoint_fields[override["endpoint_field"]]
            old_value = _text(properties.get(endpoint_field))
            if old_value != override["expected_old_node_id"]:
                raise ValueError(
                    "confirmed override old value mismatch: "
                    f"road={road_id}, field={endpoint_field}, "
                    f"expected={override['expected_old_node_id']}, actual={old_value}"
                )
            before = {
                "road_id": road_id,
                "snodeid": _text(properties.get(snode_field)),
                "enodeid": _text(properties.get(enode_field)),
            }
            properties[endpoint_field] = int(override["replacement_node_id"])
            after = {
                "road_id": road_id,
                "snodeid": _text(properties.get(snode_field)),
                "enodeid": _text(properties.get(enode_field)),
            }
            applied_overrides.append(
                {
                    **override,
                    "resolved_endpoint_field": endpoint_field,
                    "before": before,
                    "after": after,
                }
            )
        output_features.append({"properties": properties, "geometry": feature.geometry})

    invalid_targets = {key: count for key, count in target_match_counts.items() if count != 1}
    if invalid_targets or len(applied_overrides) != len(overrides):
        raise ValueError(f"target RCSDRoad endpoint must exist exactly once: {invalid_targets}")

    missing_before = _missing_endpoint_ids(
        roads.features,
        node_ids,
        snode_field,
        enode_field,
    )
    write_gpkg(
        roads_output,
        output_features,
        crs_text=roads.output_crs.to_string(),
        empty_fields=roads.field_names,
        geometry_type="LineString",
    )
    shutil.copy2(overrides_input, overrides_output)

    written = read_vector(roads_output, target_epsg=None)
    written_id_field = resolve_field_name(written.features, ["id"], "corrected RCSDRoad")
    written_snode_field = resolve_field_name(written.features, ["snodeid"], "corrected RCSDRoad")
    written_enode_field = resolve_field_name(written.features, ["enodeid"], "corrected RCSDRoad")
    input_by_id = {_text(feature.properties.get(road_id_field)): feature for feature in roads.features}
    output_by_id = {
        _text(feature.properties.get(written_id_field)): feature for feature in written.features
    }
    road_count_unchanged = len(roads.features) == len(written.features)
    road_id_set_unchanged = set(input_by_id) == set(output_by_id)
    geometry_unchanged = road_id_set_unchanged and all(
        input_by_id[road_id].geometry.equals_exact(output_by_id[road_id].geometry, 0.0)
        for road_id in input_by_id
    )

    changed_cells: list[dict[str, str]] = []
    if road_id_set_unchanged:
        for road_id, before_feature in input_by_id.items():
            after_feature = output_by_id[road_id]
            for field in roads.field_names:
                before_value = _text(before_feature.properties.get(field))
                after_value = _text(after_feature.properties.get(field))
                if before_value != after_value:
                    changed_cells.append(
                        {
                            "road_id": road_id,
                            "field": field,
                            "before": before_value,
                            "after": after_value,
                        }
                    )
    expected_changed_cells = [
        {
            "road_id": item["road_id"],
            "field": endpoint_fields[item["endpoint_field"]],
            "before": item["expected_old_node_id"],
            "after": item["replacement_node_id"],
        }
        for item in overrides
    ]
    cell_key = lambda row: (row["road_id"], row["field"], row["before"], row["after"])
    changed_cells.sort(key=cell_key)
    expected_changed_cells.sort(key=cell_key)
    only_confirmed_fields_changed = changed_cells == expected_changed_cells

    missing_after = _missing_endpoint_ids(
        written.features,
        node_ids,
        written_snode_field,
        written_enode_field,
    )
    passed = all(
        (
            road_count_unchanged,
            road_id_set_unchanged,
            geometry_unchanged,
            only_confirmed_fields_changed,
            not missing_after,
            overrides_input.read_bytes() == overrides_output.read_bytes(),
        )
    )
    audit = {
        "status": "passed" if passed else "failed",
        "policy": "user_confirmed_copy_on_write_endpoint_override_list",
        "overrides": sorted(applied_overrides, key=lambda row: (row["road_id"], row["endpoint_field"])),
        "checks": {
            "target_endpoint_match_counts": target_match_counts,
            "replacement_node_match_counts": replacement_node_match_counts,
            "input_road_count": len(roads.features),
            "output_road_count": len(written.features),
            "confirmed_override_count": len(overrides),
            "road_count_unchanged": road_count_unchanged,
            "road_id_set_unchanged": road_id_set_unchanged,
            "geometry_unchanged": geometry_unchanged,
            "only_confirmed_fields_changed": only_confirmed_fields_changed,
            "changed_property_cells": changed_cells,
            "missing_endpoint_ids_before": sorted(missing_before),
            "missing_endpoint_ids_after": sorted(missing_after),
            "missing_endpoint_count_before": len(missing_before),
            "missing_endpoint_count_after": len(missing_after),
            "override_list_byte_identical": overrides_input.read_bytes() == overrides_output.read_bytes(),
            "crosslid_used": False,
            "nodelid_used": False,
            "geometry_inference_used": False,
        },
        "crs": {
            "input": roads.output_crs.to_string(),
            "output": written.output_crs.to_string(),
        },
        "paths": {
            "input_roads": str(roads_input),
            "nodes": str(nodes_input),
            "working_roads": str(roads_output),
            "confirmed_override_list_source": str(overrides_input),
            "confirmed_override_list_copy": str(overrides_output),
        },
        "hashes": {
            "input_roads_sha256": _sha256(roads_input),
            "working_roads_sha256": _sha256(roads_output),
            "confirmed_override_list_sha256": _sha256(overrides_input),
        },
    }
    audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed:
        raise RuntimeError(f"confirmed endpoint override verification failed; see {audit_output}")
    return EndpointOverrideArtifacts(
        corrected_roads=roads_output,
        confirmed_overrides=overrides_output,
        audit=audit_output,
    )


def _load_overrides(path: Path) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {normalize_field_name(field) for field in (reader.fieldnames or ())}
        if set(REQUIRED_OVERRIDE_FIELDS) - fieldnames:
            raise ValueError(f"invalid confirmed endpoint override schema: {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"confirmed endpoint override list is empty: {path}")
    overrides: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        item = {key: _text(value) for key, value in normalize_property_keys(row).items()}
        item["endpoint_field"] = normalize_field_name(item["endpoint_field"])
        if not all(item.get(field) for field in REQUIRED_OVERRIDE_FIELDS):
            raise ValueError(f"invalid confirmed endpoint override row: {row}")
        if item["endpoint_field"] not in {"snodeid", "enodeid"}:
            raise ValueError(f"unsupported endpoint field: {item['endpoint_field']}")
        key = _override_key(item)
        if key in seen:
            raise ValueError(f"duplicate confirmed endpoint override: {key}")
        seen.add(key)
        overrides.append(item)
    return tuple(overrides)


def _override_key(item: dict[str, str]) -> str:
    return f"{item['road_id']}.{item['endpoint_field']}"


def _missing_endpoint_ids(
    road_features: list[Any],
    node_ids: set[str],
    snode_field: str,
    enode_field: str,
) -> set[str]:
    missing: set[str] = set()
    for feature in road_features:
        for field in (snode_field, enode_field):
            node_id = _text(feature.properties.get(field))
            if node_id and node_id not in node_ids:
                missing.add(node_id)
    return missing


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = ["EndpointOverrideArtifacts", "apply_confirmed_endpoint_overrides"]
