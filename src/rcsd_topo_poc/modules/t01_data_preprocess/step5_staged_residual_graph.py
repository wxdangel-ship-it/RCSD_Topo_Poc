from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import (
    build_endpoint_pool_source_map,
    collect_endpoint_pool_mainnodes,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    first_existing_vector_path,
    load_vector_feature_collection,
    write_csv,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes_and_roads,
    _load_nodes,
    _load_roads,
    _road_flow_flags_for_group,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _coerce_int, _find_repo_root, _normalize_id, _sort_key
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc
from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import (
    _filter_active_road_ids_excluding_right_turn,
    _identify_right_turn_only_side_pseudojunction_ids,
    _filter_right_turn_only_side_boundary_ids,
    _current_closed_con,
    _current_grade_2,
    _current_kind_2,
    _current_segmentid,
    _parse_segment_body_assignments,
    _read_csv_rows,
    _write_boundary_node_outputs,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    ACTIVE_CLOSED_CON_VALUES,
    WORKING_NODE_FIELDS,
    WORKING_ROAD_FIELDS,
    canonicalize_road_working_properties,
    get_road_segmentid,
    get_road_sgrade,
    is_active_closed_con,
    is_allowed_road_kind,
    is_full_through_kind,
    is_full_through_or_t_kind,
    is_roundabout_mainnode_kind,
    sanitize_public_node_properties,
    set_road_segmentid,
    set_road_sgrade,
)


DEFAULT_RUN_ID_PREFIX = "t01_step5_staged_residual_graph_"
STEP5A_STRATEGY_ID = "STEP5A"
STEP5B_STRATEGY_ID = "STEP5B"
STEP5C_STRATEGY_ID = "STEP5C"
STEP5_NEW_SEGMENT_GRADE = "0-2\u53cc"
STEP5C_TARGET_A_NODE_ID = "997356"
STEP5C_TARGET_B_NODE_ID = "39546395"
STEP5C_TARGET_PAIR_ID = f"{STEP5C_STRATEGY_ID}:{STEP5C_TARGET_A_NODE_ID}__{STEP5C_TARGET_B_NODE_ID}"
STEP5C_ROLLING_ENDPOINT_POOL_CSV = "step5c_rolling_endpoint_pool.csv"
STEP5C_ROLLING_ENDPOINT_POOL_GEOJSON = "step5c_rolling_endpoint_pool.gpkg"
STEP5C_PROTECTED_HARD_STOPS_CSV = "step5c_protected_hard_stops.csv"
STEP5C_PROTECTED_HARD_STOPS_GEOJSON = "step5c_protected_hard_stops.gpkg"
STEP5C_DEMOTABLE_ENDPOINTS_CSV = "step5c_demotable_endpoints.csv"
STEP5C_DEMOTABLE_ENDPOINTS_GEOJSON = "step5c_demotable_endpoints.gpkg"
STEP5C_ACTUAL_BARRIERS_CSV = "step5c_actual_barriers.csv"
STEP5C_ACTUAL_BARRIERS_GEOJSON = "step5c_actual_barriers.gpkg"
STEP5C_ENDPOINT_DEMOTE_AUDIT_JSON = "step5c_endpoint_demote_audit.json"
STEP5C_TARGET_PAIR_AUDIT_JSON = "target_pair_audit_997356__39546395.json"


@dataclass(frozen=True)
class PhaseInputArtifacts:
    phase_id: str
    working_nodes_path: Path
    working_roads_path: Path
    strategy_path: Path
    input_node_count: int
    seed_count: int
    terminate_count: int
    working_graph_road_count: int
    active_road_ids: tuple[str, ...]
    endpoint_pool_ids: tuple[str, ...]
    endpoint_pool_source_map: dict[str, tuple[str, ...]]
    actual_barrier_ids: tuple[str, ...] = ()
    protected_hard_stop_ids: tuple[str, ...] = ()
    demoted_endpoint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhaseRunArtifacts:
    phase_id: str
    phase_dir: Path
    candidate_pair_count: int
    validated_pair_count: int
    rejected_pair_count: int
    new_segment_road_count: int
    validated_rows: list[dict[str, str]]
    road_to_segmentid: dict[str, str]
    assigned_segment_ids: tuple[str, ...]
    segment_summary: dict[str, Any]


@dataclass(frozen=True)
class Step5Artifacts:
    out_root: Path
    refreshed_nodes_path: Path
    refreshed_roads_path: Path
    refreshed_nodes_alias_path: Optional[Path]
    refreshed_roads_alias_path: Optional[Path]
    summary_path: Path
    mainnode_table_path: Path
    summary: dict[str, Any]
    step6_nodes: tuple[NodeFeatureRecord, ...]
    step6_roads: tuple[RoadFeatureRecord, ...]
    step6_node_properties_map: dict[str, dict[str, Any]]
    step6_road_properties_map: dict[str, dict[str, Any]]
    step6_mainnode_groups: dict[str, Any]
    step6_group_to_allowed_road_ids: dict[str, set[str]]


@dataclass(frozen=True)
class Step5CAdaptiveContext:
    rolling_endpoint_pool_ids: tuple[str, ...]
    current_input_candidate_ids: tuple[str, ...]
    protected_hard_stop_ids: tuple[str, ...]
    demotable_endpoint_ids: tuple[str, ...]
    actual_terminate_barrier_ids: tuple[str, ...]
    endpoint_source_map: dict[str, tuple[str, ...]]
    demote_audit_rows: tuple[dict[str, Any], ...]


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
    return repo_root / "outputs" / "_work" / "t01_step5_staged_residual_graph" / resolved_run_id, resolved_run_id


def _step5a_base_match(grade_2: Optional[int], kind_2: Optional[int]) -> bool:
    return (
        (is_full_through_or_t_kind(kind_2) and grade_2 in {1, 2})
        or (is_full_through_kind(kind_2) and grade_2 == 3)
    )


def _step5b_base_match(grade_2: Optional[int], kind_2: Optional[int]) -> bool:
    return is_full_through_or_t_kind(kind_2) and grade_2 in {1, 2, 3}


def _step5c_base_match(grade_2: Optional[int], kind_2: Optional[int]) -> bool:
    return is_full_through_or_t_kind(kind_2) and grade_2 in {1, 2, 3}


def _build_group_to_road_ids(
    *,
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    physical_to_semantic: dict[str, str],
) -> dict[str, set[str]]:
    group_to_road_ids: dict[str, set[str]] = {}
    for road in roads:
        if road.road_id not in active_road_ids:
            continue
        snode_group = physical_to_semantic.get(road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid)
        if snode_group is not None:
            group_to_road_ids.setdefault(snode_group, set()).add(road.road_id)
        if enode_group is not None:
            group_to_road_ids.setdefault(enode_group, set()).add(road.road_id)
    return group_to_road_ids


def _build_active_semantic_state(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
) -> tuple[
    dict[str, NodeFeatureRecord],
    dict[str, Any],
    dict[str, set[str]],
    dict[str, int],
    dict[str, set[str]],
]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = {
        node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids
    }
    group_to_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids=active_road_ids,
        physical_to_semantic=physical_to_semantic,
    )
    incident_degree: dict[str, int] = {}
    distinct_neighbor_groups: dict[str, set[str]] = {}
    for road in roads:
        if road.road_id not in active_road_ids:
            continue
        snode_group = physical_to_semantic.get(road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid)
        if snode_group is None or enode_group is None or snode_group == enode_group:
            continue
        incident_degree[snode_group] = incident_degree.get(snode_group, 0) + 1
        incident_degree[enode_group] = incident_degree.get(enode_group, 0) + 1
        distinct_neighbor_groups.setdefault(snode_group, set()).add(enode_group)
        distinct_neighbor_groups.setdefault(enode_group, set()).add(snode_group)
    return node_by_id, mainnode_groups, group_to_road_ids, incident_degree, distinct_neighbor_groups


