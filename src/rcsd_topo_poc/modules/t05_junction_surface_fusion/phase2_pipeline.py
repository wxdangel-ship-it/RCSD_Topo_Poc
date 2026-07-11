from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .phase2_ids import normalize_target_id
from .phase2_io import prepare_run_root, produced_at_utc, read_table, read_vector_3857
from .phase2_models import (
    SCENE_DIRECT,
    SCENE_FAILURE,
    SCENE_GROUP_EXISTING,
    SCENE_NO_RCSD,
    SCENE_ROAD_SPLIT,
    SCENE_ROUNDABOUT,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    SceneDecision,
    SwsdTargetContext,
    T05Phase2Artifacts,
)
from .phase2_node_grouping import (
    apply_mainnodeid_grouping,
    canonical_mainnode_id,
    canonical_mainnode_ids,
    choose_primary_node_id,
)
from .phase2_outputs import write_phase2_outputs
from .phase2_projection import project_points_to_active_roads, projection_points_for_decision
from .phase2_relation import failure_relation_feature, relation_properties, success_relation_feature
from .phase2_relation_cardinality import build_relation_cardinality_errors, filter_cardinality_error_relations
from .phase2_roundabout import build_roundabout_aggregations
from .phase2_scene_classifier import (
    SOURCE_T02_INPUT,
    SOURCE_T03,
    SOURCE_T04,
    SOURCE_T10_PAIR_ANCHOR_CLUSTER,
    SOURCE_T10_SIDE_GROUP,
    SOURCE_T11_MANUAL,
    SOURCE_T07,
    build_evidence_rows,
    choose_actionable_decisions,
    classify_evidence,
)
from .phase2_split import split_roads


DIRECT_NEARBY_NONBASE_SURFACE_GAP_M = 5.0
DIRECT_NEARBY_NONBASE_TARGET_DISTANCE_M = 50.0



from . import phase2_runner as _facade


def _add_supplement(*args: Any, **kwargs: Any) -> Any:
    return _facade._add_supplement(*args, **kwargs)


def _all_node_ids_exist(*args: Any, **kwargs: Any) -> Any:
    return _facade._all_node_ids_exist(*args, **kwargs)


def _audit_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._audit_row(*args, **kwargs)


def _blocking_audit_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._blocking_audit_row(*args, **kwargs)


def _blocking_error_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._blocking_error_row(*args, **kwargs)


