from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

from .carrier_graph import field_name, normalize_id, parse_ids
from .inputs import LoadedInputs
from .junction_inputs import JunctionSources, T03CaseEvidence
from .models import AuditConfig, T12ContractError


@dataclass(frozen=True)
class JunctionAuditResult:
    candidates: list[dict[str, Any]]
    confirmed: list[dict[str, Any]]
    exclusions: list[dict[str, Any]]
    layers: dict[str, list[dict[str, Any]]]
    audit: dict[str, Any]


def audit_junction_quality(
    loaded: LoadedInputs,
    sources: JunctionSources,
    config: AuditConfig,
    *,
    run_id: str,
) -> JunctionAuditResult:
    if not sources.t03_cases and not sources.t07_rows:
        return JunctionAuditResult(
            candidates=[],
            confirmed=[],
            exclusions=[],
            layers={
                "junction_candidates": [],
                "support_roads": [],
                "target_projections": [],
                "frcsd_endpoints": [],
                "t07_conflict_links": [],
            },
            audit={
                "counts": {
                    "candidate_count": 0,
                    "confirmed_count": 0,
                    "exclusion_count": 0,
                    "t07_ignored_row_count": 0,
                },
                "source_exclusions": {},
                "by_issue_type": {},
                "by_decision_rule": {},
                "eligibility_nodes": {"source": "not_loaded_no_junction_sources"},
                "t03_policy": {"candidate_source": "formal_t03_rejected_only"},
                "t07_policy": {"decision": "stable_failure_direct_publish"},
                "silent_fix": False,
            },
        )
    eligibility_nodes, eligibility_audit = _load_eligibility_nodes(
        sources.t03_eligibility_nodes_path,
        loaded.swsd_nodes,
        loaded.processing_crs,
    )
    eligibility_lookup = _node_lookup(eligibility_nodes)
    output_node_lookup = _node_lookup(loaded.swsd_nodes)
    frcsd_node_lookup = _node_lookup(loaded.frcsd_nodes)
    frcsd_roads = _road_index(loaded.frcsd_roads)
    global_node_degree, global_component_by_road = _global_road_topology(
        loaded.frcsd_roads
    )
    candidates: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    layers: dict[str, list[dict[str, Any]]] = {
        "junction_candidates": [],
        "support_roads": [],
        "target_projections": [],
        "frcsd_endpoints": [],
        "t07_conflict_links": [],
    }
    counters: Counter[str] = Counter()
    source_exclusions: Counter[str] = Counter()

    for case in sources.t03_cases:
        counters["t03_rejected_source_count"] += 1
        source_row = eligibility_lookup.get(case.case_id)
        if source_row is None:
            source_exclusions["missing_t03_eligibility_node"] += 1
            continue
        eligible, eligibility_reason = _formal_t03_eligibility(source_row)
        if not eligible:
            source_exclusions[eligibility_reason] += 1
            continue
        target_ids = parse_ids(case.step3_status.get("target_group_node_ids"))
        if len(target_ids) < 2:
            source_exclusions["target_group_has_fewer_than_two_nodes"] += 1
            continue
        target_rows = [eligibility_lookup.get(node_id) for node_id in target_ids]
        if any(row is None for row in target_rows):
            source_exclusions["target_group_node_missing"] += 1
            continue
        representative = output_node_lookup.get(case.case_id)
        if representative is None:
            representative = source_row
        geometry = representative.geometry
        if geometry is None or geometry.is_empty:
            source_exclusions["representative_point_missing"] += 1
            continue
        row, evidence = _evaluate_t03_case(
            case=case,
            target_ids=target_ids,
            target_rows=[row for row in target_rows if row is not None],
            representative_geometry=geometry,
            loaded=loaded,
            config=config,
            frcsd_roads=frcsd_roads,
            frcsd_node_lookup=frcsd_node_lookup,
            global_node_degree=global_node_degree,
            global_component_by_road=global_component_by_road,
            run_id=run_id,
        )
        candidates.append(row)
        layers["junction_candidates"].append(_point_feature(row))
        for layer_name, layer_rows in evidence.items():
            layers[layer_name].extend(layer_rows)
        if row["review_status"] == "confirmed_frcsd_quality_issue":
            confirmed.append(row)
        else:
            exclusions.append(row)

    t07_ignored = 0
    for source_index, source_row in enumerate(sources.t07_rows):
        error_type = str(source_row.get("error_type") or "")
        if error_type == "duplicate_target_rows":
            t07_ignored += 1
            continue
        if error_type not in {
            "one_target_to_many_base",
            "many_target_to_one_base",
        }:
            t07_ignored += 1
            continue
        target_ids = parse_ids(
            source_row.get("related_target_ids") or source_row.get("target_id")
        )
        base_ids = parse_ids(source_row.get("base_id"))
        if not target_ids or not base_ids:
            raise T12ContractError(
                "T07 stable cardinality error has empty target/base IDs: "
                f"row={source_index}"
            )
        conflict_group_id = _conflict_group_id(error_type, target_ids, base_ids)
        target_points: list[Point] = []
        for target_id in target_ids:
            node_row = output_node_lookup.get(target_id)
            if node_row is None or node_row.geometry is None or node_row.geometry.is_empty:
                raise T12ContractError(
                    f"T07 cardinality target is missing from SWSD Nodes: {target_id}"
                )
            point = Point(node_row.geometry)
            target_points.append(point)
            row = _t07_row(
                run_id=run_id,
                target_id=target_id,
                target_ids=target_ids,
                base_ids=base_ids,
                error_type=error_type,
                conflict_group_id=conflict_group_id,
                source_row=source_row,
                geometry=point,
            )
            candidates.append(row)
            confirmed.append(row)
            layers["junction_candidates"].append(_point_feature(row))
            counters[f"t07_{error_type}_junction_count"] += 1
        if len(target_points) > 1:
            layers["t07_conflict_links"].append(
                {
                    "conflict_group_id": conflict_group_id,
                    "detection_rule": error_type,
                    "target_ids": target_ids,
                    "base_ids": base_ids,
                    "geometry": LineString(target_points),
                }
            )

    counters["t07_ignored_row_count"] = t07_ignored
    counters["candidate_count"] = len(candidates)
    counters["confirmed_count"] = len(confirmed)
    counters["exclusion_count"] = len(exclusions)
    if len(candidates) != len(confirmed) + len(exclusions):
        raise T12ContractError("Junction result counts do not conserve")
    return JunctionAuditResult(
        candidates=candidates,
        confirmed=confirmed,
        exclusions=exclusions,
        layers=layers,
        audit={
            "counts": dict(sorted(counters.items())),
            "source_exclusions": dict(sorted(source_exclusions.items())),
            "by_issue_type": _count_by(confirmed, "issue_type"),
            "by_decision_rule": _count_by(candidates, "decision_rule"),
            "eligibility_nodes": eligibility_audit,
            "t03_policy": {
                "candidate_source": "formal_t03_rejected_only",
                "formal_eligibility": {
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": [4, 2048],
                },
                "target_projection_source": "original_1v1_frcsd_road_node",
                "distance_role": "audit_only",
                "alias_role": "semantic_group_only_no_graph_edge",
            },
            "t07_policy": {
                "decision": "stable_failure_direct_publish",
                "published_error_types": [
                    "one_target_to_many_base",
                    "many_target_to_one_base",
                ],
                "ignored_error_types": ["duplicate_target_rows"],
            },
            "silent_fix": False,
        },
    )


