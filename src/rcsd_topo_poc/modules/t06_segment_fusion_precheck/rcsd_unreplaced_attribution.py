"""RCSD road attribution for unreplaced Step3 output."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from .io import write_feature_triplet, write_json
from .parsing import normalize_id, parse_id_list
from .schemas import STEP3_SUMMARY

PROCESS_CRS = "EPSG:3857"
STEP1_DIR_NAME = "step1_identify_fusion_units"
STEP2_DIR_NAME = "step2_extract_rcsd_segments"
STEP3_DIR_NAME = "step3_segment_replacement"

STEP1_CANDIDATES_STEM = "t06_swsd_segment_candidates"
STEP1_FINAL_FUSION_UNITS_STEM = "t06_swsd_segment_final_fusion_units"
STEP1_REJECTED_STEM = "t06_swsd_segment_rejected"
STEP2_REPLACEABLE_STEM = "t06_rcsd_segment_replaceable"
STEP2_REJECTED_STEM = "t06_rcsd_segment_rejected"
STEP2_PLAN_STEM = "t06_segment_replacement_plan"
STEP2_PROBLEM_REGISTRY_STEM = "t06_segment_replacement_problem_registry"
STEP3_RELATION_STEM = "t06_step3_swsd_frcsd_segment_relation"
STEP3_UNREPLACED_RCSD_STEM = "t06_step3_unreplaced_rcsd_roads"
ATTRIBUTION_STEM = "t06_step3_unreplaced_rcsd_attribution"
ATTRIBUTION_SUMMARY_NAME = "t06_step3_unreplaced_rcsd_attribution_summary.json"

RELATION_FAILURE_REASONS = {
    "invalid_pair_base_id",
    "invalid_pair_relation_status",
    "missing_pair_relation",
    "missing_relation",
    "pair_relation_missing",
    "relation_failed",
}

STEP3_FAILURE_STATUSES = {"failed", "topology_failed", "connectivity_failed"}
STEP3_PARTIAL_STATUSES = {"replaced+retained_swsd", "partial_replaced"}
STEP3_REPLACED_STATUSES = {"replaced", "replaced+retained_swsd", "failed"}


@dataclass(frozen=True)
class RcsdUnreplacedAttributionArtifacts:
    """Output paths and metrics for unreplaced RCSD attribution."""

    attribution_gpkg_path: Path
    attribution_csv_path: Path
    summary_path: Path
    summary: dict[str, Any]


def run_t06_rcsd_unreplaced_attribution(
    *,
    t06_run_root: Path,
    step_output_root: Path | None = None,
    swsd_segment_path: Path,
    rcsdroad_path: Path,
    audit_buffer_m: float = 50.0,
    update_step3_summary: bool = True,
) -> RcsdUnreplacedAttributionArtifacts:
    """Classify unreplaced RCSD roads using the formal T06 funnel priority.

    Priority is 5 > 4 > 3 > 2 > 1 > 6:
    replaceable-but-unreplaced, relation-complete-but-not-replaceable,
    evidence-but-not-all-relation, SWSD-scope-but-not-evidence,
    outside-SWSD-scope, and unattributed.
    """

    input_run_root = Path(t06_run_root)
    output_run_root = Path(step_output_root) if step_output_root is not None else input_run_root
    step1_root = input_run_root / STEP1_DIR_NAME
    step2_root = input_run_root / STEP2_DIR_NAME
    step3_root = output_run_root / STEP3_DIR_NAME
    step3_root.mkdir(parents=True, exist_ok=True)

    attribution_gpkg_path = step3_root / f"{ATTRIBUTION_STEM}.gpkg"
    attribution_csv_path = step3_root / f"{ATTRIBUTION_STEM}.csv"
    summary_path = step3_root / ATTRIBUTION_SUMMARY_NAME

    swsd_segments = _read_gdf(Path(swsd_segment_path))
    rcsd_roads = _read_gdf(Path(rcsdroad_path))
    unreplaced_roads = _read_gdf(step3_root / f"{STEP3_UNREPLACED_RCSD_STEM}.gpkg")

    target_crs = _choose_target_crs(swsd_segments, rcsd_roads, unreplaced_roads)
    swsd_segments = _ensure_crs(swsd_segments, target_crs)
    rcsd_roads = _ensure_crs(rcsd_roads, target_crs)
    unreplaced_roads = _ensure_crs(unreplaced_roads, target_crs)

    step1_candidates = _read_gdf(step1_root / f"{STEP1_CANDIDATES_STEM}.gpkg")
    step1_final_fusion_units = _read_gdf(step1_root / f"{STEP1_FINAL_FUSION_UNITS_STEM}.gpkg")
    step1_rejected = _read_gdf(step1_root / f"{STEP1_REJECTED_STEM}.gpkg")
    step2_replaceable = _read_gdf(step2_root / f"{STEP2_REPLACEABLE_STEM}.gpkg")
    step2_rejected = _read_gdf(step2_root / f"{STEP2_REJECTED_STEM}.gpkg")
    step2_plan = _read_gdf(step2_root / f"{STEP2_PLAN_STEM}.gpkg")
    step2_registry = _read_gdf(step2_root / f"{STEP2_PROBLEM_REGISTRY_STEM}.gpkg")
    step2_summary = _read_optional_json(step2_root / "t06_step2_summary.json")
    step3_relation = _read_gdf(step3_root / f"{STEP3_RELATION_STEM}.gpkg")

    all_segment_ids = _ids_from_column(swsd_segments, "id")
    evidence_ids = _ids_from_column(step1_candidates, "swsd_segment_id")
    final_fusion_unit_ids = _ids_from_column(step1_final_fusion_units, "swsd_segment_id") or set(evidence_ids)
    relation_failure_ids = _relation_failure_segment_ids(step1_rejected, step2_rejected)
    relation_scope_ids = final_fusion_unit_ids - relation_failure_ids
    replaceable_scope_ids = _replaceable_scope_ids(step2_replaceable, step2_plan, step3_relation)

    step1_reason_by_segment = _reason_map(step1_rejected)
    step2_reason_by_segment = _reason_map(step2_rejected)
    problem_reason_by_segment = _problem_reason_map(step2_registry)
    plan_status_by_segment = _plan_status_map(step2_plan)
    step3_status_by_segment = _step3_status_map(step3_relation)

    matches_all = _match_roads_to_segments(unreplaced_roads, swsd_segments, all_segment_ids, audit_buffer_m)
    matches_evidence = _match_roads_to_segments(unreplaced_roads, swsd_segments, evidence_ids, audit_buffer_m)
    matches_relation = _match_roads_to_segments(unreplaced_roads, swsd_segments, relation_scope_ids, audit_buffer_m)
    matches_replaceable = _match_roads_to_segments(
        unreplaced_roads,
        swsd_segments,
        replaceable_scope_ids,
        audit_buffer_m,
    )

    features: list[dict[str, Any]] = []
    for _, road in unreplaced_roads.iterrows():
        road_id = _road_id(road)
        all_ids = matches_all.get(road_id, [])
        evidence_match_ids = matches_evidence.get(road_id, [])
        relation_ids = matches_relation.get(road_id, [])
        replaceable_ids = matches_replaceable.get(road_id, [])
        classification = _classify_road(
            replaceable_ids=replaceable_ids,
            relation_ids=relation_ids,
            evidence_ids=evidence_match_ids,
            all_ids=all_ids,
            step1_reason_by_segment=step1_reason_by_segment,
            step2_reason_by_segment=step2_reason_by_segment,
            problem_reason_by_segment=problem_reason_by_segment,
            plan_status_by_segment=plan_status_by_segment,
            step3_status_by_segment=step3_status_by_segment,
        )
        props = _road_properties(road)
        props.update(classification)
        props.update(
            {
                "audit_buffer_m": float(audit_buffer_m),
                "matched_segment_count": len(all_ids),
                "matched_segment_ids": _join_ids(all_ids),
                "matched_evidence_segment_ids": _join_ids(evidence_match_ids),
                "matched_relation_segment_ids": _join_ids(relation_ids),
                "matched_replaceable_segment_ids": _join_ids(replaceable_ids),
                "step1_reject_reasons": _joined_reasons(all_ids, step1_reason_by_segment),
                "step2_reject_reasons": _joined_reasons(all_ids, step2_reason_by_segment),
                "problem_registry_reasons": _joined_reasons(all_ids, problem_reason_by_segment),
                "plan_statuses": _joined_reasons(all_ids, plan_status_by_segment),
                "step3_relation_statuses": _joined_reasons(all_ids, step3_status_by_segment),
            }
        )
        features.append({"properties": props, "geometry": road.geometry})

    attribution_paths = write_feature_triplet(
        step_root=step3_root,
        stem=ATTRIBUTION_STEM,
        features=features,
        fieldnames=_attribution_fields(),
        write_json_output=False,
    )
    attribution_gpkg_path = attribution_paths["gpkg"]
    attribution_csv_path = attribution_paths["csv"]

    summary = _build_summary(
        features=features,
        rcsd_roads=rcsd_roads,
        unreplaced_roads=unreplaced_roads,
        audit_buffer_m=audit_buffer_m,
        target_crs=target_crs,
        swsd_segment_count=len(all_segment_ids),
        evidence_segment_count=len(evidence_ids),
        relation_segment_count=len(relation_scope_ids),
        replaceable_segment_count=len(replaceable_scope_ids),
        step2_reported_relation_success_count=step2_summary.get("relation_success_count"),
        step2_reported_relation_failure_count=step2_summary.get("relation_failure_count"),
        attribution_gpkg_path=attribution_gpkg_path,
        attribution_csv_path=attribution_csv_path,
    )
    write_json(summary_path, summary)
    if update_step3_summary:
        _patch_step3_summary(step3_root / STEP3_SUMMARY, summary, attribution_gpkg_path, summary_path)

    return RcsdUnreplacedAttributionArtifacts(
        attribution_gpkg_path=attribution_gpkg_path,
        attribution_csv_path=attribution_csv_path,
        summary_path=summary_path,
        summary=summary,
    )


def _read_gdf(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=PROCESS_CRS)
    return gpd.read_file(path)


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _choose_target_crs(*frames: gpd.GeoDataFrame) -> Any:
    for frame in frames:
        if frame.crs is not None:
            return frame.crs
    return PROCESS_CRS


def _ensure_crs(frame: gpd.GeoDataFrame, target_crs: Any) -> gpd.GeoDataFrame:
    if frame.empty:
        return frame.set_crs(target_crs, allow_override=True)
    if frame.crs is None:
        return frame.set_crs(target_crs, allow_override=True)
    if frame.crs != target_crs:
        return frame.to_crs(target_crs)
    return frame


def _ids_from_column(frame: gpd.GeoDataFrame, column: str) -> set[str]:
    if frame.empty or column not in frame.columns:
        return set()
    return {_norm(value) for value in frame[column] if _norm(value)}


def _segment_id(row: Any) -> str:
    for column in ("swsd_segment_id", "segment_id", "id"):
        if column in row and _norm(row[column]):
            return _norm(row[column])
    return ""


def _road_id(row: Any) -> str:
    for column in ("id", "rcsd_road_id", "road_id"):
        if column in row and _norm(row[column]):
            return _norm(row[column])
    return ""


def _norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        return normalize_id(value)
    except Exception:
        return str(value).strip()


def _relation_failure_segment_ids(step1_rejected: gpd.GeoDataFrame, step2_rejected: gpd.GeoDataFrame) -> set[str]:
    ids: set[str] = set()
    if not step1_rejected.empty and "reject_stage" in step1_rejected.columns:
        for _, row in step1_rejected.iterrows():
            if _norm(row.get("reject_stage")) == "after_evd":
                segment_id = _segment_id(row)
                if segment_id:
                    ids.add(segment_id)
    if not step2_rejected.empty:
        for _, row in step2_rejected.iterrows():
            reason = _norm(row.get("reject_reason"))
            stage = _norm(row.get("reject_stage"))
            if stage == "relation_mapping" or reason in RELATION_FAILURE_REASONS or "relation" in reason:
                segment_id = _segment_id(row)
                if segment_id:
                    ids.add(segment_id)
    return ids


def _replaceable_scope_ids(
    step2_replaceable: gpd.GeoDataFrame,
    step2_plan: gpd.GeoDataFrame,
    step3_relation: gpd.GeoDataFrame,
) -> set[str]:
    ids = _ids_from_column(step2_replaceable, "swsd_segment_id")
    ids.update(_ids_from_column(step2_plan, "swsd_segment_id"))
    for column in ("group_segment_ids", "source_segment_ids", "swsd_segment_ids"):
        ids.update(_ids_from_list_column(step2_plan, column))
    if not step3_relation.empty:
        for _, row in step3_relation.iterrows():
            status = _norm(row.get("relation_status"))
            if status in STEP3_REPLACED_STATUSES:
                segment_id = _segment_id(row)
                if segment_id:
                    ids.add(segment_id)
    return {segment_id for segment_id in ids if segment_id}


def _ids_from_list_column(frame: gpd.GeoDataFrame, column: str) -> set[str]:
    ids: set[str] = set()
    if frame.empty or column not in frame.columns:
        return ids
    for value in frame[column]:
        ids.update(parse_id_list(value))
    return {_norm(value) for value in ids if _norm(value)}


def _reason_map(frame: gpd.GeoDataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if frame.empty:
        return out
    for _, row in frame.iterrows():
        segment_id = _segment_id(row)
        reason = _norm(row.get("reject_reason")) or _norm(row.get("root_cause_category"))
        if segment_id and reason and reason not in out[segment_id]:
            out[segment_id].append(reason)
    return out


def _problem_reason_map(frame: gpd.GeoDataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if frame.empty:
        return out
    for _, row in frame.iterrows():
        ids = parse_id_list(row.get("swsd_segment_ids")) or [_segment_id(row)]
        reason = _norm(row.get("problem_type")) or _norm(row.get("problem_key")) or _norm(row.get("reject_reason"))
        for segment_id in ids:
            segment_id = _norm(segment_id)
            if segment_id and reason and reason not in out[segment_id]:
                out[segment_id].append(reason)
    return out


def _plan_status_map(frame: gpd.GeoDataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if frame.empty:
        return out
    for _, row in frame.iterrows():
        status = _norm(row.get("plan_status")) or _norm(row.get("execution_action"))
        ids = {_segment_id(row)}
        ids.update(parse_id_list(row.get("group_segment_ids")))
        ids.update(parse_id_list(row.get("source_segment_ids")))
        for segment_id in ids:
            segment_id = _norm(segment_id)
            if segment_id and status and status not in out[segment_id]:
                out[segment_id].append(status)
    return out


def _step3_status_map(frame: gpd.GeoDataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if frame.empty:
        return out
    for _, row in frame.iterrows():
        segment_id = _segment_id(row)
        status = _norm(row.get("relation_status")) or _norm(row.get("status"))
        if segment_id and status and status not in out[segment_id]:
            out[segment_id].append(status)
    return out


def _match_roads_to_segments(
    roads: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    segment_ids: set[str],
    audit_buffer_m: float,
) -> dict[str, list[str]]:
    if roads.empty or segments.empty or not segment_ids:
        return {}
    if "id" not in segments.columns:
        return {}
    segment_subset = segments[segments["id"].map(_norm).isin(segment_ids)].copy()
    if segment_subset.empty:
        return {}
    segment_subset["segment_id"] = segment_subset["id"].map(_norm)
    segment_subset = segment_subset[["segment_id", "geometry"]]
    segment_subset["geometry"] = segment_subset.geometry.buffer(float(audit_buffer_m))

    road_subset = roads.copy()
    road_subset["road_id"] = road_subset.apply(_road_id, axis=1)
    road_subset = road_subset[["road_id", "geometry"]]
    joined = gpd.sjoin(road_subset, segment_subset, how="inner", predicate="intersects")
    matches: dict[str, list[str]] = defaultdict(list)
    for _, row in joined.iterrows():
        road_id = _norm(row.get("road_id"))
        segment_id = _norm(row.get("segment_id"))
        if road_id and segment_id and segment_id not in matches[road_id]:
            matches[road_id].append(segment_id)
    return {road_id: sorted(ids) for road_id, ids in matches.items()}


def _classify_road(
    *,
    replaceable_ids: list[str],
    relation_ids: list[str],
    evidence_ids: list[str],
    all_ids: list[str],
    step1_reason_by_segment: dict[str, list[str]],
    step2_reason_by_segment: dict[str, list[str]],
    problem_reason_by_segment: dict[str, list[str]],
    plan_status_by_segment: dict[str, list[str]],
    step3_status_by_segment: dict[str, list[str]],
) -> dict[str, Any]:
    if replaceable_ids:
        return _class_props(
            priority=5,
            class_code="5_replaceable_scope_unreplaced",
            owner="T06_algorithm_strategy",
            reason="在可替换范围内但最终未替换成功，包含Step2计划后未消费或Step3失败。",
            subclass=_class5_subclass(replaceable_ids, plan_status_by_segment, step3_status_by_segment),
        )
    if relation_ids:
        return _class_props(
            priority=4,
            class_code="4_relation_scope_not_replaceable",
            owner="SWSD_data_quality",
            reason="首尾路口已完成Relation，但RCSD无法构成满足Segment要求的替换结果。",
            subclass=_first_reason(
                relation_ids,
                step2_reason_by_segment,
                fallback_map=problem_reason_by_segment,
                default="4_relation_complete_not_replaceable",
            ),
        )
    if evidence_ids:
        return _class_props(
            priority=3,
            class_code="3_evidence_scope_relation_incomplete",
            owner="pre_T05_junction_anchor",
            reason="Segment有证据进入T06，但未进入所有路口均Relation的范围。",
            subclass=_first_reason(
                evidence_ids,
                step1_reason_by_segment,
                fallback_map=step2_reason_by_segment,
                default="3_relation_incomplete",
            ),
        )
    if all_ids:
        return _class_props(
            priority=2,
            class_code="2_swsd_scope_no_t06_evidence",
            owner="RCSD_patch_version_mismatch",
            reason="RCSD落在SWSD Segment范围内，但该Segment不在T06有证据Segment范围内。",
            subclass=_first_reason(
                all_ids,
                step1_reason_by_segment,
                default="2_swsd_segment_without_t06_evidence",
            ),
        )
    return _class_props(
        priority=1,
        class_code="1_outside_swsd_segment_scope",
        owner="SWSD_timeliness_or_quality",
        reason="RCSD不在SWSD Segment范围内，按SWSD时效性或质量导致无法替换归因。",
        subclass="1_outside_swsd_segment_scope",
    )


def _class_props(priority: int, class_code: str, owner: str, reason: str, subclass: str) -> dict[str, Any]:
    return {
        "attribution_priority": priority,
        "attribution_class": class_code,
        "attribution_subclass": subclass,
        "attribution_owner": owner,
        "attribution_reason": reason,
    }


def _class5_subclass(
    segment_ids: list[str],
    plan_status_by_segment: dict[str, list[str]],
    step3_status_by_segment: dict[str, list[str]],
) -> str:
    statuses = _collect(segment_ids, step3_status_by_segment)
    if any(status in STEP3_FAILURE_STATUSES for status in statuses):
        return "5_step3_failed"
    if any(status in STEP3_PARTIAL_STATUSES for status in statuses):
        return "5_partial_replaced_retained_swsd"
    plan_statuses = _collect(segment_ids, plan_status_by_segment)
    if plan_statuses and not any(status == "ready" for status in plan_statuses):
        return f"5_plan_{plan_statuses[0]}"
    return "5_replaceable_scope_not_consumed"


def _first_reason(
    segment_ids: list[str],
    reason_by_segment: dict[str, list[str]],
    *,
    fallback_map: dict[str, list[str]] | None = None,
    default: str,
) -> str:
    reasons = _collect(segment_ids, reason_by_segment)
    if not reasons and fallback_map is not None:
        reasons = _collect(segment_ids, fallback_map)
    return reasons[0] if reasons else default


def _collect(segment_ids: list[str], values_by_segment: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for segment_id in segment_ids:
        for value in values_by_segment.get(segment_id, []):
            if value not in values:
                values.append(value)
    return values


def _road_properties(row: Any) -> dict[str, Any]:
    road_id = _road_id(row)
    props: dict[str, Any] = {
        "id": road_id,
        "rcsd_road_id": road_id,
    }
    for column in ("snodeid", "enodeid", "direction", "formway", "patchid", "source"):
        if column in row:
            props[column] = row[column]
    if "length_m" in row and row["length_m"] is not None:
        props["length_m"] = float(row["length_m"])
    elif row.geometry is not None:
        props["length_m"] = float(row.geometry.length)
    else:
        props["length_m"] = 0.0
    return props


def _joined_reasons(segment_ids: list[str], values_by_segment: dict[str, list[str]]) -> str:
    return "|".join(_collect(segment_ids, values_by_segment))


def _join_ids(ids: list[str]) -> str:
    return "|".join(ids)


def _build_summary(
    *,
    features: list[dict[str, Any]],
    rcsd_roads: gpd.GeoDataFrame,
    unreplaced_roads: gpd.GeoDataFrame,
    audit_buffer_m: float,
    target_crs: Any,
    swsd_segment_count: int,
    evidence_segment_count: int,
    relation_segment_count: int,
    replaceable_segment_count: int,
    step2_reported_relation_success_count: Any,
    step2_reported_relation_failure_count: Any,
    attribution_gpkg_path: Path,
    attribution_csv_path: Path,
) -> dict[str, Any]:
    total_count = int(len(rcsd_roads))
    total_length = _frame_length_m(rcsd_roads)
    unreplaced_count = int(len(unreplaced_roads))
    unreplaced_length = _frame_length_m(unreplaced_roads)
    replaced_count = max(total_count - unreplaced_count, 0)
    replaced_length = max(total_length - unreplaced_length, 0.0)
    rows = [dict(feature.get("properties") or {}) for feature in features]
    by_class = _aggregate(rows, "attribution_class", total_length, unreplaced_length)
    by_subclass = _aggregate(rows, "attribution_subclass", total_length, unreplaced_length)
    by_owner = _aggregate(rows, "attribution_owner", total_length, unreplaced_length)
    return {
        "audit_name": "t06_step3_unreplaced_rcsd_attribution",
        "audit_buffer_m": float(audit_buffer_m),
        "crs": str(target_crs),
        "classification_priority": ["5", "4", "3", "2", "1", "6"],
        "total_rcsd_road_count": total_count,
        "total_rcsd_road_length_m": round(total_length, 3),
        "unreplaced_rcsd_road_count": unreplaced_count,
        "unreplaced_rcsd_road_length_m": round(unreplaced_length, 3),
        "replaced_rcsd_road_count": replaced_count,
        "replaced_rcsd_road_length_m": round(replaced_length, 3),
        "replaced_rcsd_road_rate_by_count": _rate(replaced_count, total_count),
        "replaced_rcsd_road_rate_by_length": _rate(replaced_length, total_length),
        "swsd_segment_count": swsd_segment_count,
        "evidence_segment_count": evidence_segment_count,
        "relation_scope_segment_count": relation_segment_count,
        "step2_reported_relation_success_count": step2_reported_relation_success_count,
        "step2_reported_relation_failure_count": step2_reported_relation_failure_count,
        "replaceable_scope_segment_count": replaceable_segment_count,
        "by_attribution_class": by_class,
        "by_attribution_subclass": by_subclass,
        "by_attribution_owner": by_owner,
        "outputs": {
            "gpkg": str(attribution_gpkg_path),
            "csv": str(attribution_csv_path),
        },
        "qa_notes": {
            "crs_check": "All spatial joins are normalized to one working CRS before buffering.",
            "topology_check": "This audit is read-only and does not perform silent geometry fixes.",
            "geometry_semantics": "A 50m segment buffer attributes unreplaced RCSD roads to the most advanced funnel scope they intersect.",
            "traceability": "Each attributed road keeps matched segment ids and upstream Step1/Step2/Step3 reasons.",
            "performance": "Spatial joins are per funnel scope and avoid per-road nested scans.",
        },
    }


def _frame_length_m(frame: gpd.GeoDataFrame) -> float:
    if frame.empty:
        return 0.0
    if "length_m" in frame.columns:
        return float(frame["length_m"].fillna(0).sum())
    return float(frame.geometry.length.sum())


def _aggregate(rows: list[dict[str, Any]], key: str, total_length: float, unreplaced_length: float) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value not in grouped:
            grouped[value] = {"value": value, "count": 0, "length_m": 0.0}
        grouped[value]["count"] += 1
        grouped[value]["length_m"] += float(row.get("length_m") or 0.0)
    out = []
    for item in grouped.values():
        length = float(item["length_m"])
        out.append(
            {
                "value": item["value"],
                "count": int(item["count"]),
                "length_m": round(length, 3),
                "unreplaced_length_rate": _rate(length, unreplaced_length),
                "total_length_rate": _rate(length, total_length),
            }
        )
    return sorted(out, key=lambda item: (-item["length_m"], item["value"]))


def _rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _patch_step3_summary(
    step3_summary_path: Path,
    attribution_summary: dict[str, Any],
    attribution_gpkg_path: Path,
    attribution_summary_path: Path,
) -> None:
    if not step3_summary_path.exists():
        return
    summary = json.loads(step3_summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        return
    summary["rcsd_unreplaced_attribution_count"] = attribution_summary["unreplaced_rcsd_road_count"]
    summary["rcsd_unreplaced_attribution_length_m"] = attribution_summary["unreplaced_rcsd_road_length_m"]
    summary["rcsd_unreplaced_attribution_by_class"] = attribution_summary["by_attribution_class"]
    outputs = summary.setdefault("outputs", {})
    if isinstance(outputs, dict):
        outputs["unreplaced_rcsd_attribution_gpkg"] = str(attribution_gpkg_path)
        outputs["unreplaced_rcsd_attribution_summary"] = str(attribution_summary_path)
    write_json(step3_summary_path, summary)


def _attribution_fields() -> list[str]:
    return [
        "id",
        "rcsd_road_id",
        "snodeid",
        "enodeid",
        "direction",
        "formway",
        "patchid",
        "source",
        "length_m",
        "attribution_priority",
        "attribution_class",
        "attribution_subclass",
        "attribution_owner",
        "attribution_reason",
        "audit_buffer_m",
        "matched_segment_count",
        "matched_segment_ids",
        "matched_evidence_segment_ids",
        "matched_relation_segment_ids",
        "matched_replaceable_segment_ids",
        "step1_reject_reasons",
        "step2_reject_reasons",
        "problem_registry_reasons",
        "plan_statuses",
        "step3_relation_statuses",
    ]
