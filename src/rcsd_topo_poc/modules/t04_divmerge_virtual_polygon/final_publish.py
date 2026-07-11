from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, box
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import _polygon_components
from .case_models import T04CaseResult
from .polygon_assembly import T04Step6Result
from .provenance import provenance_doc
from .support_domain import T04Step5CaseResult


STEP7_BUSINESS_OBJECT = "divmerge_virtual_anchor_surface"
STEP7_SOURCE_MODULE = "T04"
STEP7_SCENE_FAMILY = "divmerge"
STEP7_ACCEPTED_LAYER_NAME = "divmerge_virtual_anchor_surface.gpkg"
STEP7_REJECTED_LAYER_NAME = "divmerge_virtual_anchor_surface_rejected.geojson"
STEP7_SUMMARY_CSV_NAME = "divmerge_virtual_anchor_surface_summary.csv"
STEP7_SUMMARY_JSON_NAME = "divmerge_virtual_anchor_surface_summary.json"
STEP7_AUDIT_LAYER_NAME = "divmerge_virtual_anchor_surface_audit.gpkg"
STEP7_CASE_FINAL_REVIEW_NAME = "final_review.png"
STEP7_REJECTED_INDEX_CSV_NAME = "step7_rejected_index.csv"
STEP7_REJECTED_INDEX_JSON_NAME = "step7_rejected_index.json"
STEP7_CONSISTENCY_REPORT_NAME = "step7_consistency_report.json"
RELATION_EVIDENCE_CSV_NAME = "t04_swsd_rcsd_relation_evidence.csv"
RELATION_EVIDENCE_JSON_NAME = "t04_swsd_rcsd_relation_evidence.json"
STEP7_ALLOWED_TOLERANCE_AREA_M2 = 1e-6
STEP7_REJECT_STUB_BUFFER_M = 2.5
STEP7_ALLOWED_FINAL_STATES = {"accepted", "rejected"}

STEP7_SURFACE_SCENARIO_AUDIT_FIELDS = (
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "reference_point_present",
    "surface_lateral_limit_m",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "post_cleanup_must_cover_ok",
    "post_cleanup_recheck_performed",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_rcsdroad_ids",
    "fallback_rcsdroad_localized",
    "fallback_domain_contained_by_allowed_growth",
    "fallback_overexpansion_detected",
    "fallback_overexpansion_area_m2",
    "divstrip_negative_mask_present",
    "divstrip_negative_overlap_area_m2",
    "forbidden_domain_kept",
    "unit_surface_count",
    "unit_surface_merge_performed",
    "merge_mode",
    "final_case_polygon_component_count",
    "single_connected_case_surface_ok",
    "barrier_separated_case_surface_ok",
    "surface_scenario_missing",
)

STEP7_SURFACE_SCENARIO_SUMMARY_FIELDNAMES = [
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "reference_point_present",
    "surface_lateral_limit_m",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "post_cleanup_must_cover_ok",
    "post_cleanup_recheck_performed",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_rcsdroad_localized",
    "fallback_overexpansion_detected",
    "divstrip_negative_mask_present",
    "forbidden_domain_kept",
    "unit_surface_count",
    "unit_surface_merge_performed",
    "merge_mode",
    "final_case_polygon_component_count",
    "single_connected_case_surface_ok",
    "barrier_separated_case_surface_ok",
]

STEP7_SUMMARY_FIELDNAMES = [
    "case_id",
    "anchor_id",
    "mainnodeid",
    "source_module",
    "scene_family",
    "scene_type",
    "junction_type",
    "kind_2",
    "patch_id",
    "patch_id_source",
    "final_state",
    "unit_count",
    "required_rcsd_node_count",
    "has_c_unit",
    "swsd_relation_type",
    "publish_target",
    "geometry_path",
    "audit_path",
    "review_png_path",
    *STEP7_SURFACE_SCENARIO_SUMMARY_FIELDNAMES,
]

STEP7_REJECTED_INDEX_FIELDNAMES = [
    "case_id",
    "mainnodeid",
    "scene_type",
    "final_state",
    "reject_reason",
    "reject_reason_detail",
    "publish_target",
    "reject_stub_path",
    "reject_index_path",
    "audit_path",
    "review_png_path",
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_overexpansion_detected",
]

RELATION_EVIDENCE_FIELDNAMES = [
    "target_id",
    "case_id",
    "junction_type",
    "scene_type",
    "final_state",
    "swsd_relation_type",
    "required_rcsd_node_ids",
    "semantic_required_rcsd_node_ids",
    "selected_rcsdnode_ids",
    "selected_rcsdroad_ids",
    "rcsd_profile",
    "has_c_unit",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "patch_id",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]


def _dedupe_sorted_text(values: Iterable[str | None]) -> list[str]:
    normalized = {
        str(value).strip()
        for value in values
        if str(value or "").strip()
    }
    return sorted(normalized)


def _pipe_join(values: Iterable[str | None], *, fallback: str = "") -> str:
    parts = _dedupe_sorted_text(values)
    if not parts:
        return fallback
    return "|".join(parts)


def _point_xy(geometry: BaseGeometry | None) -> tuple[float | str, float | str]:
    if geometry is None or geometry.is_empty:
        return "", ""
    point = geometry if getattr(geometry, "geom_type", "") == "Point" else geometry.representative_point()
    return float(point.x), float(point.y)


def _node_level(properties: dict[str, Any]) -> Any:
    value = properties.get("grade")
    return value if value not in (None, "") else -1


def _node_is_highway(properties: dict[str, Any]) -> Any:
    value = properties.get("closed_con")
    return value if value not in (None, "") else -1


def _event_unit_values(case_result: T04CaseResult, field_name: str) -> list[str]:
    values: list[str] = []
    for event_unit in case_result.event_units:
        value = getattr(event_unit, field_name, ()) or ()
        if isinstance(value, str):
            iterable = (value,)
        else:
            iterable = value
        for item in iterable:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)
    return sorted(values, key=sort_patch_key)


def _first_required_rcsd_point(case_result: T04CaseResult) -> tuple[float | str, float | str]:
    for event_unit in case_result.event_units:
        geometry = getattr(event_unit, "required_rcsd_node_geometry", None)
        x, y = _point_xy(geometry)
        if x != "" and y != "":
            return x, y
    return "", ""


