from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from ._runtime_shared import normalize_id
from .final_publish import RELATION_EVIDENCE_CSV_NAME, RELATION_EVIDENCE_FIELDNAMES, RELATION_EVIDENCE_JSON_NAME
from .provenance import provenance_doc


FALLBACK_NODE_VALUE = "fail4_fallback"
FALLBACK_RELATION_STATE = "success_required_rcsd_junction"
FALLBACK_AUDIT_CSV_NAME = "t04_relation_fallback_audit.csv"
FALLBACK_AUDIT_JSON_NAME = "t04_relation_fallback_audit.json"
FALLBACK_SUMMARY_NAME = "t04_relation_fallback_summary.json"

FALLBACK_AUDIT_FIELDNAMES = [
    "case_id",
    "target_id",
    "fallback_state",
    "previous_relation_state",
    "new_relation_state",
    "previous_status_suggested",
    "new_status_suggested",
    "required_rcsd_node_ids",
    "base_id_candidate",
    "reason",
]


def enrich_t04_relation_evidence_with_fallback(
    *,
    run_root: Path,
    selected_cases: Iterable[Mapping[str, Any]],
    source_node_features: Iterable[Any],
    rcsdnode_features: Iterable[Any],
    rcsdintersection_features: Iterable[Any] | None = None,
    failure_status_by_case: Mapping[str, Any] | None = None,
    input_dataset_id: str | None = None,
) -> dict[str, Any]:
    """Rewrite T04 relation evidence with relation-only fallback successes."""
    failure_status_by_case = {} if failure_status_by_case is None else dict(failure_status_by_case)
    rcsdnode_feature_list = list(rcsdnode_features)
    rcsdintersection_feature_list = list(rcsdintersection_features or [])
    selected = [
        {"case_id": str(item.get("case_id")), "mainnodeid": str(item.get("mainnodeid") or item.get("case_id"))}
        for item in selected_cases
    ]
    relation_csv_path = run_root / RELATION_EVIDENCE_CSV_NAME
    relation_json_path = run_root / RELATION_EVIDENCE_JSON_NAME
    rows = _read_relation_rows(relation_csv_path)
    rows_by_case = {str(row.get("case_id")): dict(row) for row in rows if str(row.get("case_id") or "").strip()}
    node_by_id = {
        node_id: feature
        for feature in source_node_features
        for node_id in [_feature_id(feature)]
        if node_id is not None
    }
    rcsd_group_by_node_id, rcsd_point_by_group_id = _rcsd_group_indexes(rcsdnode_feature_list)
    rcsd_geometry_by_node_id = _rcsd_node_geometry_index(rcsdnode_feature_list)
    rcsdintersection_by_singleton_node_id = _rcsdintersection_singleton_index(
        rcsdintersection_feature_list,
        rcsd_geometry_by_node_id=rcsd_geometry_by_node_id,
    )

    enriched_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    fallback_success_case_ids: list[str] = []
    fallback_reason_by_case: dict[str, str] = {}
    fallback_base_id_by_case: dict[str, str] = {}

    for case_doc in selected:
        case_id = case_doc["case_id"]
        mainnodeid = case_doc["mainnodeid"]
        row = rows_by_case.get(case_id) or _default_relation_row(
            case_id=case_id,
            mainnodeid=mainnodeid,
            feature=node_by_id.get(mainnodeid) or node_by_id.get(case_id),
            failure_status=failure_status_by_case.get(case_id),
        )
        previous_relation_state = str(row.get("relation_state") or "")
        previous_status = str(row.get("status_suggested") or "")
        required_nodes = _ordered_values(
            _split_values(row.get("required_rcsd_node_ids"))
            + _case_required_rcsd_nodes(run_root=run_root, case_id=case_id)
        )
        if required_nodes and not str(row.get("required_rcsd_node_ids") or "").strip():
            row["required_rcsd_node_ids"] = "|".join(required_nodes)
        fallback_state, base_id_candidate, reason = _fallback_decision(
            row=row,
            required_nodes=required_nodes,
            rcsd_group_by_node_id=rcsd_group_by_node_id,
            rcsdintersection_by_singleton_node_id=rcsdintersection_by_singleton_node_id,
        )
        if fallback_state == "success":
            row["base_id_candidate"] = base_id_candidate
            row["status_suggested"] = 0
            row["relation_state"] = FALLBACK_RELATION_STATE
            row["surface_candidate_present"] = 0
            row["reason"] = f"fail4_fallback:{reason}"
            x, y = rcsd_point_by_group_id.get(str(base_id_candidate), ("", ""))
            row["rcsd_point_x"] = x
            row["rcsd_point_y"] = y
            fallback_success_case_ids.append(case_id)
            fallback_reason_by_case[case_id] = str(row["reason"])
            fallback_base_id_by_case[case_id] = str(base_id_candidate)
        enriched_rows.append(_normalize_row(row))
        audit_rows.append(
            {
                "case_id": case_id,
                "target_id": row.get("target_id") or mainnodeid,
                "fallback_state": fallback_state,
                "previous_relation_state": previous_relation_state,
                "new_relation_state": row.get("relation_state"),
                "previous_status_suggested": previous_status,
                "new_status_suggested": row.get("status_suggested"),
                "required_rcsd_node_ids": "|".join(required_nodes),
                "base_id_candidate": row.get("base_id_candidate"),
                "reason": reason,
            }
        )

    write_csv(relation_csv_path, enriched_rows, RELATION_EVIDENCE_FIELDNAMES)
    write_json(
        relation_json_path,
        {
            **provenance_doc(input_dataset_id=input_dataset_id),
            "target_crs": "EPSG:3857",
            "row_count": len(enriched_rows),
            "fieldnames": RELATION_EVIDENCE_FIELDNAMES,
            "fallback_success_count": len(fallback_success_case_ids),
            "fallback_success_case_ids": fallback_success_case_ids,
            "rows": enriched_rows,
        },
    )
    audit_csv_path = run_root / FALLBACK_AUDIT_CSV_NAME
    audit_json_path = run_root / FALLBACK_AUDIT_JSON_NAME
    summary_path = run_root / FALLBACK_SUMMARY_NAME
    write_csv(audit_csv_path, audit_rows, FALLBACK_AUDIT_FIELDNAMES)
    write_json(
        audit_json_path,
        {
            **provenance_doc(input_dataset_id=input_dataset_id),
            "row_count": len(audit_rows),
            "fallback_success_count": len(fallback_success_case_ids),
            "rows": audit_rows,
        },
    )
    summary_payload = {
        **provenance_doc(input_dataset_id=input_dataset_id),
        "fallback_success_count": len(fallback_success_case_ids),
        "fallback_success_case_ids": fallback_success_case_ids,
        "fallback_failed_count": len(audit_rows) - len(fallback_success_case_ids),
        "relation_evidence_csv_path": str(relation_csv_path),
        "relation_evidence_json_path": str(relation_json_path),
        "fallback_audit_csv_path": str(audit_csv_path),
        "fallback_audit_json_path": str(audit_json_path),
    }
    write_json(summary_path, summary_payload)
    _patch_closeout_documents(
        run_root=run_root,
        relation_row_count=len(enriched_rows),
        fallback_success_case_ids=fallback_success_case_ids,
    )
    return {
        **summary_payload,
        "fallback_success_case_ids": fallback_success_case_ids,
        "fallback_reason_by_case": fallback_reason_by_case,
        "fallback_base_id_by_case": fallback_base_id_by_case,
        "summary_path": str(summary_path),
    }


