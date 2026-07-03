from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


MANUAL_RELATION_ACTIONABLE_TYPES = {
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
}

T11_MANUAL_REVIEW_XLSX_FILENAMES = {
    "all_1v1_not_replaced": "t11_segments_all_1v1_relation_success_but_not_replaced.xlsx",
    "all_evidence_relation_gaps": "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx",
    "no_evidence_relation_gaps": "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx",
}

MANUAL_RELATION_CSV_FIELDS = [
    "case_id",
    "swsd_segment_id",
    "target_id",
    "manual_relation_type",
    "selected_ids",
    "comment",
    "source_manual_table",
    "source_manual_xlsx",
]

T05_MANUAL_FINAL_REJECTED_FIELDS = [
    "target_id",
    "swsd_segment_id",
    "manual_relation_type",
    "manual_selected_ids",
    "t05_scene",
    "t05_action",
    "t05_status",
    "t05_base_id",
    "t05_reason",
    "t05_skipped_reason",
    "blocking_error",
    "original_rcsdroad_ids",
    "original_rcsdnode_ids",
    "new_rcsdroad_ids",
    "new_rcsdnode_ids",
    "grouped_rcsdnode_ids",
    "selected_main_rcsdnode_id",
    "reject_category",
    "suggested_manual_check",
]

T05_MANUAL_GRAPH_UNCONSUMABLE_REFERENCE_FIELDS = [
    *T05_MANUAL_FINAL_REJECTED_FIELDS,
    "graph_consumable",
    "graph_consumability_status",
    "graph_recommended_action",
]

T05_BLOCKING_CARDINALITY_ERROR_TYPES = {"one_target_to_many_base", "duplicate_target_rows"}


@dataclass(frozen=True)
class ManualRelationFinalRejectedArtifacts:
    rejected_csv: Path
    graph_unconsumable_reference_csv: Path
    summary_json: Path
    summary: dict[str, Any]


@dataclass(frozen=True)
class ManualRelationImportArtifacts:
    manual_relation_csv: Path
    summary_json: Path
    summary: dict[str, Any]


def resolve_t11_manual_review_xlsx_paths(
    *,
    manual_audit_root: Path,
    all_1v1_xlsx: Path | None = None,
    all_evidence_xlsx: Path | None = None,
    no_evidence_xlsx: Path | None = None,
) -> dict[str, Path]:
    paths = {
        "all_1v1_not_replaced": all_1v1_xlsx,
        "all_evidence_relation_gaps": all_evidence_xlsx,
        "no_evidence_relation_gaps": no_evidence_xlsx,
    }
    resolved: dict[str, Path] = {}
    for table_name, explicit in paths.items():
        path = explicit or manual_audit_root / T11_MANUAL_REVIEW_XLSX_FILENAMES[table_name]
        if not path.is_file():
            raise FileNotFoundError(f"missing T11 manual review workbook for {table_name}: {path}")
        resolved[table_name] = path
    return resolved


