from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, box
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import _polygon_components
from .case_models import T04CaseResult
from .polygon_assembly import T04Step6Result
from .provenance import provenance_doc
from .support_domain import T04Step5CaseResult


STEP7_BUSINESS_OBJECT = "divmerge_virtual_anchor_surface"
STEP7_SOURCE_MODULE = "T04"
STEP7_SCENE_FAMILY = "divmerge"
STEP7_ACCEPTED_LAYER_NAME = "divmerge_virtual_anchor_surface.gpkg"
STEP7_REJECTED_LAYER_NAME = "divmerge_virtual_anchor_surface_rejected.geojson"
STEP7_SUMMARY_CSV_NAME = "divmerge_virtual_anchor_surface_summary.csv"
STEP7_SUMMARY_JSON_NAME = "divmerge_virtual_anchor_surface_summary.json"
STEP7_AUDIT_LAYER_NAME = "divmerge_virtual_anchor_surface_audit.gpkg"
STEP7_CASE_FINAL_REVIEW_NAME = "final_review.png"
STEP7_REJECTED_INDEX_CSV_NAME = "step7_rejected_index.csv"
STEP7_REJECTED_INDEX_JSON_NAME = "step7_rejected_index.json"
STEP7_CONSISTENCY_REPORT_NAME = "step7_consistency_report.json"
RELATION_EVIDENCE_CSV_NAME = "t04_swsd_rcsd_relation_evidence.csv"
RELATION_EVIDENCE_JSON_NAME = "t04_swsd_rcsd_relation_evidence.json"
STEP7_ALLOWED_TOLERANCE_AREA_M2 = 1e-6
STEP7_REJECT_STUB_BUFFER_M = 2.5
STEP7_ALLOWED_FINAL_STATES = {"accepted", "rejected"}

STEP7_SURFACE_SCENARIO_AUDIT_FIELDS = (
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "reference_point_present",
    "surface_lateral_limit_m",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "post_cleanup_must_cover_ok",
    "post_cleanup_recheck_performed",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_rcsdroad_ids",
    "fallback_rcsdroad_localized",
    "fallback_domain_contained_by_allowed_growth",
    "fallback_overexpansion_detected",
    "fallback_overexpansion_area_m2",
    "divstrip_negative_mask_present",
    "divstrip_negative_overlap_area_m2",
    "forbidden_domain_kept",
    "unit_surface_count",
    "unit_surface_merge_performed",
    "merge_mode",
    "final_case_polygon_component_count",
    "single_connected_case_surface_ok",
    "barrier_separated_case_surface_ok",
    "surface_scenario_missing",
)

STEP7_SURFACE_SCENARIO_SUMMARY_FIELDNAMES = [
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "reference_point_present",
    "surface_lateral_limit_m",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "post_cleanup_must_cover_ok",
    "post_cleanup_recheck_performed",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_rcsdroad_localized",
    "fallback_overexpansion_detected",
    "divstrip_negative_mask_present",
    "forbidden_domain_kept",
    "unit_surface_count",
    "unit_surface_merge_performed",
    "merge_mode",
    "final_case_polygon_component_count",
    "single_connected_case_surface_ok",
    "barrier_separated_case_surface_ok",
]

STEP7_SUMMARY_FIELDNAMES = [
    "case_id",
    "anchor_id",
    "mainnodeid",
    "source_module",
    "scene_family",
    "scene_type",
    "junction_type",
    "kind_2",
    "patch_id",
    "patch_id_source",
    "final_state",
    "unit_count",
    "required_rcsd_node_count",
    "has_c_unit",
    "swsd_relation_type",
    "publish_target",
    "geometry_path",
    "audit_path",
    "review_png_path",
    *STEP7_SURFACE_SCENARIO_SUMMARY_FIELDNAMES,
]

STEP7_REJECTED_INDEX_FIELDNAMES = [
    "case_id",
    "mainnodeid",
    "scene_type",
    "final_state",
    "reject_reason",
    "reject_reason_detail",
    "publish_target",
    "reject_stub_path",
    "reject_index_path",
    "audit_path",
    "review_png_path",
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_overexpansion_detected",
]

