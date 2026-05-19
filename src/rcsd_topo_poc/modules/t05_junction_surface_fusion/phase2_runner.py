from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .phase2_io import prepare_run_root, produced_at_utc, read_table, read_vector_3857
from .phase2_models import (
    SCENE_DIRECT,
    SCENE_GROUP_EXISTING,
    SCENE_ROAD_SPLIT,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    SwsdTargetContext,
    T05Phase2Artifacts,
)
from .phase2_node_grouping import apply_mainnodeid_grouping, choose_primary_node_id
from .phase2_outputs import write_phase2_outputs
from .phase2_projection import project_points_to_roads, projection_points_for_decision
from .phase2_relation import failure_relation_feature, success_relation_feature
from .phase2_scene_classifier import build_evidence_rows, choose_actionable_decisions, classify_evidence
from .phase2_split import split_roads


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
) -> T05Phase2Artifacts:
    run_root = prepare_run_root(out_root, run_id)
    produced_at = produced_at_utc()

    surfaces = _feature_dicts(read_vector_3857(junction_surface_path, layer_name=junction_surface_layer, crs_override=crs_override).features)
    swsd_nodes = _feature_dicts(read_vector_3857(nodes_path, layer_name=nodes_layer, crs_override=crs_override).features)
    original_roads = _feature_dicts(read_vector_3857(rcsdroad_path, layer_name=rcsdroad_layer, crs_override=crs_override).features)
    original_rcsdnodes = _feature_dicts(read_vector_3857(rcsdnode_path, layer_name=rcsdnode_layer, crs_override=crs_override).features)
    _ = read_table(_required_path(fusion_audit_path, "fusion_audit_path"))

    roads_by_id = _features_by_int_id(original_roads, "RCSDRoad")
    node_out_by_id = _features_by_int_id([_copy_feature(feature) for feature in original_rcsdnodes], "RCSDNode")
    node_template = dict((original_rcsdnodes[0].get("properties") or {}) if original_rcsdnodes else {"id": None, "mainnodeid": None})
    next_road_id = max(roads_by_id.keys(), default=0) + 1
    next_node_id = max(node_out_by_id.keys(), default=0) + 1

    t04_rows = _merge_t04_supplements(
        read_table(_required_path(t04_relation_evidence_path, "t04_relation_evidence_path")),
        _load_t04_supplements(
            t04_surface_path=t04_surface_path,
            t04_summary_path=t04_summary_path,
            t04_audit_path=t04_audit_path,
            t04_case_root=t04_case_root,
            crs_override=crs_override,
        ),
    )
    evidence_rows = build_evidence_rows(
        t02_rows=read_table(_required_path(t02_relation_evidence_path, "t02_relation_evidence_path")),
        t03_rows=read_table(_required_path(t03_relation_evidence_path, "t03_relation_evidence_path")),
        t04_rows=t04_rows,
    )
    evidence_by_target: dict[str, list[Any]] = defaultdict(list)
    for evidence in evidence_rows:
        evidence_by_target[evidence.target_id].append(evidence)

    contexts = _target_contexts(surfaces, swsd_nodes)
    relation_features: list[dict[str, Any]] = []
    split_road_features: list[dict[str, Any]] = []
    generated_node_features: list[dict[str, Any]] = []
    grouped_node_features: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    blocking_errors: list[dict[str, Any]] = []
    original_split_road_ids: set[int] = set()
    context_by_target = {context.target_id: context for context in contexts}

    for context in sorted(contexts, key=lambda item: item.target_id):
        decisions = [
            classify_evidence(evidence, junction_type=context.junction_type)
            for evidence in evidence_by_target.get(context.target_id, [])
        ]
        actionable = choose_actionable_decisions(decisions)
        if not actionable:
            relation = failure_relation_feature(context=context)
            relation_features.append(relation)
            audit_rows.append(_audit_row(context=context, decision=None, relation=relation, reason="missing_relation_evidence"))
            continue
        multi_candidate_ids = _candidate_ids(actionable)
        if len(actionable) > 1 or len(multi_candidate_ids) > 1:
            if len(multi_candidate_ids) == 1:
                decision = actionable[0]
                rcsd_point = _node_point(node_out_by_id.get(multi_candidate_ids[0])) or _evidence_rcsd_point(
                    _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
                )
                relation = success_relation_feature(context=context, base_id=multi_candidate_ids[0], rcsd_point=rcsd_point)
                relation_features.append(relation)
                audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))
                continue
            if _all_node_ids_exist(multi_candidate_ids, node_out_by_id):
                primary = choose_primary_node_id(multi_candidate_ids, nodes_by_id=node_out_by_id, reference_point=context.point)
                grouped = apply_mainnodeid_grouping(
                    node_ids=multi_candidate_ids,
                    primary_node_id=primary,
                    node_features_by_id=node_out_by_id,
                )
                grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=actionable[0],
                        relation=relation,
                        reason="multiple_base_id_merged",
                        original_node_ids=multi_candidate_ids,
                        grouped_node_ids=multi_candidate_ids,
                        selected_main_node_id=primary,
                    )
                )
                continue
            blocking_row = _blocking_error_row(
                context=context,
                decisions=actionable,
                candidate_ids=multi_candidate_ids,
                notes="not_all_candidates_are_groupable_rcsdnodes",
            )
            blocking_errors.append(blocking_row)
            audit_rows.append(_blocking_audit_row(context=context, decisions=actionable, candidate_ids=multi_candidate_ids))
            continue

        for decision in actionable[:1]:
            if decision.scene == SCENE_DIRECT:
                if not decision.base_id_candidates:
                    relation = failure_relation_feature(context=context)
                    relation_features.append(relation)
                    audit_rows.append(_audit_row(context=context, decision=decision, relation=relation, reason="missing_base_id_candidate"))
                    continue
                base_id = decision.base_id_candidates[0]
                evidence = _first_evidence_row(evidence_by_target.get(context.target_id, []), decision)
                rcsd_point = _node_point(node_out_by_id.get(base_id)) or _evidence_rcsd_point(evidence)
                relation = success_relation_feature(context=context, base_id=base_id, rcsd_point=rcsd_point)
                relation_features.append(relation)
                audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))
                continue
            if decision.scene == SCENE_GROUP_EXISTING:
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
                            skipped_reason="rcsdnode_grouping_failed",
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
                        original_node_ids=list(decision.rcsdnode_ids),
                        grouped_node_ids=list(decision.rcsdnode_ids),
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
                projected = project_points_to_roads(
                    road_ids=decision.rcsdroad_ids,
                    roads_by_id=roads_by_id,
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
                        primary = choose_primary_node_id(
                            endpoint_node_ids,
                            nodes_by_id=node_out_by_id,
                            reference_point=context.point,
                        )
                        grouped = apply_mainnodeid_grouping(
                            node_ids=endpoint_node_ids,
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
                                original_node_ids=endpoint_node_ids,
                                grouped_node_ids=endpoint_node_ids if len(endpoint_node_ids) > 1 else [],
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
                original_split_road_ids.update(split_result.original_road_ids)
                for road_id in split_result.original_road_ids:
                    roads_by_id.pop(road_id, None)
                for road_feature in split_result.new_road_features:
                    roads_by_id[_int_id(road_feature, "RCSDRoad")] = road_feature
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
                grouped = apply_mainnodeid_grouping(
                    node_ids=new_node_ids,
                    primary_node_id=primary,
                    node_features_by_id=node_out_by_id,
                )
                split_road_features.extend(_copy_feature(feature) for feature in split_result.new_road_features)
                generated_node_features.extend(_copy_feature(feature) for feature in split_result.new_node_features)
                grouped_node_features.extend(_copy_feature(feature) for feature in grouped)
                relation = success_relation_feature(context=context, base_id=primary, rcsd_point=_node_point(node_out_by_id[primary]))
                relation_features.append(relation)
                audit_rows.append(
                    _audit_row(
                        context=context,
                        decision=decision,
                        relation=relation,
                        original_road_ids=split_result.original_road_ids,
                        new_road_ids=[_int_id(feature, "RCSDRoad") for feature in split_result.new_road_features],
                        new_node_ids=new_node_ids,
                        grouped_node_ids=new_node_ids if len(new_node_ids) > 1 else [],
                        selected_main_node_id=primary,
                        projection_point_count=sum(len(items) for items in projected.values()),
                        split_point_count=len(new_node_ids),
                    )
                )
                continue
            relation = failure_relation_feature(context=context)
            relation_features.append(relation)
            audit_rows.append(_audit_row(context=context, decision=decision, relation=relation))

    relation_features, duplicate_blocking_rows, duplicate_audit_rows = _enforce_unique_relation_targets(
        relation_features,
        context_by_target=context_by_target,
    )
    blocking_errors.extend(duplicate_blocking_rows)
    audit_rows.extend(duplicate_audit_rows)

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
            "t03_relation_evidence_path": str(t03_relation_evidence_path) if t03_relation_evidence_path else None,
            "t04_relation_evidence_path": str(t04_relation_evidence_path) if t04_relation_evidence_path else None,
            "t04_surface_path": str(t04_surface_path) if t04_surface_path else None,
            "t04_summary_path": str(t04_summary_path) if t04_summary_path else None,
            "t04_audit_path": str(t04_audit_path) if t04_audit_path else None,
            "t04_case_root": str(t04_case_root) if t04_case_root else None,
        },
        relation_features=relation_features,
        rcsdroad_out_features=[_copy_feature(feature) for feature in roads_by_id.values()],
        rcsdnode_out_features=[_copy_feature(feature) for feature in node_out_by_id.values()],
        split_road_features=split_road_features,
        generated_node_features=generated_node_features,
        grouped_node_features=grouped_node_features,
        audit_rows=audit_rows,
        blocking_errors=blocking_errors,
        original_split_road_ids=original_split_road_ids,
    )
    summary = outputs["summary"]
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
        summary_path=outputs["summary_path"],
        relation_count=summary["intersection_match_all_feature_count"],
        success_count=summary["status_0_count"],
        failure_count=summary["status_1_count"],
    )