def _read_relation_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row.get(field, "") for field in RELATION_EVIDENCE_FIELDNAMES}


def _default_relation_row(
    *,
    case_id: str,
    mainnodeid: str,
    feature: Any | None,
    failure_status: Any,
) -> dict[str, Any]:
    props = _properties(feature)
    x, y = _point_xy(_geometry(feature))
    step7_state = "formal_result_missing"
    reason = "formal_result_missing"
    if isinstance(failure_status, Mapping):
        step7_state = str(failure_status.get("step7_state") or step7_state)
        reason = str(failure_status.get("reason") or reason)
    return {
        "target_id": mainnodeid or case_id,
        "case_id": case_id,
        "junction_type": _junction_type(props.get("kind_2")),
        "scene_type": "",
        "final_state": step7_state,
        "swsd_relation_type": "unknown",
        "required_rcsd_node_ids": "",
        "selected_rcsdnode_ids": "",
        "selected_rcsdroad_ids": "",
        "rcsd_profile": "",
        "has_c_unit": 0,
        "surface_candidate_present": 0,
        "base_id_candidate": -1,
        "status_suggested": 1,
        "relation_state": "geometry_not_accepted",
        "reason": reason,
        "level": _node_level(props),
        "is_highway": _node_is_highway(props),
        "patch_id": "",
        "swsd_point_x": x,
        "swsd_point_y": y,
        "rcsd_point_x": "",
        "rcsd_point_y": "",
    }


