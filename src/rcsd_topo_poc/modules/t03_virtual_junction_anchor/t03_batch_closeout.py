from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.gpkg_update import (
    copy_gpkg_and_update_field_by_id,
    update_gpkg_field_by_id,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer, write_csv
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    derive_stage3_official_review_decision,
    resolve_stage3_output_kind,
    resolve_stage3_output_kind_source,
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
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.id_utils import normalize_id
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationReviewIndexRow,
)
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_relation_geojson_crs84


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

RELATION_EVIDENCE_CSV_NAME = "t03_swsd_rcsd_relation_evidence.csv"
RELATION_EVIDENCE_JSON_NAME = "t03_swsd_rcsd_relation_evidence.json"
INTERSECTION_MATCH_T03_NAME = "intersection_match_t03.geojson"
INTERSECTION_MATCH_T03_SUMMARY_NAME = "intersection_match_t03_summary.json"
INTERSECTION_MATCH_T03_CARDINALITY_CSV_NAME = "intersection_match_t03_cardinality_errors.csv"
INTERSECTION_MATCH_T03_CARDINALITY_JSON_NAME = "intersection_match_t03_cardinality_errors.json"
RELATION_EVIDENCE_FIELDNAMES = [
    "target_id",
    "case_id",
    "junction_type",
    "template_class",
    "association_class",
    "required_rcsdnode_ids",
    "required_rcsdroad_ids",
    "support_rcsdnode_ids",
    "support_rcsdroad_ids",
    "excluded_rcsdnode_ids",
    "excluded_rcsdroad_ids",
    "nonsemantic_connector_rcsdnode_ids",
    "true_foreign_rcsdnode_ids",
    "degree2_merged_rcsdroad_groups",
    "step7_state",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]
INTERSECTION_MATCH_T03_CARDINALITY_FIELDS = [
    "error_type",
    "target_id",
    "base_id",
    "related_target_ids",
    "introduced_by_module",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
]


def _stable_sort_key(case_id: str) -> tuple[int, int | str]:
    return (0, int(case_id)) if case_id.isdigit() else (1, case_id)


def _representative_lookup(shared_nodes: tuple[LayerFeature, ...]) -> dict[str, LayerFeature]:
    representatives: dict[str, LayerFeature] = {}
    for feature in shared_nodes:
        node_id = feature_id(feature)
        if node_id is not None:
            representatives.setdefault(node_id, feature)
    for feature in shared_nodes:
        node_id = feature_id(feature)
        mainnodeid = feature_mainnodeid(feature)
        if node_id is not None and mainnodeid is not None and node_id == mainnodeid:
            representatives.setdefault(mainnodeid, feature)
    return representatives


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


def _point_xy(geometry: Any) -> tuple[float | str, float | str]:
    if geometry is None or geometry.is_empty:
        return "", ""
    point = geometry if getattr(geometry, "geom_type", "") == "Point" else geometry.representative_point()
    return float(point.x), float(point.y)


def _json_text(value: Any) -> str:
    if value in (None, "", [], {}, ()):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _pipe_join(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, str):
        return normalize_id(values) or values
    return "|".join(normalized for value in values if (normalized := normalize_id(value)) is not None)


def _node_level(properties: dict[str, Any]) -> Any:
    value = properties.get("grade")
    return value if value not in (None, "") else -1


def _node_is_highway(properties: dict[str, Any]) -> Any:
    value = properties.get("closed_con")
    return value if value not in (None, "") else -1


def _junction_type_from_template(template_class: str | None) -> str:
    if template_class == "single_sided_t_mouth":
        return "single_sided_t_mouth"
    if template_class == "center_junction":
        return "center_junction"
    return str(template_class or "")


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_t03_handoff_status(case_dir: Path) -> dict[str, Any]:
    status_doc = _read_json_if_exists(case_dir / "association_status.json")
    if status_doc:
        return status_doc
    return _read_json_if_exists(case_dir / "step6_status.json")


def _required_rcsd_point(case_dir: Path) -> tuple[float | str, float | str]:
    required_path = case_dir / "association_required_rcsdnode.gpkg"
    if not required_path.is_file():
        return "", ""
    features = read_vector_layer(required_path).features
    if not features:
        return "", ""
    return _point_xy(features[0].geometry)