def _ids_from_value(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        parsed: Any = None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                parsed = None
        if isinstance(parsed, (list, tuple, set)):
            return tuple(_dedupe_sorted_text(str(item) for item in parsed))
        for separator in ("|", ";", ","):
            text = text.replace(separator, "|")
        return tuple(_dedupe_sorted_text(part.strip(" []'\"") for part in text.split("|")))
    if isinstance(value, (list, tuple, set)):
        return tuple(_dedupe_sorted_text(str(item) for item in value))
    return (str(value).strip(),) if str(value or "").strip() else ()


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None


def _rcsd_road_lookup(case_result: T04CaseResult) -> dict[str, Any]:
    return {
        str(getattr(road, "road_id", "") or "").strip(): road
        for road in getattr(case_result.case_bundle, "rcsd_roads", ()) or ()
        if str(getattr(road, "road_id", "") or "").strip()
    }


def _rcsd_node_lookup(case_result: T04CaseResult) -> dict[str, Any]:
    return {
        str(getattr(node, "node_id", "") or "").strip(): node
        for node in getattr(case_result.case_bundle, "rcsd_nodes", ()) or ()
        if str(getattr(node, "node_id", "") or "").strip()
    }


def _road_endpoint_ids(road: Any) -> tuple[str, ...]:
    return tuple(
        _dedupe_sorted_text(
            (
                str(getattr(road, "snodeid", "") or "").strip(),
                str(getattr(road, "enodeid", "") or "").strip(),
            )
        )
    )


def _incident_rcsdroad_ids_by_node(case_result: T04CaseResult) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for road in getattr(case_result.case_bundle, "rcsd_roads", ()) or ():
        road_id = str(getattr(road, "road_id", "") or "").strip()
        if not road_id:
            continue
        for node_id in _road_endpoint_ids(road):
            result.setdefault(node_id, set()).add(road_id)
    return result


def _node_lid_count(node: Any) -> int:
    properties = getattr(node, "properties", {}) or {}
    return len(_ids_from_value(properties.get("node_lid")))


def _is_reusable_rcsd_semantic_endpoint(
    node: Any,
    *,
    incident_road_ids: set[str],
) -> bool:
    properties = getattr(node, "properties", {}) or {}
    kind = _int_value(getattr(node, "kind", None))
    if kind is None:
        kind = _int_value(properties.get("kind"))
    if kind != 8:
        return False
    return max(len(incident_road_ids), _node_lid_count(node)) >= 3


def _event_unit_fallback_rcsdroad_ids(event_unit: Any) -> tuple[str, ...]:
    values: list[str] = []
    sources = [
        getattr(event_unit, "fallback_rcsdroad_ids", ()) or (),
        (getattr(event_unit, "selected_evidence_summary", {}) or {}).get("fallback_rcsdroad_ids"),
        (getattr(event_unit, "selected_candidate_summary", {}) or {}).get("fallback_rcsdroad_ids"),
        (getattr(event_unit, "positive_rcsd_audit", {}) or {}).get("fallback_rcsdroad_ids"),
    ]
    for source in sources:
        for road_id in _ids_from_value(source):
            if road_id not in values:
                values.append(road_id)
    return tuple(values)


def _event_unit_review_reasons(event_unit: Any) -> tuple[str, ...]:
    values: list[str] = []
    if hasattr(event_unit, "all_review_reasons"):
        try:
            values.extend(str(item) for item in event_unit.all_review_reasons())
        except TypeError:
            pass
    values.extend(str(item) for item in getattr(event_unit, "review_reasons", ()) or ())
    for summary_name in ("selected_evidence_summary", "selected_candidate_summary", "positive_rcsd_audit"):
        summary = getattr(event_unit, summary_name, {}) or {}
        if isinstance(summary, dict):
            values.extend(str(item) for item in summary.get("review_reasons") or ())
    return tuple(_dedupe_sorted_text(values))


def _allows_fallback_endpoint_reuse(event_unit: Any) -> bool:
    reasons = set(_event_unit_review_reasons(event_unit))
    return "road_surface_fork_binding_used" in reasons


def _fallback_rcsdroad_semantic_endpoint_node_id(
    case_result: T04CaseResult,
    event_unit: Any,
) -> str | None:
    if len(getattr(case_result, "event_units", ()) or ()) != 1:
        return None
    if str(getattr(event_unit, "required_rcsd_node", "") or "").strip():
        return None
    if not _allows_fallback_endpoint_reuse(event_unit):
        return None
    fallback_road_ids = _event_unit_fallback_rcsdroad_ids(event_unit)
    if len(fallback_road_ids) != 1:
        return None
    road = _rcsd_road_lookup(case_result).get(fallback_road_ids[0])
    if road is None:
        return None
    nodes_by_id = _rcsd_node_lookup(case_result)
    incident_by_node = _incident_rcsdroad_ids_by_node(case_result)
    reusable_node_ids = [
        node_id
        for node_id in _road_endpoint_ids(road)
        for node in (nodes_by_id.get(node_id),)
        if node is not None
        and _is_reusable_rcsd_semantic_endpoint(
            node,
            incident_road_ids=incident_by_node.get(node_id, set()),
        )
    ]
    if len(reusable_node_ids) != 1:
        return None
    return reusable_node_ids[0]


def _rcsd_node_geometry(case_result: T04CaseResult, node_id: str | None) -> BaseGeometry | None:
    if not node_id:
        return None
    node = _rcsd_node_lookup(case_result).get(str(node_id))
    return getattr(node, "geometry", None) if node is not None else None


def _local_rcsd_node_id(event_unit: Any) -> str | None:
    unit_id = str(getattr(event_unit, "local_rcsd_unit_id", "") or "").strip()
    if not unit_id:
        return None
    parts = unit_id.split(":")
    if len(parts) >= 2 and parts[-2] == "node":
        node_id = parts[-1].strip()
        return node_id or None
    return None


def _relation_handoff_node_id(
    event_unit: Any,
    *,
    case_result: T04CaseResult | None = None,
    swsd_relation_type: str,
) -> str | None:
    required_node = str(getattr(event_unit, "required_rcsd_node", "") or "").strip()
    if (
        required_node
        and swsd_relation_type == "partial"
        and str(getattr(event_unit, "main_evidence_type", "") or "") == "road_surface_fork"
        and not bool(getattr(event_unit, "swsd_junction_present", False))
        and str(getattr(event_unit, "positive_rcsd_consistency_level", "") or "").strip().upper() == "A"
    ):
        local_node_id = _local_rcsd_node_id(event_unit)
        if local_node_id:
            return local_node_id
    if required_node:
        return required_node
    if case_result is None:
        return None
    return _fallback_rcsdroad_semantic_endpoint_node_id(case_result, event_unit)


def _relation_handoff_rcsd_node_ids(
    case_result: T04CaseResult,
    *,
    swsd_relation_type: str,
) -> list[str]:
    return _dedupe_sorted_text(
        _relation_handoff_node_id(
            event_unit,
            case_result=case_result,
            swsd_relation_type=swsd_relation_type,
        )
        for event_unit in case_result.event_units
    )


def _first_relation_handoff_rcsd_point(
    case_result: T04CaseResult,
    *,
    swsd_relation_type: str,
) -> tuple[float | str, float | str]:
    for event_unit in case_result.event_units:
        handoff_node_id = _relation_handoff_node_id(
            event_unit,
            case_result=case_result,
            swsd_relation_type=swsd_relation_type,
        )
        required_node = str(getattr(event_unit, "required_rcsd_node", "") or "").strip()
        rcsd_node_geometry = _rcsd_node_geometry(case_result, handoff_node_id)
        x, y = _point_xy(rcsd_node_geometry)
        if x != "" and y != "":
            return x, y
        geometry_field = (
            "local_rcsd_unit_geometry"
            if handoff_node_id and required_node and handoff_node_id != required_node
            else "required_rcsd_node_geometry"
        )
        x, y = _point_xy(getattr(event_unit, geometry_field, None))
        if x != "" and y != "":
            return x, y
    return _first_required_rcsd_point(case_result)


def _has_ambiguous_rcsd_alignment(case_result: T04CaseResult) -> bool:
    return any(
        str(getattr(event_unit, "rcsd_alignment_type", "") or "") == "ambiguous_rcsd_alignment"
        for event_unit in case_result.event_units
    )


def _t04_relation_state(
    *,
    final_state: str,
    swsd_relation_type: str,
    required_rcsd_node_ids: list[str],
    selected_rcsdnode_ids: list[str],
    selected_rcsdroad_ids: list[str],
    ambiguous_rcsd_alignment: bool,
) -> tuple[str, int, Any]:
    if final_state != "accepted":
        return "geometry_not_accepted", 1, -1
    if ambiguous_rcsd_alignment:
        return "ambiguous_review", 1, -1
    if required_rcsd_node_ids:
        if swsd_relation_type == "offset_fact":
            return "success_offset_fact_with_rcsd_junction", 0, "|".join(required_rcsd_node_ids)
        return "success_required_rcsd_junction", 0, "|".join(required_rcsd_node_ids)
    if selected_rcsdnode_ids or selected_rcsdroad_ids:
        return "rcsd_present_not_junction", 1, -1
    return "no_related_rcsd", 1, -1


def _geometry_summary(geometry: BaseGeometry | None) -> dict[str, Any]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return {
            "present": False,
            "geometry_type": "",
            "area_m2": 0.0,
            "length_m": 0.0,
        }
    return {
        "present": True,
        "geometry_type": str(normalized.geom_type),
        "area_m2": float(getattr(normalized, "area", 0.0) or 0.0),
        "length_m": float(getattr(normalized, "length", 0.0) or 0.0),
    }


def _primary_reject_reason(reject_reasons: tuple[str, ...]) -> str:
    return str(reject_reasons[0]) if reject_reasons else ""


def _text_attr(obj: Any, name: str, default: str = "missing") -> str:
    value = getattr(obj, name, default)
    text = str(value or "").strip()
    return text or default


def _bool_attr(obj: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(obj, name, default))


def _float_attr(obj: Any, name: str, default: float | None = None) -> float | None:
    value = getattr(obj, name, default)
    if value is None:
        return default
    return float(value)


def _tuple_text_attr(obj: Any, name: str) -> tuple[str, ...]:
    value = getattr(obj, name, ()) or ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value if str(item or "").strip())


