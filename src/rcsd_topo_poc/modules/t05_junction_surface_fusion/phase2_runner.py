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


from .phase2_pipeline import (
    run_t05_phase2_rcsd_junctionization_and_relation,
    _actionable_t11_manual_rows,
    _target_contexts,
    _is_t04_fallback_relation,
    _is_t07_relation_only_success,
    _is_t07_multi_intersection_relation,
    _is_t11_manual_relation,
    _relation_only_surface_id,
    _has_nonzero_base_id_candidate,
    _required_path,
    _resolve_next_id_start,
    _load_t04_supplements,
    _target_case_ids,
    _iter_t04_case_audit_paths,
    _t04_fact_reference_case_ids,
    _t04_step4_evidence_supplement,
    _merge_t04_supplements,
    _rcsdnode_spatial_index,
    _build_decision_plan,
)


def _upgrade_direct_rcsdintersection_multi_nodes(
    *,
    context: SwsdTargetContext,
    actionable: list[Any],
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsdnode_tree: STRtree | None,
    rcsdnode_geometries: list[BaseGeometry],
    rcsdnode_ids: list[int],
    rcsdnode_semantic_ids: set[int],
    nearby_nonbase_node_ids: list[int],
) -> list[Any]:
    if len(actionable) != 1:
        return actionable
    decision = actionable[0]
    if decision.scene != SCENE_DIRECT:
        return actionable
    if decision.source_module not in {SOURCE_T07, SOURCE_T02_INPUT}:
        return actionable
    if decision.reason != "existing_rcsdintersection_matched":
        return actionable
    semantic_ids = _surface_rcsd_semantic_ids(
        context.surface_geometry,
        rcsdnode_features_by_id=rcsdnode_features_by_id,
        rcsdnode_tree=rcsdnode_tree,
        rcsdnode_geometries=rcsdnode_geometries,
        rcsdnode_ids=rcsdnode_ids,
    )
    if decision.source_module == SOURCE_T07 and not _all_candidate_bases_resolvable(
        decision.base_id_candidates,
        rcsdnode_semantic_ids,
    ):
        if len(semantic_ids) == 1:
            semantic_id = semantic_ids[0]
            return [
                SceneDecision(
                    scene=SCENE_DIRECT,
                    action="direct_relation",
                    reason="existing_rcsdintersection_surface_1v1_rcsdnode_rebased",
                    source_module=decision.source_module,
                    source_case_id=decision.source_case_id,
                    base_id_candidates=(semantic_id,),
                )
            ]
        if len(semantic_ids) > 1:
            return [
                SceneDecision(
                    scene=SCENE_GROUP_EXISTING,
                    action="group_existing_rcsd_nodes",
                    reason="existing_rcsdintersection_multi_rcsdnode_surface",
                    source_module=decision.source_module,
                    source_case_id=decision.source_case_id,
                    base_id_candidates=tuple(decision.base_id_candidates),
                    rcsdnode_ids=tuple(semantic_ids),
                    multi_base_relation=True,
                )
            ]
        return [
            SceneDecision(
                scene=SCENE_FAILURE,
                action="failure_relation",
                reason="t07_rcsdintersection_base_not_in_rcsdnode_out",
                source_module=decision.source_module,
                source_case_id=decision.source_case_id,
                base_id_candidates=tuple(decision.base_id_candidates),
            )
        ]
    if len(semantic_ids) <= 1:
        nearby_ids = _direct_nearby_group_node_ids(decision, nearby_nonbase_node_ids)
        if not nearby_ids:
            return actionable
        return [
            SceneDecision(
                scene=SCENE_GROUP_EXISTING,
                action="group_existing_rcsd_nodes",
                reason="existing_rcsdintersection_nearby_nonbase_node_grouping",
                source_module=decision.source_module,
                source_case_id=decision.source_case_id,
                base_id_candidates=tuple(decision.base_id_candidates),
                rcsdnode_ids=tuple(nearby_ids),
                multi_base_relation=True,
            )
        ]
    return [
        SceneDecision(
            scene=SCENE_GROUP_EXISTING,
            action="group_existing_rcsd_nodes",
            reason="existing_rcsdintersection_multi_rcsdnode_surface",
            source_module=decision.source_module,
            source_case_id=decision.source_case_id,
            base_id_candidates=tuple(decision.base_id_candidates),
            rcsdnode_ids=tuple(semantic_ids),
            multi_base_relation=True,
        )
    ]


