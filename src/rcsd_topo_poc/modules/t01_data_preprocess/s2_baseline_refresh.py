from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer, write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    _bit_enabled,
    _coerce_int,
    _find_repo_root,
    _normalize_id,
    _normalize_mainnodeid,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    canonicalize_road_working_properties,
    get_road_segmentid,
    get_road_sgrade,
    initialize_working_layers,
    is_roundabout_mainnode_kind,
    sanitize_public_node_properties,
    set_road_segmentid,
    set_road_sgrade,
)


DEFAULT_RUN_ID_PREFIX = "t01_s2_refresh_node_road_"
RIGHT_TURN_FORMWAY_BIT = 7
SEGMENT_GRADE_VALUE = "0-0\u53cc"


@dataclass(frozen=True)
class NodeFeatureRecord:
    node_id: str
    mainnodeid: Optional[str]
    semantic_node_id: str
    grade: Optional[int]
    kind: Optional[int]
    properties: dict[str, Any]
    geometry: BaseGeometry


def _resolve_working_mainnodeid(properties: dict[str, Any]) -> Optional[str]:
    working_mainnodeid = _normalize_mainnodeid(properties.get("working_mainnodeid"))
    if working_mainnodeid is not None:
        return working_mainnodeid
    return _normalize_mainnodeid(properties.get("mainnodeid"))


@dataclass(frozen=True)
class RoadFeatureRecord:
    road_id: str
    snodeid: str
    enodeid: str
    direction: int
    formway: Optional[int]
    road_kind: Optional[int]
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class MainnodeGroup:
    mainnode_id: str
    representative_node_id: str
    member_node_ids: tuple[str, ...]
    grade_old: Optional[int]
    kind_old: Optional[int]


@dataclass(frozen=True)
class RefreshArtifacts:
    nodes_path: Path
    roads_path: Path
    summary_path: Path
    mainnode_table_path: Path
    preserved_s2_dir: Optional[Path]
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
    return repo_root / "outputs" / "_work" / "t01_s2_refresh_node_road" / resolved_run_id, resolved_run_id


