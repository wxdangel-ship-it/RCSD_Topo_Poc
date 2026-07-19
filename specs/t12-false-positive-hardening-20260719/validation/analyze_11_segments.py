#!/usr/bin/env python3
"""Audit Segment evidence packages before replaying T12.

This validation helper does not modify package inputs.  It verifies whether the
explicit 1V1 FRCSD node slice and the T10 compatibility node slice came from the
same source, and whether the compatibility node slice is a topology-complete
superset for the selected explicit 1V1 FRCSD roads.  The compatibility Road
slice is never substituted because its dependency-preserving materialization
may retain different geometry extents or additional forced roads.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import geopandas as gpd
import pandas as pd

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    field_name,
    normalize_id,
)


def _one_gpkg(case_dir: Path, slot: str) -> Path:
    matches = sorted((case_dir / "external_inputs" / slot).glob("*.gpkg"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one GPKG for {case_dir.name}/{slot}, found {len(matches)}"
        )
    return matches[0].resolve()


def _input_entry(manifest: dict[str, Any], slot: str) -> dict[str, Any]:
    matches = [
        row
        for row in manifest.get("included_external_inputs", [])
        if str(row.get("slot") or "") == slot
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one manifest row for slot {slot}")
    return matches[0]


def _id_map(frame: pd.DataFrame) -> dict[str, Any]:
    id_field = field_name(frame, "id")
    return {
        normalize_id(row[id_field]): row
        for _, row in frame.iterrows()
    }


def _endpoint_ids(roads: pd.DataFrame) -> set[str]:
    start_field = field_name(roads, "snodeid")
    end_field = field_name(roads, "enodeid")
    return {
        normalize_id(value)
        for value in pd.concat([roads[start_field], roads[end_field]])
        if normalize_id(value)
    }


def _common_geometry_equal(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    tolerance: float = 1e-6,
) -> bool:
    for object_id in left.keys() & right.keys():
        left_geometry = left[object_id].geometry
        right_geometry = right[object_id].geometry
        if left_geometry is None or right_geometry is None:
            if left_geometry is not right_geometry:
                return False
            continue
        if not left_geometry.equals_exact(right_geometry, tolerance):
            return False
    return True


def _road_semantics_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    left_map = _id_map(left)
    right_map = _id_map(right)
    if set(left_map) != set(right_map):
        return False
    fields = ("snodeid", "enodeid", "direction")
    left_fields = {name: field_name(left, name) for name in fields}
    right_fields = {name: field_name(right, name) for name in fields}
    for road_id in left_map:
        for name in fields:
            if normalize_id(left_map[road_id][left_fields[name]]) != normalize_id(
                right_map[road_id][right_fields[name]]
            ):
                return False
    return True


def _common_road_semantics_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    left_map = _id_map(left)
    right_map = _id_map(right)
    fields = ("snodeid", "enodeid", "direction")
    left_fields = {name: field_name(left, name) for name in fields}
    right_fields = {name: field_name(right, name) for name in fields}
    for road_id in left_map.keys() & right_map.keys():
        for name in fields:
            if normalize_id(left_map[road_id][left_fields[name]]) != normalize_id(
                right_map[road_id][right_fields[name]]
            ):
                return False
    return True


def _geometry_boundary_points(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    boundary = geometry.boundary
    if boundary is None or boundary.is_empty:
        return []
    return list(boundary.geoms) if hasattr(boundary, "geoms") else [boundary]


def _road_geometry_attachment_missing_count(
    roads: pd.DataFrame,
    nodes: pd.DataFrame,
    *,
    tolerance_m: float = 1.0,
) -> int:
    node_map = _id_map(nodes)
    start_field = field_name(roads, "snodeid")
    end_field = field_name(roads, "enodeid")
    missing = 0
    for _, road in roads.iterrows():
        boundaries = _geometry_boundary_points(road.geometry)
        endpoint_nodes = [
            node_map.get(normalize_id(road[start_field])),
            node_map.get(normalize_id(road[end_field])),
        ]
        if not boundaries or any(node is None for node in endpoint_nodes):
            missing += 1
            continue
        if any(
            min(float(node.geometry.distance(point)) for point in boundaries)
            > tolerance_m
            for node in endpoint_nodes
        ):
            missing += 1
    return missing


def _audit_case(case_dir: Path) -> dict[str, Any]:
    manifest_path = case_dir / "t10_case_evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    explicit_roads_path = _one_gpkg(case_dir, "frcsd_1v1_roads")
    explicit_nodes_path = _one_gpkg(case_dir, "frcsd_1v1_nodes")
    compat_roads_path = _one_gpkg(case_dir, "rcsdroad")
    compat_nodes_path = _one_gpkg(case_dir, "rcsdnode")

    explicit_roads = gpd.read_file(explicit_roads_path)
    explicit_nodes = gpd.read_file(explicit_nodes_path)
    compat_roads = gpd.read_file(compat_roads_path)
    compat_nodes = gpd.read_file(compat_nodes_path)

    explicit_road_map = _id_map(explicit_roads)
    compat_road_map = _id_map(compat_roads)
    explicit_node_map = _id_map(explicit_nodes)
    compat_node_map = _id_map(compat_nodes)
    endpoints = _endpoint_ids(explicit_roads)
    missing_explicit = sorted(endpoints - set(explicit_node_map))
    missing_compat = sorted(endpoints - set(compat_node_map))

    explicit_road_entry = _input_entry(manifest, "frcsd_1v1_roads")
    compat_road_entry = _input_entry(manifest, "rcsdroad")
    explicit_node_entry = _input_entry(manifest, "frcsd_1v1_nodes")
    compat_node_entry = _input_entry(manifest, "rcsdnode")

    road_ids_equal = set(explicit_road_map) == set(compat_road_map)
    explicit_road_ids_are_compat_subset = set(explicit_road_map) <= set(
        compat_road_map
    )
    road_geometry_equal = _common_geometry_equal(
        explicit_road_map,
        compat_road_map,
    )
    road_semantics_equal = _road_semantics_equal(explicit_roads, compat_roads)
    common_road_semantics_equal = _common_road_semantics_equal(
        explicit_roads,
        compat_roads,
    )
    node_subset = set(explicit_node_map) <= set(compat_node_map)
    common_node_geometry_equal = _common_geometry_equal(
        explicit_node_map,
        compat_node_map,
    )
    source_paths_equal = (
        explicit_road_entry.get("source_path") == compat_road_entry.get("source_path")
        and explicit_node_entry.get("source_path")
        == compat_node_entry.get("source_path")
    )
    explicit_road_attachment_missing = _road_geometry_attachment_missing_count(
        explicit_roads,
        compat_nodes,
    )
    compat_road_attachment_missing = _road_geometry_attachment_missing_count(
        compat_roads,
        compat_nodes,
    )
    compatibility_topology_safe = all(
        (
            source_paths_equal,
            explicit_road_ids_are_compat_subset,
            common_road_semantics_equal,
            node_subset,
            common_node_geometry_equal,
            not missing_compat,
            compat_road_attachment_missing == 0,
        )
    )

    scope = manifest.get("scope", {})
    return {
        "segment_id": str(scope.get("swsd_segment_id") or case_dir.name),
        "case_dir": str(case_dir.resolve()),
        "selection_crs": str(scope.get("selection_crs") or ""),
        "buffer_m": float(scope.get("buffer_m") or 0.0),
        "source_paths_equal": source_paths_equal,
        "explicit_road_count": len(explicit_roads),
        "compat_road_count": len(compat_roads),
        "road_ids_equal": road_ids_equal,
        "explicit_road_ids_are_compat_subset": explicit_road_ids_are_compat_subset,
        "road_geometry_equal": road_geometry_equal,
        "road_semantics_equal": road_semantics_equal,
        "common_road_semantics_equal": common_road_semantics_equal,
        "explicit_road_geometry_attachment_missing_count": (
            explicit_road_attachment_missing
        ),
        "compat_road_geometry_attachment_missing_count": (
            compat_road_attachment_missing
        ),
        "explicit_node_count": len(explicit_nodes),
        "compat_node_count": len(compat_nodes),
        "explicit_nodes_are_compat_subset": node_subset,
        "common_node_geometry_equal": common_node_geometry_equal,
        "road_endpoint_count": len(endpoints),
        "explicit_missing_endpoint_count": len(missing_explicit),
        "explicit_missing_endpoint_ids": "|".join(missing_explicit),
        "compat_missing_endpoint_count": len(missing_compat),
        "compat_missing_endpoint_ids": "|".join(missing_compat),
        "compatibility_topology_slice_safe_for_t12_replay": (
            compatibility_topology_safe
        ),
        "topology_silent_fix": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args(argv)

    package_root = args.package_root.resolve()
    case_dirs = sorted(
        path
        for path in package_root.iterdir()
        if path.is_dir() and (path / "t10_case_evidence_manifest.json").is_file()
    )
    if not case_dirs:
        raise RuntimeError(f"no Segment package directories found: {package_root}")

    rows = [_audit_case(case_dir) for case_dir in case_dirs]
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    csv_path = out_root / "package_topology_compatibility_audit.csv"
    json_path = out_root / "package_topology_compatibility_audit.json"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary = {
        "status": (
            "passed"
            if all(
                row["compatibility_topology_slice_safe_for_t12_replay"]
                for row in rows
            )
            else "failed"
        ),
        "package_root": str(package_root),
        "case_count": len(rows),
        "explicit_missing_endpoint_case_count": sum(
            bool(row["explicit_missing_endpoint_count"]) for row in rows
        ),
        "compat_missing_endpoint_case_count": sum(
            bool(row["compat_missing_endpoint_count"]) for row in rows
        ),
        "compatibility_safe_case_count": sum(
            bool(row["compatibility_topology_slice_safe_for_t12_replay"])
            for row in rows
        ),
        "qa": {
            "crs": sorted({row["selection_crs"] for row in rows}),
            "geometry_semantics": (
                "Compatibility Road/Node slices must share the explicit 1V1 source, "
                "contain every explicit Road ID with matching endpoint semantics, "
                "contain every Road endpoint Node, and retain geometry-to-Node "
                "attachment before the topology-complete compatibility subgraph is "
                "used for replay."
            ),
            "topology_silent_fix": False,
            "audit_traceability": str(csv_path),
            "performance_verifiability": {
                "case_count": len(rows),
                "road_feature_count": sum(row["explicit_road_count"] for row in rows),
                "node_feature_count": sum(row["compat_node_count"] for row in rows),
            },
        },
        "rows": rows,
    }
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": str(json_path), **summary}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
