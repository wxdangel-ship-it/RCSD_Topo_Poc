from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    build_step7_status_doc,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_status_doc,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    Step67CaseResult,
    Step67Context,
    Step67ReviewIndexRow,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_render import render_step67_review_png
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.t03_batch_closeout import (
    materialize_t03_review_gallery,
    write_t03_review_index,
    write_t03_review_summary,
    write_t03_summary,
)


CASE_REQUIRED_OUTPUTS = (
    "step6_polygon_seed.gpkg",
    "step6_polygon_final.gpkg",
    "step6_constraint_foreign_mask.gpkg",
    "step67_final_polygon.gpkg",
    "step6_status.json",
    "step6_audit.json",
    "step7_status.json",
    "step7_audit.json",
    "step67_review.png",
)

def _geometry_feature(geometry, **properties):
    if geometry is None:
        return []
    return [{"properties": properties, "geometry": geometry}]


def write_case_outputs(
    *,
    run_root: Path,
    step67_context: Step67Context,
    case_result: Step67CaseResult,
    debug_render: bool = False,
) -> Step67ReviewIndexRow:
    case_id = step67_context.step45_context.step1_context.case_spec.case_id
    case_dir = run_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    step6_result = case_result.step6_result
    step7_result = case_result.step7_result

    write_vector(
        case_dir / "step6_polygon_seed.gpkg",
        _geometry_feature(
            step6_result.output_geometries.polygon_seed_geometry,
            case_id=case_id,
            template_class=case_result.template_class,
            layer="step6_polygon_seed",
            step6_state=step6_result.step6_state,
        ),
    )
    write_vector(
        case_dir / "step6_polygon_final.gpkg",
        _geometry_feature(
            step6_result.output_geometries.polygon_final_geometry,
            case_id=case_id,
            template_class=case_result.template_class,
            layer="step6_polygon_final",
            step6_state=step6_result.step6_state,
        ),
    )
    write_vector(
        case_dir / "step6_constraint_foreign_mask.gpkg",
        _geometry_feature(
            step6_result.output_geometries.foreign_mask_geometry,
            case_id=case_id,
            template_class=case_result.template_class,
            layer="step6_constraint_foreign_mask",
            step6_state=step6_result.step6_state,
        ),
    )
    write_vector(
        case_dir / "step67_final_polygon.gpkg",
        _geometry_feature(
            step6_result.output_geometries.polygon_final_geometry,
            case_id=case_id,
            template_class=case_result.template_class,
            layer="step67_final_polygon",
            step6_state=step6_result.step6_state,
            step7_state=step7_result.step7_state,
            reason=step7_result.reason,
            root_cause_layer=step7_result.root_cause_layer,
            root_cause_type=step7_result.root_cause_type,
        ),
    )
    write_json(case_dir / "step6_status.json", build_step6_status_doc(step67_context, step6_result))
    write_json(case_dir / "step6_audit.json", step6_result.audit_doc)
    write_json(case_dir / "step7_status.json", build_step7_status_doc(step67_context, step6_result, step7_result))
    write_json(case_dir / "step7_audit.json", step7_result.audit_doc)
    review_png_path = case_dir / "step67_review.png"
    render_step67_review_png(
        out_path=review_png_path,
        step67_context=step67_context,
        case_result=case_result,
        debug_render=debug_render,
    )
    return Step67ReviewIndexRow(
        case_id=case_id,
        template_class=case_result.template_class,
        association_class=case_result.association_class,
        step45_state=case_result.step45_state,
        step6_state=step6_result.step6_state,
        step7_state=step7_result.step7_state,
        visual_class=step7_result.visual_review_class,
        reason=step7_result.reason,
        note=step7_result.note or "",
        source_png_path=str(review_png_path),
    )


def materialize_review_gallery(run_root: Path, rows: list[Step67ReviewIndexRow]) -> list[Step67ReviewIndexRow]:
    return materialize_t03_review_gallery(run_root, rows)


def write_review_index(run_root: Path, rows: list[Step67ReviewIndexRow]) -> Path:
    return write_t03_review_index(run_root, rows)


def write_review_summary(run_root: Path, rows: list[Step67ReviewIndexRow]) -> Path:
    return write_t03_review_summary(run_root, rows)


def write_summary(
    run_root: Path,
    rows: list[Step67ReviewIndexRow],
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
    return write_t03_summary(
        run_root,
        rows,
        expected_case_ids=expected_case_ids,
        raw_case_count=raw_case_count,
        default_formal_case_count=default_formal_case_count,
        effective_case_ids=effective_case_ids,
        raw_case_ids=raw_case_ids,
        default_formal_case_ids=default_formal_case_ids,
        default_full_batch_excluded_case_ids=default_full_batch_excluded_case_ids,
        excluded_case_ids=excluded_case_ids,
        explicit_case_selection=explicit_case_selection,
        failed_case_ids=failed_case_ids,
        rerun_cleaned_before_write=rerun_cleaned_before_write,
    )
