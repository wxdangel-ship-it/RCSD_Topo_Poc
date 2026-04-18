from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import (
    build_step7_status_doc,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_status_doc,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import (
    Step67CaseResult,
    Step67Context,
    Step67ReviewIndexRow,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_render import render_step67_review_png


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

REVIEW_INDEX_FIELDNAMES = [
    "sequence_no",
    "case_id",
    "template_class",
    "association_class",
    "step45_state",
    "step6_state",
    "step7_state",
    "visual_class",
    "reason",
    "note",
    "image_name",
    "image_path",
]


def _geometry_feature(geometry, **properties):
    if geometry is None:
        return []
    return [{"properties": properties, "geometry": geometry}]


def _stable_sort_key(case_id: str) -> tuple[int, int | str]:
    return (0, int(case_id)) if case_id.isdigit() else (1, case_id)


def _sanitize_slug(value: str | None) -> str:
    text = (value or "result").strip().lower().replace(" ", "_")
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "result"


def _short_label(row: Step67ReviewIndexRow) -> str:
    if row.step7_state == "accepted" and row.visual_class == "V1 认可成功":
        return _sanitize_slug(row.template_class or "accepted")
    return _sanitize_slug(row.reason)


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
            visual_review_class=step7_result.visual_review_class,
            visual_audit_class=step7_result.visual_review_class,
            reason=step7_result.reason,
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
    accepted_dir = run_root / "step67_review_accepted"
    rejected_dir = run_root / "step67_review_rejected"
    v2_risk_dir = run_root / "step67_review_v2_risk"
    flat_dir = run_root / "step67_review_flat"
    for path in (accepted_dir, rejected_dir, v2_risk_dir, flat_dir):
        path.mkdir(parents=True, exist_ok=True)

    categorized_rows: list[Step67ReviewIndexRow] = []
    for index, row in enumerate(sorted(rows, key=lambda item: _stable_sort_key(item.case_id)), start=1):
        label = _short_label(row)
        image_name = f"{index:04d}_{row.case_id}_{row.step7_state}_{label}.png"
        if row.step7_state == "accepted":
            target_dir = accepted_dir
        else:
            target_dir = rejected_dir
        target_path = target_dir / image_name
        flat_path = flat_dir / image_name
        shutil.copy2(row.source_png_path, target_path)
        shutil.copy2(row.source_png_path, flat_path)
        if row.visual_class == "V2 业务正确但几何待修":
            shutil.copy2(row.source_png_path, v2_risk_dir / image_name)
        categorized_rows.append(
            replace(
                row,
                sequence_no=index,
                image_name=image_name,
                image_path=str(flat_path),
            )
        )
    return categorized_rows


def write_review_index(run_root: Path, rows: list[Step67ReviewIndexRow]) -> Path:
    csv_rows = [
        {
            "sequence_no": row.sequence_no,
            "case_id": row.case_id,
            "template_class": row.template_class,
            "association_class": row.association_class,
            "step45_state": row.step45_state,
            "step6_state": row.step6_state,
            "step7_state": row.step7_state,
            "visual_class": row.visual_class,
            "reason": row.reason,
            "note": row.note,
            "image_name": row.image_name,
            "image_path": row.image_path,
        }
        for row in rows
    ]
    output_path = run_root / "step67_review_index.csv"
    write_csv(output_path, csv_rows, REVIEW_INDEX_FIELDNAMES)
    return output_path


def _case_outputs_complete(case_dir: Path) -> bool:
    return case_dir.is_dir() and all((case_dir / rel_path).is_file() for rel_path in CASE_REQUIRED_OUTPUTS)


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
    cases_dir = run_root / "cases"
    flat_dir = run_root / "step67_review_flat"
    actual_case_ids = sorted(
        [entry.name for entry in cases_dir.iterdir() if entry.is_dir()] if cases_dir.is_dir() else [],
        key=_stable_sort_key,
    )
    flat_png_count = (
        len([entry for entry in flat_dir.iterdir() if entry.is_file() and entry.suffix.lower() == ".png"])
        if flat_dir.is_dir()
        else 0
    )
    expected_case_ids = sorted(list(expected_case_ids), key=_stable_sort_key)
    effective_case_ids = sorted(list(effective_case_ids), key=_stable_sort_key)
    raw_case_ids = sorted(list(raw_case_ids or []), key=_stable_sort_key)
    default_formal_case_ids = sorted(list(default_formal_case_ids or []), key=_stable_sort_key)
    default_full_batch_excluded_case_ids = sorted(list(default_full_batch_excluded_case_ids or []), key=_stable_sort_key)
    excluded_case_ids = sorted(list(excluded_case_ids or []), key=_stable_sort_key)
    missing_case_ids = [case_id for case_id in expected_case_ids if not _case_outputs_complete(cases_dir / case_id)]

    step6_established_count = sum(1 for row in rows if row.step6_state == "established")
    step6_not_established_count = sum(1 for row in rows if row.step6_state != "established")
    step7_accepted_count = sum(1 for row in rows if row.step7_state == "accepted")
    step7_rejected_count = sum(1 for row in rows if row.step7_state == "rejected")
    binary_state_sum = step7_accepted_count + step7_rejected_count
    visual_v1_count = sum(1 for row in rows if row.visual_class == "V1 认可成功")
    visual_v2_count = sum(1 for row in rows if row.visual_class == "V2 业务正确但几何待修")
    visual_v3_count = sum(1 for row in rows if row.visual_class == "V3 漏包 required")
    visual_v4_count = sum(1 for row in rows if row.visual_class == "V4 误包 foreign")
    visual_v5_count = sum(1 for row in rows if row.visual_class == "V5 明确失败")

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
        "step6_established_count": step6_established_count,
        "step6_not_established_count": step6_not_established_count,
        "step7_accepted_count": step7_accepted_count,
        "step7_rejected_count": step7_rejected_count,
        "binary_state_sum": binary_state_sum,
        "binary_state_sum_matches_total": binary_state_sum == len(expected_case_ids),
        "visual_v1_count": visual_v1_count,
        "visual_v2_count": visual_v2_count,
        "visual_v3_count": visual_v3_count,
        "visual_v4_count": visual_v4_count,
        "visual_v5_count": visual_v5_count,
        "default_full_batch_excluded_case_count": len(default_full_batch_excluded_case_ids),
        "default_full_batch_excluded_case_ids": default_full_batch_excluded_case_ids,
        "excluded_case_count": len(excluded_case_ids),
        "excluded_case_ids": excluded_case_ids,
        "applied_excluded_case_count": len(excluded_case_ids),
        "applied_excluded_case_ids": excluded_case_ids,
        "explicit_case_selection": explicit_case_selection,
        "missing_case_ids": missing_case_ids,
        "failed_case_ids": sorted(list(failed_case_ids), key=_stable_sort_key),
        "rerun_cleaned_before_write": rerun_cleaned_before_write,
        "run_root": str(run_root),
        "step67_review_flat_dir": str(flat_dir),
        "structure": {
            "cases_dir": str(cases_dir),
            "review_index_csv": str(run_root / "step67_review_index.csv"),
            "accepted_dir": str(run_root / "step67_review_accepted"),
            "rejected_dir": str(run_root / "step67_review_rejected"),
            "v2_risk_dir": str(run_root / "step67_review_v2_risk"),
        },
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path
