from __future__ import annotations

import shutil
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_vector
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import ReviewIndexRow, Step1Context, Step3CaseResult
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.render import render_step3_review_png
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


def _geometry_feature(geometry, **properties):
    if geometry is None:
        return []
    return [{"properties": properties, "geometry": geometry}]


def write_case_outputs(
    *,
    run_root: Path,
    context: Step1Context,
    case_result: Step3CaseResult,
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
    review_png_path = case_dir / "step3_review.png"
    render_step3_review_png(out_path=review_png_path, context=context, case_result=case_result)
    flat_dir = run_root / "step3_review_flat"
    flat_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{context.case_spec.case_id}__{case_result.step3_state}.png"
    flat_image_path = flat_dir / image_name
    shutil.copy2(review_png_path, flat_image_path)
    return ReviewIndexRow(
        case_id=context.case_spec.case_id,
        template_class=case_result.template_class,
        step3_state=case_result.step3_state,
        reason=case_result.reason,
        image_name=image_name,
        image_path=str(flat_image_path),
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


def write_summary(run_root: Path, rows: list[ReviewIndexRow]) -> Path:
    summary = {
        "total_case_count": len(rows),
        "step3_established_count": sum(1 for row in rows if row.step3_state == "established"),
        "step3_review_count": sum(1 for row in rows if row.step3_state == "review"),
        "step3_not_established_count": sum(1 for row in rows if row.step3_state == "not_established"),
        "run_root": str(run_root),
        "step3_review_flat_dir": str(run_root / "step3_review_flat"),
        "structure": {
            "cases_dir": str(run_root / "cases"),
            "review_index_csv": str(run_root / "step3_review_index.csv"),
        },
        "summary_semantics": {
            "primary_statistics": "established/review/not_established",
        },
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path
