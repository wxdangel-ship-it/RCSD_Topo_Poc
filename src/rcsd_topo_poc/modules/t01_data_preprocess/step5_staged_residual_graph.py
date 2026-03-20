from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes,
    _load_roads,
    _road_flow_flags_for_group,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _coerce_int, _find_repo_root, _normalize_id, _sort_key
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc
from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import (
    _current_closed_con,
    _current_grade_2,
    _current_kind_2,
    _current_segmentid,
    _parse_segment_body_assignments,
    _read_csv_rows,
)


DEFAULT_RUN_ID_PREFIX = "t01_step5_staged_residual_graph_"
STEP5A_STRATEGY_ID = "STEP5A"
STEP5B_STRATEGY_ID = "STEP5B"
STEP5_NEW_SEGMENT_GRADE = "0-2\u53cc"


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
    segment_summary: dict[str, Any]


@dataclass(frozen=True)
class Step5Artifacts:
    out_root: Path
    refreshed_nodes_path: Path
    refreshed_roads_path: Path
    refreshed_nodes_alias_path: Path
    refreshed_roads_alias_path: Path
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
    return repo_root / "outputs" / "_work" / "t01_step5_staged_residual_graph" / resolved_run_id, resolved_run_id


def _step5a_base_match(grade_2: Optional[int], kind_2: Optional[int]) -> bool:
    return ((kind_2 in {4, 2048} and grade_2 in {1, 2}) or (kind_2 == 4 and grade_2 == 3))


def _step5b_base_match(grade_2: Optional[int], kind_2: Optional[int]) -> bool:
    return kind_2 in {4, 2048} and grade_2 in {1, 2, 3}


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