def _t03_relation_state(
    *,
    step7_state: str,
    association_class: str,
    required_rcsdnode_ids: list[Any],
) -> tuple[str, int, Any]:
    if step7_state != "accepted":
        return "geometry_not_accepted", 1, -1
    if association_class == "A" and required_rcsdnode_ids:
        return "success_required_rcsd_junction", 0, _pipe_join(required_rcsdnode_ids)
    if association_class == "B":
        return "rcsd_present_not_junction", 1, -1
    if association_class == "C":
        return "no_related_rcsd", 1, -1
    return "ambiguous_review", 1, -1


def _split_id_parts(value: Any) -> list[str]:
    if value in (None, "", [], {}, ()):
        return []
    parts = str(value).replace(",", "|").split("|")
    normalized_parts: list[str] = []
    for part in parts:
        normalized = normalize_id(part)
        if normalized is None or normalized in {"", "-1"} or _is_zero_id(normalized):
            continue
        normalized_parts.append(normalized)
    return normalized_parts


def _is_zero_id(value: Any) -> bool:
    text = normalize_id(value)
    if text is None:
        return False
    try:
        return float(text) == 0
    except ValueError:
        return text == "0"


def _is_success_status(value: Any) -> bool:
    text = normalize_id(value)
    if text is None:
        return False
    try:
        return float(text) == 0
    except ValueError:
        return text == "0"


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_from_evidence_row(row: dict[str, Any]) -> LineString | None:
    swsd_x = _float_or_none(row.get("swsd_point_x"))
    swsd_y = _float_or_none(row.get("swsd_point_y"))
    rcsd_x = _float_or_none(row.get("rcsd_point_x"))
    rcsd_y = _float_or_none(row.get("rcsd_point_y"))
    if None in {swsd_x, swsd_y, rcsd_x, rcsd_y}:
        return None
    return LineString([(swsd_x, swsd_y), (rcsd_x, rcsd_y)])


