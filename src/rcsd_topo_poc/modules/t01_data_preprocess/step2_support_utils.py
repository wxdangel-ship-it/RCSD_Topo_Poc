from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    SemanticNodeRecord,
    Step1GraphContext,
    StrategySpec,
    TraversalEdge,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import PairArbitrationOutcome
from rcsd_topo_poc.modules.t01_data_preprocess.step2_output_utils import _write_step2_outputs_bundle
from rcsd_topo_poc.modules.t01_data_preprocess.step2_runtime_utils import Step2ProgressCallback
from rcsd_topo_poc.modules.t01_data_preprocess.step2_validation_utils import PairValidationResult, Step2StrategyResult
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import is_allowed_road_kind


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


def _build_semantic_endpoints(
    context: Step1GraphContext,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[TraversalEdge, ...]]]:
    road_endpoints: dict[str, tuple[str, str]] = {}
    undirected_lists: dict[str, list[TraversalEdge]] = {}

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
        undirected_lists.setdefault(semantic_snode_id, []).append(
            TraversalEdge(road.road_id, semantic_snode_id, semantic_enode_id)
        )
        undirected_lists.setdefault(semantic_enode_id, []).append(
            TraversalEdge(road.road_id, semantic_enode_id, semantic_snode_id)
        )

    return road_endpoints, {node_id: tuple(edges) for node_id, edges in undirected_lists.items()}


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