def _resolve_s2_dir(path: Union[str, Path]) -> Path:
    candidate = Path(path)
    direct_validated = candidate / "validated_pairs.csv"
    direct_segment = candidate / "segment_body_roads.geojson"
    if direct_validated.is_file() and direct_segment.is_file():
        return candidate

    nested = candidate / "S2"
    nested_validated = nested / "validated_pairs.csv"
    nested_segment = nested / "segment_body_roads.geojson"
    if nested_validated.is_file() and nested_segment.is_file():
        return nested

    raise ValueError(
        f"Could not resolve S2 baseline directory from '{candidate}'. "
        "Expected validated_pairs.csv and segment_body_roads.geojson either directly under the path or under path/S2."
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _load_validated_pairs(path: Path) -> list[dict[str, str]]:
    rows = _read_csv_rows(path)
    required = {"pair_id", "a_node_id", "b_node_id"}
    if not rows:
        return []
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Validated pair file '{path}' is missing required fields: {sorted(missing)}")
    return rows


def _parse_road_ids(payload: Any, fallback_text: Any) -> tuple[str, ...]:
    if isinstance(payload, list):
        return tuple(
            road_id
            for road_id in (_normalize_id(value) for value in payload)
            if road_id is not None
        )

    if isinstance(fallback_text, str) and fallback_text.strip():
        return tuple(
            road_id
            for road_id in (_normalize_id(value) for value in fallback_text.split(","))
            if road_id is not None
        )

    return ()


def _build_segmentid_base(a_node_id: str, b_node_id: str) -> str:
    return f"{a_node_id}_{b_node_id}"


def _segmentid_matches_base(segmentid: str, base_segmentid: str) -> bool:
    if segmentid == base_segmentid:
        return True
    prefix = f"{base_segmentid}_"
    if not segmentid.startswith(prefix):
        return False
    suffix = segmentid[len(prefix) :]
    return suffix.isdigit()


def _allocate_unique_segmentid(
    *,
    a_node_id: str,
    b_node_id: str,
    used_segmentids: set[str],
    force_suffix: bool,
) -> str:
    base_segmentid = _build_segmentid_base(a_node_id, b_node_id)
    has_family_conflict = force_suffix or any(
        _segmentid_matches_base(segmentid, base_segmentid) for segmentid in used_segmentids
    )
    if not has_family_conflict and base_segmentid not in used_segmentids:
        used_segmentids.add(base_segmentid)
        return base_segmentid

    suffix = 1
    while True:
        candidate = f"{base_segmentid}_{suffix}"
        if candidate not in used_segmentids:
            used_segmentids.add(candidate)
            return candidate
        suffix += 1


def _load_segment_body_assignments(path: Path) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    road_to_segmentid: dict[str, str] = {}
    pair_endpoints: dict[str, tuple[str, str]] = {}
    pending_rows: list[tuple[str, str, str, tuple[str, ...]]] = []
    base_segmentid_counts: dict[str, int] = defaultdict(int)

    for feature in payload.get("features", []):
        props = dict(feature.get("properties") or {})
        if props.get("validated_status") not in {None, "", "validated"}:
            continue

        pair_id = str(props.get("pair_id") or "").strip()
        a_node_id = _normalize_id(props.get("a_node_id"))
        b_node_id = _normalize_id(props.get("b_node_id"))
        if not pair_id or a_node_id is None or b_node_id is None:
            continue

        road_ids = _parse_road_ids(props.get("road_ids"), props.get("road_ids_text"))
        pending_rows.append((pair_id, a_node_id, b_node_id, road_ids))
        base_segmentid_counts[_build_segmentid_base(a_node_id, b_node_id)] += 1

    used_segmentids: set[str] = set()
    for pair_id, a_node_id, b_node_id, road_ids in pending_rows:
        segmentid = _allocate_unique_segmentid(
            a_node_id=a_node_id,
            b_node_id=b_node_id,
            used_segmentids=used_segmentids,
            force_suffix=base_segmentid_counts[_build_segmentid_base(a_node_id, b_node_id)] > 1,
        )
        pair_endpoints[pair_id] = (a_node_id, b_node_id)

        for road_id in road_ids:
            existing = road_to_segmentid.get(road_id)
            if existing is not None and existing != segmentid:
                raise ValueError(
                    f"Road '{road_id}' is assigned to multiple segment ids: '{existing}' and '{segmentid}'."
                )
            road_to_segmentid[road_id] = segmentid

    return road_to_segmentid, pair_endpoints


def _load_nodes(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
) -> tuple[list[NodeFeatureRecord], dict[str, NodeFeatureRecord], dict[str, list[str]]]:
    result = read_vector_layer(path, layer_name=layer_name, crs_override=crs_override)
    ordered_records: list[NodeFeatureRecord] = []
    by_id: dict[str, NodeFeatureRecord] = {}
    groups: dict[str, list[str]] = defaultdict(list)

    for feature in result.features:
        props = canonicalize_road_working_properties(dict(feature.properties))
        node_id = _normalize_id(props.get("id"))
        if node_id is None:
            raise ValueError("Node feature is missing required field 'id'.")

        mainnodeid = _resolve_working_mainnodeid(props)
        semantic_node_id = mainnodeid or node_id
        record = NodeFeatureRecord(
            node_id=node_id,
            mainnodeid=mainnodeid,
            semantic_node_id=semantic_node_id,
            grade=_coerce_int(props.get("grade")),
            kind=_coerce_int(props.get("kind")),
            properties=props,
            geometry=feature.geometry,
        )
        ordered_records.append(record)
        by_id[node_id] = record
        groups[semantic_node_id].append(node_id)

    return ordered_records, by_id, groups


def _build_mainnode_groups(
    node_by_id: dict[str, NodeFeatureRecord],
    groups: dict[str, list[str]],
) -> tuple[dict[str, MainnodeGroup], int]:
    mainnode_groups: dict[str, MainnodeGroup] = {}
    representative_fallback_count = 0

    for mainnode_id, member_ids in groups.items():
        sorted_members = tuple(sorted(member_ids, key=_sort_key))
        representative_node_id = mainnode_id if mainnode_id in node_by_id else sorted_members[0]
        if representative_node_id != mainnode_id:
            representative_fallback_count += 1

        representative = node_by_id[representative_node_id]
        mainnode_groups[mainnode_id] = MainnodeGroup(
            mainnode_id=mainnode_id,
            representative_node_id=representative_node_id,
            member_node_ids=sorted_members,
            grade_old=representative.grade,
            kind_old=representative.kind,
        )

    return mainnode_groups, representative_fallback_count


def _load_roads(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
) -> tuple[list[RoadFeatureRecord], dict[str, RoadFeatureRecord]]:
    result = read_vector_layer(path, layer_name=layer_name, crs_override=crs_override)
    ordered_records: list[RoadFeatureRecord] = []
    by_id: dict[str, RoadFeatureRecord] = {}

    for feature in result.features:
        props = dict(feature.properties)
        road_id = _normalize_id(props.get("id"))
        snodeid = _normalize_id(props.get("snodeid"))
        enodeid = _normalize_id(props.get("enodeid"))
        direction = _coerce_int(props.get("direction"))
        if road_id is None or snodeid is None or enodeid is None or direction is None:
            raise ValueError("Road feature is missing one of required fields: id/snodeid/enodeid/direction.")

        record = RoadFeatureRecord(
            road_id=road_id,
            snodeid=snodeid,
            enodeid=enodeid,
            direction=direction,
            formway=_coerce_int(props.get("formway")),
            road_kind=_coerce_int(props.get("road_kind")),
            properties=props,
            geometry=feature.geometry,
        )
        ordered_records.append(record)
        by_id[road_id] = record

    return ordered_records, by_id


def _load_nodes_and_roads(
    *,
    node_path: Union[str, Path],
    road_path: Union[str, Path],
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
) -> tuple[
    tuple[list[NodeFeatureRecord], dict[str, NodeFeatureRecord], dict[str, list[str]]],
    tuple[list[RoadFeatureRecord], dict[str, RoadFeatureRecord]],
]:
    # Node / Road 读取互不依赖，使用固定 2 worker 并发即可减少大文件加载等待时间。
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="t01-load") as executor:
        future_nodes = executor.submit(_load_nodes, node_path, layer_name=node_layer, crs_override=node_crs)
        future_roads = executor.submit(_load_roads, road_path, layer_name=road_layer, crs_override=road_crs)
        return future_nodes.result(), future_roads.result()