def _evaluate_t03_case(
    *,
    case: T03CaseEvidence,
    target_ids: list[str],
    target_rows: list[pd.Series],
    representative_geometry: Any,
    loaded: LoadedInputs,
    config: AuditConfig,
    frcsd_roads: Mapping[str, pd.Series],
    frcsd_node_lookup: Mapping[str, pd.Series],
    global_node_degree: Mapping[str, int],
    global_component_by_road: Mapping[str, int],
    run_id: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    association = case.association_status
    step6 = case.step6_status
    association_class = str(
        association.get("association_class")
        or step6.get("association_class")
        or ""
    )
    association_state = str(
        association.get("association_state")
        or step6.get("association_state")
        or ""
    )
    required_node_ids = _ids_from(
        association,
        step6,
        keys=("required_rcsdnode_ids",),
    )
    required_node_count_value = _find_first(
        (association, step6, case.step6_audit),
        "required_rcsdnode_count",
    )
    required_node_count = (
        _as_int(required_node_count_value, default=len(required_node_ids))
        if required_node_count_value is not None
        else len(required_node_ids)
    )
    if association_class == "B" and not required_node_ids:
        required_node_count = 0
    support_ids = _ids_from(
        association,
        step6,
        keys=("support_rcsdroad_ids",),
    )
    support_source = "t03_published_support_ids"
    target_points = [Point(row.geometry) for row in target_rows]
    missing_support_ids = [road_id for road_id in support_ids if road_id not in frcsd_roads]
    if missing_support_ids:
        support_ids = []
    if (
        not support_ids
        and association_class == "B"
        and association_state == "not_established"
    ):
        nearest_support_ids = _nearest_road_ids(target_points, frcsd_roads)
        support_ids = _terminal_collapse_support_ids(
            target_points=target_points,
            roads=frcsd_roads,
            node_lookup=frcsd_node_lookup,
            seed_road_ids=nearest_support_ids,
            endpoint_tolerance_m=config.junction_endpoint_tolerance_m,
            local_radius_m=config.junction_local_radius_m,
        )
        if support_ids:
            support_source = (
                "t12_recomputed_terminal_collapse_support_from_nearest_endpoint"
            )
        else:
            support_ids = nearest_support_ids
            support_source = "t12_recomputed_nearest_raw_frcsd"
    if not support_ids and association_class == "B":
        support_ids = _nearest_road_ids(target_points, frcsd_roads)
        support_source = "t12_recomputed_nearest_raw_frcsd"
    support_rows = [frcsd_roads[road_id] for road_id in support_ids if road_id in frcsd_roads]
    support_component_by_road, support_degree = _support_topology(support_rows)
    projections = _target_projections(
        target_ids=target_ids,
        target_points=target_points,
        support_rows=support_rows,
        support_component_by_road=support_component_by_road,
        support_degree=support_degree,
        frcsd_node_lookup=frcsd_node_lookup,
        endpoint_tolerance_m=config.junction_endpoint_tolerance_m,
    )
    projection_components = sorted(
        {
            int(row["component_id"])
            for row in projections
            if row.get("component_id") is not None
        }
    )
    support_components = sorted(set(support_component_by_road.values()))
    unmatched_components = sorted(set(support_components) - set(projection_components))
    terminal_endpoint_ids = {
        str(row.get("endpoint_node_id") or "")
        for row in projections
        if row.get("projection_mode") == "terminal_endpoint"
    } - {""}
    all_terminal = bool(projections) and all(
        row.get("projection_mode") == "terminal_endpoint" for row in projections
    )
    shared_terminal = (
        next(iter(terminal_endpoint_ids))
        if all_terminal and len(terminal_endpoint_ids) == 1
        else ""
    )
    terminal_degree = (
        int(projections[0].get("endpoint_support_degree") or 0)
        if shared_terminal
        else 0
    )
    global_terminal_degree = int(global_node_degree.get(shared_terminal, 0))
    local_component_by_road = _local_component_by_road(
        roads=frcsd_roads,
        point=Point(representative_geometry),
        radius_m=config.junction_local_radius_m,
    )
    full_components = {
        local_component_by_road[road_id]
        for road_id in support_ids
        if road_id in local_component_by_road
    }
    alternate_raw_carrier = (
        terminal_degree > 1
        if shared_terminal
        else (
            len(support_components) >= 2
            and len(full_components) == 1
            and all(road_id in local_component_by_road for road_id in support_ids)
        )
    )
    direction_status = _direction_status(support_rows)
    local_invalid_drivezone = _local_invalid_drivezone_count(
        loaded.drivezone,
        representative_geometry,
        config.junction_local_radius_m,
    )
    step3_invalid = _as_int(
        _find_first(
            (case.step3_status,),
            "drivezone_input_invalid_feature_count",
        ),
        default=0,
    )
    input_geometry_status = (
        "invalid_geometry_blocked"
        if local_invalid_drivezone or step3_invalid
        else "valid_no_normalization"
    )
    cross_layer_status, cross_layer_evidence = _cross_layer_status(
        loaded=loaded,
        selected_road_ids=parse_ids(case.step3_status.get("selected_road_ids")),
        representative_geometry=representative_geometry,
        radius_m=config.junction_local_radius_m,
    )
    formal_cross_layer = str(
        _find_first(
            (case.step6_audit, case.step6_status, case.step7_audit),
            "cross_layer_status",
        )
        or ""
    ).strip().lower()
    if formal_cross_layer in {
        "high_confidence_cross_layer",
        "confirmed_cross_layer",
    }:
        cross_layer_status = "high_confidence_cross_layer"
        cross_layer_evidence["formal_cross_layer_status"] = formal_cross_layer
    constraint_value = _find_first(
        (case.step6_audit, case.step6_status),
        "constraint_induced_split",
    )
    constraint_induced_split = _as_bool(constraint_value)
    step6_reason = str(step6.get("reason") or "")
    meaningful_component_count = _as_int(
        _find_first(
            (case.step6_audit, case.step6_status),
            "pre_business_cleanup_meaningful_component_count",
        ),
        default=0,
    )
    rule_a = (
        association_class == "B"
        and association_state == "not_established"
        and required_node_count == 0
        and len(target_ids) >= 2
        and all_terminal
        and bool(shared_terminal)
        and terminal_degree == 1
        and not alternate_raw_carrier
    )
    rule_b = (
        association_class == "B"
        and association_state == "review"
        and required_node_count == 0
        and len(support_components) >= 2
        and len(target_ids) >= 2
        and len(projection_components) == 1
        and bool(unmatched_components)
        and step6_reason == "step6_support_only_multi_target_fragmented_surface"
        and meaningful_component_count >= 3
        and constraint_value is not None
        and not constraint_induced_split
        and not alternate_raw_carrier
    )
    blockers: list[str] = []
    if input_geometry_status != "valid_no_normalization":
        blockers.append("invalid_input_geometry")
    if cross_layer_status == "high_confidence_cross_layer":
        blockers.append("cross_layer_evidence")
    if direction_status != "valid_strict_direction":
        blockers.append("invalid_road_direction")
    confirmed = (rule_a or rule_b) and not blockers
    if confirmed and rule_a:
        detection_rule = "shared_degree1_terminal_collapse"
        issue_type = "junction_required_topology_missing"
        decision_rule = "raw_frcsd_shared_degree1_terminal_collapse_confirmed"
        review_reason = (
            "all SWSD targets collapse to one degree-1 raw FRCSD terminal; "
            "no physical alternative carrier exists"
        )
    elif confirmed:
        detection_rule = "multi_component_unmatched_support"
        issue_type = "junction_reality_or_precision_gap"
        decision_rule = "raw_frcsd_multi_component_unmatched_support_confirmed"
        review_reason = (
            "all SWSD targets explain only one raw FRCSD support component while "
            "other meaningful components remain unmatched"
        )
    else:
        detection_rule = (
            "shared_degree1_terminal_collapse"
            if rule_a
            else (
                "multi_component_unmatched_support"
                if rule_b
                else "t03_rejected_insufficient_junction_evidence"
            )
        )
        issue_type = ""
        decision_rule = _exclusion_rule(
            blockers=blockers,
            constraint_value=constraint_value,
            constraint_induced_split=constraint_induced_split,
            meaningful_component_count=meaningful_component_count,
            projections=projections,
            alternate_raw_carrier=alternate_raw_carrier,
        )
        review_reason = decision_rule
    row = {
        "run_id": run_id,
        "candidate_id": f"junction:t03:{case.case_id}",
        "object_type": "junction",
        "junction_id": case.case_id,
        "target_group_node_ids": target_ids,
        "candidate_status": "candidate_pending_decision",
        "review_status": (
            "confirmed_frcsd_quality_issue"
            if confirmed
            else "excluded_false_positive"
        ),
        "issue_type": issue_type,
        "detection_rule": detection_rule,
        "decision_rule": decision_rule,
        "association_class": association_class,
        "association_state": association_state,
        "required_rcsdnode_ids": required_node_ids,
        "support_rcsdroad_ids": support_ids,
        "support_id_source": support_source,
        "support_topology_component_count": len(support_components),
        "target_projection_component_ids": projection_components,
        "unmatched_support_component_ids": unmatched_components,
        "target_projection_rows": projections,
        "shared_terminal_endpoint_id": shared_terminal,
        "shared_terminal_endpoint_degree": terminal_degree or "",
        "raw_frcsd_terminal_degree": global_terminal_degree or "",
        "constraint_induced_split": (
            constraint_induced_split if constraint_value is not None else ""
        ),
        "cross_layer_status": cross_layer_status,
        "cross_layer_evidence": cross_layer_evidence,
        "input_geometry_status": input_geometry_status,
        "invalid_drivezone_feature_count": local_invalid_drivezone,
        "raw_frcsd_verification_status": (
            "no_equivalent_local_physical_carrier"
            if not alternate_raw_carrier
            else "equivalent_local_physical_carrier_exists"
        ),
        "direction_status": direction_status,
        "step6_reason": step6_reason,
        "pre_business_cleanup_meaningful_component_count": meaningful_component_count,
        "review_reason": review_reason,
        "decision_source": "automatic_high_confidence",
        "source_module": "T03",
        "source_case_id": case.case_id,
        "conflict_group_id": "",
        "silent_fix": False,
        "geometry": Point(representative_geometry),
    }
    evidence = {
        "support_roads": [
            {
                "candidate_id": row["candidate_id"],
                "junction_id": case.case_id,
                "road_id": road_id,
                "component_id": support_component_by_road.get(road_id, ""),
                "direction": _road_direction(frcsd_roads[road_id]),
                "geometry": frcsd_roads[road_id].geometry,
            }
            for road_id in support_ids
            if road_id in frcsd_roads
        ],
        "target_projections": [
            _projection_feature(row["candidate_id"], projection)
            for projection in projections
        ],
        "frcsd_endpoints": [],
    }
    if shared_terminal and shared_terminal in frcsd_node_lookup:
        evidence["frcsd_endpoints"].append(
            {
                "candidate_id": row["candidate_id"],
                "junction_id": case.case_id,
                "node_id": shared_terminal,
                "support_degree": terminal_degree,
                "raw_frcsd_degree": global_terminal_degree,
                "geometry": frcsd_node_lookup[shared_terminal].geometry,
            }
        )
    for projection in row["target_projection_rows"]:
        projection.pop("_geometry", None)
    return row, evidence


def _t07_row(
    *,
    run_id: str,
    target_id: str,
    target_ids: list[str],
    base_ids: list[str],
    error_type: str,
    conflict_group_id: str,
    source_row: Mapping[str, Any],
    geometry: Point,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "candidate_id": (
            f"junction:t07:{error_type}:{conflict_group_id}:{target_id}"
        ),
        "object_type": "junction",
        "junction_id": target_id,
        "target_group_node_ids": target_ids,
        "candidate_status": "candidate_pending_decision",
        "review_status": "confirmed_frcsd_quality_issue",
        "issue_type": "junction_relation_cardinality_mismatch",
        "detection_rule": error_type,
        "decision_rule": f"t07_stable_{error_type}_direct_publish",
        "association_class": "",
        "association_state": "",
        "required_rcsdnode_ids": [],
        "support_rcsdroad_ids": [],
        "support_id_source": "",
        "support_topology_component_count": "",
        "target_projection_component_ids": [],
        "unmatched_support_component_ids": [],
        "target_projection_rows": [],
        "shared_terminal_endpoint_id": "",
        "shared_terminal_endpoint_degree": "",
        "raw_frcsd_terminal_degree": "",
        "constraint_induced_split": "",
        "cross_layer_status": "not_applicable_t07_direct_publish",
        "cross_layer_evidence": {},
        "input_geometry_status": "not_applicable_t07_direct_publish",
        "invalid_drivezone_feature_count": 0,
        "raw_frcsd_verification_status": "not_rejudged_t07_stable_failure",
        "direction_status": "not_applicable_t07_direct_publish",
        "step6_reason": "",
        "pre_business_cleanup_meaningful_component_count": "",
        "review_reason": (
            f"T07 stable relation cardinality failure {error_type}; "
            "published without T12 rejudgment"
        ),
        "decision_source": "t07_stable_failure_direct",
        "source_module": "T07",
        "source_case_id": str(source_row.get("source_case_ids") or ""),
        "base_ids": base_ids,
        "source_modules": str(source_row.get("source_modules") or ""),
        "scenes": str(source_row.get("scenes") or ""),
        "conflict_group_id": conflict_group_id,
        "silent_fix": False,
        "geometry": geometry,
    }


def _formal_t03_eligibility(row: pd.Series) -> tuple[bool, str]:
    has_evd = str(_row_value(row, "has_evd") or "").strip().lower()
    is_anchor = str(_row_value(row, "is_anchor") or "").strip().lower()
    kind_2 = _as_int(_row_value(row, "kind_2"), default=-1)
    if has_evd != "yes":
        return False, "formal_eligibility_has_evd_not_yes"
    if is_anchor != "no":
        return False, "formal_eligibility_is_anchor_not_no"
    if kind_2 not in {4, 2048}:
        return False, "formal_eligibility_kind_2_out_of_scope"
    return True, "formal_eligibility_passed"


def _load_eligibility_nodes(
    source_path: Path | None,
    fallback: gpd.GeoDataFrame,
    processing_crs: str,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    if source_path is None:
        return fallback, {
            "source": "t12_swsd_nodes_fallback",
            "row_count": len(fallback),
            "processing_crs": processing_crs,
        }
    frame = gpd.read_file(source_path)
    if frame.crs is None:
        raise T12ContractError(f"T03 eligibility Nodes has no CRS: {source_path}")
    source_crs = CRS.from_user_input(frame.crs)
    target_crs = CRS.from_user_input(processing_crs)
    transformed = source_crs != target_crs
    if transformed:
        frame = frame.to_crs(target_crs)
    return frame, {
        "source": "t03_run_preflight_nodes",
        "path": str(source_path),
        "row_count": len(frame),
        "input_crs": source_crs.to_string(),
        "processing_crs": target_crs.to_string(),
        "transform_applied": transformed,
    }


def _node_lookup(frame: gpd.GeoDataFrame) -> dict[str, pd.Series]:
    id_field = field_name(frame, "id")
    lookup: dict[str, pd.Series] = {}
    for _, row in frame.iterrows():
        node_id = normalize_id(row[id_field])
        if node_id:
            lookup[node_id] = row
    return lookup


def _road_index(frame: gpd.GeoDataFrame) -> dict[str, pd.Series]:
    id_field = field_name(frame, "id")
    return {
        normalize_id(row[id_field]): row
        for _, row in frame.iterrows()
        if normalize_id(row[id_field])
    }


def _global_road_topology(
    roads: gpd.GeoDataFrame,
) -> tuple[dict[str, int], dict[str, int]]:
    rows = [row for _, row in roads.iterrows()]
    component_by_road, degree = _support_topology(rows)
    return degree, component_by_road


def _support_topology(
    rows: Iterable[pd.Series],
) -> tuple[dict[str, int], dict[str, int]]:
    rows = list(rows)
    if not rows:
        return {}, {}
    id_field = field_name(pd.DataFrame(rows), "id")
    start_field = field_name(pd.DataFrame(rows), "snodeid")
    end_field = field_name(pd.DataFrame(rows), "enodeid")
    node_to_roads: defaultdict[str, set[str]] = defaultdict(set)
    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    road_ids: list[str] = []
    for row in rows:
        road_id = normalize_id(row[id_field])
        road_ids.append(road_id)
        for field in (start_field, end_field):
            node_id = normalize_id(row[field])
            if node_id:
                node_to_roads[node_id].add(road_id)
    for values in node_to_roads.values():
        for road_id in values:
            adjacency[road_id].update(values - {road_id})
    component_by_road: dict[str, int] = {}
    for road_id in sorted(road_ids, key=_id_key):
        if road_id in component_by_road:
            continue
        component_id = len(set(component_by_road.values()))
        pending = [road_id]
        while pending:
            current = pending.pop()
            if current in component_by_road:
                continue
            component_by_road[current] = component_id
            pending.extend(adjacency[current] - set(component_by_road))
    return component_by_road, {
        node_id: len(values) for node_id, values in node_to_roads.items()
    }


def _target_projections(
    *,
    target_ids: list[str],
    target_points: list[Point],
    support_rows: list[pd.Series],
    support_component_by_road: Mapping[str, int],
    support_degree: Mapping[str, int],
    frcsd_node_lookup: Mapping[str, pd.Series],
    endpoint_tolerance_m: float,
) -> list[dict[str, Any]]:
    if not support_rows:
        return []
    table = pd.DataFrame(support_rows)
    road_id_field = field_name(table, "id")
    start_field = field_name(table, "snodeid")
    end_field = field_name(table, "enodeid")
    output: list[dict[str, Any]] = []
    for target_id, target_point in zip(target_ids, target_points):
        nearest = min(
            support_rows,
            key=lambda row: (
                float(row.geometry.distance(target_point)),
                _id_key(normalize_id(row[road_id_field])),
            ),
        )
        road_id = normalize_id(nearest[road_id_field])
        projected = nearest_points(target_point, nearest.geometry)[1]
        endpoint_candidates: list[tuple[float, str]] = []
        for field in (start_field, end_field):
            node_id = normalize_id(nearest[field])
            node = frcsd_node_lookup.get(node_id)
            if node is not None and node.geometry is not None and not node.geometry.is_empty:
                endpoint_candidates.append(
                    (float(projected.distance(node.geometry)), node_id)
                )
        endpoint_candidates.sort(key=lambda item: (item[0], _id_key(item[1])))
        endpoint_id = ""
        endpoint_degree: int | None = None
        projection_mode = "interior"
        if endpoint_candidates and endpoint_candidates[0][0] <= endpoint_tolerance_m:
            endpoint_id = endpoint_candidates[0][1]
            endpoint_degree = int(support_degree.get(endpoint_id, 0))
            projection_mode = (
                "terminal_endpoint"
                if endpoint_degree == 1
                else "shared_endpoint"
            )
        output.append(
            {
                "target_node_id": target_id,
                "nearest_road_id": road_id,
                "distance_m": round(float(target_point.distance(nearest.geometry)), 6),
                "component_id": support_component_by_road.get(road_id),
                "projection_mode": projection_mode,
                "endpoint_node_id": endpoint_id,
                "endpoint_support_degree": endpoint_degree,
                "_geometry": projected,
            }
        )
    return output


def _nearest_road_ids(
    points: list[Point],
    roads: Mapping[str, pd.Series],
) -> list[str]:
    if not roads:
        return []
    return list(
        dict.fromkeys(
            min(
                roads.items(),
                key=lambda item: (
                    float(item[1].geometry.distance(point)),
                    _id_key(item[0]),
                ),
            )[0]
            for point in points
        )
    )


def _terminal_collapse_support_ids(
    *,
    target_points: list[Point],
    roads: Mapping[str, pd.Series],
    node_lookup: Mapping[str, pd.Series],
    seed_road_ids: list[str],
    endpoint_tolerance_m: float,
    local_radius_m: float,
) -> list[str]:
    seed_endpoint_ids = {
        normalize_id(_row_value(roads[road_id], field))
        for road_id in seed_road_ids
        if road_id in roads
        for field in ("snodeid", "enodeid")
    } - {""}
    candidates: list[tuple[float, float, tuple[int, int | str], str]] = []
    for road_id, row in roads.items():
        if _road_direction(row) not in {0, 1, 2, 3}:
            continue
        start_id = normalize_id(_row_value(row, "snodeid"))
        end_id = normalize_id(_row_value(row, "enodeid"))
        if not ({start_id, end_id} & seed_endpoint_ids):
            continue
        endpoints = {
            node_id: node_lookup[node_id].geometry
            for node_id in (start_id, end_id)
            if node_id in node_lookup
            and node_lookup[node_id].geometry is not None
            and not node_lookup[node_id].geometry.is_empty
        }
        if len(endpoints) != 2:
            continue
        selected_endpoint_ids: list[str] = []
        target_distances: list[float] = []
        for point in target_points:
            projected = nearest_points(point, row.geometry)[1]
            endpoint_distance, endpoint_id = min(
                (
                    (float(projected.distance(endpoint)), node_id)
                    for node_id, endpoint in endpoints.items()
                ),
                key=lambda item: (item[0], _id_key(item[1])),
            )
            if endpoint_distance > endpoint_tolerance_m:
                selected_endpoint_ids = []
                break
            selected_endpoint_ids.append(endpoint_id)
            target_distances.append(float(point.distance(row.geometry)))
        if (
            selected_endpoint_ids
            and len(set(selected_endpoint_ids)) == 1
            and len(selected_endpoint_ids) == len(target_points)
            and selected_endpoint_ids[0] in seed_endpoint_ids
            and max(target_distances) <= local_radius_m
        ):
            candidates.append(
                (
                    max(target_distances),
                    sum(target_distances),
                    _id_key(road_id),
                    road_id,
                )
            )
    return [min(candidates)[3]] if candidates else []


def _local_component_by_road(
    *,
    roads: Mapping[str, pd.Series],
    point: Point,
    radius_m: float,
) -> dict[str, int]:
    window = point.buffer(radius_m)
    local_rows = [
        row
        for row in roads.values()
        if row.geometry is not None
        and not row.geometry.is_empty
        and row.geometry.intersects(window)
    ]
    component_by_road, _ = _support_topology(local_rows)
    return component_by_road


def _direction_status(rows: Iterable[pd.Series]) -> str:
    values = {_road_direction(row) for row in rows}
    return (
        "valid_strict_direction"
        if values and values.issubset({0, 1, 2, 3})
        else "invalid_or_missing_direction"
    )


def _road_direction(row: pd.Series) -> int:
    value = _row_value(row, "direction")
    return _as_int(value, default=-1)


def _local_invalid_drivezone_count(
    drivezone: gpd.GeoDataFrame | None,
    point: Point,
    radius_m: float,
) -> int:
    if drivezone is None or drivezone.empty:
        return 0
    minx, miny, maxx, maxy = point.buffer(radius_m).bounds
    count = 0
    for geometry in drivezone.geometry:
        if geometry is None or geometry.is_empty or geometry.is_valid:
            continue
        gx1, gy1, gx2, gy2 = geometry.bounds
        if gx2 >= minx and gx1 <= maxx and gy2 >= miny and gy1 <= maxy:
            count += 1
    return count


def _cross_layer_status(
    *,
    loaded: LoadedInputs,
    selected_road_ids: list[str],
    representative_geometry: Point,
    radius_m: float,
) -> tuple[str, dict[str, Any]]:
    patch_field = _optional_field(
        loaded.swsd_roads,
        "patch_id",
        "patchid",
        "mesh_id",
        "meshcode",
        "mesh_code",
    )
    road_id_field = field_name(loaded.swsd_roads, "id")
    selected = loaded.swsd_roads.loc[
        loaded.swsd_roads[road_id_field].map(normalize_id).isin(selected_road_ids)
    ]
    patches: set[str] = set()
    if patch_field:
        for value in selected[patch_field]:
            patches.update(_parts(value))
    direct_overlap_pairs: list[list[str]] = []
    drivezone_patch_field = (
        _optional_field(
            loaded.drivezone,
            "patch_id",
            "patchid",
            "mesh_id",
            "meshcode",
            "mesh_code",
        )
        if loaded.drivezone is not None
        else ""
    )
    if loaded.drivezone is not None and drivezone_patch_field:
        window = representative_geometry.buffer(radius_m)
        valid_drivezone = loaded.drivezone.loc[
            loaded.drivezone.geometry.is_valid
        ]
        local = valid_drivezone.loc[
            valid_drivezone.geometry.intersects(window)
        ]
        local_rows = [row for _, row in local.iterrows()]
        for index, left in enumerate(local_rows):
            left_ids = _parts(left[drivezone_patch_field])
            for right in local_rows[index + 1 :]:
                right_ids = _parts(right[drivezone_patch_field])
                if not left_ids or not right_ids or left_ids == right_ids:
                    continue
                if float(left.geometry.intersection(right.geometry).area) > 0.05:
                    direct_overlap_pairs.append(
                        [
                            "|".join(sorted(left_ids, key=_id_key)),
                            "|".join(sorted(right_ids, key=_id_key)),
                        ]
                    )
    detected = len(patches) > 1 or bool(direct_overlap_pairs)
    return (
        (
            "audit_only_patch_overlap_observed"
            if detected
            else "no_formal_high_confidence_cross_layer_evidence"
        ),
        {
            "selected_swsd_patch_ids": sorted(patches, key=_id_key),
            "selected_swsd_patch_count": len(patches),
            "drivezone_direct_overlap_patch_pairs": direct_overlap_pairs,
            "distance_only_not_used": True,
        },
    )


def _exclusion_rule(
    *,
    blockers: list[str],
    constraint_value: Any,
    constraint_induced_split: bool,
    meaningful_component_count: int,
    projections: list[dict[str, Any]],
    alternate_raw_carrier: bool,
) -> str:
    if "invalid_input_geometry" in blockers:
        return "invalid_input_geometry"
    if "cross_layer_evidence" in blockers:
        return "high_confidence_cross_layer_excluded"
    if "invalid_road_direction" in blockers:
        return "invalid_road_direction"
    if constraint_value is not None and constraint_induced_split:
        return "constraint_induced_split"
    if meaningful_component_count and meaningful_component_count < 3:
        return "geometry_fragment_only"
    if alternate_raw_carrier:
        return "equivalent_local_physical_carrier"
    if projections and any(
        row.get("projection_mode") != "terminal_endpoint" for row in projections
    ):
        return "not_all_targets_terminal_endpoint"
    return "insufficient_junction_evidence"


def _point_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "junction_id": row["junction_id"],
        "source_module": row["source_module"],
        "review_status": row["review_status"],
        "issue_type": row["issue_type"],
        "detection_rule": row["detection_rule"],
        "decision_rule": row["decision_rule"],
        "conflict_group_id": row.get("conflict_group_id", ""),
        "geometry": row["geometry"],
    }


def _projection_feature(
    candidate_id: str,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        **{
            key: value
            for key, value in projection.items()
            if key != "_geometry"
        },
        "geometry": projection["_geometry"],
    }


def _conflict_group_id(
    error_type: str,
    target_ids: list[str],
    base_ids: list[str],
) -> str:
    payload = json.dumps(
        {
            "error_type": error_type,
            "target_ids": sorted(target_ids, key=_id_key),
            "base_ids": sorted(base_ids, key=_id_key),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _ids_from(
    *documents: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[str]:
    for key in keys:
        for document in documents:
            value = _find_first((document,), key)
            if value not in (None, "", []):
                return parse_ids(value)
    return []


def _find_first(documents: Iterable[Any], key: str) -> Any:
    for document in documents:
        value = _find_recursive(document, key)
        if value is not None:
            return value
    return None


def _find_recursive(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_recursive(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_recursive(child, key)
            if found is not None:
                return found
    return None


def _row_value(row: pd.Series, name: str) -> Any:
    by_lower = {str(key).lower(): key for key in row.index}
    key = by_lower.get(name.lower())
    return row[key] if key is not None else None


def _optional_field(frame: pd.DataFrame | None, *names: str) -> str:
    if frame is None:
        return ""
    by_lower = {str(column).lower(): str(column) for column in frame.columns}
    for name in names:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return ""


def _parts(value: Any) -> set[str]:
    text = str(value or "").replace(",", "|")
    return {part.strip() for part in text.split("|") if part.strip()}


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)