def _all_candidate_bases_resolvable(candidate_ids: tuple[int, ...], rcsdnode_semantic_ids: set[int]) -> bool:
    return bool(candidate_ids) and all(candidate_id in rcsdnode_semantic_ids for candidate_id in candidate_ids)


def _rcsdnode_semantic_id_set(rcsdnode_features_by_id: dict[int, dict[str, Any]]) -> set[int]:
    semantic_ids = set(rcsdnode_features_by_id)
    for feature in rcsdnode_features_by_id.values():
        props = feature.get("properties") or {}
        mainnodeid = _positive_int_value(_field_value(props, "mainnodeid"))
        if mainnodeid is not None:
            semantic_ids.add(mainnodeid)
    return semantic_ids


def _direct_nearby_group_node_ids(decision: Any, nearby_nonbase_node_ids: list[int]) -> list[int]:
    if not nearby_nonbase_node_ids or len(getattr(decision, "base_id_candidates", ()) or ()) != 1:
        return []
    node_ids: list[int] = []
    seen: set[int] = set()
    for node_id in [*getattr(decision, "base_id_candidates", ()), *nearby_nonbase_node_ids]:
        if node_id in seen:
            continue
        seen.add(node_id)
        node_ids.append(node_id)
    return node_ids if len(node_ids) > 1 else []


def _direct_nearby_nonbase_node_ids_by_target(
    contexts: list[SwsdTargetContext],
    evidence_by_target: dict[str, list[Any]],
    *,
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsdnode_tree: STRtree | None,
    rcsdnode_geometries: list[BaseGeometry],
    rcsdnode_ids: list[int],
    protected_rcsdnode_ids: set[int],
) -> dict[str, list[int]]:
    raw_by_target: dict[str, list[int]] = {}
    candidate_bases: dict[int, set[int]] = defaultdict(set)
    for context in contexts:
        decision = _single_direct_t07_existing_decision(
            context=context,
            evidence_by_target=evidence_by_target,
        )
        if decision is None or not decision.base_id_candidates:
            continue
        base_id = int(decision.base_id_candidates[0])
        candidates = _nearby_nonbase_rcsdnode_ids(
            context=context,
            base_id=base_id,
            rcsdnode_features_by_id=rcsdnode_features_by_id,
            rcsdnode_tree=rcsdnode_tree,
            rcsdnode_geometries=rcsdnode_geometries,
            rcsdnode_ids=rcsdnode_ids,
            protected_rcsdnode_ids=protected_rcsdnode_ids,
        )
        if not candidates:
            continue
        raw_by_target[context.target_id] = candidates
        for node_id in candidates:
            candidate_bases[node_id].add(base_id)
    conflicted = {node_id for node_id, base_ids in candidate_bases.items() if len(base_ids) > 1}
    return {
        target_id: [node_id for node_id in node_ids if node_id not in conflicted]
        for target_id, node_ids in raw_by_target.items()
        if any(node_id not in conflicted for node_id in node_ids)
    }


def _single_direct_t07_existing_decision(
    *,
    context: SwsdTargetContext,
    evidence_by_target: dict[str, list[Any]],
) -> Any | None:
    decisions = [
        classify_evidence(evidence, junction_type=context.junction_type)
        for evidence in evidence_by_target.get(context.target_id, [])
    ]
    actionable = choose_actionable_decisions(decisions)
    if len(actionable) != 1:
        return None
    decision = actionable[0]
    if decision.scene != SCENE_DIRECT:
        return None
    if decision.source_module != SOURCE_T07:
        return None
    if decision.reason != "existing_rcsdintersection_matched":
        return None
    if len(decision.base_id_candidates) != 1:
        return None
    return decision


