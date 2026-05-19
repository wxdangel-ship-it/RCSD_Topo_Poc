from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


T03_BACKFILL_FIELDS = [
    "required_rcsdnode_ids",
    "required_rcsdroad_ids",
    "support_rcsdnode_ids",
    "support_rcsdroad_ids",
    "excluded_rcsdnode_ids",
    "excluded_rcsdroad_ids",
    "nonsemantic_connector_rcsdnode_ids",
    "true_foreign_rcsdnode_ids",
    "degree2_merged_rcsdroad_groups",
]

DERIVED_FIELDS = [
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "surface_candidate_present",
]

AUDIT_FIELDS = [
    "target_id",
    "case_id",
    "step7_state",
    "source_status_path",
    "source_audit_path",
    "backfill_action",
    "required_rcsdnode_ids",
    "support_rcsdroad_ids",
    "relation_state_before",
    "relation_state_after",
    "status_suggested_before",
    "status_suggested_after",
    "base_id_candidate_before",
    "base_id_candidate_after",
    "notes",
]


@dataclass(frozen=True)
class T03RelationEvidenceBackfillArtifacts:
    out_root: Path
    evidence_csv_path: Path
    evidence_json_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    summary_path: Path
    row_count: int
    backfilled_row_count: int


def backfill_t03_relation_evidence(
    *,
    t03_run_root: str | Path,
    out_root: str | Path | None = None,
    relation_evidence_path: str | Path | None = None,
    case_ids: Iterable[str] | None = None,
    accepted_only: bool = False,
) -> T03RelationEvidenceBackfillArtifacts:
    root = Path(t03_run_root)
    if not root.is_dir():
        raise ValueError(f"t03_run_root does not exist or is not a directory: {root}")
    evidence_path = Path(relation_evidence_path) if relation_evidence_path else root / "t03_swsd_rcsd_relation_evidence.csv"
    rows, fieldnames = _read_relation_evidence(evidence_path)
    case_filter = {str(item).strip() for item in case_ids or [] if str(item).strip()}
    if case_filter:
        rows = [row for row in rows if _case_id(row) in case_filter or _target_id(row) in case_filter]
    output_root = Path(out_root) if out_root else root / "t05_phase2_handoff"
    output_root.mkdir(parents=True, exist_ok=True)

    required_fields = _ordered_unique([*fieldnames, *T03_BACKFILL_FIELDS, *DERIVED_FIELDS])
    backfilled_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    backfilled_count = 0
    skipped_nonaccepted = 0
    missing_case_status = 0

    for row in rows:
        working = dict(row)
        case_id = _case_id(working)
        target_id = _target_id(working)
        step_payload, status_path, audit_payload, audit_path = _load_case_payloads(root, case_id or target_id)
        source_payload = _merge_step6_payloads(step_payload, audit_payload)
        step7_state = _text(working.get("step7_state") or source_payload.get("step7_state"))
        if accepted_only and step7_state and step7_state != "accepted":
            skipped_nonaccepted += 1
            continue

        relation_before = _text(working.get("relation_state"))
        status_before = _text(working.get("status_suggested"))
        base_before = _text(working.get("base_id_candidate"))
        action = "missing_step6_status"
        notes = ""

        if source_payload:
            for field in T03_BACKFILL_FIELDS:
                value = _ids_text(source_payload.get(field))
                if value and not _has_value(working.get(field)):
                    working[field] = value
            action = _derive_relation_fields(working, source_payload)
            if action != "no_backfill_needed":
                backfilled_count += 1
        else:
            missing_case_status += 1
            notes = "cases/<case_id>/step6_status.json and step6_audit.json inputs are missing"

        if step7_state == "accepted" and not _has_value(working.get("surface_candidate_present")):
            working["surface_candidate_present"] = "1"

        backfilled_rows.append({field: working.get(field, "") for field in required_fields})
        audit_rows.append(
            {
                "target_id": target_id,
                "case_id": case_id,
                "step7_state": step7_state,
                "source_status_path": str(status_path) if status_path else "",
                "source_audit_path": str(audit_path) if audit_path else "",
                "backfill_action": action,
                "required_rcsdnode_ids": _ids_text(working.get("required_rcsdnode_ids")),
                "support_rcsdroad_ids": _ids_text(working.get("support_rcsdroad_ids")),
                "relation_state_before": relation_before,
                "relation_state_after": _text(working.get("relation_state")),
                "status_suggested_before": status_before,
                "status_suggested_after": _text(working.get("status_suggested")),
                "base_id_candidate_before": base_before,
                "base_id_candidate_after": _text(working.get("base_id_candidate")),
                "notes": notes,
            }
        )

    evidence_csv = output_root / "t03_swsd_rcsd_relation_evidence_backfilled.csv"
    evidence_json = output_root / "t03_swsd_rcsd_relation_evidence_backfilled.json"
    audit_csv = output_root / "t03_swsd_rcsd_relation_evidence_backfill_audit.csv"
    audit_json = output_root / "t03_swsd_rcsd_relation_evidence_backfill_audit.json"
    summary_path = output_root / "t03_swsd_rcsd_relation_evidence_backfill_summary.json"
    produced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_csv(evidence_csv, backfilled_rows, required_fields)
    _write_json(
        evidence_json,
        {
            "produced_at": produced_at,
            "row_count": len(backfilled_rows),
            "fieldnames": required_fields,
            "rows": backfilled_rows,
        },
    )
    _write_csv(audit_csv, audit_rows, AUDIT_FIELDS)
    _write_json(audit_json, {"produced_at": produced_at, "row_count": len(audit_rows), "rows": audit_rows})
    summary = {
        "produced_at": produced_at,
        "input_paths": {
            "t03_run_root": str(root),
            "relation_evidence_path": str(evidence_path),
        },
        "output_paths": {
            "evidence_csv": str(evidence_csv),
            "evidence_json": str(evidence_json),
            "audit_csv": str(audit_csv),
            "audit_json": str(audit_json),
            "summary": str(summary_path),
        },
        "input_row_count": len(rows),
        "output_row_count": len(backfilled_rows),
        "backfilled_row_count": backfilled_count,
        "skipped_nonaccepted_count": skipped_nonaccepted,
        "missing_case_status_count": missing_case_status,
        "accepted_only": accepted_only,
        "case_filter_count": len(case_filter),
    }
    _write_json(summary_path, summary)
    return T03RelationEvidenceBackfillArtifacts(
        out_root=output_root,
        evidence_csv_path=evidence_csv,
        evidence_json_path=evidence_json,
        audit_csv_path=audit_csv,
        audit_json_path=audit_json,
        summary_path=summary_path,
        row_count=len(backfilled_rows),
        backfilled_row_count=backfilled_count,
    )


