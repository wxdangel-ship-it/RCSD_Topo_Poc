from __future__ import annotations

import ast
import csv
import heapq
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyproj import CRS
from shapely.geometry import Point

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_crs,
    _read_nodes,
    _read_roads,
    _resolve_case_paths,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


ACTUAL_ATTACHMENT_ACTIONS = {
    "reuse_existing_rcsd_endpoint_node": "REUSE_ENDPOINT",
    "split_rcsd_road_for_swsd_advance": "SPLIT_ROAD",
}
DETERMINISTIC_NORMALIZATION_ACTION = "normalize_swsd_singleton_mainnode"


def build_advance_right_attachment_supervision(
    *,
    enriched_attachment_store_root: Path,
    target_label_root: Path,
    poc_data_root: Path,
    output_root: Path,
) -> Path:
    """Extract exact T06 attachment actions without making them inference inputs."""
    attachment_root = normalize_runtime_path(
        enriched_attachment_store_root
    ).resolve(strict=True)
    label_root = normalize_runtime_path(target_label_root).resolve(strict=True)
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    objects = {
        _object_key(row): row
        for row in _read_jsonl(attachment_root / "advance_right_objects.jsonl")
    }
    plan_labels = {
        _object_key(row): row
        for row in _read_jsonl(attachment_root / "advance_right_labels.jsonl")
    }
    attachments = _read_jsonl(
        attachment_root / "advance_right_attachment_labels.jsonl"
    )
    case_rows = {
        str(row["case_key"]): row
        for row in _read_jsonl(label_root / "case_inventory.jsonl")
    }
    case_keys = sorted({str(row["case_key"]) for row in attachments})
    raw_road_stores: dict[str, dict[str, Any]] = {}
    final_road_stores: dict[str, list[Any]] = {}
    node_stores: dict[str, dict[str, Point]] = {}
    relation_stores: dict[str, dict[str, dict[str, str]]] = {}
    input_records = []
    for case_key in case_keys:
        paths, _ = _resolve_case_paths(
            baseline_root=label_root,
            case_row=case_rows[case_key],
            poc_data_root=data_root,
        )
        crs_values = {
            _read_crs(paths.raw_rcsd_roads),
            _read_crs(paths.t06_final_nodes),
        }
        if len(crs_values) != 1:
            raise ValueError(f"attachment label CRS differs: {case_key}")
        if not _metric_projected(next(iter(crs_values))):
            raise ValueError(f"attachment label CRS is not metric: {case_key}")
        raw_road_stores[case_key] = {
            road.road_id: road for road in _read_roads(paths.raw_rcsd_roads)
        }
        final_road_stores[case_key] = _read_roads(paths.t06_final_roads)
        node_stores[case_key] = _read_nodes(paths.t06_final_nodes)
        relation_stores[case_key] = _read_relation_store(paths.t06_relation)
        for role, path in (
            ("RAW_RCSD_ROADS", paths.raw_rcsd_roads),
            ("T06_RELATION_LABEL_ONLY", paths.t06_relation),
            ("T06_FINAL_ROADS_LABEL_ONLY", paths.t06_final_roads),
            ("T06_FINAL_NODES_LABEL_ONLY", paths.t06_final_nodes),
        ):
            input_records.append(
                {
                    "case_key": case_key,
                    "role": role,
                    **_input_record(path),
                }
            )

    action_groups: Counter[tuple[str, str, str]] = Counter()
    prepared = []
    normalization_rows = []
    for attachment in attachments:
        key = _object_key(attachment)
        obj = objects[key]
        for action in attachment.get("attachment_actions") or ():
            action_name = str(action.get("action") or "")
            if action_name == DETERMINISTIC_NORMALIZATION_ACTION:
                normalization_rows.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": key[0],
                        "object_id": key[1],
                        "action": action_name,
                        "swsd_node_id": str(action.get("swsd_node_id") or ""),
                        "model_target": False,
                        "deterministic_only": True,
                        "label_only": True,
                        "inference_input_allowed": False,
                    }
                )
                continue
            if action_name not in ACTUAL_ATTACHMENT_ACTIONS:
                raise ValueError(f"unknown T06 attachment action: {action_name}")
            side = _action_side(action, obj)
            action_groups[(key[0], key[1], side)] += 1
            prepared.append((attachment, obj, action, side))

    counts: Counter[str] = Counter()
    rows = []
    unresolved = []
    for attachment, obj, action, side in prepared:
        key = _object_key(attachment)
        plan = plan_labels[key]
        action_name = str(action["action"])
        adjacent_segment_id = _adjacent_segment_id(attachment, side)
        replacement_segment_ids = sorted(
            {
                str(value)
                for value in action.get("replacement_segment_ids") or ()
                if str(value)
            }
        )
        parent_road_id = str(action.get("rcsd_road_id") or "")
        reasons = []
        if side == "UNRESOLVED":
            reasons.append("SIDE_DEPENDENCY_UNRESOLVED")
        if action_groups[(key[0], key[1], side)] != 1:
            reasons.append("SIDE_ACTION_NOT_UNIQUE")
        if attachment.get("topology_hard_failures"):
            reasons.append("TOPOLOGY_HARD_FAILURE")
        if not adjacent_segment_id:
            reasons.append("ADJACENT_SEGMENT_UNRESOLVED")
        elif adjacent_segment_id not in replacement_segment_ids:
            reasons.append("ADJACENT_SEGMENT_NOT_IN_T06_REPLACEMENT_SCOPE")
        if float(plan.get("label_weight") or 0.0) <= 0.0:
            reasons.append("LABEL_SCOPE_WEIGHT_ZERO")

        final_parent = None
        if side != "UNRESOLVED" and adjacent_segment_id:
            try:
                final_parent = resolve_final_access_parent(
                    action,
                    adjacent_segment_id=adjacent_segment_id,
                    relation=relation_stores[key[0]].get(
                        adjacent_segment_id
                    ),
                    final_roads=final_road_stores[key[0]],
                )
            except ValueError as error:
                reasons.append(str(error))
        final_position = _final_parent_position(
            action,
            final_parent=final_parent,
            final_nodes=node_stores[key[0]],
        )
        if final_position["state"] == "UNRESOLVED":
            reasons.append("FINAL_ACCESS_PARENT_POSITION_UNRESOLVED")
        raw_road = raw_road_stores[key[0]].get(parent_road_id)
        if raw_road is None:
            break_position = _empty_position()
            break_position["state"] = "PRE_BREAK_PARENT_IS_T06_GENERATED"
        else:
            try:
                break_position = resolve_action_position(
                    action,
                    road=raw_road,
                    final_nodes=node_stores[key[0]],
                )
            except ValueError:
                break_position = _empty_position()
                break_position["state"] = "PRE_BREAK_POSITION_UNRESOLVED"

        task_mask = not reasons
        state = (
            "EXACT_T06_SIDE_ATTACHMENT"
            if task_mask
            else "MASKED_T06_ATTACHMENT"
        )
        counts[state] += 1
        counts[f"action_{action_name}"] += 1
        counts[f"side_{side.lower()}"] += 1
        counts["legacy_plan_task_mask"] += int(
            bool(plan.get("plan_task_mask"))
        )
        row = {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "case_key": key[0],
            "object_id": key[1],
            "fold": int(plan["fold"]),
            "side": side,
            "adjacent_segment_id": adjacent_segment_id,
            "swsd_access_node_id": str(action.get("swsd_node_id") or ""),
            "pre_break_parent_road_id": parent_road_id,
            "final_access_parent_road_id": (
                str(final_parent.road_id) if final_parent is not None else ""
            ),
            "attachment_operation": ACTUAL_ATTACHMENT_ACTIONS[action_name],
            "final_access_parent_endpoint_fraction": final_position["fraction"],
            "attachment_position_x": final_position["x"],
            "attachment_position_y": final_position["y"],
            "position_to_final_parent_road_m": final_position["gap_m"],
            "position_label_state": final_position["state"],
            "pre_break_parent_position_fraction_audit": break_position[
                "fraction"
            ],
            "pre_break_position_state_audit": break_position["state"],
            "replacement_segment_ids": replacement_segment_ids,
            "adjacent_segment_in_t06_replacement_scope": (
                bool(adjacent_segment_id)
                and adjacent_segment_id in replacement_segment_ids
            ),
            "supervision_state": state,
            "attachment_task_mask": task_mask,
            "attachment_label_weight": float(plan["label_weight"]),
            "weak_auxiliary_weight": (
                0.0
                if task_mask
                else (
                    0.3
                    if side != "UNRESOLVED"
                    and "FINAL_ACCESS_PARENT_UNREACHABLE"
                    in reasons
                    else 0.0
                )
            ),
            "mask_reasons": sorted(set(reasons)),
            "legacy_plan_candidate_reachable": bool(
                plan.get("plan_task_mask")
            ),
            "generated_node_id_audit": str(
                action.get("generated_rcsd_node_id") or ""
            ),
            "reused_node_id_audit": str(action.get("rcsd_node_id") or ""),
            "t06_projected_gap_m_audit": _optional_float(
                action.get("projected_gap_m")
            ),
            "label_only": True,
            "inference_input_allowed": False,
            "terminal_feature_count": 0,
        }
        rows.append(row)
        if not task_mask:
            unresolved.append(row)

    rows.sort(key=_row_sort_key)
    normalization_rows.sort(key=_row_sort_key)
    unresolved.sort(key=_row_sort_key)
    label_path = root / "advance_right_attachment_supervision.jsonl"
    normalization_path = root / "deterministic_normalization_audit.jsonl"
    unresolved_path = root / "unresolved_attachment_audit.jsonl"
    _write_jsonl(label_path, rows)
    _write_jsonl(normalization_path, normalization_rows)
    _write_jsonl(unresolved_path, unresolved)
    exact_count = counts["EXACT_T06_SIDE_ATTACHMENT"]
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_T06_ATTACHMENT_SUPERVISION_AUDIT",
        "business_contract": {
            "model_output": (
                "for each RCSD side, select one adjacent ordinary parent Road "
                "and one split or reused-endpoint position"
            ),
            "deterministic_output": (
                "generate the final Node id and execute the selected geometry"
            ),
            "joint_constraint": (
                "the selected parent Road must belong to the already selected "
                "complete ordinary Segment Road plan"
            ),
            "fallback": (
                "an unresolved side dependency masks this attachment label and "
                "causes only the AdvanceRight Segment to abstain at inference"
            ),
        },
        "label_policy": {
            "exact_t06_action": (
                "strong field supervision with the inherited Case label weight"
            ),
            "conditional_nearest_geometry_replay": (
                "weak supervision kept outside this exact-action store"
            ),
            "t06_terminal_fields": (
                "label-only; never copied into inference features"
            ),
        },
        "counts": {
            **dict(sorted(counts.items())),
            "actual_attachment_actions": len(rows),
            "deterministic_normalization_actions": len(normalization_rows),
            "exact_action_labels": exact_count,
            "masked_action_labels": len(unresolved),
            "weak_action_only_labels": sum(
                float(row["weak_auxiliary_weight"]) > 0.0 for row in rows
            ),
            "weak_labels_mixed_into_exact_store": 0,
        },
        "inputs": {
            "attachment_store": _input_record(
                attachment_root / "advance_right_attachment_labels.jsonl"
            ),
            "object_store": _input_record(
                attachment_root / "advance_right_objects.jsonl"
            ),
            "plan_label_store": _input_record(
                attachment_root / "advance_right_labels.jsonl"
            ),
            "geometry_inputs": input_records,
        },
        "outputs": {
            "attachment_supervision": _input_record(label_path),
            "deterministic_normalization_audit": _input_record(
                normalization_path
            ),
            "unresolved_attachment_audit": _input_record(unresolved_path),
        },
        "crs_consistent": True,
        "crs_metric": True,
        "silent_fix": False,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "gate_pass": (
            len(rows) == 756
            and len(normalization_rows) == 725
            and exact_count + len(unresolved) == len(rows)
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight attachment supervision audit differs")
    return root


def resolve_action_position(
    action: Mapping[str, Any],
    *,
    road: Any,
    final_nodes: Mapping[str, Point],
) -> dict[str, Any]:
    action_name = str(action.get("action") or "")
    if action_name == "split_rcsd_road_for_swsd_advance":
        node_id = str(action.get("generated_rcsd_node_id") or "")
        state = "T06_GENERATED_NODE_PROJECTED_TO_PARENT_ROAD"
    elif action_name == "reuse_existing_rcsd_endpoint_node":
        node_id = str(action.get("rcsd_node_id") or "")
        state = "T06_REUSED_ENDPOINT"
    else:
        raise ValueError("POSITION_ACTION_UNSUPPORTED")
    point = final_nodes.get(node_id)
    if point is None:
        raise ValueError("T06_POSITION_NODE_MISSING")
    length = float(road.geometry.length)
    if length <= 0.0:
        raise ValueError("PARENT_RCSD_ROAD_ZERO_LENGTH")
    distance = float(road.geometry.project(point))
    fraction = min(max(distance / length, 0.0), 1.0)
    projected = road.geometry.interpolate(distance)
    if action_name == "reuse_existing_rcsd_endpoint_node":
        node_matches_endpoint = node_id in {road.snodeid, road.enodeid}
        fraction_is_endpoint = fraction <= 1e-9 or fraction >= 1.0 - 1e-9
        if not node_matches_endpoint or not fraction_is_endpoint:
            raise ValueError("T06_REUSED_NODE_NOT_PARENT_ENDPOINT")
    return {
        "fraction": fraction,
        "x": float(projected.x),
        "y": float(projected.y),
        "gap_m": float(point.distance(projected)),
        "state": state,
    }


def resolve_final_access_parent(
    action: Mapping[str, Any],
    *,
    adjacent_segment_id: str,
    relation: Mapping[str, str] | None,
    final_roads: Sequence[Any],
) -> Any:
    """Resolve the post-break Road piece that leads to the ordinary carrier."""
    if relation is None:
        raise ValueError("ADJACENT_SEGMENT_RELATION_MISSING")
    status = str(relation.get("relation_status") or "")
    if status not in {"replaced", "replaced+retained_swsd"}:
        raise ValueError("ADJACENT_SEGMENT_FINAL_SOURCE_NOT_RCSD")
    owner_ids = _parse_id_list(relation.get("owned_frcsd_road_ids"))
    if not owner_ids:
        owner_ids = _parse_id_list(relation.get("frcsd_road_ids"))
    allowed_ids = set(owner_ids)
    for field in (
        "frcsd_road_ids",
        "related_connectivity_road_ids",
        "related_special_junction_internal_road_ids",
    ):
        allowed_ids.update(_parse_id_list(relation.get(field)))
    allowed_roads = [
        road
        for road in final_roads
        if _road_reference_ids(road) & allowed_ids
    ]
    target_nodes = {
        node_id
        for road in allowed_roads
        if _road_reference_ids(road) & owner_ids
        for node_id in (road.snodeid, road.enodeid)
    }
    if not target_nodes:
        raise ValueError("ADJACENT_SEGMENT_FINAL_CARRIER_MISSING")
    distances = _distance_to_nodes(allowed_roads, target_nodes)
    action_parent_id = str(action.get("rcsd_road_id") or "")
    action_node_id = str(
        action.get("generated_rcsd_node_id")
        or action.get("rcsd_node_id")
        or ""
    )
    candidates = [
        road
        for road in allowed_roads
        if action_parent_id in _road_reference_ids(road)
        and action_node_id in {road.snodeid, road.enodeid}
    ]
    scores = []
    for road in candidates:
        other_node = (
            road.enodeid if road.snodeid == action_node_id else road.snodeid
        )
        distance = distances.get(other_node)
        if distance is not None:
            scores.append(
                (float(road.geometry.length) + distance, road.road_id, road)
            )
    if not scores:
        raise ValueError("FINAL_ACCESS_PARENT_UNREACHABLE")
    best = min(value for value, _, _ in scores)
    selected = [
        road for value, _, road in scores if abs(value - best) <= 1e-6
    ]
    if len(selected) != 1:
        raise ValueError("FINAL_ACCESS_PARENT_AMBIGUOUS")
    return selected[0]


def _final_parent_position(
    action: Mapping[str, Any],
    *,
    final_parent: Any | None,
    final_nodes: Mapping[str, Point],
) -> dict[str, Any]:
    if final_parent is None:
        return _empty_position()
    node_id = str(
        action.get("generated_rcsd_node_id")
        or action.get("rcsd_node_id")
        or ""
    )
    point = final_nodes.get(node_id)
    if point is None:
        return _empty_position()
    if node_id == final_parent.snodeid:
        fraction = 0.0
    elif node_id == final_parent.enodeid:
        fraction = 1.0
    else:
        return _empty_position()
    projected = final_parent.geometry.interpolate(
        0.0 if fraction == 0.0 else float(final_parent.geometry.length)
    )
    return {
        "fraction": fraction,
        "x": float(point.x),
        "y": float(point.y),
        "gap_m": float(point.distance(projected)),
        "state": "T06_FINAL_ACCESS_PARENT_ENDPOINT",
    }


def _distance_to_nodes(
    roads: Sequence[Any],
    target_nodes: set[str],
) -> dict[str, float]:
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for road in roads:
        length = max(float(road.geometry.length), 1e-6)
        adjacency[road.snodeid].append((road.enodeid, length))
        adjacency[road.enodeid].append((road.snodeid, length))
    distances = {node_id: 0.0 for node_id in target_nodes}
    queue = [(0.0, node_id) for node_id in target_nodes]
    heapq.heapify(queue)
    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance != distances[node_id]:
            continue
        for neighbor, length in adjacency[node_id]:
            candidate = distance + length
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return distances


def _road_reference_ids(road: Any) -> set[str]:
    return {
        str(road.road_id or ""),
        str(road.source_road_id or ""),
        str(road.split_original_road_id or ""),
    } - {""}


def _parse_id_list(value: Any) -> set[str]:
    if value is None or str(value).strip() == "":
        return set()
    parsed = ast.literal_eval(str(value))
    if not isinstance(parsed, (list, tuple, set)):
        parsed = [parsed]
    return {
        str(item)
        for item in parsed
        if str(item).strip() and str(item).strip() != "[]"
    }


def _read_relation_store(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {
            str(row["swsd_segment_id"]): dict(row)
            for row in csv.DictReader(stream)
        }


def _action_side(
    action: Mapping[str, Any],
    obj: Mapping[str, Any],
) -> str:
    node_id = str(action.get("swsd_node_id") or "")
    source = str(obj.get("source_access_node_id") or "")
    target = str(obj.get("target_access_node_id") or "")
    if node_id and node_id == source:
        return "SOURCE"
    if node_id and node_id == target:
        return "TARGET"
    return "UNRESOLVED"


def _adjacent_segment_id(
    attachment: Mapping[str, Any],
    side: str,
) -> str:
    if side == "SOURCE":
        return str(attachment.get("source_adjacent_segment_id") or "")
    if side == "TARGET":
        return str(attachment.get("target_adjacent_segment_id") or "")
    return ""


def _empty_position() -> dict[str, Any]:
    return {
        "fraction": None,
        "x": None,
        "y": None,
        "gap_m": None,
        "state": "UNRESOLVED",
    }


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _metric_projected(value: str) -> bool:
    crs = CRS.from_user_input(value)
    return crs.is_projected and all(
        str(axis.unit_name or "").lower() in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    )


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("case_key") or ""),
        str(row.get("object_id") or ""),
        str(row.get("side") or ""),
        str(row.get("swsd_node_id") or row.get("swsd_access_node_id") or ""),
    )


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "build_advance_right_attachment_supervision",
    "resolve_final_access_parent",
    "resolve_action_position",
]