def _nearby_nonbase_rcsdnode_ids(
    *,
    context: SwsdTargetContext,
    base_id: int,
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsdnode_tree: STRtree | None,
    rcsdnode_geometries: list[BaseGeometry],
    rcsdnode_ids: list[int],
    protected_rcsdnode_ids: set[int],
) -> list[int]:
    surface = context.surface_geometry
    if surface is None or surface.is_empty or rcsdnode_tree is None:
        return []
    projection_points = [point for point in context.projection_points if point is not None and not point.is_empty]
    if not projection_points:
        return []
    result: list[int] = []
    search_area = surface.buffer(DIRECT_NEARBY_NONBASE_SURFACE_GAP_M)
    for index in rcsdnode_tree.query(search_area):
        node_index = int(index)
        node_id = rcsdnode_ids[node_index]
        if node_id == base_id or node_id in protected_rcsdnode_ids:
            continue
        feature = rcsdnode_features_by_id[node_id]
        props = feature.get("properties") or {}
        if _positive_int_value(_field_value(props, "mainnodeid")) is not None:
            continue
        geometry = rcsdnode_geometries[node_index]
        surface_distance = float(geometry.distance(surface))
        if surface_distance <= 0.0 or surface_distance > DIRECT_NEARBY_NONBASE_SURFACE_GAP_M:
            continue
        target_distance = min(float(geometry.distance(point)) for point in projection_points)
        if target_distance > DIRECT_NEARBY_NONBASE_TARGET_DISTANCE_M:
            continue
        result.append(node_id)
    return sorted(result)


def _protected_direct_nearby_node_ids(evidence_rows: list[Any], *, roads_by_id: dict[int, dict[str, Any]]) -> set[int]:
    protected = _accepted_relation_base_ids(evidence_rows)
    for evidence in evidence_rows:
        row = getattr(evidence, "row", {}) or {}
        if _text(row.get("status_suggested")) == "0" and _has_nonzero_base_id_candidate(row):
            continue
        for road_id in _road_candidate_ids(row):
            road = roads_by_id.get(road_id)
            if road is None:
                continue
            props = road.get("properties") or {}
            for field in ("snodeid", "enodeid"):
                node_id = _positive_int_value(_field_value(props, field))
                if node_id is not None:
                    protected.add(node_id)
    return protected


def _accepted_relation_base_ids(evidence_rows: list[Any]) -> set[int]:
    result: set[int] = set()
    for evidence in evidence_rows:
        row = getattr(evidence, "row", {}) or {}
        if _text(row.get("status_suggested")) != "0":
            continue
        for value in _list_values(row.get("base_id_candidate")):
            parsed = _positive_int_value(value)
            if parsed is not None:
                result.add(parsed)
    return result