def _is_step5c_current_input_candidate(node: NodeFeatureRecord) -> bool:
    grade_2 = _current_grade_2(node)
    kind_2 = _current_kind_2(node)
    return (
        is_active_closed_con(_current_closed_con(node))
        and kind_2 in {4, 64, 2048}
        and grade_2 in {1, 2, 3}
    )


def collect_rolling_endpoint_pool(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    historical_seed_node_ids: set[str],
    historical_seed_source_map: dict[str, tuple[str, ...]],
    excluded_node_ids: set[str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]]]:
    excluded_node_ids = set(excluded_node_ids or ())
    node_by_id, mainnode_groups, group_to_road_ids, _, _ = _build_active_semantic_state(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
    )
    current_input_candidate_ids: set[str] = set()
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        if mainnode_id in excluded_node_ids:
            continue
        if not group_to_road_ids.get(mainnode_id):
            continue
        representative = node_by_id[mainnode_groups[mainnode_id].representative_node_id]
        if _is_step5c_current_input_candidate(representative):
            current_input_candidate_ids.add(mainnode_id)

    rolling_endpoint_pool_ids = (set(historical_seed_node_ids) - excluded_node_ids) | current_input_candidate_ids
    endpoint_source_map: dict[str, tuple[str, ...]] = {}
    for node_id in sorted(rolling_endpoint_pool_ids, key=_sort_key):
        tags = set(historical_seed_source_map.get(node_id, ()))
        if node_id in historical_seed_node_ids and not tags:
            tags.add("historical_endpoint")
        if node_id in current_input_candidate_ids:
            tags.add("STEP5C_CURRENT_INPUT")
        endpoint_source_map[node_id] = tuple(sorted(tags, key=_sort_key))

    return (
        tuple(sorted(rolling_endpoint_pool_ids, key=_sort_key)),
        tuple(sorted(current_input_candidate_ids, key=_sort_key)),
        endpoint_source_map,
    )


def collect_protected_hard_stop_set(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
) -> tuple[str, ...]:
    node_by_id, mainnode_groups, group_to_road_ids, _, _ = _build_active_semantic_state(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
    )
    protected_ids: set[str] = set()
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        if not group_to_road_ids.get(mainnode_id):
            continue
        representative = node_by_id[mainnode_groups[mainnode_id].representative_node_id]
        if is_active_closed_con(_current_closed_con(representative)) and is_roundabout_mainnode_kind(
            _current_kind_2(representative)
        ):
            protected_ids.add(mainnode_id)
    return tuple(sorted(protected_ids, key=_sort_key))


