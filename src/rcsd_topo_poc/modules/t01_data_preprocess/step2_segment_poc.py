from __future__ import annotations

import argparse
import gc
import inspect
import json
import pickle
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime
from heapq import heappop, heappush
from itertools import count
from math import ceil, hypot
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Union

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import (
    build_endpoint_pool_source_map,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step2_output_utils import (
    _iter_pair_arbitration_rows,
    _pair_conflict_components_payload,
    _write_step2_outputs_bundle,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_validation_utils import (
    PairValidationResult,
    Step2StrategyResult,
    _arbitration_boundary_node_ids,
    _arbitration_semantic_conflict_node_ids,
    _arbitration_strong_anchor_node_ids,
    _arbitration_tjunction_anchor_node_ids,
    _arbitration_weak_endpoint_node_ids,
    _empty_pair_arbitration_outcome,
    _pair_validation_from_option,
    _road_length_index,
    _road_node_index,
    _single_pair_illegal_validation,
    _validation_road_count,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_release_utils import (
    _compact_branch_cut_info,
    _compact_option_for_validation_runtime,
    _compact_option_support_info_for_runtime,
    _compact_execution_for_validation,
    _compact_validation_result_for_release,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_trunk_utils import (
    DirectedPath,
    TrunkCandidate,
    _TrunkEvaluationChoice,
    _alternative_trunk_only_road_ids,
    _build_direction_support_index,
    _build_direction_support_index_from_adjacency,
    _build_filtered_directed_adjacency,
    _classify_attachment_flow_status,
    _classify_component_directionality,
    _classify_parallel_corridor_directionality,
    _collect_segment_path_road_ids,
    _collect_transition_same_dir_block_infos,
    _dual_separation_support_info,
    _evaluate_through_collapsed_corridor,
    _evaluate_trunk,
    _evaluate_trunk_choices,
    _geometry_coords,
    _geometry_length,
    _is_tjunction_support_anchor_node,
    _line_geometry_from_coords,
    _line_geometry_from_road_ids,
    _max_nearest_distance_m,
    _max_sampled_distance_m,
    _minimal_trunk_chain_gate_info,
    _minimal_loop_long_branch_gate_info,
    _road_matches_any_formway_bits,
    _road_matches_formway_bit,
    _tjunction_node_kind,
    _trunk_candidate_counterclockwise_ok,
    _trunk_candidate_mode,
    _tjunction_vertical_tracking_gate_info,
    _bidirectional_side_bypass_gate_info,
    _bidirectional_minimal_loop_extra_branch_gate_info,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import (
    PairArbitrationDecision,
    PairArbitrationOption,
    PairArbitrationOutcome,
    arbitrate_pair_options,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    RoadRecord,
    SemanticNodeRecord,
    Step1GraphContext,
    Step1StrategyExecution,
    StrategySpec,
    ThroughRuleSpec,
    TraversalEdge,
    _bit_enabled,
    _find_repo_root,
    _load_strategy,
    _sort_key,
    build_step1_graph_context,
    run_step1_strategy,
    write_step1_candidate_outputs,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
    initialize_working_layers,
    is_allowed_road_kind,
)


DEFAULT_RUN_ID_PREFIX = "t01_step2_segment_poc_"
LEFT_TURN_FORMWAY_BIT = 8
MAX_PATHS_PER_DIRECTION = 12
MAX_PATH_DEPTH = 64
SIDE_ACCESS_SAMPLE_STEP_M = MAX_SIDE_ACCESS_DISTANCE_M / 2.0
VALIDATION_PROGRESS_CHECKPOINT_INTERVAL = 1000
VALIDATION_BATCH_SIZE = 1000
VALIDATION_PHASE_TRACE_PAIR_LIMIT = 50


def _semantic_node_priority_grade(node: Optional[SemanticNodeRecord]) -> int:
    if node is None:
        return 0
    return int(getattr(node, "grade_2", 0) or node.raw_properties.get("grade") or node.raw_grade or 0)


def _pair_endpoint_priority_grades(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
) -> tuple[int, int]:
    grades = (
        _semantic_node_priority_grade(context.semantic_nodes.get(pair.a_node_id)),
        _semantic_node_priority_grade(context.semantic_nodes.get(pair.b_node_id)),
    )
    return tuple(sorted(grades, reverse=True))


@dataclass(frozen=True)
class NonTrunkComponent:
    component_id: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    attachment_node_ids: tuple[str, ...]
    internal_support_attachment_node_ids: tuple[str, ...]
    internal_t_support_attachment_node_ids: tuple[str, ...]
    component_directionality: str
    bidirectional_road_ids: tuple[str, ...]
    attachment_flow_status: str
    attachment_direction_labels: tuple[str, ...]
    parallel_corridor_directionality: str
    parallel_corridor_directions: tuple[str, ...]
    hits_other_terminate: bool
    terminate_node_ids: tuple[str, ...]
    contains_other_validated_trunk: bool
    conflicting_pair_ids: tuple[str, ...]
    blocked_by_transition_same_dir: bool
    transition_block_infos: tuple[dict[str, Any], ...]
    side_access_metric: str
    side_access_distance_m: Optional[float]
    side_access_gate_passed: bool
    kept_as_segment_body: bool
    moved_to_step3_residual: bool
    moved_to_branch_cut: bool
    decision_reason: str


Step2ProgressCallback = Callable[[str, dict[str, Any]], None]


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
    return repo_root / "outputs" / "_work" / "t01_step2_segment_poc" / resolved_run_id, resolved_run_id


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_json_doc(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_pickle_doc(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fp:
        pickle.dump(payload, fp, protocol=pickle.HIGHEST_PROTOCOL)


def _read_pickle_doc(path: Path) -> Any:
    with path.open("rb") as fp:
        return pickle.load(fp)


def _restore_validation_winner_option(
    option: PairArbitrationOption,
    *,
    restore_payload: dict[str, Any],
) -> PairArbitrationOption:
    support_info = dict(option.support_info)
    support_info.update(restore_payload.get("support_info_extras", {}))
    return replace(option, support_info=support_info)


def _format_cli_progress_details(payload: dict[str, Any]) -> str:
    detail_keys = (
        "strategy_id",
        "strategy_index",
        "strategy_count",
        "pair_index",
        "validation_count",
        "pair_id",
        "phase",
        "validated_status",
        "reject_reason",
        "trunk_found",
        "candidate_road_count",
        "pruned_road_count",
        "segment_road_count",
        "candidate_pair_count",
        "validated_pair_count",
        "rejected_pair_count",
        "search_seed_count",
        "terminate_count",
        "road_count",
        "physical_node_count",
        "semantic_node_count",
        "semantic_endpoint_road_count",
        "undirected_node_count",
        "requested_pair_count",
        "requested_pair_index_start",
        "requested_pair_index_end",
        "matched_pair_count",
        "output_dir",
        "gc_collected_objects",
    )
    parts: list[str] = []
    for key in detail_keys:
        if key not in payload:
            continue
        parts.append(f"{key}={payload[key]}")
    return " ".join(parts)


def _write_step2_cli_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    message: Optional[str],
    current_event: Optional[str] = None,
    failed_event: Optional[str] = None,
) -> None:
    _write_json_doc(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "current_event": current_event,
            "failed_event": failed_event,
            "message": message,
        },
    )


def _make_step2_cli_progress_callback(
    *,
    run_id: str,
    out_root: Path,
) -> tuple[Step2ProgressCallback, Path, Path]:
    progress_path = out_root / "t01_step2_segment_poc_progress.json"
    perf_markers_path = out_root / "t01_step2_segment_poc_perf_markers.jsonl"

    def _callback(event: str, payload: dict[str, Any]) -> None:
        control_payload = dict(payload)
        perf_log = bool(control_payload.pop("_perf_log", True))
        stdout_log = bool(control_payload.pop("_stdout_log", True))
        details = _format_cli_progress_details(control_payload)
        message = f"Step2 {event}."
        if details:
            message = f"{message} {details}"
        _write_step2_cli_progress_snapshot(
            out_path=progress_path,
            run_id=run_id,
            status="running",
            current_event=event,
            message=message,
        )
        if perf_log:
            _append_jsonl(
                perf_markers_path,
                {
                    "event": "step2_subprogress",
                    "at": _now_text(),
                    "run_id": run_id,
                    "substage_event": event,
                    "payload": control_payload,
                },
            )
        if stdout_log:
            suffix = f" {details}" if details else ""
            print(f"[{_now_text()}] step2:{event}{suffix}", flush=True)

    _write_step2_cli_progress_snapshot(
        out_path=progress_path,
        run_id=run_id,
        status="initializing",
        current_event=None,
        message="Step2 CLI initialized.",
    )
    _append_jsonl(
        perf_markers_path,
        {
            "event": "step2_run_start",
            "at": _now_text(),
            "run_id": run_id,
        },
    )
    return _callback, progress_path, perf_markers_path


def _emit_progress(
    progress_callback: Optional[Step2ProgressCallback],
    event: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload)




def _collect_road_node_ids(
    road_ids: Iterable[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    node_ids: set[str] = set()
    for road_id in road_ids:
        node_ids.update(road_endpoints.get(road_id, ()))
    return node_ids


def _build_semantic_endpoints(
    context: Step1GraphContext,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[TraversalEdge, ...]]]:
    road_endpoints: dict[str, tuple[str, str]] = {}
    undirected_lists: dict[str, list[TraversalEdge]] = defaultdict(list)

    for road in context.roads.values():
        if not is_allowed_road_kind(road.road_kind):
            continue
        if road.snodeid not in context.physical_nodes or road.enodeid not in context.physical_nodes:
            continue

        semantic_snode_id = context.physical_to_semantic.get(road.snodeid, road.snodeid)
        semantic_enode_id = context.physical_to_semantic.get(road.enodeid, road.enodeid)
        if semantic_snode_id == semantic_enode_id:
            continue

        road_endpoints[road.road_id] = (semantic_snode_id, semantic_enode_id)
        undirected_lists[semantic_snode_id].append(TraversalEdge(road.road_id, semantic_snode_id, semantic_enode_id))
        undirected_lists[semantic_enode_id].append(TraversalEdge(road.road_id, semantic_enode_id, semantic_snode_id))

    return road_endpoints, {node_id: tuple(edges) for node_id, edges in undirected_lists.items()}


def _build_candidate_channel(
    pair: PairRecord,
    *,
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    protected = {pair.a_node_id, pair.b_node_id}
    support_node_ids = set(pair.forward_path_node_ids) | set(pair.reverse_path_node_ids)
    support_road_ids = set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids)
    candidate_road_ids: set[str] = set(support_road_ids)
    boundary_terminate_ids: set[str] = set()

    for start_node_id in sorted(support_node_ids, key=_sort_key):
        for edge in undirected_adjacency.get(start_node_id, ()):
            if edge.road_id in candidate_road_ids:
                continue

            previous_node_id = start_node_id
            current_node_id = edge.to_node
            current_road_id = edge.road_id
            candidate_road_ids.add(current_road_id)

            while True:
                if current_node_id in support_node_ids:
                    break
                if current_node_id in boundary_node_ids and current_node_id not in protected:
                    boundary_terminate_ids.add(current_node_id)
                    break

                next_edges = [
                    next_edge
                    for next_edge in undirected_adjacency.get(current_node_id, ())
                    if next_edge.to_node != previous_node_id and next_edge.road_id not in candidate_road_ids
                ]
                if not next_edges:
                    break
                if len(next_edges) > 1:
                    break

                next_edge = next_edges[0]
                candidate_road_ids.add(next_edge.road_id)
                previous_node_id = current_node_id
                current_node_id = next_edge.to_node

    return candidate_road_ids, boundary_terminate_ids


def _build_segment_body_candidate_channel(
    pair: PairRecord,
    *,
    trunk_road_ids: tuple[str, ...],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: Optional[set[str]] = None,
) -> set[str]:
    protected = {pair.a_node_id, pair.b_node_id}
    start_node_ids = _collect_road_node_ids(trunk_road_ids, road_endpoints=road_endpoints)
    candidate_road_ids: set[str] = set(trunk_road_ids)
    allowed_road_id_set = set(allowed_road_ids) if allowed_road_ids is not None else None

    for start_node_id in sorted(start_node_ids, key=_sort_key):
        for edge in undirected_adjacency.get(start_node_id, ()):
            if allowed_road_id_set is not None and edge.road_id not in allowed_road_id_set:
                continue
            if edge.road_id in candidate_road_ids:
                continue

            queue: deque[TraversalEdge] = deque([edge])
            while queue:
                current_edge = queue.popleft()
                if allowed_road_id_set is not None and current_edge.road_id not in allowed_road_id_set:
                    continue
                if current_edge.road_id in candidate_road_ids:
                    continue

                candidate_road_ids.add(current_edge.road_id)
                current_node_id = current_edge.to_node
                if current_node_id in boundary_node_ids and current_node_id not in protected:
                    continue

                for next_edge in undirected_adjacency.get(current_node_id, ()):
                    if allowed_road_id_set is not None and next_edge.road_id not in allowed_road_id_set:
                        continue
                    if next_edge.road_id in candidate_road_ids:
                        continue
                    queue.append(next_edge)

    non_trunk_candidate_road_ids = candidate_road_ids - set(trunk_road_ids)
    retained_non_trunk_road_ids: set[str] = set()
    for component_road_ids, component_node_ids in _collect_components(
        non_trunk_candidate_road_ids,
        road_endpoints=road_endpoints,
    ):
        attachment_node_ids = set(component_node_ids) & start_node_ids
        if len(attachment_node_ids) >= 2:
            retained_non_trunk_road_ids.update(component_road_ids)

    return set(trunk_road_ids) | retained_non_trunk_road_ids


def _expand_segment_body_allowed_road_ids(
    *,
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    """Recover local bridge roads between branch-backtrack-pruned fragments.

    Trunk search intentionally keeps a narrow candidate channel, and prune may
    cut side-corridor attachments as backtracking leaves. For segment_body
    recovery we only stitch short local bridge components between those pruned
    branch anchors, while avoiding an unrestricted walk over the whole graph.
    """

    allowed_road_ids = set(pruned_road_ids)
    backtrack_infos = [
        info
        for info in branch_cut_infos
        if str(info.get("cut_reason", "")) == "branch_backtrack_prune" and info.get("road_id") in road_endpoints
    ]
    if not backtrack_infos:
        return allowed_road_ids

    normalized_backtrack_infos = [
        (
            str(info["road_id"]),
            str(info["from_node_id"]),
            str(info["to_node_id"]),
        )
        for info in backtrack_infos
        if info.get("from_node_id") and info.get("to_node_id")
    ]
    if len(normalized_backtrack_infos) < 2:
        return allowed_road_ids

    max_bridge_depth = 6
    outer_anchor_node_ids = {anchor_node_id for _, anchor_node_id, _ in normalized_backtrack_infos}
    branch_anchor_road_ids = {road_id for road_id, _, _ in normalized_backtrack_infos}

    for index, (start_anchor_road_id, start_node_id, start_attach_node_id) in enumerate(normalized_backtrack_infos):
        for end_anchor_road_id, end_node_id, end_attach_node_id in normalized_backtrack_infos[index + 1 :]:
            if start_attach_node_id == end_attach_node_id:
                continue
            queue: deque[tuple[str, tuple[str, ...], tuple[str, ...]]] = deque(
                [(start_node_id, (), (start_node_id,))]
            )
            visited_states: set[tuple[str, int]] = {(start_node_id, 0)}
            bridge_path_road_ids: Optional[tuple[str, ...]] = None

            while queue:
                current_node_id, road_path, node_path = queue.popleft()
                if len(road_path) >= max_bridge_depth:
                    continue

                for edge in undirected_adjacency.get(current_node_id, ()):
                    road_id = edge.road_id
                    if road_id in allowed_road_ids:
                        continue
                    if road_id in branch_anchor_road_ids:
                        continue
                    next_node_id = edge.to_node
                    if next_node_id in node_path:
                        continue
                    if next_node_id in boundary_node_ids and next_node_id not in {start_node_id, end_node_id}:
                        continue
                    if next_node_id in outer_anchor_node_ids and next_node_id not in {start_node_id, end_node_id}:
                        continue

                    next_road_path = (*road_path, road_id)
                    if next_node_id == end_node_id:
                        bridge_path_road_ids = next_road_path
                        break

                    state = (next_node_id, len(next_road_path))
                    if state in visited_states:
                        continue
                    visited_states.add(state)
                    queue.append((next_node_id, next_road_path, (*node_path, next_node_id)))

                if bridge_path_road_ids is not None:
                    break

            if bridge_path_road_ids:
                allowed_road_ids.update((start_anchor_road_id, end_anchor_road_id))
                allowed_road_ids.update(bridge_path_road_ids)

    return allowed_road_ids


def _build_incident_map(
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> dict[str, set[str]]:
    incident: dict[str, set[str]] = defaultdict(set)
    for road_id in road_ids:
        endpoints = road_endpoints.get(road_id)
        if endpoints is None:
            continue
        a_node_id, b_node_id = endpoints
        incident[a_node_id].add(road_id)
        incident[b_node_id].add(road_id)
    return incident


def _collect_components(
    road_ids: set[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    if not road_ids:
        return []

    incident = _build_incident_map(road_ids, road_endpoints)
    components: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    visited_nodes: set[str] = set()

    for start_node_id in sorted(incident.keys(), key=_sort_key):
        if start_node_id in visited_nodes:
            continue
        queue: deque[str] = deque([start_node_id])
        component_node_ids: set[str] = set()
        component_road_ids: set[str] = set()
        visited_nodes.add(start_node_id)

        while queue:
            node_id = queue.popleft()
            component_node_ids.add(node_id)
            for road_id in incident.get(node_id, set()):
                component_road_ids.add(road_id)
                other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
                if other_node_id in visited_nodes:
                    continue
                visited_nodes.add(other_node_id)
                queue.append(other_node_id)

        if component_road_ids:
            components.append(
                (
                    tuple(sorted(component_road_ids, key=_sort_key)),
                    tuple(sorted(component_node_ids, key=_sort_key)),
                )
            )

    return components


def _other_endpoint(road_id: str, node_id: str, road_endpoints: dict[str, tuple[str, str]]) -> str:
    a_node_id, b_node_id = road_endpoints[road_id]
    return b_node_id if node_id == a_node_id else a_node_id


def _remaining_degree(node_id: str, incident: dict[str, set[str]], remaining_road_ids: set[str]) -> int:
    return sum(1 for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)


def _path_exists_undirected(
    start_node_id: str,
    end_node_id: str,
    *,
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> bool:
    if start_node_id == end_node_id:
        return True
    if not road_ids:
        return False

    incident = _build_incident_map(road_ids, road_endpoints)
    queue: deque[str] = deque([start_node_id])
    visited = {start_node_id}

    while queue:
        current_node_id = queue.popleft()
        for road_id in incident.get(current_node_id, set()):
            next_node_id = _other_endpoint(road_id, current_node_id, road_endpoints)
            if next_node_id == end_node_id:
                return True
            if next_node_id in visited:
                continue
            visited.add(next_node_id)
            queue.append(next_node_id)

    return False


def _path_exists_directed(
    start_node_id: str,
    end_node_id: str,
    *,
    adjacency: dict[str, tuple[TraversalEdge, ...]],
) -> bool:
    if start_node_id == end_node_id:
        return True

    queue: deque[str] = deque([start_node_id])
    visited = {start_node_id}

    while queue:
        current_node_id = queue.popleft()
        for edge in adjacency.get(current_node_id, ()):
            next_node_id = edge.to_node
            if next_node_id == end_node_id:
                return True
            if next_node_id in visited:
                continue
            visited.add(next_node_id)
            queue.append(next_node_id)

    return False


def _count_components(
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> int:
    if not road_ids:
        return 0

    incident = _build_incident_map(road_ids, road_endpoints)
    remaining_nodes = {node_id for node_id, node_road_ids in incident.items() if node_road_ids}
    component_count = 0
    visited: set[str] = set()

    for node_id in sorted(remaining_nodes, key=_sort_key):
        if node_id in visited:
            continue
        component_count += 1
        queue: deque[str] = deque([node_id])
        visited.add(node_id)
        while queue:
            current_node_id = queue.popleft()
            for road_id in incident.get(current_node_id, set()):
                next_node_id = _other_endpoint(road_id, current_node_id, road_endpoints)
                if next_node_id in visited:
                    continue
                visited.add(next_node_id)
                queue.append(next_node_id)

    return component_count


def _collect_component_road_ids(
    start_node_id: str,
    *,
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    if not road_ids:
        return set()

    incident = _build_incident_map(road_ids, road_endpoints)
    if start_node_id not in incident:
        return set()

    component_road_ids: set[str] = set()
    visited_nodes: set[str] = {start_node_id}
    queue: deque[str] = deque([start_node_id])

    while queue:
        node_id = queue.popleft()
        for road_id in incident.get(node_id, set()):
            if road_id not in road_ids:
                continue
            component_road_ids.add(road_id)
            other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
            if other_node_id in visited_nodes:
                continue
            visited_nodes.add(other_node_id)
            queue.append(other_node_id)

    return component_road_ids


def _find_bridge_road_ids(
    road_ids: set[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    if not road_ids:
        return set()

    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for road_id in road_ids:
        snode_id, enode_id = road_endpoints[road_id]
        adjacency[snode_id].append((enode_id, road_id))
        adjacency[enode_id].append((snode_id, road_id))

    timer = count()
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    bridge_road_ids: set[str] = set()

    def dfs(node_id: str, parent_road_id: Optional[str]) -> None:
        disc[node_id] = next(timer)
        low[node_id] = disc[node_id]

        for next_node_id, road_id in adjacency.get(node_id, []):
            if road_id == parent_road_id:
                continue
            if next_node_id not in disc:
                dfs(next_node_id, road_id)
                low[node_id] = min(low[node_id], low[next_node_id])
                if low[next_node_id] > disc[node_id]:
                    bridge_road_ids.add(road_id)
            else:
                low[node_id] = min(low[node_id], disc[next_node_id])

    for node_id in sorted(adjacency.keys(), key=_sort_key):
        if node_id not in disc:
            dfs(node_id, None)

    return bridge_road_ids


def _prune_candidate_channel(
    pair: PairRecord,
    *,
    candidate_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    terminate_ids: set[str],
    hard_stop_node_ids: set[str],
) -> tuple[set[str], list[dict[str, Any]], bool]:
    protected = {pair.a_node_id, pair.b_node_id}
    remaining_road_ids = set(candidate_road_ids)
    incident = _build_incident_map(remaining_road_ids, road_endpoints)
    queue: deque[str] = deque(
        node_id
        for node_id in sorted(incident.keys(), key=_sort_key)
        if node_id not in protected and _remaining_degree(node_id, incident, remaining_road_ids) == 1
    )
    branch_cut_infos: list[dict[str, Any]] = []

    while queue:
        node_id = queue.popleft()
        if node_id in protected:
            continue
        if _remaining_degree(node_id, incident, remaining_road_ids) != 1:
            continue

        road_id = next(road_id for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)
        other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
        current_connects_protected = _path_exists_undirected(
            pair.a_node_id,
            pair.b_node_id,
            road_ids=remaining_road_ids,
            road_endpoints=road_endpoints,
        )
        if current_connects_protected and not _path_exists_undirected(
            pair.a_node_id,
            pair.b_node_id,
            road_ids=remaining_road_ids - {road_id},
            road_endpoints=road_endpoints,
        ):
            continue
        if node_id in hard_stop_node_ids and node_id not in protected:
            cut_reason = "branch_leads_to_historical_boundary"
        elif node_id in terminate_ids and node_id not in protected:
            cut_reason = "branch_leads_to_other_terminate"
        else:
            cut_reason = "branch_backtrack_prune"
        branch_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": cut_reason,
                "from_node_id": node_id,
                "to_node_id": other_node_id,
            }
        )
        remaining_road_ids.remove(road_id)
        incident[node_id].discard(road_id)
        incident[other_node_id].discard(road_id)

        if other_node_id not in protected and _remaining_degree(other_node_id, incident, remaining_road_ids) == 1:
            queue.append(other_node_id)

    disconnected_after_prune = True
    if remaining_road_ids:
        disconnected_after_prune = (
            _count_components(remaining_road_ids, road_endpoints) != 1
            or not _path_exists_undirected(
                pair.a_node_id,
                pair.b_node_id,
                road_ids=remaining_road_ids,
                road_endpoints=road_endpoints,
            )
        )

    return remaining_road_ids, branch_cut_infos, disconnected_after_prune


def _refine_segment_roads(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    pruned_road_ids: set[str],
    trunk_road_ids: tuple[str, ...],
    through_rule: ThroughRuleSpec,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    if not pruned_road_ids:
        return (), []

    remaining_road_ids = set(pruned_road_ids)
    trunk_road_id_set = set(trunk_road_ids)
    segment_cut_infos: list[dict[str, Any]] = []

    # Step1 uses these formway bits to collapse pseudo-intersection branches.
    # Step2 should not keep the same roads in final segment retention.
    if through_rule.incident_degree_exclude_formway_bits_any:
        for road_id in sorted(tuple(remaining_road_ids), key=_sort_key):
            if road_id in trunk_road_id_set:
                continue
            road = context.roads[road_id]
            if not _road_matches_any_formway_bits(road, through_rule.incident_degree_exclude_formway_bits_any):
                continue
            remaining_road_ids.remove(road_id)
            from_node_id, to_node_id = road_endpoints[road_id]
            segment_cut_infos.append(
                {
                    "road_id": road_id,
                    "cut_reason": "segment_exclude_formway",
                    "from_node_id": from_node_id,
                    "to_node_id": to_node_id,
                }
            )

    protected_nodes = {pair.a_node_id, pair.b_node_id}
    changed = True
    while changed and remaining_road_ids:
        changed = False
        incident = _build_incident_map(remaining_road_ids, road_endpoints)
        queue: deque[str] = deque(
            node_id
            for node_id in sorted(incident.keys(), key=_sort_key)
            if node_id not in protected_nodes and _remaining_degree(node_id, incident, remaining_road_ids) == 1
        )

        while queue:
            node_id = queue.popleft()
            if node_id in protected_nodes:
                continue
            if _remaining_degree(node_id, incident, remaining_road_ids) != 1:
                continue

            road_id = next(road_id for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)
            if road_id in trunk_road_id_set:
                continue

            other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
            remaining_road_ids.remove(road_id)
            incident[node_id].discard(road_id)
            incident[other_node_id].discard(road_id)
            segment_cut_infos.append(
                {
                    "road_id": road_id,
                    "cut_reason": "segment_backtrack_prune",
                    "from_node_id": node_id,
                    "to_node_id": other_node_id,
                }
            )
            changed = True

            if other_node_id not in protected_nodes and _remaining_degree(other_node_id, incident, remaining_road_ids) == 1:
                queue.append(other_node_id)

        bridge_road_ids = _find_bridge_road_ids(remaining_road_ids, road_endpoints=road_endpoints)
        removable_bridge_road_ids = sorted(bridge_road_ids - trunk_road_id_set, key=_sort_key)
        if removable_bridge_road_ids:
            changed = True
            for road_id in removable_bridge_road_ids:
                if road_id not in remaining_road_ids:
                    continue
                from_node_id, to_node_id = road_endpoints[road_id]
                remaining_road_ids.remove(road_id)
                segment_cut_infos.append(
                    {
                        "road_id": road_id,
                        "cut_reason": "segment_bridge_prune",
                        "from_node_id": from_node_id,
                        "to_node_id": to_node_id,
                    }
                )

    component_road_ids = _collect_component_road_ids(
        pair.a_node_id,
        road_ids=remaining_road_ids,
        road_endpoints=road_endpoints,
    )
    for road_id in sorted(remaining_road_ids - component_road_ids, key=_sort_key):
        from_node_id, to_node_id = road_endpoints[road_id]
        segment_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": "segment_disconnected_component_prune",
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
            }
        )

    final_road_ids = component_road_ids if component_road_ids else trunk_road_id_set
    if not trunk_road_id_set.issubset(final_road_ids):
        final_road_ids |= trunk_road_id_set

    path_road_ids = _collect_segment_path_road_ids(
        pair,
        context=context,
        road_endpoints=road_endpoints,
        allowed_road_ids=final_road_ids,
    )
    removable_non_path_road_ids = sorted((final_road_ids - path_road_ids) - trunk_road_id_set, key=_sort_key)
    for road_id in removable_non_path_road_ids:
        from_node_id, to_node_id = road_endpoints[road_id]
        segment_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": "segment_non_path_prune",
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
            }
        )
    if path_road_ids:
        final_road_ids = path_road_ids | trunk_road_id_set

    return tuple(sorted(final_road_ids, key=_sort_key)), segment_cut_infos


def _collect_internal_boundary_nodes(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    blocked_node_ids: set[str],
) -> tuple[str, ...]:
    if not blocked_node_ids:
        return ()
    internal_nodes = (set(candidate.forward_path.node_ids[1:-1]) | set(candidate.reverse_path.node_ids[1:-1])) - {
        pair.a_node_id,
        pair.b_node_id,
    }
    return tuple(sorted((node_id for node_id in internal_nodes if node_id in blocked_node_ids), key=_sort_key))


def _component_to_dict(component: NonTrunkComponent) -> dict[str, Any]:
    return {
        "component_id": component.component_id,
        "road_ids": list(component.road_ids),
        "node_ids": list(component.node_ids),
        "attachment_node_ids": list(component.attachment_node_ids),
        "internal_support_attachment_node_ids": list(component.internal_support_attachment_node_ids),
        "internal_t_support_attachment_node_ids": list(component.internal_t_support_attachment_node_ids),
        "component_directionality": component.component_directionality,
        "bidirectional_road_ids": list(component.bidirectional_road_ids),
        "attachment_flow_status": component.attachment_flow_status,
        "attachment_direction_labels": list(component.attachment_direction_labels),
        "parallel_corridor_directionality": component.parallel_corridor_directionality,
        "parallel_corridor_directions": list(component.parallel_corridor_directions),
        "hits_other_terminate": component.hits_other_terminate,
        "terminate_node_ids": list(component.terminate_node_ids),
        "contains_other_validated_trunk": component.contains_other_validated_trunk,
        "conflicting_pair_ids": list(component.conflicting_pair_ids),
        "blocked_by_transition_same_dir": component.blocked_by_transition_same_dir,
        "transition_block_infos": list(component.transition_block_infos),
        "side_access_metric": component.side_access_metric,
        "side_access_distance_m": component.side_access_distance_m,
        "side_access_gate_passed": component.side_access_gate_passed,
        "kept_as_segment_body": component.kept_as_segment_body,
        "moved_to_step3_residual": component.moved_to_step3_residual,
        "moved_to_branch_cut": component.moved_to_branch_cut,
        "decision_reason": component.decision_reason,
    }


def _is_same_endpoint_parallel_closure_component(
    *,
    pair: PairRecord,
    validation: PairValidationResult,
    component_directionality: str,
    attachment_flow_status: str,
    attachment_node_ids: tuple[str, ...],
    parallel_corridor_directionality: str,
    roads: dict[str, RoadRecord],
    road_endpoints: dict[str, tuple[str, str]],
) -> bool:
    if component_directionality != "one_way_only":
        return False
    if attachment_flow_status != "single_departure_return":
        return False
    if parallel_corridor_directionality != "one_way_parallel":
        return False
    if tuple(sorted(attachment_node_ids, key=_sort_key)) != tuple(sorted({pair.a_node_id, pair.b_node_id}, key=_sort_key)):
        return False
    if len(validation.trunk_road_ids) != 1:
        return False
    if not bool(validation.support_info.get("bidirectional_minimal_loop")):
        return False

    trunk_road_id = validation.trunk_road_ids[0]
    trunk_road = roads.get(trunk_road_id)
    if trunk_road is None or trunk_road.direction not in {0, 1}:
        return False
    return set(road_endpoints.get(trunk_road_id, ())) == {pair.a_node_id, pair.b_node_id}


def _road_supports_traversal(
    road: RoadRecord,
    *,
    from_node_id: str,
    to_node_id: str,
) -> bool:
    if road.snodeid == from_node_id and road.enodeid == to_node_id:
        return road.direction in {0, 1, 2}
    if road.enodeid == from_node_id and road.snodeid == to_node_id:
        return road.direction in {0, 1, 3}
    return False


def _replace_path_road_ids_with_parallel_twin(
    *,
    path_node_ids: tuple[str, ...],
    path_road_ids: tuple[str, ...],
    old_trunk_road_id: str,
    new_parallel_road_id: str,
    new_parallel_road: RoadRecord,
) -> Optional[tuple[str, ...]]:
    if old_trunk_road_id not in path_road_ids:
        return path_road_ids

    if len(path_node_ids) != len(path_road_ids) + 1:
        return None

    updated_road_ids = list(path_road_ids)
    replaced = False
    for index, road_id in enumerate(path_road_ids):
        if road_id != old_trunk_road_id:
            continue
        from_node_id = path_node_ids[index]
        to_node_id = path_node_ids[index + 1]
        if not _road_supports_traversal(
            new_parallel_road,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
        ):
            return None
        updated_road_ids[index] = new_parallel_road_id
        replaced = True

    return tuple(updated_road_ids) if replaced else path_road_ids


def _dedupe_preserving_order(road_ids: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for road_id in road_ids:
        if road_id in seen:
            continue
        seen.add(road_id)
        ordered.append(road_id)
    return tuple(ordered)


def _swap_internal_parallel_oneway_twin_into_trunk(
    *,
    pair: PairRecord,
    validation: PairValidationResult,
    support_info: dict[str, Any],
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    trunk_road_id_set: set[str],
    trunk_node_id_set: set[str],
    internal_support_node_id_set: set[str],
    body_candidate_road_ids: set[str],
) -> PairValidationResult:
    body_candidate_non_trunk_road_ids = body_candidate_road_ids - trunk_road_id_set
    if not body_candidate_non_trunk_road_ids or len(validation.trunk_road_ids) <= 1:
        return validation

    direct_bidirectional_trunk_by_nodes: dict[tuple[str, str], str] = {}
    ambiguous_direct_trunk_node_pairs: set[tuple[str, str]] = set()
    for trunk_road_id in validation.trunk_road_ids:
        trunk_endpoints = road_endpoints.get(trunk_road_id)
        trunk_road = context.roads.get(trunk_road_id)
        if trunk_endpoints is None or trunk_road is None or trunk_road.direction not in {0, 1}:
            continue
        if not set(trunk_endpoints).issubset(internal_support_node_id_set):
            continue
        trunk_node_pair = tuple(sorted(trunk_endpoints, key=_sort_key))
        if trunk_node_pair in direct_bidirectional_trunk_by_nodes:
            ambiguous_direct_trunk_node_pairs.add(trunk_node_pair)
            continue
        direct_bidirectional_trunk_by_nodes[trunk_node_pair] = trunk_road_id
    for trunk_node_pair in ambiguous_direct_trunk_node_pairs:
        direct_bidirectional_trunk_by_nodes.pop(trunk_node_pair, None)

    if not direct_bidirectional_trunk_by_nodes:
        return validation

    updated_validation = validation
    updated_forward_path_road_ids = tuple(
        str(road_id) for road_id in support_info.get("forward_path_road_ids", ())
    )
    updated_reverse_path_road_ids = tuple(
        str(road_id) for road_id in support_info.get("reverse_path_road_ids", ())
    )
    updated_trunk_road_ids = list(validation.trunk_road_ids)
    swap_infos: list[dict[str, Any]] = []

    for component_road_ids, component_node_ids in _collect_components(
        set(body_candidate_non_trunk_road_ids),
        road_endpoints=road_endpoints,
    ):
        if len(component_road_ids) != 1:
            continue
        component_road_id = component_road_ids[0]
        component_road = context.roads.get(component_road_id)
        if component_road is None or component_road.direction not in {2, 3}:
            continue

        attachment_node_ids = tuple(
            sorted((set(component_node_ids) & trunk_node_id_set), key=_sort_key)
        )
        if len(attachment_node_ids) != 2:
            continue
        if not set(attachment_node_ids).issubset(internal_support_node_id_set):
            continue

        component_directed_adjacency = _build_filtered_directed_adjacency(
            context.roads,
            road_endpoints=road_endpoints,
            allowed_road_ids={component_road_id},
            exclude_left_turn=False,
            left_turn_formway_bit=LEFT_TURN_FORMWAY_BIT,
        )
        component_direction_support_index = _build_direction_support_index_from_adjacency(
            component_directed_adjacency
        )
        component_directionality, _ = _classify_component_directionality(
            (component_road_id,),
            roads=context.roads,
        )
        attachment_flow_status, _ = _classify_attachment_flow_status(
            component_road_ids=(component_road_id,),
            attachment_node_ids=attachment_node_ids,
            road_endpoints=road_endpoints,
            direction_support_index=component_direction_support_index,
        )
        parallel_corridor_directionality, _ = _classify_parallel_corridor_directionality(
            attachment_node_ids=attachment_node_ids,
            directed_adjacency=component_directed_adjacency,
        )
        if component_directionality != "one_way_only":
            continue
        if attachment_flow_status != "single_departure_return":
            continue
        if parallel_corridor_directionality != "one_way_parallel":
            continue

        attachment_node_pair = tuple(sorted(attachment_node_ids, key=_sort_key))
        direct_trunk_road_id = direct_bidirectional_trunk_by_nodes.get(attachment_node_pair)
        if direct_trunk_road_id is None:
            continue

        replaced_forward_path_road_ids = _replace_path_road_ids_with_parallel_twin(
            path_node_ids=pair.forward_path_node_ids,
            path_road_ids=updated_forward_path_road_ids,
            old_trunk_road_id=direct_trunk_road_id,
            new_parallel_road_id=component_road_id,
            new_parallel_road=component_road,
        )
        replaced_reverse_path_road_ids = _replace_path_road_ids_with_parallel_twin(
            path_node_ids=pair.reverse_path_node_ids,
            path_road_ids=updated_reverse_path_road_ids,
            old_trunk_road_id=direct_trunk_road_id,
            new_parallel_road_id=component_road_id,
            new_parallel_road=component_road,
        )
        if replaced_forward_path_road_ids is None or replaced_reverse_path_road_ids is None:
            continue
        if (
            direct_trunk_road_id not in updated_forward_path_road_ids
            and direct_trunk_road_id not in updated_reverse_path_road_ids
        ):
            continue

        updated_forward_path_road_ids = replaced_forward_path_road_ids
        updated_reverse_path_road_ids = replaced_reverse_path_road_ids
        updated_trunk_road_ids = [
            component_road_id if road_id == direct_trunk_road_id else road_id
            for road_id in updated_trunk_road_ids
        ]
        trunk_road_id_set.discard(direct_trunk_road_id)
        trunk_road_id_set.add(component_road_id)
        direct_bidirectional_trunk_by_nodes.pop(attachment_node_pair, None)
        swap_infos.append(
            {
                "decision_reason": "internal_support_parallel_twin_swap",
                "pair_id": validation.pair_id,
                "attachment_node_ids": list(attachment_node_pair),
                "replaced_trunk_road_id": direct_trunk_road_id,
                "promoted_parallel_road_id": component_road_id,
            }
        )

    if not swap_infos:
        return validation

    support_info["forward_path_road_ids"] = list(updated_forward_path_road_ids)
    support_info["reverse_path_road_ids"] = list(updated_reverse_path_road_ids)
    support_info["pair_support_road_ids"] = list(
        _dedupe_preserving_order(updated_forward_path_road_ids + updated_reverse_path_road_ids)
    )
    existing_swap_infos = list(support_info.get("internal_parallel_trunk_swap_infos", []))
    existing_swap_infos.extend(swap_infos)
    support_info["internal_parallel_trunk_swap_infos"] = existing_swap_infos
    updated_validation = replace(
        validation,
        trunk_road_ids=tuple(updated_trunk_road_ids),
        support_info=support_info,
    )
    return updated_validation


def _tighten_validated_segment_components(
    validations: list[PairValidationResult],
    *,
    execution: Step1StrategyExecution,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[PairValidationResult]:
    pair_lookup = {pair.pair_id: pair for pair in execution.pair_candidates}
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    validated_trunk_owner_by_road = {
        road_id: validation.pair_id
        for validation in validations
        if validation.validated_status == "validated"
        for road_id in validation.trunk_road_ids
    }
    validated_internal_support_owners_by_node: dict[str, set[str]] = defaultdict(set)
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        pair = pair_lookup.get(validation.pair_id)
        if pair is None:
            continue
        internal_support_node_ids = (
            set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1])
        ) - {pair.a_node_id, pair.b_node_id}
        for node_id in internal_support_node_ids:
            validated_internal_support_owners_by_node[node_id].add(validation.pair_id)
    direction_support_index = _build_direction_support_index(context)

    tightened: list[PairValidationResult] = []
    for validation in validations:
        if validation.validated_status != "validated":
            tightened.append(validation)
            continue

        pair = pair_lookup.get(validation.pair_id)
        if pair is None:
            tightened.append(validation)
            continue

        support_info = dict(validation.support_info)
        branch_cut_infos = list(support_info.get("branch_cut_infos", []))
        residual_infos: list[dict[str, Any]] = []
        component_infos: list[dict[str, Any]] = []
        branch_cut_seen = {(info.get("road_id"), info.get("cut_reason")) for info in branch_cut_infos}

        trunk_road_id_set = set(validation.trunk_road_ids)
        trunk_node_id_set = _collect_road_node_ids(validation.trunk_road_ids, road_endpoints=road_endpoints)
        internal_support_node_ids = tuple(
            sorted(
                (
                    (set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1]))
                    - {pair.a_node_id, pair.b_node_id}
                ),
                key=_sort_key,
            )
        )
        internal_support_node_id_set = set(internal_support_node_ids)
        internal_t_support_node_ids = tuple(
            sorted(
                (
                    node_id
                    for node_id in (
                        (set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1]))
                        - {pair.a_node_id, pair.b_node_id}
                    )
                    if node_id in context.semantic_nodes
                    and _bit_enabled(context.semantic_nodes[node_id].kind_2, 11)
                ),
                key=_sort_key,
            )
        )
        internal_t_support_node_id_set = set(internal_t_support_node_ids)
        pruned_road_id_set = set(validation.pruned_road_ids)
        trunk_geometry = _line_geometry_from_road_ids(validation.trunk_road_ids, roads=context.roads)

        if validation.trunk_mode in {"through_collapsed_corridor", "mirrored_one_sided_corridor"}:
            body_candidate_road_ids = set(validation.trunk_road_ids)
            refine_cut_infos: list[dict[str, Any]] = []
        elif "segment_body_candidate_road_ids" in support_info:
            body_candidate_road_ids = {
                str(road_id) for road_id in support_info.get("segment_body_candidate_road_ids", [])
            }
            refine_cut_infos = [dict(info) for info in support_info.get("segment_body_candidate_cut_infos", [])]
        else:
            body_candidate_road_ids, refine_cut_infos = _refine_segment_roads(
                pair,
                context=context,
                road_endpoints=road_endpoints,
                pruned_road_ids=pruned_road_id_set,
                trunk_road_ids=validation.trunk_road_ids,
                through_rule=execution.strategy.through_rule,
            )
            body_candidate_road_ids = set(body_candidate_road_ids)

        validation = _swap_internal_parallel_oneway_twin_into_trunk(
            pair=pair,
            validation=validation,
            support_info=support_info,
            context=context,
            road_endpoints=road_endpoints,
            trunk_road_id_set=trunk_road_id_set,
            trunk_node_id_set=trunk_node_id_set,
            internal_support_node_id_set=internal_support_node_id_set,
            body_candidate_road_ids=body_candidate_road_ids,
        )
        trunk_road_id_set = set(validation.trunk_road_ids)
        trunk_node_id_set = _collect_road_node_ids(validation.trunk_road_ids, road_endpoints=road_endpoints)
        trunk_geometry = _line_geometry_from_road_ids(validation.trunk_road_ids, roads=context.roads)
        body_candidate_non_trunk_road_ids = body_candidate_road_ids - trunk_road_id_set

        refine_cut_reason_by_road: dict[str, set[str]] = defaultdict(set)
        for info in refine_cut_infos:
            road_id = str(info["road_id"])
            refine_cut_reason_by_road[road_id].add(str(info["cut_reason"]))

        pruned_non_trunk_road_ids = pruned_road_id_set - trunk_road_id_set
        refined_out_non_trunk_road_ids = pruned_non_trunk_road_ids - body_candidate_non_trunk_road_ids
        segment_body_non_trunk_road_ids: set[str] = set()
        residual_road_ids: set[str] = set()
        transition_same_dir_blocked = False

        component_queue: deque[tuple[tuple[str, ...], tuple[str, ...], bool]] = deque(
            [
                (*component, True)
                for component in _collect_components(
                    set(body_candidate_non_trunk_road_ids),
                    road_endpoints=road_endpoints,
                )
            ]
            + [
                (*component, False)
                for component in _collect_components(
                    refined_out_non_trunk_road_ids,
                    road_endpoints=road_endpoints,
                )
            ]
        )
        component_index = 0
        while component_queue:
            component_road_ids, component_node_ids, component_is_body_candidate = component_queue.popleft()
            if not component_road_ids:
                continue

            component_index += 1
            component_id = f"{validation.pair_id}:C{component_index}"
            component_road_id_set = set(component_road_ids)
            terminate_node_ids = tuple(
                sorted((set(component_node_ids) & (boundary_node_ids - {pair.a_node_id, pair.b_node_id})), key=_sort_key)
            )
            hits_historical_boundary = bool(set(terminate_node_ids) & hard_stop_node_ids)
            conflicting_pair_ids = tuple(
                sorted(
                    {
                        validated_trunk_owner_by_road[road_id]
                        for road_id in component_road_ids
                        if road_id in validated_trunk_owner_by_road and validated_trunk_owner_by_road[road_id] != validation.pair_id
                    },
                    key=_sort_key,
                )
            )
            conflicting_road_ids = {
                road_id
                for road_id in component_road_ids
                if road_id in validated_trunk_owner_by_road and validated_trunk_owner_by_road[road_id] != validation.pair_id
            }
            support_barrier_node_ids = tuple(
                sorted(
                    (
                        node_id
                        for node_id in set(component_node_ids)
                        if any(
                            owner_pair_id != validation.pair_id
                            for owner_pair_id in validated_internal_support_owners_by_node.get(node_id, set())
                        )
                    ),
                    key=_sort_key,
                )
            )
            support_barrier_road_ids = {
                road_id
                for road_id in component_road_ids
                if set(road_endpoints.get(road_id, ())) & set(support_barrier_node_ids)
            }
            terminate_cut_road_ids = {
                road_id
                for road_id in component_road_ids
                if set(road_endpoints.get(road_id, ())) & set(terminate_node_ids)
            }
            blocker_road_ids = terminate_cut_road_ids | conflicting_road_ids | support_barrier_road_ids
            if blocker_road_ids:
                for road_id in sorted(blocker_road_ids, key=_sort_key):
                    road_node_ids = set(road_endpoints.get(road_id, ()))
                    touched_terminate_node_ids = tuple(
                        sorted(road_node_ids & set(terminate_node_ids), key=_sort_key)
                    )
                    touched_support_barrier_node_ids = tuple(
                        sorted(road_node_ids & set(support_barrier_node_ids), key=_sort_key)
                    )
                    if touched_terminate_node_ids:
                        cut_reason = (
                            "hits_historical_boundary"
                            if set(touched_terminate_node_ids) & hard_stop_node_ids
                            else "hits_other_terminate"
                        )
                    elif touched_support_barrier_node_ids:
                        cut_reason = "hits_other_validated_support_node"
                    else:
                        cut_reason = "contains_other_validated_trunk"
                    key = (road_id, cut_reason)
                    if key in branch_cut_seen:
                        continue
                    branch_cut_infos.append(
                        {
                            "road_id": road_id,
                            "cut_reason": cut_reason,
                            "component_id": component_id,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                            "support_barrier_node_ids": list(support_barrier_node_ids),
                        }
                    )
                    branch_cut_seen.add(key)

                remaining_component_road_ids = component_road_id_set - blocker_road_ids
                if remaining_component_road_ids:
                    component_queue.extendleft(
                        [
                            (*component, component_is_body_candidate)
                            for component in reversed(
                                _collect_components(remaining_component_road_ids, road_endpoints=road_endpoints)
                            )
                        ]
                    )
                continue

            transition_block_infos = _collect_transition_same_dir_block_infos(
                component_road_ids=component_road_ids,
                component_node_ids=component_node_ids,
                trunk_road_ids=validation.trunk_road_ids,
                road_endpoints=road_endpoints,
                direction_support_index=direction_support_index,
            )
            attachment_node_ids = tuple(sorted((set(component_node_ids) & trunk_node_id_set), key=_sort_key))
            internal_support_attachment_node_ids = tuple(
                sorted((set(attachment_node_ids) & internal_support_node_id_set), key=_sort_key)
            )
            internal_t_support_attachment_node_ids = tuple(
                sorted((set(attachment_node_ids) & internal_t_support_node_id_set), key=_sort_key)
            )
            component_directed_adjacency = _build_filtered_directed_adjacency(
                context.roads,
                road_endpoints=road_endpoints,
                allowed_road_ids=component_road_id_set,
                exclude_left_turn=False,
                left_turn_formway_bit=LEFT_TURN_FORMWAY_BIT,
            )
            component_direction_support_index = _build_direction_support_index_from_adjacency(
                component_directed_adjacency
            )
            component_directionality, bidirectional_road_ids = _classify_component_directionality(
                component_road_ids,
                roads=context.roads,
            )
            attachment_flow_status, attachment_direction_labels = _classify_attachment_flow_status(
                component_road_ids=component_road_ids,
                attachment_node_ids=attachment_node_ids,
                road_endpoints=road_endpoints,
                direction_support_index=component_direction_support_index,
            )
            parallel_corridor_directionality, parallel_corridor_directions = _classify_parallel_corridor_directionality(
                attachment_node_ids=attachment_node_ids,
                directed_adjacency=component_directed_adjacency,
            )
            hits_other_terminate = bool(terminate_node_ids)
            contains_other_validated_trunk = bool(conflicting_pair_ids)
            blocked_by_transition_same_dir = bool(transition_block_infos)
            component_geometry = _line_geometry_from_road_ids(component_road_ids, roads=context.roads)
            side_access_metric = "component_to_trunk_sampled"
            side_access_distance_m = _max_sampled_distance_m(component_geometry, trunk_geometry)
            if len(attachment_node_ids) < 2:
                side_access_gate_passed = False
                side_access_failure_reason = "side_access_attachment_insufficient"
            else:
                side_access_gate_passed = (
                    side_access_distance_m is None or side_access_distance_m <= MAX_SIDE_ACCESS_DISTANCE_M
                )
                side_access_failure_reason = "side_access_distance_exceeded"

            kept_as_segment_body = False
            moved_to_step3_residual = False
            moved_to_branch_cut = False
            decision_reason = "weak_rule_residual"

            if hits_historical_boundary:
                moved_to_branch_cut = True
                decision_reason = "hits_historical_boundary"
            elif hits_other_terminate:
                moved_to_branch_cut = True
                decision_reason = "hits_other_terminate"
            elif contains_other_validated_trunk:
                moved_to_branch_cut = True
                decision_reason = "contains_other_validated_trunk"
            elif (
                component_is_body_candidate
                and len(attachment_node_ids) >= 2
                and component_directionality != "one_way_only"
            ):
                moved_to_step3_residual = True
                decision_reason = "contains_bidirectional_side_road"
            elif component_is_body_candidate and parallel_corridor_directionality == "bidirectional_parallel":
                moved_to_step3_residual = True
                decision_reason = "bidirectional_parallel_corridor"
            elif component_is_body_candidate and attachment_flow_status != "single_departure_return":
                moved_to_step3_residual = True
                decision_reason = attachment_flow_status
            elif (
                component_is_body_candidate
                and parallel_corridor_directionality == "one_way_parallel"
                and attachment_node_ids
                and set(attachment_node_ids).issubset(internal_support_node_id_set)
            ):
                moved_to_step3_residual = True
                decision_reason = "internal_support_one_way_parallel"
            elif component_is_body_candidate and _is_same_endpoint_parallel_closure_component(
                pair=pair,
                validation=validation,
                component_directionality=component_directionality,
                attachment_flow_status=attachment_flow_status,
                attachment_node_ids=attachment_node_ids,
                parallel_corridor_directionality=parallel_corridor_directionality,
                roads=context.roads,
                road_endpoints=road_endpoints,
            ):
                moved_to_step3_residual = True
                decision_reason = "same_endpoint_parallel_closure"
            elif blocked_by_transition_same_dir:
                moved_to_step3_residual = True
                transition_same_dir_blocked = True
                decision_reason = "transition_same_dir_block"
            elif component_is_body_candidate and not side_access_gate_passed:
                moved_to_step3_residual = True
                decision_reason = side_access_failure_reason
            elif component_is_body_candidate:
                kept_as_segment_body = True
                decision_reason = "segment_body"
            else:
                moved_to_step3_residual = True
                component_hint_reasons = {
                    reason
                    for road_id in component_road_ids
                    for reason in refine_cut_reason_by_road.get(road_id, set())
                }
                if "segment_exclude_formway" in component_hint_reasons:
                    decision_reason = "step1_formway_excluded"
                else:
                    decision_reason = "weak_rule_residual"

            component = NonTrunkComponent(
                component_id=component_id,
                road_ids=component_road_ids,
                node_ids=component_node_ids,
                attachment_node_ids=attachment_node_ids,
                internal_support_attachment_node_ids=internal_support_attachment_node_ids,
                internal_t_support_attachment_node_ids=internal_t_support_attachment_node_ids,
                component_directionality=component_directionality,
                bidirectional_road_ids=bidirectional_road_ids,
                attachment_flow_status=attachment_flow_status,
                attachment_direction_labels=attachment_direction_labels,
                parallel_corridor_directionality=parallel_corridor_directionality,
                parallel_corridor_directions=parallel_corridor_directions,
                hits_other_terminate=hits_other_terminate,
                terminate_node_ids=terminate_node_ids,
                contains_other_validated_trunk=contains_other_validated_trunk,
                conflicting_pair_ids=conflicting_pair_ids,
                blocked_by_transition_same_dir=blocked_by_transition_same_dir,
                transition_block_infos=transition_block_infos,
                side_access_metric=side_access_metric,
                side_access_distance_m=side_access_distance_m,
                side_access_gate_passed=side_access_gate_passed,
                kept_as_segment_body=kept_as_segment_body,
                moved_to_step3_residual=moved_to_step3_residual,
                moved_to_branch_cut=moved_to_branch_cut,
                decision_reason=decision_reason,
            )
            component_infos.append(_component_to_dict(component))

            if kept_as_segment_body:
                segment_body_non_trunk_road_ids.update(component_road_ids)
            elif moved_to_step3_residual:
                residual_road_ids.update(component_road_ids)
                for road_id in component_road_ids:
                    residual_infos.append(
                        {
                            "road_id": road_id,
                            "component_id": component.component_id,
                            "residual_reason": decision_reason,
                            "blocked_by_transition_same_dir": blocked_by_transition_same_dir,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                            "side_access_distance_m": side_access_distance_m,
                            "side_access_gate_passed": side_access_gate_passed,
                            "hint_cut_reasons": sorted(refine_cut_reason_by_road.get(road_id, set()), key=_sort_key),
                        }
                    )
            elif moved_to_branch_cut:
                for road_id in component_road_ids:
                    key = (road_id, decision_reason)
                    if key in branch_cut_seen:
                        continue
                    branch_cut_infos.append(
                        {
                            "road_id": road_id,
                            "cut_reason": decision_reason,
                            "component_id": component.component_id,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                        }
                    )
                    branch_cut_seen.add(key)

        segment_body_road_ids = tuple(sorted(trunk_road_id_set | segment_body_non_trunk_road_ids, key=_sort_key))
        residual_road_ids_tuple = tuple(sorted(residual_road_ids, key=_sort_key))
        support_info["branch_cut_infos"] = branch_cut_infos
        support_info["non_trunk_components"] = component_infos
        support_info["step3_residual_infos"] = residual_infos
        support_info["segment_body_road_ids"] = list(segment_body_road_ids)
        support_info["residual_road_ids"] = list(residual_road_ids_tuple)

        tightened.append(
            replace(
                validation,
                segment_road_ids=segment_body_road_ids,
                residual_road_ids=residual_road_ids_tuple,
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                transition_same_dir_blocked=transition_same_dir_blocked,
                support_info=support_info,
            )
        )

    return tightened

def _write_step2_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    arbitration_outcome: Optional[PairArbitrationOutcome] = None,
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    endpoint_pool_source_map: dict[str, tuple[str, ...]],
    formway_mode: str,
    debug: bool,
    retain_validation_details: bool,
    progress_callback: Optional[Step2ProgressCallback] = None,
) -> Step2StrategyResult:
    segment_summary = _write_step2_outputs_bundle(
        out_dir,
        strategy=strategy,
        run_id=run_id,
        context=context,
        validations=validations,
        arbitration_outcome=arbitration_outcome,
        road_to_node_ids=road_to_node_ids,
        endpoint_pool_source_map=endpoint_pool_source_map,
        formway_mode=formway_mode,
        debug=debug,
        progress_callback=progress_callback,
    )

    return Step2StrategyResult(
        strategy=strategy,
        segment_summary=segment_summary,
        output_files=[str(path) for path in sorted(out_dir.iterdir()) if path.is_file()],
        validations=validations if retain_validation_details else [],
    )

def _validate_pair_candidates(
    execution: Step1StrategyExecution,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    formway_mode: str,
    left_turn_formway_bit: int,
    compact_release_payloads: bool = False,
    progress_callback: Optional[Step2ProgressCallback] = None,
    return_arbitration_outcome: bool = False,
    trace_validation_pair_ids: Optional[set[str]] = None,
    validation_batch_spill_dir: Optional[Path] = None,
) -> Union[list[PairValidationResult], tuple[list[PairValidationResult], PairArbitrationOutcome]]:
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    validation_count = len(execution.pair_candidates)
    road_lengths = _road_length_index(context)
    road_to_node_ids = _road_node_index(road_endpoints)
    arbitration_boundary_node_ids = _arbitration_boundary_node_ids(
        execution,
        hard_stop_node_ids=hard_stop_node_ids,
    )
    weak_endpoint_node_ids = _arbitration_weak_endpoint_node_ids(context)
    semantic_conflict_node_ids = _arbitration_semantic_conflict_node_ids(context)
    strong_anchor_node_ids = _arbitration_strong_anchor_node_ids(context)
    tjunction_anchor_node_ids = _arbitration_tjunction_anchor_node_ids(context)
    trace_pair_ids = set(trace_validation_pair_ids or ())

    _emit_progress(progress_callback, "validation_started", validation_count=validation_count)

    def _emit_validation_pair_phase(
        *,
        pair_index: int,
        pair: PairRecord,
        phase: str,
        checkpoint: bool = False,
        **extra_payload: Any,
    ) -> None:
        payload = {
            "pair_index": pair_index,
            "validation_count": validation_count,
            "pair_id": pair.pair_id,
            "a_node_id": pair.a_node_id,
            "b_node_id": pair.b_node_id,
            "phase": phase,
            **extra_payload,
        }
        perf_trace_enabled = (
            pair.pair_id in trace_pair_ids
            or pair_index <= VALIDATION_PHASE_TRACE_PAIR_LIMIT
        )
        _emit_progress(
            progress_callback,
            "validation_pair_state",
            **payload,
            _perf_log=perf_trace_enabled,
            _stdout_log=False,
        )
        if checkpoint:
            _emit_progress(progress_callback, "validation_pair_checkpoint", **payload)

    illegal_validations_by_pair_id: dict[str, PairValidationResult] = {}
    options_by_pair_id: dict[str, list[PairArbitrationOption]] = {}
    winner_restore_payloads_by_option_id: dict[str, dict[str, Any]] = {}
    batch_illegal_validations_by_pair_id: dict[str, PairValidationResult] = {}
    batch_options_by_pair_id: dict[str, list[PairArbitrationOption]] = {}
    batch_winner_restore_payloads_by_option_id: dict[str, dict[str, Any]] = {}
    spilled_batch_paths: list[Path] = []
    spill_validation_batches = (
        compact_release_payloads
        and validation_batch_spill_dir is not None
        and validation_count > 0
    )
    if spill_validation_batches:
        validation_batch_spill_dir.mkdir(parents=True, exist_ok=True)

    def _store_illegal_validation(validation: PairValidationResult) -> None:
        batch_illegal_validations_by_pair_id[validation.pair_id] = validation

    def _store_pair_options(pair_id: str, pair_options: list[PairArbitrationOption]) -> None:
        batch_options_by_pair_id[pair_id] = pair_options

    def _store_winner_restore_payload(option_id: str, restore_payload: dict[str, Any]) -> None:
        batch_winner_restore_payloads_by_option_id[option_id] = restore_payload

    def _flush_validation_batch() -> None:
        if (
            not batch_illegal_validations_by_pair_id
            and not batch_options_by_pair_id
            and not batch_winner_restore_payloads_by_option_id
        ):
            return
        if compact_release_payloads:
            compact_illegal_validations_by_pair_id = {
                pair_id: _compact_validation_result_for_release(
                    validation,
                    keep_tighten_fields=False,
                )
                for pair_id, validation in batch_illegal_validations_by_pair_id.items()
            }
            compact_options_by_pair_id = {
                pair_id: [
                    option
                    for option in pair_options
                ]
                for pair_id, pair_options in batch_options_by_pair_id.items()
            }
        else:
            compact_illegal_validations_by_pair_id = dict(batch_illegal_validations_by_pair_id)
            compact_options_by_pair_id = dict(batch_options_by_pair_id)
        if spill_validation_batches:
            batch_index = len(spilled_batch_paths) + 1
            batch_path = validation_batch_spill_dir / f"validation_batch_{batch_index:04d}.pkl"
            _write_pickle_doc(
                batch_path,
                {
                    "illegal_validations_by_pair_id": compact_illegal_validations_by_pair_id,
                    "options_by_pair_id": compact_options_by_pair_id,
                    "winner_restore_payloads_by_option_id": dict(batch_winner_restore_payloads_by_option_id),
                },
            )
            spilled_batch_paths.append(batch_path)
        else:
            illegal_validations_by_pair_id.update(compact_illegal_validations_by_pair_id)
            options_by_pair_id.update(compact_options_by_pair_id)
            winner_restore_payloads_by_option_id.update(batch_winner_restore_payloads_by_option_id)
        batch_illegal_validations_by_pair_id.clear()
        batch_options_by_pair_id.clear()
        batch_winner_restore_payloads_by_option_id.clear()
        if compact_release_payloads or spill_validation_batches:
            gc.collect()

    def _flush_validation_batch_if_needed(pair_index: int) -> None:
        if pair_index == validation_count or pair_index % VALIDATION_BATCH_SIZE == 0:
            _flush_validation_batch()

    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="validation_pair_started",
        )
        if (
            pair_index == 1
            or pair_index == validation_count
            or pair_index % VALIDATION_PROGRESS_CHECKPOINT_INTERVAL == 0
        ):
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="validation_pair_started",
                checkpoint=True,
            )

        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            boundary_node_ids=boundary_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="candidate_channel_built",
            candidate_road_count=len(candidate_road_ids),
        )

        if not candidate_road_ids:
            _store_illegal_validation(PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="invalid_candidate_boundary",
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=(),
                candidate_channel_road_ids=(),
                pruned_road_ids=(),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=(),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info={"boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key)},
            ))
            _flush_validation_batch_if_needed(pair_index)
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="prune_completed",
            candidate_road_count=len(candidate_road_ids),
            pruned_road_count=len(pruned_road_ids),
        )
        if disconnected_after_prune:
            _store_illegal_validation(PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="disconnected_after_prune",
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=(),
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info={
                    "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                    "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                },
            ))
            _flush_validation_batch_if_needed(pair_index)
            continue

        trunk_choices, reject_reason, warning_codes, trunk_gate_info = _evaluate_trunk_choices(
            pair,
            context=context,
            candidate_road_ids=candidate_road_ids,
            pruned_road_ids=pruned_road_ids,
            branch_cut_infos=branch_cut_infos,
            road_endpoints=road_endpoints,
            through_rule=execution.strategy.through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="trunk_evaluated",
            validated_status="validated" if trunk_choices else "rejected",
            reject_reason="" if reject_reason is None else reject_reason,
            trunk_found=bool(trunk_choices),
        )
        if not trunk_choices:
            _store_illegal_validation(PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason=reject_reason,
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=warning_codes,
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info={
                    "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                    "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    **trunk_gate_info,
                },
            ))
            _flush_validation_batch_if_needed(pair_index)
            continue

        pair_options: list[PairArbitrationOption] = []
        pair_fallback_validation: Optional[PairValidationResult] = None
        endpoint_priority_grades = _pair_endpoint_priority_grades(pair, context=context)

        for zero_based_option_index, choice in enumerate(trunk_choices):
            option_index = zero_based_option_index + 1
            trunk_candidate = choice.candidate
            option_id = f"{pair.pair_id}::opt_{option_index:02d}"
            alternative_trunk_only_road_ids = _alternative_trunk_only_road_ids(
                trunk_choices,
                current_choice_index=zero_based_option_index,
            )
            internal_boundary_node_ids = _collect_internal_boundary_nodes(
                pair,
                candidate=trunk_candidate,
                blocked_node_ids=hard_stop_node_ids,
            )
            if internal_boundary_node_ids:
                pair_fallback_validation = PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="historical_boundary_blocked",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        "historical_boundary_node_ids": list(internal_boundary_node_ids),
                    },
                )
                continue

            current_boundary_terminate_node_ids = _collect_internal_boundary_nodes(
                pair,
                candidate=trunk_candidate,
                blocked_node_ids=boundary_terminate_ids - hard_stop_node_ids,
            )
            if current_boundary_terminate_node_ids:
                pair_fallback_validation = PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="current_terminate_blocked",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        "current_terminate_node_ids": list(current_boundary_terminate_node_ids),
                    },
                )
                continue

            trunk_mode = _trunk_candidate_mode(trunk_candidate)
            if trunk_mode in {"through_collapsed_corridor", "mirrored_one_sided_corridor"}:
                segment_candidate_road_ids = trunk_candidate.road_ids
                segment_road_ids = trunk_candidate.road_ids
                segment_cut_infos: list[dict[str, Any]] = []
            else:
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_started",
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_body_allowed_road_ids = _expand_segment_body_allowed_road_ids(
                    pruned_road_ids=pruned_road_ids,
                    branch_cut_infos=branch_cut_infos,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                )
                if alternative_trunk_only_road_ids:
                    segment_body_allowed_road_ids -= alternative_trunk_only_road_ids
                segment_candidate_road_ids = _build_segment_body_candidate_channel(
                    pair,
                    trunk_road_ids=trunk_candidate.road_ids,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                    allowed_road_ids=segment_body_allowed_road_ids,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_candidate_channel_built",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_started",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_road_ids, segment_cut_infos = _refine_segment_roads(
                    pair,
                    context=context,
                    road_endpoints=road_endpoints,
                    pruned_road_ids=segment_candidate_road_ids,
                    trunk_road_ids=trunk_candidate.road_ids,
                    through_rule=execution.strategy.through_rule,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_completed",
                    candidate_road_count=len(segment_candidate_road_ids),
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_completed",
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )

            sorted_candidate_road_ids = tuple(sorted(candidate_road_ids, key=_sort_key))
            sorted_pruned_road_ids = tuple(sorted(pruned_road_ids, key=_sort_key))
            sorted_segment_candidate_road_ids = tuple(sorted(segment_candidate_road_ids, key=_sort_key))
            sorted_segment_road_ids = tuple(sorted(segment_road_ids, key=_sort_key))
            sorted_branch_cut_road_ids = tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key))
            sorted_boundary_terminate_node_ids = tuple(sorted(boundary_terminate_ids, key=_sort_key))

            if compact_release_payloads:
                runtime_support_info = _compact_option_support_info_for_runtime(
                    {
                        "branch_cut_infos": [
                            _compact_branch_cut_info(dict(info))
                            for info in branch_cut_infos
                        ],
                        "forward_path_road_ids": list(trunk_candidate.forward_path.road_ids),
                        "reverse_path_road_ids": list(trunk_candidate.reverse_path.road_ids),
                        "trunk_signed_area": trunk_candidate.signed_area,
                        "trunk_mode": trunk_mode,
                        "bidirectional_minimal_loop": trunk_candidate.is_bidirectional_minimal_loop,
                        "semantic_node_group_closure": trunk_candidate.is_semantic_node_group_closure,
                        "endpoint_priority_grades": list(endpoint_priority_grades),
                        **choice.support_info,
                        **trunk_gate_info,
                    },
                    candidate_channel_road_count=len(sorted_candidate_road_ids),
                    pruned_road_count=len(sorted_pruned_road_ids),
                    trunk_road_count=len(trunk_candidate.road_ids),
                    segment_body_candidate_road_count=len(sorted_segment_candidate_road_ids),
                    segment_body_road_count=len(sorted_segment_road_ids),
                    branch_cut_road_count=len(sorted_branch_cut_road_ids),
                    boundary_terminate_node_count=len(sorted_boundary_terminate_node_ids),
                )
                pair_options.append(
                    PairArbitrationOption(
                        option_id=option_id,
                        pair_id=pair.pair_id,
                        a_node_id=pair.a_node_id,
                        b_node_id=pair.b_node_id,
                        trunk_mode=trunk_mode,
                        counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                        warning_codes=choice.warning_codes,
                        candidate_channel_road_ids=(),
                        pruned_road_ids=sorted_pruned_road_ids,
                        trunk_road_ids=trunk_candidate.road_ids,
                        segment_candidate_road_ids=sorted_segment_candidate_road_ids,
                        segment_road_ids=sorted_segment_road_ids,
                        branch_cut_road_ids=(),
                        boundary_terminate_node_ids=(),
                        transition_same_dir_blocked=False,
                        support_info=runtime_support_info,
                    )
                )
                _store_winner_restore_payload(
                    option_id,
                    {
                        "support_info_extras": {
                            "boundary_terminate_node_ids": list(sorted_boundary_terminate_node_ids),
                            "candidate_channel_road_ids": list(sorted_candidate_road_ids),
                            "pruned_road_ids": list(sorted_pruned_road_ids),
                            "pair_support_road_ids": sorted(
                                set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids),
                                key=_sort_key,
                            ),
                            "alternative_trunk_only_road_ids": sorted(alternative_trunk_only_road_ids, key=_sort_key),
                            "segment_body_candidate_road_ids": list(sorted_segment_candidate_road_ids),
                            "segment_body_candidate_cut_infos": [
                                _compact_branch_cut_info(dict(info))
                                for info in segment_cut_infos
                            ],
                            "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                        },
                    },
                )
            else:
                support_info = {
                    "boundary_terminate_node_ids": list(sorted_boundary_terminate_node_ids),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": list(sorted_candidate_road_ids),
                    "pruned_road_ids": list(sorted_pruned_road_ids),
                    "pair_support_road_ids": sorted(
                        set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids),
                        key=_sort_key,
                    ),
                    "forward_path_road_ids": list(trunk_candidate.forward_path.road_ids),
                    "reverse_path_road_ids": list(trunk_candidate.reverse_path.road_ids),
                    "trunk_signed_area": trunk_candidate.signed_area,
                    "trunk_mode": trunk_mode,
                    "bidirectional_minimal_loop": trunk_candidate.is_bidirectional_minimal_loop,
                    "semantic_node_group_closure": trunk_candidate.is_semantic_node_group_closure,
                    "endpoint_priority_grades": list(endpoint_priority_grades),
                    **choice.support_info,
                    **trunk_gate_info,
                    "alternative_trunk_only_road_ids": sorted(alternative_trunk_only_road_ids, key=_sort_key),
                    "segment_body_candidate_road_ids": list(sorted_segment_candidate_road_ids),
                    "segment_body_candidate_cut_infos": segment_cut_infos,
                    "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                }
                pair_options.append(
                    PairArbitrationOption(
                        option_id=option_id,
                        pair_id=pair.pair_id,
                        a_node_id=pair.a_node_id,
                        b_node_id=pair.b_node_id,
                        trunk_mode=trunk_mode,
                        counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                        warning_codes=choice.warning_codes,
                        candidate_channel_road_ids=sorted_candidate_road_ids,
                        pruned_road_ids=sorted_pruned_road_ids,
                        trunk_road_ids=trunk_candidate.road_ids,
                        segment_candidate_road_ids=sorted_segment_candidate_road_ids,
                        segment_road_ids=sorted_segment_road_ids,
                        branch_cut_road_ids=sorted_branch_cut_road_ids,
                        boundary_terminate_node_ids=sorted_boundary_terminate_node_ids,
                        transition_same_dir_blocked=False,
                        support_info=support_info,
                    )
                )

        if pair_options:
            _store_pair_options(pair.pair_id, pair_options)
        else:
            if pair_fallback_validation is None:
                pair_fallback_validation = PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="no_valid_segment_body_option",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                )
            _store_illegal_validation(pair_fallback_validation)

        _flush_validation_batch_if_needed(pair_index)

    _flush_validation_batch()
    if spill_validation_batches:
        for batch_path in spilled_batch_paths:
            payload = _read_pickle_doc(batch_path)
            illegal_validations_by_pair_id.update(payload["illegal_validations_by_pair_id"])
            options_by_pair_id.update(payload["options_by_pair_id"])
            winner_restore_payloads_by_option_id.update(payload.get("winner_restore_payloads_by_option_id", {}))
        gc.collect()

    _emit_progress(
        progress_callback,
        "same_stage_arbitration_started",
        legal_pair_count=len(options_by_pair_id),
        illegal_pair_count=len(illegal_validations_by_pair_id),
    )
    arbitration_outcome = arbitrate_pair_options(
        options_by_pair=options_by_pair_id,
        single_pair_illegal_pair_ids=set(illegal_validations_by_pair_id),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=weak_endpoint_node_ids,
        boundary_node_ids=arbitration_boundary_node_ids,
        semantic_conflict_node_ids=semantic_conflict_node_ids,
        strong_anchor_node_ids=strong_anchor_node_ids,
        tjunction_anchor_node_ids=tjunction_anchor_node_ids,
    )
    _emit_progress(
        progress_callback,
        "same_stage_arbitration_completed",
        component_count=len(arbitration_outcome.components),
        winner_count=len(arbitration_outcome.selected_options_by_pair_id),
        loser_count=sum(1 for item in arbitration_outcome.decisions if item.arbitration_status == "lose"),
    )

    decision_by_pair_id = {decision.pair_id: decision for decision in arbitration_outcome.decisions}
    winning_pair_ids = {
        decision.pair_id
        for decision in arbitration_outcome.decisions
        if decision.arbitration_status == "win"
    }
    conflict_pair_ids_by_loser: dict[str, str] = {}
    for record in arbitration_outcome.conflict_records:
        left_wins = record.pair_id in winning_pair_ids
        right_wins = record.conflict_pair_id in winning_pair_ids
        if left_wins and not right_wins:
            conflict_pair_ids_by_loser.setdefault(record.conflict_pair_id, record.pair_id)
        elif right_wins and not left_wins:
            conflict_pair_ids_by_loser.setdefault(record.pair_id, record.conflict_pair_id)

    provisional_results: list[PairValidationResult] = []
    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        decision = decision_by_pair_id[pair.pair_id]
        if pair.pair_id in options_by_pair_id:
            pair_options = options_by_pair_id[pair.pair_id]
            selected_option_id = decision.selected_option_id or pair_options[0].option_id
            selected_option = next(
                option
                for option in pair_options
                if option.option_id == selected_option_id
            )
            if compact_release_payloads and decision.arbitration_status == "win":
                restore_payload = winner_restore_payloads_by_option_id.get(selected_option.option_id)
                if restore_payload is not None:
                    selected_option = _restore_validation_winner_option(
                        selected_option,
                        restore_payload=restore_payload,
                    )
            result = _pair_validation_from_option(
                selected_option,
                decision=decision,
                conflict_pair_id=conflict_pair_ids_by_loser.get(pair.pair_id),
                left_turn_excluded_mode=formway_mode,
                compact_release_payloads=compact_release_payloads,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
                segment_road_count=_validation_road_count(
                    result.segment_road_ids,
                    result.support_info,
                    "segment_body_road_count",
                ),
            )
        else:
            result = _single_pair_illegal_validation(
                illegal_validations_by_pair_id[pair.pair_id],
                decision=decision,
                compact_release_payloads=compact_release_payloads,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
            )
        provisional_results.append(result)
    options_by_pair_id.clear()
    illegal_validations_by_pair_id.clear()
    winner_restore_payloads_by_option_id.clear()
    provisional_validated_pair_count = sum(
        1 for item in provisional_results if item.validated_status == "validated"
    )
    _emit_progress(
        progress_callback,
        "validation_tighten_started",
        validation_count=validation_count,
        validated_pair_count=provisional_validated_pair_count,
    )
    if provisional_validated_pair_count:
        validated_results = [item for item in provisional_results if item.validated_status == "validated"]
        tightened_validated = _tighten_validated_segment_components(
            validated_results,
            execution=execution,
            context=context,
            road_endpoints=road_endpoints,
        )
        if compact_release_payloads:
            tightened_validated = [
                _compact_validation_result_for_release(item, keep_tighten_fields=False)
                for item in tightened_validated
            ]
        tightened_by_pair_id = {item.pair_id: item for item in tightened_validated}
    else:
        tightened_by_pair_id = {}

    tightened = [tightened_by_pair_id.get(item.pair_id, item) for item in provisional_results]
    _emit_progress(
        progress_callback,
        "validation_tighten_completed",
        validation_count=len(tightened),
        validated_pair_count=sum(1 for item in tightened if item.validated_status == "validated"),
    )
    if return_arbitration_outcome:
        return tightened, arbitration_outcome
    return tightened