def _road_candidate_ids(row: dict[str, Any]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for field in (
        "fallback_rcsdroad_ids",
        "support_rcsdroad_ids",
        "selected_rcsdroad_ids",
        "required_rcsdroad_ids",
    ):
        for value in _list_values(row.get(field)):
            road_id = _positive_int_value(value)
            if road_id is None or road_id in seen:
                continue
            seen.add(road_id)
            result.append(road_id)
    return result


def _surface_rcsd_semantic_ids(
    surface_geometry: BaseGeometry | None,
    *,
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsdnode_tree: STRtree | None = None,
    rcsdnode_geometries: list[BaseGeometry] | None = None,
    rcsdnode_ids: list[int] | None = None,
) -> list[int]:
    if surface_geometry is None or surface_geometry.is_empty:
        return []
    semantic_ids: set[int] = set()
    if rcsdnode_tree is not None and rcsdnode_geometries is not None and rcsdnode_ids is not None:
        candidate_features = (
            (rcsdnode_features_by_id[rcsdnode_ids[int(index)]], rcsdnode_geometries[int(index)])
            for index in rcsdnode_tree.query(surface_geometry)
        )
    else:
        candidate_features = (
            (feature, feature.get("geometry"))
            for feature in rcsdnode_features_by_id.values()
        )
    for feature, geometry in candidate_features:
        if geometry is None or geometry.is_empty:
            continue
        if not surface_geometry.covers(geometry):
            continue
        props = feature.get("properties") or {}
        semantic_id = _int_field_value(props, "mainnodeid") or _int_field_value(props, "id")
        if semantic_id is not None:
            semantic_ids.add(semantic_id)
    return sorted(semantic_ids)


def _build_readonly_relation_results(
    *,
    contexts: list[SwsdTargetContext],
    decision_plan: dict[str, tuple[list[Any], list[Any]]],
    evidence_by_target: dict[str, list[Any]],
    node_features_by_id: dict[int, dict[str, Any]],
    readonly_workers: int,
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    readonly_contexts = [
        context
        for context in contexts
        if _is_readonly_plan(*decision_plan.get(context.target_id, ([], [])))
    ]
    if not readonly_contexts:
        return {}

    def build(context: SwsdTargetContext) -> tuple[str, dict[str, Any], dict[str, Any]]:
        return _readonly_relation_for_context(
            context=context,
            decision_plan=decision_plan,
            evidence_by_target=evidence_by_target,
            node_features_by_id=node_features_by_id,
        )

    if readonly_workers <= 1 or len(readonly_contexts) <= 1:
        rows = [build(context) for context in readonly_contexts]
    else:
        with ThreadPoolExecutor(max_workers=readonly_workers) as executor:
            rows = list(executor.map(build, readonly_contexts))
    return {target_id: (relation, audit_row) for target_id, relation, audit_row in rows}


def _readonly_relation_for_context(
    *,
    context: SwsdTargetContext,
    decision_plan: dict[str, tuple[list[Any], list[Any]]],
    evidence_by_target: dict[str, list[Any]],
    node_features_by_id: dict[int, dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    _, actionable = decision_plan.get(context.target_id, ([], []))
    if not actionable:
        relation = failure_relation_feature(context=context)
        return (
            context.target_id,
            relation,
            _audit_row(context=context, decision=None, relation=relation, reason="missing_relation_evidence"),
        )
    decision = actionable[0]
    if decision.scene == SCENE_DIRECT:
        if not decision.base_id_candidates:
            relation = failure_relation_feature(context=context)
            return (
                context.target_id,
                relation,
                _audit_row(context=context, decision=decision, relation=relation, reason="missing_base_id_candidate"),
            )
        base_id = canonical_mainnode_id(decision.base_id_candidates[0], node_features_by_id)
        evidence = _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
        rcsd_point = _node_point(node_features_by_id.get(base_id)) or _evidence_rcsd_point(evidence)
        relation = success_relation_feature(context=context, base_id=base_id, rcsd_point=rcsd_point)
        return context.target_id, relation, _audit_row(context=context, decision=decision, relation=relation)
    relation = failure_relation_feature(context=context)
    return context.target_id, relation, _audit_row(context=context, decision=decision, relation=relation)


def _is_readonly_plan(decisions: list[Any], actionable: list[Any]) -> bool:
    if not actionable:
        return True
    if len(actionable) != 1:
        return False
    decision = actionable[0]
    if decision.scene in {SCENE_NO_RCSD, SCENE_FAILURE}:
        return True
    return decision.scene == SCENE_DIRECT and len(_candidate_ids(actionable)) <= 1


def _module_relation_audit_summary(
    *,
    evidence_rows: list[Any],
    source_input_counts: dict[str, int],
    context_by_target: dict[str, SwsdTargetContext],
    relation_features: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scenarios = (
        "pre_failed_no_relation_overall_failure",
        "pre_success_rcsd_semantic_relation",
        "pre_success_rcsdroad_junctionization",
        "pre_success_no_rcsd_overall_failure",
    )
    source_modules = (SOURCE_T11_MANUAL, SOURCE_T07, SOURCE_T02_INPUT, SOURCE_T03, SOURCE_T04)
    classified_counts: Counter[str] = Counter()
    target_input_counts: Counter[str] = Counter()
    counters: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    relation_status_by_target = {
        normalize_target_id((feature.get("properties") or {}).get("target_id")): int((feature.get("properties") or {}).get("status"))
        for feature in relation_features
        if normalize_target_id((feature.get("properties") or {}).get("target_id"))
    }
    blocking_targets = {
        normalize_target_id(row.get("target_id"))
        for row in blocking_errors
        if normalize_target_id(row.get("target_id"))
    }

    for evidence in evidence_rows:
        source = _text(getattr(evidence, "source_module", ""))
        if source not in source_modules:
            continue
        classified_counts[source] += 1
        context = context_by_target.get(evidence.target_id)
        if context is not None:
            target_input_counts[source] += 1
        junction_type = context.junction_type if context is not None else _text(evidence.row.get("junction_type"))
        decision = classify_evidence(evidence, junction_type=junction_type)
        scenario = _module_audit_scenario(decision)
        key = (source, scenario)
        counters[key]["scenario_input_count"] += 1
        if evidence.target_id in blocking_targets:
            counters[key]["blocking_error_count"] += 1
            continue
        relation_status = relation_status_by_target.get(evidence.target_id)
        if relation_status == STATUS_SUCCESS:
            counters[key]["relation_success_count"] += 1
        elif relation_status == STATUS_FAILURE:
            counters[key]["relation_failure_count"] += 1
        else:
            counters[key]["missing_relation_count"] += 1

    rows: list[dict[str, Any]] = []
    for source in source_modules:
        input_count = int(source_input_counts.get(source, 0))
        classified_input_count = int(classified_counts[source])
        for scenario in scenarios:
            counter = counters[(source, scenario)]
            relation_failure_count = int(counter["relation_failure_count"])
            missing_relation_count = int(counter["missing_relation_count"])
            blocking_error_count = int(counter["blocking_error_count"])
            rows.append(
                {
                    "source_module": source,
                    "input_count": input_count,
                    "classified_input_count": classified_input_count,
                    "unclassified_input_count": max(0, input_count - classified_input_count),
                    "phase2_target_input_count": int(target_input_counts[source]),
                    "scenario": scenario,
                    "scenario_input_count": int(counter["scenario_input_count"]),
                    "relation_success_count": int(counter["relation_success_count"]),
                    "relation_failure_count": relation_failure_count,
                    "missing_relation_count": missing_relation_count,
                    "blocking_error_count": blocking_error_count,
                    "overall_failure_count": relation_failure_count + missing_relation_count + blocking_error_count,
                }
            )
    return rows


def _target_key(value: Any) -> str:
    return normalize_target_id(value)


def _module_audit_scenario(decision: Any) -> str:
    if decision.scene in {SCENE_DIRECT, SCENE_GROUP_EXISTING}:
        return "pre_success_rcsd_semantic_relation"
    if decision.scene == SCENE_ROAD_SPLIT:
        return "pre_success_rcsdroad_junctionization"
    if decision.scene == SCENE_NO_RCSD:
        return "pre_success_no_rcsd_overall_failure"
    return "pre_failed_no_relation_overall_failure"


def _add_supplement(supplements: dict[str, dict[str, Any]], properties: dict[str, Any]) -> None:
    props = dict(properties or {})
    for key in (normalize_target_id(props.get("target_id") or props.get("mainnodeid")), normalize_target_id(props.get("case_id"))):
        if key:
            supplements.setdefault(key, {}).update({field: value for field, value in props.items() if value not in (None, "")})


def _t04_step4_supplement(payload: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {"case_id": payload.get("case_id")}
    units = [unit for unit in payload.get("event_units") or [] if isinstance(unit, dict)]
    aggregate = payload.get("case_alignment_aggregate") if isinstance(payload.get("case_alignment_aggregate"), dict) else {}
    alignment_values = _ordered_text(
        [aggregate.get("rcsd_alignment_type")]
        + [
            item.get("rcsd_alignment_type")
            for item in aggregate.get("unit_alignment_results") or []
            if isinstance(item, dict)
        ]
        + [unit.get("rcsd_alignment_type") for unit in units]
    )
    fallback_road_ids = _ordered_text(
        [road_id for unit in units for road_id in _list_values(unit.get("fallback_rcsdroad_ids"))]
        + [road_id for unit in units for road_id in _list_values((unit.get("selected_evidence") or {}).get("fallback_rcsdroad_ids"))]
        + [road_id for unit in units for road_id in _list_values((unit.get("selected_candidate") or {}).get("fallback_rcsdroad_ids"))]
    )
    selected_road_ids = _ordered_text(
        [road_id for unit in units for road_id in _list_values(unit.get("selected_rcsdroad_ids"))]
        + [road_id for unit in units for road_id in _list_values((unit.get("rcsd_alignment_result") or {}).get("positive_rcsdroad_ids"))]
    )
    required_nodes = _ordered_text(
        [unit.get("required_rcsd_node") for unit in units]
        + [(unit.get("selected_evidence") or {}).get("required_rcsd_node") for unit in units]
    )
    if alignment_values:
        props["rcsd_alignment_type"] = alignment_values[0]
    if fallback_road_ids:
        props["fallback_rcsdroad_ids"] = "|".join(fallback_road_ids)
    if selected_road_ids:
        props["selected_rcsdroad_ids"] = "|".join(selected_road_ids)
    if required_nodes:
        props["required_rcsd_node_ids"] = "|".join(required_nodes)
    return props


def _candidate_ids(decisions: list[Any]) -> list[int]:
    ids: set[int] = set()
    for decision in decisions:
        ids.update(int(item) for item in getattr(decision, "base_id_candidates", ()) or ())
        ids.update(int(item) for item in getattr(decision, "rcsdnode_ids", ()) or ())
    return sorted(ids)


def _has_road_split(decisions: list[Any]) -> bool:
    return any(getattr(decision, "scene", "") == SCENE_ROAD_SPLIT for decision in decisions)


def _t10_supplement_node_ids(
    decisions: list[Any],
    node_features_by_id: dict[int, dict[str, Any]],
) -> list[int]:
    ids: set[int] = set()
    for decision in decisions:
        if getattr(decision, "source_module", "") not in {SOURCE_T10_SIDE_GROUP, SOURCE_T10_PAIR_ANCHOR_CLUSTER}:
            continue
        for node_id in getattr(decision, "rcsdnode_ids", ()) or ():
            node_id = int(node_id)
            if node_id in node_features_by_id:
                ids.add(node_id)
    return sorted(ids)


def _merged_audit_decision(decisions: list[Any]) -> Any:
    if not decisions:
        return None
    first = decisions[0]
    source_modules = sorted({_text(getattr(decision, "source_module", "")) for decision in decisions if getattr(decision, "source_module", "")})
    source_case_ids = sorted({_text(getattr(decision, "source_case_id", "")) for decision in decisions if getattr(decision, "source_case_id", "")})
    return SceneDecision(
        scene=getattr(first, "scene", SCENE_GROUP_EXISTING),
        action=getattr(first, "action", "group_existing_rcsd_nodes"),
        reason=getattr(first, "reason", "multiple_base_id_merged"),
        source_module="|".join(source_modules),
        source_case_id="|".join(source_case_ids),
        base_id_candidates=tuple(_candidate_ids(decisions)),
        multi_base_relation=True,
    )


def _group_node_ids(raw_node_ids: list[int], canonical_node_ids: list[int]) -> list[int]:
    return sorted(set(raw_node_ids).union(canonical_node_ids))


def _all_node_ids_exist(node_ids: list[int], nodes_by_id: dict[int, dict[str, Any]]) -> bool:
    return bool(node_ids) and all(node_id in nodes_by_id for node_id in node_ids)


def _blocking_error_row(
    *,
    context: SwsdTargetContext,
    decisions: list[Any],
    candidate_ids: list[int],
    notes: str,
) -> dict[str, Any]:
    return {
        "target_id": context.target_id,
        "surface_id": context.surface_id,
        "reason": "multiple_base_id_unmergeable",
        "base_id_candidates": "|".join(str(item) for item in candidate_ids),
        "source_modules": "|".join(sorted({_text(getattr(decision, "source_module", "")) for decision in decisions if getattr(decision, "source_module", "")})),
        "source_case_ids": "|".join(sorted({_text(getattr(decision, "source_case_id", "")) for decision in decisions if getattr(decision, "source_case_id", "")})),
        "notes": notes,
    }


def _blocking_audit_row(
    *,
    context: SwsdTargetContext,
    decisions: list[Any],
    candidate_ids: list[int],
) -> dict[str, Any]:
    return {
        "target_id": context.target_id,
        "surface_id": context.surface_id,
        "source_module": "|".join(sorted({_text(getattr(decision, "source_module", "")) for decision in decisions if getattr(decision, "source_module", "")})),
        "source_case_id": "|".join(sorted({_text(getattr(decision, "source_case_id", "")) for decision in decisions if getattr(decision, "source_case_id", "")})),
        "scene": "multiple_base_id_unmergeable",
        "action": "blocking_error",
        "status": "",
        "base_id": "",
        "reason": "multiple_base_id_unmergeable",
        "original_rcsdroad_ids": "",
        "new_rcsdroad_ids": "",
        "original_rcsdnode_ids": "|".join(str(item) for item in candidate_ids),
        "new_rcsdnode_ids": "",
        "grouped_rcsdnode_ids": "",
        "selected_main_rcsdnode_id": "",
        "projection_point_count": 0,
        "split_point_count": 0,
        "skipped_reason": "blocking_error",
        "geometry_mode": "",
        "multi_base_relation": 1,
        "blocking_error": 1,
    }


def _enforce_unique_relation_targets(
    relation_features: list[dict[str, Any]],
    *,
    context_by_target: dict[str, SwsdTargetContext],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    target_counts: dict[str, int] = defaultdict(int)
    for feature in relation_features:
        target_counts[normalize_target_id((feature.get("properties") or {}).get("target_id"))] += 1
    duplicates = {target_id for target_id, count in target_counts.items() if target_id and count > 1}
    if not duplicates:
        return relation_features, [], []
    filtered = [
        feature
        for feature in relation_features
        if normalize_target_id((feature.get("properties") or {}).get("target_id")) not in duplicates
    ]
    blocking_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for target_id in sorted(duplicates):
        context = context_by_target.get(target_id)
        if context is None:
            continue
        blocking_rows.append(
            {
                "target_id": target_id,
                "surface_id": context.surface_id,
                "reason": "duplicate_target_id_relation",
                "base_id_candidates": "",
                "source_modules": "",
                "source_case_ids": "",
                "notes": "target_id appeared more than once in relation output",
            }
        )
        audit_rows.append(_blocking_audit_row(context=context, decisions=[], candidate_ids=[]))
    return filtered, blocking_rows, audit_rows


def _endpoint_reuse_node_ids(
    *,
    projected: dict[int, list[Any]],
    roads_by_id: dict[int, dict[str, Any]],
    node_features_by_id: dict[int, dict[str, Any]],
    min_endpoint_gap_m: float,
) -> tuple[list[int], list[int]]:
    node_ids: list[int] = []
    missing_node_ids: list[int] = []
    seen: set[int] = set()
    missing_seen: set[int] = set()
    for road_id in sorted(projected):
        road_feature = roads_by_id.get(road_id)
        line = road_feature.get("geometry") if road_feature else None
        if road_feature is None or line is None or line.is_empty or line.length <= 0:
            continue
        props = road_feature.get("properties") or {}
        for split_point in projected[road_id]:
            distance_m = float(split_point.distance_m)
            start_gap = distance_m
            end_gap = float(line.length) - distance_m
            if min(start_gap, end_gap) > min_endpoint_gap_m:
                continue
            endpoint_field = "snodeid" if start_gap <= end_gap else "enodeid"
            endpoint_node_id = _int_field_value(props, endpoint_field)
            if endpoint_node_id is None:
                continue
            if endpoint_node_id not in node_features_by_id:
                if endpoint_node_id not in missing_seen:
                    missing_seen.add(endpoint_node_id)
                    missing_node_ids.append(endpoint_node_id)
                continue
            if endpoint_node_id not in seen:
                seen.add(endpoint_node_id)
                node_ids.append(endpoint_node_id)
    return node_ids, missing_node_ids


def _groupable_endpoint_reuse_node_ids(
    endpoint_node_ids: list[int],
    node_features_by_id: dict[int, dict[str, Any]],
) -> list[int]:
    groupable: list[int] = []
    for node_id in endpoint_node_ids:
        feature = node_features_by_id.get(node_id)
        if feature is None:
            continue
        props = feature.get("properties") or {}
        if _positive_int_value(_field_value(props, "mainnodeid")) is not None:
            continue
        groupable.append(node_id)
    return groupable


def _should_group_split_endpoint_extras(new_node_ids: list[int], endpoint_extra_node_ids: list[int]) -> bool:
    return len(new_node_ids) == 1 and len(endpoint_extra_node_ids) == 1


def _projection_skipped_reasons(
    road_ids: tuple[int, ...],
    *,
    active_road_ids_by_source_id: dict[int, set[int]],
    roads_by_id: dict[int, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    for road_id in road_ids:
        active_ids = active_road_ids_by_source_id.get(road_id) or {road_id}
        existing_ids = [active_id for active_id in active_ids if active_id in roads_by_id]
        if not existing_ids:
            reasons.append(f"missing_rcsdroad_id:{road_id}")
            continue
        if not any(_road_has_projectable_geometry(roads_by_id[active_id]) for active_id in existing_ids):
            reasons.append(f"non_projectable_rcsdroad_id:{road_id}")
    return reasons or ["no_projected_split_points"]


def _road_has_projectable_geometry(road_feature: dict[str, Any]) -> bool:
    geometry = road_feature.get("geometry")
    return geometry is not None and not geometry.is_empty and getattr(geometry, "length", 0.0) > 0


def _semantic_point(nodes: list[dict[str, Any]], surface_geometry: BaseGeometry | None) -> Point:
    points = [_point_of(node.get("geometry")) for node in nodes if node.get("geometry") is not None]
    if points:
        return _point_of(unary_union(points).centroid)
    if surface_geometry is not None and not surface_geometry.is_empty:
        return _point_of(surface_geometry.representative_point())
    return Point(0.0, 0.0)


def _representative_node(nodes: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    target_key = normalize_target_id(target_id)
    for node in nodes:
        if normalize_target_id(_field_value(node.get("properties") or {}, "id")) == target_key:
            return node
    return nodes[0] if nodes else None


def _audit_row(
    *,
    context: SwsdTargetContext,
    decision: Any,
    relation: dict[str, Any],
    reason: str | None = None,
    original_road_ids: list[int] | None = None,
    new_road_ids: list[int] | None = None,
    original_node_ids: list[int] | None = None,
    new_node_ids: list[int] | None = None,
    grouped_node_ids: list[int] | None = None,
    selected_main_node_id: int | None = None,
    projection_point_count: int = 0,
    split_point_count: int = 0,
    skipped_reason: str = "",
) -> dict[str, Any]:
    props = relation.get("properties") or {}
    status = int(props.get("status"))
    return {
        "target_id": context.target_id,
        "surface_id": context.surface_id,
        "source_module": getattr(decision, "source_module", ""),
        "source_case_id": getattr(decision, "source_case_id", "") or "",
        "scene": getattr(decision, "scene", "missing_relation_evidence"),
        "action": getattr(decision, "action", "failure_relation"),
        "status": status,
        "base_id": props.get("base_id", 0),
        "reason": reason or getattr(decision, "reason", "missing_relation_evidence"),
        "original_rcsdroad_ids": "|".join(str(item) for item in (original_road_ids or [])),
        "new_rcsdroad_ids": "|".join(str(item) for item in (new_road_ids or [])),
        "original_rcsdnode_ids": "|".join(str(item) for item in (original_node_ids or [])),
        "new_rcsdnode_ids": "|".join(str(item) for item in (new_node_ids or [])),
        "grouped_rcsdnode_ids": "|".join(str(item) for item in (grouped_node_ids or [])),
        "selected_main_rcsdnode_id": selected_main_node_id or (props.get("base_id") if status == STATUS_SUCCESS else 0),
        "projection_point_count": projection_point_count,
        "split_point_count": split_point_count,
        "skipped_reason": skipped_reason,
        "geometry_mode": "success_line" if status == STATUS_SUCCESS else "zero_length_no_rcsd",
        "multi_base_relation": int(bool(getattr(decision, "multi_base_relation", False))),
        "blocking_error": 0,
    }


def _features_by_int_id(features: list[dict[str, Any]], layer_label: str) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for feature in features:
        feature_id = _int_id(feature, layer_label)
        result[feature_id] = _copy_feature(feature)
    return result


def _int_id(feature: dict[str, Any], layer_label: str) -> int:
    value = _field_value(feature.get("properties") or {}, "id")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{layer_label}.id must be convertible to integer, got {value!r}") from exc


def _feature_dicts(features: list[Any]) -> list[dict[str, Any]]:
    return [{"properties": dict(feature.properties), "geometry": feature.geometry} for feature in features]


def _copy_feature(feature: dict[str, Any]) -> dict[str, Any]:
    return {"properties": dict(feature.get("properties") or {}), "geometry": feature.get("geometry")}


def _field_value(properties: dict[str, Any], field_name: str) -> Any:
    for key, value in properties.items():
        if key.lower() == field_name:
            return value
    return None


def _int_field_value(properties: dict[str, Any], field_name: str) -> int | None:
    value = _field_value(properties, field_name)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_int_value(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _minus_one_or_missing(value: Any) -> int:
    try:
        if value in (None, ""):
            return -1
        return int(value) - 1
    except (TypeError, ValueError):
        return -1


def _point_of(geometry: BaseGeometry) -> Point:
    return geometry if getattr(geometry, "geom_type", "") == "Point" else geometry.representative_point()


def _node_point(feature: dict[str, Any] | None) -> Point | None:
    if feature is None or feature.get("geometry") is None:
        return None
    return _point_of(feature["geometry"])


def _evidence_rcsd_point(row: dict[str, Any]) -> Point | None:
    x_value = row.get("rcsd_point_x")
    y_value = row.get("rcsd_point_y")
    try:
        if x_value in (None, "") or y_value in (None, ""):
            return None
        return Point(float(str(x_value).split("|")[0]), float(str(y_value).split("|")[0]))
    except (TypeError, ValueError):
        return None


def _first_evidence_row(evidence_rows: list[Any], decision: Any) -> dict[str, Any]:
    for evidence in evidence_rows:
        if evidence.source_module == decision.source_module and evidence.case_id == decision.source_case_id:
            return evidence.row
    return evidence_rows[0].row if evidence_rows else {}


def _ordered_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _list_values(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [part.strip() for part in str(value).replace(",", "|").split("|") if part.strip()]


def _int_text(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return _text(value)


def _text(value: Any) -> str:
    return str(value or "").strip()