def evaluate_demotable_endpoint_candidates(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    rolling_endpoint_pool_ids: tuple[str, ...],
    current_input_candidate_ids: tuple[str, ...],
    historical_seed_node_ids: set[str],
    protected_hard_stop_ids: tuple[str, ...],
    endpoint_source_map: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    _, mainnode_groups, group_to_road_ids, incident_degree, distinct_neighbor_groups = _build_active_semantic_state(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
    )
    active_mainnode_ids = {mainnode_id for mainnode_id, road_ids in group_to_road_ids.items() if road_ids}
    current_input_candidate_set = set(current_input_candidate_ids)
    protected_hard_stop_set = set(protected_hard_stop_ids)

    demotable_ids: set[str] = set()
    audit_rows: list[dict[str, Any]] = []
    for node_id in sorted(rolling_endpoint_pool_ids, key=_sort_key):
        semantic_incident_degree = incident_degree.get(node_id, 0) if node_id in active_mainnode_ids else 0
        distinct_neighbor_group_count = (
            len(distinct_neighbor_groups.get(node_id, set())) if node_id in active_mainnode_ids else 0
        )
        is_protected = node_id in protected_hard_stop_set
        demoted = False
        if is_protected:
            reason = "protected_roundabout"
        elif semantic_incident_degree == 2 and distinct_neighbor_group_count == 2:
            demoted = True
            reason = "demoted_residual_degree_eq_2_distinct_two_neighbors"
            demotable_ids.add(node_id)
        elif semantic_incident_degree < 2:
            reason = "residual_degree_lt_2_boundary"
        elif semantic_incident_degree > 2:
            reason = "residual_degree_gt_2_branching"
        else:
            reason = "residual_degree_eq_2_but_not_distinct_two_neighbors"
        audit_rows.append(
            {
                "node_id": node_id,
                "is_historical_endpoint": node_id in historical_seed_node_ids,
                "is_current_input_candidate": node_id in current_input_candidate_set,
                "is_protected_hard_stop": is_protected,
                "semantic_incident_degree": semantic_incident_degree,
                "distinct_neighbor_group_count": distinct_neighbor_group_count,
                "demoted": demoted,
                "reason": reason,
                "source_tags": list(endpoint_source_map.get(node_id, ())),
                "present_in_current_residual_graph": node_id in active_mainnode_ids and node_id in mainnode_groups,
            }
        )
    return tuple(sorted(demotable_ids, key=_sort_key)), tuple(audit_rows)


def collect_actual_terminate_barriers(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    protected_hard_stop_ids: tuple[str, ...],
    demote_audit_rows: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    _, _, group_to_road_ids, _, _ = _build_active_semantic_state(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
    )
    active_mainnode_ids = {mainnode_id for mainnode_id, road_ids in group_to_road_ids.items() if road_ids}
    actual_barrier_ids = set(protected_hard_stop_ids) & active_mainnode_ids
    for row in demote_audit_rows:
        node_id = str(row["node_id"])
        if node_id not in active_mainnode_ids:
            continue
        if not bool(row["demoted"]):
            actual_barrier_ids.add(node_id)
    return tuple(sorted(actual_barrier_ids, key=_sort_key))


def _build_step5c_adaptive_context(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    historical_seed_node_ids: set[str],
    historical_seed_source_map: dict[str, tuple[str, ...]],
    excluded_node_ids: set[str] | None = None,
) -> Step5CAdaptiveContext:
    rolling_endpoint_pool_ids, current_input_candidate_ids, endpoint_source_map = collect_rolling_endpoint_pool(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
        historical_seed_node_ids=historical_seed_node_ids,
        historical_seed_source_map=historical_seed_source_map,
        excluded_node_ids=excluded_node_ids,
    )
    protected_hard_stop_ids = collect_protected_hard_stop_set(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
    )
    demotable_endpoint_ids, demote_audit_rows = evaluate_demotable_endpoint_candidates(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
        rolling_endpoint_pool_ids=rolling_endpoint_pool_ids,
        current_input_candidate_ids=current_input_candidate_ids,
        historical_seed_node_ids=historical_seed_node_ids,
        protected_hard_stop_ids=protected_hard_stop_ids,
        endpoint_source_map=endpoint_source_map,
    )
    actual_terminate_barrier_ids = collect_actual_terminate_barriers(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
        protected_hard_stop_ids=protected_hard_stop_ids,
        demote_audit_rows=demote_audit_rows,
    )
    return Step5CAdaptiveContext(
        rolling_endpoint_pool_ids=rolling_endpoint_pool_ids,
        current_input_candidate_ids=current_input_candidate_ids,
        protected_hard_stop_ids=protected_hard_stop_ids,
        demotable_endpoint_ids=demotable_endpoint_ids,
        actual_terminate_barrier_ids=actual_terminate_barrier_ids,
        endpoint_source_map=endpoint_source_map,
        demote_audit_rows=demote_audit_rows,
    )


def _step5c_audit_rows_by_node_id(
    adaptive_context: Step5CAdaptiveContext,
) -> dict[str, dict[str, Any]]:
    rows = {str(row["node_id"]): dict(row) for row in adaptive_context.demote_audit_rows}
    for node_id in adaptive_context.protected_hard_stop_ids:
        rows.setdefault(
            node_id,
            {
                "node_id": node_id,
                "is_historical_endpoint": False,
                "is_current_input_candidate": False,
                "is_protected_hard_stop": True,
                "semantic_incident_degree": 0,
                "distinct_neighbor_group_count": 0,
                "demoted": False,
                "reason": "protected_roundabout",
                "source_tags": list(adaptive_context.endpoint_source_map.get(node_id, ())),
                "present_in_current_residual_graph": True,
            },
        )
    return rows


def _write_named_node_set_outputs(
    *,
    out_dir: Path,
    csv_name: str,
    geojson_name: str,
    node_ids: tuple[str, ...],
    nodes: list[NodeFeatureRecord],
    audit_rows_by_node_id: dict[str, dict[str, Any]],
) -> tuple[Path, Path]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)

    csv_rows: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for node_id in sorted(node_ids, key=_sort_key):
        audit_row = dict(audit_rows_by_node_id.get(node_id, {"node_id": node_id, "source_tags": []}))
        audit_row["source_tags"] = ";".join(str(value) for value in audit_row.get("source_tags", []))
        csv_rows.append(audit_row)
        group = mainnode_groups.get(node_id)
        if group is None:
            continue
        representative = node_by_id[group.representative_node_id]
        feature_props = dict(audit_rows_by_node_id.get(node_id, {"node_id": node_id}))
        feature_props["source_tags"] = list(feature_props.get("source_tags", []))
        feature_props["representative_node_id"] = group.representative_node_id
        feature_props["member_node_ids"] = list(group.member_node_ids)
        feature_props["kind_2"] = _current_kind_2(representative)
        feature_props["grade_2"] = _current_grade_2(representative)
        feature_props["closed_con"] = _current_closed_con(representative)
        features.append({"properties": feature_props, "geometry": representative.geometry})

    csv_path = out_dir / csv_name
    geojson_path = out_dir / geojson_name
    write_csv(
        csv_path,
        csv_rows,
        [
            "node_id",
            "is_historical_endpoint",
            "is_current_input_candidate",
            "is_protected_hard_stop",
            "semantic_incident_degree",
            "distinct_neighbor_group_count",
            "demoted",
            "reason",
            "source_tags",
            "present_in_current_residual_graph",
        ],
    )
    write_vector(geojson_path, features)
    return csv_path, geojson_path


def write_step5c_barrier_audit_outputs(
    *,
    phase_dir: Path,
    nodes: list[NodeFeatureRecord],
    adaptive_context: Step5CAdaptiveContext,
) -> dict[str, str]:
    phase_dir.mkdir(parents=True, exist_ok=True)
    audit_rows_by_node_id = _step5c_audit_rows_by_node_id(adaptive_context)
    rolling_csv_path, rolling_geojson_path = _write_named_node_set_outputs(
        out_dir=phase_dir,
        csv_name=STEP5C_ROLLING_ENDPOINT_POOL_CSV,
        geojson_name=STEP5C_ROLLING_ENDPOINT_POOL_GEOJSON,
        node_ids=adaptive_context.rolling_endpoint_pool_ids,
        nodes=nodes,
        audit_rows_by_node_id=audit_rows_by_node_id,
    )
    protected_csv_path, protected_geojson_path = _write_named_node_set_outputs(
        out_dir=phase_dir,
        csv_name=STEP5C_PROTECTED_HARD_STOPS_CSV,
        geojson_name=STEP5C_PROTECTED_HARD_STOPS_GEOJSON,
        node_ids=adaptive_context.protected_hard_stop_ids,
        nodes=nodes,
        audit_rows_by_node_id=audit_rows_by_node_id,
    )
    demotable_csv_path, demotable_geojson_path = _write_named_node_set_outputs(
        out_dir=phase_dir,
        csv_name=STEP5C_DEMOTABLE_ENDPOINTS_CSV,
        geojson_name=STEP5C_DEMOTABLE_ENDPOINTS_GEOJSON,
        node_ids=adaptive_context.demotable_endpoint_ids,
        nodes=nodes,
        audit_rows_by_node_id=audit_rows_by_node_id,
    )
    actual_csv_path, actual_geojson_path = _write_named_node_set_outputs(
        out_dir=phase_dir,
        csv_name=STEP5C_ACTUAL_BARRIERS_CSV,
        geojson_name=STEP5C_ACTUAL_BARRIERS_GEOJSON,
        node_ids=adaptive_context.actual_terminate_barrier_ids,
        nodes=nodes,
        audit_rows_by_node_id=audit_rows_by_node_id,
    )
    demote_audit_path = phase_dir / STEP5C_ENDPOINT_DEMOTE_AUDIT_JSON
    write_json(
        demote_audit_path,
        {
            "rolling_endpoint_pool_ids": list(adaptive_context.rolling_endpoint_pool_ids),
            "current_input_candidate_ids": list(adaptive_context.current_input_candidate_ids),
            "protected_hard_stop_ids": list(adaptive_context.protected_hard_stop_ids),
            "demotable_endpoint_ids": list(adaptive_context.demotable_endpoint_ids),
            "actual_terminate_barrier_ids": list(adaptive_context.actual_terminate_barrier_ids),
            "rows": list(adaptive_context.demote_audit_rows),
        },
    )
    return {
        "rolling_endpoint_pool_csv": str(rolling_csv_path.resolve()),
        "rolling_endpoint_pool_geojson": str(rolling_geojson_path.resolve()),
        "protected_hard_stops_csv": str(protected_csv_path.resolve()),
        "protected_hard_stops_geojson": str(protected_geojson_path.resolve()),
        "demotable_endpoints_csv": str(demotable_csv_path.resolve()),
        "demotable_endpoints_geojson": str(demotable_geojson_path.resolve()),
        "actual_barriers_csv": str(actual_csv_path.resolve()),
        "actual_barriers_geojson": str(actual_geojson_path.resolve()),
        "endpoint_demote_audit_json": str(demote_audit_path.resolve()),
    }


def _write_step5c_target_pair_audit(
    *,
    phase_dir: Path,
    adaptive_context: Step5CAdaptiveContext,
) -> Path:
    candidate_rows = _read_csv_rows(phase_dir / "pair_candidates.csv") if (phase_dir / "pair_candidates.csv").is_file() else []
    validated_rows = _read_csv_rows(phase_dir / "validated_pairs.csv") if (phase_dir / "validated_pairs.csv").is_file() else []
    validation_rows = _read_csv_rows(phase_dir / "pair_validation_table.csv") if (phase_dir / "pair_validation_table.csv").is_file() else []
    search_audit = (
        json.loads((phase_dir / "search_audit.json").read_text(encoding="utf-8"))
        if (phase_dir / "search_audit.json").is_file()
        else {}
    )
    target_candidate = next((row for row in candidate_rows if row.get("pair_id") == STEP5C_TARGET_PAIR_ID), None)
    target_validated = next((row for row in validated_rows if row.get("pair_id") == STEP5C_TARGET_PAIR_ID), None)
    target_validation_row = next((row for row in validation_rows if row.get("pair_id") == STEP5C_TARGET_PAIR_ID), None)
    actual_barrier_ids = set(adaptive_context.actual_terminate_barrier_ids)
    blocking_barrier_node_ids: set[str] = set()
    for event in search_audit.get("search_events") or []:
        event_name = str(event.get("event") or "")
        seed_node_id = _normalize_id(event.get("seed_node_id"))
        node_id = _normalize_id(event.get("node_id"))
        if seed_node_id not in {STEP5C_TARGET_A_NODE_ID, STEP5C_TARGET_B_NODE_ID}:
            continue
        if node_id is None or node_id not in actual_barrier_ids:
            continue
        if event_name in {"hard_stop_boundary", "hard_stop_terminal_candidate", "hard_stop_terminal_not_seed"}:
            blocking_barrier_node_ids.add(node_id)

    reverse_confirm_events = [
        event
        for event in (search_audit.get("search_events") or [])
        if str(event.get("event") or "") == "reverse_confirm_fail"
        and (
            {_normalize_id(event.get("a_node_id")), _normalize_id(event.get("b_node_id"))}
            == {STEP5C_TARGET_A_NODE_ID, STEP5C_TARGET_B_NODE_ID}
            or {_normalize_id(event.get("a_node_id")), _normalize_id(event.get("b_node_id"))}
            == {"1026960", "1029576"}
        )
    ]

    if target_validated is not None:
        remaining_blocker_type = "none"
        remaining_blocker_detail: Any = ""
    elif blocking_barrier_node_ids:
        remaining_blocker_type = "actual_barrier"
        remaining_blocker_detail = sorted(blocking_barrier_node_ids, key=_sort_key)
    elif target_validation_row is not None and str(target_validation_row.get("reject_reason") or ""):
        reject_reason = str(target_validation_row.get("reject_reason") or "")
        if "dual_carriageway" in reject_reason or "side_access" in reject_reason:
            remaining_blocker_type = "50m_gate"
        else:
            remaining_blocker_type = "validation_reject"
        remaining_blocker_detail = reject_reason
    elif reverse_confirm_events:
        remaining_blocker_type = "reverse_confirm"
        remaining_blocker_detail = reverse_confirm_events
    else:
        remaining_blocker_type = "search_no_terminal"
        remaining_blocker_detail = ""

    out_path = phase_dir / STEP5C_TARGET_PAIR_AUDIT_JSON
    write_json(
        out_path,
        {
            "target_pair_id": STEP5C_TARGET_PAIR_ID,
            "entered_step5c_candidate": target_candidate is not None,
            "entered_step5c_validated": target_validated is not None,
            "blocked_by_actual_barrier": bool(blocking_barrier_node_ids),
            "blocking_barrier_node_ids": sorted(blocking_barrier_node_ids, key=_sort_key),
            "remaining_blocker_type": remaining_blocker_type,
            "remaining_blocker_detail": remaining_blocker_detail,
            "terminate_rigidity_cleared": not bool(blocking_barrier_node_ids),
        },
    )
    return out_path


def _build_phase_inputs(
    *,
    phase_id: str,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    pseudo_junction_ids: set[str],
    out_root: Path,
    base_match: Callable[[Optional[int], Optional[int]], bool],
    historical_seed_node_ids: set[str],
    historical_seed_source_map: dict[str, tuple[str, ...]],
    hard_stop_node_ids: set[str],
) -> PhaseInputArtifacts:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = {
        node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids
    }
    group_to_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids=active_road_ids,
        physical_to_semantic=physical_to_semantic,
    )

    input_mainnode_ids: set[str] = set()
    eligible_mainnode_ids: set[str] = set()
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        group = mainnode_groups[mainnode_id]
        representative = node_by_id[group.representative_node_id]
        if not group_to_road_ids.get(mainnode_id):
            continue
        grade_2 = _current_grade_2(representative)
        kind_2 = _current_kind_2(representative)
        is_historical_seed = mainnode_id in historical_seed_node_ids
        if mainnode_id in pseudo_junction_ids and not is_historical_seed:
            continue
        if mainnode_id in hard_stop_node_ids and not is_historical_seed:
            continue
        if not is_historical_seed and not base_match(grade_2, kind_2):
            continue
        input_mainnode_ids.add(mainnode_id)
        if is_historical_seed or is_active_closed_con(_current_closed_con(representative)):
            eligible_mainnode_ids.add(mainnode_id)

    phase_lower = phase_id.lower()
    working_node_features: list[dict[str, Any]] = []
    for node in nodes:
        props = dict(node.properties)
        is_historical_boundary = node.semantic_node_id in hard_stop_node_ids
        is_eligible = node.semantic_node_id in eligible_mainnode_ids and node.semantic_node_id not in pseudo_junction_ids
        props["grade_2"] = _current_grade_2(node)
        props["kind_2"] = _current_kind_2(node)
        props[f"{phase_lower}_input_eligible"] = is_eligible
        props[f"{phase_lower}_historical_boundary"] = is_historical_boundary
        props[f"{phase_lower}_input_grade_2"] = _current_grade_2(node)
        props[f"{phase_lower}_input_kind_2"] = _current_kind_2(node)
        props[f"{phase_lower}_input_closed_con"] = _current_closed_con(node)
        working_node_features.append({"properties": props, "geometry": node.geometry})

    working_road_features = [
        {"properties": dict(road.properties), "geometry": road.geometry}
        for road in roads
        if road.road_id in active_road_ids
    ]

    working_nodes_path = out_root / f"{phase_lower}_working_nodes.gpkg"
    working_roads_path = out_root / f"{phase_lower}_working_roads.gpkg"
    strategy_path = out_root / f"{phase_lower}_strategy.json"
    write_vector(working_nodes_path, working_node_features)
    write_vector(working_roads_path, working_road_features)
    endpoint_pool_source_map = build_endpoint_pool_source_map(
        node_ids=eligible_mainnode_ids,
        stage_id=phase_id,
        previous_source_map=historical_seed_source_map,
    )
    write_json(
        strategy_path,
        {
            "strategy_id": phase_id,
            "description": f"{phase_id} staged residual graph segment construction.",
            "seed_rule": (
                {
                    "kind_values_in": [4, 64, 2048],
                    "grade_in": [1, 2, 3],
                    "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES),
                }
                if phase_id != STEP5A_STRATEGY_ID
                else {
                    "kind_values_in": [4, 64, 2048],
                    "grade_eq": 9999,
                    "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES),
                }
            ),
            "terminate_rule": (
                {
                    "kind_values_in": [4, 64, 2048],
                    "grade_in": [1, 2, 3],
                    "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES),
                }
                if phase_id != STEP5A_STRATEGY_ID
                else {
                    "kind_values_in": [4, 64, 2048],
                    "grade_eq": 9999,
                    "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES),
                }
            ),
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "incident_degree_exclude_formway_bits_any": [7],
                "disallow_seed_terminate_nodes": True,
            },
            "explicit_seed_node_ids": sorted(eligible_mainnode_ids, key=_sort_key),
            "explicit_terminate_node_ids": sorted(eligible_mainnode_ids, key=_sort_key),
            "force_seed_node_ids": sorted(historical_seed_node_ids, key=_sort_key),
            "force_terminate_node_ids": sorted(historical_seed_node_ids, key=_sort_key),
            "hard_stop_node_ids": sorted(hard_stop_node_ids, key=_sort_key),
        },
    )

    active_road_ids_ordered = tuple(sorted(active_road_ids, key=_sort_key))
    return PhaseInputArtifacts(
        phase_id=phase_id,
        working_nodes_path=working_nodes_path,
        working_roads_path=working_roads_path,
        strategy_path=strategy_path,
        input_node_count=len(input_mainnode_ids),
        seed_count=len(eligible_mainnode_ids),
        terminate_count=len(eligible_mainnode_ids),
        working_graph_road_count=len(active_road_ids_ordered),
        active_road_ids=active_road_ids_ordered,
        endpoint_pool_ids=tuple(sorted(eligible_mainnode_ids, key=_sort_key)),
        endpoint_pool_source_map=endpoint_pool_source_map,
    )


