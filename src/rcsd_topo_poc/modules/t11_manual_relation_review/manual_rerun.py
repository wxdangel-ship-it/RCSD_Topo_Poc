from __future__ import annotations

import csv
import json
import re
import zipfile
from dataclasses import dataclass
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