def derive_step7_surface_scenario_publish_audit(step6_result: T04Step6Result) -> dict[str, Any]:
    return {
        "surface_scenario_type": _text_attr(step6_result, "surface_scenario_type"),
        "section_reference_source": _text_attr(step6_result, "section_reference_source"),
        "surface_generation_mode": _text_attr(step6_result, "surface_generation_mode"),
        "reference_point_present": _bool_attr(step6_result, "reference_point_present"),
        "surface_lateral_limit_m": _float_attr(step6_result, "surface_lateral_limit_m"),
        "post_cleanup_allowed_growth_ok": _bool_attr(step6_result, "post_cleanup_allowed_growth_ok", True),
        "post_cleanup_forbidden_ok": _bool_attr(step6_result, "post_cleanup_forbidden_ok", True),
        "post_cleanup_terminal_cut_ok": _bool_attr(step6_result, "post_cleanup_terminal_cut_ok", True),
        "post_cleanup_lateral_limit_ok": _bool_attr(step6_result, "post_cleanup_lateral_limit_ok", True),
        "post_cleanup_must_cover_ok": _bool_attr(step6_result, "post_cleanup_must_cover_ok", True),
        "post_cleanup_recheck_performed": _bool_attr(step6_result, "post_cleanup_recheck_performed"),
        "no_surface_reference_guard": _bool_attr(step6_result, "no_surface_reference_guard"),
        "final_polygon_suppressed_by_no_surface_reference": _bool_attr(
            step6_result,
            "final_polygon_suppressed_by_no_surface_reference",
        ),
        "fallback_rcsdroad_ids": list(_tuple_text_attr(step6_result, "fallback_rcsdroad_ids")),
        "fallback_rcsdroad_localized": _bool_attr(step6_result, "fallback_rcsdroad_localized"),
        "fallback_domain_contained_by_allowed_growth": _bool_attr(
            step6_result,
            "fallback_domain_contained_by_allowed_growth",
            True,
        ),
        "fallback_overexpansion_detected": _bool_attr(step6_result, "fallback_overexpansion_detected"),
        "fallback_overexpansion_area_m2": _float_attr(step6_result, "fallback_overexpansion_area_m2", 0.0),
        "divstrip_negative_mask_present": _bool_attr(step6_result, "divstrip_negative_mask_present"),
        "divstrip_negative_overlap_area_m2": _float_attr(step6_result, "divstrip_negative_overlap_area_m2", 0.0),
        "forbidden_domain_kept": _bool_attr(step6_result, "forbidden_domain_kept"),
        "unit_surface_count": int(getattr(step6_result, "unit_surface_count", 0) or 0),
        "unit_surface_merge_performed": _bool_attr(step6_result, "unit_surface_merge_performed"),
        "merge_mode": _text_attr(step6_result, "merge_mode", "case_level_assembly"),
        "final_case_polygon_component_count": int(
            getattr(step6_result, "final_case_polygon_component_count", 0) or 0
        ),
        "single_connected_case_surface_ok": _bool_attr(step6_result, "single_connected_case_surface_ok"),
        "barrier_separated_case_surface_ok": _bool_attr(
            step6_result,
            "barrier_separated_case_surface_ok",
        ),
        "surface_scenario_missing": _bool_attr(step6_result, "surface_scenario_missing", True),
    }


