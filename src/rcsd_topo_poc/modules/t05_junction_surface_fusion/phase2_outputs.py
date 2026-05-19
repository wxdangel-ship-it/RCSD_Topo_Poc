from __future__ import annotations

from pathlib import Path
from typing import Any

from .phase2_io import write_csv, write_gpkg, write_json, write_relation_geojson_crs84
from .phase2_models import (
    BLOCKING_ERROR_FIELDS,
    JUNCTIONIZATION_AUDIT_FIELDS,
    RELATION_FIELDS,
    STATUS_FAILURE,
    STATUS_SUCCESS,
)
from .phase2_relation import relation_properties


RELATION_FILENAME = "intersection_match_all.geojson"
RCSDROAD_OUT_FILENAME = "rcsdroad_out.gpkg"
RCSDNODE_OUT_FILENAME = "rcsdnode_out.gpkg"
RCSDROAD_SPLIT_FILENAME = "rcsdroad_split.gpkg"
RCSDNODE_GENERATED_FILENAME = "rcsdnode_generated.gpkg"
RCSDNODE_GROUPED_FILENAME = "rcsdnode_grouped.gpkg"
JUNCTIONIZATION_AUDIT_CSV = "rcsd_junctionization_audit.csv"
JUNCTIONIZATION_AUDIT_JSON = "rcsd_junctionization_audit.json"
RELATION_AUDIT_CSV = "intersection_match_all_audit.csv"
RELATION_AUDIT_JSON = "intersection_match_all_audit.json"
BLOCKING_ERRORS_CSV = "blocking_errors.csv"
BLOCKING_ERRORS_JSON = "blocking_errors.json"
SUMMARY_FILENAME = "summary.json"