RELATION_EVIDENCE_FIELDNAMES = [
    "target_id",
    "case_id",
    "junction_type",
    "scene_type",
    "final_state",
    "swsd_relation_type",
    "required_rcsd_node_ids",
    "semantic_required_rcsd_node_ids",
    "selected_rcsdnode_ids",
    "selected_rcsdroad_ids",
    "rcsd_profile",
    "has_c_unit",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "patch_id",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]



from .final_publish import (
    T04Step7CaseArtifact,
    _guard_doc_from_artifact,
    _primary_reject_reason,
    _resolved_review_png_path,
    _step7_guard_mapping_issues,
    collect_surface_scenario_summary_counts,
)

def write_step7_batch_outputs(
    *,
    run_root: Path,
    artifacts: list[T04Step7CaseArtifact],
    input_dataset_id: str | None = None,
    review_outputs_enabled: bool = True,
) -> dict[str, Any]:
    batch_provenance = provenance_doc(input_dataset_id=input_dataset_id)
    ordered_artifacts = sorted(artifacts, key=lambda item: sort_patch_key(item.case_id))
    accepted_features = [item.accepted_feature for item in ordered_artifacts if item.accepted_feature is not None]
    rejected_features = [item.rejected_feature for item in ordered_artifacts if item.rejected_feature is not None]
    audit_features = [item.audit_feature for item in ordered_artifacts if item.audit_feature is not None]
    summary_rows = []
    for item in ordered_artifacts:
        row = dict(item.summary_row)
        row["review_png_path"] = (
            _resolved_review_png_path(
                run_root,
                case_id=item.case_id,
                case_review_png_path=str(item.summary_row["review_png_path"]),
            )
            if review_outputs_enabled
            else ""
        )
        summary_rows.append(row)
    surface_scenario_summary_counts = collect_surface_scenario_summary_counts(ordered_artifacts)

    accepted_path = run_root / STEP7_ACCEPTED_LAYER_NAME
    rejected_path = run_root / STEP7_REJECTED_LAYER_NAME
    audit_path = run_root / STEP7_AUDIT_LAYER_NAME
    summary_csv_path = run_root / STEP7_SUMMARY_CSV_NAME
    summary_json_path = run_root / STEP7_SUMMARY_JSON_NAME
    rejected_index_csv_path = run_root / STEP7_REJECTED_INDEX_CSV_NAME
    rejected_index_json_path = run_root / STEP7_REJECTED_INDEX_JSON_NAME
    consistency_report_path = run_root / STEP7_CONSISTENCY_REPORT_NAME
    relation_evidence_csv_path = run_root / RELATION_EVIDENCE_CSV_NAME
    relation_evidence_json_path = run_root / RELATION_EVIDENCE_JSON_NAME
    relation_evidence_rows = [dict(item.relation_evidence_row) for item in ordered_artifacts]

    write_vector(accepted_path, accepted_features, crs_text="EPSG:3857")
    write_vector(rejected_path, rejected_features, crs_text="EPSG:3857")
    write_vector(audit_path, audit_features, crs_text="EPSG:3857")
    write_csv(summary_csv_path, summary_rows, STEP7_SUMMARY_FIELDNAMES)
    write_csv(relation_evidence_csv_path, relation_evidence_rows, RELATION_EVIDENCE_FIELDNAMES)
    write_json(
        relation_evidence_json_path,
        {
            **batch_provenance,
            "target_crs": "EPSG:3857",
            "row_count": len(relation_evidence_rows),
            "fieldnames": RELATION_EVIDENCE_FIELDNAMES,
            "rows": relation_evidence_rows,
        },
    )
    write_json(
        summary_json_path,
        {
            **batch_provenance,
            "business_object": STEP7_BUSINESS_OBJECT,
            "row_count": len(summary_rows),
            "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
            "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
            "relation_evidence": {
                "csv_path": str(relation_evidence_csv_path),
                "json_path": str(relation_evidence_json_path),
                "row_count": len(relation_evidence_rows),
                "target_crs": "EPSG:3857",
                "handoff_target": "T05 intersection_match_all.geojson source evidence",
            },
            **surface_scenario_summary_counts,
            "rows": summary_rows,
        },
    )
    rejected_index_rows = [
        {
            "case_id": item.case_id,
            "mainnodeid": item.summary_row["mainnodeid"],
            "scene_type": item.summary_row["scene_type"],
            "final_state": item.final_state,
            "reject_reason": _primary_reject_reason(item.reject_reasons),
            "reject_reason_detail": "|".join(item.reject_reasons),
            "publish_target": item.publish_target,
            "reject_stub_path": str(run_root / "cases" / item.case_id / "reject_stub.geojson"),
            "reject_index_path": str(run_root / "cases" / item.case_id / "reject_index.json"),
            "audit_path": item.summary_row["audit_path"],
            "review_png_path": (
                _resolved_review_png_path(
                    run_root,
                    case_id=item.case_id,
                    case_review_png_path=str(item.summary_row["review_png_path"]),
                )
                if review_outputs_enabled
                else ""
            ),
            "surface_scenario_type": item.summary_row.get("surface_scenario_type", "missing"),
            "section_reference_source": item.summary_row.get("section_reference_source", "missing"),
            "surface_generation_mode": item.summary_row.get("surface_generation_mode", "missing"),
            "no_surface_reference_guard": item.summary_row.get("no_surface_reference_guard", False),
            "final_polygon_suppressed_by_no_surface_reference": item.summary_row.get(
                "final_polygon_suppressed_by_no_surface_reference",
                False,
            ),
            "fallback_overexpansion_detected": item.summary_row.get("fallback_overexpansion_detected", False),
        }
        for item in ordered_artifacts
        if item.final_state == "rejected"
    ]
    write_csv(rejected_index_csv_path, rejected_index_rows, STEP7_REJECTED_INDEX_FIELDNAMES)
    write_json(
        rejected_index_json_path,
        {
            **batch_provenance,
            "row_count": len(rejected_index_rows),
            "rows": rejected_index_rows,
        },
    )
    missing_review_png_case_ids = (
        sorted(
            item.case_id
            for item in ordered_artifacts
            if not Path(
                _resolved_review_png_path(
                    run_root,
                    case_id=item.case_id,
                    case_review_png_path=str(item.summary_row["review_png_path"]),
                )
            ).is_file()
        )
        if review_outputs_enabled
        else []
    )
    missing_reject_stub_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "rejected"
        and item.reject_stub_feature is not None
        and not Path(run_root / "cases" / item.case_id / "reject_stub.geojson").is_file()
    )
    missing_reject_index_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "rejected"
        and not Path(run_root / "cases" / item.case_id / "reject_index.json").is_file()
    )
    missing_step7_status_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if not Path(run_root / "cases" / item.case_id / "step7_status.json").is_file()
    )
    missing_step7_audit_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if not Path(run_root / "cases" / item.case_id / "step7_audit.json").is_file()
    )
    unexpected_final_state_values = sorted(
        {
            str(item.final_state)
            for item in ordered_artifacts
            if str(item.final_state) not in STEP7_ALLOWED_FINAL_STATES
        }
    )
    accepted_layer_nonaccepted_count = sum(
        1
        for feature in accepted_features
        if str((feature.get("properties") or {}).get("final_state") or "") != "accepted"
    )
    rejected_layer_nonrejected_count = sum(
        1
        for feature in rejected_features
        if str((feature.get("properties") or {}).get("final_state") or "") != "rejected"
    )
    no_surface_reference_accepted_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "accepted"
        and (
            _guard_doc_from_artifact(item).get("surface_scenario_type") == "no_surface_reference"
            or bool(_guard_doc_from_artifact(item).get("no_surface_reference_guard"))
        )
    )
    step6_guard_field_missing_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if any(field not in _guard_doc_from_artifact(item) for field in STEP7_SURFACE_SCENARIO_AUDIT_FIELDS)
    )
    step6_guard_mapping_issues = _step7_guard_mapping_issues(ordered_artifacts)
    step7_guard_consistency_passed = not any(
        [
            unexpected_final_state_values,
            accepted_layer_nonaccepted_count,
            rejected_layer_nonrejected_count,
            no_surface_reference_accepted_case_ids,
            step6_guard_field_missing_case_ids,
            step6_guard_mapping_issues,
        ]
    )
    consistency_report = {
        **batch_provenance,
        "passed": not any(
            [
                missing_review_png_case_ids,
                missing_reject_stub_case_ids,
                missing_reject_index_case_ids,
                missing_step7_status_case_ids,
                missing_step7_audit_case_ids,
                unexpected_final_state_values,
                accepted_layer_nonaccepted_count,
                rejected_layer_nonrejected_count,
                no_surface_reference_accepted_case_ids,
                step6_guard_field_missing_case_ids,
                step6_guard_mapping_issues,
            ]
        ),
        "total_case_count": len(ordered_artifacts),
        "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
        "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
        **surface_scenario_summary_counts,
        "step7_allowed_final_states": sorted(STEP7_ALLOWED_FINAL_STATES),
        "unexpected_final_state_values": unexpected_final_state_values,
        "accepted_layer_only_accepted": accepted_layer_nonaccepted_count == 0,
        "accepted_layer_nonaccepted_count": accepted_layer_nonaccepted_count,
        "rejected_layer_only_rejected": rejected_layer_nonrejected_count == 0,
        "rejected_layer_nonrejected_count": rejected_layer_nonrejected_count,
        "no_surface_reference_accepted_case_ids": no_surface_reference_accepted_case_ids,
        "step6_guard_fields_present": not step6_guard_field_missing_case_ids,
        "step6_guard_field_missing_case_ids": step6_guard_field_missing_case_ids,
        "step6_guard_failure_reject_mapping_passed": not step6_guard_mapping_issues,
        "step6_guard_failure_reject_mapping_issues": step6_guard_mapping_issues,
        "nodes_writeback_rule": "accepted->yes; fallback_success->fail4_fallback; rejected/runtime_failed/formal_result_missing->fail4",
        "nodes_writeback_checked_in_step7_consistency_report": False,
        "nodes_writeback_check_reason": "nodes_publish owns downstream node materialization and preserves the existing value domain",
        "step7_guard_consistency_passed": step7_guard_consistency_passed,
        "review_outputs_enabled": bool(review_outputs_enabled),
        "accepted_layer_feature_count": len(accepted_features),
        "rejected_layer_feature_count": len(rejected_features),
        "audit_layer_feature_count": len(audit_features),
        "summary_row_count": len(summary_rows),
        "rejected_index_row_count": len(rejected_index_rows),
        "step4_review_flat_dir": str(run_root / "step4_review_flat"),
        "step4_review_flat_dir_exists": bool((run_root / "step4_review_flat").is_dir()),
        "review_png_present_count": (
            len(ordered_artifacts) - len(missing_review_png_case_ids)
            if review_outputs_enabled
            else 0
        ),
        "missing_review_png_case_ids": missing_review_png_case_ids,
        "missing_reject_stub_case_ids": missing_reject_stub_case_ids,
        "missing_reject_index_case_ids": missing_reject_index_case_ids,
        "missing_step7_status_case_ids": missing_step7_status_case_ids,
        "missing_step7_audit_case_ids": missing_step7_audit_case_ids,
        "accepted_layer_path": str(accepted_path),
        "rejected_layer_path": str(rejected_path),
        "audit_layer_path": str(audit_path),
        "summary_csv_path": str(summary_csv_path),
        "summary_json_path": str(summary_json_path),
        "rejected_index_csv_path": str(rejected_index_csv_path),
        "rejected_index_json_path": str(rejected_index_json_path),
        "relation_evidence_csv_path": str(relation_evidence_csv_path),
        "relation_evidence_json_path": str(relation_evidence_json_path),
        "relation_evidence_row_count": len(relation_evidence_rows),
    }
    write_json(consistency_report_path, consistency_report)
    return {
        "accepted_layer_path": str(accepted_path),
        "rejected_layer_path": str(rejected_path),
        "audit_layer_path": str(audit_path),
        "summary_csv_path": str(summary_csv_path),
        "summary_json_path": str(summary_json_path),
        "rejected_index_csv_path": str(rejected_index_csv_path),
        "rejected_index_json_path": str(rejected_index_json_path),
        "consistency_report_path": str(consistency_report_path),
        "relation_evidence_csv_path": str(relation_evidence_csv_path),
        "relation_evidence_json_path": str(relation_evidence_json_path),
        "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
        "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
        **surface_scenario_summary_counts,
    }
