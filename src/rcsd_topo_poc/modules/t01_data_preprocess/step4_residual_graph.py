from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import (
    build_endpoint_pool_source_map,
    collect_endpoint_pool_mainnodes,
    write_endpoint_pool_outputs,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes_and_roads,
    _load_nodes,
    _load_roads,
    _road_flow_flags_for_group,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    SemanticNodeRecord,
    _coerce_int,
    _find_repo_root,
    _normalize_id,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    ACTIVE_CLOSED_CON_VALUES,
    WORKING_NODE_FIELDS,
    WORKING_ROAD_FIELDS,
    is_active_closed_con,
    is_allowed_road_kind,
    is_full_through_or_t_kind,
    is_roundabout_mainnode_kind,
)


DEFAULT_RUN_ID_PREFIX = "t01_step4_residual_graph_"
STEP4_NEW_SEGMENT_GRADE = "0-1\u53cc"
STEP4_STRATEGY_ID = "STEP4"
STEP4_TARGET_CASES = (
    "785324__502866811",
    "784901__40237259",
    "788837__784901",
    "40237227__785217",
    "55225313__785217",
    "792579__55225234",
)


@dataclass(frozen=True)
class Step4Artifacts:
    out_root: Path
    step4_dir: Path
    refreshed_nodes_path: Path
    refreshed_roads_path: Path
    summary_path: Path
    mainnode_table_path: Path
    summary: dict[str, Any]


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_step4_residual_graph" / resolved_run_id, resolved_run_id


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _write_boundary_node_outputs(
    *,
    out_root: Path,
    nodes: list[NodeFeatureRecord],
    boundary_source_map: dict[str, tuple[str, ...]],
) -> Optional[Path]:
    if not boundary_source_map:
        return None

    features: list[dict[str, Any]] = []
    seen_mainnodes: set[str] = set()
    for node in nodes:
        mainnode_id = node.semantic_node_id
        if mainnode_id not in boundary_source_map or mainnode_id in seen_mainnodes:
            continue
        seen_mainnodes.add(mainnode_id)
        props = dict(node.properties)
        props["mainnode_id"] = mainnode_id
        props["boundary_sources"] = list(boundary_source_map[mainnode_id])
        features.append({"properties": props, "geometry": node.geometry})

    out_path = out_root / "historical_boundary_nodes.geojson"
    write_geojson(out_path, features)
    return out_path