def run_step2_segment_poc(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    strategy_config_paths: list[Union[str, Path]],
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    formway_mode: str = "strict",
    left_turn_formway_bit: int = LEFT_TURN_FORMWAY_BIT,
    debug: bool = True,
    retain_validation_details: bool = True,
    progress_callback: Optional[Step2ProgressCallback] = None,
    assume_working_layers: bool = False,
    trace_validation_pair_ids: Optional[Iterable[str]] = None,
    only_validation_pair_ids: Optional[Iterable[str]] = None,
    validation_pair_index_start: Optional[int] = None,
    validation_pair_index_end: Optional[int] = None,
) -> list[Step2StrategyResult]:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")
    if validation_pair_index_start is not None and validation_pair_index_start < 1:
        raise ValueError("validation_pair_index_start must be >= 1.")
    if validation_pair_index_end is not None and validation_pair_index_end < 1:
        raise ValueError("validation_pair_index_end must be >= 1.")
    if (
        validation_pair_index_start is not None
        and validation_pair_index_end is not None
        and validation_pair_index_start > validation_pair_index_end
    ):
        raise ValueError("validation_pair_index_start must be <= validation_pair_index_end.")

    resolved_out_root = Path(out_root)
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
            progress_callback=lambda event, payload: _emit_progress(progress_callback, event, **payload),
        )
        working_road_path = bootstrap_artifacts.roads_path
        working_node_path = bootstrap_artifacts.nodes_path
    _emit_progress(progress_callback, "context_build_started")
    context = build_step1_graph_context(
        road_path=working_road_path,
        node_path=working_node_path,
    )
    _emit_progress(
        progress_callback,
        "context_build_completed",
        road_count=len(context.roads),
        physical_node_count=len(context.physical_nodes),
        semantic_node_count=len(context.semantic_nodes),
        orphan_ref_count=context.orphan_ref_count,
    )
    road_endpoints, undirected_adjacency = _build_semantic_endpoints(context)
    _emit_progress(
        progress_callback,
        "semantic_endpoints_completed",
        semantic_endpoint_road_count=len(road_endpoints),
        undirected_node_count=len(undirected_adjacency),
    )

    results: list[Step2StrategyResult] = []
    comparison_summary: list[dict[str, Any]] = []
    resolved_run_id = resolved_out_root.name if run_id is None else run_id
    strategy_count = len(strategy_config_paths)
    trace_pair_ids = set(trace_validation_pair_ids or ())
    only_pair_ids = set(only_validation_pair_ids or ())
    pair_index_range_enabled = (
        validation_pair_index_start is not None or validation_pair_index_end is not None
    )

    for strategy_index, strategy_path in enumerate(strategy_config_paths, start=1):
        _emit_progress(
            progress_callback,
            "strategy_started",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_path=str(strategy_path),
        )
        strategy = _load_strategy(strategy_path)
        _emit_progress(
            progress_callback,
            "strategy_loaded",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
        )
        execution = run_step1_strategy(context, strategy)
        _emit_progress(
            progress_callback,
            "candidate_search_completed",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            candidate_pair_count=len(execution.pair_candidates),
            search_seed_count=len(execution.search_seed_ids),
            terminate_count=len(execution.terminate_ids),
        )
        strategy_out_dir = resolved_out_root / strategy.strategy_id

        write_step1_candidate_outputs(
            strategy_out_dir,
            strategy=strategy,
            run_id=resolved_run_id,
            semantic_nodes=context.semantic_nodes,
            physical_nodes=context.physical_nodes,
            physical_to_semantic=context.physical_to_semantic,
            roads=context.roads,
            seed_eval=execution.seed_eval,
            terminate_eval=execution.terminate_eval,
            pairs=execution.pair_candidates,
            search_event_counts=execution.search_event_counts,
            search_event_samples=execution.search_event_samples,
            graph_audit_events=context.graph_audit_events,
            orphan_ref_count=context.orphan_ref_count,
            search_seed_count=len(execution.search_seed_ids),
            through_seed_pruned_count=execution.through_seed_pruned_count,
            debug=debug,
        )
        _emit_progress(
            progress_callback,
            "candidate_outputs_written",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            output_dir=str(strategy_out_dir.resolve()),
        )

        execution = _compact_execution_for_validation(execution)
        if only_pair_ids or pair_index_range_enabled:
            filtered_pairs = [
                pair
                for pair_index, pair in enumerate(execution.pair_candidates, start=1)
                if (
                    not only_pair_ids or pair.pair_id in only_pair_ids
                )
                and (
                    validation_pair_index_start is None
                    or pair_index >= validation_pair_index_start
                )
                and (
                    validation_pair_index_end is None
                    or pair_index <= validation_pair_index_end
                )
            ]
            _emit_progress(
                progress_callback,
                "validation_pair_filter_applied",
                strategy_index=strategy_index,
                strategy_count=strategy_count,
                strategy_id=strategy.strategy_id,
                requested_pair_count=len(only_pair_ids),
                requested_pair_index_start=validation_pair_index_start,
                requested_pair_index_end=validation_pair_index_end,
                matched_pair_count=len(filtered_pairs),
            )
            execution = replace(execution, pair_candidates=filtered_pairs)
        gc.collect()
        compact_release_payloads = not debug and not retain_validation_details
        validation_result = _validate_pair_candidates(
            execution,
            context=context,
            road_endpoints=road_endpoints,
            undirected_adjacency=undirected_adjacency,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
            compact_release_payloads=compact_release_payloads,
            progress_callback=progress_callback,
            return_arbitration_outcome=True,
            trace_validation_pair_ids=trace_pair_ids,
            validation_batch_spill_dir=(
                strategy_out_dir / "_validation_batches"
                if compact_release_payloads
                else None
            ),
        )
        if isinstance(validation_result, tuple):
            validations, arbitration_outcome = validation_result
        else:
            validations = validation_result
            arbitration_outcome = _empty_pair_arbitration_outcome()
        endpoint_pool_source_map = build_endpoint_pool_source_map(
            node_ids=set(execution.seed_ids) | set(execution.terminate_ids),
            stage_id=strategy.strategy_id,
        )
        validated_pair_count = sum(1 for item in validations if item.validated_status == "validated")
        rejected_pair_count = len(validations) - validated_pair_count
        _emit_progress(
            progress_callback,
            "validation_completed",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            candidate_pair_count=len(validations),
            validated_pair_count=validated_pair_count,
            rejected_pair_count=rejected_pair_count,
        )
        write_outputs_kwargs = {
            "strategy": strategy,
            "run_id": resolved_run_id,
            "context": context,
            "validations": validations,
            "endpoint_pool_source_map": endpoint_pool_source_map,
            "formway_mode": formway_mode,
            "debug": debug,
            "retain_validation_details": retain_validation_details,
            "progress_callback": progress_callback,
        }
        if "road_to_node_ids" in inspect.signature(_write_step2_outputs).parameters:
            write_outputs_kwargs["road_to_node_ids"] = road_endpoints
        if "arbitration_outcome" in inspect.signature(_write_step2_outputs).parameters:
            write_outputs_kwargs["arbitration_outcome"] = arbitration_outcome
        step2_result = _write_step2_outputs(
            strategy_out_dir,
            **write_outputs_kwargs,
        )
        _emit_progress(
            progress_callback,
            "step2_outputs_written",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            output_dir=str(strategy_out_dir.resolve()),
            segment_summary=step2_result.segment_summary,
            retained_validation_details=retain_validation_details,
        )
        results.append(step2_result)
        comparison_summary.append(step2_result.segment_summary)
        del execution
        del validations
        del arbitration_outcome
        gc_collected = gc.collect()
        _emit_progress(
            progress_callback,
            "strategy_memory_released",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            gc_collected_objects=gc_collected,
            retained_validation_details=retain_validation_details,
        )

    write_json(resolved_out_root / "strategy_comparison.json", comparison_summary)
    _emit_progress(
        progress_callback,
        "comparison_summary_written",
        strategy_count=strategy_count,
        strategy_comparison_path=str((resolved_out_root / "strategy_comparison.json").resolve()),
    )
    return results