def _build_step5c_adaptive_phase_inputs(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    out_root: Path,
    historical_seed_node_ids: set[str],
    historical_seed_source_map: dict[str, tuple[str, ...]],
    pseudo_junction_ids: set[str],
) -> tuple[PhaseInputArtifacts, Step5CAdaptiveContext]:
    adaptive_context = _build_step5c_adaptive_context(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids,
        historical_seed_node_ids=historical_seed_node_ids,
        historical_seed_source_map=historical_seed_source_map,
        excluded_node_ids=pseudo_junction_ids,
    )
    phase_lower = STEP5C_STRATEGY_ID.lower()
    reason_by_node_id = {str(row["node_id"]): str(row["reason"]) for row in adaptive_context.demote_audit_rows}
    historical_seed_set = set(historical_seed_node_ids)
    current_input_candidate_set = set(adaptive_context.current_input_candidate_ids)
    protected_hard_stop_set = set(adaptive_context.protected_hard_stop_ids)
    demotable_endpoint_set = set(adaptive_context.demotable_endpoint_ids)
    actual_barrier_set = set(adaptive_context.actual_terminate_barrier_ids)

    working_node_features: list[dict[str, Any]] = []
    for node in nodes:
        props = dict(node.properties)
        semantic_node_id = node.semantic_node_id
        props[f"{phase_lower}_input_eligible"] = semantic_node_id in set(adaptive_context.rolling_endpoint_pool_ids)
        props[f"{phase_lower}_historical_boundary"] = semantic_node_id in actual_barrier_set
        props[f"{phase_lower}_input_grade_2"] = _current_grade_2(node)
        props[f"{phase_lower}_input_kind_2"] = _current_kind_2(node)
        props[f"{phase_lower}_input_closed_con"] = _current_closed_con(node)
        props["step5c_in_rolling_pool"] = semantic_node_id in set(adaptive_context.rolling_endpoint_pool_ids)
        props["step5c_is_current_input_candidate"] = semantic_node_id in current_input_candidate_set
        props["step5c_is_historical_endpoint"] = semantic_node_id in historical_seed_set
        props["step5c_is_protected_hard_stop"] = semantic_node_id in protected_hard_stop_set
        props["step5c_is_demotable_endpoint"] = semantic_node_id in demotable_endpoint_set
        props["step5c_is_actual_barrier"] = semantic_node_id in actual_barrier_set
        props["step5c_endpoint_reason"] = reason_by_node_id.get(
            semantic_node_id,
            "not_in_rolling_pool",
        )
        working_node_features.append({"properties": props, "geometry": node.geometry})

    working_road_features = [
        {"properties": dict(road.properties), "geometry": road.geometry}
        for road in roads
        if road.road_id in active_road_ids
    ]

    working_nodes_path = out_root / f"{phase_lower}_working_nodes.gpkg"
    working_roads_path = out_root / f"{phase_lower}_working_roads.gpkg"
    strategy_path = out_root / f"{phase_lower}_strategy.json"
    write_vector(working_nodes_path, working_node_features)
    write_vector(working_roads_path, working_road_features)
    write_json(
        strategy_path,
        {
            "strategy_id": STEP5C_STRATEGY_ID,
            "description": f"{STEP5C_STRATEGY_ID} staged residual graph adaptive barrier fallback.",
            "seed_rule": {"kind_bits_any": [2, 6], "grade_eq": 1, "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES)},
            "terminate_rule": {"kind_bits_any": [2, 6], "grade_eq": 1, "closed_con_in": sorted(ACTIVE_CLOSED_CON_VALUES)},
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "incident_degree_exclude_formway_bits_any": [7],
                "disallow_seed_terminate_nodes": True,
                "retain_seed_node_ids_as_through_node_ids": list(adaptive_context.demotable_endpoint_ids),
                "allow_seed_search_when_through": True,
            },
            "force_seed_node_ids": list(adaptive_context.rolling_endpoint_pool_ids),
            "force_terminate_node_ids": list(adaptive_context.actual_terminate_barrier_ids),
            "hard_stop_node_ids": list(adaptive_context.protected_hard_stop_ids),
        },
    )

    active_road_ids_ordered = tuple(sorted(active_road_ids, key=_sort_key))
    return (
        PhaseInputArtifacts(
            phase_id=STEP5C_STRATEGY_ID,
            working_nodes_path=working_nodes_path,
            working_roads_path=working_roads_path,
            strategy_path=strategy_path,
            input_node_count=len(adaptive_context.rolling_endpoint_pool_ids),
            seed_count=len(adaptive_context.rolling_endpoint_pool_ids),
            terminate_count=len(adaptive_context.actual_terminate_barrier_ids),
            working_graph_road_count=len(active_road_ids_ordered),
            active_road_ids=active_road_ids_ordered,
            endpoint_pool_ids=adaptive_context.rolling_endpoint_pool_ids,
            endpoint_pool_source_map=adaptive_context.endpoint_source_map,
            actual_barrier_ids=adaptive_context.actual_terminate_barrier_ids,
            protected_hard_stop_ids=adaptive_context.protected_hard_stop_ids,
            demoted_endpoint_ids=adaptive_context.demotable_endpoint_ids,
        ),
        adaptive_context,
    )