def _fallback_decision(
    *,
    row: Mapping[str, Any],
    required_nodes: list[str],
    rcsd_group_by_node_id: Mapping[str, str],
    rcsdintersection_by_singleton_node_id: Mapping[str, str],
) -> tuple[str, str | int, str]:
    if str(row.get("final_state") or "") == "accepted":
        return "skipped_accepted_surface", row.get("base_id_candidate", -1), "accepted_surface"
    if str(row.get("relation_state") or "") == "ambiguous_review":
        return "failed", -1, "ambiguous_review"
    if not required_nodes:
        return "failed", -1, "required_rcsd_node_missing"
    missing_nodes = [node_id for node_id in required_nodes if node_id not in rcsd_group_by_node_id]
    if missing_nodes:
        return "failed", -1, "missing_rcsdnode_group_id:" + "|".join(missing_nodes)
    group_ids_by_node: dict[str, str] = {}
    singleton_resolution_reasons: set[str] = set()
    for node_id in required_nodes:
        raw_group_id = rcsd_group_by_node_id[node_id]
        resolved_group_id, singleton_reason = _resolved_rcsd_group_id(
            node_id=node_id,
            raw_group_id=raw_group_id,
            row=row,
            required_node_count=len(required_nodes),
            rcsdintersection_by_singleton_node_id=rcsdintersection_by_singleton_node_id,
        )
        group_ids_by_node[node_id] = resolved_group_id
        if singleton_reason:
            singleton_resolution_reasons.add(singleton_reason)
    invalid_group_nodes = [
        f"{node_id}={group_id}"
        for node_id, group_id in group_ids_by_node.items()
        if not _is_valid_rcsd_group_id(group_id)
    ]
    if invalid_group_nodes:
        return "failed", -1, "invalid_rcsdnode_group_id:" + "|".join(invalid_group_nodes)
    group_ids = _ordered_values(group_ids_by_node.values())
    if len(group_ids) != 1:
        return "failed", -1, "ambiguous_rcsd_group_id:" + "|".join(group_ids)
    if singleton_resolution_reasons:
        return "success", group_ids[0], sorted(singleton_resolution_reasons)[0]
    return "success", group_ids[0], "required_rcsd_node_group_resolved"