def import_t11_manual_review_xlsx_to_csv(
    *,
    xlsx_paths: dict[str, Path],
    out_csv: Path,
    case_id: str = "605415675",
) -> ManualRelationImportArtifacts:
    rows, summary = read_t11_manual_review_xlsx_rows(xlsx_paths=xlsx_paths, case_id=case_id)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_RELATION_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANUAL_RELATION_CSV_FIELDS})
    summary = {
        **summary,
        "manual_relation_csv": str(out_csv),
        "manual_relation_csv_fields": list(MANUAL_RELATION_CSV_FIELDS),
        "produced_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    summary_json = out_csv.with_suffix(".summary.json")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return ManualRelationImportArtifacts(manual_relation_csv=out_csv, summary_json=summary_json, summary=summary)


def read_t11_manual_review_xlsx_rows(
    *,
    xlsx_paths: dict[str, Path],
    case_id: str = "605415675",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    accepted: list[dict[str, str]] = []
    accepted_targets: set[str] = set()
    stats: dict[str, Any] = {
        "input_xlsx_paths": {name: str(path) for name, path in xlsx_paths.items()},
        "source_table_stats": {},
        "accepted_row_count": 0,
        "ignored_non_actionable_row_count": 0,
        "ignored_selected_ids_null_or_empty_count": 0,
        "ignored_manual_row_not_consumable_count": 0,
        "ignored_duplicate_target_count": 0,
        "accepted_target_ids": [],
    }
    for table_name, path in xlsx_paths.items():
        table_stats = {
            "raw_row_count": 0,
            "accepted_row_count": 0,
            "ignored_non_actionable_row_count": 0,
            "ignored_selected_ids_null_or_empty_count": 0,
            "ignored_manual_row_not_consumable_count": 0,
            "ignored_duplicate_target_count": 0,
        }
        for raw in read_text_xlsx(path):
            table_stats["raw_row_count"] += 1
            manual_type = _text(raw.get("manual_relation_type"))
            selected_ids = _text(raw.get("selected_ids"))
            target_id = _text(raw.get("target_id"))
            if manual_type not in MANUAL_RELATION_ACTIONABLE_TYPES:
                table_stats["ignored_non_actionable_row_count"] += 1
                stats["ignored_non_actionable_row_count"] += 1
                continue
            if not selected_ids or selected_ids.lower() == "null":
                table_stats["ignored_selected_ids_null_or_empty_count"] += 1
                stats["ignored_selected_ids_null_or_empty_count"] += 1
                continue
            if _is_false_like(raw.get("manual_row_consumable")):
                table_stats["ignored_manual_row_not_consumable_count"] += 1
                stats["ignored_manual_row_not_consumable_count"] += 1
                continue
            if not target_id:
                table_stats["ignored_non_actionable_row_count"] += 1
                stats["ignored_non_actionable_row_count"] += 1
                continue
            if target_id in accepted_targets:
                table_stats["ignored_duplicate_target_count"] += 1
                stats["ignored_duplicate_target_count"] += 1
                continue
            accepted_targets.add(target_id)
            comment = _text(raw.get("comment"))
            source_note = f"source_table={table_name}"
            accepted.append(
                {
                    "case_id": _text(raw.get("case_id")) or case_id,
                    "swsd_segment_id": _text(raw.get("swsd_segment_id")),
                    "target_id": target_id,
                    "manual_relation_type": manual_type,
                    "selected_ids": selected_ids,
                    "comment": f"{comment};{source_note}" if comment else source_note,
                    "source_manual_table": table_name,
                    "source_manual_xlsx": str(path),
                }
            )
            table_stats["accepted_row_count"] += 1
            stats["accepted_row_count"] += 1
        stats["source_table_stats"][table_name] = table_stats
    stats["accepted_target_ids"] = sorted(accepted_targets)
    return accepted, stats


def read_text_xlsx(path: Path) -> list[dict[str, str]]:
    table = _read_text_xlsx_table(path)
    if not table:
        return []
    headers = [_text(value) for value in table[0]]
    rows: list[dict[str, str]] = []
    for values in table[1:]:
        if not any(_text(value) for value in values):
            continue
        row = {header: _text(values[index]) if index < len(values) else "" for index, header in enumerate(headers) if header}
        rows.append(row)
    return rows


def compare_t06_run_metrics(*, before_t06_root: Path, after_t06_root: Path, out_json: Path | None = None) -> dict[str, Any]:
    before = _t06_metrics(before_t06_root)
    after = _t06_metrics(after_t06_root)
    delta = {
        key: round(after[key] - before[key], 6)
        for key in sorted(after)
        if isinstance(after[key], (int, float)) and isinstance(before.get(key), (int, float))
    }
    report = {
        "before_t06_root": str(before_t06_root),
        "after_t06_root": str(after_t06_root),
        "before": before,
        "after": after,
        "delta": delta,
    }
    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_t05_manual_relation_final_rejected_reports(
    *,
    manual_relation_csv: Path,
    t05_phase2_root: Path,
    out_root: Path | None = None,
) -> ManualRelationFinalRejectedArtifacts:
    phase2_root = Path(t05_phase2_root)
    output_root = Path(out_root) if out_root is not None else phase2_root
    _require_t05_manual_rejection_inputs(phase2_root, manual_relation_csv)

    manual_rows = _read_csv_rows(manual_relation_csv)
    manual_by_target = _actionable_manual_rows_by_target(manual_rows)
    audit_rows = _read_csv_rows(phase2_root / "rcsd_junctionization_audit.csv")
    graph_rows = _read_csv_rows(phase2_root / "relation_graph_consumability_audit.csv")
    blocking_rows = _read_csv_rows(phase2_root / "blocking_errors.csv")
    cardinality_rows = _read_csv_rows(phase2_root / "relation_cardinality_errors.csv")

    audit_by_target = _rows_by_target(audit_rows)
    t11_audit_by_target = {
        target_id: [row for row in rows if _source_contains(row.get("source_module"), "T11_MANUAL")]
        for target_id, rows in audit_by_target.items()
    }
    blocking_by_target = _blocking_rows_by_manual_target(blocking_rows, manual_by_target)
    cardinality_by_target = _blocking_cardinality_rows_by_manual_target(cardinality_rows, manual_by_target)

    strict_targets: set[str] = set()
    for target_id, rows in t11_audit_by_target.items():
        if target_id not in manual_by_target:
            continue
        for row in rows:
            if _strictly_rejected_audit_row(row):
                strict_targets.add(target_id)
                break
    strict_targets.update(blocking_by_target)
    strict_targets.update(cardinality_by_target)

    rejected_rows = [
        _manual_rejection_row(
            target_id=target_id,
            manual_row=manual_by_target[target_id],
            audit_row=_pick_audit_row(t11_audit_by_target.get(target_id), audit_by_target.get(target_id)),
            blocking_rows=blocking_by_target.get(target_id, []),
            cardinality_rows=cardinality_by_target.get(target_id, []),
        )
        for target_id in sorted(strict_targets, key=_sort_key)
        if target_id in manual_by_target
    ]
    rejected_target_ids = {row["target_id"] for row in rejected_rows}

    graph_reference_rows = []
    graph_by_target = _rows_by_target(graph_rows)
    for target_id, graph_target_rows in sorted(graph_by_target.items(), key=lambda item: _sort_key(item[0])):
        if target_id not in manual_by_target or target_id in rejected_target_ids:
            continue
        graph_row = _pick_graph_unconsumable_success_row(graph_target_rows)
        if graph_row is None:
            continue
        base_row = _manual_rejection_row(
            target_id=target_id,
            manual_row=manual_by_target[target_id],
            audit_row=_pick_audit_row(t11_audit_by_target.get(target_id), audit_by_target.get(target_id)),
            blocking_rows=[],
            cardinality_rows=[],
            category_override="graph_unconsumable_reference",
        )
        graph_reference_rows.append(
            {
                **base_row,
                "t05_reason": _join_nonempty([base_row.get("t05_reason"), graph_row.get("graph_consumability_status")]),
                "graph_consumable": _text(graph_row.get("graph_consumable")),
                "graph_consumability_status": _text(graph_row.get("graph_consumability_status")),
                "graph_recommended_action": _text(graph_row.get("recommended_action")),
            }
        )

    rejected_csv = output_root / "t05_manual_relation_final_rejected_junctions.csv"
    graph_csv = output_root / "t05_manual_relation_graph_unconsumable_reference.csv"
    summary_json = output_root / "t05_manual_relation_final_rejected_summary.json"
    _write_csv_rows(rejected_csv, rejected_rows, T05_MANUAL_FINAL_REJECTED_FIELDS)
    _write_csv_rows(graph_csv, graph_reference_rows, T05_MANUAL_GRAPH_UNCONSUMABLE_REFERENCE_FIELDS)

    success_targets = {
        target_id
        for target_id, rows in t11_audit_by_target.items()
        if target_id in manual_by_target
        and target_id not in rejected_target_ids
        and any(_successful_valid_audit_row(row) for row in rows)
    }
    category_counts = Counter(row["reject_category"] for row in rejected_rows)
    summary = {
        "manual_actionable_target_count": len(manual_by_target),
        "t05_manual_consumed_success_count": len(success_targets),
        "t05_final_rejected_count": len(rejected_rows),
        "graph_unconsumable_reference_count": len(graph_reference_rows),
        "reject_category_counts": dict(sorted(category_counts.items())),
        "t05_manual_audit_row_count": sum(len(rows) for rows in t11_audit_by_target.values()),
        "output_paths": {
            "t05_manual_relation_final_rejected_junctions": str(rejected_csv),
            "t05_manual_relation_graph_unconsumable_reference": str(graph_csv),
            "t05_manual_relation_final_rejected_summary": str(summary_json),
        },
        "input_paths": {
            "manual_relation_csv": str(manual_relation_csv),
            "t05_phase2_root": str(phase2_root),
        },
        "produced_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return ManualRelationFinalRejectedArtifacts(
        rejected_csv=rejected_csv,
        graph_unconsumable_reference_csv=graph_csv,
        summary_json=summary_json,
        summary=summary,
    )


def resolve_rcsd_inputs_from_case_root(case_root: Path) -> tuple[Path, Path]:
    summary_path = case_root / "t05" / "t05_phase2" / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        input_paths = summary.get("input_paths") or {}
        rcsdroad = Path(str(input_paths.get("rcsdroad_path") or ""))
        rcsdnode = Path(str(input_paths.get("rcsdnode_path") or ""))
        if rcsdroad.is_file() and rcsdnode.is_file():
            return rcsdroad, rcsdnode
    fallback_root = Path("/mnt/d/TestData/POC_Data/T10/605415675/external_inputs")
    rcsdroad = fallback_root / "rcsdroad" / "rcsdroad_slice.gpkg"
    rcsdnode = fallback_root / "rcsdnode" / "rcsdnode_slice.gpkg"
    if rcsdroad.is_file() and rcsdnode.is_file():
        return rcsdroad, rcsdnode
    raise FileNotFoundError(
        "cannot resolve RCSD inputs from case root summary or default T10 external_inputs: "
        f"{summary_path}"
    )


def _require_t05_manual_rejection_inputs(t05_phase2_root: Path, manual_relation_csv: Path) -> None:
    required = [
        manual_relation_csv,
        t05_phase2_root / "intersection_match_all.geojson",
        t05_phase2_root / "rcsd_junctionization_audit.csv",
        t05_phase2_root / "relation_graph_consumability_audit.csv",
        t05_phase2_root / "blocking_errors.csv",
        t05_phase2_root / "relation_cardinality_errors.csv",
    ]
    missing = [str(path) for path in required if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError("missing T05 manual rejection report inputs: " + ", ".join(missing))


def _actionable_manual_rows_by_target(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        target_id = _normalize_id(row.get("target_id"))
        manual_type = _text(row.get("manual_relation_type"))
        selected_ids = _text(row.get("selected_ids") or row.get("manual_selected_ids"))
        if not target_id or target_id in result:
            continue
        if manual_type not in MANUAL_RELATION_ACTIONABLE_TYPES:
            continue
        if not selected_ids or selected_ids.lower() == "null":
            continue
        result[target_id] = {**row, "target_id": target_id, "selected_ids": selected_ids}
    return result


def _rows_by_target(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        target_id = _normalize_id(row.get("target_id"))
        if not target_id:
            continue
        result.setdefault(target_id, []).append(row)
    return result


def _blocking_rows_by_manual_target(
    rows: list[dict[str, str]],
    manual_by_target: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        target_ids = _normalized_parts(row.get("target_id"))
        for target_id in sorted(target_ids & set(manual_by_target), key=_sort_key):
            result.setdefault(target_id, []).append(row)
    return result


def _blocking_cardinality_rows_by_manual_target(
    rows: list[dict[str, str]],
    manual_by_target: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if _text(row.get("error_type")) not in T05_BLOCKING_CARDINALITY_ERROR_TYPES:
            continue
        target_ids = _normalized_parts(row.get("related_target_ids")) or _normalized_parts(row.get("target_id"))
        for target_id in sorted(target_ids & set(manual_by_target), key=_sort_key):
            result.setdefault(target_id, []).append(row)
    return result


def _strictly_rejected_audit_row(row: dict[str, str]) -> bool:
    return (
        _text(row.get("status")) != "0"
        or not _valid_base_id(row.get("base_id"))
        or _nonzero(row.get("blocking_error"))
    )


def _successful_valid_audit_row(row: dict[str, str]) -> bool:
    return _text(row.get("status")) == "0" and _valid_base_id(row.get("base_id")) and not _nonzero(row.get("blocking_error"))


def _pick_audit_row(
    t11_rows: list[dict[str, str]] | None,
    fallback_rows: list[dict[str, str]] | None,
) -> dict[str, str]:
    for row in t11_rows or []:
        if _strictly_rejected_audit_row(row):
            return row
    if t11_rows:
        return t11_rows[0]
    return (fallback_rows or [{}])[0]


def _pick_graph_unconsumable_success_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in rows:
        if _text(row.get("relation_status")) == "0" and _false_like(row.get("graph_consumable")):
            return row
    return None


def _manual_rejection_row(
    *,
    target_id: str,
    manual_row: dict[str, str],
    audit_row: dict[str, str],
    blocking_rows: list[dict[str, str]],
    cardinality_rows: list[dict[str, str]],
    category_override: str | None = None,
) -> dict[str, str]:
    category = category_override or _reject_category(
        manual_row=manual_row,
        audit_row=audit_row,
        cardinality_rows=cardinality_rows,
    )
    cardinality_types = [_text(row.get("error_type")) for row in cardinality_rows]
    reason = _join_nonempty(
        [
            audit_row.get("reason"),
            *[row.get("reason") for row in blocking_rows],
            *[row.get("reasons") for row in cardinality_rows],
            "|".join(cardinality_types),
        ]
    )
    skipped_reason = _join_nonempty(
        [
            audit_row.get("skipped_reason"),
            *[f"relation_cardinality_error:{item}" for item in cardinality_types if item],
        ]
    )
    return {
        "target_id": target_id,
        "swsd_segment_id": _text(manual_row.get("swsd_segment_id")),
        "manual_relation_type": _text(manual_row.get("manual_relation_type")),
        "manual_selected_ids": _text(manual_row.get("selected_ids") or manual_row.get("manual_selected_ids")),
        "t05_scene": _text(audit_row.get("scene")) or _join_nonempty([row.get("scenes") for row in cardinality_rows]),
        "t05_action": _text(audit_row.get("action")),
        "t05_status": _text(audit_row.get("status")),
        "t05_base_id": _text(audit_row.get("base_id")) or _join_nonempty([row.get("base_id") for row in cardinality_rows]),
        "t05_reason": reason,
        "t05_skipped_reason": skipped_reason,
        "blocking_error": _text(audit_row.get("blocking_error")) or ("1" if blocking_rows else "0"),
        "original_rcsdroad_ids": _text(audit_row.get("original_rcsdroad_ids")),
        "original_rcsdnode_ids": _text(audit_row.get("original_rcsdnode_ids")),
        "new_rcsdroad_ids": _text(audit_row.get("new_rcsdroad_ids")),
        "new_rcsdnode_ids": _text(audit_row.get("new_rcsdnode_ids")),
        "grouped_rcsdnode_ids": _text(audit_row.get("grouped_rcsdnode_ids")),
        "selected_main_rcsdnode_id": _text(audit_row.get("selected_main_rcsdnode_id")),
        "reject_category": category,
        "suggested_manual_check": _suggested_manual_check(category),
    }


def _reject_category(
    *,
    manual_row: dict[str, str],
    audit_row: dict[str, str],
    cardinality_rows: list[dict[str, str]],
) -> str:
    if cardinality_rows:
        return "cardinality_blocked"
    manual_type = _text(manual_row.get("manual_relation_type"))
    text = "|".join(
        _text(value)
        for value in (
            audit_row.get("reason"),
            audit_row.get("skipped_reason"),
            audit_row.get("scene"),
            audit_row.get("action"),
        )
    )
    if "missing_rcsdnode_ids" in text or "missing_endpoint_rcsdnode_ids" in text:
        return "selected_rcsdnode_missing"
    if "missing_rcsdroad_id" in text:
        return "selected_rcsdroad_missing"
    if "rcsdnode_grouping_failed" in text or "multiple_base_id_unmergeable" in text:
        return "rcsdnode_grouping_failed"
    if "rcsdroad_split_failed" in text or "no_valid_split_point" in text or "missing_fact_reference_point" in text:
        return "rcsdroad_split_failed"
    if manual_type.endswith("_road") and _text(audit_row.get("status")) != "0":
        return "rcsdroad_split_failed"
    return "other_t05_failure"


def _suggested_manual_check(category: str) -> str:
    suggestions = {
        "selected_rcsdnode_missing": "Check whether selected_ids are RCSDNode.id/mainnodeid and exist in T05 rcsdnode_out.gpkg; reselect RCSDNode if needed.",
        "selected_rcsdroad_missing": "Check whether selected_ids are RCSDRoad.id and exist in T05 input or rcsdroad_out.gpkg; reselect a projectable RCSDRoad if needed.",
        "rcsdnode_grouping_failed": "Review whether selected RCSDNodes belong to one semantic junction and can share one mainnodeid; narrow or reselect the node group if needed.",
        "rcsdroad_split_failed": "Review whether the road-only selection can project to a splittable RCSDRoad, especially missing_rcsdroad_id, no_valid_split_point, and endpoint reuse conditions.",
        "cardinality_blocked": "Review whether one target produced multiple bases or duplicate success rows; keep exactly one publishable relation.",
        "graph_unconsumable_reference": "T05 published a success relation but graph topology is not consumable; route to incident-road or T06 replaceability review, not T05 final rejection.",
        "other_t05_failure": "Review T05 scene/action/reason/skipped_reason and confirm manual_relation_type matches the selected_ids kind.",
    }
    return suggestions.get(category, suggestions["other_t05_failure"])


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {_text(key): _text(value) for key, value in row.items() if key is not None}
            for row in reader
        ]


def _write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _normalized_parts(value: Any) -> set[str]:
    return {normalized for part in str(value or "").replace(",", "|").split("|") if (normalized := _normalize_id(part))}


def _normalize_id(value: Any) -> str:
    text = _text(value)
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    try:
        numeric = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if numeric == numeric.to_integral_value():
        return str(int(numeric))
    return text


def _valid_base_id(value: Any) -> bool:
    return _normalize_id(value) not in {"", "0", "-1"}


def _nonzero(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        return int(float(text)) != 0
    except ValueError:
        return text.lower() not in {"false", "no", "none", "null"}


def _source_contains(value: Any, source: str) -> bool:
    return source in {part.strip() for part in str(value or "").replace(",", "|").split("|") if part.strip()}


def _false_like(value: Any) -> bool:
    return _text(value).lower() in {"0", "false", "no"}


def _join_nonempty(values: Iterable[Any]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return "|".join(result)


def _sort_key(value: Any) -> tuple[int, int | str]:
    text = _normalize_id(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _read_text_xlsx_table(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        strings = _read_shared_strings(archive)
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    table: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            ref = cell.attrib.get("r", "")
            column_index = _cell_column_index(ref)
            if column_index is None:
                continue
            values[column_index] = _cell_text(cell, strings, namespace)
        width = max(values) + 1 if values else 0
        table.append([values.get(index, "") for index in range(width)])
    return table


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        shared_xml = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(shared_xml)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for item in root.findall("x:si", namespace):
        parts = [node.text or "" for node in item.findall(".//x:t", namespace)]
        strings.append("".join(parts))
    return strings


def _cell_text(cell: ET.Element, strings: list[str], namespace: dict[str, str]) -> str:
    value = cell.find("x:v", namespace)
    if value is None or value.text is None:
        inline = cell.find("x:is/x:t", namespace)
        return _text(inline.text if inline is not None else "")
    text = value.text
    if cell.attrib.get("t") == "s":
        try:
            return strings[int(text)]
        except (ValueError, IndexError):
            return ""
    return _text(text)


def _cell_column_index(ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", ref.upper())
    if not match:
        return None
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _t06_metrics(root: Path) -> dict[str, Any]:
    step1 = _read_json(root / "step1_identify_fusion_units" / "t06_step1_summary.json")
    step2 = _read_json(root / "step2_extract_rcsd_segments" / "t06_step2_summary.json")
    step3 = _read_json(root / "step3_segment_replacement" / "t06_step3_summary.json")
    attribution = _read_json(
        root / "step3_segment_replacement" / "t06_step3_unreplaced_rcsd_attribution_summary.json"
    )
    unreplaced_length = attribution.get("unreplaced_rcsd_road_length_m")
    total_length = _estimate_total_rcsd_length(attribution.get("by_attribution_class") or [])
    replaced_rate = None if total_length in (None, 0) or unreplaced_length is None else (1 - unreplaced_length / total_length) * 100.0
    return {
        "step1_final_fusion_unit_count": step1.get("final_fusion_unit_count") or step1.get("swsd_final_fusion_unit_count"),
        "manual_anchor_override_segment_count": step1.get("manual_relation_anchor_override_segment_count", 0),
        "manual_evd_override_segment_count": step1.get("manual_relation_evd_override_segment_count", 0),
        "step2_replaceable_count": step2.get("replaceable_count"),
        "replacement_plan_ready_count": step2.get("replacement_plan_ready_count"),
        "step3_replacement_success_count": step3.get("replacement_unit_success_count"),
        "removed_swsd_road_count": step3.get("removed_swsd_road_count"),
        "added_rcsd_road_count": step3.get("added_rcsd_road_count"),
        "frcsd_road_count": step3.get("frcsd_road_count"),
        "unreplaced_rcsd_road_count": attribution.get("unreplaced_rcsd_road_count"),
        "unreplaced_rcsd_road_length_m": unreplaced_length,
        "rcsd_replaced_length_rate_percent": round(replaced_rate, 6) if replaced_rate is not None else None,
        "unreplaced_rcsd_attribution_classes": attribution.get("by_attribution_class") or [],
    }


def _estimate_total_rcsd_length(classes: Iterable[dict[str, Any]]) -> float | None:
    for item in classes:
        length = item.get("length_m")
        rate = item.get("total_length_rate")
        if isinstance(length, (int, float)) and isinstance(rate, (int, float)) and rate:
            return float(length) / float(rate)
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _is_false_like(value: Any) -> bool:
    text = _text(value).lower()
    return text in {"0", "false", "no"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()