def _require_working_layers(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    stage_label: str,
) -> None:
    issues: list[str] = []
    for index, node in enumerate(nodes):
        missing = [field for field in WORKING_NODE_FIELDS if field != "working_mainnodeid" and field not in node.properties]
        if missing:
            issues.append(f"{stage_label} node feature[{index}] missing working fields: {', '.join(missing)}")
    for index, road in enumerate(roads):
        missing = [field for field in WORKING_ROAD_FIELDS if field not in road.properties]
        if missing:
            issues.append(f"{stage_label} road feature[{index}] missing working fields: {', '.join(missing)}")
    if issues:
        raise ValueError("; ".join(issues))


def _copy_phase_review_outputs(*, phase_dir: Path, out_root: Path, prefix: str) -> None:
    mapping = {
        "pair_candidates.csv": f"{prefix}_pair_candidates.csv",
        "validated_pairs.csv": f"{prefix}_validated_pairs.csv",
        "rejected_pair_candidates.csv": f"{prefix}_rejected_pairs.csv",
        "pair_links_candidates.gpkg": f"{prefix}_pair_links_candidates.gpkg",
        "pair_links_validated.gpkg": f"{prefix}_pair_links_validated.gpkg",
        "pair_validation_table.csv": f"{prefix}_pair_validation_table.csv",
        "trunk_roads.gpkg": f"{prefix}_trunk_roads.gpkg",
        "segment_body_roads.gpkg": f"{prefix}_segment_body_roads.gpkg",
        "step3_residual_roads.gpkg": f"{prefix}_residual_roads.gpkg",
        "branch_cut_roads.gpkg": f"{prefix}_branch_cut_roads.gpkg",
    }
    for source_name, target_name in mapping.items():
        source = first_existing_vector_path(phase_dir, source_name) if source_name.endswith(".gpkg") else phase_dir / source_name
        if source is not None and source.exists():
            shutil.copy2(source, out_root / target_name)


