from __future__ import annotations

import shutil
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_vector
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import ReviewIndexRow, Step1Context, Step3CaseResult
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_render import render_step3_review_png
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_status_doc


REVIEW_INDEX_FIELDNAMES = [
    "case_id",
    "template_class",
    "step3_state",
    "reason",
    "image_name",
    "image_path",
    "visual_review_class",
    "root_cause_layer",
    "root_cause_type",
]

CASE_REQUIRED_OUTPUTS = (
    "step3_allowed_space.gpkg",
    "step3_negative_mask_adjacent_junction.gpkg",
    "step3_negative_mask_foreign_objects.gpkg",
    "step3_negative_mask_foreign_mst.gpkg",
    "step3_status.json",
    "step3_audit.json",
)


def _geometry_feature(geometry, **properties):
    if geometry is None:
        return []
    return [{"properties": properties, "geometry": geometry}]


def write_case_outputs(
    *,
    run_root: Path,
    context: Step1Context,
    case_result: Step3CaseResult,
    render_review_png: bool = True,
) -> ReviewIndexRow:
    case_dir = run_root / "cases" / context.case_spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    write_vector(
        case_dir / "step3_allowed_space.gpkg",
        _geometry_feature(case_result.allowed_space_geometry, case_id=context.case_spec.case_id, layer="allowed_space"),
    )
    write_vector(
        case_dir / "step3_negative_mask_adjacent_junction.gpkg",
        _geometry_feature(case_result.negative_masks.adjacent_junction_geometry, case_id=context.case_spec.case_id, layer="adjacent_junction"),
    )
    write_vector(
        case_dir / "step3_negative_mask_foreign_objects.gpkg",
        _geometry_feature(case_result.negative_masks.foreign_objects_geometry, case_id=context.case_spec.case_id, layer="foreign_objects"),
    )
    write_vector(
        case_dir / "step3_negative_mask_foreign_mst.gpkg",
        _geometry_feature(case_result.negative_masks.foreign_mst_geometry, case_id=context.case_spec.case_id, layer="foreign_mst"),
    )
    write_json(case_dir / "step3_status.json", build_step3_status_doc(case_result))
    write_json(case_dir / "step3_audit.json", case_result.audit_doc)
    image_name = ""
    image_path = ""
    if render_review_png:
        review_png_path = case_dir / "step3_review.png"
        render_step3_review_png(out_path=review_png_path, context=context, case_result=case_result)
        flat_dir = run_root / "step3_review_flat"
        flat_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"{context.case_spec.case_id}__{case_result.step3_state}.png"
        flat_image_path = flat_dir / image_name
        shutil.copy2(review_png_path, flat_image_path)
        image_path = str(flat_image_path)
    return ReviewIndexRow(
        case_id=context.case_spec.case_id,
        template_class=case_result.template_class,
        step3_state=case_result.step3_state,
        reason=case_result.reason,
        image_name=image_name,
        image_path=image_path,
        visual_review_class=case_result.visual_review_class,
        root_cause_layer=case_result.root_cause_layer,
        root_cause_type=case_result.root_cause_type,
    )


def write_review_index(run_root: Path, rows: list[ReviewIndexRow]) -> Path:
    csv_rows = [
        {
            "case_id": row.case_id,
            "template_class": row.template_class,
            "step3_state": row.step3_state,
            "reason": row.reason,
            "image_name": row.image_name,
            "image_path": row.image_path,
            "visual_review_class": row.visual_review_class,
            "root_cause_layer": row.root_cause_layer,
            "root_cause_type": row.root_cause_type,
        }
        for row in rows
    ]
    output_path = run_root / "step3_review_index.csv"
    write_csv(output_path, csv_rows, REVIEW_INDEX_FIELDNAMES)
    return output_path


def _sorted_case_ids(case_ids: list[str]) -> list[str]:
    return sorted(case_ids, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _case_outputs_complete(case_dir: Path) -> bool:
    return case_dir.is_dir() and all((case_dir / rel_path).is_file() for rel_path in CASE_REQUIRED_OUTPUTS)


def write_summary(
    run_root: Path,
    rows: list[ReviewIndexRow],
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
    flat_dir = run_root / "step3_review_flat"
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
    step3_established_count = sum(1 for row in rows if row.step3_state == "established")
    step3_review_count = sum(1 for row in rows if row.step3_state == "review")
    step3_not_established_count = sum(1 for row in rows if row.step3_state == "not_established")
    tri_state_sum = step3_established_count + step3_review_count + step3_not_established_count
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
        "step3_established_count": step3_established_count,
        "step3_review_count": step3_review_count,
        "step3_not_established_count": step3_not_established_count,
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
        "step3_review_flat_dir": str(flat_dir),
        "structure": {
            "cases_dir": str(cases_dir),
            "review_index_csv": str(run_root / "step3_review_index.csv"),
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
