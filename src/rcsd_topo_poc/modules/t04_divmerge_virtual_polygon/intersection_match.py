from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_relation_geojson_crs84

from ._runtime_shared import normalize_id
from .final_publish import RELATION_EVIDENCE_JSON_NAME


INTERSECTION_MATCH_T04_NAME = "intersection_match_t04.geojson"
INTERSECTION_MATCH_T04_SUMMARY_NAME = "intersection_match_t04_summary.json"
INTERSECTION_MATCH_T04_CARDINALITY_CSV_NAME = "intersection_match_t04_cardinality_errors.csv"
INTERSECTION_MATCH_T04_CARDINALITY_JSON_NAME = "intersection_match_t04_cardinality_errors.json"

INTERSECTION_MATCH_T04_CARDINALITY_FIELDS = [
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


def _split_id_parts(value: Any) -> list[str]:
    if value in (None, "", [], {}, ()):
        return []
    result: list[str] = []
    for part in str(value).replace(",", "|").split("|"):
        normalized = normalize_id(part)
        if normalized is None or normalized in {"", "-1"} or _is_zero_id(normalized):
            continue
        result.append(normalized)
    return result


def _is_zero_id(value: Any) -> bool:
    text = normalize_id(value)
    if text is None:
        return False
    try:
        return float(text) == 0
    except ValueError:
        return text == "0"


def _is_success_status(value: Any) -> bool:
    return _is_zero_id(value)


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


def _read_relation_evidence_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _t04_relation_records_from_evidence_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                "source_module": "T04",
                "source_case_id": row.get("case_id", ""),
                "relation_source": "T04_INTERSECTION_MATCH",
                "relation_state": row.get("relation_state", "success_required_rcsd_junction"),
                "reason": row.get("reason", "success_required_rcsd_junction"),
                "final_state": row.get("final_state", ""),
                "scene_type": row.get("scene_type", ""),
                "junction_type": row.get("junction_type", ""),
                "surface_candidate_present": row.get("surface_candidate_present", ""),
            }
            records.append(
                {
                    "feature_index": index,
                    "target_id": target_id,
                    "base_id": base_id,
                    "source_module": "T04",
                    "source_case_id": str(row.get("case_id") or target_id),
                    "relation_state": str(row.get("relation_state") or ""),
                    "reason": str(row.get("reason") or ""),
                    "representative_node_id": str(row.get("case_id") or target_id),
                    "step7_state": str(row.get("final_state") or ""),
                    "properties": properties,
                    "geometry": _line_from_evidence_row(row),
                }
            )
    return records


def _read_intersection_match_records(path: Path | None, *, source_module: str) -> list[dict[str, Any]]:
    records, _audit = _read_intersection_match_source(path, source_module=source_module)
    return records


