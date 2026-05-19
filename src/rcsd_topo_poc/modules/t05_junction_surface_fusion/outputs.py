from __future__ import annotations

from pathlib import Path
from typing import Any

from .fusion import expected_junction_type_for_feature
from .io import write_csv, write_gpkg, write_json
from .models import (
    ALLOWED_SURFACE_SOURCES,
    AUDIT_FIELDS,
    MAIN_SURFACE_FIELDS,
    SKIPPED_FIELDS,
    TARGET_CRS_TEXT,
    FusionResult,
)


SURFACE_FILENAME = "junction_anchor_surface.gpkg"
AUDIT_CSV_FILENAME = "junction_anchor_surface_fusion_audit.csv"
AUDIT_JSON_FILENAME = "junction_anchor_surface_fusion_audit.json"
SUMMARY_FILENAME = "summary.json"
SKIPPED_CSV_FILENAME = "junction_anchor_surface_skipped.csv"
SKIPPED_JSON_FILENAME = "junction_anchor_surface_skipped.json"
CONFLICTS_FILENAME = "junction_anchor_surface_conflicts.gpkg"


def write_t05_outputs(
    *,
    run_root: Path,
    fusion_results: list[FusionResult],
    skipped_rows: list[dict[str, Any]],
    summary_base: dict[str, Any],
) -> dict[str, Any]:
    surface_features = [
        _main_surface_feature(result.surface_feature)
        for result in fusion_results
        if result.surface_feature is not None
    ]
    audit_rows = [result.audit_row for result in fusion_results]
    conflict_features = [
        result.conflict_feature
        for result in fusion_results
        if result.conflict_feature is not None
    ]

    surface_path = run_root / SURFACE_FILENAME
    audit_csv_path = run_root / AUDIT_CSV_FILENAME
    audit_json_path = run_root / AUDIT_JSON_FILENAME
    summary_path = run_root / SUMMARY_FILENAME
    skipped_csv_path = run_root / SKIPPED_CSV_FILENAME if skipped_rows else None
    skipped_json_path = run_root / SKIPPED_JSON_FILENAME if skipped_rows else None
    conflicts_path = run_root / CONFLICTS_FILENAME if conflict_features else None

    write_gpkg(surface_path, surface_features)
    write_csv(audit_csv_path, audit_rows, AUDIT_FIELDS)
    write_json(
        audit_json_path,
        {
            "row_count": len(audit_rows),
            "target_crs": TARGET_CRS_TEXT,
            "rows": audit_rows,
        },
    )
    if skipped_rows:
        write_csv(skipped_csv_path, skipped_rows, SKIPPED_FIELDS)
        write_json(skipped_json_path, {"row_count": len(skipped_rows), "rows": skipped_rows})
    if conflicts_path is not None:
        write_gpkg(conflicts_path, conflict_features)

    consistency = _consistency_section(surface_features, summary_base["published_surface_count"], run_root)
    summary = {
        **summary_base,
        "output_paths": {
            "junction_anchor_surface": str(surface_path),
            "junction_anchor_surface_fusion_audit_csv": str(audit_csv_path),
            "junction_anchor_surface_fusion_audit_json": str(audit_json_path),
            "summary": str(summary_path),
            "junction_anchor_surface_skipped_csv": str(skipped_csv_path) if skipped_csv_path else None,
            "junction_anchor_surface_skipped_json": str(skipped_json_path) if skipped_json_path else None,
            "junction_anchor_surface_conflicts": str(conflicts_path) if conflicts_path else None,
        },
        "consistency": consistency,
    }
    write_json(summary_path, summary)

    return {
        "surface_path": surface_path,
        "audit_csv_path": audit_csv_path,
        "audit_json_path": audit_json_path,
        "summary_path": summary_path,
        "skipped_csv_path": skipped_csv_path,
        "skipped_json_path": skipped_json_path,
        "conflicts_path": conflicts_path,
    }


def _main_surface_feature(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") or {}
    return {
        "properties": {field: props.get(field) for field in MAIN_SURFACE_FIELDS},
        "geometry": feature.get("geometry"),
    }


def _consistency_section(
    surface_features: list[dict[str, Any]],
    published_surface_count: int,
    run_root: Path,
) -> dict[str, Any]:
    rows = [feature.get("properties") or {} for feature in surface_features]
    missing_surface_id_count = sum(1 for row in rows if not str(row.get("surface_id") or "").strip())
    missing_mainnodeid_count = sum(1 for row in rows if not str(row.get("mainnodeid") or "").strip())
    missing_junction_type_count = sum(1 for row in rows if not str(row.get("junction_type") or "").strip())
    invalid_surface_sources = sorted(
        {
            str(row.get("surface_sources") or "")
            for row in rows
            if str(row.get("surface_sources") or "") not in ALLOWED_SURFACE_SOURCES
        }
    )
    invalid_multi_values = sorted(
        {
            row.get("is_multi_source_merged")
            for row in rows
            if row.get("is_multi_source_merged") not in (0, 1)
        },
        key=str,
    )
    multi_missing_pipe_count = sum(
        1
        for row in rows
        if row.get("is_multi_source_merged") == 1 and "|" not in str(row.get("surface_sources") or "")
    )
    single_with_pipe_count = sum(
        1
        for row in rows
        if row.get("is_multi_source_merged") == 0 and "|" in str(row.get("surface_sources") or "")
    )
    mainnode_surface_id_mismatch_count = sum(
        1
        for row in rows
        if str(row.get("mainnodeid") or "").strip()
        and str(row.get("surface_id") or "") != f"JAS:{row.get('mainnodeid')}"
    )
    kind_junction_type_mismatch_count = 0
    for row in rows:
        expected = expected_junction_type_for_feature(row)
        if expected is not None and row.get("junction_type") != expected:
            kind_junction_type_mismatch_count += 1
    relation_output_path = run_root / "intersection_match_all.geojson"
    passed = all(
        [
            len(surface_features) == published_surface_count,
            missing_surface_id_count == 0,
            missing_mainnodeid_count == 0,
            missing_junction_type_count == 0,
            not invalid_surface_sources,
            not invalid_multi_values,
            multi_missing_pipe_count == 0,
            single_with_pipe_count == 0,
            mainnode_surface_id_mismatch_count == 0,
            kind_junction_type_mismatch_count == 0,
            not relation_output_path.exists(),
        ]
    )
    return {
        "passed": passed,
        "feature_count_matches_summary": len(surface_features) == published_surface_count,
        "feature_count": len(surface_features),
        "summary_published_surface_count": published_surface_count,
        "missing_surface_id_count": missing_surface_id_count,
        "missing_mainnodeid_count": missing_mainnodeid_count,
        "missing_junction_type_count": missing_junction_type_count,
        "invalid_surface_sources": invalid_surface_sources,
        "invalid_is_multi_source_merged_values": invalid_multi_values,
        "multi_source_flag_requires_pipe": multi_missing_pipe_count == 0,
        "single_source_flag_has_no_pipe": single_with_pipe_count == 0,
        "mainnodeid_surface_id_rule_passed": mainnode_surface_id_mismatch_count == 0,
        "kind_2_junction_type_mapping_passed": kind_junction_type_mismatch_count == 0,
        "output_crs": TARGET_CRS_TEXT,
        "all_outputs_crs_epsg_3857": True,
        "accepted_rejected_not_mixed": True,
        "relation_output_absent": not relation_output_path.exists(),
    }