def _derive_relation_fields(row: dict[str, Any], source_payload: dict[str, Any]) -> str:
    required_nodes = _ids_text(row.get("required_rcsdnode_ids") or source_payload.get("required_rcsdnode_ids"))
    support_roads = _ids_text(row.get("support_rcsdroad_ids") or source_payload.get("support_rcsdroad_ids"))
    changed = False
    if required_nodes:
        changed |= _set_if_different(row, "base_id_candidate", required_nodes)
        changed |= _set_if_different(row, "status_suggested", "0")
        changed |= _set_if_different(row, "relation_state", "success_required_rcsd_junction")
        if not _has_value(row.get("reason")) or _text(row.get("reason")).startswith("step7_"):
            row["reason"] = "t03_backfilled_required_rcsdnode_ids"
            changed = True
        return "backfilled_required_rcsdnode_ids" if changed else "no_backfill_needed"
    if support_roads:
        changed |= _set_if_different(row, "base_id_candidate", "-1")
        changed |= _set_if_different(row, "status_suggested", "1")
        changed |= _set_if_different(row, "relation_state", "rcsd_present_not_junction")
        if not _has_value(row.get("reason")) or _text(row.get("reason")).startswith("step7_"):
            row["reason"] = "t03_backfilled_support_rcsdroad_ids"
            changed = True
        return "backfilled_support_rcsdroad_ids" if changed else "no_backfill_needed"
    return "no_backfill_needed"


def _read_relation_evidence(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        raise ValueError(f"T03 relation evidence input does not exist: {path}")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            return [dict(row) for row in reader], list(reader.fieldnames or [])
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("rows") or []
        fields = payload.get("fieldnames") or []
    elif isinstance(payload, list):
        rows = payload
        fields = []
    else:
        raise ValueError(f"Unsupported T03 relation evidence JSON shape: {path}")
    dict_rows = [dict(row) for row in rows if isinstance(row, dict)]
    return dict_rows, _ordered_unique([str(field) for field in fields] + [key for row in dict_rows for key in row])


def _load_case_payloads(root: Path, case_id: str) -> tuple[dict[str, Any], Path | None, dict[str, Any], Path | None]:
    if not case_id:
        return {}, None, {}, None
    case_dir = _find_case_dir(root, str(case_id))
    status_path = case_dir / "step6_status.json"
    audit_path = case_dir / "step6_audit.json"
    status_payload = _read_json_dict(status_path) if status_path.is_file() else {}
    audit_payload = _read_json_dict(audit_path) if audit_path.is_file() else {}
    return status_payload, status_path if status_payload else None, audit_payload, audit_path if audit_payload else None


def _find_case_dir(root: Path, case_id: str) -> Path:
    direct = root / "cases" / case_id
    if direct.is_dir():
        return direct
    nested = sorted(root.glob(f"*/cases/{case_id}"))
    if nested:
        return nested[0]
    return direct


def _merge_step6_payloads(status_payload: dict[str, Any], audit_payload: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    inputs = audit_payload.get("inputs") if isinstance(audit_payload.get("inputs"), dict) else {}
    for payload in (inputs, audit_payload, status_payload):
        for key, value in payload.items():
            if value not in (None, "", []):
                merged[key] = value
    return merged


def _read_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _ids_text(value: Any) -> str:
    if value in (None, "", -1, "-1", 0, "0", []):
        return ""
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(",", "|").split("|")]
        return "|".join(part for part in parts if part and part not in {"-1", "0"})
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item).strip() for item in value if str(item).strip() and str(item).strip() not in {"-1", "0"})
    return str(value).strip()


def _has_value(value: Any) -> bool:
    return _text(value) not in {"", "-1"}


def _set_if_different(row: dict[str, Any], field: str, value: str) -> bool:
    if _text(row.get(field)) == value:
        return False
    row[field] = value
    return True


def _case_id(row: dict[str, Any]) -> str:
    return _text(row.get("case_id") or row.get("target_id"))


def _target_id(row: dict[str, Any]) -> str:
    return _text(row.get("target_id") or row.get("case_id"))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