def _build_target_case_audit(
    *,
    out_root: Path,
    target_cases: tuple[str, ...],
    candidate_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    nodes: list[NodeFeatureRecord],
    rule_audit_rows: list[dict[str, Any]],
    search_audit: dict[str, Any],
) -> Path:
    candidate_map = {str(row["pair_id"]).split(":", 1)[1]: row for row in candidate_rows}
    validation_map = {str(row["pair_id"]).split(":", 1)[1]: row for row in validation_rows}
    node_by_id = {node.node_id: node for node in nodes}
    rule_audit_by_node_id = {_normalize_id(row.get("node_id")): row for row in rule_audit_rows}
    search_events = list(search_audit.get("search_events") or [])
    search_started_node_ids = {
        _normalize_id(event.get("seed_node_id"))
        for event in search_events
        if _normalize_id(event.get("seed_node_id")) is not None
    }

    payload: dict[str, Any] = {"cases": []}
    for case_id in target_cases:
        a_node_id, b_node_id = case_id.split("__", 1)
        reverse_case_id = f"{b_node_id}__{a_node_id}"
        matched_case_id = case_id
        if (
            case_id not in validation_map
            and case_id not in candidate_map
            and (reverse_case_id in validation_map or reverse_case_id in candidate_map)
        ):
            matched_case_id = reverse_case_id
        case_payload: dict[str, Any] = {
            "case_id": case_id,
            "candidate_generated": matched_case_id in candidate_map or matched_case_id in validation_map,
            "validated_status": None,
            "reject_reason": None,
            "matched_pair_id": matched_case_id if matched_case_id != case_id else case_id,
            "matched_reversed_pair": matched_case_id != case_id,
            "endpoint_a_exists": a_node_id in node_by_id,
            "endpoint_b_exists": b_node_id in node_by_id,
            "endpoint_a_input_eligible": False,
            "endpoint_b_input_eligible": False,
            "endpoint_a_historical_boundary": False,
            "endpoint_b_historical_boundary": False,
            "endpoint_a_seed_match": False,
            "endpoint_b_seed_match": False,
            "endpoint_a_terminate_match": False,
            "endpoint_b_terminate_match": False,
            "endpoint_a_search_started": False,
            "endpoint_b_search_started": False,
        }
        if a_node_id in node_by_id:
            node = node_by_id[a_node_id]
            case_payload["endpoint_a_input_eligible"] = bool(node.properties.get("step4_input_eligible"))
            case_payload["endpoint_a_historical_boundary"] = bool(
                node.properties.get("step4_historical_boundary")
            )
            case_payload["endpoint_a_grade_2"] = _current_grade_2(node)
            case_payload["endpoint_a_kind_2"] = _current_kind_2(node)
            case_payload["endpoint_a_closed_con"] = _current_closed_con(node)
            case_payload["endpoint_a_search_started"] = a_node_id in search_started_node_ids
        if b_node_id in node_by_id:
            node = node_by_id[b_node_id]
            case_payload["endpoint_b_input_eligible"] = bool(node.properties.get("step4_input_eligible"))
            case_payload["endpoint_b_historical_boundary"] = bool(
                node.properties.get("step4_historical_boundary")
            )
            case_payload["endpoint_b_grade_2"] = _current_grade_2(node)
            case_payload["endpoint_b_kind_2"] = _current_kind_2(node)
            case_payload["endpoint_b_closed_con"] = _current_closed_con(node)
            case_payload["endpoint_b_search_started"] = b_node_id in search_started_node_ids

        if a_node_id in rule_audit_by_node_id:
            row = rule_audit_by_node_id[a_node_id]
            case_payload["endpoint_a_seed_match"] = bool(row.get("seed_match"))
            case_payload["endpoint_a_terminate_match"] = bool(row.get("terminate_match"))
            case_payload["endpoint_a_seed_reasons"] = row.get("seed_reasons") or []
            case_payload["endpoint_a_terminate_reasons"] = row.get("terminate_reasons") or []
        if b_node_id in rule_audit_by_node_id:
            row = rule_audit_by_node_id[b_node_id]
            case_payload["endpoint_b_seed_match"] = bool(row.get("seed_match"))
            case_payload["endpoint_b_terminate_match"] = bool(row.get("terminate_match"))
            case_payload["endpoint_b_seed_reasons"] = row.get("seed_reasons") or []
            case_payload["endpoint_b_terminate_reasons"] = row.get("terminate_reasons") or []

        if matched_case_id in validation_map:
            row = validation_map[matched_case_id]
            case_payload["validated_status"] = row.get("validated_status")
            case_payload["reject_reason"] = row.get("reject_reason")
            support_info = row.get("support_info")
            case_payload["support_info"] = json.loads(support_info) if support_info else {}
        elif matched_case_id in candidate_map:
            case_payload["validated_status"] = "candidate_only"
            support_info = candidate_map[matched_case_id].get("support_info")
            case_payload["support_info"] = json.loads(support_info) if support_info else {}
        else:
            relevant_events = [
                event
                for event in search_events
                if _normalize_id(event.get("seed_node_id")) in {a_node_id, b_node_id}
            ]
            hard_stop_events = [event for event in relevant_events if event.get("event") == "hard_stop_boundary"]
            case_payload["search_event_sample"] = relevant_events[:12]
            if not case_payload["endpoint_a_seed_match"] or not case_payload["endpoint_b_seed_match"]:
                case_payload["missing_reason"] = "endpoint_not_in_step4_input_rule"
            elif not case_payload["endpoint_a_search_started"] or not case_payload["endpoint_b_search_started"]:
                case_payload["missing_reason"] = "endpoint_consumed_as_through_or_disconnected"
            elif hard_stop_events:
                case_payload["missing_reason"] = "blocked_by_historical_boundary_in_search"
                case_payload["historical_boundary_events"] = hard_stop_events
            elif case_payload["endpoint_a_historical_boundary"] or case_payload["endpoint_b_historical_boundary"]:
                case_payload["missing_reason"] = "historical_boundary_endpoint_blocked"
            else:
                case_payload["missing_reason"] = "not_reached_in_candidate_search"

        payload["cases"].append(case_payload)

    out_path = out_root / "target_case_audit.json"
    write_json(out_path, payload)
    return out_path


