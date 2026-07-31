from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import pandas as pd

from .junction_audit import JunctionAuditResult


JUNCTION_FIELDS = (
    "run_id",
    "candidate_id",
    "object_type",
    "junction_id",
    "target_group_node_ids",
    "candidate_status",
    "review_status",
    "issue_type",
    "detection_rule",
    "decision_rule",
    "association_class",
    "association_state",
    "required_rcsdnode_ids",
    "support_rcsdroad_ids",
    "support_id_source",
    "support_topology_component_count",
    "target_projection_component_ids",
    "unmatched_support_component_ids",
    "target_projection_rows",
    "shared_terminal_endpoint_id",
    "shared_terminal_endpoint_degree",
    "raw_frcsd_terminal_degree",
    "constraint_induced_split",
    "cross_layer_status",
    "cross_layer_evidence",
    "input_geometry_status",
    "invalid_drivezone_feature_count",
    "raw_frcsd_verification_status",
    "direction_status",
    "step6_reason",
    "pre_business_cleanup_meaningful_component_count",
    "review_reason",
    "decision_source",
    "source_module",
    "source_case_id",
    "base_ids",
    "source_modules",
    "scenes",
    "conflict_group_id",
    "silent_fix",
)


def write_junction_outputs(
    *,
    run_root: Path,
    processing_crs: str,
    result: JunctionAuditResult,
) -> dict[str, Path]:
    paths = junction_output_paths(run_root)
    _write_csv(paths["junction_candidates_csv"], result.candidates, JUNCTION_FIELDS)
    _write_csv(paths["junction_confirmed_csv"], result.confirmed, JUNCTION_FIELDS)
    _write_csv(paths["junction_exclusions_csv"], result.exclusions, JUNCTION_FIELDS)
    _write_point_layer(
        paths["junction_candidates_gpkg"],
        "t12_frcsd_junction_quality_candidates",
        result.candidates,
        processing_crs,
    )
    _write_point_layer(
        paths["junction_confirmed_gpkg"],
        "t12_frcsd_confirmed_junction_quality_issues",
        result.confirmed,
        processing_crs,
    )
    _write_evidence(
        paths["junction_evidence_gpkg"],
        result.layers,
        processing_crs,
    )
    return paths


def junction_output_paths(root: Path) -> dict[str, Path]:
    return {
        "junction_candidates_csv": (
            root / "t12_frcsd_junction_quality_candidates.csv"
        ),
        "junction_candidates_gpkg": (
            root / "t12_frcsd_junction_quality_candidates.gpkg"
        ),
        "junction_confirmed_csv": (
            root / "t12_frcsd_confirmed_junction_quality_issues.csv"
        ),
        "junction_confirmed_gpkg": (
            root / "t12_frcsd_confirmed_junction_quality_issues.gpkg"
        ),
        "junction_exclusions_csv": (
            root / "t12_frcsd_junction_quality_exclusions.csv"
        ),
        "junction_evidence_gpkg": (
            root / "t12_frcsd_junction_carrier_evidence.gpkg"
        ),
    }


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    fieldnames = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: _scalar(row.get(field, ""))
                    for field in fieldnames
                }
            )


def _write_point_layer(
    path: Path,
    layer: str,
    rows: list[dict[str, Any]],
    crs: str,
) -> None:
    if path.exists():
        path.unlink()
    frame = _spatial_frame(
        [
            {
                **{
                    field: row.get(field, "")
                    for field in JUNCTION_FIELDS
                    if field
                    not in {
                        "target_projection_rows",
                        "cross_layer_evidence",
                    }
                },
                "geometry": row["geometry"],
            }
            for row in rows
        ],
        crs,
        empty_columns=(
            "candidate_id",
            "junction_id",
            "review_status",
            "issue_type",
        ),
    )
    frame.to_file(path, layer=layer, driver="GPKG")


def _write_evidence(
    path: Path,
    layers: dict[str, list[dict[str, Any]]],
    crs: str,
) -> None:
    if path.exists():
        path.unlink()
    definitions = (
        (
            "junction_candidates",
            layers.get("junction_candidates") or [],
            ("candidate_id", "junction_id", "review_status"),
        ),
        (
            "support_roads",
            layers.get("support_roads") or [],
            ("candidate_id", "junction_id", "road_id", "component_id"),
        ),
        (
            "target_projections",
            layers.get("target_projections") or [],
            ("candidate_id", "target_node_id", "nearest_road_id"),
        ),
        (
            "frcsd_endpoints",
            layers.get("frcsd_endpoints") or [],
            ("candidate_id", "junction_id", "node_id"),
        ),
        (
            "t07_conflict_links",
            layers.get("t07_conflict_links") or [],
            ("conflict_group_id", "detection_rule"),
        ),
    )
    for index, (layer_name, rows, empty_columns) in enumerate(definitions):
        frame = _spatial_frame(rows, crs, empty_columns=empty_columns)
        frame.to_file(
            path,
            layer=layer_name,
            driver="GPKG",
            mode="w" if index == 0 else "a",
        )


def _spatial_frame(
    rows: list[dict[str, Any]],
    crs: str,
    *,
    empty_columns: tuple[str, ...],
) -> gpd.GeoDataFrame:
    if not rows:
        payload = {column: pd.Series(dtype="str") for column in empty_columns}
        payload["geometry"] = gpd.GeoSeries([], crs=crs)
        return gpd.GeoDataFrame(payload, geometry="geometry", crs=crs)
    normalized = [
        {
            key: value if key == "geometry" else _scalar(value)
            for key, value in row.items()
            if not key.startswith("_")
        }
        for row in rows
    ]
    return gpd.GeoDataFrame(normalized, geometry="geometry", crs=crs)


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict, set)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=isinstance(value, dict),
        )
    return value
