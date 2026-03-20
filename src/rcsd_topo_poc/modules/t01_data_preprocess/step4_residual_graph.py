from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes,
    _load_roads,
    _road_flow_flags_for_group,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    _coerce_int,
    _find_repo_root,
    _normalize_id,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc


DEFAULT_RUN_ID_PREFIX = "t01_step4_residual_graph_"
STEP4_NEW_SEGMENT_GRADE = "0-1\u53cc"
STEP4_STRATEGY_ID = "STEP4"


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
    grade_2 = _coerce_int(node.properties.get("grade_2"))
    if grade_2 is not None:
        return grade_2
    return node.grade


def _current_kind_2(node: NodeFeatureRecord) -> Optional[int]:
    kind_2 = _coerce_int(node.properties.get("kind_2"))
    if kind_2 is not None:
        return kind_2
    return node.kind


def _current_closed_con(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("closed_con"))


def _current_segmentid(road: RoadFeatureRecord) -> Optional[str]:
    return _normalize_id(road.properties.get("segmentid"))


def _build_step4_inputs(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    out_root: Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
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
        if grade_2 in {1, 2} and kind_2 in {4, 2048}:
            input_mainnode_candidate_count += 1
            if closed_con in {1, 2}:
                input_seed_count += 1
            else:
                input_closed_con_filtered_out_count += 1

    input_terminate_count = input_seed_count

    working_node_features: list[dict[str, Any]] = []
    for node in nodes:
        props = dict(node.properties)
        grade_2 = _current_grade_2(node)
        kind_2 = _current_kind_2(node)
        closed_con = _current_closed_con(node)
        if grade_2 in {1, 2} and kind_2 in {4, 2048} and closed_con in {1, 2}:
            props["grade"] = 1
            props["kind"] = 4
            props["step4_input_eligible"] = True
        else:
            props["grade"] = 0
            props["kind"] = 0
            props["step4_input_eligible"] = False
        props["step4_input_grade_2"] = grade_2
        props["step4_input_kind_2"] = kind_2
        props["step4_input_closed_con"] = closed_con
        working_node_features.append({"properties": props, "geometry": node.geometry})

    removed_existing_segment_road_count = 0
    working_road_features: list[dict[str, Any]] = []
    for road in roads:
        current_segmentid = _current_segmentid(road)
        if current_segmentid:
            removed_existing_segment_road_count += 1
            continue
        working_road_features.append({"properties": dict(road.properties), "geometry": road.geometry})

    working_graph_road_count = len(working_road_features)
    working_nodes_path = out_root / "step4_working_nodes.geojson"
    working_roads_path = out_root / "step4_working_roads.geojson"
    strategy_path = out_root / "step4_strategy.json"

    write_geojson(working_nodes_path, working_node_features)
    write_geojson(working_roads_path, working_road_features)
    write_json(
        strategy_path,
        {
            "strategy_id": STEP4_STRATEGY_ID,
            "description": "Step4 residual graph segment construction using refreshed grade_2/kind_2/closed_con.",
            "seed_rule": {"kind_bits_all": [2], "grade_eq": 1, "closed_con_in": [1, 2]},
            "terminate_rule": {"kind_bits_all": [2], "grade_eq": 1, "closed_con_in": [1, 2]},
            "through_node_rule": {"incident_road_degree_eq": 2, "incident_degree_exclude_formway_bits_any": [7]},
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
            "removed_existing_segment_road_count": removed_existing_segment_road_count,
            "working_graph_road_count": working_graph_road_count,
            "mainnode_representative_fallback_count": representative_fallback_count,
        },
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


def _preserve_previous_s2_snapshot(*, node_path: Union[str, Path], road_path: Union[str, Path], out_root: Path) -> Optional[Path]:
    node_parent = Path(node_path).resolve().parent
    road_parent = Path(road_path).resolve().parent
    if node_parent != road_parent:
        return None

    source_s2_dir = node_parent / "S2"
    if not source_s2_dir.is_dir():
        return None

    target_s2_dir = out_root / "S2"
    shutil.copytree(source_s2_dir, target_s2_dir, dirs_exist_ok=True)
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
        if mainnode_id in validated_endpoint_ids:
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
) -> Step4Artifacts:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    nodes, _, _ = _load_nodes(node_path, layer_name=node_layer, crs_override=node_crs)
    roads, _ = _load_roads(road_path, layer_name=road_layer, crs_override=road_crs)

    working_nodes_path, working_roads_path, strategy_path, input_audit = _build_step4_inputs(
        nodes=nodes,
        roads=roads,
        out_root=resolved_out_root,
    )

    step4_results = run_step2_segment_poc(
        road_path=working_roads_path,
        node_path=working_nodes_path,
        strategy_config_paths=[strategy_path],
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    if len(step4_results) != 1:
        raise ValueError(f"Expected one Step4 strategy result, got {len(step4_results)}.")

    step4_dir = resolved_out_root / STEP4_STRATEGY_ID
    _copy_step4_review_outputs(step4_dir, resolved_out_root)
    preserved_prev_s2_dir = _preserve_previous_s2_snapshot(
        node_path=node_path,
        road_path=road_path,
        out_root=resolved_out_root,
    )

    validated_pairs = _read_csv_rows(step4_dir / "validated_pairs.csv")
    new_road_to_segmentid, _pair_endpoints = _parse_segment_body_assignments(step4_dir / "segment_body_roads.geojson")

    return _refresh_after_step4(
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
    )
    return 0