def _parse_segment_body_assignments(path: Path) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    road_to_segmentid: dict[str, str] = {}
    pair_endpoints: dict[str, tuple[str, str]] = {}

    for feature in payload.get("features", []):
        props = dict(feature.get("properties") or {})
        if props.get("validated_status") not in {None, "", "validated"}:
            continue

        a_node_id = _normalize_id(props.get("a_node_id"))
        b_node_id = _normalize_id(props.get("b_node_id"))
        pair_id = str(props.get("pair_id") or "").strip()
        if pair_id == "" or a_node_id is None or b_node_id is None:
            continue

        segmentid = f"{a_node_id}_{b_node_id}"
        pair_endpoints[pair_id] = (a_node_id, b_node_id)
        road_ids_payload = props.get("road_ids")
        road_ids_text = props.get("road_ids_text")
        if isinstance(road_ids_payload, list):
            road_ids = tuple(road_id for road_id in (_normalize_id(value) for value in road_ids_payload) if road_id)
        elif isinstance(road_ids_text, str) and road_ids_text.strip():
            road_ids = tuple(road_id for road_id in (_normalize_id(value) for value in road_ids_text.split(",")) if road_id)
        else:
            road_ids = ()

        for road_id in road_ids:
            existing = road_to_segmentid.get(road_id)
            if existing is not None and existing != segmentid:
                raise ValueError(
                    f"Road '{road_id}' is assigned to multiple Step4 segment ids: '{existing}' and '{segmentid}'."
                )
            road_to_segmentid[road_id] = segmentid

    return road_to_segmentid, pair_endpoints


def _current_grade_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("grade_2"))


def _current_kind_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("kind_2"))


def _current_closed_con(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("closed_con"))


def _current_segmentid(road: RoadFeatureRecord) -> Optional[str]:
    return _normalize_id(road.properties.get("segmentid"))


def _require_working_layers(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    stage_label: str,
) -> None:
    issues: list[str] = []
    for index, node in enumerate(nodes):
        missing = [field for field in WORKING_NODE_FIELDS if field not in node.properties]
        if missing:
            issues.append(f"{stage_label} node feature[{index}] missing working fields: {', '.join(missing)}")
    for index, road in enumerate(roads):
        missing = [field for field in WORKING_ROAD_FIELDS if field not in road.properties]
        if missing:
            issues.append(f"{stage_label} road feature[{index}] missing working fields: {', '.join(missing)}")
    if issues:
        raise ValueError("; ".join(issues))