def _target_contexts(surfaces: list[dict[str, Any]], swsd_nodes: list[dict[str, Any]]) -> list[SwsdTargetContext]:
    nodes_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in swsd_nodes:
        props = node.get("properties") or {}
        target_id = _text(_field_value(props, "mainnodeid") or _field_value(props, "id"))
        if target_id:
            nodes_by_target[target_id].append(node)
    contexts: list[SwsdTargetContext] = []
    for surface in surfaces:
        props = surface.get("properties") or {}
        target_id = _text(_field_value(props, "mainnodeid"))
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
                level=_minus_one_or_missing(_field_value(rep_props, "grade")),
                is_highway=_minus_one_or_missing(_field_value(rep_props, "closed_con")),
                representative_properties=rep_props,
            )
        )
    return contexts


def _required_path(path: str | Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required for T05 Phase 2.")
    resolved = Path(path)
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist: {resolved}")
    return resolved


def _load_t04_supplements(
    *,
    t04_surface_path: str | Path | None,
    t04_summary_path: str | Path | None,
    t04_audit_path: str | Path | None,
    t04_case_root: str | Path | None,
    crs_override: str | None,
) -> dict[str, dict[str, Any]]:
    supplements: dict[str, dict[str, Any]] = {}
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
            for audit_path in root.glob(f"**/{name}"):
                payload = json.loads(audit_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    if name == "step4_event_interpretation.json":
                        _add_supplement(supplements, _t04_step4_supplement(payload))
                    else:
                        _add_supplement(supplements, payload)
    return supplements


def _merge_t04_supplements(rows: list[dict[str, Any]], supplements: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        for key in (_text(row.get("target_id")), _text(row.get("case_id"))):
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


def _add_supplement(supplements: dict[str, dict[str, Any]], properties: dict[str, Any]) -> None:
    props = dict(properties or {})
    for key in (_text(props.get("target_id") or props.get("mainnodeid")), _text(props.get("case_id"))):
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
        target_counts[_text((feature.get("properties") or {}).get("target_id"))] += 1
    duplicates = {target_id for target_id, count in target_counts.items() if target_id and count > 1}
    if not duplicates:
        return relation_features, [], []
    filtered = [
        feature
        for feature in relation_features
        if _text((feature.get("properties") or {}).get("target_id")) not in duplicates
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


def _semantic_point(nodes: list[dict[str, Any]], surface_geometry: BaseGeometry | None) -> Point:
    points = [_point_of(node.get("geometry")) for node in nodes if node.get("geometry") is not None]
    if points:
        return _point_of(unary_union(points).centroid)
    if surface_geometry is not None and not surface_geometry.is_empty:
        return _point_of(surface_geometry.representative_point())
    return Point(0.0, 0.0)


def _representative_node(nodes: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    for node in nodes:
        if _text(_field_value(node.get("properties") or {}, "id")) == target_id:
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


def _text(value: Any) -> str:
    return str(value or "").strip()
