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


def _actionable_t11_manual_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._actionable_t11_manual_rows(*args, **kwargs)


def _build_decision_plan(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_decision_plan(*args, **kwargs)


def _load_t04_supplements(*args: Any, **kwargs: Any) -> Any:
    return _facade._load_t04_supplements(*args, **kwargs)


def _merge_t04_supplements(*args: Any, **kwargs: Any) -> Any:
    return _facade._merge_t04_supplements(*args, **kwargs)


def _rcsdnode_spatial_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._rcsdnode_spatial_index(*args, **kwargs)


def _required_path(*args: Any, **kwargs: Any) -> Any:
    return _facade._required_path(*args, **kwargs)


def _resolve_next_id_start(*args: Any, **kwargs: Any) -> Any:
    return _facade._resolve_next_id_start(*args, **kwargs)


def _target_case_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._target_case_ids(*args, **kwargs)


def _target_contexts(*args: Any, **kwargs: Any) -> Any:
    return _facade._target_contexts(*args, **kwargs)


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


def _merged_audit_decision(*args: Any, **kwargs: Any) -> Any:
    return _facade._merged_audit_decision(*args, **kwargs)


def _module_relation_audit_summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._module_relation_audit_summary(*args, **kwargs)


def _node_point(*args: Any, **kwargs: Any) -> Any:
    return _facade._node_point(*args, **kwargs)


def _projection_skipped_reasons(*args: Any, **kwargs: Any) -> Any:
    return _facade._projection_skipped_reasons(*args, **kwargs)


def _protected_direct_nearby_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._protected_direct_nearby_node_ids(*args, **kwargs)


def _should_group_split_endpoint_extras(*args: Any, **kwargs: Any) -> Any:
    return _facade._should_group_split_endpoint_extras(*args, **kwargs)


def _t10_supplement_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._t10_supplement_node_ids(*args, **kwargs)


def run_t05_phase2_rcsd_junctionization_and_relation(
    *,
    junction_surface_path: str | Path,
    fusion_audit_path: str | Path | None,
    nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    t02_relation_evidence_path: str | Path | None,
    t03_relation_evidence_path: str | Path | None,
    t04_relation_evidence_path: str | Path | None,
    out_root: str | Path,
    run_id: str | None = None,
    junction_surface_layer: str | None = None,
    nodes_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    t04_surface_path: str | Path | None = None,
    t04_summary_path: str | Path | None = None,
    t04_audit_path: str | Path | None = None,
    t04_case_root: str | Path | None = None,
    crs_override: str | None = None,
    min_split_gap_m: float = 2.0,
    min_endpoint_gap_m: float = 2.0,
    progress: bool = False,
    progress_interval: int = 1000,
    readonly_workers: int = 1,
    t07_relation_evidence_path: str | Path | None = None,
    t10_side_group_endpoint_candidate_path: str | Path | None = None,
    t10_pair_anchor_endpoint_cluster_path: str | Path | None = None,
    t11_manual_relation_path: str | Path | None = None,
    next_road_id_start: int | None = None,
    next_node_id_start: int | None = None,
) -> T05Phase2Artifacts:
    run_started = perf_counter()
    timings_sec: dict[str, float] = {}
    progress_every = max(1, int(progress_interval))

    def mark(name: str, started_at: float) -> None:
        timings_sec[name] = round(perf_counter() - started_at, 6)

    def mark_and_log(name: str, started_at: float, **counts: Any) -> None:
        mark(name, started_at)
        details = " ".join(f"{key}={value}" for key, value in counts.items())
        suffix = f" {details}" if details else ""
        log(f"{name} done sec={timings_sec[name]}{suffix}")

    def log(message: str) -> None:
        if progress:
            print(f"[T05 Phase2] {message}", flush=True)

    log("start")
    run_root = prepare_run_root(out_root, run_id)
    produced_at = produced_at_utc()

    read_started = perf_counter()
    log("read_vectors start")
    surfaces = _feature_dicts(read_vector_3857(junction_surface_path, layer_name=junction_surface_layer, crs_override=crs_override).features)
    swsd_nodes = _feature_dicts(read_vector_3857(nodes_path, layer_name=nodes_layer, crs_override=crs_override).features)
    original_roads = _feature_dicts(read_vector_3857(rcsdroad_path, layer_name=rcsdroad_layer, crs_override=crs_override).features)
    original_rcsdnodes = _feature_dicts(read_vector_3857(rcsdnode_path, layer_name=rcsdnode_layer, crs_override=crs_override).features)
    _ = read_table(_required_path(fusion_audit_path, "fusion_audit_path"))
    mark_and_log(
        "read_vectors_sec",
        read_started,
        surfaces=len(surfaces),
        swsd_nodes=len(swsd_nodes),
        rcsdroads=len(original_roads),
        rcsdnodes=len(original_rcsdnodes),
    )

    index_started = perf_counter()
    log("build_indexes start")
    roads_by_id = _features_by_int_id(original_roads, "RCSDRoad")
    node_out_by_id = _features_by_int_id([_copy_feature(feature) for feature in original_rcsdnodes], "RCSDNode")
    rcsdnode_tree, rcsdnode_geometries, rcsdnode_ids = _rcsdnode_spatial_index(node_out_by_id)
    node_template = dict((original_rcsdnodes[0].get("properties") or {}) if original_rcsdnodes else {"id": None, "mainnodeid": None})
    next_road_id = _resolve_next_id_start(
        provided=next_road_id_start,
        current_max=max(roads_by_id.keys(), default=0),
        label="next_road_id_start",
    )
    next_node_id = _resolve_next_id_start(
        provided=next_node_id_start,
        current_max=max(node_out_by_id.keys(), default=0),
        label="next_node_id_start",
    )
    mark_and_log(
        "build_indexes_sec",
        index_started,
        roads_by_id=len(roads_by_id),
        node_out_by_id=len(node_out_by_id),
        indexed_rcsdnodes=len(rcsdnode_ids),
    )

    evidence_started = perf_counter()
    log("read_evidence start")
    if t02_relation_evidence_path is None and t07_relation_evidence_path is None:
        raise ValueError("Either t07_relation_evidence_path or t02_relation_evidence_path is required for T05 Phase 2.")
    t02_rows = read_table(_required_path(t02_relation_evidence_path, "t02_relation_evidence_path")) if t02_relation_evidence_path is not None else []
    t07_rows = read_table(_required_path(t07_relation_evidence_path, "t07_relation_evidence_path")) if t07_relation_evidence_path is not None else []
    t03_rows = read_table(_required_path(t03_relation_evidence_path, "t03_relation_evidence_path"))
    t04_base_rows = read_table(_required_path(t04_relation_evidence_path, "t04_relation_evidence_path"))
    t10_side_group_rows = (
        read_table(_required_path(t10_side_group_endpoint_candidate_path, "t10_side_group_endpoint_candidate_path"))
        if t10_side_group_endpoint_candidate_path is not None
        else []
    )
    t10_pair_anchor_cluster_rows = (
        read_table(_required_path(t10_pair_anchor_endpoint_cluster_path, "t10_pair_anchor_endpoint_cluster_path"))
        if t10_pair_anchor_endpoint_cluster_path is not None
        else []
    )
    t11_manual_rows = (
        _actionable_t11_manual_rows(read_table(_required_path(t11_manual_relation_path, "t11_manual_relation_path")))
        if t11_manual_relation_path is not None
        else []
    )
    mark_and_log(
        "read_evidence_tables_sec",
        evidence_started,
        t02=len(t02_rows),
        t07=len(t07_rows),
        t03=len(t03_rows),
        t04_base=len(t04_base_rows),
        t11_manual=len(t11_manual_rows),
    )
    t04_supplement_started = perf_counter()
    log("load_t04_supplements start")
    t04_target_case_ids = _target_case_ids(t04_base_rows)
    t04_supplements = _load_t04_supplements(
        t04_base_rows=t04_base_rows,
        t04_surface_path=t04_surface_path,
        t04_summary_path=t04_summary_path,
        t04_audit_path=t04_audit_path,
        t04_case_root=t04_case_root,
        target_case_ids=t04_target_case_ids,
        crs_override=crs_override,
    )
    mark_and_log("load_t04_supplements_sec", t04_supplement_started, supplements=len(t04_supplements))
    evidence_merge_started = perf_counter()
    log("merge_evidence start")
    t04_rows = _merge_t04_supplements(
        t04_base_rows,
        t04_supplements,
    )
    evidence_rows = build_evidence_rows(
        t02_rows=t02_rows,
        t07_rows=t07_rows,
        t03_rows=t03_rows,
        t04_rows=t04_rows,
        t10_side_group_rows=t10_side_group_rows,
        t10_pair_anchor_cluster_rows=t10_pair_anchor_cluster_rows,
        t11_manual_rows=t11_manual_rows,
    )
    evidence_by_target: dict[str, list[Any]] = defaultdict(list)
    for evidence in evidence_rows:
        evidence_by_target[evidence.target_id].append(evidence)
    mark_and_log("merge_evidence_sec", evidence_merge_started, evidence_rows=len(evidence_rows), targets=len(evidence_by_target))
    mark("read_evidence_sec", evidence_started)

    plan_started = perf_counter()
    contexts_started = perf_counter()
    log("target_contexts start")
    contexts = _target_contexts(surfaces, swsd_nodes, evidence_rows=evidence_rows)
    sorted_contexts = sorted(contexts, key=lambda item: item.target_id)
    mark_and_log("target_contexts_sec", contexts_started, contexts=len(sorted_contexts))
    roundabout_started = perf_counter()
    log("roundabout_aggregations start")
    roundabout_aggregations = build_roundabout_aggregations(
        contexts=sorted_contexts,
        surfaces=surfaces,
        swsd_nodes=swsd_nodes,
        roads_by_id=roads_by_id,
        rcsdnode_features_by_id=node_out_by_id,
    )
    mark_and_log("roundabout_aggregations_sec", roundabout_started, aggregations=len(roundabout_aggregations))
    direct_nearby_started = perf_counter()
    log("direct_nearby_node_index start")
    direct_nearby_node_ids_by_target = _direct_nearby_nonbase_node_ids_by_target(
        sorted_contexts,
        evidence_by_target,
        rcsdnode_features_by_id=node_out_by_id,
        rcsdnode_tree=rcsdnode_tree,
        rcsdnode_geometries=rcsdnode_geometries,
        rcsdnode_ids=rcsdnode_ids,
        protected_rcsdnode_ids=_protected_direct_nearby_node_ids(evidence_rows, roads_by_id=roads_by_id),
    )
    mark_and_log("direct_nearby_node_index_sec", direct_nearby_started, targets=len(direct_nearby_node_ids_by_target))
    decision_started = perf_counter()
    log("decision_plan start")
    decision_plan, plan_stats = _build_decision_plan(
        sorted_contexts,
        evidence_by_target,
        rcsdnode_features_by_id=node_out_by_id,
        rcsdnode_tree=rcsdnode_tree,
        rcsdnode_geometries=rcsdnode_geometries,
        rcsdnode_ids=rcsdnode_ids,
        roundabout_aggregations=roundabout_aggregations,
        direct_nearby_node_ids_by_target=direct_nearby_node_ids_by_target,
    )
    mark_and_log("decision_plan_sec", decision_started, targets=len(decision_plan))
    mark("build_plan_sec", plan_started)
    data_volume = {
        "surface_count": len(surfaces),
        "swsd_node_count": len(swsd_nodes),
        "rcsdroad_count": len(original_roads),
        "rcsdnode_count": len(original_rcsdnodes),
        "t02_evidence_row_count": len(t02_rows),
        "t07_evidence_row_count": len(t07_rows),
        "t03_evidence_row_count": len(t03_rows),
        "t04_evidence_row_count": len(t04_rows),
        "t04_supplement_target_count": len(t04_supplements),
        "phase2_target_count": len(sorted_contexts),
    }
    log(
        "data volume "
        + " ".join(f"{key}={value}" for key, value in data_volume.items())
    )
    log(
        "plan "
        + " ".join(f"{key}={value}" for key, value in plan_stats.items())
    )

    relation_features: list[dict[str, Any]] = []
    split_road_features_by_id: dict[int, dict[str, Any]] = {}
    generated_node_features: list[dict[str, Any]] = []
    grouped_node_features: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    blocking_errors: list[dict[str, Any]] = []
    original_split_road_ids: set[int] = set()
    original_input_road_ids = set(roads_by_id)
    active_road_ids_by_source_id: dict[int, set[int]] = {road_id: {road_id} for road_id in roads_by_id}
    source_road_ids_by_active_id: dict[int, set[int]] = {road_id: {road_id} for road_id in roads_by_id}
    context_by_target = {context.target_id: context for context in contexts}

    process_started = perf_counter()
    total_targets = len(sorted_contexts)
    readonly_workers = max(1, int(readonly_workers))
    readonly_started = perf_counter()
    readonly_results = _build_readonly_relation_results(
        contexts=sorted_contexts,
        decision_plan=decision_plan,
        evidence_by_target=evidence_by_target,
        node_features_by_id=node_out_by_id,
        readonly_workers=readonly_workers,
    )
    mark("process_readonly_targets_sec", readonly_started)
    log(
        f"readonly targets={len(readonly_results)} readonly_workers={readonly_workers} "
        f"mutable_targets={total_targets - len(readonly_results)}"
    )
    mutable_started = perf_counter()
    for index, context in enumerate(sorted_contexts, start=1):
        if index == 1 or index == total_targets or index % progress_every == 0:
            log(f"processing target {index}/{total_targets}")
        readonly_result = readonly_results.get(context.target_id)
        if readonly_result is not None:
            relation, audit_row = readonly_result
            relation_features.append(relation)
            audit_rows.append(audit_row)
            continue
        decisions, actionable = decision_plan.get(context.target_id, ([], []))
        if not actionable:
            relation = failure_relation_feature(context=context)
            relation_features.append(relation)
            audit_rows.append(_audit_row(context=context, decision=None, relation=relation, reason="missing_relation_evidence"))
            continue
        if len(actionable) == 1 and actionable[0].scene == SCENE_ROUNDABOUT:
            decision = actionable[0]
            missing = [node_id for node_id in decision.rcsdnode_ids if node_id not in node_out_by_id]
            if missing:
                relation = failure_relation_feature(context=context)
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=decision,
                        relation=relation,
                        reason=f"missing_rcsdnode_ids:{missing}",
                        skipped_reason="roundabout_rcsdnode_grouping_failed",
                    )
                )
                continue
            primary = choose_primary_node_id(
                list(decision.rcsdnode_ids),
                nodes_by_id=node_out_by_id,
                reference_point=context.point,
                preferred_ids=list(decision.base_id_candidates or decision.rcsdnode_ids),
            )
            grouped = apply_mainnodeid_grouping(
                node_ids=list(decision.rcsdnode_ids),
                primary_node_id=primary,
                node_features_by_id=node_out_by_id,
            )
            grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
            relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
            relation_features.append(relation)
            audit_rows.append(
                _audit_row(
                    context=context,
                    decision=decision,
                    relation=relation,
                    original_road_ids=list(decision.rcsdroad_ids),
                    original_node_ids=list(decision.rcsdnode_ids),
                    grouped_node_ids=list(decision.rcsdnode_ids),
                    selected_main_node_id=primary,
                )
            )
            continue
        raw_candidate_ids = _candidate_ids(actionable)
        multi_candidate_ids = canonical_mainnode_ids(raw_candidate_ids, node_out_by_id)
        if (
            len(actionable) > 1
            or len(multi_candidate_ids) > 1
            or raw_candidate_ids != multi_candidate_ids
        ) and not (len(actionable) == 1 and actionable[0].scene == SCENE_GROUP_EXISTING) and not _has_road_split(actionable):
            if len(multi_candidate_ids) == 1:
                decision = actionable[0]
                base_id = multi_candidate_ids[0]
                rcsd_point = _node_point(node_out_by_id.get(multi_candidate_ids[0])) or _evidence_rcsd_point(
                    _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
                )
                relation = success_relation_feature(context=context, base_id=base_id, rcsd_point=rcsd_point)
                relation_features.append(relation)
                audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))
                continue
            group_node_ids = _group_node_ids(raw_candidate_ids, multi_candidate_ids)
            if _all_node_ids_exist(group_node_ids, node_out_by_id):
                primary = choose_primary_node_id(multi_candidate_ids, nodes_by_id=node_out_by_id, reference_point=context.point)
                grouped = apply_mainnodeid_grouping(
                    node_ids=group_node_ids,
                    primary_node_id=primary,
                    node_features_by_id=node_out_by_id,
                )
                grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=_merged_audit_decision(actionable),
                        relation=relation,
                        reason="multiple_base_id_merged",
                        original_node_ids=raw_candidate_ids,
                        grouped_node_ids=group_node_ids,
                        selected_main_node_id=primary,
                    )
                )
                continue
            blocking_row = _blocking_error_row(
                context=context,
                decisions=actionable,
                candidate_ids=group_node_ids,
                notes="not_all_candidates_are_groupable_rcsdnodes",
            )
            blocking_errors.append(blocking_row)
            audit_rows.append(_blocking_audit_row(context=context, decisions=actionable, candidate_ids=group_node_ids))
            continue

        for decision in actionable[:1]:
            if decision.scene == SCENE_DIRECT:
                if not decision.base_id_candidates:
                    relation = failure_relation_feature(context=context)
                    relation_features.append(relation)
                    audit_rows.append(_audit_row(context=context, decision=decision, relation=relation, reason="missing_base_id_candidate"))
                    continue
                base_id = canonical_mainnode_id(decision.base_id_candidates[0], node_out_by_id)
                evidence = _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
                rcsd_point = _node_point(node_out_by_id.get(base_id)) or _evidence_rcsd_point(evidence)
                relation = success_relation_feature(context=context, base_id=base_id, rcsd_point=rcsd_point)
                relation_features.append(relation)
                audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))
                continue
            if decision.scene == SCENE_GROUP_EXISTING:
                raw_node_ids = list(decision.rcsdnode_ids)
                canonical_node_ids = canonical_mainnode_ids(raw_node_ids, node_out_by_id)
                group_node_ids = _group_node_ids(raw_node_ids, canonical_node_ids)
                missing = [node_id for node_id in group_node_ids if node_id not in node_out_by_id]
                if missing:
                    relation = failure_relation_feature(context=context)
                    relation_features.append(relation)
                    audit_rows.append(
                        _audit_row(
                            context=context,
                            decision=decision,
                            relation=relation,
                            reason=f"missing_rcsdnode_ids:{missing}",
                            skipped_reason="rcsdnode_grouping_failed",
                        )
                    )
                    continue
                primary = choose_primary_node_id(
                    canonical_node_ids,
                    nodes_by_id=node_out_by_id,
                    reference_point=context.point,
                    preferred_ids=list(decision.base_id_candidates or canonical_node_ids),
                )
                grouped = apply_mainnodeid_grouping(
                    node_ids=group_node_ids,
                    primary_node_id=primary,
                    node_features_by_id=node_out_by_id,
                )
                grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=decision,
                        relation=relation,
                        original_node_ids=raw_node_ids,
                        grouped_node_ids=group_node_ids,
                        selected_main_node_id=primary,
                    )
                )
                continue
            if decision.scene == SCENE_ROAD_SPLIT:
                evidence = _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
                points = projection_points_for_decision(
                    context=context,
                    evidence_row=evidence,
                    reference_mode=decision.reference_mode,
                )
                if not points:
                    relation = failure_relation_feature(context=context)
                    relation_features.append(relation)
                    audit_rows.append(
                        _audit_row(
                            context=context,
                            decision=decision,
                            relation=relation,
                            original_road_ids=list(decision.rcsdroad_ids),
                            reason="missing_fact_reference_point",
                            skipped_reason="missing_fact_reference_point",
                        )
                    )
                    continue
                projected = project_points_to_active_roads(
                    source_road_ids=decision.rcsdroad_ids,
                    roads_by_id=roads_by_id,
                    active_road_ids_by_source_id=active_road_ids_by_source_id,
                    points=points,
                    junction_type=context.junction_type,
                )
                split_result, next_road_id, next_node_id = split_roads(
                    target_id=context.target_id,
                    split_points_by_road=projected,
                    roads_by_id=roads_by_id,
                    next_road_id=next_road_id,
                    next_node_id=next_node_id,
                    swsd_properties=context.representative_properties,
                    rcsdnode_template=node_template,
                    min_split_gap_m=min_split_gap_m,
                    min_endpoint_gap_m=min_endpoint_gap_m,
                )
                if not split_result.new_node_features or not split_result.new_road_features:
                    endpoint_node_ids, missing_endpoint_node_ids = _endpoint_reuse_node_ids(
                        projected=projected,
                        roads_by_id=roads_by_id,
                        node_features_by_id=node_out_by_id,
                        min_endpoint_gap_m=min_endpoint_gap_m,
                    )
                    if endpoint_node_ids and not missing_endpoint_node_ids:
                        canonical_endpoint_node_ids = canonical_mainnode_ids(endpoint_node_ids, node_out_by_id)
                        supplement_node_ids = _t10_supplement_node_ids(actionable, node_out_by_id)
                        supplement_extra_node_ids = [node_id for node_id in supplement_node_ids if node_id not in endpoint_node_ids]
                        group_node_ids = _group_node_ids(
                            [*endpoint_node_ids, *supplement_node_ids],
                            canonical_mainnode_ids([*endpoint_node_ids, *supplement_node_ids], node_out_by_id),
                        )
                        primary = choose_primary_node_id(
                            canonical_endpoint_node_ids,
                            nodes_by_id=node_out_by_id,
                            reference_point=context.point,
                        )
                        grouped = apply_mainnodeid_grouping(
                            node_ids=group_node_ids,
                            primary_node_id=primary,
                            node_features_by_id=node_out_by_id,
                        )
                        grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                        relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                        relation_features.append(relation)
                        audit_rows.append(
                            _audit_row(
                                context=context,
                                decision=decision,
                                relation=relation,
                                reason="road_only_projection_near_endpoint_reuse_rcsdnode",
                                original_road_ids=list(decision.rcsdroad_ids),
                                original_node_ids=[*endpoint_node_ids, *supplement_extra_node_ids],
                                grouped_node_ids=group_node_ids if len(group_node_ids) > 1 else [],
                                selected_main_node_id=primary,
                                projection_point_count=sum(len(items) for items in projected.values()),
                                split_point_count=0,
                                skipped_reason="|".join(split_result.skipped_reasons),
                            )
                        )
                        continue
                    relation = failure_relation_feature(context=context)
                    relation_features.append(relation)
                    skipped_reasons = list(split_result.skipped_reasons)
                    if not projected:
                        skipped_reasons.extend(
                            _projection_skipped_reasons(
                                decision.rcsdroad_ids,
                                active_road_ids_by_source_id=active_road_ids_by_source_id,
                                roads_by_id=roads_by_id,
                            )
                        )
                    if missing_endpoint_node_ids:
                        skipped_reasons.append(
                            "missing_endpoint_rcsdnode_ids:" + "|".join(str(item) for item in missing_endpoint_node_ids)
                        )
                    audit_rows.append(
                        _audit_row(
                            context=context,
                            decision=decision,
                            relation=relation,
                            original_road_ids=list(decision.rcsdroad_ids),
                            reason="rcsdroad_split_failed",
                            skipped_reason="|".join(skipped_reasons),
                            projection_point_count=sum(len(items) for items in projected.values()),
                        )
                    )
                    continue
                endpoint_node_ids, _missing_endpoint_node_ids = _endpoint_reuse_node_ids(
                    projected=projected,
                    roads_by_id=roads_by_id,
                    node_features_by_id=node_out_by_id,
                    min_endpoint_gap_m=min_endpoint_gap_m,
                )
                groupable_endpoint_node_ids = _groupable_endpoint_reuse_node_ids(endpoint_node_ids, node_out_by_id)
                split_source_ids_by_active_road = {
                    road_id: set(source_road_ids_by_active_id.get(road_id, {road_id}))
                    for road_id in split_result.original_road_ids
                }
                new_road_ids = [_int_id(feature, "RCSDRoad") for feature in split_result.new_road_features]
                original_split_road_ids.update(
                    road_id for road_id in split_result.original_road_ids if road_id in original_input_road_ids
                )
                for road_id in split_result.original_road_ids:
                    roads_by_id.pop(road_id, None)
                    split_road_features_by_id.pop(road_id, None)
                    source_road_ids_by_active_id.pop(road_id, None)
                for road_feature in split_result.new_road_features:
                    new_road_id = _int_id(road_feature, "RCSDRoad")
                    roads_by_id[new_road_id] = road_feature
                    split_road_features_by_id[new_road_id] = _copy_feature(road_feature)
                new_node_ids = []
                for node_feature in split_result.new_node_features:
                    node_id = _int_id(node_feature, "RCSDNode")
                    new_node_ids.append(node_id)
                    node_out_by_id[node_id] = node_feature
                primary = choose_primary_node_id(
                    new_node_ids,
                    nodes_by_id=node_out_by_id,
                    reference_point=context.point,
                )
                for split_road_id, source_ids in split_source_ids_by_active_road.items():
                    replacement_road_ids = split_result.new_road_ids_by_original_road_id.get(split_road_id, [])
                    for source_id in source_ids:
                        active_ids = active_road_ids_by_source_id.setdefault(source_id, set())
                        active_ids.discard(split_road_id)
                        active_ids.update(replacement_road_ids)
                    for new_road_id in replacement_road_ids:
                        source_road_ids_by_active_id.setdefault(new_road_id, set()).update(source_ids)
                supplement_node_ids = _t10_supplement_node_ids(actionable, node_out_by_id)
                supplement_extra_node_ids = [node_id for node_id in supplement_node_ids if node_id not in new_node_ids]
                endpoint_extra_node_ids = [
                    node_id
                    for node_id in groupable_endpoint_node_ids
                    if node_id not in new_node_ids and node_id not in supplement_extra_node_ids
                ]
                if not _should_group_split_endpoint_extras(new_node_ids, endpoint_extra_node_ids):
                    endpoint_extra_node_ids = []
                group_node_ids = _group_node_ids(
                    [*new_node_ids, *endpoint_extra_node_ids, *supplement_node_ids],
                    canonical_mainnode_ids([*new_node_ids, *endpoint_extra_node_ids, *supplement_node_ids], node_out_by_id),
                )
                grouped = apply_mainnodeid_grouping(
                    node_ids=group_node_ids,
                    primary_node_id=primary,
                    node_features_by_id=node_out_by_id,
                )
                generated_node_features.extend(_copy_feature(feature) for feature in split_result.new_node_features)
                grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=decision,
                        relation=relation,
                        original_road_ids=list(decision.rcsdroad_ids),
                        new_road_ids=new_road_ids,
                        original_node_ids=[*endpoint_extra_node_ids, *supplement_extra_node_ids],
                        new_node_ids=new_node_ids,
                        grouped_node_ids=group_node_ids if len(group_node_ids) > 1 else [],
                        selected_main_node_id=primary,
                        projection_point_count=sum(len(items) for items in projected.values()),
                        split_point_count=len(new_node_ids),
                    )
                )
                continue
            relation = failure_relation_feature(context=context)
            relation_features.append(relation)
            audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))

    mark("process_mutable_targets_sec", mutable_started)
    mark("process_targets_sec", process_started)
    relation_features, duplicate_blocking_rows, duplicate_audit_rows = _enforce_unique_relation_targets(
        relation_features,
        context_by_target=context_by_target,
    )
    blocking_errors.extend(duplicate_blocking_rows)
    audit_rows.extend(duplicate_audit_rows)
    relation_cardinality_input_features = [
        {"properties": relation_properties(feature), "geometry": feature.get("geometry")}
        for feature in relation_features
    ]
    relation_cardinality_errors = build_relation_cardinality_errors(
        relation_features=relation_cardinality_input_features,
        audit_rows=audit_rows,
    )
    (
        filtered_relation_cardinality_features,
        relation_cardinality_removed_target_ids,
        relation_cardinality_removed_relation_count,
    ) = filter_cardinality_error_relations(relation_cardinality_input_features, relation_cardinality_errors)
    if relation_cardinality_removed_target_ids:
        kept_target_ids = {
            normalize_target_id((feature.get("properties") or {}).get("target_id"))
            for feature in filtered_relation_cardinality_features
        }
        relation_features = [
            feature
            for feature in relation_features
            if normalize_target_id((feature.get("properties") or {}).get("target_id")) in kept_target_ids
        ]
    module_relation_audit_rows = _module_relation_audit_summary(
        evidence_rows=evidence_rows,
        source_input_counts={
            SOURCE_T07: len(t07_rows),
            SOURCE_T02_INPUT: len(t02_rows),
            SOURCE_T03: len(t03_rows),
            SOURCE_T04: len(t04_rows),
            SOURCE_T11_MANUAL: len(t11_manual_rows),
        },
        context_by_target=context_by_target,
        relation_features=relation_features,
        blocking_errors=blocking_errors,
    )

    write_started = perf_counter()
    log("writing outputs")
    outputs = write_phase2_outputs(
        run_root=run_root,
        produced_at=produced_at,
        run_id=run_root.name,
        input_paths={
            "junction_surface_path": str(junction_surface_path),
            "fusion_audit_path": str(fusion_audit_path) if fusion_audit_path else None,
            "nodes_path": str(nodes_path),
            "rcsdroad_path": str(rcsdroad_path),
            "rcsdnode_path": str(rcsdnode_path),
            "t02_relation_evidence_path": str(t02_relation_evidence_path) if t02_relation_evidence_path else None,
            "t07_relation_evidence_path": str(t07_relation_evidence_path) if t07_relation_evidence_path else None,
            "t03_relation_evidence_path": str(t03_relation_evidence_path) if t03_relation_evidence_path else None,
            "t04_relation_evidence_path": str(t04_relation_evidence_path) if t04_relation_evidence_path else None,
            "t10_side_group_endpoint_candidate_path": str(t10_side_group_endpoint_candidate_path) if t10_side_group_endpoint_candidate_path else None,
            "t10_pair_anchor_endpoint_cluster_path": str(t10_pair_anchor_endpoint_cluster_path) if t10_pair_anchor_endpoint_cluster_path else None,
            "t11_manual_relation_path": str(t11_manual_relation_path) if t11_manual_relation_path else None,
            "t04_surface_path": str(t04_surface_path) if t04_surface_path else None,
            "t04_summary_path": str(t04_summary_path) if t04_summary_path else None,
            "t04_audit_path": str(t04_audit_path) if t04_audit_path else None,
            "t04_case_root": str(t04_case_root) if t04_case_root else None,
        },
        swsd_node_features=swsd_nodes,
        evidence_rows=evidence_rows,
        relation_features=relation_features,
        rcsdroad_out_features=[_copy_feature(feature) for feature in roads_by_id.values()],
        rcsdnode_out_features=[_copy_feature(feature) for feature in node_out_by_id.values()],
        split_road_features=list(split_road_features_by_id.values()),
        generated_node_features=generated_node_features,
        grouped_node_features=grouped_node_features,
        audit_rows=audit_rows,
        blocking_errors=blocking_errors,
        module_relation_audit_rows=module_relation_audit_rows,
        original_split_road_ids=original_split_road_ids,
        relation_cardinality_errors=relation_cardinality_errors,
        relation_cardinality_removed_target_ids=relation_cardinality_removed_target_ids,
        relation_cardinality_removed_relation_count=relation_cardinality_removed_relation_count,
        performance={
            "data_volume": data_volume,
            "plan": plan_stats,
            "timings_sec": timings_sec,
            "progress_interval": progress_every,
            "readonly_workers": readonly_workers,
        },
        progress_logger=log if progress else None,
    )
    mark("write_outputs_sec", write_started)
    timings_sec["total_sec"] = round(perf_counter() - run_started, 6)
    log(f"done total_sec={timings_sec['total_sec']}")
    summary = outputs["summary"]
    summary.setdefault("performance", {})["timings_sec"] = dict(timings_sec)
    outputs["summary_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return T05Phase2Artifacts(
        run_root=run_root,
        relation_geojson_path=outputs["relation_geojson_path"],
        rcsdroad_out_path=outputs["rcsdroad_out_path"],
        rcsdnode_out_path=outputs["rcsdnode_out_path"],
        rcsdroad_split_path=outputs["rcsdroad_split_path"],
        rcsdnode_generated_path=outputs["rcsdnode_generated_path"],
        rcsdnode_grouped_path=outputs["rcsdnode_grouped_path"],
        rcsd_junctionization_audit_csv_path=outputs["junction_audit_csv_path"],
        rcsd_junctionization_audit_json_path=outputs["junction_audit_json_path"],
        relation_audit_csv_path=outputs["relation_audit_csv_path"],
        relation_audit_json_path=outputs["relation_audit_json_path"],
        blocking_errors_csv_path=outputs["blocking_errors_csv_path"],
        blocking_errors_json_path=outputs["blocking_errors_json_path"],
        module_relation_audit_csv_path=outputs["module_relation_audit_csv_path"],
        module_relation_audit_json_path=outputs["module_relation_audit_json_path"],
        relation_cardinality_errors_csv_path=outputs["relation_cardinality_errors_csv_path"],
        relation_cardinality_errors_json_path=outputs["relation_cardinality_errors_json_path"],
        relation_graph_consumability_audit_csv_path=outputs["relation_graph_consumability_audit_csv_path"],
        relation_graph_consumability_audit_json_path=outputs["relation_graph_consumability_audit_json_path"],
        junction_anchor_funnel_summary_path=outputs["junction_anchor_funnel_summary_path"],
        junction_anchor_source_funnel_csv_path=outputs["junction_anchor_source_funnel_csv_path"],
        junction_anchor_failure_reasons_csv_path=outputs["junction_anchor_failure_reasons_csv_path"],
        summary_path=outputs["summary_path"],
        relation_count=summary["intersection_match_all_feature_count"],
        success_count=summary["status_0_count"],
        failure_count=summary["status_1_count"],
    )