def _load_geojson_doc(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".gpkg", ".gpkt"}:
        return load_vector_feature_collection(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_merged_geojson(*, paths: list[Path], out_path: Path, phase_labels: list[str]) -> None:
    merged_features: list[dict[str, Any]] = []
    crs: Optional[dict[str, Any]] = None
    for path, phase_label in zip(paths, phase_labels):
        if not path.exists():
            continue
        payload = _load_geojson_doc(path)
        if crs is None:
            crs = payload.get("crs")
        for feature in payload.get("features", []):
            props = dict(feature.get("properties") or {})
            props["step5_phase"] = phase_label
            merged_features.append(
                {
                    "type": "Feature",
                    "geometry": feature.get("geometry"),
                    "properties": props,
                }
            )

    write_vector(
        out_path,
        (
            {
                "properties": dict(feature.get("properties") or {}),
                "geometry": feature.get("geometry"),
            }
            for feature in merged_features
        ),
    )


def _write_merged_validated_pairs(
    *,
    phase_rows: list[tuple[str, list[dict[str, str]]]],
    out_path: Path,
) -> list[dict[str, str]]:
    merged_rows: list[dict[str, str]] = []
    for phase_label, rows in phase_rows:
        for row in rows:
            copied = dict(row)
            copied["step5_phase"] = phase_label
            merged_rows.append(copied)
    merged_rows.sort(key=lambda row: (_sort_key(row.get("pair_id")), _sort_key(row.get("a_node_id")), _sort_key(row.get("b_node_id"))))
    write_csv(
        out_path,
        merged_rows,
        ["step5_phase", "pair_id", "a_node_id", "b_node_id", "trunk_mode", "left_turn_excluded_mode", "warning_codes", "segment_body_road_count", "residual_road_count"],
    )
    return merged_rows


def _preserve_previous_stage_snapshots(
    *,
    node_path: Union[str, Path],
    road_path: Union[str, Path],
    out_root: Path,
) -> dict[str, str]:
    node_parent = Path(node_path).resolve().parent
    road_parent = Path(road_path).resolve().parent
    if node_parent != road_parent:
        return {}

    preserved: dict[str, str] = {}
    for snapshot_name in ("S2", "STEP4"):
        source = node_parent / snapshot_name
        if not source.is_dir():
            continue
        target = out_root / snapshot_name
        shutil.copytree(source, target, dirs_exist_ok=True)
        preserved[snapshot_name] = str(target)
    return preserved


def _run_phase(
    *,
    phase_input: PhaseInputArtifacts,
    out_root: Path,
    run_id: str,
    formway_mode: str,
    left_turn_formway_bit: int,
    debug: bool,
    reserved_segmentids: Optional[set[str]] = None,
) -> PhaseRunArtifacts:
    run_step2_segment_poc(
        road_path=phase_input.working_roads_path,
        node_path=phase_input.working_nodes_path,
        strategy_config_paths=[phase_input.strategy_path],
        out_root=out_root,
        run_id=run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        assume_working_layers=True,
    )
    phase_dir = out_root / phase_input.phase_id
    phase_lower = phase_input.phase_id.lower()
    if debug:
        _copy_phase_review_outputs(phase_dir=phase_dir, out_root=out_root, prefix=phase_lower)
    validated_rows = _read_csv_rows(phase_dir / "validated_pairs.csv")
    segment_body_path = first_existing_vector_path(phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson")
    if segment_body_path is None:
        raise ValueError(f"Step5 phase segment body output is missing under '{phase_dir}'.")
    road_to_segmentid, _ = _parse_segment_body_assignments(
        segment_body_path,
        reserved_segmentids=reserved_segmentids,
    )
    segment_summary = _load_geojson_doc(phase_dir / "segment_summary.json")
    return PhaseRunArtifacts(
        phase_id=phase_input.phase_id,
        phase_dir=phase_dir,
        candidate_pair_count=int(segment_summary.get("candidate_pair_count", 0)),
        validated_pair_count=int(segment_summary.get("validated_pair_count", 0)),
        rejected_pair_count=int(segment_summary.get("rejected_pair_count", 0)),
        new_segment_road_count=len(road_to_segmentid),
        validated_rows=validated_rows,
        road_to_segmentid=road_to_segmentid,
        assigned_segment_ids=tuple(sorted(set(road_to_segmentid.values()), key=_sort_key)),
        segment_summary=segment_summary,
    )


def _write_refreshed_outputs(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    out_root: Path,
    mainnode_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    mainnode_groups: dict[str, Any],
    group_to_allowed_road_ids: dict[str, set[str]],
    write_alias_outputs: bool,
) -> Step5Artifacts:
    refreshed_nodes_path = out_root / "nodes.gpkg"
    refreshed_roads_path = out_root / "roads.gpkg"
    refreshed_nodes_alias_path = out_root / "nodes_step5_refreshed.gpkg"
    refreshed_roads_alias_path = out_root / "roads_step5_refreshed.gpkg"
    summary_path = out_root / "step5_summary.json"
    mainnode_table_path = out_root / "step5_mainnode_refresh_table.csv"

    node_features = [
        {"properties": sanitize_public_node_properties(node_properties_map[node.node_id]), "geometry": node.geometry}
        for node in nodes
    ]
    road_features = [{"properties": road_properties_map[road.road_id], "geometry": road.geometry} for road in roads]

    write_vector(refreshed_nodes_path, node_features)
    write_vector(refreshed_roads_path, road_features)
    if write_alias_outputs:
        write_vector(refreshed_nodes_alias_path, node_features)
        write_vector(refreshed_roads_alias_path, road_features)
    else:
        refreshed_nodes_alias_path = None
        refreshed_roads_alias_path = None
    write_json(summary_path, summary)
    write_csv(
        mainnode_table_path,
        mainnode_rows,
        [
            "mainnode_id",
            "representative_node_id",
            "participates_in_step5a_pair",
            "participates_in_step5b_pair",
            "participates_in_step5c_pair",
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
    return Step5Artifacts(
        out_root=out_root,
        refreshed_nodes_path=refreshed_nodes_path,
        refreshed_roads_path=refreshed_roads_path,
        refreshed_nodes_alias_path=refreshed_nodes_alias_path,
        refreshed_roads_alias_path=refreshed_roads_alias_path,
        summary_path=summary_path,
        mainnode_table_path=mainnode_table_path,
        summary=summary,
        step6_nodes=tuple(nodes),
        step6_roads=tuple(roads),
        step6_node_properties_map={node_id: dict(props) for node_id, props in node_properties_map.items()},
        step6_road_properties_map={road_id: dict(props) for road_id, props in road_properties_map.items()},
        step6_mainnode_groups=mainnode_groups,
        step6_group_to_allowed_road_ids={group_id: set(road_ids) for group_id, road_ids in group_to_allowed_road_ids.items()},
    )


def _refresh_after_step5(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    phase_a: PhaseRunArtifacts,
    phase_b: PhaseRunArtifacts,
    phase_c: PhaseRunArtifacts,
    out_root: Path,
    preserved_snapshots: dict[str, str],
    step5a_input: PhaseInputArtifacts,
    step5b_input: PhaseInputArtifacts,
    step5c_input: PhaseInputArtifacts,
    removed_historical_segment_road_count: int,
    removed_step5a_segment_road_count: int,
    removed_step5b_segment_road_count: int,
    debug: bool,
) -> Step5Artifacts:
    node_by_id = {node.node_id: node for node in nodes}
    road_by_id = {road.road_id: road for road in roads}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, representative_fallback_count = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = {
        node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids
    }

    all_validated_rows = list(phase_a.validated_rows) + list(phase_b.validated_rows) + list(phase_c.validated_rows)
    step5a_endpoint_ids: set[str] = set()
    step5b_endpoint_ids: set[str] = set()
    step5c_endpoint_ids: set[str] = set()
    all_endpoint_ids: set[str] = set()
    for row in phase_a.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5a_endpoint_ids.add(value)
                all_endpoint_ids.add(value)
    for row in phase_b.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5b_endpoint_ids.add(value)
                all_endpoint_ids.add(value)
    for row in phase_c.validated_rows:
        for key in ("a_node_id", "b_node_id"):
            value = _normalize_id(row.get(key))
            if value is not None:
                step5c_endpoint_ids.add(value)
                all_endpoint_ids.add(value)

    new_road_to_segmentid = dict(phase_a.road_to_segmentid)
    for road_id, segmentid in phase_b.road_to_segmentid.items():
        existing = new_road_to_segmentid.get(road_id)
        if existing is not None and existing != segmentid:
            raise ValueError(
                f"Road '{road_id}' is assigned to multiple Step5 segment ids: '{existing}' and '{segmentid}'."
            )
        new_road_to_segmentid[road_id] = segmentid
    for road_id, segmentid in phase_c.road_to_segmentid.items():
        existing = new_road_to_segmentid.get(road_id)
        if existing is not None and existing != segmentid:
            raise ValueError(
                f"Road '{road_id}' is assigned to multiple Step5 segment ids: '{existing}' and '{segmentid}'."
            )
        new_road_to_segmentid[road_id] = segmentid

    road_properties_map: dict[str, dict[str, Any]] = {}
    for road in roads:
        props = canonicalize_road_working_properties(road.properties)
        existing_segmentid = _current_segmentid(road)
        if existing_segmentid:
            set_road_segmentid(props, existing_segmentid)
            set_road_sgrade(props, get_road_sgrade(props))
        elif road.road_id in new_road_to_segmentid:
            set_road_segmentid(props, new_road_to_segmentid[road.road_id])
            set_road_sgrade(props, STEP5_NEW_SEGMENT_GRADE)
        else:
            set_road_segmentid(props, get_road_segmentid(props))
            set_road_sgrade(props, get_road_sgrade(props))
        road_properties_map[road.road_id] = props

    group_to_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids={road.road_id for road in roads},
        physical_to_semantic=physical_to_semantic,
    )
    group_to_allowed_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids={road.road_id for road in roads if is_allowed_road_kind(road.road_kind)},
        physical_to_semantic=physical_to_semantic,
    )

    node_properties_map: dict[str, dict[str, Any]] = {node.node_id: dict(node.properties) for node in nodes}
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
            (_coerce_int(road.properties.get("formway")) or 0) & (1 << RIGHT_TURN_FORMWAY_BIT) for road in nonsegment_roads
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
        elif mainnode_id in all_endpoint_ids:
            applied_rule = "keep_step5_pair_endpoint"
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
                "participates_in_step5a_pair": mainnode_id in step5a_endpoint_ids,
                "participates_in_step5b_pair": mainnode_id in step5b_endpoint_ids,
                "participates_in_step5c_pair": mainnode_id in step5c_endpoint_ids,
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

    summary = {
        "run_id": out_root.name,
        "input_node_path": str(out_root.parent),  # overwritten below
        "input_road_path": str(out_root.parent),  # overwritten below
        "preserved_prev_s2_dir": preserved_snapshots.get("S2"),
        "preserved_prev_step4_dir": preserved_snapshots.get("STEP4"),
        "step5a_input_node_count": step5a_input.input_node_count,
        "step5a_seed_count": step5a_input.seed_count,
        "step5a_terminate_count": step5a_input.terminate_count,
        "step5a_validated_pair_count": phase_a.validated_pair_count,
        "step5a_new_segment_road_count": phase_a.new_segment_road_count,
        "step5b_input_node_count": step5b_input.input_node_count,
        "step5b_seed_count": step5b_input.seed_count,
        "step5b_terminate_count": step5b_input.terminate_count,
        "step5b_validated_pair_count": phase_b.validated_pair_count,
        "step5b_new_segment_road_count": phase_b.new_segment_road_count,
        "step5c_input_node_count": step5c_input.input_node_count,
        "step5c_seed_count": step5c_input.seed_count,
        "step5c_terminate_count": step5c_input.terminate_count,
        "step5c_validated_pair_count": phase_c.validated_pair_count,
        "step5c_new_segment_road_count": phase_c.new_segment_road_count,
        "step5_removed_historical_segment_road_count": removed_historical_segment_road_count,
        "step5_removed_step5a_segment_road_count": removed_step5a_segment_road_count,
        "step5_removed_step5b_segment_road_count": removed_step5b_segment_road_count,
        "step5_total_new_segment_road_count": len(new_road_to_segmentid),
        "node_rule_keep_pair_count": node_rule_keep_pair_count,
        "node_rule_single_segment_count": node_rule_single_segment_count,
        "node_rule_right_turn_only_count": node_rule_right_turn_only_count,
        "node_rule_new_t_count": node_rule_new_t_count,
        "multi_segment_mainnode_kept_count": multi_segment_mainnode_kept_count,
        "mainnode_representative_fallback_count": representative_fallback_count,
    }

    return _write_refreshed_outputs(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        out_root=out_root,
        mainnode_rows=mainnode_rows,
        summary=summary,
        mainnode_groups=mainnode_groups,
        group_to_allowed_road_ids=group_to_allowed_road_ids,
        write_alias_outputs=debug,
    )


def run_step5_staged_residual_graph(
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
) -> Step5Artifacts:
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
    _require_working_layers(nodes=nodes, roads=roads, stage_label="Step5")
    input_parent = Path(node_path).resolve().parent

    preserved_snapshots: dict[str, str] = {}
    if debug:
        preserved_snapshots = _preserve_previous_stage_snapshots(
            node_path=node_path,
            road_path=road_path,
            out_root=resolved_out_root,
        )
    historical_boundary_ids, historical_boundary_source_map = collect_endpoint_pool_mainnodes(
        base_dir=input_parent,
        source_specs=(
            ("S2", ("S2/endpoint_pool.csv", "S2/validated_pairs.csv")),
            ("STEP4", ("STEP4/endpoint_pool.csv", "step4_endpoint_pool.csv", "STEP4/validated_pairs.csv", "step4_validated_pairs.csv")),
        ),
    )

    historical_segment_road_ids = {road.road_id for road in roads if _current_segmentid(road)}
    used_segmentids = {
        segmentid
        for road in roads
        for segmentid in (_current_segmentid(road),)
        if segmentid is not None
    }
    active_road_ids_step5a_raw = {
        road.road_id
        for road in roads
        if road.road_id not in historical_segment_road_ids and is_allowed_road_kind(road.road_kind)
    }
    step5a_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5a_raw,
    )
    active_road_ids_step5a = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5a_raw,
    )
    historical_boundary_ids, _demoted_step5a_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=historical_boundary_ids,
        active_road_ids=active_road_ids_step5a_raw,
    )
    step5a_input = _build_phase_inputs(
        phase_id=STEP5A_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5a,
        pseudo_junction_ids=step5a_pseudo_junction_ids,
        out_root=resolved_out_root,
        base_match=_step5a_base_match,
        historical_seed_node_ids=historical_boundary_ids,
        historical_seed_source_map=historical_boundary_source_map,
        hard_stop_node_ids=historical_boundary_ids,
    )
    phase_a = _run_phase(
        phase_input=step5a_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_a.assigned_segment_ids)
    step5b_historical_seed_node_ids = set(step5a_input.endpoint_pool_ids)
    combined_boundary_source_map = dict(step5a_input.endpoint_pool_source_map)
    if debug:
        _write_boundary_node_outputs(
            out_root=resolved_out_root,
            nodes=nodes,
            boundary_source_map=combined_boundary_source_map,
        )

    active_road_ids_step5b_raw = set(active_road_ids_step5a_raw) - set(phase_a.road_to_segmentid)
    step5b_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5b_raw,
    )
    active_road_ids_step5b = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5b_raw,
    )
    step5b_historical_seed_node_ids, _demoted_step5b_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=step5b_historical_seed_node_ids,
        active_road_ids=active_road_ids_step5b_raw,
    )
    step5b_hard_stop_node_ids = set(step5b_historical_seed_node_ids)
    step5b_input = _build_phase_inputs(
        phase_id=STEP5B_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5b,
        pseudo_junction_ids=step5b_pseudo_junction_ids,
        out_root=resolved_out_root,
        base_match=_step5b_base_match,
        historical_seed_node_ids=step5b_historical_seed_node_ids,
        historical_seed_source_map=combined_boundary_source_map,
        hard_stop_node_ids=step5b_hard_stop_node_ids,
    )
    phase_b = _run_phase(
        phase_input=step5b_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_b.assigned_segment_ids)

    step5c_historical_seed_node_ids = set(step5b_input.endpoint_pool_ids)
    combined_boundary_source_map = dict(step5b_input.endpoint_pool_source_map)
    if debug:
        _write_boundary_node_outputs(
            out_root=resolved_out_root,
            nodes=nodes,
            boundary_source_map=combined_boundary_source_map,
        )

    active_road_ids_step5c_raw = set(active_road_ids_step5b_raw) - set(phase_b.road_to_segmentid)
    step5c_pseudo_junction_ids = _identify_right_turn_only_side_pseudojunction_ids(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5c_raw,
    )
    active_road_ids_step5c = _filter_active_road_ids_excluding_right_turn(
        roads=roads,
        active_road_ids=active_road_ids_step5c_raw,
    )
    step5c_historical_seed_node_ids, _demoted_step5c_boundary_ids = _filter_right_turn_only_side_boundary_ids(
        nodes=nodes,
        roads=roads,
        boundary_ids=step5c_historical_seed_node_ids,
        active_road_ids=active_road_ids_step5c_raw,
    )
    step5c_input, step5c_adaptive_context = _build_step5c_adaptive_phase_inputs(
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5c,
        out_root=resolved_out_root,
        historical_seed_node_ids=step5c_historical_seed_node_ids,
        historical_seed_source_map=combined_boundary_source_map,
        pseudo_junction_ids=step5c_pseudo_junction_ids,
    )
    phase_c = _run_phase(
        phase_input=step5c_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
        debug=debug,
        reserved_segmentids=used_segmentids,
    )
    used_segmentids.update(phase_c.assigned_segment_ids)
    step5c_barrier_audit_paths = write_step5c_barrier_audit_outputs(
        phase_dir=phase_c.phase_dir,
        nodes=nodes,
        adaptive_context=step5c_adaptive_context,
    )
    step5c_target_pair_audit_path = _write_step5c_target_pair_audit(
        phase_dir=phase_c.phase_dir,
        adaptive_context=step5c_adaptive_context,
    )

    merged_validated_rows = _write_merged_validated_pairs(
        phase_rows=[
            ("STEP5A", phase_a.validated_rows),
            ("STEP5B", phase_b.validated_rows),
            ("STEP5C", phase_c.validated_rows),
        ],
        out_path=resolved_out_root / "step5_validated_pairs_merged.csv",
    )
    if debug:
        _write_merged_geojson(
            paths=[
                first_existing_vector_path(phase_a.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_a.phase_dir / "segment_body_roads.gpkg",
                first_existing_vector_path(phase_b.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_b.phase_dir / "segment_body_roads.gpkg",
                first_existing_vector_path(phase_c.phase_dir, "segment_body_roads.gpkg", "segment_body_roads.geojson") or phase_c.phase_dir / "segment_body_roads.gpkg",
            ],
            out_path=resolved_out_root / "step5_segment_body_roads_merged.gpkg",
            phase_labels=["STEP5A", "STEP5B", "STEP5C"],
        )
        _write_merged_geojson(
            paths=[
                first_existing_vector_path(phase_a.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_a.phase_dir / "step3_residual_roads.gpkg",
                first_existing_vector_path(phase_b.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_b.phase_dir / "step3_residual_roads.gpkg",
                first_existing_vector_path(phase_c.phase_dir, "step3_residual_roads.gpkg", "step3_residual_roads.geojson") or phase_c.phase_dir / "step3_residual_roads.gpkg",
            ],
            out_path=resolved_out_root / "step5_residual_roads_merged.gpkg",
            phase_labels=["STEP5A", "STEP5B", "STEP5C"],
        )
        write_json(
            resolved_out_root / "strategy_comparison.json",
            {
                "run_id": resolved_run_id,
                "strategies": [
                    {"strategy_id": phase_a.phase_id, **phase_a.segment_summary},
                    {"strategy_id": phase_b.phase_id, **phase_b.segment_summary},
                    {"strategy_id": phase_c.phase_id, **phase_c.segment_summary},
                ],
            },
        )

    artifacts = _refresh_after_step5(
        nodes=nodes,
        roads=roads,
        phase_a=phase_a,
        phase_b=phase_b,
        phase_c=phase_c,
        out_root=resolved_out_root,
        preserved_snapshots=preserved_snapshots,
        step5a_input=step5a_input,
        step5b_input=step5b_input,
        step5c_input=step5c_input,
        removed_historical_segment_road_count=len(historical_segment_road_ids),
        removed_step5a_segment_road_count=len(phase_a.road_to_segmentid),
        removed_step5b_segment_road_count=len(phase_b.road_to_segmentid),
        debug=debug,
    )
    refreshed_summary = dict(artifacts.summary)
    refreshed_summary["input_node_path"] = str(Path(node_path))
    refreshed_summary["input_road_path"] = str(Path(road_path))
    refreshed_summary["step5a_candidate_pair_count"] = phase_a.candidate_pair_count
    refreshed_summary["step5a_rejected_pair_count"] = phase_a.rejected_pair_count
    refreshed_summary["step5b_candidate_pair_count"] = phase_b.candidate_pair_count
    refreshed_summary["step5b_rejected_pair_count"] = phase_b.rejected_pair_count
    refreshed_summary["step5c_candidate_pair_count"] = phase_c.candidate_pair_count
    refreshed_summary["step5c_rejected_pair_count"] = phase_c.rejected_pair_count
    refreshed_summary["step5_merged_validated_pair_count"] = len(merged_validated_rows)
    refreshed_summary["historical_boundary_node_count"] = len(historical_boundary_ids)
    refreshed_summary["step5b_hard_stop_node_count"] = len(step5b_hard_stop_node_ids)
    refreshed_summary["step5c_hard_stop_node_count"] = len(step5c_input.protected_hard_stop_ids)
    refreshed_summary["step5c_rolling_endpoint_pool_count"] = len(step5c_input.endpoint_pool_ids)
    refreshed_summary["step5c_protected_hard_stop_count"] = len(step5c_input.protected_hard_stop_ids)
    refreshed_summary["step5c_demoted_endpoint_count"] = len(step5c_input.demoted_endpoint_ids)
    refreshed_summary["step5c_actual_barrier_count"] = len(step5c_input.actual_barrier_ids)
    refreshed_summary["step5c_rolling_endpoint_pool_path"] = step5c_barrier_audit_paths["rolling_endpoint_pool_csv"]
    refreshed_summary["step5c_protected_hard_stops_path"] = step5c_barrier_audit_paths["protected_hard_stops_csv"]
    refreshed_summary["step5c_demotable_endpoints_path"] = step5c_barrier_audit_paths["demotable_endpoints_csv"]
    refreshed_summary["step5c_actual_barriers_path"] = step5c_barrier_audit_paths["actual_barriers_csv"]
    refreshed_summary["step5c_endpoint_demote_audit_path"] = step5c_barrier_audit_paths["endpoint_demote_audit_json"]
    refreshed_summary["step5c_target_pair_audit_path"] = str(step5c_target_pair_audit_path.resolve())
    refreshed_summary["debug"] = debug
    write_json(artifacts.summary_path, refreshed_summary)
    return Step5Artifacts(
        out_root=artifacts.out_root,
        refreshed_nodes_path=artifacts.refreshed_nodes_path,
        refreshed_roads_path=artifacts.refreshed_roads_path,
        refreshed_nodes_alias_path=artifacts.refreshed_nodes_alias_path,
        refreshed_roads_alias_path=artifacts.refreshed_roads_alias_path,
        summary_path=artifacts.summary_path,
        mainnode_table_path=artifacts.mainnode_table_path,
        summary=refreshed_summary,
        step6_nodes=artifacts.step6_nodes,
        step6_roads=artifacts.step6_roads,
        step6_node_properties_map=artifacts.step6_node_properties_map,
        step6_road_properties_map=artifacts.step6_road_properties_map,
        step6_mainnode_groups=artifacts.step6_mainnode_groups,
        step6_group_to_allowed_road_ids=artifacts.step6_group_to_allowed_road_ids,
    )


def run_step5_staged_residual_graph_cli(args: argparse.Namespace) -> int:
    run_step5_staged_residual_graph(
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