def _build_step4_inputs(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    out_root: Path,
    historical_boundary_ids: set[str],
    historical_boundary_source_map: dict[str, tuple[str, ...]],
    debug: bool,
) -> tuple[Path, Path, Path, dict[str, Any], dict[str, tuple[str, ...]]]:
    groups: dict[str, list[str]] = {}
    node_by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, representative_fallback_count = _build_mainnode_groups(node_by_id, groups)

    input_mainnode_candidate_count = 0
    input_closed_con_filtered_out_count = 0
    input_seed_count = 0
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        group = mainnode_groups[mainnode_id]
        representative = node_by_id[group.representative_node_id]
        grade_2 = _current_grade_2(representative)
        kind_2 = _current_kind_2(representative)
        closed_con = _current_closed_con(representative)
        is_historical_boundary = mainnode_id in historical_boundary_ids
        if is_historical_boundary or (grade_2 in {1, 2} and is_full_through_or_t_kind(kind_2)):
            input_mainnode_candidate_count += 1
            if is_historical_boundary or is_active_closed_con(closed_con):
                input_seed_count += 1
            else:
                input_closed_con_filtered_out_count += 1

    input_terminate_count = input_seed_count
    endpoint_pool_ids: set[str] = set()

    working_node_features: list[dict[str, Any]] = []
    for node in nodes:
        props = dict(node.properties)
        grade_2 = _current_grade_2(node)
        kind_2 = _current_kind_2(node)
        closed_con = _current_closed_con(node)
        is_historical_boundary = node.semantic_node_id in historical_boundary_ids
        is_eligible = is_historical_boundary or (
            grade_2 in {1, 2} and is_full_through_or_t_kind(kind_2) and is_active_closed_con(closed_con)
        )
        if is_eligible:
            endpoint_pool_ids.add(node.semantic_node_id)
        props["grade_2"] = 1 if is_eligible else 0
        props["kind_2"] = 4 if is_eligible else 0
        props["step4_input_eligible"] = is_eligible
        props["step4_historical_boundary"] = is_historical_boundary
        props["step4_input_grade_2"] = grade_2
        props["step4_input_kind_2"] = kind_2
        props["step4_input_closed_con"] = closed_con
        working_node_features.append({"properties": props, "geometry": node.geometry})

    removed_existing_segment_road_count = 0
    removed_closed_road_count = 0
    working_road_features: list[dict[str, Any]] = []
    for road in roads:
        current_segmentid = _current_segmentid(road)
        if current_segmentid:
            removed_existing_segment_road_count += 1
            continue
        if not is_allowed_road_kind(road.road_kind):
            removed_closed_road_count += 1
            continue
        working_road_features.append({"properties": dict(road.properties), "geometry": road.geometry})

    working_graph_road_count = len(working_road_features)
    working_nodes_path = out_root / "step4_working_nodes.geojson"
    working_roads_path = out_root / "step4_working_roads.geojson"
    strategy_path = out_root / "step4_strategy.json"
    step4_stage_dir = out_root / STEP4_STRATEGY_ID
    step4_stage_dir.mkdir(parents=True, exist_ok=True)
    semantic_nodes: dict[str, SemanticNodeRecord] = {}
    for mainnode_id, group in mainnode_groups.items():
        representative = node_by_id[group.representative_node_id]
        semantic_nodes[mainnode_id] = SemanticNodeRecord(
            semantic_node_id=mainnode_id,
            representative_node_id=group.representative_node_id,
            member_node_ids=tuple(group.member_node_ids),
            geometry=representative.geometry,
            raw_kind=_coerce_int(representative.properties.get("kind")),
            raw_grade=_coerce_int(representative.properties.get("grade")),
            kind_2=_current_kind_2(representative),
            grade_2=_current_grade_2(representative),
            closed_con=_current_closed_con(representative),
            raw_properties=dict(representative.properties),
        )
    endpoint_pool_source_map = build_endpoint_pool_source_map(
        node_ids=endpoint_pool_ids,
        stage_id=STEP4_STRATEGY_ID,
        previous_source_map=historical_boundary_source_map,
    )

    write_geojson(working_nodes_path, working_node_features)
    write_geojson(working_roads_path, working_road_features)
    write_endpoint_pool_outputs(
        out_dir=step4_stage_dir,
        source_map=endpoint_pool_source_map,
        stage_id=STEP4_STRATEGY_ID,
        semantic_nodes=semantic_nodes,
        debug=debug,
    )
    write_json(
        strategy_path,
        {
            "strategy_id": STEP4_STRATEGY_ID,
            "description": "Step4 residual graph segment construction using refreshed grade_2/kind_2/closed_con.",
            "seed_rule": {"kind_bits_any": [2, 6], "grade_eq": 1, "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES)},
            "terminate_rule": {"kind_bits_any": [2, 6], "grade_eq": 1, "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES)},
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "incident_degree_exclude_formway_bits_any": [7],
                "disallow_seed_terminate_nodes": True,
                "disallow_null_mainnode_singleton_seed_terminate_nodes": True,
            },
            "force_seed_node_ids": sorted(historical_boundary_ids, key=_sort_key),
            "force_terminate_node_ids": sorted(historical_boundary_ids, key=_sort_key),
            "hard_stop_node_ids": sorted(historical_boundary_ids, key=_sort_key),
        },
    )

    return (
        working_nodes_path,
        working_roads_path,
        strategy_path,
        {
            "input_mainnode_candidate_count": input_mainnode_candidate_count,
            "input_seed_count": input_seed_count,
            "input_terminate_count": input_terminate_count,
            "input_closed_con_filtered_out_count": input_closed_con_filtered_out_count,
            "historical_boundary_node_count": len(historical_boundary_ids),
            "endpoint_pool_node_count": len(endpoint_pool_ids),
            "removed_existing_segment_road_count": removed_existing_segment_road_count,
            "removed_closed_road_count": removed_closed_road_count,
            "working_graph_road_count": working_graph_road_count,
            "mainnode_representative_fallback_count": representative_fallback_count,
        },
        endpoint_pool_source_map,
    )


def _copy_step4_review_outputs(step4_dir: Path, out_root: Path) -> None:
    mapping = {
        "pair_candidates.csv": "step4_pair_candidates.csv",
        "validated_pairs.csv": "step4_validated_pairs.csv",
        "rejected_pair_candidates.csv": "step4_rejected_pairs.csv",
        "pair_links_candidates.geojson": "step4_pair_links_candidates.geojson",
        "pair_links_validated.geojson": "step4_pair_links_validated.geojson",
        "pair_validation_table.csv": "step4_pair_validation_table.csv",
        "trunk_roads.geojson": "step4_trunk_roads.geojson",
        "segment_body_roads.geojson": "step4_segment_body_roads.geojson",
        "step3_residual_roads.geojson": "step4_residual_roads.geojson",
        "branch_cut_roads.geojson": "step4_branch_cut_roads.geojson",
    }
    for source_name, target_name in mapping.items():
        source = step4_dir / source_name
        if source.exists():
            shutil.copy2(source, out_root / target_name)


def _preserve_previous_s2_snapshot(
    *,
    node_path: Union[str, Path],
    road_path: Union[str, Path],
    out_root: Path,
    debug: bool,
) -> Optional[Path]:
    node_parent = Path(node_path).resolve().parent
    road_parent = Path(road_path).resolve().parent
    if node_parent != road_parent:
        return None

    source_s2_dir = node_parent / "S2"
    if not source_s2_dir.is_dir():
        return None

    target_s2_dir = out_root / "S2"
    target_s2_dir.mkdir(parents=True, exist_ok=True)
    if debug:
        shutil.copytree(source_s2_dir, target_s2_dir, dirs_exist_ok=True)
    else:
        validated_pairs_path = source_s2_dir / "validated_pairs.csv"
        if validated_pairs_path.is_file():
            shutil.copy2(validated_pairs_path, target_s2_dir / "validated_pairs.csv")
    return target_s2_dir


def _write_step4_refreshed_outputs(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    out_root: Path,
    node_output_name: str,
    road_output_name: str,
    mainnode_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Step4Artifacts:
    refreshed_nodes_path = out_root / node_output_name
    refreshed_roads_path = out_root / road_output_name
    summary_path = out_root / "step4_summary.json"
    mainnode_table_path = out_root / "step4_mainnode_refresh_table.csv"

    write_geojson(
        refreshed_nodes_path,
        [{"properties": node_properties_map[node.node_id], "geometry": node.geometry} for node in nodes],
    )
    write_geojson(
        refreshed_roads_path,
        [{"properties": road_properties_map[road.road_id], "geometry": road.geometry} for road in roads],
    )
    write_json(summary_path, summary)
    write_csv(
        mainnode_table_path,
        mainnode_rows,
        [
            "mainnode_id",
            "representative_node_id",
            "in_step4_validated_pair",
            "current_grade_2",
            "current_kind_2",
            "current_closed_con",
            "new_grade_2",
            "new_kind_2",
            "unique_segmentid_count",
            "nonsegment_road_count",
            "nonsegment_all_right_turn_only",
            "nonsegment_has_in",
            "nonsegment_has_out",
            "applied_rule",
        ],
    )

    return Step4Artifacts(
        out_root=out_root,
        step4_dir=out_root / STEP4_STRATEGY_ID,
        refreshed_nodes_path=refreshed_nodes_path,
        refreshed_roads_path=refreshed_roads_path,
        summary_path=summary_path,
        mainnode_table_path=mainnode_table_path,
        summary=summary,
    )


def _refresh_after_step4(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    step4_validated_pairs: list[dict[str, str]],
    new_road_to_segmentid: dict[str, str],
    out_root: Path,
    step4_dir: Path,
    input_audit: dict[str, Any],
    input_node_path: Union[str, Path],
    input_road_path: Union[str, Path],
    node_output_name: str,
    road_output_name: str,
    preserved_prev_s2_dir: Optional[Path],
) -> Step4Artifacts:
    node_by_id = {node.node_id: node for node in nodes}
    road_by_id = {road.road_id: road for road in roads}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, representative_fallback_count = _build_mainnode_groups(node_by_id, groups)

    validated_endpoint_ids: set[str] = set()
    for row in step4_validated_pairs:
        a_node_id = _normalize_id(row.get("a_node_id"))
        b_node_id = _normalize_id(row.get("b_node_id"))
        if a_node_id is not None:
            validated_endpoint_ids.add(a_node_id)
        if b_node_id is not None:
            validated_endpoint_ids.add(b_node_id)

    road_properties_map: dict[str, dict[str, Any]] = {}
    for road in roads:
        props = dict(road.properties)
        existing_segmentid = _current_segmentid(road)
        existing_s_grade = props.get("s_grade")
        new_segmentid = new_road_to_segmentid.get(road.road_id)
        if existing_segmentid:
            props["segmentid"] = existing_segmentid
            props["s_grade"] = existing_s_grade
        elif new_segmentid is not None:
            props["segmentid"] = new_segmentid
            props["s_grade"] = STEP4_NEW_SEGMENT_GRADE
        else:
            props["segmentid"] = props.get("segmentid")
            props["s_grade"] = props.get("s_grade")
        road_properties_map[road.road_id] = props

    group_to_road_ids: dict[str, set[str]] = {}
    physical_to_semantic = {node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids}
    for road in roads:
        snode_group = physical_to_semantic.get(road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid)
        if snode_group is not None:
            group_to_road_ids.setdefault(snode_group, set()).add(road.road_id)
        if enode_group is not None:
            group_to_road_ids.setdefault(enode_group, set()).add(road.road_id)

    node_properties_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_properties_map[node.node_id] = dict(node.properties)

    node_rule_keep_pair_count = 0
    node_rule_single_segment_count = 0
    node_rule_right_turn_only_count = 0
    node_rule_new_t_count = 0
    multi_segment_mainnode_kept_count = 0

    mainnode_rows: list[dict[str, Any]] = []
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        group = mainnode_groups[mainnode_id]
        representative = node_by_id[group.representative_node_id]
        current_grade_2 = _current_grade_2(representative)
        current_kind_2 = _current_kind_2(representative)
        current_closed_con = _current_closed_con(representative)

        associated_road_ids = sorted(group_to_road_ids.get(mainnode_id, set()), key=_sort_key)
        associated_roads = [road_by_id[road_id] for road_id in associated_road_ids]
        segment_ids = sorted(
            {
                road_properties_map[road.road_id].get("segmentid")
                for road in associated_roads
                if road_properties_map[road.road_id].get("segmentid")
            },
            key=_sort_key,
        )
        unique_segmentid_count = len(segment_ids)
        nonsegment_roads = [road for road in associated_roads if not road_properties_map[road.road_id].get("segmentid")]
        nonsegment_road_count = len(nonsegment_roads)
        nonsegment_all_right_turn_only = bool(nonsegment_roads) and all(
            (_coerce_int(road.properties.get("formway")) or 0) & (1 << RIGHT_TURN_FORMWAY_BIT)
            for road in nonsegment_roads
        )
        member_id_set = set(group.member_node_ids)
        nonsegment_has_in = False
        nonsegment_has_out = False
        for road in nonsegment_roads:
            has_in, has_out = _road_flow_flags_for_group(road, member_id_set)
            nonsegment_has_in = nonsegment_has_in or has_in
            nonsegment_has_out = nonsegment_has_out or has_out

        new_grade_2 = current_grade_2
        new_kind_2 = current_kind_2
        applied_rule = "keep_current"
        if is_roundabout_mainnode_kind(current_kind_2):
            applied_rule = "protected_roundabout_mainnode"
        elif mainnode_id in validated_endpoint_ids:
            applied_rule = "keep_step4_pair_endpoint"
            node_rule_keep_pair_count += 1
        elif unique_segmentid_count > 1:
            applied_rule = "multi_segment_kept_current"
            multi_segment_mainnode_kept_count += 1
        elif associated_roads and unique_segmentid_count == 1 and all(
            road_properties_map[road.road_id].get("segmentid") for road in associated_roads
        ):
            new_grade_2 = -1
            new_kind_2 = 1
            applied_rule = "single_segment_non_intersection"
            node_rule_single_segment_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_all_right_turn_only:
            new_grade_2 = 3
            new_kind_2 = 1
            applied_rule = "right_turn_only_side"
            node_rule_right_turn_only_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_has_in and nonsegment_has_out:
            new_grade_2 = 3
            new_kind_2 = 2048
            applied_rule = "new_t_like"
            node_rule_new_t_count += 1

        rep_props = dict(node_properties_map[group.representative_node_id])
        rep_props["grade_2"] = new_grade_2
        rep_props["kind_2"] = new_kind_2
        node_properties_map[group.representative_node_id] = rep_props

        mainnode_rows.append(
            {
                "mainnode_id": mainnode_id,
                "representative_node_id": group.representative_node_id,
                "in_step4_validated_pair": mainnode_id in validated_endpoint_ids,
                "current_grade_2": current_grade_2,
                "current_kind_2": current_kind_2,
                "current_closed_con": current_closed_con,
                "new_grade_2": new_grade_2,
                "new_kind_2": new_kind_2,
                "unique_segmentid_count": unique_segmentid_count,
                "nonsegment_road_count": nonsegment_road_count,
                "nonsegment_all_right_turn_only": nonsegment_all_right_turn_only,
                "nonsegment_has_in": nonsegment_has_in,
                "nonsegment_has_out": nonsegment_has_out,
                "applied_rule": applied_rule,
            }
        )

    step4_segment_summary = json.loads((step4_dir / "segment_summary.json").read_text(encoding="utf-8"))
    summary = {
        "run_id": out_root.name,
        "input_node_path": str(Path(input_node_path)),
        "input_road_path": str(Path(input_road_path)),
        "step4_dir": str(step4_dir),
        "preserved_prev_s2_dir": str(preserved_prev_s2_dir) if preserved_prev_s2_dir is not None else None,
        **input_audit,
        "step4_candidate_pair_count": step4_segment_summary["candidate_pair_count"],
        "step4_validated_pair_count": step4_segment_summary["validated_pair_count"],
        "step4_rejected_pair_count": step4_segment_summary["rejected_pair_count"],
        "step4_new_segment_road_count": len(new_road_to_segmentid),
        "node_rule_keep_pair_count": node_rule_keep_pair_count,
        "node_rule_single_segment_count": node_rule_single_segment_count,
        "node_rule_right_turn_only_count": node_rule_right_turn_only_count,
        "node_rule_new_t_count": node_rule_new_t_count,
        "multi_segment_mainnode_kept_count": multi_segment_mainnode_kept_count,
        "mainnode_representative_fallback_count": representative_fallback_count,
    }

    return _write_step4_refreshed_outputs(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        out_root=out_root,
        node_output_name=node_output_name,
        road_output_name=road_output_name,
        mainnode_rows=mainnode_rows,
        summary=summary,
    )


def run_step4_residual_graph(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    formway_mode: str = "strict",
    left_turn_formway_bit: int = 8,
    debug: bool = True,
) -> Step4Artifacts:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    (nodes, _, _), (roads, _) = _load_nodes_and_roads(
        node_path=node_path,
        road_path=road_path,
        node_layer=node_layer,
        node_crs=node_crs,
        road_layer=road_layer,
        road_crs=road_crs,
    )
    _require_working_layers(nodes=nodes, roads=roads, stage_label="Step4")
    input_parent = Path(node_path).resolve().parent
    historical_boundary_ids, historical_boundary_source_map = collect_endpoint_pool_mainnodes(
        base_dir=input_parent,
        source_specs=(("S2", ("S2/endpoint_pool.csv", "S2/validated_pairs.csv")),),
    )

    working_nodes_path, working_roads_path, strategy_path, input_audit, _endpoint_pool_source_map = _build_step4_inputs(
        nodes=nodes,
        roads=roads,
        out_root=resolved_out_root,
        historical_boundary_ids=historical_boundary_ids,
        historical_boundary_source_map=historical_boundary_source_map,
        debug=debug,
    )

    step4_results = run_step2_segment_poc(
        road_path=working_roads_path,
        node_path=working_nodes_path,
        strategy_config_paths=[strategy_path],
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        assume_working_layers=True,
    )
    if len(step4_results) != 1:
        raise ValueError(f"Expected one Step4 strategy result, got {len(step4_results)}.")

    step4_dir = resolved_out_root / STEP4_STRATEGY_ID
    preserved_prev_s2_dir = _preserve_previous_s2_snapshot(
        node_path=node_path,
        road_path=road_path,
        out_root=resolved_out_root,
        debug=debug,
    )
    if debug:
        _copy_step4_review_outputs(step4_dir, resolved_out_root)
        _write_boundary_node_outputs(
            out_root=resolved_out_root,
            nodes=nodes,
            boundary_source_map=historical_boundary_source_map,
        )

    validated_pairs = _read_csv_rows(step4_dir / "validated_pairs.csv")
    new_road_to_segmentid, _pair_endpoints = _parse_segment_body_assignments(step4_dir / "segment_body_roads.geojson")
    if debug:
        candidate_rows = _read_csv_rows(step4_dir / "pair_candidates.csv")
        validation_rows = _read_csv_rows(step4_dir / "pair_validation_table.csv")
        working_nodes, _, _ = _load_nodes(working_nodes_path)
        rule_audit_rows = json.loads((step4_dir / "rule_audit.json").read_text(encoding="utf-8"))
        search_audit = json.loads((step4_dir / "search_audit.json").read_text(encoding="utf-8"))
        _build_target_case_audit(
            out_root=resolved_out_root,
            target_cases=STEP4_TARGET_CASES,
            candidate_rows=candidate_rows,
            validation_rows=validation_rows,
            nodes=working_nodes,
            rule_audit_rows=rule_audit_rows,
            search_audit=search_audit,
        )

    artifacts = _refresh_after_step4(
        nodes=nodes,
        roads=roads,
        step4_validated_pairs=validated_pairs,
        new_road_to_segmentid=new_road_to_segmentid,
        out_root=resolved_out_root,
        step4_dir=step4_dir,
        input_audit=input_audit,
        input_node_path=node_path,
        input_road_path=road_path,
        node_output_name=Path(node_path).name,
        road_output_name=Path(road_path).name,
        preserved_prev_s2_dir=preserved_prev_s2_dir,
    )
    refreshed_summary = dict(artifacts.summary)
    refreshed_summary["debug"] = debug
    write_json(artifacts.summary_path, refreshed_summary)
    return Step4Artifacts(
        out_root=artifacts.out_root,
        step4_dir=artifacts.step4_dir,
        refreshed_nodes_path=artifacts.refreshed_nodes_path,
        refreshed_roads_path=artifacts.refreshed_roads_path,
        summary_path=artifacts.summary_path,
        mainnode_table_path=artifacts.mainnode_table_path,
        summary=refreshed_summary,
    )


def run_step4_residual_graph_cli(args: argparse.Namespace) -> int:
    run_step4_residual_graph(
        road_path=args.road_path,
        node_path=args.node_path,
        out_root=args.out_root,
        run_id=args.run_id,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        formway_mode=args.formway_mode,
        left_turn_formway_bit=args.left_turn_formway_bit,
        debug=args.debug,
    )
    return 0