def _read_intersection_match_source(path: Path | None, *, source_module: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = {
        "source_module": source_module,
        "path": str(path) if path is not None else "",
        "provided": path is not None,
        "status": "not_provided",
        "usable": False,
        "record_count": 0,
        "error": "",
    }
    if path is None:
        return [], audit
    if not path.is_file():
        raise FileNotFoundError(f"{source_module} intersection match does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        audit["status"] = "empty_file"
        audit["error"] = "intersection match file is empty"
        return [], audit
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        audit["status"] = "invalid_json"
        audit["error"] = f"{exc.msg}: line {exc.lineno} column {exc.colno}"
        return [], audit
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        audit["status"] = "missing_features"
        audit["error"] = "GeoJSON payload does not contain a features list"
        return [], audit
    records: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        target_id = normalize_id(props.get("target_id"))
        base_id = normalize_id(props.get("base_id"))
        if target_id is None or base_id is None or not _is_success_status(props.get("status")):
            continue
        if _is_zero_id(base_id) or base_id == "-1":
            continue
        records.append(
            {
                "feature_index": index,
                "target_id": target_id,
                "base_id": base_id,
                "source_module": source_module,
                "source_case_id": str(props.get("source_case_id") or props.get("case_id") or ""),
                "relation_state": str(props.get("relation_state") or f"intersection_match_{source_module.lower()}"),
                "reason": str(props.get("reason") or f"intersection_match_{source_module.lower()}"),
                "representative_node_id": str(props.get("representative_node_id") or target_id),
                "step7_state": str(props.get("step7_state") or props.get("final_state") or ""),
                "properties": props,
                "geometry": feature.get("geometry"),
            }
        )
    audit["status"] = "ok"
    audit["usable"] = True
    audit["record_count"] = len(records)
    return records, audit


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
    source_module_text = "|".join(sorted(source_modules, key=sort_patch_key))
    return {
        "error_type": error_type,
        "target_id": "|".join(target_ids),
        "base_id": "|".join(base_ids),
        "related_target_ids": "|".join(target_ids),
        "introduced_by_module": source_module_text or "T04_INTERSECTION_MATCH",
        "source_modules": source_module_text,
        "source_case_ids": "|".join(sorted(source_case_ids, key=sort_patch_key)),
        "scenes": "|".join(sorted(scenes, key=sort_patch_key)),
        "reasons": "|".join(sorted({reason for reason in reasons if reason}, key=sort_patch_key)),
    }


def _build_cardinality_errors(records: list[dict[str, Any]]) -> list[dict[str, str]]:
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
    for target_id, base_ids in sorted(target_to_base.items(), key=lambda item: sort_patch_key(item[0])):
        if len(base_ids) <= 1:
            continue
        errors.append(
            _relation_error_row(
                error_type="one_target_to_many_base",
                target_ids=[target_id],
                base_ids=sorted(base_ids, key=sort_patch_key),
                records=records_by_target[target_id],
            )
        )
    for base_id, target_ids in sorted(base_to_target.items(), key=lambda item: sort_patch_key(item[0])):
        if len(target_ids) <= 1:
            continue
        sorted_target_ids = sorted(target_ids, key=sort_patch_key)
        errors.append(
            _relation_error_row(
                error_type="many_target_to_one_base",
                target_ids=sorted_target_ids,
                base_ids=[base_id],
                records=records_by_base[base_id],
            )
        )
    return errors


def _error_counts(error_rows: list[dict[str, str]]) -> dict[str, Any]:
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


def _patch_closeout_documents(*, run_root: Path, summary: dict[str, Any]) -> None:
    for path in [run_root / "divmerge_virtual_anchor_surface_summary.json", run_root / "step7_consistency_report.json"]:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["intersection_match_t04"] = summary
        if path.name == "step7_consistency_report.json":
            payload["intersection_match_t04_path"] = summary["intersection_match_t04_path"]
            payload["intersection_match_t04_cardinality_passed"] = summary["relation_cardinality_passed"]
            payload["intersection_match_t04_cardinality_error_count"] = summary["relation_cardinality_error_count"]
            payload["intersection_match_t04_rollback_target_ids"] = list(summary["rollback_target_ids"])
            if bool(summary.get("external_validation_enabled")):
                payload["passed"] = bool(payload.get("passed")) and bool(summary["relation_cardinality_passed"])
        write_json(path, payload)


def write_intersection_match_t04(
    *,
    run_root: Path,
    relation_evidence_json_path: Path | None = None,
    intersection_match_t07_path: Path | str | None = None,
    intersection_match_t03_path: Path | str | None = None,
) -> dict[str, Any]:
    relation_path = relation_evidence_json_path or (run_root / RELATION_EVIDENCE_JSON_NAME)
    t07_path = Path(intersection_match_t07_path) if intersection_match_t07_path is not None else None
    t03_path = Path(intersection_match_t03_path) if intersection_match_t03_path is not None else None
    t04_records = _t04_relation_records_from_evidence_rows(_read_relation_evidence_rows(relation_path))
    t07_records, t07_validation_input = _read_intersection_match_source(t07_path, source_module="T07")
    t03_records, t03_validation_input = _read_intersection_match_source(t03_path, source_module="T03")
    external_validation_enabled = t07_path is not None or t03_path is not None
    error_rows = _build_cardinality_errors(t07_records + t03_records + t04_records)
    error_counts = _error_counts(error_rows)
    suppressed_target_ids = _error_target_ids(error_rows)
    deduped_rollback_rows: list[dict[str, Any]] = []
    output_records = [
        record
        for record in t04_records
        if str(record["target_id"]) not in suppressed_target_ids
    ]

    match_path = run_root / INTERSECTION_MATCH_T04_NAME
    error_csv_path = run_root / INTERSECTION_MATCH_T04_CARDINALITY_CSV_NAME
    error_json_path = run_root / INTERSECTION_MATCH_T04_CARDINALITY_JSON_NAME
    summary_path = run_root / INTERSECTION_MATCH_T04_SUMMARY_NAME
    write_relation_geojson_crs84(
        match_path,
        ({"properties": record["properties"], "geometry": record["geometry"]} for record in output_records),
    )
    write_csv(error_csv_path, error_rows, INTERSECTION_MATCH_T04_CARDINALITY_FIELDS)
    write_json(
        error_json_path,
        {
            "row_count": len(error_rows),
            "fieldnames": INTERSECTION_MATCH_T04_CARDINALITY_FIELDS,
            "rows": error_rows,
        },
    )
    summary = {
        "intersection_match_t04_path": str(match_path),
        "intersection_match_t07_path": str(t07_path) if t07_path is not None else "",
        "intersection_match_t03_path": str(t03_path) if t03_path is not None else "",
        "t07_validation_enabled": t07_path is not None,
        "t03_validation_enabled": t03_path is not None,
        "external_validation_enabled": external_validation_enabled,
        "target_crs": "CRS84",
        "t04_candidate_relation_count": len(t04_records),
        "t07_validation_relation_count": len(t07_records),
        "t03_validation_relation_count": len(t03_records),
        "t07_validation_input": t07_validation_input,
        "t03_validation_input": t03_validation_input,
        "external_validation_unusable_input_count": sum(
            1
            for item in (t07_validation_input, t03_validation_input)
            if item["provided"] and not item["usable"]
        ),
        "published_relation_count": len(output_records),
        "suppressed_target_ids": sorted(suppressed_target_ids, key=sort_patch_key),
        "rollback_target_ids": sorted({str(row["target_id"]) for row in deduped_rollback_rows}, key=sort_patch_key),
        **error_counts,
        "cardinality_errors_csv": str(error_csv_path),
        "cardinality_errors_json": str(error_json_path),
    }
    write_json(summary_path, summary)
    _patch_closeout_documents(run_root=run_root, summary=summary)
    return {
        "intersection_match_t04_path": str(match_path),
        "intersection_match_t04_summary_path": str(summary_path),
        "intersection_match_t04_cardinality_errors_csv_path": str(error_csv_path),
        "intersection_match_t04_cardinality_errors_json_path": str(error_json_path),
        "intersection_match_t04_summary": summary,
        "intersection_match_t04_rollback_rows": deduped_rollback_rows,
    }


__all__ = [
    "INTERSECTION_MATCH_T04_CARDINALITY_CSV_NAME",
    "INTERSECTION_MATCH_T04_CARDINALITY_JSON_NAME",
    "INTERSECTION_MATCH_T04_NAME",
    "INTERSECTION_MATCH_T04_SUMMARY_NAME",
    "write_intersection_match_t04",
]