def run_step2_segment_poc_cli(args: argparse.Namespace) -> int:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=args.out_root, run_id=args.run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    progress_callback, progress_path, perf_markers_path = _make_step2_cli_progress_callback(
        run_id=resolved_run_id,
        out_root=resolved_out_root,
    )
    try:
        results = run_step2_segment_poc(
            road_path=args.road_path,
            road_layer=args.road_layer,
            road_crs=args.road_crs,
            node_path=args.node_path,
            node_layer=args.node_layer,
            node_crs=args.node_crs,
            strategy_config_paths=list(args.strategy_config),
            out_root=resolved_out_root,
            run_id=resolved_run_id,
            formway_mode=args.formway_mode,
            left_turn_formway_bit=args.left_turn_formway_bit,
            debug=args.debug,
            progress_callback=progress_callback,
            assume_working_layers=bool(getattr(args, "assume_working_layers", False)),
            trace_validation_pair_ids=list(getattr(args, "trace_validation_pair_ids", None) or []),
            only_validation_pair_ids=list(getattr(args, "only_validation_pair_ids", None) or []),
            validation_pair_index_start=getattr(args, "validation_pair_index_start", None),
            validation_pair_index_end=getattr(args, "validation_pair_index_end", None),
        )
    except Exception as exc:
        _write_step2_cli_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="failed",
            current_event=None,
            failed_event="step2_failed",
            message=str(exc),
        )
        _append_jsonl(
            perf_markers_path,
            {
                "event": "step2_run_failed",
                "at": _now_text(),
                "run_id": resolved_run_id,
                "error": str(exc),
            },
        )
        raise

    payload = {
        "run_id": resolved_run_id,
        "out_root": str(resolved_out_root.resolve()),
        "progress_path": str(progress_path.resolve()),
        "perf_markers_path": str(perf_markers_path.resolve()),
        "strategies": [
            {
                "strategy_id": result.strategy.strategy_id,
                "candidate_pair_count": result.segment_summary["candidate_pair_count"],
                "validated_pair_count": result.segment_summary["validated_pair_count"],
                "rejected_pair_count": result.segment_summary["rejected_pair_count"],
                "output_dir": str((resolved_out_root / result.strategy.strategy_id).resolve()),
            }
            for result in results
        ],
    }
    _write_step2_cli_progress_snapshot(
        out_path=progress_path,
        run_id=resolved_run_id,
        status="completed",
        current_event=None,
        message="Step2 CLI completed.",
    )
    _append_jsonl(
        perf_markers_path,
        {
            "event": "step2_run_completed",
            "at": _now_text(),
            "run_id": resolved_run_id,
            "strategy_count": len(results),
        },
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
