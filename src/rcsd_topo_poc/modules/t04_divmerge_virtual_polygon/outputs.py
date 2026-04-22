from __future__ import annotations

import shutil
from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from .case_models import T04CaseResult, T04ReviewIndexRow
from .review_render import render_case_overview_png, render_event_unit_review_png
from .topology import build_step3_status_doc, build_unit_step3_status_doc


REVIEW_INDEX_FIELDNAMES = [
    "sequence_no",
    "case_id",
    "event_unit_id",
    "event_type",
    "review_state",
    "evidence_source",
    "position_source",
    "reverse_tip_used",
    "rcsd_consistency_result",
    "primary_candidate_id",
    "primary_candidate_layer",
    "ownership_signature",
    "upper_evidence_object_id",
    "local_region_id",
    "point_signature",
    "image_name",
    "image_path",
    "case_overview_path",
]


def _geometry_features_for_case(case_result: T04CaseResult):
    features: list[dict] = []
    for event_unit in case_result.event_units:
        for geometry_role, geometry in (
            ("pair_local_region_geometry", event_unit.pair_local_region_geometry),
            ("pair_local_structure_face_geometry", event_unit.pair_local_structure_face_geometry),
            ("pair_local_middle_geometry", event_unit.pair_local_middle_geometry),
            ("pair_local_throat_core_geometry", event_unit.pair_local_throat_core_geometry),
            ("selected_candidate_region_geometry", event_unit.selected_candidate_region_geometry),
            ("coarse_anchor_zone_geometry", event_unit.coarse_anchor_zone_geometry),
            ("selected_component_union_geometry", event_unit.selected_component_union_geometry),
            ("localized_evidence_core_geometry", event_unit.localized_evidence_core_geometry),
            ("fact_reference_point", event_unit.fact_reference_point),
            ("review_materialized_point", event_unit.review_materialized_point),
            ("positive_rcsd_geometry", event_unit.positive_rcsd_geometry),
        ):
            if geometry is None or geometry.is_empty:
                continue
            features.append(
                {
                    "properties": {
                        "case_id": case_result.case_spec.case_id,
                        "event_unit_id": event_unit.spec.event_unit_id,
                        "geometry_role": geometry_role,
                        "event_type": event_unit.spec.event_type,
                        "review_state": event_unit.review_state,
                        "candidate_id": str(event_unit.selected_candidate_summary.get("candidate_id") or ""),
                        "candidate_layer": str(event_unit.selected_candidate_summary.get("layer_label") or ""),
                    },
                    "geometry": geometry,
                }
            )
    return features


def write_case_outputs(
    *,
    run_root: Path,
    case_result: T04CaseResult,
) -> list[T04ReviewIndexRow]:
    case_dir = run_root / "cases" / case_result.case_spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    write_json(case_dir / "step1_status.json", case_result.admission.to_status_doc())
    write_json(case_dir / "case_meta.json", case_result.to_case_meta_doc())
    write_json(
        case_dir / "step3_status.json",
        build_step3_status_doc(
            admission=case_result.base_context.admission,
            topology_skeleton=case_result.base_context.topology_skeleton,
        ),
    )
    write_json(
        case_dir / "step3_audit.json",
        {
            "step2_local_context": case_result.base_context.local_context.to_audit_summary(),
            "step3_topology_skeleton": case_result.base_context.topology_skeleton.to_audit_summary(),
        },
    )
    write_json(
        case_dir / "step4_event_interpretation.json",
        {
            "case_id": case_result.case_spec.case_id,
            "case_review_state": case_result.case_review_state,
            "case_review_reasons": list(case_result.case_review_reasons),
            "event_units": [event_unit.to_summary_doc() for event_unit in case_result.event_units],
        },
    )
    write_json(
        case_dir / "step4_audit.json",
        {
            "case_id": case_result.case_spec.case_id,
            "step4_review_state": case_result.case_review_state,
            "step4_review_reasons": list(case_result.case_review_reasons),
            "event_units": [event_unit.to_summary_doc() for event_unit in case_result.event_units],
        },
    )
    write_vector(case_dir / "step4_event_evidence.gpkg", _geometry_features_for_case(case_result))
    overview_path = case_dir / "step4_review_overview.png"
    render_case_overview_png(overview_path, case_result)

    rows: list[T04ReviewIndexRow] = []
    for event_unit in case_result.event_units:
        event_unit_dir = case_dir / "event_units" / event_unit.spec.event_unit_id
        event_unit_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            event_unit_dir / "step3_status.json",
            build_unit_step3_status_doc(
                admission=event_unit.unit_context.admission,
                topology_skeleton=event_unit.unit_context.topology_skeleton,
                topology_scope=event_unit.unit_envelope.topology_scope,
                unit_population_node_ids=event_unit.unit_envelope.unit_population_node_ids,
                context_augmented_node_ids=event_unit.unit_envelope.context_augmented_node_ids,
                event_branch_ids=event_unit.unit_envelope.event_branch_ids,
                boundary_branch_ids=event_unit.unit_envelope.boundary_branch_ids,
                preferred_axis_branch_id=event_unit.unit_envelope.preferred_axis_branch_id,
                degraded_scope_reason=event_unit.unit_envelope.degraded_scope_reason,
                explicit_branch_ids=event_unit.unit_envelope.branch_ids,
                explicit_main_branch_ids=event_unit.unit_envelope.main_branch_ids,
                explicit_input_branch_ids=event_unit.unit_envelope.input_branch_ids,
                explicit_output_branch_ids=event_unit.unit_envelope.output_branch_ids,
                branch_road_memberships=event_unit.unit_envelope.branch_road_memberships,
                branch_bridge_node_ids=event_unit.unit_envelope.branch_bridge_node_ids,
            ),
        )
        write_json(
            event_unit_dir / "step4_candidates.json",
            {
                "case_id": case_result.case_spec.case_id,
                "event_unit_id": event_unit.spec.event_unit_id,
                "pair_local_summary": dict(event_unit.pair_local_summary),
                "selected_candidate": dict(event_unit.selected_candidate_summary),
                "alternative_candidates": [dict(item) for item in event_unit.alternative_candidate_summaries],
            },
        )
        png_path = event_unit_dir / "step4_review.png"
        render_event_unit_review_png(png_path, event_unit)
        event_unit.source_png_path = str(png_path)
        rows.append(
            T04ReviewIndexRow(
                case_id=case_result.case_spec.case_id,
                event_unit_id=event_unit.spec.event_unit_id,
                event_type=event_unit.spec.event_type,
                review_state=event_unit.review_state,
                evidence_source=event_unit.evidence_source,
                position_source=event_unit.position_source,
                reverse_tip_used=event_unit.reverse_tip_used,
                rcsd_consistency_result=event_unit.rcsd_consistency_result,
                primary_candidate_id=str(event_unit.selected_candidate_summary.get("candidate_id") or ""),
                primary_candidate_layer=str(event_unit.selected_candidate_summary.get("layer_label") or ""),
                ownership_signature=str(event_unit.selected_candidate_summary.get("ownership_signature") or ""),
                upper_evidence_object_id=str(event_unit.selected_candidate_summary.get("upper_evidence_object_id") or ""),
                local_region_id=str(event_unit.selected_candidate_summary.get("local_region_id") or ""),
                point_signature=str(event_unit.selected_candidate_summary.get("point_signature") or ""),
                case_overview_path=str(overview_path),
            )
        )
    return rows