def _build_phase_inputs(
    *,
    phase_id: str,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    active_road_ids: set[str],
    out_root: Path,
    base_match: Callable[[Optional[int], Optional[int]], bool],
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
        if not base_match(grade_2, kind_2):
            continue
        input_mainnode_ids.add(mainnode_id)
        if _current_closed_con(representative) in {1, 2}:
            eligible_mainnode_ids.add(mainnode_id)

    phase_lower = phase_id.lower()
    working_node_features: list[dict[str, Any]] = []
    for node in nodes:
        props = dict(node.properties)
        is_eligible = node.semantic_node_id in eligible_mainnode_ids
        props["grade"] = 1 if is_eligible else 0
        props["kind"] = 4 if is_eligible else 0
        props[f"{phase_lower}_input_eligible"] = is_eligible
        props[f"{phase_lower}_input_grade_2"] = _current_grade_2(node)
        props[f"{phase_lower}_input_kind_2"] = _current_kind_2(node)
        props[f"{phase_lower}_input_closed_con"] = _current_closed_con(node)
        working_node_features.append({"properties": props, "geometry": node.geometry})

    working_road_features = [
        {"properties": dict(road.properties), "geometry": road.geometry}
        for road in roads
        if road.road_id in active_road_ids
    ]

    working_nodes_path = out_root / f"{phase_lower}_working_nodes.geojson"
    working_roads_path = out_root / f"{phase_lower}_working_roads.geojson"
    strategy_path = out_root / f"{phase_lower}_strategy.json"
    write_geojson(working_nodes_path, working_node_features)
    write_geojson(working_roads_path, working_road_features)
    write_json(
        strategy_path,
        {
            "strategy_id": phase_id,
            "description": f"{phase_id} staged residual graph segment construction.",
            "seed_rule": {"kind_bits_all": [2], "grade_eq": 1, "closed_con_in": [1, 2]},
            "terminate_rule": {"kind_bits_all": [2], "grade_eq": 1, "closed_con_in": [1, 2]},
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "incident_degree_exclude_formway_bits_any": [7],
                "disallow_seed_terminate_nodes": True,
            },
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
    )


def _copy_phase_review_outputs(*, phase_dir: Path, out_root: Path, prefix: str) -> None:
    mapping = {
        "pair_candidates.csv": f"{prefix}_pair_candidates.csv",
        "validated_pairs.csv": f"{prefix}_validated_pairs.csv",
        "rejected_pair_candidates.csv": f"{prefix}_rejected_pairs.csv",
        "pair_links_candidates.geojson": f"{prefix}_pair_links_candidates.geojson",
        "pair_links_validated.geojson": f"{prefix}_pair_links_validated.geojson",
        "pair_validation_table.csv": f"{prefix}_pair_validation_table.csv",
        "trunk_roads.geojson": f"{prefix}_trunk_roads.geojson",
        "segment_body_roads.geojson": f"{prefix}_segment_body_roads.geojson",
        "step3_residual_roads.geojson": f"{prefix}_residual_roads.geojson",
        "branch_cut_roads.geojson": f"{prefix}_branch_cut_roads.geojson",
    }
    for source_name, target_name in mapping.items():
        source = phase_dir / source_name
        if source.exists():
            shutil.copy2(source, out_root / target_name)


def _load_geojson_doc(path: Path) -> dict[str, Any]:
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
            copied = json.loads(json.dumps(feature, ensure_ascii=False))
            props = dict(copied.get("properties") or {})
            props["step5_phase"] = phase_label
            copied["properties"] = props
            merged_features.append(copied)

    write_json(
        out_path,
        {
            "type": "FeatureCollection",
            "crs": crs or {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": merged_features,
        },
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
) -> PhaseRunArtifacts:
    run_step2_segment_poc(
        road_path=phase_input.working_roads_path,
        node_path=phase_input.working_nodes_path,
        strategy_config_paths=[phase_input.strategy_path],
        out_root=out_root,
        run_id=run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    phase_dir = out_root / phase_input.phase_id
    phase_lower = phase_input.phase_id.lower()
    _copy_phase_review_outputs(phase_dir=phase_dir, out_root=out_root, prefix=phase_lower)
    validated_rows = _read_csv_rows(phase_dir / "validated_pairs.csv")
    road_to_segmentid, _ = _parse_segment_body_assignments(phase_dir / "segment_body_roads.geojson")
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
) -> Step5Artifacts:
    refreshed_nodes_path = out_root / "nodes.geojson"
    refreshed_roads_path = out_root / "roads.geojson"
    refreshed_nodes_alias_path = out_root / "nodes_step5_refreshed.geojson"
    refreshed_roads_alias_path = out_root / "roads_step5_refreshed.geojson"
    summary_path = out_root / "step5_summary.json"
    mainnode_table_path = out_root / "step5_mainnode_refresh_table.csv"

    node_features = [{"properties": node_properties_map[node.node_id], "geometry": node.geometry} for node in nodes]
    road_features = [{"properties": road_properties_map[road.road_id], "geometry": road.geometry} for road in roads]

    write_geojson(refreshed_nodes_path, node_features)
    write_geojson(refreshed_roads_path, road_features)
    write_geojson(refreshed_nodes_alias_path, node_features)
    write_geojson(refreshed_roads_alias_path, road_features)
    write_json(summary_path, summary)
    write_csv(
        mainnode_table_path,
        mainnode_rows,
        [
            "mainnode_id",
            "representative_node_id",
            "participates_in_step5a_pair",
            "participates_in_step5b_pair",
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
    )


def _refresh_after_step5(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    phase_a: PhaseRunArtifacts,
    phase_b: PhaseRunArtifacts,
    out_root: Path,
    preserved_snapshots: dict[str, str],
    step5a_input: PhaseInputArtifacts,
    step5b_input: PhaseInputArtifacts,
    removed_historical_segment_road_count: int,
    removed_step5a_segment_road_count: int,
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

    all_validated_rows = list(phase_a.validated_rows) + list(phase_b.validated_rows)
    step5a_endpoint_ids: set[str] = set()
    step5b_endpoint_ids: set[str] = set()
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

    new_road_to_segmentid = dict(phase_a.road_to_segmentid)
    for road_id, segmentid in phase_b.road_to_segmentid.items():
        existing = new_road_to_segmentid.get(road_id)
        if existing is not None and existing != segmentid:
            raise ValueError(
                f"Road '{road_id}' is assigned to multiple Step5 segment ids: '{existing}' and '{segmentid}'."
            )
        new_road_to_segmentid[road_id] = segmentid

    road_properties_map: dict[str, dict[str, Any]] = {}
    for road in roads:
        props = dict(road.properties)
        existing_segmentid = _current_segmentid(road)
        if existing_segmentid:
            props["segmentid"] = existing_segmentid
            props["s_grade"] = props.get("s_grade")
        elif road.road_id in new_road_to_segmentid:
            props["segmentid"] = new_road_to_segmentid[road.road_id]
            props["s_grade"] = STEP5_NEW_SEGMENT_GRADE
        else:
            props["segmentid"] = props.get("segmentid")
            props["s_grade"] = props.get("s_grade")
        road_properties_map[road.road_id] = props

    group_to_road_ids = _build_group_to_road_ids(
        roads=roads,
        active_road_ids={road.road_id for road in roads},
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
        if mainnode_id in all_endpoint_ids:
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
        "step5_removed_historical_segment_road_count": removed_historical_segment_road_count,
        "step5_removed_step5a_segment_road_count": removed_step5a_segment_road_count,
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
) -> Step5Artifacts:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    nodes, _, _ = _load_nodes(node_path, layer_name=node_layer, crs_override=node_crs)
    roads, _ = _load_roads(road_path, layer_name=road_layer, crs_override=road_crs)

    preserved_snapshots = _preserve_previous_stage_snapshots(
        node_path=node_path,
        road_path=road_path,
        out_root=resolved_out_root,
    )

    historical_segment_road_ids = {road.road_id for road in roads if _current_segmentid(road)}
    active_road_ids_step5a = {road.road_id for road in roads if road.road_id not in historical_segment_road_ids}
    step5a_input = _build_phase_inputs(
        phase_id=STEP5A_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5a,
        out_root=resolved_out_root,
        base_match=_step5a_base_match,
    )
    phase_a = _run_phase(
        phase_input=step5a_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )

    active_road_ids_step5b = set(active_road_ids_step5a) - set(phase_a.road_to_segmentid)
    step5b_input = _build_phase_inputs(
        phase_id=STEP5B_STRATEGY_ID,
        nodes=nodes,
        roads=roads,
        active_road_ids=active_road_ids_step5b,
        out_root=resolved_out_root,
        base_match=_step5b_base_match,
    )
    phase_b = _run_phase(
        phase_input=step5b_input,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )

    merged_validated_rows = _write_merged_validated_pairs(
        phase_rows=[("STEP5A", phase_a.validated_rows), ("STEP5B", phase_b.validated_rows)],
        out_path=resolved_out_root / "step5_validated_pairs_merged.csv",
    )
    _write_merged_geojson(
        paths=[phase_a.phase_dir / "segment_body_roads.geojson", phase_b.phase_dir / "segment_body_roads.geojson"],
        out_path=resolved_out_root / "step5_segment_body_roads_merged.geojson",
        phase_labels=["STEP5A", "STEP5B"],
    )
    _write_merged_geojson(
        paths=[phase_a.phase_dir / "step3_residual_roads.geojson", phase_b.phase_dir / "step3_residual_roads.geojson"],
        out_path=resolved_out_root / "step5_residual_roads_merged.geojson",
        phase_labels=["STEP5A", "STEP5B"],
    )
    write_json(
        resolved_out_root / "strategy_comparison.json",
        {
            "run_id": resolved_run_id,
            "strategies": [
                {"strategy_id": phase_a.phase_id, **phase_a.segment_summary},
                {"strategy_id": phase_b.phase_id, **phase_b.segment_summary},
            ],
        },
    )

    artifacts = _refresh_after_step5(
        nodes=nodes,
        roads=roads,
        phase_a=phase_a,
        phase_b=phase_b,
        out_root=resolved_out_root,
        preserved_snapshots=preserved_snapshots,
        step5a_input=step5a_input,
        step5b_input=step5b_input,
        removed_historical_segment_road_count=len(historical_segment_road_ids),
        removed_step5a_segment_road_count=len(phase_a.road_to_segmentid),
    )
    refreshed_summary = dict(artifacts.summary)
    refreshed_summary["input_node_path"] = str(Path(node_path))
    refreshed_summary["input_road_path"] = str(Path(road_path))
    refreshed_summary["step5a_candidate_pair_count"] = phase_a.candidate_pair_count
    refreshed_summary["step5a_rejected_pair_count"] = phase_a.rejected_pair_count
    refreshed_summary["step5b_candidate_pair_count"] = phase_b.candidate_pair_count
    refreshed_summary["step5b_rejected_pair_count"] = phase_b.rejected_pair_count
    refreshed_summary["step5_merged_validated_pair_count"] = len(merged_validated_rows)
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
    )
    return 0