def _road_flow_flags_for_group(road: RoadFeatureRecord, member_node_ids: set[str]) -> tuple[bool, bool]:
    touches_snode = road.snodeid in member_node_ids
    touches_enode = road.enodeid in member_node_ids
    if not touches_snode and not touches_enode:
        return False, False

    if road.direction in {0, 1}:
        return True, True

    if touches_snode and touches_enode:
        return True, True

    if road.direction == 2:
        return touches_enode, touches_snode

    if road.direction == 3:
        return touches_snode, touches_enode

    return False, False


def _current_node_grade_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("grade_2"))


def _current_node_kind_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("kind_2"))


def _write_outputs(
    *,
    node_records: list[NodeFeatureRecord],
    road_records: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    out_root: Path,
    node_output_name: str,
    road_output_name: str,
    summary: dict[str, Any],
    mainnode_rows: list[dict[str, Any]],
    preserved_s2_dir: Optional[Path],
) -> RefreshArtifacts:
    nodes_path = out_root / node_output_name
    roads_path = out_root / road_output_name
    summary_path = out_root / "refresh_summary.json"
    mainnode_table_path = out_root / "mainnode_refresh_table.csv"

    write_geojson(
        nodes_path,
        [
            {"properties": sanitize_public_node_properties(node_properties_map[record.node_id]), "geometry": record.geometry}
            for record in node_records
        ],
    )
    write_geojson(
        roads_path,
        [
            {"properties": road_properties_map[record.road_id], "geometry": record.geometry}
            for record in road_records
        ],
    )
    write_json(summary_path, summary)
    write_csv(
        mainnode_table_path,
        mainnode_rows,
        [
            "mainnode_id",
            "representative_node_id",
            "in_validated_pair",
            "unique_segmentid_count",
            "segmentid_values_text",
            "all_roads_in_one_segment",
            "nonsegment_road_count",
            "nonsegment_all_right_turn_only",
            "nonsegment_has_in",
            "nonsegment_has_out",
            "applied_rule",
            "grade_old",
            "kind_old",
            "grade_2",
            "kind_2",
        ],
    )

    return RefreshArtifacts(
        nodes_path=nodes_path,
        roads_path=roads_path,
        summary_path=summary_path,
        mainnode_table_path=mainnode_table_path,
        preserved_s2_dir=preserved_s2_dir,
        summary=summary,
    )