def _resolved_rcsd_group_id(
    *,
    node_id: str,
    raw_group_id: Any,
    row: Mapping[str, Any],
    required_node_count: int,
    rcsdintersection_by_singleton_node_id: Mapping[str, str],
) -> tuple[str, str]:
    group_id = normalize_id(raw_group_id)
    if group_id not in {"0", "-1"}:
        return group_id or "", ""
    if _has_single_strong_rcsd_profile(row) and required_node_count == 1:
        return node_id, "required_rcsd_singleton_node_resolved_from_strong_rcsd_profile"
    if required_node_count == 1 and node_id in rcsdintersection_by_singleton_node_id:
        return node_id, "required_rcsd_singleton_node_resolved_from_rcsdintersection"
    return group_id or "", ""


def _has_single_strong_rcsd_profile(row: Mapping[str, Any]) -> bool:
    profile = _parse_rcsd_profile(row.get("rcsd_profile"))
    return profile.get("A", 0) == 1 and profile.get("B", 0) == 0 and profile.get("C", 0) == 0


def _parse_rcsd_profile(value: Any) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0}
    for part in str(value or "").split("|"):
        key, sep, raw_count = part.partition("=")
        if not sep:
            continue
        key = key.strip().upper()
        if key not in counts:
            continue
        try:
            counts[key] = int(float(str(raw_count).strip()))
        except (TypeError, ValueError):
            counts[key] = 0
    return counts


def _case_required_rcsd_nodes(*, run_root: Path, case_id: str) -> list[str]:
    case_dir = run_root / "cases" / str(case_id)
    docs: list[dict[str, Any]] = []
    for path in [
        case_dir / "step4_event_interpretation.json",
        *sorted((case_dir / "event_units").glob("*/step4_candidates.json")),
        *sorted((case_dir / "event_units").glob("*/step4_evidence_audit.json")),
    ]:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                docs.append(payload)
    values: list[str] = []
    for doc in docs:
        units = doc.get("event_units") if isinstance(doc.get("event_units"), list) else [doc]
        for unit in units:
            if not isinstance(unit, dict):
                continue
            values.extend(_split_values(unit.get("required_rcsd_node")))
            selected_evidence = unit.get("selected_evidence")
            if isinstance(selected_evidence, dict):
                values.extend(_split_values(selected_evidence.get("required_rcsd_node")))
    return _ordered_values(values)


def _is_valid_rcsd_group_id(value: Any) -> bool:
    group_id = normalize_id(value)
    return group_id is not None and group_id not in {"0", "-1"}


def _rcsd_group_indexes(features: Iterable[Any]) -> tuple[dict[str, str], dict[str, tuple[Any, Any]]]:
    group_by_node: dict[str, str] = {}
    point_by_group: dict[str, tuple[Any, Any]] = {}
    point_by_node: dict[str, tuple[Any, Any]] = {}
    for feature in features:
        props = _properties(feature)
        node_id = normalize_id(props.get("id"))
        if node_id is None:
            continue
        group_id = normalize_id(props.get("mainnodeid")) or node_id
        group_by_node[node_id] = group_id
        point = _point_xy(_geometry(feature))
        point_by_node[node_id] = point
        point_by_group.setdefault(node_id, point)
        if node_id == group_id:
            point_by_group[group_id] = point
    for node_id, group_id in group_by_node.items():
        point_by_group.setdefault(group_id, point_by_node.get(node_id, ("", "")))
    return group_by_node, point_by_group


def _rcsd_node_geometry_index(features: Iterable[Any]) -> dict[str, Any]:
    by_node: dict[str, Any] = {}
    for feature in features:
        node_id = normalize_id(_properties(feature).get("id"))
        if node_id is None:
            continue
        geometry = _geometry(feature)
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        by_node[node_id] = geometry
    return by_node


