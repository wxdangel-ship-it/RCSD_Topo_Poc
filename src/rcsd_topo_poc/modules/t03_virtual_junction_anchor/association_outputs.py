from __future__ import annotations

import shutil
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_vector
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import (
    AssociationCaseResult,
    AssociationContext,
    AssociationReviewIndexRow,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_association_status_doc
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_render import render_association_review_png


REVIEW_INDEX_FIELDNAMES = [
    "case_id",
    "template_class",
    "association_class",
    "association_state",
    "reason",
    "image_name",
    "image_path",
    "visual_review_class",
    "root_cause_layer",
    "root_cause_type",
]

CASE_REQUIRED_OUTPUTS = (
    "association_required_rcsdnode.gpkg",
    "association_required_rcsdroad.gpkg",
    "association_support_rcsdnode.gpkg",
    "association_support_rcsdroad.gpkg",
    "association_excluded_rcsdnode.gpkg",
    "association_excluded_rcsdroad.gpkg",
    "association_required_hook_zone.gpkg",
    "association_foreign_swsd_context.gpkg",
    "association_foreign_rcsd_context.gpkg",
    "association_status.json",
    "association_audit.json",
    "association_review.png",
)


def _geometry_feature(geometry, **properties):
    if geometry is None:
        return []
    return [{"properties": properties, "geometry": geometry}]


def write_case_outputs(
    *,
    run_root: Path,
    context: AssociationContext,
    case_result: AssociationCaseResult,
    debug_render: bool = False,
) -> AssociationReviewIndexRow:
    case_dir = run_root / "cases" / context.step1_context.case_spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    outputs = case_result.output_geometries
    write_vector(
        case_dir / "association_required_rcsdnode.gpkg",
        _geometry_feature(outputs.required_rcsdnode_geometry, case_id=context.step1_context.case_spec.case_id, layer="required_rcsdnode"),
    )
    write_vector(
        case_dir / "association_required_rcsdroad.gpkg",
        _geometry_feature(outputs.required_rcsdroad_geometry, case_id=context.step1_context.case_spec.case_id, layer="required_rcsdroad"),
    )
    write_vector(
        case_dir / "association_support_rcsdnode.gpkg",
        _geometry_feature(outputs.support_rcsdnode_geometry, case_id=context.step1_context.case_spec.case_id, layer="support_rcsdnode"),
    )
    write_vector(
        case_dir / "association_support_rcsdroad.gpkg",
        _geometry_feature(outputs.support_rcsdroad_geometry, case_id=context.step1_context.case_spec.case_id, layer="support_rcsdroad"),
    )
    write_vector(
        case_dir / "association_excluded_rcsdnode.gpkg",
        _geometry_feature(outputs.excluded_rcsdnode_geometry, case_id=context.step1_context.case_spec.case_id, layer="excluded_rcsdnode"),
    )
    write_vector(
        case_dir / "association_excluded_rcsdroad.gpkg",
        _geometry_feature(outputs.excluded_rcsdroad_geometry, case_id=context.step1_context.case_spec.case_id, layer="excluded_rcsdroad"),
    )
    write_vector(
        case_dir / "association_required_hook_zone.gpkg",
        _geometry_feature(outputs.required_hook_zone_geometry, case_id=context.step1_context.case_spec.case_id, layer="required_hook_zone"),
    )
    write_vector(
        case_dir / "association_foreign_swsd_context.gpkg",
        _geometry_feature(outputs.foreign_swsd_context_geometry, case_id=context.step1_context.case_spec.case_id, layer="foreign_swsd_context"),
    )
    write_vector(
        case_dir / "association_foreign_rcsd_context.gpkg",
        _geometry_feature(outputs.foreign_rcsd_context_geometry, case_id=context.step1_context.case_spec.case_id, layer="foreign_rcsd_context"),
    )
    write_json(case_dir / "association_status.json", build_association_status_doc(case_result))
    write_json(case_dir / "association_audit.json", case_result.audit_doc)
    review_png_path = case_dir / "association_review.png"
    render_association_review_png(out_path=review_png_path, context=context, case_result=case_result, debug_render=debug_render)
    flat_dir = run_root / "association_review_flat"
    flat_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{context.step1_context.case_spec.case_id}__{case_result.association_state}.png"
    flat_image_path = flat_dir / image_name
    shutil.copy2(review_png_path, flat_image_path)
    return AssociationReviewIndexRow(
        case_id=context.step1_context.case_spec.case_id,
        template_class=case_result.template_class,
        association_class=case_result.association_class,
        association_state=case_result.association_state,
        reason=case_result.reason,
        image_name=image_name,
        image_path=str(flat_image_path),
        visual_review_class=case_result.visual_review_class,
        root_cause_layer=case_result.root_cause_layer,
        root_cause_type=case_result.root_cause_type,
    )


def write_review_index(run_root: Path, rows: list[AssociationReviewIndexRow]) -> Path:
    csv_rows = [
        {
            "case_id": row.case_id,
            "template_class": row.template_class,
            "association_class": row.association_class,
            "association_state": row.association_state,
            "reason": row.reason,
            "image_name": row.image_name,
            "image_path": row.image_path,
            "visual_review_class": row.visual_review_class,
            "root_cause_layer": row.root_cause_layer,
            "root_cause_type": row.root_cause_type,
        }
        for row in rows
    ]
    output_path = run_root / "association_review_index.csv"
    write_csv(output_path, csv_rows, REVIEW_INDEX_FIELDNAMES)
    return output_path


def _sorted_case_ids(case_ids: list[str]) -> list[str]:
    return sorted(case_ids, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _case_outputs_complete(case_dir: Path) -> bool:
    return case_dir.is_dir() and all((case_dir / rel_path).is_file() for rel_path in CASE_REQUIRED_OUTPUTS)


def write_summary(
    run_root: Path,
    rows: list[AssociationReviewIndexRow],
    *,
    expected_case_ids: list[str],
    raw_case_count: int,
    default_formal_case_count: int,
    effective_case_ids: list[str],
    raw_case_ids: list[str] | None = None,
    default_formal_case_ids: list[str] | None = None,
    default_full_batch_excluded_case_ids: list[str] | None = None,
    excluded_case_ids: list[str] | None = None,
    explicit_case_selection: bool = False,
    failed_case_ids: list[str],
    rerun_cleaned_before_write: bool,
) -> Path:
    cases_dir = run_root / "cases"
    flat_dir = run_root / "association_review_flat"
    actual_case_ids = [entry.name for entry in cases_dir.iterdir() if entry.is_dir()] if cases_dir.is_dir() else []
    actual_case_ids = _sorted_case_ids(actual_case_ids)
    flat_png_count = (
        len([entry for entry in flat_dir.iterdir() if entry.is_file() and entry.suffix.lower() == ".png"])
        if flat_dir.is_dir()
        else 0
    )
    raw_case_ids = _sorted_case_ids(list(raw_case_ids or []))
    default_formal_case_ids = _sorted_case_ids(list(default_formal_case_ids or []))
    default_full_batch_excluded_case_ids = _sorted_case_ids(list(default_full_batch_excluded_case_ids or []))
    expected_case_ids = _sorted_case_ids(list(expected_case_ids))
    effective_case_ids = _sorted_case_ids(list(effective_case_ids))
    excluded_case_ids = _sorted_case_ids(list(excluded_case_ids or []))
    missing_case_ids = [
        case_id
        for case_id in expected_case_ids
        if not _case_outputs_complete(cases_dir / case_id)
    ]
    association_established_count = sum(1 for row in rows if row.association_state == "established")
    association_review_count = sum(1 for row in rows if row.association_state == "review")
    association_not_established_count = sum(1 for row in rows if row.association_state == "not_established")
    tri_state_sum = association_established_count + association_review_count + association_not_established_count
    summary = {
        "total_case_count": len(rows),
        "raw_case_count": raw_case_count,
        "raw_case_ids": raw_case_ids,
        "default_formal_case_count": default_formal_case_count,
        "default_formal_case_ids": default_formal_case_ids,
        "formal_full_batch_case_count": default_formal_case_count,
        "formal_full_batch_case_ids": default_formal_case_ids,
        "expected_case_count": len(expected_case_ids),
        "effective_case_count": len(effective_case_ids),
        "effective_case_ids": effective_case_ids,
        "actual_case_dir_count": len(actual_case_ids),
        "flat_png_count": flat_png_count,
        "association_established_count": association_established_count,
        "association_review_count": association_review_count,
        "association_not_established_count": association_not_established_count,
        "tri_state_sum": tri_state_sum,
        "tri_state_sum_matches_total": tri_state_sum == len(expected_case_ids),
        "default_full_batch_excluded_case_count": len(default_full_batch_excluded_case_ids),
        "default_full_batch_excluded_case_ids": default_full_batch_excluded_case_ids,
        "excluded_case_count": len(excluded_case_ids),
        "excluded_case_ids": excluded_case_ids,
        "applied_excluded_case_count": len(excluded_case_ids),
        "applied_excluded_case_ids": excluded_case_ids,
        "explicit_case_selection": explicit_case_selection,
        "missing_case_ids": missing_case_ids,
        "failed_case_ids": _sorted_case_ids(list(failed_case_ids)),
        "rerun_cleaned_before_write": rerun_cleaned_before_write,
        "run_root": str(run_root),
        "association_review_flat_dir": str(flat_dir),
        "structure": {
            "cases_dir": str(cases_dir),
            "review_index_csv": str(run_root / "association_review_index.csv"),
        },
        "summary_semantics": {
            "primary_statistics": "established/review/not_established",
            "acceptance_case_sets": {
                "raw": "all discovered case-package directories under case_root",
                "formal_full_batch": "raw cases minus default full-batch excluded cases",
                "effective": "cases actually executed in this run after explicit selection and max_cases",
            },
        },
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path