def _build_readonly_relation_results(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_readonly_relation_results(*args, **kwargs)


def _candidate_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._candidate_ids(*args, **kwargs)


def _copy_feature(*args: Any, **kwargs: Any) -> Any:
    return _facade._copy_feature(*args, **kwargs)


def _direct_nearby_nonbase_node_ids_by_target(*args: Any, **kwargs: Any) -> Any:
    return _facade._direct_nearby_nonbase_node_ids_by_target(*args, **kwargs)


def _endpoint_reuse_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._endpoint_reuse_node_ids(*args, **kwargs)


def _enforce_unique_relation_targets(*args: Any, **kwargs: Any) -> Any:
    return _facade._enforce_unique_relation_targets(*args, **kwargs)


def _evidence_rcsd_point(*args: Any, **kwargs: Any) -> Any:
    return _facade._evidence_rcsd_point(*args, **kwargs)


def _feature_dicts(*args: Any, **kwargs: Any) -> Any:
    return _facade._feature_dicts(*args, **kwargs)


def _features_by_int_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._features_by_int_id(*args, **kwargs)


def _field_value(*args: Any, **kwargs: Any) -> Any:
    return _facade._field_value(*args, **kwargs)


def _first_evidence_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._first_evidence_row(*args, **kwargs)


def _group_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._group_node_ids(*args, **kwargs)


def _groupable_endpoint_reuse_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._groupable_endpoint_reuse_node_ids(*args, **kwargs)


def _has_road_split(*args: Any, **kwargs: Any) -> Any:
    return _facade._has_road_split(*args, **kwargs)


def _int_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._int_id(*args, **kwargs)


def _is_readonly_plan(*args: Any, **kwargs: Any) -> Any:
    return _facade._is_readonly_plan(*args, **kwargs)


def _list_values(*args: Any, **kwargs: Any) -> Any:
    return _facade._list_values(*args, **kwargs)


def _merged_audit_decision(*args: Any, **kwargs: Any) -> Any:
    return _facade._merged_audit_decision(*args, **kwargs)


def _minus_one_or_missing(*args: Any, **kwargs: Any) -> Any:
    return _facade._minus_one_or_missing(*args, **kwargs)


def _module_relation_audit_summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._module_relation_audit_summary(*args, **kwargs)


def _node_point(*args: Any, **kwargs: Any) -> Any:
    return _facade._node_point(*args, **kwargs)


def _point_of(*args: Any, **kwargs: Any) -> Any:
    return _facade._point_of(*args, **kwargs)


def _projection_skipped_reasons(*args: Any, **kwargs: Any) -> Any:
    return _facade._projection_skipped_reasons(*args, **kwargs)


def _protected_direct_nearby_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._protected_direct_nearby_node_ids(*args, **kwargs)


def _rcsdnode_semantic_id_set(*args: Any, **kwargs: Any) -> Any:
    return _facade._rcsdnode_semantic_id_set(*args, **kwargs)


def _representative_node(*args: Any, **kwargs: Any) -> Any:
    return _facade._representative_node(*args, **kwargs)


def _semantic_point(*args: Any, **kwargs: Any) -> Any:
    return _facade._semantic_point(*args, **kwargs)


def _should_group_split_endpoint_extras(*args: Any, **kwargs: Any) -> Any:
    return _facade._should_group_split_endpoint_extras(*args, **kwargs)


def _t04_step4_supplement(*args: Any, **kwargs: Any) -> Any:
    return _facade._t04_step4_supplement(*args, **kwargs)


def _t10_supplement_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._t10_supplement_node_ids(*args, **kwargs)


def _text(*args: Any, **kwargs: Any) -> Any:
    return _facade._text(*args, **kwargs)


def _upgrade_direct_rcsdintersection_multi_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._upgrade_direct_rcsdintersection_multi_nodes(*args, **kwargs)


from .phase2_run import run_t05_phase2_rcsd_junctionization_and_relation


def _actionable_t11_manual_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actionable_types = {"1v1_rcsd_junction", "1vN_rcsd_junction", "1v1_rcsd_road", "1vN_rcsd_road"}
    result: list[dict[str, Any]] = []
    for row in rows:
        manual_type = _text(row.get("manual_relation_type"))
        selected_ids = _text(row.get("selected_ids"))
        if manual_type not in actionable_types:
            continue
        if not selected_ids or selected_ids.lower() == "null":
            continue
        result.append(dict(row))
    return result


def _target_contexts(
    surfaces: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    *,
    evidence_rows: list[Any] | None = None,
) -> list[SwsdTargetContext]:
    nodes_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in swsd_nodes:
        props = node.get("properties") or {}
        target_id = normalize_target_id(_field_value(props, "mainnodeid") or _field_value(props, "id"))
        if target_id:
            nodes_by_target[target_id].append(node)
    contexts: list[SwsdTargetContext] = []
    for surface in surfaces:
        props = surface.get("properties") or {}
        target_id = normalize_target_id(_field_value(props, "mainnodeid"))
        if not target_id:
            continue
        nodes = nodes_by_target.get(target_id, [])
        representative = _representative_node(nodes, target_id)
        point = _semantic_point(nodes, surface.get("geometry"))
        projection_points = tuple(_point_of(node.get("geometry")) for node in nodes if node.get("geometry") is not None)
        rep_props = dict(representative.get("properties") or {}) if representative else {}
        contexts.append(
            SwsdTargetContext(
                target_id=target_id,
                surface_id=_text(_field_value(props, "surface_id")) or f"JAS:{target_id}",
                junction_type=_text(_field_value(props, "junction_type")) or "unknown",
                point=point,
                projection_points=projection_points or (point,),
                surface_geometry=surface.get("geometry"),
                level=_minus_one_or_missing(_field_value(rep_props, "grade")),
                is_highway=_minus_one_or_missing(_field_value(rep_props, "closed_con")),
                representative_properties=rep_props,
            )
        )
    known_targets = {context.target_id for context in contexts}
    for evidence in evidence_rows or []:
        if evidence.target_id in known_targets:
            continue
        if not (
            _is_t04_fallback_relation(evidence)
            or _is_t07_relation_only_success(evidence)
            or _is_t07_multi_intersection_relation(evidence)
            or _is_t11_manual_relation(evidence)
        ):
            continue
        nodes = nodes_by_target.get(evidence.target_id, [])
        representative = _representative_node(nodes, evidence.target_id)
        rep_props = dict(representative.get("properties") or {}) if representative else {}
        if _is_t04_fallback_relation(evidence) and _text(_field_value(rep_props, "is_anchor")) != "fail4_fallback":
            continue
        point = _semantic_point(nodes, None)
        projection_points = tuple(_point_of(node.get("geometry")) for node in nodes if node.get("geometry") is not None)
        contexts.append(
            SwsdTargetContext(
                target_id=evidence.target_id,
                surface_id=_relation_only_surface_id(evidence),
                junction_type=_text(evidence.row.get("junction_type")) or "unknown",
                point=point,
                projection_points=projection_points or (point,),
                surface_geometry=None,
                level=_minus_one_or_missing(_field_value(rep_props, "grade")),
                is_highway=_minus_one_or_missing(_field_value(rep_props, "closed_con")),
                representative_properties=rep_props,
            )
        )
        known_targets.add(evidence.target_id)
    return contexts


def _is_t04_fallback_relation(evidence: Any) -> bool:
    row = getattr(evidence, "row", {}) or {}
    surface_candidate_present = str(row.get("surface_candidate_present", "")).strip()
    return (
        getattr(evidence, "source_module", "") == "T04"
        and _text(row.get("status_suggested")) == "0"
        and surface_candidate_present in {"0", "false", "False"}
        and _text(row.get("relation_state")).startswith("success_")
    )


def _is_t07_relation_only_success(evidence: Any) -> bool:
    row = getattr(evidence, "row", {}) or {}
    return (
        getattr(evidence, "source_module", "") == SOURCE_T07
        and _text(row.get("status_suggested")) == "0"
        and _has_nonzero_base_id_candidate(row)
    )


def _is_t07_multi_intersection_relation(evidence: Any) -> bool:
    row = getattr(evidence, "row", {}) or {}
    base_ids = [
        value
        for value in _list_values(row.get("base_id_candidate"))
        if _text(value) not in {"", "0", "-1"}
    ]
    return (
        getattr(evidence, "source_module", "") == SOURCE_T07
        and _text(row.get("relation_state")) == "multiple_intersections_for_group"
        and len(base_ids) > 1
    )


def _is_t11_manual_relation(evidence: Any) -> bool:
    row = getattr(evidence, "row", {}) or {}
    return (
        getattr(evidence, "source_module", "") == SOURCE_T11_MANUAL
        and _text(row.get("manual_relation_type")) in {"1v1_rcsd_junction", "1vN_rcsd_junction", "1v1_rcsd_road", "1vN_rcsd_road"}
        and _text(row.get("selected_ids")).lower() not in {"", "null"}
    )


def _relation_only_surface_id(evidence: Any) -> str:
    if getattr(evidence, "source_module", "") == SOURCE_T11_MANUAL:
        return f"T11_MANUAL:{evidence.target_id}"
    if getattr(evidence, "source_module", "") == SOURCE_T07:
        return f"T07_RELATION:{evidence.target_id}"
    return f"T04_FALLBACK:{evidence.target_id}"


def _has_nonzero_base_id_candidate(row: dict[str, Any]) -> bool:
    for value in _list_values(row.get("base_id_candidate")):
        if _text(value) not in {"", "0", "-1"}:
            return True
    return False


def _required_path(path: str | Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required for T05 Phase 2.")
    resolved = Path(path)
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist: {resolved}")
    return resolved


def _resolve_next_id_start(*, provided: int | None, current_max: int, label: str) -> int:
    default_next = int(current_max) + 1
    if provided is None:
        return default_next
    next_id = int(provided)
    if next_id <= int(current_max):
        raise ValueError(f"{label}={next_id} must be greater than current max id {current_max}.")
    return next_id


def _load_t04_supplements(
    *,
    t04_base_rows: list[dict[str, Any]],
    t04_surface_path: str | Path | None,
    t04_summary_path: str | Path | None,
    t04_audit_path: str | Path | None,
    t04_case_root: str | Path | None,
    target_case_ids: set[str] | None,
    crs_override: str | None,
) -> dict[str, dict[str, Any]]:
    supplements: dict[str, dict[str, Any]] = {}
    for row in t04_base_rows:
        _add_supplement(supplements, row)
    if t04_surface_path is not None:
        for feature in read_vector_3857(t04_surface_path, crs_override=crs_override).features:
            _add_supplement(supplements, feature.properties)
    if t04_summary_path is not None:
        for row in read_table(t04_summary_path):
            _add_supplement(supplements, row)
    if t04_audit_path is not None:
        audit_path = Path(t04_audit_path)
        if audit_path.suffix.lower() in {".gpkg", ".gpkt", ".shp", ".geojson", ".json"} and audit_path.suffix.lower() not in {".json"}:
            for feature in read_vector_3857(audit_path, crs_override=crs_override).features:
                _add_supplement(supplements, feature.properties)
        else:
            for row in read_table(audit_path):
                _add_supplement(supplements, row)
    if t04_case_root is not None:
        root = Path(t04_case_root)
        for name in ("step7_audit.json", "step6_audit.json", "reject_index.json", "step4_event_interpretation.json"):
            for audit_path in _iter_t04_case_audit_paths(root, name, target_case_ids):
                payload = json.loads(audit_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    if name == "step4_event_interpretation.json":
                        _add_supplement(supplements, _t04_step4_supplement(payload))
                    else:
                        _add_supplement(supplements, payload)
        fact_reference_case_ids = _t04_fact_reference_case_ids(supplements, target_case_ids)
        for evidence_path in _iter_t04_case_audit_paths(root, "step4_event_evidence.gpkg", fact_reference_case_ids):
            _add_supplement(supplements, _t04_step4_evidence_supplement(evidence_path, crs_override=crs_override))
    return supplements


def _target_case_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        for value in (row.get("case_id"), row.get("target_id")):
            text = normalize_target_id(value)
            if text:
                result.add(text)
    return result


def _iter_t04_case_audit_paths(root: Path, name: str, target_case_ids: set[str] | None) -> list[Path]:
    if not target_case_ids:
        return sorted(root.glob(f"**/{name}"))
    paths: list[Path] = []
    seen: set[Path] = set()
    for case_id in sorted(target_case_ids):
        for candidate in (
            root / case_id / name,
            root / "cases" / case_id / name,
        ):
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                paths.append(candidate)
    return paths


def _t04_fact_reference_case_ids(
    supplements: dict[str, dict[str, Any]],
    target_case_ids: set[str] | None,
) -> set[str]:
    case_ids: set[str] = set()
    for case_id, props in supplements.items():
        if target_case_ids and case_id not in target_case_ids:
            continue
        scene_type = _text(props.get("surface_scenario_type") or props.get("scene_type"))
        if scene_type != "main_evidence_with_rcsdroad_fallback":
            continue
        if _text(props.get("fact_reference_x")) and _text(props.get("fact_reference_y")):
            continue
        case_ids.add(case_id)
    return case_ids


def _t04_step4_evidence_supplement(path: Path, *, crs_override: str | None) -> dict[str, Any]:
    case_id = path.parent.name
    points: list[Point] = []
    for feature in read_vector_3857(path, crs_override=crs_override).features:
        props = feature.properties
        if _text(props.get("geometry_role")) != "fact_reference_point":
            continue
        geometry = feature.geometry
        if isinstance(geometry, Point) and not geometry.is_empty:
            points.append(geometry)
            case_id = normalize_target_id(props.get("case_id")) or case_id
    supplement: dict[str, Any] = {
        "case_id": case_id,
        "fact_reference_point_count": len(points),
        "fact_reference_source": "step4_event_evidence.gpkg",
    }
    if len(points) == 1:
        point = points[0]
        supplement["fact_reference_x"] = float(point.x)
        supplement["fact_reference_y"] = float(point.y)
    return supplement


def _merge_t04_supplements(rows: list[dict[str, Any]], supplements: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        for key in (normalize_target_id(row.get("target_id")), normalize_target_id(row.get("case_id"))):
            supplement = supplements.get(key)
            if not supplement:
                continue
            for field, value in supplement.items():
                if merged.get(field) in (None, "") and value not in (None, ""):
                    merged[field] = value
            if merged.get("scene_type") in (None, "") and supplement.get("surface_scenario_type") not in (None, ""):
                merged["scene_type"] = supplement.get("surface_scenario_type")
        merged_rows.append(merged)
    return merged_rows


def _rcsdnode_spatial_index(
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
) -> tuple[STRtree | None, list[BaseGeometry], list[int]]:
    geometries: list[BaseGeometry] = []
    node_ids: list[int] = []
    for node_id, feature in rcsdnode_features_by_id.items():
        geometry = feature.get("geometry")
        if geometry is None or geometry.is_empty:
            continue
        geometries.append(geometry)
        node_ids.append(node_id)
    if not geometries:
        return None, [], []
    return STRtree(geometries), geometries, node_ids


def _build_decision_plan(
    contexts: list[SwsdTargetContext],
    evidence_by_target: dict[str, list[Any]],
    *,
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsdnode_tree: STRtree | None,
    rcsdnode_geometries: list[BaseGeometry],
    rcsdnode_ids: list[int],
    roundabout_aggregations: dict[str, Any] | None = None,
    direct_nearby_node_ids_by_target: dict[str, list[int]] | None = None,
) -> tuple[dict[str, tuple[list[Any], list[Any]]], dict[str, int]]:
    plan: dict[str, tuple[list[Any], list[Any]]] = {}
    scene_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    split_road_ids: set[int] = set()
    grouped_node_ids: set[int] = set()
    rcsdnode_semantic_ids = _rcsdnode_semantic_id_set(rcsdnode_features_by_id)
    multi_actionable_count = 0
    readonly_target_count = 0
    for context in contexts:
        roundabout = (roundabout_aggregations or {}).get(context.target_id)
        if roundabout is not None:
            decisions = [
                SceneDecision(
                    scene=SCENE_ROUNDABOUT,
                    action="group_roundabout_rcsd_junctions",
                    reason=roundabout.reason,
                    source_module="T05",
                    source_case_id=context.target_id,
                    rcsdnode_ids=roundabout.rcsdnode_ids,
                    rcsdroad_ids=roundabout.rcsdroad_ids,
                    base_id_candidates=roundabout.semantic_group_ids,
                )
            ]
            actionable = list(decisions)
        else:
            decisions = [
                classify_evidence(evidence, junction_type=context.junction_type)
                for evidence in evidence_by_target.get(context.target_id, [])
            ]
            actionable = choose_actionable_decisions(decisions)
            actionable = _upgrade_direct_rcsdintersection_multi_nodes(
                context=context,
                actionable=actionable,
                rcsdnode_features_by_id=rcsdnode_features_by_id,
                rcsdnode_tree=rcsdnode_tree,
                rcsdnode_geometries=rcsdnode_geometries,
                rcsdnode_ids=rcsdnode_ids,
                rcsdnode_semantic_ids=rcsdnode_semantic_ids,
                nearby_nonbase_node_ids=(direct_nearby_node_ids_by_target or {}).get(context.target_id, []),
            )
        plan[context.target_id] = (decisions, actionable)
        if _is_readonly_plan(decisions, actionable):
            readonly_target_count += 1
        if not actionable:
            scene_counts["missing_relation_evidence"] += 1
            continue
        if len(actionable) > 1:
            multi_actionable_count += 1
        for decision in actionable:
            scene_counts[decision.scene] += 1
            if decision.source_module:
                source_counts[decision.source_module] += 1
            if decision.scene == SCENE_ROAD_SPLIT:
                split_road_ids.update(decision.rcsdroad_ids)
            if decision.scene == SCENE_GROUP_EXISTING:
                grouped_node_ids.update(decision.rcsdnode_ids)
            if decision.scene == SCENE_ROUNDABOUT:
                grouped_node_ids.update(decision.rcsdnode_ids)
    return (
        plan,
        {
            "target_count": len(contexts),
            "direct_target_count": scene_counts[SCENE_DIRECT],
            "group_existing_target_count": scene_counts[SCENE_GROUP_EXISTING],
            "road_split_target_count": scene_counts[SCENE_ROAD_SPLIT],
            "roundabout_target_count": scene_counts[SCENE_ROUNDABOUT],
            "no_related_target_count": scene_counts[SCENE_NO_RCSD],
            "failure_target_count": scene_counts[SCENE_FAILURE],
            "missing_evidence_target_count": scene_counts["missing_relation_evidence"],
            "multi_actionable_target_count": multi_actionable_count,
            "t07_actionable_count": source_counts[SOURCE_T07],
            "t02_actionable_count": source_counts[SOURCE_T02_INPUT],
            "t03_actionable_count": source_counts[SOURCE_T03],
            "t04_actionable_count": source_counts[SOURCE_T04],
            "unique_split_road_candidate_count": len(split_road_ids),
            "unique_group_node_candidate_count": len(grouped_node_ids),
            "readonly_target_count": readonly_target_count,
            "mutable_target_count": len(contexts) - readonly_target_count,
        },
    )