def _step6_guard_feature_properties(step6_guard_audit: dict[str, Any]) -> dict[str, Any]:
    properties = {
        key: step6_guard_audit.get(key)
        for key in STEP7_SURFACE_SCENARIO_AUDIT_FIELDS
        if key in step6_guard_audit
    }
    properties["fallback_rcsdroad_ids"] = "|".join(
        str(item) for item in step6_guard_audit.get("fallback_rcsdroad_ids", []) if str(item or "").strip()
    )
    return properties


def _guard_doc_from_artifact(artifact: Any) -> dict[str, Any]:
    audit_doc = dict(getattr(artifact, "audit_doc", {}) or {})
    guard_doc = audit_doc.get("step6_guard_audit")
    if isinstance(guard_doc, dict):
        return dict(guard_doc)
    return {
        key: audit_doc.get(key)
        for key in STEP7_SURFACE_SCENARIO_AUDIT_FIELDS
        if key in audit_doc
    }


def collect_surface_scenario_summary_counts(artifacts: Iterable[Any]) -> dict[str, Any]:
    ordered_artifacts = list(artifacts)
    guard_docs = [_guard_doc_from_artifact(item) for item in ordered_artifacts]
    final_state_counts = Counter(str(getattr(item, "final_state", "") or "missing") for item in ordered_artifacts)
    surface_scenario_type_counts = Counter(
        str(doc.get("surface_scenario_type") or "missing") for doc in guard_docs
    )
    section_reference_source_counts = Counter(
        str(doc.get("section_reference_source") or "missing") for doc in guard_docs
    )
    surface_generation_mode_counts = Counter(
        str(doc.get("surface_generation_mode") or "missing") for doc in guard_docs
    )
    no_surface_reference_case_ids = [
        str(getattr(artifact, "case_id", ""))
        for artifact, doc in zip(ordered_artifacts, guard_docs)
        if doc.get("surface_scenario_type") == "no_surface_reference"
        or bool(doc.get("no_surface_reference_guard"))
    ]
    return {
        "step7_final_state_counts": dict(sorted(final_state_counts.items())),
        "surface_scenario_type_counts": dict(sorted(surface_scenario_type_counts.items())),
        "section_reference_source_counts": dict(sorted(section_reference_source_counts.items())),
        "surface_generation_mode_counts": dict(sorted(surface_generation_mode_counts.items())),
        "post_cleanup_allowed_growth_fail_count": sum(
            1 for doc in guard_docs if doc.get("post_cleanup_allowed_growth_ok") is False
        ),
        "post_cleanup_forbidden_fail_count": sum(
            1 for doc in guard_docs if doc.get("post_cleanup_forbidden_ok") is False
        ),
        "post_cleanup_terminal_cut_fail_count": sum(
            1 for doc in guard_docs if doc.get("post_cleanup_terminal_cut_ok") is False
        ),
        "no_surface_reference_count": len(no_surface_reference_case_ids),
        "no_surface_reference_case_ids": sorted(no_surface_reference_case_ids, key=sort_patch_key),
        "fallback_overexpansion_count": sum(
            1 for doc in guard_docs if bool(doc.get("fallback_overexpansion_detected"))
        ),
        "divstrip_negative_mask_present_count": sum(
            1 for doc in guard_docs if bool(doc.get("divstrip_negative_mask_present"))
        ),
    }


