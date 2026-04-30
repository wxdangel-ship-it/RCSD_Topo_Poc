from __future__ import annotations

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
]

STEP7_SUMMARY_FIELDNAMES = [
    "case_id",
    "anchor_id",
    "mainnodeid",
    "source_module",
    "scene_family",
    "scene_type",
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
        if guard_doc.get("single_connected_case_surface_ok") is False and "multi_component_result" not in reject_reasons:
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
    swsd_relation_type = _swsd_relation_type(
        final_case_polygon=final_case_polygon,
        case_result=case_result,
        final_state=final_state,
    )
    anchor_id = case_result.case_spec.case_id
    mainnodeid = case_result.case_spec.mainnodeid
    related_mainnodeids_text = _related_mainnodeids_text(case_result)
    rcsd_profile = _rcsd_profile(case_result)
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
            write_vector(case_dir / "reject_stub.geojson", [artifact.reject_stub_feature])


def write_step7_batch_outputs(
    *,
    run_root: Path,
    artifacts: list[T04Step7CaseArtifact],
    input_dataset_id: str | None = None,
) -> dict[str, Any]:
    batch_provenance = provenance_doc(input_dataset_id=input_dataset_id)
    ordered_artifacts = sorted(artifacts, key=lambda item: sort_patch_key(item.case_id))
    accepted_features = [item.accepted_feature for item in ordered_artifacts if item.accepted_feature is not None]
    rejected_features = [item.rejected_feature for item in ordered_artifacts if item.rejected_feature is not None]
    audit_features = [item.audit_feature for item in ordered_artifacts if item.audit_feature is not None]
    summary_rows = []
    for item in ordered_artifacts:
        row = dict(item.summary_row)
        row["review_png_path"] = _resolved_review_png_path(
            run_root,
            case_id=item.case_id,
            case_review_png_path=str(item.summary_row["review_png_path"]),
        )
        summary_rows.append(row)
    surface_scenario_summary_counts = collect_surface_scenario_summary_counts(ordered_artifacts)

    accepted_path = run_root / STEP7_ACCEPTED_LAYER_NAME
    rejected_path = run_root / STEP7_REJECTED_LAYER_NAME
    audit_path = run_root / STEP7_AUDIT_LAYER_NAME
    summary_csv_path = run_root / STEP7_SUMMARY_CSV_NAME
    summary_json_path = run_root / STEP7_SUMMARY_JSON_NAME
    rejected_index_csv_path = run_root / STEP7_REJECTED_INDEX_CSV_NAME
    rejected_index_json_path = run_root / STEP7_REJECTED_INDEX_JSON_NAME
    consistency_report_path = run_root / STEP7_CONSISTENCY_REPORT_NAME

    write_vector(accepted_path, accepted_features)
    write_vector(rejected_path, rejected_features)
    write_vector(audit_path, audit_features)
    write_csv(summary_csv_path, summary_rows, STEP7_SUMMARY_FIELDNAMES)
    write_json(
        summary_json_path,
        {
            **batch_provenance,
            "business_object": STEP7_BUSINESS_OBJECT,
            "row_count": len(summary_rows),
            "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
            "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
            **surface_scenario_summary_counts,
            "rows": summary_rows,
        },
    )
    rejected_index_rows = [
        {
            "case_id": item.case_id,
            "mainnodeid": item.summary_row["mainnodeid"],
            "scene_type": item.summary_row["scene_type"],
            "final_state": item.final_state,
            "reject_reason": _primary_reject_reason(item.reject_reasons),
            "reject_reason_detail": "|".join(item.reject_reasons),
            "publish_target": item.publish_target,
            "reject_stub_path": str(run_root / "cases" / item.case_id / "reject_stub.geojson"),
            "reject_index_path": str(run_root / "cases" / item.case_id / "reject_index.json"),
            "audit_path": item.summary_row["audit_path"],
            "review_png_path": _resolved_review_png_path(
                run_root,
                case_id=item.case_id,
                case_review_png_path=str(item.summary_row["review_png_path"]),
            ),
            "surface_scenario_type": item.summary_row.get("surface_scenario_type", "missing"),
            "section_reference_source": item.summary_row.get("section_reference_source", "missing"),
            "surface_generation_mode": item.summary_row.get("surface_generation_mode", "missing"),
            "no_surface_reference_guard": item.summary_row.get("no_surface_reference_guard", False),
            "final_polygon_suppressed_by_no_surface_reference": item.summary_row.get(
                "final_polygon_suppressed_by_no_surface_reference",
                False,
            ),
            "fallback_overexpansion_detected": item.summary_row.get("fallback_overexpansion_detected", False),
        }
        for item in ordered_artifacts
        if item.final_state == "rejected"
    ]
    write_csv(rejected_index_csv_path, rejected_index_rows, STEP7_REJECTED_INDEX_FIELDNAMES)
    write_json(
        rejected_index_json_path,
        {
            **batch_provenance,
            "row_count": len(rejected_index_rows),
            "rows": rejected_index_rows,
        },
    )
    missing_review_png_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if not Path(
            _resolved_review_png_path(
                run_root,
                case_id=item.case_id,
                case_review_png_path=str(item.summary_row["review_png_path"]),
            )
        ).is_file()
    )
    missing_reject_stub_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "rejected"
        and item.reject_stub_feature is not None
        and not Path(run_root / "cases" / item.case_id / "reject_stub.geojson").is_file()
    )
    missing_reject_index_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "rejected"
        and not Path(run_root / "cases" / item.case_id / "reject_index.json").is_file()
    )
    missing_step7_status_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if not Path(run_root / "cases" / item.case_id / "step7_status.json").is_file()
    )
    missing_step7_audit_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if not Path(run_root / "cases" / item.case_id / "step7_audit.json").is_file()
    )
    unexpected_final_state_values = sorted(
        {
            str(item.final_state)
            for item in ordered_artifacts
            if str(item.final_state) not in STEP7_ALLOWED_FINAL_STATES
        }
    )
    accepted_layer_nonaccepted_count = sum(
        1
        for feature in accepted_features
        if str((feature.get("properties") or {}).get("final_state") or "") != "accepted"
    )
    rejected_layer_nonrejected_count = sum(
        1
        for feature in rejected_features
        if str((feature.get("properties") or {}).get("final_state") or "") != "rejected"
    )
    no_surface_reference_accepted_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if item.final_state == "accepted"
        and (
            _guard_doc_from_artifact(item).get("surface_scenario_type") == "no_surface_reference"
            or bool(_guard_doc_from_artifact(item).get("no_surface_reference_guard"))
        )
    )
    step6_guard_field_missing_case_ids = sorted(
        item.case_id
        for item in ordered_artifacts
        if any(field not in _guard_doc_from_artifact(item) for field in STEP7_SURFACE_SCENARIO_AUDIT_FIELDS)
    )
    step6_guard_mapping_issues = _step7_guard_mapping_issues(ordered_artifacts)
    step7_guard_consistency_passed = not any(
        [
            unexpected_final_state_values,
            accepted_layer_nonaccepted_count,
            rejected_layer_nonrejected_count,
            no_surface_reference_accepted_case_ids,
            step6_guard_field_missing_case_ids,
            step6_guard_mapping_issues,
        ]
    )
    consistency_report = {
        **batch_provenance,
        "passed": not any(
            [
                missing_review_png_case_ids,
                missing_reject_stub_case_ids,
                missing_reject_index_case_ids,
                missing_step7_status_case_ids,
                missing_step7_audit_case_ids,
                unexpected_final_state_values,
                accepted_layer_nonaccepted_count,
                rejected_layer_nonrejected_count,
                no_surface_reference_accepted_case_ids,
                step6_guard_field_missing_case_ids,
                step6_guard_mapping_issues,
            ]
        ),
        "total_case_count": len(ordered_artifacts),
        "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
        "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
        **surface_scenario_summary_counts,
        "step7_allowed_final_states": sorted(STEP7_ALLOWED_FINAL_STATES),
        "unexpected_final_state_values": unexpected_final_state_values,
        "accepted_layer_only_accepted": accepted_layer_nonaccepted_count == 0,
        "accepted_layer_nonaccepted_count": accepted_layer_nonaccepted_count,
        "rejected_layer_only_rejected": rejected_layer_nonrejected_count == 0,
        "rejected_layer_nonrejected_count": rejected_layer_nonrejected_count,
        "no_surface_reference_accepted_case_ids": no_surface_reference_accepted_case_ids,
        "step6_guard_fields_present": not step6_guard_field_missing_case_ids,
        "step6_guard_field_missing_case_ids": step6_guard_field_missing_case_ids,
        "step6_guard_failure_reject_mapping_passed": not step6_guard_mapping_issues,
        "step6_guard_failure_reject_mapping_issues": step6_guard_mapping_issues,
        "nodes_writeback_rule": "accepted->yes; rejected/runtime_failed/formal_result_missing->fail4",
        "nodes_writeback_checked_in_step7_consistency_report": False,
        "nodes_writeback_check_reason": "nodes_publish owns downstream node materialization and preserves the existing value domain",
        "step7_guard_consistency_passed": step7_guard_consistency_passed,
        "accepted_layer_feature_count": len(accepted_features),
        "rejected_layer_feature_count": len(rejected_features),
        "audit_layer_feature_count": len(audit_features),
        "summary_row_count": len(summary_rows),
        "rejected_index_row_count": len(rejected_index_rows),
        "step4_review_flat_dir": str(run_root / "step4_review_flat"),
        "step4_review_flat_dir_exists": bool((run_root / "step4_review_flat").is_dir()),
        "review_png_present_count": len(ordered_artifacts) - len(missing_review_png_case_ids),
        "missing_review_png_case_ids": missing_review_png_case_ids,
        "missing_reject_stub_case_ids": missing_reject_stub_case_ids,
        "missing_reject_index_case_ids": missing_reject_index_case_ids,
        "missing_step7_status_case_ids": missing_step7_status_case_ids,
        "missing_step7_audit_case_ids": missing_step7_audit_case_ids,
        "accepted_layer_path": str(accepted_path),
        "rejected_layer_path": str(rejected_path),
        "audit_layer_path": str(audit_path),
        "summary_csv_path": str(summary_csv_path),
        "summary_json_path": str(summary_json_path),
        "rejected_index_csv_path": str(rejected_index_csv_path),
        "rejected_index_json_path": str(rejected_index_json_path),
    }
    write_json(consistency_report_path, consistency_report)
    return {
        "accepted_layer_path": str(accepted_path),
        "rejected_layer_path": str(rejected_path),
        "audit_layer_path": str(audit_path),
        "summary_csv_path": str(summary_csv_path),
        "summary_json_path": str(summary_json_path),
        "rejected_index_csv_path": str(rejected_index_csv_path),
        "rejected_index_json_path": str(rejected_index_json_path),
        "consistency_report_path": str(consistency_report_path),
        "accepted_count": sum(1 for item in ordered_artifacts if item.final_state == "accepted"),
        "rejected_count": sum(1 for item in ordered_artifacts if item.final_state == "rejected"),
        **surface_scenario_summary_counts,
    }


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