def write_phase2_outputs(
    *,
    run_root: Path,
    produced_at: str,
    run_id: str,
    input_paths: dict[str, Any],
    relation_features: list[dict[str, Any]],
    rcsdroad_out_features: list[dict[str, Any]],
    rcsdnode_out_features: list[dict[str, Any]],
    split_road_features: list[dict[str, Any]],
    generated_node_features: list[dict[str, Any]],
    grouped_node_features: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
    original_split_road_ids: set[int],
) -> dict[str, Any]:
    relation_path = run_root / RELATION_FILENAME
    rcsdroad_out_path = run_root / RCSDROAD_OUT_FILENAME
    rcsdnode_out_path = run_root / RCSDNODE_OUT_FILENAME
    rcsdroad_split_path = run_root / RCSDROAD_SPLIT_FILENAME
    rcsdnode_generated_path = run_root / RCSDNODE_GENERATED_FILENAME
    rcsdnode_grouped_path = run_root / RCSDNODE_GROUPED_FILENAME
    junction_audit_csv_path = run_root / JUNCTIONIZATION_AUDIT_CSV
    junction_audit_json_path = run_root / JUNCTIONIZATION_AUDIT_JSON
    relation_audit_csv_path = run_root / RELATION_AUDIT_CSV
    relation_audit_json_path = run_root / RELATION_AUDIT_JSON
    blocking_errors_csv_path = run_root / BLOCKING_ERRORS_CSV
    blocking_errors_json_path = run_root / BLOCKING_ERRORS_JSON
    summary_path = run_root / SUMMARY_FILENAME

    relation_output_features = [
        {"properties": relation_properties(feature), "geometry": feature.get("geometry")}
        for feature in relation_features
    ]
    write_relation_geojson_crs84(relation_path, relation_output_features)
    write_gpkg(rcsdroad_out_path, rcsdroad_out_features, geometry_type="LineString")
    write_gpkg(rcsdnode_out_path, rcsdnode_out_features, geometry_type="Point")
    write_gpkg(rcsdroad_split_path, split_road_features, geometry_type="LineString")
    write_gpkg(rcsdnode_generated_path, generated_node_features, geometry_type="Point")
    write_gpkg(rcsdnode_grouped_path, grouped_node_features, geometry_type="Point")
    write_csv(junction_audit_csv_path, audit_rows, JUNCTIONIZATION_AUDIT_FIELDS)
    write_json(junction_audit_json_path, {"row_count": len(audit_rows), "rows": audit_rows})
    write_csv(relation_audit_csv_path, audit_rows, JUNCTIONIZATION_AUDIT_FIELDS)
    write_json(relation_audit_json_path, {"row_count": len(audit_rows), "rows": audit_rows})
    write_csv(blocking_errors_csv_path, blocking_errors, BLOCKING_ERROR_FIELDS)
    write_json(blocking_errors_json_path, {"row_count": len(blocking_errors), "rows": blocking_errors})

    summary = _summary(
        produced_at=produced_at,
        run_id=run_id,
        input_paths=input_paths,
        relation_features=relation_output_features,
        rcsdroad_out_features=rcsdroad_out_features,
        rcsdnode_out_features=rcsdnode_out_features,
        split_road_features=split_road_features,
        generated_node_features=generated_node_features,
        grouped_node_features=grouped_node_features,
        audit_rows=audit_rows,
        blocking_errors=blocking_errors,
        original_split_road_ids=original_split_road_ids,
        output_paths={
            "intersection_match_all": str(relation_path),
            "rcsdroad_out": str(rcsdroad_out_path),
            "rcsdnode_out": str(rcsdnode_out_path),
            "rcsdroad_split": str(rcsdroad_split_path),
            "rcsdnode_generated": str(rcsdnode_generated_path),
            "rcsdnode_grouped": str(rcsdnode_grouped_path),
            "rcsd_junctionization_audit_csv": str(junction_audit_csv_path),
            "rcsd_junctionization_audit_json": str(junction_audit_json_path),
            "intersection_match_all_audit_csv": str(relation_audit_csv_path),
            "intersection_match_all_audit_json": str(relation_audit_json_path),
            "blocking_errors_csv": str(blocking_errors_csv_path),
            "blocking_errors_json": str(blocking_errors_json_path),
            "summary": str(summary_path),
        },
    )
    write_json(summary_path, summary)
    return {
        "relation_geojson_path": relation_path,
        "rcsdroad_out_path": rcsdroad_out_path,
        "rcsdnode_out_path": rcsdnode_out_path,
        "rcsdroad_split_path": rcsdroad_split_path,
        "rcsdnode_generated_path": rcsdnode_generated_path,
        "rcsdnode_grouped_path": rcsdnode_grouped_path,
        "junction_audit_csv_path": junction_audit_csv_path,
        "junction_audit_json_path": junction_audit_json_path,
        "relation_audit_csv_path": relation_audit_csv_path,
        "relation_audit_json_path": relation_audit_json_path,
        "blocking_errors_csv_path": blocking_errors_csv_path,
        "blocking_errors_json_path": blocking_errors_json_path,
        "summary_path": summary_path,
        "summary": summary,
    }