def materialize_review_gallery(run_root: Path, rows: list[T04ReviewIndexRow]) -> list[T04ReviewIndexRow]:
    flat_dir = run_root / "step4_review_flat"
    flat_dir.mkdir(parents=True, exist_ok=True)
    for png_path in flat_dir.glob("*.png"):
        if png_path.is_file():
            png_path.unlink()

    ordered_rows = sorted(rows, key=lambda row: (sort_patch_key(row.case_id), row.event_unit_id))
    materialized_rows: list[T04ReviewIndexRow] = []
    for index, row in enumerate(ordered_rows, start=1):
        source_path = run_root / "cases" / row.case_id / "event_units" / row.event_unit_id / "step4_review.png"
        image_name = f"{index:04d}__{row.case_id}__{row.event_unit_id}.png"
        image_path = flat_dir / image_name
        if source_path.is_file():
            shutil.copy2(source_path, image_path)
        row.sequence_no = index
        row.image_name = image_name
        row.image_path = str(image_path)
        materialized_rows.append(row)
    return materialized_rows


def write_review_index(run_root: Path, rows: list[T04ReviewIndexRow]) -> Path:
    output_path = run_root / "step4_review_index.csv"
    write_csv(output_path, [row.to_csv_row() for row in rows], REVIEW_INDEX_FIELDNAMES)
    return output_path


def write_review_summary(run_root: Path, rows: list[T04ReviewIndexRow]) -> Path:
    summary = {
        "total_case_count": len({row.case_id for row in rows}),
        "total_event_unit_count": len(rows),
        "STEP4_OK": sum(1 for row in rows if row.review_state == "STEP4_OK"),
        "STEP4_REVIEW": sum(1 for row in rows if row.review_state == "STEP4_REVIEW"),
        "STEP4_FAIL": sum(1 for row in rows if row.review_state == "STEP4_FAIL"),
        "selected_layer_1_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 1"),
        "selected_layer_2_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 2"),
        "selected_layer_3_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 3"),
        "cases_with_multiple_event_units": sorted(
            case_id
            for case_id in {row.case_id for row in rows}
            if sum(1 for row in rows if row.case_id == case_id) > 1
        ),
    }
    output_path = run_root / "step4_review_summary.json"
    write_json(output_path, summary)
    return output_path


def write_summary(
    *,
    run_root: Path,
    rows: list[T04ReviewIndexRow],
    preflight: dict,
    failed_case_ids: list[str],
    rerun_cleaned_before_write: bool,
) -> Path:
    cases_dir = run_root / "cases"
    summary = {
        "total_case_count": len({row.case_id for row in rows}),
        "total_event_unit_count": len(rows),
        "selected_case_count": preflight.get("selected_case_count"),
        "selected_case_ids": preflight.get("selected_case_ids", []),
        "failed_case_ids": failed_case_ids,
        "rerun_cleaned_before_write": rerun_cleaned_before_write,
        "run_root": str(run_root),
        "cases_dir": str(cases_dir),
        "step4_review_index_csv": str(run_root / "step4_review_index.csv"),
        "step4_review_summary_json": str(run_root / "step4_review_summary.json"),
        "step4_review_flat_dir": str(run_root / "step4_review_flat"),
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path