def _step7_guard_mapping_issues(artifacts: Iterable[T04Step7CaseArtifact]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for artifact in artifacts:
        guard_doc = _guard_doc_from_artifact(artifact)
        reject_reasons = set(str(reason) for reason in artifact.reject_reasons)
        expected_checks = [
            ("post_cleanup_allowed_growth_ok", "allowed_growth_conflict"),
            ("post_cleanup_forbidden_ok", "forbidden_conflict"),
            ("post_cleanup_terminal_cut_ok", "terminal_cut_conflict"),
            ("post_cleanup_lateral_limit_ok", "allowed_growth_conflict"),
            ("post_cleanup_must_cover_ok", "hard_must_cover_disconnected"),
        ]
        for field_name, expected_reason in expected_checks:
            if guard_doc.get(field_name) is False and expected_reason not in reject_reasons:
                issues.append(
                    {
                        "case_id": artifact.case_id,
                        "field": field_name,
                        "expected_reject_reason": expected_reason,
                    }
                )
        if bool(guard_doc.get("fallback_overexpansion_detected")) and "fallback_overexpansion_detected" not in reject_reasons:
            issues.append(
                {
                    "case_id": artifact.case_id,
                    "field": "fallback_overexpansion_detected",
                    "expected_reject_reason": "fallback_overexpansion_detected",
                }
            )
        if bool(guard_doc.get("no_surface_reference_guard")) and "no_surface_reference" not in reject_reasons:
            issues.append(
                {
                    "case_id": artifact.case_id,
                    "field": "no_surface_reference_guard",
                    "expected_reject_reason": "no_surface_reference",
                }
            )
        if (
            guard_doc.get("single_connected_case_surface_ok") is False
            and "multi_component_result" not in reject_reasons
        ):
            issues.append(
                {
                    "case_id": artifact.case_id,
                    "field": "single_connected_case_surface_ok",
                    "expected_reject_reason": "multi_component_result",
                }
            )
    return issues


def _flat_review_png_path(run_root: Path, case_id: str) -> Path:
    return run_root / "step4_review_flat" / f"case__{case_id}__final_review.png"


def _resolved_review_png_path(run_root: Path, *, case_id: str, case_review_png_path: str) -> str:
    flat_path = _flat_review_png_path(run_root, case_id)
    if flat_path.is_file():
        return str(flat_path)
    return case_review_png_path


def _related_mainnodeids_text(case_result: T04CaseResult) -> str:
    related = _dedupe_sorted_text(case_result.base_context.topology_skeleton.chain_context.related_mainnodeids)
    if not related:
        return str(case_result.case_spec.mainnodeid)
    return "|".join(related)


def _scene_type(case_result: T04CaseResult) -> str:
    representative_kind_2 = case_result.admission.source_kind_2
    if representative_kind_2 == 128:
        return "complex_divmerge"
    if bool(case_result.base_context.topology_skeleton.chain_context.is_in_continuous_chain):
        return "complex_divmerge"
    if representative_kind_2 == 16:
        return "diverge"
    if representative_kind_2 == 8:
        return "merge"
    return "complex_divmerge"


def _swsd_core_geometry(case_result: T04CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(
            event_unit.localized_evidence_core_geometry
            for event_unit in case_result.event_units
            if event_unit.localized_evidence_core_geometry is not None
        )
    )


def _swsd_relation_type(
    *,
    final_case_polygon: BaseGeometry | None,
    case_result: T04CaseResult,
    final_state: str,
) -> str:
    swsd_core_geometry = _swsd_core_geometry(case_result)
    if swsd_core_geometry is None or swsd_core_geometry.is_empty:
        return "unknown" if final_state == "rejected" else "offset_fact"
    normalized_polygon = _normalize_geometry(final_case_polygon)
    if normalized_polygon is None or normalized_polygon.is_empty:
        return "unknown" if final_state == "rejected" else "offset_fact"
    if normalized_polygon.buffer(1e-6).covers(swsd_core_geometry):
        return "covering"
    if normalized_polygon.intersects(swsd_core_geometry):
        return "partial"
    return "offset_fact"


def _required_rcsd_node_ids(case_result: T04CaseResult) -> list[str]:
    return _dedupe_sorted_text(
        event_unit.required_rcsd_node
        for event_unit in case_result.event_units
    )


def _rcsd_profile(case_result: T04CaseResult) -> str:
    counts = {"A": 0, "B": 0, "C": 0}
    for event_unit in case_result.event_units:
        level = str(event_unit.positive_rcsd_consistency_level or "").strip().upper()
        if level in counts:
            counts[level] += 1
    return f"A={counts['A']}|B={counts['B']}|C={counts['C']}"


def _reject_stub_geometry(case_result: T04CaseResult) -> BaseGeometry | None:
    preferred = _normalize_geometry(
        _union_geometry(
            event_unit.selected_candidate_region_geometry
            for event_unit in case_result.event_units
            if event_unit.selected_candidate_region_geometry is not None
        )
    )
    if preferred is not None and not preferred.is_empty:
        return preferred

    fallback = _normalize_geometry(
        _union_geometry(
            event_unit.localized_evidence_core_geometry
            for event_unit in case_result.event_units
            if event_unit.localized_evidence_core_geometry is not None
        )
    )
    if fallback is None or fallback.is_empty:
        fallback = _normalize_geometry(
            _union_geometry(
                event_unit.fact_reference_point
                for event_unit in case_result.event_units
                if event_unit.fact_reference_point is not None
            )
        )
    if fallback is None or fallback.is_empty:
        return None

    buffered = _normalize_geometry(fallback.buffer(STEP7_REJECT_STUB_BUFFER_M))
    if buffered is not None and not buffered.is_empty:
        return buffered

    bounds = getattr(fallback, "bounds", None)
    if not bounds:
        return None
    min_x, min_y, max_x, max_y = bounds
    pad = STEP7_REJECT_STUB_BUFFER_M
    return _normalize_geometry(box(min_x - pad, min_y - pad, max_x + pad, max_y + pad))


def _allowed_outside_area_m2(
    final_case_polygon: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None,
) -> float:
    normalized_polygon = _normalize_geometry(final_case_polygon)
    normalized_allowed = _normalize_geometry(allowed_geometry)
    if normalized_polygon is None or normalized_polygon.is_empty or normalized_allowed is None or normalized_allowed.is_empty:
        return 0.0
    return float(normalized_polygon.difference(normalized_allowed).area)


def _reject_reasons(
    *,
    step6_result: T04Step6Result,
    allowed_outside_area_m2: float,
) -> tuple[str, ...]:
    reasons: list[str] = []
    final_case_polygon = _normalize_geometry(step6_result.final_case_polygon)
    if final_case_polygon is None or final_case_polygon.is_empty:
        reasons.append("final_polygon_missing")
    if (
        getattr(step6_result, "no_surface_reference_guard", False)
        or getattr(step6_result, "final_polygon_suppressed_by_no_surface_reference", False)
        or getattr(step6_result, "surface_scenario_type", "") == "no_surface_reference"
        or getattr(step6_result, "surface_generation_mode", "") == "no_surface"
    ):
        reasons.append("final_polygon_missing")
        reasons.append("no_surface_reference")
        if getattr(step6_result, "final_polygon_suppressed_by_no_surface_reference", False):
            reasons.append("final_polygon_suppressed_by_no_surface_reference")
    if step6_result.component_count != 1:
        reasons.append("multi_component_result")
    if not getattr(step6_result, "single_connected_case_surface_ok", step6_result.component_count == 1):
        reasons.append("multi_component_result")
    if not step6_result.hard_must_cover_ok:
        reasons.append("hard_must_cover_disconnected")
    if not getattr(step6_result, "post_cleanup_must_cover_ok", True):
        reasons.append("hard_must_cover_disconnected")
    if not step6_result.b_node_target_covered:
        reasons.append("b_node_not_covered")
    if step6_result.forbidden_overlap_area_m2 > STEP7_ALLOWED_TOLERANCE_AREA_M2:
        reasons.append("forbidden_conflict")
    if not getattr(step6_result, "post_cleanup_forbidden_ok", True):
        reasons.append("forbidden_conflict")
    if allowed_outside_area_m2 > STEP7_ALLOWED_TOLERANCE_AREA_M2:
        reasons.append("allowed_growth_conflict")
    if not getattr(step6_result, "post_cleanup_allowed_growth_ok", True):
        reasons.append("allowed_growth_conflict")
    if not getattr(step6_result, "post_cleanup_lateral_limit_ok", True):
        reasons.append("allowed_growth_conflict")
        reasons.append("lateral_limit_conflict")
    if getattr(step6_result, "fallback_overexpansion_detected", False):
        reasons.append("allowed_growth_conflict")
        reasons.append("fallback_overexpansion_detected")
    if step6_result.cut_violation:
        reasons.append("terminal_cut_conflict")
    if not getattr(step6_result, "post_cleanup_terminal_cut_ok", True):
        reasons.append("terminal_cut_conflict")
    if step6_result.unexpected_hole_count > 0:
        reasons.append("unexpected_hole_present")
    if step6_result.assembly_state == "assembly_failed":
        reasons.extend(step6_result.review_reasons)
    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        text = str(reason).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return tuple(deduped)


def derive_step7_reject_reason_from_step6_guards(
    step6_result: T04Step6Result,
    *,
    allowed_outside_area_m2: float = 0.0,
) -> dict[str, Any]:
    reject_reasons = _reject_reasons(
        step6_result=step6_result,
        allowed_outside_area_m2=allowed_outside_area_m2,
    )
    return {
        "final_state": "accepted" if not reject_reasons else "rejected",
        "reject_reasons": list(reject_reasons),
        "reject_reason": _primary_reject_reason(reject_reasons),
        "reject_reason_detail": "|".join(reject_reasons),
    }


@dataclass(frozen=True)
class T04Step7CaseArtifact:
    case_id: str
    final_state: str
    reject_reasons: tuple[str, ...]
    publish_target: str
    accepted_feature: dict[str, Any] | None
    rejected_feature: dict[str, Any] | None
    audit_feature: dict[str, Any] | None
    summary_row: dict[str, Any]
    status_doc: dict[str, Any]
    audit_doc: dict[str, Any]
    reject_index_doc: dict[str, Any]
    reject_stub_feature: dict[str, Any] | None
    relation_evidence_row: dict[str, Any]


def build_step7_case_artifact(
    *,
    run_root: Path,
    case_dir: Path,
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
    step6_result: T04Step6Result,
) -> T04Step7CaseArtifact:
    final_case_polygon = _normalize_geometry(step6_result.final_case_polygon)
    reject_stub_geometry = _reject_stub_geometry(case_result)
    allowed_outside_area_m2 = _allowed_outside_area_m2(
        final_case_polygon,
        step5_result.case_allowed_growth_domain,
    )
    reject_reasons = _reject_reasons(
        step6_result=step6_result,
        allowed_outside_area_m2=allowed_outside_area_m2,
    )
    final_state = "accepted" if not reject_reasons else "rejected"
    publish_target = "accepted_layer" if final_state == "accepted" else "rejected_index"
    step6_guard_audit = derive_step7_surface_scenario_publish_audit(step6_result)
    step6_guard_properties = _step6_guard_feature_properties(step6_guard_audit)

    required_rcsd_node_ids = _required_rcsd_node_ids(case_result)
    required_rcsd_node_ids_text = "|".join(required_rcsd_node_ids)
    scene_type = _scene_type(case_result)
    source_kind_2 = case_result.admission.source_kind_2
    junction_type = scene_type
    local_context = getattr(case_result.base_context, "local_context", None)
    patch_id = getattr(local_context, "current_patch_id", None)
    patch_id_source = "stage4_local_context.current_patch_id" if patch_id is not None else "unresolved"
    swsd_relation_type = _swsd_relation_type(
        final_case_polygon=final_case_polygon,
        case_result=case_result,
        final_state=final_state,
    )
    relation_handoff_rcsd_node_ids = _relation_handoff_rcsd_node_ids(
        case_result,
        swsd_relation_type=swsd_relation_type,
    )
    relation_handoff_rcsd_node_ids_text = "|".join(relation_handoff_rcsd_node_ids)
    anchor_id = case_result.case_spec.case_id
    mainnodeid = case_result.case_spec.mainnodeid
    related_mainnodeids_text = _related_mainnodeids_text(case_result)
    rcsd_profile = _rcsd_profile(case_result)
    selected_rcsdnode_ids = _event_unit_values(case_result, "selected_rcsdnode_ids")
    selected_rcsdroad_ids = _event_unit_values(case_result, "selected_rcsdroad_ids")
    has_c_unit = any(
        str(event_unit.positive_rcsd_consistency_level or "").strip().upper() == "C"
        for event_unit in case_result.event_units
    )
    hole_valid = step6_result.unexpected_hole_count == 0
    reject_reason = _primary_reject_reason(reject_reasons)
    reject_reason_detail = "|".join(reject_reasons)
    review_png_path = case_dir / STEP7_CASE_FINAL_REVIEW_NAME
    accepted_layer_path = run_root / STEP7_ACCEPTED_LAYER_NAME
    rejected_layer_path = run_root / STEP7_REJECTED_LAYER_NAME
    audit_layer_path = run_root / STEP7_AUDIT_LAYER_NAME
    case_reject_stub_path = case_dir / "reject_stub.geojson"
    case_reject_index_path = case_dir / "reject_index.json"
    case_step7_audit_path = case_dir / "step7_audit.json"

    unit_states_rollup = {
        "unit_count": len(case_result.event_units),
        "step4_review_state_counts": {
            state: sum(1 for event_unit in case_result.event_units if event_unit.review_state == state)
            for state in ("STEP4_OK", "STEP4_REVIEW", "STEP4_FAIL")
        },
        "rcsd_profile": rcsd_profile,
        "has_c_unit": has_c_unit,
    }

    status_doc = {
        "case_id": case_result.case_spec.case_id,
        "final_state": final_state,
        "reject_reasons": list(reject_reasons),
        "unit_states_rollup": unit_states_rollup,
        "published_layer_target": publish_target,
        "step6_guard_audit": step6_guard_audit,
        **step6_guard_audit,
    }
    audit_doc = {
        "case_id": case_result.case_spec.case_id,
        "assembly_state": step6_result.assembly_state,
        "step6_guard_audit": step6_guard_audit,
        "hard_gate_checks": {
            "has_final_case_polygon": bool(final_case_polygon is not None and not final_case_polygon.is_empty),
            "single_component": step6_result.component_count == 1,
            "hard_must_cover_ok": step6_result.hard_must_cover_ok,
            "b_node_target_covered": step6_result.b_node_target_covered,
            "forbidden_overlap_ok": step6_result.forbidden_overlap_area_m2 <= STEP7_ALLOWED_TOLERANCE_AREA_M2,
            "allowed_growth_ok": allowed_outside_area_m2 <= STEP7_ALLOWED_TOLERANCE_AREA_M2,
            "cut_violation_free": not step6_result.cut_violation,
            "hole_valid": hole_valid,
            "post_cleanup_allowed_growth_ok": step6_guard_audit["post_cleanup_allowed_growth_ok"],
            "post_cleanup_forbidden_ok": step6_guard_audit["post_cleanup_forbidden_ok"],
            "post_cleanup_terminal_cut_ok": step6_guard_audit["post_cleanup_terminal_cut_ok"],
            "post_cleanup_lateral_limit_ok": step6_guard_audit["post_cleanup_lateral_limit_ok"],
            "post_cleanup_must_cover_ok": step6_guard_audit["post_cleanup_must_cover_ok"],
            "post_cleanup_recheck_performed": step6_guard_audit["post_cleanup_recheck_performed"],
            "no_surface_reference_guard": step6_guard_audit["no_surface_reference_guard"],
            "fallback_overexpansion_detected": step6_guard_audit["fallback_overexpansion_detected"],
        },
        "must_cover_coverage": {
            "hard_must_cover_ok": step6_result.hard_must_cover_ok,
            "b_node_target_covered": step6_result.b_node_target_covered,
            "hard_seed_geometry": _geometry_summary(step6_result.hard_seed_geometry),
            "weak_seed_geometry": _geometry_summary(step6_result.weak_seed_geometry),
        },
        "forbidden_overlap_check": {
            "forbidden_overlap_area_m2": step6_result.forbidden_overlap_area_m2,
            "allowed_outside_area_m2": allowed_outside_area_m2,
        },
        "cut_constraint_check": {
            "cut_violation": step6_result.cut_violation,
            "final_case_cut_lines": _geometry_summary(step6_result.final_case_cut_lines),
        },
        "hole_validity_check": {
            "hole_valid": hole_valid,
            "business_hole_count": step6_result.business_hole_count,
            "unexpected_hole_count": step6_result.unexpected_hole_count,
            "final_case_holes": _geometry_summary(step6_result.final_case_holes),
        },
        "publish_target": publish_target,
        "final_publish_outputs": {
            "accepted_layer_path": str(accepted_layer_path),
            "rejected_layer_path": str(rejected_layer_path),
            "audit_layer_path": str(audit_layer_path),
            "case_reject_stub_path": str(case_reject_stub_path),
            "case_reject_index_path": str(case_reject_index_path),
            "case_final_review_png_path": str(review_png_path),
        },
        "reject_reasons": list(reject_reasons),
        **step6_guard_audit,
    }
    reject_index_doc = {
        "case_id": case_result.case_spec.case_id,
        "final_state": final_state,
        "reject_reason": reject_reason,
        "reject_reason_detail": reject_reason_detail,
        "reject_stub_path": str(case_reject_stub_path),
        "published_layer_target": publish_target,
        **step6_guard_audit,
    }

    accepted_feature = None
    if final_state == "accepted" and final_case_polygon is not None and not final_case_polygon.is_empty:
        accepted_feature = {
            "properties": {
                "anchor_id": anchor_id,
                "case_id": case_result.case_spec.case_id,
                "mainnodeid": mainnodeid,
                "related_mainnodeids": related_mainnodeids_text,
                "business_object": STEP7_BUSINESS_OBJECT,
                "source_module": STEP7_SOURCE_MODULE,
                "scene_family": STEP7_SCENE_FAMILY,
                "scene_type": scene_type,
                "junction_type": junction_type,
                "kind_2": source_kind_2,
                "patch_id": patch_id,
                "patch_id_source": patch_id_source,
                "final_state": "accepted",
                "swsd_relation_type": swsd_relation_type,
                "component_count": step6_result.component_count,
                "hole_count": step6_result.business_hole_count,
                "area_m2": float(final_case_polygon.area),
                "perimeter_m": float(final_case_polygon.length),
                **step6_guard_properties,
            },
            "geometry": final_case_polygon,
        }

    rejected_feature = None
    if final_state == "rejected":
        rejected_feature = {
            "properties": {
                "anchor_id": anchor_id,
                "case_id": case_result.case_spec.case_id,
                "mainnodeid": mainnodeid,
                "related_mainnodeids": related_mainnodeids_text,
                "business_object": STEP7_BUSINESS_OBJECT,
                "source_module": STEP7_SOURCE_MODULE,
                "scene_family": STEP7_SCENE_FAMILY,
                "scene_type": scene_type,
                "junction_type": junction_type,
                "kind_2": source_kind_2,
                "patch_id": patch_id,
                "patch_id_source": patch_id_source,
                "final_state": "rejected",
                "reject_reason": reject_reason,
                "reject_reason_detail": reject_reason_detail,
                "unit_count": len(case_result.event_units),
                "required_rcsd_node_ids": required_rcsd_node_ids_text,
                "rcsd_profile": rcsd_profile,
                "swsd_relation_type": swsd_relation_type,
                **step6_guard_properties,
            },
            "geometry": reject_stub_geometry,
        }

    audit_feature_geometry = (
        final_case_polygon
        if final_state == "accepted"
        else reject_stub_geometry
    )
    audit_feature = {
        "properties": {
            "anchor_id": anchor_id,
            "case_id": case_result.case_spec.case_id,
            "unit_count": len(case_result.event_units),
            "fact_reference_count": sum(1 for event_unit in case_result.event_units if event_unit.fact_reference_point is not None),
            "required_rcsd_node_ids": required_rcsd_node_ids_text,
            "required_rcsd_node_count": len(required_rcsd_node_ids),
            "rcsd_profile": rcsd_profile,
            "has_c_unit": has_c_unit,
            "hard_must_cover_ok": step6_result.hard_must_cover_ok,
            "forbidden_overlap": step6_result.forbidden_overlap_area_m2 > STEP7_ALLOWED_TOLERANCE_AREA_M2,
            "cut_violation": step6_result.cut_violation,
            "hole_valid": hole_valid,
            "reject_reason": reject_reason,
            "reject_reason_detail": reject_reason_detail,
            "publish_target": publish_target,
            **step6_guard_properties,
        },
        "geometry": audit_feature_geometry,
    }

    geometry_path = (
        str(accepted_layer_path)
        if final_state == "accepted"
        else str(case_reject_stub_path if reject_stub_geometry is not None else case_reject_index_path)
    )
    summary_row = {
        "case_id": case_result.case_spec.case_id,
        "anchor_id": anchor_id,
        "mainnodeid": mainnodeid,
        "source_module": STEP7_SOURCE_MODULE,
        "scene_family": STEP7_SCENE_FAMILY,
        "scene_type": scene_type,
        "junction_type": junction_type,
        "kind_2": source_kind_2,
        "patch_id": patch_id,
        "patch_id_source": patch_id_source,
        "final_state": final_state,
        "unit_count": len(case_result.event_units),
        "required_rcsd_node_count": len(required_rcsd_node_ids),
        "has_c_unit": has_c_unit,
        "swsd_relation_type": swsd_relation_type,
        "publish_target": publish_target,
        "geometry_path": geometry_path,
        "audit_path": str(case_step7_audit_path),
        "review_png_path": str(review_png_path),
        **{
            key: step6_guard_properties.get(key)
            for key in STEP7_SURFACE_SCENARIO_SUMMARY_FIELDNAMES
        },
    }
    representative_properties = dict(case_result.case_bundle.representative_node.properties)
    swsd_point_x, swsd_point_y = _point_xy(case_result.case_bundle.representative_node.geometry)
    rcsd_point_x, rcsd_point_y = _first_relation_handoff_rcsd_point(
        case_result,
        swsd_relation_type=swsd_relation_type,
    )
    relation_state, status_suggested, base_id_candidate = _t04_relation_state(
        final_state=final_state,
        swsd_relation_type=swsd_relation_type,
        required_rcsd_node_ids=relation_handoff_rcsd_node_ids,
        selected_rcsdnode_ids=selected_rcsdnode_ids,
        selected_rcsdroad_ids=selected_rcsdroad_ids,
        ambiguous_rcsd_alignment=_has_ambiguous_rcsd_alignment(case_result),
    )
    relation_evidence_row = {
        "target_id": mainnodeid or case_result.admission.representative_node_id,
        "case_id": case_result.case_spec.case_id,
        "junction_type": junction_type,
        "scene_type": scene_type,
        "final_state": final_state,
        "swsd_relation_type": swsd_relation_type,
        "required_rcsd_node_ids": relation_handoff_rcsd_node_ids_text,
        "semantic_required_rcsd_node_ids": required_rcsd_node_ids_text,
        "selected_rcsdnode_ids": "|".join(selected_rcsdnode_ids),
        "selected_rcsdroad_ids": "|".join(selected_rcsdroad_ids),
        "rcsd_profile": rcsd_profile,
        "has_c_unit": int(has_c_unit),
        "surface_candidate_present": int(final_state == "accepted"),
        "base_id_candidate": base_id_candidate,
        "status_suggested": status_suggested,
        "relation_state": relation_state,
        "reason": reject_reason_detail or relation_state,
        "level": _node_level(representative_properties),
        "is_highway": _node_is_highway(representative_properties),
        "patch_id": patch_id,
        "swsd_point_x": swsd_point_x,
        "swsd_point_y": swsd_point_y,
        "rcsd_point_x": rcsd_point_x if status_suggested == 0 else "",
        "rcsd_point_y": rcsd_point_y if status_suggested == 0 else "",
    }
    reject_stub_feature = (
        {
            "properties": {
                "case_id": case_result.case_spec.case_id,
                "final_state": final_state,
                "reject_reason": reject_reason,
                "reject_reason_detail": reject_reason_detail,
                "publish_target": publish_target,
            },
            "geometry": reject_stub_geometry,
        }
        if final_state == "rejected" and reject_stub_geometry is not None
        else None
    )

    return T04Step7CaseArtifact(
        case_id=case_result.case_spec.case_id,
        final_state=final_state,
        reject_reasons=reject_reasons,
        publish_target=publish_target,
        accepted_feature=accepted_feature,
        rejected_feature=rejected_feature,
        audit_feature=audit_feature,
        summary_row=summary_row,
        status_doc=status_doc,
        audit_doc=audit_doc,
        reject_index_doc=reject_index_doc,
        reject_stub_feature=reject_stub_feature,
        relation_evidence_row=relation_evidence_row,
    )


def write_step7_case_outputs(
    *,
    case_dir: Path,
    artifact: T04Step7CaseArtifact,
    provenance: dict[str, Any] | None = None,
) -> None:
    trace = {} if provenance is None else dict(provenance)
    write_json(case_dir / "step7_status.json", {**artifact.status_doc, **trace})
    write_json(case_dir / "step7_audit.json", {**artifact.audit_doc, **trace})
    if artifact.final_state == "rejected":
        write_json(case_dir / "reject_index.json", {**artifact.reject_index_doc, **trace})
        if artifact.reject_stub_feature is not None:
            write_vector(
                case_dir / "reject_stub.geojson",
                [artifact.reject_stub_feature],
                crs_text="EPSG:3857",
            )


def write_step7_batch_outputs(
    *,
    run_root: Path,
    artifacts: list[T04Step7CaseArtifact],
    input_dataset_id: str | None = None,
    review_outputs_enabled: bool = True,
) -> dict[str, Any]:
    from .final_publish_batch import write_step7_batch_outputs as _write_step7_batch_outputs

    return _write_step7_batch_outputs(
        run_root=run_root,
        artifacts=artifacts,
        input_dataset_id=input_dataset_id,
        review_outputs_enabled=review_outputs_enabled,
    )


__all__ = [
    "STEP7_CASE_FINAL_REVIEW_NAME",
    "T04Step7CaseArtifact",
    "build_step7_case_artifact",
    "collect_surface_scenario_summary_counts",
    "derive_step7_reject_reason_from_step6_guards",
    "derive_step7_surface_scenario_publish_audit",
    "write_step7_batch_outputs",
    "write_step7_case_outputs",
]