def _sort_relation_id(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _read_relation_evidence_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _t03_relation_records_from_evidence_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not _is_success_status(row.get("status_suggested")):
            continue
        target_id = normalize_id(row.get("target_id"))
        base_ids = _split_id_parts(row.get("base_id_candidate"))
        if target_id is None or not base_ids:
            continue
        for base_id in base_ids:
            properties = {
                "target_id": target_id,
                "base_id": base_id,
                "status": 0,
                "level": row.get("level", -1),
                "is_highway": row.get("is_highway", -1),
                "source_module": "T03",
                "source_case_id": row.get("case_id", ""),
                "relation_source": "T03_INTERSECTION_MATCH",
                "relation_state": row.get("relation_state", "success_required_rcsd_junction"),
                "reason": row.get("reason", "success_required_rcsd_junction"),
            }
            records.append(
                {
                    "feature_index": index,
                    "target_id": target_id,
                    "base_id": base_id,
                    "source_module": "T03",
                    "source_case_id": str(row.get("case_id") or target_id),
                    "relation_state": str(row.get("relation_state") or ""),
                    "reason": str(row.get("reason") or ""),
                    "representative_node_id": str(row.get("case_id") or target_id),
                    "step7_state": str(row.get("step7_state") or ""),
                    "properties": properties,
                    "geometry": _line_from_evidence_row(row),
                }
            )
    return records


def _read_external_intersection_match_records(
    path: Path | None,
    *,
    default_source_module: str,
    default_relation_state: str,
    default_reason: str,
) -> list[dict[str, Any]]:
    if path is None:
        return []
    if not path.is_file():
        raise FileNotFoundError(f"intersection match validation GeoJSON does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return []
    records: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        target_id = normalize_id(props.get("target_id"))
        base_id = normalize_id(props.get("base_id"))
        if target_id is None or base_id is None or not _is_success_status(props.get("status")) or _is_zero_id(base_id):
            continue
        source_module = str(props.get("source_module") or default_source_module)
        records.append(
            {
                "feature_index": index,
                "target_id": target_id,
                "base_id": base_id,
                "source_module": source_module,
                "source_case_id": str(props.get("source_case_id") or props.get("case_id") or ""),
                "relation_state": str(props.get("relation_state") or default_relation_state),
                "reason": str(props.get("reason") or default_reason),
                "representative_node_id": str(props.get("representative_node_id") or target_id),
                "step7_state": "",
                "properties": props,
                "geometry": feature.get("geometry"),
            }
        )
    return records


def _read_intersection_match_t07_records(path: Path | None) -> list[dict[str, Any]]:
    return _read_external_intersection_match_records(
        path,
        default_source_module="T07",
        default_relation_state="intersection_match_t07_matched",
        default_reason="intersection_match_t07_matched",
    )


def _same_optional_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _relation_error_row(
    *,
    error_type: str,
    target_ids: list[str],
    base_ids: list[str],
    records: list[dict[str, Any]],
) -> dict[str, str]:
    source_modules = {str(record.get("source_module") or "") for record in records if record.get("source_module")}
    source_case_ids = {str(record.get("source_case_id") or "") for record in records if record.get("source_case_id")}
    scenes = {str(record.get("relation_state") or "") for record in records if record.get("relation_state")}
    reasons = {error_type}
    reasons.update(str(record.get("reason") or "") for record in records if record.get("reason"))
    source_module_text = "|".join(sorted(source_modules, key=_sort_relation_id))
    return {
        "error_type": error_type,
        "target_id": "|".join(target_ids),
        "base_id": "|".join(base_ids),
        "related_target_ids": "|".join(target_ids),
        "introduced_by_module": source_module_text or "T03_INTERSECTION_MATCH",
        "source_modules": source_module_text,
        "source_case_ids": "|".join(sorted(source_case_ids, key=_sort_relation_id)),
        "scenes": "|".join(sorted(scenes, key=_sort_relation_id)),
        "reasons": "|".join(sorted({reason for reason in reasons if reason}, key=_sort_relation_id)),
    }


def _build_intersection_match_cardinality_errors(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    pair_records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        target_id = record.get("target_id")
        base_id = record.get("base_id")
        if target_id is None or base_id is None:
            continue
        pair_records[(str(target_id), str(base_id))].append(record)

    target_to_base: dict[str, set[str]] = defaultdict(set)
    base_to_target: dict[str, set[str]] = defaultdict(set)
    records_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (target_id, base_id), grouped_records in pair_records.items():
        target_to_base[target_id].add(base_id)
        base_to_target[base_id].add(target_id)
        records_by_target[target_id].extend(grouped_records)
        records_by_base[base_id].extend(grouped_records)

    errors: list[dict[str, str]] = []
    for target_id, base_ids in sorted(target_to_base.items(), key=lambda item: _sort_relation_id(item[0])):
        if len(base_ids) <= 1:
            continue
        errors.append(
            _relation_error_row(
                error_type="one_target_to_many_base",
                target_ids=[target_id],
                base_ids=sorted(base_ids, key=_sort_relation_id),
                records=records_by_target[target_id],
            )
        )
    for base_id, target_ids in sorted(base_to_target.items(), key=lambda item: _sort_relation_id(item[0])):
        if len(target_ids) <= 1:
            continue
        sorted_target_ids = sorted(target_ids, key=_sort_relation_id)
        errors.append(
            _relation_error_row(
                error_type="many_target_to_one_base",
                target_ids=sorted_target_ids,
                base_ids=[base_id],
                records=records_by_base[base_id],
            )
        )
    return errors


def _relation_error_counts(error_rows: list[dict[str, str]]) -> dict[str, Any]:
    counts = Counter(row.get("error_type", "") for row in error_rows)
    return {
        "relation_cardinality_error_count": len(error_rows),
        "one_target_to_many_base_count": int(counts["one_target_to_many_base"]),
        "many_target_to_one_base_count": int(counts["many_target_to_one_base"]),
        "relation_cardinality_passed": not error_rows,
    }


def _error_target_ids(error_rows: list[dict[str, str]]) -> set[str]:
    return {
        target_id
        for row in error_rows
        for target_id in _split_id_parts(row.get("target_id"))
    }


def _update_t03_summary_with_intersection_match(
    *,
    run_root: Path,
    summary: dict[str, Any],
) -> None:
    summary_path = run_root / "summary.json"
    if not summary_path.is_file():
        return
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["intersection_match_t03"] = summary
    write_json(summary_path, payload)


def write_intersection_match_t03(
    *,
    run_root: Path,
    relation_evidence_json_path: Path,
    intersection_match_all_path: Path | str | None = None,
    intersection_match_t07_path: Path | str | None = None,
) -> dict[str, Any]:
    all_path = Path(intersection_match_all_path) if intersection_match_all_path is not None else None
    t07_path = Path(intersection_match_t07_path) if intersection_match_t07_path is not None else None
    if all_path is not None and t07_path is not None and not _same_optional_path(all_path, t07_path):
        raise ValueError(
            "Provide only one optional relation validation input: "
            "intersection_match_all_path or intersection_match_t07_path."
        )
    validation_path = all_path if all_path is not None else t07_path
    validation_source = (
        "intersection_match_all"
        if all_path is not None
        else "intersection_match_t07"
        if t07_path is not None
        else ""
    )
    t03_records = _t03_relation_records_from_evidence_rows(_read_relation_evidence_rows(relation_evidence_json_path))
    if validation_source == "intersection_match_all":
        external_records = _read_external_intersection_match_records(
            validation_path,
            default_source_module="INTERSECTION_MATCH_ALL",
            default_relation_state="intersection_match_all_matched",
            default_reason="intersection_match_all_matched",
        )
    else:
        external_records = _read_intersection_match_t07_records(validation_path)
    error_rows = _build_intersection_match_cardinality_errors(t03_records + external_records)
    error_counts = _relation_error_counts(error_rows)
    suppressed_target_ids = _error_target_ids(error_rows)
    deduped_rollback_rows: list[dict[str, Any]] = []
    output_records = [
        record
        for record in t03_records
        if str(record["target_id"]) not in suppressed_target_ids
    ]

    match_path = run_root / INTERSECTION_MATCH_T03_NAME
    error_csv_path = run_root / INTERSECTION_MATCH_T03_CARDINALITY_CSV_NAME
    error_json_path = run_root / INTERSECTION_MATCH_T03_CARDINALITY_JSON_NAME
    summary_path = run_root / INTERSECTION_MATCH_T03_SUMMARY_NAME
    write_relation_geojson_crs84(
        match_path,
        ({"properties": record["properties"], "geometry": record["geometry"]} for record in output_records),
    )
    write_csv(error_csv_path, error_rows, INTERSECTION_MATCH_T03_CARDINALITY_FIELDS)
    write_json(
        error_json_path,
        {
            "row_count": len(error_rows),
            "fieldnames": INTERSECTION_MATCH_T03_CARDINALITY_FIELDS,
            "rows": error_rows,
        },
    )
    summary = {
        "intersection_match_t03_path": str(match_path),
        "intersection_match_all_path": str(all_path) if all_path is not None else "",
        "intersection_match_t07_path": str(t07_path) if t07_path is not None else "",
        "relation_validation_path": str(validation_path) if validation_path is not None else "",
        "relation_validation_source": validation_source,
        "external_validation_enabled": validation_path is not None,
        "t07_validation_enabled": validation_source == "intersection_match_t07",
        "target_crs": "CRS84",
        "t03_candidate_relation_count": len(t03_records),
        "external_validation_relation_count": len(external_records),
        "t07_validation_relation_count": (
            len(external_records) if validation_source == "intersection_match_t07" else 0
        ),
        "published_relation_count": len(output_records),
        "suppressed_target_ids": sorted(suppressed_target_ids, key=_sort_relation_id),
        "rollback_target_ids": sorted({str(row["target_id"]) for row in deduped_rollback_rows}, key=_sort_relation_id),
        **error_counts,
        "cardinality_errors_csv": str(error_csv_path),
        "cardinality_errors_json": str(error_json_path),
    }
    write_json(summary_path, summary)
    _update_t03_summary_with_intersection_match(run_root=run_root, summary=summary)
    return {
        "intersection_match_t03_path": match_path,
        "intersection_match_t03_summary_path": summary_path,
        "intersection_match_t03_cardinality_errors_csv_path": error_csv_path,
        "intersection_match_t03_cardinality_errors_json_path": error_json_path,
        "intersection_match_t03_summary": summary,
        "intersection_match_t03_rollback_rows": deduped_rollback_rows,
    }


def _update_t03_summary_with_relation_evidence(
    *,
    run_root: Path,
    csv_path: Path,
    json_path: Path,
    row_count: int,
) -> None:
    summary_path = run_root / "summary.json"
    if not summary_path.is_file():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["relation_evidence"] = {
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "row_count": row_count,
        "target_crs": "EPSG:3857",
        "handoff_target": "T05 intersection_match_all.geojson source evidence",
    }
    write_json(summary_path, summary)


def materialize_t03_review_gallery(
    run_root: Path,
    rows: list[FinalizationReviewIndexRow],
    *,
    target_dir: Path | None = None,
    layout: str = "legacy",
) -> list[FinalizationReviewIndexRow]:
    if layout not in {"legacy", "flat"}:
        raise ValueError(f"unsupported T03 review gallery layout: {layout}")
    accepted_dir = run_root / T03_REVIEW_ACCEPTED_DIRNAME
    rejected_dir = run_root / T03_REVIEW_REJECTED_DIRNAME
    v2_risk_dir = run_root / T03_REVIEW_V2_RISK_DIRNAME
    flat_dir = target_dir if target_dir is not None else run_root / T03_REVIEW_FLAT_DIRNAME
    target_dirs = (accepted_dir, rejected_dir, v2_risk_dir, flat_dir) if layout == "legacy" else (flat_dir,)
    for path in target_dirs:
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
            flat_path = flat_dir / image_name
            shutil.copy2(source_path, flat_path)
            output_image_path = str(flat_path)
            if layout == "legacy":
                categorized_dir = accepted_dir if row.step7_state == "accepted" else rejected_dir
                shutil.copy2(source_path, categorized_dir / image_name)
            if layout == "legacy" and row.visual_class == "V2 业务正确但几何待修":
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
    visual_outputs: dict[str, Any] | None = None,
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
        "visual_outputs": visual_outputs or {
            "enabled": True,
            "layout": "legacy",
            "directory": str(flat_dir),
        },
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

    if streamed_result.step7_state != "accepted":
        return None

    visual_review_class = streamed_result.visual_class
    business_outcome_class = "success"
    acceptance_class = "accepted"
    success = True
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


def write_t03_relation_evidence(
    *,
    run_root: Path,
    shared_nodes: tuple[LayerFeature, ...],
    selected_case_ids: list[str],
    streamed_results: dict[str, T03StreamedCaseResult],
    failed_case_ids: list[str],
) -> dict[str, Path]:
    failed_case_id_set = {str(case_id) for case_id in failed_case_ids}
    representative_by_case_id = _representative_lookup(shared_nodes)
    rows: list[dict[str, Any]] = []
    for case_id in sorted(selected_case_ids, key=sort_patch_key):
        representative_feature = representative_by_case_id.get(case_id) or resolve_representative_feature(shared_nodes, case_id)
        representative_properties = dict(representative_feature.properties)
        representative_node_id = feature_id(representative_feature) or case_id
        target_id = feature_mainnodeid(representative_feature) or representative_node_id
        swsd_point_x, swsd_point_y = _point_xy(representative_feature.geometry)
        case_dir = run_root / "cases" / case_id
        status_doc = _read_t03_handoff_status(case_dir)
        record = streamed_results.get(case_id)
        if record is None:
            step7_state = "runtime_failed" if case_id in failed_case_id_set else "formal_result_missing"
            association_class = str(status_doc.get("association_class") or "")
            template_class = status_doc.get("template_class")
            reason = step7_state
        else:
            step7_state = record.step7_state
            association_class = record.association_class
            template_class = record.template_class
            reason = record.reason
        required_rcsdnode_ids = list(status_doc.get("required_rcsdnode_ids") or [])
        required_rcsdroad_ids = list(status_doc.get("required_rcsdroad_ids") or [])
        support_rcsdnode_ids = list(status_doc.get("support_rcsdnode_ids") or [])
        support_rcsdroad_ids = list(status_doc.get("support_rcsdroad_ids") or [])
        relation_state, status_suggested, base_id_candidate = _t03_relation_state(
            step7_state=step7_state,
            association_class=association_class,
            required_rcsdnode_ids=required_rcsdnode_ids,
        )
        rcsd_point_x, rcsd_point_y = _required_rcsd_point(case_dir) if status_suggested == 0 else ("", "")
        rows.append(
            {
                "target_id": target_id,
                "case_id": case_id,
                "junction_type": _junction_type_from_template(template_class),
                "template_class": template_class or "",
                "association_class": association_class,
                "required_rcsdnode_ids": _pipe_join(required_rcsdnode_ids),
                "required_rcsdroad_ids": _pipe_join(required_rcsdroad_ids),
                "support_rcsdnode_ids": _pipe_join(support_rcsdnode_ids),
                "support_rcsdroad_ids": _pipe_join(support_rcsdroad_ids),
                "excluded_rcsdnode_ids": _pipe_join(status_doc.get("excluded_rcsdnode_ids")),
                "excluded_rcsdroad_ids": _pipe_join(status_doc.get("excluded_rcsdroad_ids")),
                "nonsemantic_connector_rcsdnode_ids": _pipe_join(status_doc.get("nonsemantic_connector_rcsdnode_ids")),
                "true_foreign_rcsdnode_ids": _pipe_join(status_doc.get("true_foreign_rcsdnode_ids")),
                "degree2_merged_rcsdroad_groups": _json_text(status_doc.get("degree2_merged_rcsdroad_groups")),
                "step7_state": step7_state,
                "surface_candidate_present": int(step7_state == "accepted"),
                "base_id_candidate": base_id_candidate,
                "status_suggested": status_suggested,
                "relation_state": relation_state,
                "reason": reason or relation_state,
                "level": _node_level(representative_properties),
                "is_highway": _node_is_highway(representative_properties),
                "swsd_point_x": swsd_point_x,
                "swsd_point_y": swsd_point_y,
                "rcsd_point_x": rcsd_point_x,
                "rcsd_point_y": rcsd_point_y,
            }
        )
    csv_path = run_root / RELATION_EVIDENCE_CSV_NAME
    json_path = run_root / RELATION_EVIDENCE_JSON_NAME
    write_csv(csv_path, rows, RELATION_EVIDENCE_FIELDNAMES)
    write_json(
        json_path,
        {
            "target_crs": "EPSG:3857",
            "row_count": len(rows),
            "fieldnames": RELATION_EVIDENCE_FIELDNAMES,
            "rows": rows,
        },
    )
    _update_t03_summary_with_relation_evidence(
        run_root=run_root,
        csv_path=csv_path,
        json_path=json_path,
        row_count=len(rows),
    )
    return {"relation_evidence_csv_path": csv_path, "relation_evidence_json_path": json_path}


def _write_nodes_audit_outputs(*, audit_csv_path: Path, audit_json_path: Path, rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    write_csv(
        audit_csv_path,
        rows,
        [
            "case_id",
            "representative_node_id",
            "previous_is_anchor",
            "new_is_anchor",
            "step7_state",
            "reason",
        ],
    )
    payload["total_update_count"] = len(rows)
    payload["updated_to_yes_count"] = sum(1 for row in rows if row["new_is_anchor"] == "yes")
    payload["updated_to_fail3_count"] = sum(1 for row in rows if row["new_is_anchor"] == "fail3")
    payload["updated_to_no_count"] = sum(1 for row in rows if row["new_is_anchor"] == "no")
    payload["rows"] = rows
    write_json(audit_json_path, payload)


def _apply_intersection_match_t03_node_rollbacks(
    *,
    nodes_output_path: Path,
    audit_csv_path: Path,
    audit_json_path: Path,
    rollback_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not rollback_rows:
        return {"requested_update_count": 0, "sqlite_changed_row_count": 0}
    audit_payload = json.loads(audit_json_path.read_text(encoding="utf-8")) if audit_json_path.is_file() else {}
    audit_rows = [dict(row) for row in audit_payload.get("rows", []) if isinstance(row, dict)]
    previous_value_by_node_id = {
        str(row.get("representative_node_id")): row.get("new_is_anchor")
        for row in audit_rows
        if row.get("representative_node_id") not in (None, "")
    }
    updates_by_node_id = {
        str(row["representative_node_id"]): "no"
        for row in rollback_rows
        if str(row.get("representative_node_id") or "").strip()
    }
    rollback_update_result = update_gpkg_field_by_id(
        path=nodes_output_path,
        updates_by_id=updates_by_node_id,
        id_field="id",
        update_field="is_anchor",
        strategy="sqlite_rollback_update",
    )

    for row in rollback_rows:
        representative_node_id = str(row.get("representative_node_id") or "")
        audit_rows.append(
            {
                "case_id": row.get("case_id") or row.get("target_id") or representative_node_id,
                "representative_node_id": representative_node_id,
                "previous_is_anchor": previous_value_by_node_id.get(representative_node_id, ""),
                "new_is_anchor": "no",
                "step7_state": row.get("step7_state") or "",
                "reason": row.get("reason") or "intersection_match_t03_one_target_to_many_base",
            }
        )
    audit_payload["intersection_match_t03_rollback_result"] = rollback_update_result
    _write_nodes_audit_outputs(
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        rows=audit_rows,
        payload=audit_payload,
    )
    return rollback_update_result


def write_updated_nodes_outputs(
    *,
    run_root: Path,
    shared_nodes: tuple[LayerFeature, ...],
    selected_case_ids: list[str],
    streamed_results: dict[str, T03StreamedCaseResult],
    failed_case_ids: list[str],
    input_nodes_path: Path | str | None = None,
    intersection_match_all_path: Path | str | None = None,
    intersection_match_t07_path: Path | str | None = None,
) -> dict[str, Any]:
    updates_by_node_id: dict[str, str] = {}
    audit_rows: list[dict[str, Any]] = []
    failed_case_id_set = {str(case_id) for case_id in failed_case_ids}
    representative_by_case_id = _representative_lookup(shared_nodes)

    for case_id in sorted(selected_case_ids, key=sort_patch_key):
        representative_feature = representative_by_case_id.get(case_id) or resolve_representative_feature(shared_nodes, case_id)
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

    nodes_output_path = run_root / "nodes.gpkg"
    audit_csv_path = run_root / "nodes_anchor_update_audit.csv"
    audit_json_path = run_root / "nodes_anchor_update_audit.json"
    if input_nodes_path is not None:
        nodes_update_result = copy_gpkg_and_update_field_by_id(
            source_path=input_nodes_path,
            output_path=nodes_output_path,
            updates_by_id=updates_by_node_id,
            id_field="id",
            update_field="is_anchor",
        )
    else:
        nodes_features = []
        for feature in shared_nodes:
            properties = dict(feature.properties)
            node_id = feature_id(feature)
            if node_id is not None and node_id in updates_by_node_id:
                properties["is_anchor"] = updates_by_node_id[node_id]
            nodes_features.append({"properties": properties, "geometry": feature.geometry})
        write_vector(nodes_output_path, nodes_features, crs_text="EPSG:3857")
        nodes_update_result = {
            "strategy": "fiona_full_rewrite",
            "layer_name": "nodes",
            "requested_update_count": len(updates_by_node_id),
            "sqlite_changed_row_count": "",
        }
    _write_nodes_audit_outputs(
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        rows=audit_rows,
        payload={"nodes_update_result": nodes_update_result},
    )
    relation_outputs = write_t03_relation_evidence(
        run_root=run_root,
        shared_nodes=shared_nodes,
        selected_case_ids=selected_case_ids,
        streamed_results=streamed_results,
        failed_case_ids=failed_case_ids,
    )
    intersection_match_outputs = write_intersection_match_t03(
        run_root=run_root,
        relation_evidence_json_path=relation_outputs["relation_evidence_json_path"],
        intersection_match_all_path=intersection_match_all_path,
        intersection_match_t07_path=intersection_match_t07_path,
    )
    rollback_update_result = _apply_intersection_match_t03_node_rollbacks(
        nodes_output_path=nodes_output_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        rollback_rows=intersection_match_outputs["intersection_match_t03_rollback_rows"],
    )
    return {
        "nodes_path": nodes_output_path,
        "audit_csv_path": audit_csv_path,
        "audit_json_path": audit_json_path,
        "nodes_update_result": nodes_update_result,
        **relation_outputs,
        **intersection_match_outputs,
        "intersection_match_t03_rollback_result": rollback_update_result,
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
    "write_intersection_match_t03",
    "write_t03_relation_evidence",
    "write_updated_nodes_outputs",
    "write_virtual_intersection_polygons",
]