def _rcsdintersection_singleton_index(
    features: Iterable[Any],
    *,
    rcsd_geometry_by_node_id: Mapping[str, Any],
) -> dict[str, str]:
    by_node: dict[str, str] = {}
    ambiguous_nodes: set[str] = set()
    for feature in features:
        props = _properties(feature)
        node_id = _intersection_singleton_node_id(props)
        if node_id is None:
            continue
        node_geometry = rcsd_geometry_by_node_id.get(node_id)
        if node_geometry is None:
            continue
        intersection_geometry = _geometry(feature)
        if not _covers_node(intersection_geometry, node_geometry):
            continue
        intersection_id = normalize_id(props.get("id")) or node_id
        previous = by_node.get(node_id)
        if previous is not None and previous != intersection_id:
            ambiguous_nodes.add(node_id)
            continue
        by_node[node_id] = intersection_id
    for node_id in ambiguous_nodes:
        by_node.pop(node_id, None)
    return by_node


def _intersection_singleton_node_id(props: Mapping[str, Any]) -> str | None:
    node_ids = _intersection_node_ids(props.get("node_ids"))
    return node_ids[0] if len(node_ids) == 1 else None


def _intersection_node_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _ordered_values(
                    normalized
                    for item in parsed
                    for normalized in [normalize_id(item)]
                    if normalized is not None and normalized != "-1"
                )
    return _split_values(value)


def _covers_node(intersection_geometry: Any, node_geometry: Any) -> bool:
    if intersection_geometry is None or node_geometry is None:
        return False
    if getattr(intersection_geometry, "is_empty", False) or getattr(node_geometry, "is_empty", False):
        return False
    try:
        return bool(intersection_geometry.covers(node_geometry))
    except Exception:
        return False


def _patch_closeout_documents(*, run_root: Path, relation_row_count: int, fallback_success_case_ids: list[str]) -> None:
    for path in [run_root / "divmerge_virtual_anchor_surface_summary.json", run_root / "step7_consistency_report.json"]:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if path.name == "divmerge_virtual_anchor_surface_summary.json":
            relation_doc = dict(payload.get("relation_evidence") or {})
            relation_doc["row_count"] = relation_row_count
            relation_doc["fallback_success_count"] = len(fallback_success_case_ids)
            relation_doc["fallback_success_case_ids"] = list(fallback_success_case_ids)
            payload["relation_evidence"] = relation_doc
        else:
            payload["relation_evidence_row_count"] = relation_row_count
            payload["relation_fallback_success_count"] = len(fallback_success_case_ids)
            payload["relation_fallback_success_case_ids"] = list(fallback_success_case_ids)
        write_json(path, payload)


def _properties(feature: Any | None) -> dict[str, Any]:
    if feature is None:
        return {}
    if isinstance(feature, Mapping):
        return dict(feature.get("properties") or {})
    return dict(getattr(feature, "properties", {}) or {})


def _geometry(feature: Any | None) -> Any:
    if feature is None:
        return None
    if isinstance(feature, Mapping):
        return feature.get("geometry")
    return getattr(feature, "geometry", None)


def _feature_id(feature: Any) -> str | None:
    return normalize_id(_properties(feature).get("id"))


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value).replace(",", "|").split("|")
    return [text for item in raw_values for text in [normalize_id(item)] if text is not None and text != "-1"]


def _ordered_values(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value or "").strip()})


def _point_xy(geometry: Any) -> tuple[Any, Any]:
    if geometry is None or getattr(geometry, "is_empty", False):
        return "", ""
    point = geometry if getattr(geometry, "geom_type", "") == "Point" else geometry.representative_point()
    return float(point.x), float(point.y)


def _node_level(props: Mapping[str, Any]) -> int:
    try:
        return int(props.get("grade"))
    except (TypeError, ValueError):
        return -1


def _node_is_highway(props: Mapping[str, Any]) -> int:
    try:
        return int(props.get("closed_con"))
    except (TypeError, ValueError):
        return -1


def _junction_type(kind_2: Any) -> str:
    try:
        value = int(kind_2)
    except (TypeError, ValueError):
        return "unknown"
    return {8: "merge", 16: "diverge", 128: "complex_divmerge"}.get(value, "unknown")


__all__ = [
    "FALLBACK_NODE_VALUE",
    "enrich_t04_relation_evidence_with_fallback",
]