def _materialize_s2_boundary_snapshot(*, source_s2_dir: Path, target_s2_dir: Path, debug: bool) -> Path:
    target_s2_dir.mkdir(parents=True, exist_ok=True)
    if debug:
        shutil.copytree(source_s2_dir, target_s2_dir, dirs_exist_ok=True)
        return target_s2_dir

    for filename in ("validated_pairs.csv", "endpoint_pool.csv", "endpoint_pool_summary.json"):
        source_path = source_s2_dir / filename
        if source_path.is_file():
            shutil.copy2(source_path, target_s2_dir / filename)
    return target_s2_dir


def refresh_s2_baseline(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    s2_path: Union[str, Path],
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    debug: bool = True,
    assume_working_layers: bool = False,
) -> RefreshArtifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    working_road_path = road_path
    working_node_path = node_path
    if not assume_working_layers:
        bootstrap_artifacts = initialize_working_layers(
            road_path=road_path,
            node_path=node_path,
            out_root=resolved_out_root / "_bootstrap",
            road_layer=road_layer,
            road_crs=road_crs,
            node_layer=node_layer,
            node_crs=node_crs,
            debug=debug,
        )
        working_road_path = bootstrap_artifacts.roads_path
        working_node_path = bootstrap_artifacts.nodes_path

    s2_dir = _resolve_s2_dir(s2_path)
    preserved_s2_dir = _materialize_s2_boundary_snapshot(
        source_s2_dir=s2_dir,
        target_s2_dir=resolved_out_root / "S2",
        debug=debug,
    )
    validated_pairs_path = s2_dir / "validated_pairs.csv"
    segment_body_path = s2_dir / "segment_body_roads.geojson"

    validated_pairs = _load_validated_pairs(validated_pairs_path)
    road_to_segmentid, pair_endpoints_from_segment = _load_segment_body_assignments(segment_body_path)
    (node_records, node_by_id, raw_groups), (road_records, road_by_id) = _load_nodes_and_roads(
        node_path=working_node_path,
        road_path=working_road_path,
    )
    mainnode_groups, representative_fallback_count = _build_mainnode_groups(node_by_id, raw_groups)

    missing_roads = sorted(set(road_to_segmentid) - set(road_by_id), key=_sort_key)
    if missing_roads:
        raise ValueError(f"Some segment_body roads are missing in the original road layer: {missing_roads}")

    validated_endpoint_ids: set[str] = set()
    validated_pair_ids: set[str] = set()
    for row in validated_pairs:
        pair_id = str(row.get("pair_id") or "").strip()
        a_node_id = _normalize_id(row.get("a_node_id"))
        b_node_id = _normalize_id(row.get("b_node_id"))
        if not pair_id or a_node_id is None or b_node_id is None:
            raise ValueError(f"Validated pair row is missing required identifiers: {row}")
        validated_pair_ids.add(pair_id)
        validated_endpoint_ids.add(a_node_id)
        validated_endpoint_ids.add(b_node_id)
        segment_pair = pair_endpoints_from_segment.get(pair_id)
        if segment_pair is not None and segment_pair != (a_node_id, b_node_id):
            raise ValueError(
                f"Validated pair '{pair_id}' endpoints do not match segment_body_roads: "
                f"csv={(a_node_id, b_node_id)} geojson={segment_pair}"
            )

    missing_mainnodes = sorted(validated_endpoint_ids - set(mainnode_groups), key=_sort_key)
    if missing_mainnodes:
        raise ValueError(f"Some validated pair endpoints are missing from the node layer: {missing_mainnodes}")

    road_properties_map: dict[str, dict[str, Any]] = {}
    for road in road_records:
        props = canonicalize_road_working_properties(road.properties)
        existing_segmentid = _normalize_id(get_road_segmentid(props))
        segmentid = road_to_segmentid.get(road.road_id, existing_segmentid)
        set_road_sgrade(props, SEGMENT_GRADE_VALUE if road.road_id in road_to_segmentid else get_road_sgrade(props))
        set_road_segmentid(props, segmentid)
        road_properties_map[road.road_id] = props

    physical_to_semantic = {node_id: group.mainnode_id for group in mainnode_groups.values() for node_id in group.member_node_ids}
    group_to_road_ids: dict[str, set[str]] = defaultdict(set)
    for road in road_records:
        snode_group = physical_to_semantic.get(road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid)
        if snode_group is not None:
            group_to_road_ids[snode_group].add(road.road_id)
        if enode_group is not None:
            group_to_road_ids[enode_group].add(road.road_id)

    node_properties_map: dict[str, dict[str, Any]] = {}
    for node in node_records:
        props = dict(node.properties)
        props["grade_2"] = _current_node_grade_2(node)
        props["kind_2"] = _current_node_kind_2(node)
        node_properties_map[node.node_id] = props

    mainnode_pair_endpoint_count = 0
    mainnode_single_segment_non_intersection_count = 0
    mainnode_right_turn_only_side_count = 0
    mainnode_t_like_count = 0
    multi_segment_mainnode_kept_init_count = 0
    subnode_kept_init_count = sum(max(0, len(group.member_node_ids) - 1) for group in mainnode_groups.values())

    mainnode_rows: list[dict[str, Any]] = []
    for mainnode_id in sorted(mainnode_groups, key=_sort_key):
        group = mainnode_groups[mainnode_id]
        member_id_set = set(group.member_node_ids)
        associated_road_ids = sorted(group_to_road_ids.get(mainnode_id, set()), key=_sort_key)
        associated_roads = [road_by_id[road_id] for road_id in associated_road_ids]

        segment_ids = sorted(
            {road_properties_map[road.road_id]["segmentid"] for road in associated_roads if road_properties_map[road.road_id]["segmentid"]},
            key=_sort_key,
        )
        unique_segmentid_count = len(segment_ids)
        all_roads_in_one_segment = bool(associated_roads) and unique_segmentid_count == 1 and all(
            road_properties_map[road.road_id]["segmentid"] is not None for road in associated_roads
        )

        nonsegment_roads = [road for road in associated_roads if road_properties_map[road.road_id]["segmentid"] is None]
        nonsegment_road_count = len(nonsegment_roads)
        nonsegment_all_right_turn_only = bool(nonsegment_roads) and all(
            _bit_enabled(road.formway, RIGHT_TURN_FORMWAY_BIT) for road in nonsegment_roads
        )

        nonsegment_has_in = False
        nonsegment_has_out = False
        for road in nonsegment_roads:
            has_in, has_out = _road_flow_flags_for_group(road, member_id_set)
            nonsegment_has_in = nonsegment_has_in or has_in
            nonsegment_has_out = nonsegment_has_out or has_out

        representative_props_current = node_properties_map[group.representative_node_id]
        current_grade_2 = _coerce_int(representative_props_current.get("grade_2"))
        current_kind_2 = _coerce_int(representative_props_current.get("kind_2"))
        grade_2 = current_grade_2
        kind_2 = current_kind_2
        applied_rule = "keep_init"

        if is_roundabout_mainnode_kind(current_kind_2):
            applied_rule = "protected_roundabout_mainnode"
        elif mainnode_id in validated_endpoint_ids:
            applied_rule = "validated_pair_endpoint"
            mainnode_pair_endpoint_count += 1
        elif unique_segmentid_count > 1:
            applied_rule = "multi_segment_kept_init"
            multi_segment_mainnode_kept_init_count += 1
        elif all_roads_in_one_segment:
            grade_2 = -1
            kind_2 = 1
            applied_rule = "single_segment_non_intersection"
            mainnode_single_segment_non_intersection_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_all_right_turn_only:
            grade_2 = 3
            kind_2 = 1
            applied_rule = "right_turn_only_side"
            mainnode_right_turn_only_side_count += 1
        elif unique_segmentid_count == 1 and nonsegment_road_count > 0 and nonsegment_has_in and nonsegment_has_out:
            grade_2 = 2
            kind_2 = 2048
            applied_rule = "t_like"
            mainnode_t_like_count += 1

        representative_props = dict(node_properties_map[group.representative_node_id])
        representative_props["grade_2"] = grade_2
        representative_props["kind_2"] = kind_2
        node_properties_map[group.representative_node_id] = representative_props

        mainnode_rows.append(
            {
                "mainnode_id": mainnode_id,
                "representative_node_id": group.representative_node_id,
                "in_validated_pair": mainnode_id in validated_endpoint_ids,
                "unique_segmentid_count": unique_segmentid_count,
                "segmentid_values_text": ",".join(segment_ids),
                "all_roads_in_one_segment": all_roads_in_one_segment,
                "nonsegment_road_count": nonsegment_road_count,
                "nonsegment_all_right_turn_only": nonsegment_all_right_turn_only,
                "nonsegment_has_in": nonsegment_has_in,
                "nonsegment_has_out": nonsegment_has_out,
                "applied_rule": applied_rule,
                "grade_old": group.grade_old,
                "kind_old": group.kind_old,
                "grade_2": grade_2,
                "kind_2": kind_2,
            }
        )

    segment_body_road_count = len(road_to_segmentid)
    summary = {
        "run_id": resolved_run_id,
        "s2_dir": str(s2_dir),
        "road_input_path": str(Path(road_path)),
        "node_input_path": str(Path(node_path)),
        "validated_pair_count": len(validated_pairs),
        "segment_body_road_count": segment_body_road_count,
        "road_written_sgrade_count": sum(1 for props in road_properties_map.values() if props["sgrade"] is not None),
        "road_written_segmentid_count": sum(1 for props in road_properties_map.values() if props["segmentid"] is not None),
        "mainnode_total_count": len(mainnode_groups),
        "mainnode_pair_endpoint_count": mainnode_pair_endpoint_count,
        "mainnode_single_segment_non_intersection_count": mainnode_single_segment_non_intersection_count,
        "mainnode_right_turn_only_side_count": mainnode_right_turn_only_side_count,
        "mainnode_t_like_count": mainnode_t_like_count,
        "multi_segment_mainnode_kept_init_count": multi_segment_mainnode_kept_init_count,
        "subnode_kept_init_count": subnode_kept_init_count,
        "mainnode_representative_fallback_count": representative_fallback_count,
        "validated_pair_ids": sorted(validated_pair_ids, key=_sort_key),
        "preserved_s2_dir": str(preserved_s2_dir) if preserved_s2_dir is not None else None,
        "debug": debug,
    }

    return _write_outputs(
        node_records=node_records,
        road_records=road_records,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        out_root=resolved_out_root,
        node_output_name=Path(node_path).name,
        road_output_name=Path(road_path).name,
        summary=summary,
        mainnode_rows=mainnode_rows,
        preserved_s2_dir=preserved_s2_dir,
    )


def run_s2_baseline_refresh_cli(args: argparse.Namespace) -> int:
    refresh_s2_baseline(
        road_path=args.road_path,
        node_path=args.node_path,
        s2_path=args.s2_path,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        out_root=args.out_root,
        run_id=args.run_id,
        debug=args.debug,
    )
    return 0