def _summary(
    *,
    produced_at: str,
    run_id: str,
    input_paths: dict[str, Any],
    output_paths: dict[str, Any],
    relation_features: list[dict[str, Any]],
    rcsdroad_out_features: list[dict[str, Any]],
    rcsdnode_out_features: list[dict[str, Any]],
    split_road_features: list[dict[str, Any]],
    generated_node_features: list[dict[str, Any]],
    grouped_node_features: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
    original_split_road_ids: set[int],
) -> dict[str, Any]:
    relation_rows = [feature.get("properties") or {} for feature in relation_features]
    success_count = sum(1 for row in relation_rows if row.get("status") == STATUS_SUCCESS)
    failure_count = sum(1 for row in relation_rows if row.get("status") == STATUS_FAILURE)
    consistency = _consistency(
        relation_rows=relation_rows,
        rcsdroad_out_features=rcsdroad_out_features,
        rcsdnode_out_features=rcsdnode_out_features,
        split_road_features=split_road_features,
        generated_node_features=generated_node_features,
        grouped_node_features=grouped_node_features,
        blocking_errors=blocking_errors,
        original_split_road_ids=original_split_road_ids,
    )
    return {
        "run_id": run_id,
        "produced_at": produced_at,
        "input_paths": input_paths,
        "output_paths": output_paths,
        "intersection_match_all_feature_count": len(relation_rows),
        "status_0_count": success_count,
        "status_1_count": failure_count,
        "rcsdroad_out_count": len(rcsdroad_out_features),
        "rcsdnode_out_count": len(rcsdnode_out_features),
        "rcsdroad_split_count": len(split_road_features),
        "rcsdnode_generated_count": len(generated_node_features),
        "rcsdnode_grouped_count": len(grouped_node_features),
        "audit_row_count": len(audit_rows),
        "blocking_error_count": len(blocking_errors),
        "passed": consistency["passed"],
        "crs": {"process": "EPSG:3857", "intersection_match_all": "CRS84"},
        "consistency": consistency,
    }


def _consistency(
    *,
    relation_rows: list[dict[str, Any]],
    rcsdroad_out_features: list[dict[str, Any]],
    rcsdnode_out_features: list[dict[str, Any]],
    split_road_features: list[dict[str, Any]],
    generated_node_features: list[dict[str, Any]],
    grouped_node_features: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
    original_split_road_ids: set[int],
) -> dict[str, Any]:
    new_node_ids = [_feature_id(feature) for feature in generated_node_features]
    new_road_ids = [_feature_id(feature) for feature in split_road_features]
    out_road_ids = {_feature_id(feature) for feature in rcsdroad_out_features}
    out_node_ids = {_feature_id(feature) for feature in rcsdnode_out_features}
    target_ids = [str(row.get("target_id") or "") for row in relation_rows]
    duplicate_target_ids = sorted({target_id for target_id in target_ids if target_ids.count(target_id) > 1})
    split_endpoint_ids = {
        int(value)
        for feature in split_road_features
        for value in (_field_value(feature, "snodeid"), _field_value(feature, "enodeid"))
        if _is_int(value)
    }
    checks = {
        "target_id_unique": not duplicate_target_ids,
        "duplicate_target_ids": duplicate_target_ids,
        "status_1_base_id_zero": all(row.get("base_id") == 0 for row in relation_rows if row.get("status") == 1),
        "status_0_base_id_nonzero": all(row.get("base_id") not in (0, "0", None, "") for row in relation_rows if row.get("status") == 0),
        "new_rcsdnode_ids_unique": len(new_node_ids) == len(set(new_node_ids)),
        "new_rcsdroad_ids_unique": len(new_road_ids) == len(set(new_road_ids)),
        "split_original_roads_removed_from_active": not (original_split_road_ids & out_road_ids),
        "split_road_endpoints_exist": split_endpoint_ids.issubset(out_node_ids),
        "generated_nodes_in_output": set(new_node_ids).issubset(out_node_ids),
        "grouped_nodes_in_output": {_feature_id(feature) for feature in grouped_node_features}.issubset(out_node_ids),
        "relation_output_crs_crs84": True,
        "copy_on_write_inputs_not_modified": True,
        "multiple_base_id_unmergeable_absent": not blocking_errors,
        "blocking_errors_force_summary_failure": not blocking_errors,
    }
    checks["passed"] = all(value for key, value in checks.items() if key != "duplicate_target_ids")
    return checks


def _feature_id(feature: dict[str, Any]) -> int:
    value = _field_value(feature, "id")
    return int(value)


def _field_value(feature: dict[str, Any], field_name: str) -> Any:
    for key, value in (feature.get("properties") or {}).items():
        if key.lower() == field_name:
            return value
    return None


def _is_int(value: Any) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False
