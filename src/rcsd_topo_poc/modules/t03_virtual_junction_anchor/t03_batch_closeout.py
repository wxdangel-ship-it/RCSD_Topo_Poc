from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer, write_csv
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    derive_stage3_official_review_decision,
    resolve_stage3_output_kind,
    resolve_stage3_output_kind_source,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_facts import (
    acceptance_class_from_business_outcome,
    business_outcome_from_visual_review_class,
    success_flag_from_business_outcome,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import ReviewIndexRow
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_streamed_results import (
    T03StreamedCaseResult,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    coerce_int,
    feature_id,
    feature_mainnodeid,
    resolve_representative_feature,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationReviewIndexRow,
)


T03_REVIEW_ACCEPTED_DIRNAME = "t03_review_accepted"
T03_REVIEW_REJECTED_DIRNAME = "t03_review_rejected"
T03_REVIEW_V2_RISK_DIRNAME = "t03_review_v2_risk"
T03_REVIEW_FLAT_DIRNAME = "t03_review_flat"
T03_REVIEW_INDEX_FILENAME = "t03_review_index.csv"
T03_REVIEW_SUMMARY_FILENAME = "t03_review_summary.json"

REVIEW_INDEX_FIELDNAMES = [
    "sequence_no",
    "case_id",
    "template_class",
    "association_class",
    "association_state",
    "step6_state",
    "step7_state",
    "visual_class",
    "reason",
    "note",
    "image_name",
    "image_path",
]

REVIEW_SUMMARY_VISUAL_CLASSES = (
    "V1 认可成功",
    "V2 业务正确但几何待修",
    "V3 漏包 required",
    "V4 误包 foreign",
    "V5 明确失败",
)


def _stable_sort_key(case_id: str) -> tuple[int, int | str]:
    return (0, int(case_id)) if case_id.isdigit() else (1, case_id)


def _sanitize_slug(value: str | None) -> str:
    text = (value or "result").strip().lower().replace(" ", "_")
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "result"


def _short_label(row: FinalizationReviewIndexRow) -> str:
    if row.step7_state == "accepted" and row.visual_class == "V1 认可成功":
        return _sanitize_slug(row.template_class or "accepted")
    return _sanitize_slug(row.reason)


def materialize_t03_review_gallery(run_root: Path, rows: list[FinalizationReviewIndexRow]) -> list[FinalizationReviewIndexRow]:
    accepted_dir = run_root / T03_REVIEW_ACCEPTED_DIRNAME
    rejected_dir = run_root / T03_REVIEW_REJECTED_DIRNAME
    v2_risk_dir = run_root / T03_REVIEW_V2_RISK_DIRNAME
    flat_dir = run_root / T03_REVIEW_FLAT_DIRNAME
    for path in (accepted_dir, rejected_dir, v2_risk_dir, flat_dir):
        path.mkdir(parents=True, exist_ok=True)
        for existing_png in path.glob("*.png"):
            if existing_png.is_file():
                existing_png.unlink()

    categorized_rows: list[FinalizationReviewIndexRow] = []
    for index, row in enumerate(sorted(rows, key=lambda item: _stable_sort_key(item.case_id)), start=1):
        label = _short_label(row)
        image_name = f"{index:04d}_{row.case_id}_{row.step7_state}_{label}.png"
        source_path = Path(row.source_png_path) if row.source_png_path else None
        output_image_name = ""
        output_image_path = ""
        if source_path is not None and source_path.is_file():
            output_image_name = image_name
            target_dir = accepted_dir if row.step7_state == "accepted" else rejected_dir
            target_path = target_dir / image_name
            flat_path = flat_dir / image_name
            shutil.copy2(source_path, target_path)
            shutil.copy2(source_path, flat_path)
            output_image_path = str(flat_path)
            if row.visual_class == "V2 业务正确但几何待修":
                shutil.copy2(source_path, v2_risk_dir / image_name)
        categorized_rows.append(
            replace(
                row,
                sequence_no=index,
                image_name=output_image_name,
                image_path=output_image_path,
            )
        )
    return categorized_rows


def write_t03_review_index(run_root: Path, rows: list[FinalizationReviewIndexRow]) -> Path:
    csv_rows = [
        {
            "sequence_no": row.sequence_no,
            "case_id": row.case_id,
            "template_class": row.template_class,
            "association_class": row.association_class,
            "association_state": row.association_state,
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
    output_path = run_root / T03_REVIEW_INDEX_FILENAME
    write_csv(output_path, csv_rows, REVIEW_INDEX_FIELDNAMES)
    return output_path


def write_t03_review_summary(run_root: Path, rows: list[FinalizationReviewIndexRow]) -> Path:
    visual_counts = {
        visual_class: sum(1 for row in rows if row.visual_class == visual_class)
        for visual_class in REVIEW_SUMMARY_VISUAL_CLASSES
    }
    summary = {
        "total_case_count": len(rows),
        "accepted_case_count": sum(1 for row in rows if row.step7_state == "accepted"),
        "rejected_case_count": sum(1 for row in rows if row.step7_state == "rejected"),
        "visual_class_counts": visual_counts,
    }
    output_path = run_root / T03_REVIEW_SUMMARY_FILENAME
    write_json(output_path, summary)
    return output_path


def _case_outputs_complete(case_dir: Path) -> bool:
    required_outputs = (
        "step6_polygon_seed.gpkg",
        "step6_polygon_final.gpkg",
        "step6_constraint_foreign_mask.gpkg",
        "step7_final_polygon.gpkg",
        "step6_status.json",
        "step6_audit.json",
        "step7_status.json",
        "step7_audit.json",
    )
    return case_dir.is_dir() and all((case_dir / rel_path).is_file() for rel_path in required_outputs)


def write_t03_summary(
    run_root: Path,
    rows: list[FinalizationReviewIndexRow],
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
    flat_dir = run_root / T03_REVIEW_FLAT_DIRNAME
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
        "t03_review_flat_dir": str(flat_dir),
        "structure": {
            "cases_dir": str(cases_dir),
            "review_index_csv": str(run_root / T03_REVIEW_INDEX_FILENAME),
            "accepted_dir": str(run_root / T03_REVIEW_ACCEPTED_DIRNAME),
            "rejected_dir": str(run_root / T03_REVIEW_REJECTED_DIRNAME),
            "v2_risk_dir": str(run_root / T03_REVIEW_V2_RISK_DIRNAME),
        },
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path


def mirror_visual_checks(*, source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        same_dir = source_dir.resolve() == target_dir.resolve()
    except FileNotFoundError:
        same_dir = False
    if same_dir:
        return

    for existing_png in target_dir.glob("*.png"):
        if existing_png.is_file():
            existing_png.unlink()

    if not source_dir.is_dir():
        return

    for png_path in sorted(source_dir.glob("*.png"), key=lambda path: sort_patch_key(path.name)):
        shutil.copy2(png_path, target_dir / png_path.name)


def publish_incremental_visual_check(
    *,
    source_png_path: str,
    target_dir: Path,
    case_id: str,
    step7_state: str,
) -> None:
    source_path = Path(source_png_path)
    if not source_path.is_file():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{case_id}_{step7_state}_t03_review.png"
    shutil.copy2(source_path, target_path)
    latest_path = target_dir / "latest_t03_review.png"
    shutil.copy2(source_path, latest_path)


def load_step3_review_rows(*, run_root: Path, expected_case_ids: list[str]) -> list[ReviewIndexRow]:
    rows: list[ReviewIndexRow] = []
    flat_dir = run_root / "step3_review_flat"
    for case_id in sorted(expected_case_ids, key=sort_patch_key):
        case_dir = run_root / "cases" / case_id
        status_path = case_dir / "step3_status.json"
        review_png_path = case_dir / "step3_review.png"
        if not status_path.is_file():
            continue
        status_doc = json.loads(status_path.read_text(encoding="utf-8"))
        image_name = ""
        image_path = ""
        if review_png_path.is_file():
            image_name = f"{case_id}__{status_doc.get('step3_state')}.png"
            flat_image_path = flat_dir / image_name
            image_path = str(flat_image_path if flat_image_path.is_file() else review_png_path)
        rows.append(
            ReviewIndexRow(
                case_id=case_id,
                template_class=status_doc.get("template_class"),
                step3_state=str(status_doc.get("step3_state") or ""),
                reason=str(status_doc.get("reason") or ""),
                image_name=image_name,
                image_path=image_path,
                visual_review_class=status_doc.get("visual_review_class"),
                root_cause_layer=status_doc.get("root_cause_layer"),
                root_cause_type=status_doc.get("root_cause_type"),
            )
        )
    return rows


def build_finalization_review_rows(
    streamed_results: dict[str, T03StreamedCaseResult],
) -> list[FinalizationReviewIndexRow]:
    rows: list[FinalizationReviewIndexRow] = []
    for case_id in sorted(streamed_results, key=sort_patch_key):
        record = streamed_results[case_id]
        rows.append(
            FinalizationReviewIndexRow(
                case_id=record.case_id,
                template_class=record.template_class,
                association_class=record.association_class,
                association_state=record.association_state,
                step6_state=record.step6_state,
                step7_state=record.step7_state,
                visual_class=record.visual_class,
                reason=record.reason,
                note=record.note,
                source_png_path=record.source_png_path,
            )
        )
    return rows


def _build_virtual_intersection_polygon_feature(
    *,
    representative_feature: LayerFeature,
    streamed_result: T03StreamedCaseResult,
    polygon_geometry,
    case_dir: Path,
) -> dict[str, Any] | None:
    if polygon_geometry is None or polygon_geometry.is_empty:
        return None

    visual_review_class = streamed_result.visual_class
    business_outcome_class = business_outcome_from_visual_review_class(visual_review_class)
    if business_outcome_class == "failure":
        return None

    acceptance_class = acceptance_class_from_business_outcome(business_outcome_class)
    success = success_flag_from_business_outcome(business_outcome_class)
    representative_properties = dict(representative_feature.properties)
    representative_node_id = feature_id(representative_feature) or streamed_result.case_id
    mainnodeid = feature_mainnodeid(representative_feature) or representative_node_id
    kind_2 = coerce_int(representative_properties.get("kind_2"))
    grade_2 = coerce_int(representative_properties.get("grade_2"))
    official_review = derive_stage3_official_review_decision(
        success=success,
        business_outcome_class=business_outcome_class,
        acceptance_class=acceptance_class,
        acceptance_reason=streamed_result.reason,
        status=streamed_result.reason,
        root_cause_layer=streamed_result.root_cause_layer,
        representative_has_evd=representative_properties.get("has_evd"),
        representative_is_anchor=representative_properties.get("is_anchor"),
        representative_kind_2=kind_2,
    )
    properties = {
        "mainnodeid": mainnodeid,
        "kind": resolve_stage3_output_kind(
            representative_kind=representative_properties.get("kind"),
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "kind_source": resolve_stage3_output_kind_source(
            representative_kind=representative_properties.get("kind"),
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "status": streamed_result.reason,
        "representative_node_id": representative_node_id,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "success": success,
        "business_outcome_class": business_outcome_class,
        "acceptance_class": acceptance_class,
        "root_cause_layer": streamed_result.root_cause_layer,
        "root_cause_type": streamed_result.root_cause_type,
        "visual_review_class": visual_review_class,
        "official_review_eligible": official_review.official_review_eligible,
        "failure_bucket": official_review.failure_bucket,
        "source_case_dir": str(case_dir),
    }
    return {"properties": properties, "geometry": polygon_geometry}


def write_virtual_intersection_polygons(
    *,
    run_root: Path,
    shared_nodes: tuple[LayerFeature, ...],
    streamed_results: dict[str, T03StreamedCaseResult],
) -> Path:
    features: list[dict[str, Any]] = []
    for case_id in sorted(streamed_results.keys(), key=sort_patch_key):
        streamed_result = streamed_results[case_id]
        polygon_path = Path(streamed_result.final_polygon_path)
        polygon_features = read_vector_layer(polygon_path).features if polygon_path.is_file() else []
        polygon_geometry = polygon_features[0].geometry if polygon_features else None
        feature = _build_virtual_intersection_polygon_feature(
            representative_feature=resolve_representative_feature(shared_nodes, case_id),
            streamed_result=streamed_result,
            polygon_geometry=polygon_geometry,
            case_dir=run_root / "cases" / case_id,
        )
        if feature is not None:
            features.append(feature)
    output_path = run_root / "virtual_intersection_polygons.gpkg"
    write_vector(output_path, features, crs_text="EPSG:3857")
    return output_path


def write_updated_nodes_outputs(
    *,
    run_root: Path,
    shared_nodes: tuple[LayerFeature, ...],
    selected_case_ids: list[str],
    streamed_results: dict[str, T03StreamedCaseResult],
    failed_case_ids: list[str],
) -> dict[str, Path]:
    updates_by_node_id: dict[str, str] = {}
    audit_rows: list[dict[str, Any]] = []
    failed_case_id_set = {str(case_id) for case_id in failed_case_ids}

    for case_id in sorted(selected_case_ids, key=sort_patch_key):
        representative_feature = resolve_representative_feature(shared_nodes, case_id)
        representative_node_id = feature_id(representative_feature) or case_id
        previous_is_anchor = representative_feature.properties.get("is_anchor")
        if case_id in streamed_results:
            streamed_result = streamed_results[case_id]
            step7_state = streamed_result.step7_state
            reason = streamed_result.reason
            new_is_anchor = "yes" if step7_state == "accepted" else "fail3"
        elif case_id in failed_case_id_set:
            step7_state = "runtime_failed"
            reason = "runtime_failed"
            new_is_anchor = "fail3"
        else:
            continue
        updates_by_node_id[representative_node_id] = new_is_anchor
        audit_rows.append(
            {
                "case_id": case_id,
                "representative_node_id": representative_node_id,
                "previous_is_anchor": previous_is_anchor,
                "new_is_anchor": new_is_anchor,
                "step7_state": step7_state,
                "reason": reason,
            }
        )

    nodes_features = []
    for feature in shared_nodes:
        properties = dict(feature.properties)
        node_id = feature_id(feature)
        if node_id is not None and node_id in updates_by_node_id:
            properties["is_anchor"] = updates_by_node_id[node_id]
        nodes_features.append({"properties": properties, "geometry": feature.geometry})

    nodes_output_path = run_root / "nodes.gpkg"
    audit_csv_path = run_root / "nodes_anchor_update_audit.csv"
    audit_json_path = run_root / "nodes_anchor_update_audit.json"
    write_vector(nodes_output_path, nodes_features, crs_text="EPSG:3857")
    write_csv(
        audit_csv_path,
        audit_rows,
        [
            "case_id",
            "representative_node_id",
            "previous_is_anchor",
            "new_is_anchor",
            "step7_state",
            "reason",
        ],
    )
    write_json(
        audit_json_path,
        {
            "total_update_count": len(audit_rows),
            "updated_to_yes_count": sum(1 for row in audit_rows if row["new_is_anchor"] == "yes"),
            "updated_to_fail3_count": sum(1 for row in audit_rows if row["new_is_anchor"] == "fail3"),
            "rows": audit_rows,
        },
    )
    return {
        "nodes_path": nodes_output_path,
        "audit_csv_path": audit_csv_path,
        "audit_json_path": audit_json_path,
    }


__all__ = [
    "T03_REVIEW_ACCEPTED_DIRNAME",
    "T03_REVIEW_FLAT_DIRNAME",
    "T03_REVIEW_INDEX_FILENAME",
    "T03_REVIEW_REJECTED_DIRNAME",
    "T03_REVIEW_SUMMARY_FILENAME",
    "T03_REVIEW_V2_RISK_DIRNAME",
    "build_finalization_review_rows",
    "load_step3_review_rows",
    "materialize_t03_review_gallery",
    "mirror_visual_checks",
    "publish_incremental_visual_check",
    "write_t03_review_index",
    "write_t03_review_summary",
    "write_t03_summary",
    "write_updated_nodes_outputs",
    "write_virtual_intersection_polygons",
]
