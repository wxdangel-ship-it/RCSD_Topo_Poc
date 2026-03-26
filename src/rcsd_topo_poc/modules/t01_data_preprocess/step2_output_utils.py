from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import write_endpoint_pool_outputs
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_json, write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    RoadRecord,
    SemanticNodeRecord,
    Step1GraphContext,
    StrategySpec,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import PairArbitrationOutcome
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _emit_progress(
    progress_callback: Optional[Callable[[str, dict[str, Any]], None]],
    event: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload)


def _line_feature(
    *,
    a_node: SemanticNodeRecord,
    b_node: SemanticNodeRecord,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "geometry": LineString([(a_node.geometry.x, a_node.geometry.y), (b_node.geometry.x, b_node.geometry.y)]),
        "properties": properties,
    }


def _road_feature(
    road: RoadRecord,
    *,
    pair_id: str,
    strategy_id: str,
    layer_role: str,
    extra_props: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    properties = {
        "road_id": road.road_id,
        "pair_id": pair_id,
        "strategy_id": strategy_id,
        "layer_role": layer_role,
        "direction": road.direction,
        "formway": road.formway,
    }
    if extra_props:
        properties.update(extra_props)
    return {"geometry": road.geometry, "properties": properties}


def _collect_multiline_parts(road_ids: tuple[str, ...], roads: dict[str, RoadRecord]) -> list[list[tuple[float, float]]]:
    parts: list[list[tuple[float, float]]] = []
    for road_id in road_ids:
        road = roads[road_id]
        geometry = road.geometry
        if geometry.geom_type == "LineString":
            parts.append([(float(x), float(y)) for x, y in geometry.coords])
            continue

        merged = linemerge(geometry)
        if merged.geom_type == "LineString":
            parts.append([(float(x), float(y)) for x, y in merged.coords])
            continue

        for part in merged.geoms:
            parts.append([(float(x), float(y)) for x, y in part.coords])
    return parts


def _pair_multiline_feature(
    *,
    context: Step1GraphContext,
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    strategy_id: str,
    layer_role: str,
    road_ids: tuple[str, ...],
    extra_props: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not road_ids:
        return None

    parts = _collect_multiline_parts(road_ids, context.roads)
    if not parts:
        return None

    properties = {
        "pair_id": pair_id,
        "a_node_id": a_node_id,
        "b_node_id": b_node_id,
        "strategy_id": strategy_id,
        "layer_role": layer_role,
        "road_count": len(road_ids),
        "road_ids": list(road_ids),
        "road_ids_text": ",".join(road_ids),
    }
    if extra_props:
        properties.update(extra_props)

    return {"geometry": MultiLineString(parts), "properties": properties}


def _iter_candidate_channel_features(
    *,
    context: Step1GraphContext,
    validations: Iterable[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        for road_id in validation.candidate_channel_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="candidate_channel",
            )


def _iter_working_graph_debug_features(
    *,
    context: Step1GraphContext,
    validations: Iterable[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        support_info = dict(validation.support_info)
        branch_cut_infos = list(support_info.get("branch_cut_infos", []))
        residual_infos = list(support_info.get("step3_residual_infos", []))

        for road_id in validation.candidate_channel_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "candidate_channel"},
            )

        for branch_cut_info in branch_cut_infos:
            branch_cut_props = {key: value for key, value in branch_cut_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[branch_cut_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "branch_cut", **branch_cut_props},
            )

        for road_id in validation.trunk_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "trunk"},
            )

        for road_id in validation.segment_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "segment_body"},
            )

        for residual_info in residual_infos:
            residual_props = {key: value for key, value in residual_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[residual_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "step3_residual", **residual_props},
            )


def _validation_road_count(
    road_ids: tuple[str, ...],
    support_info: dict[str, Any],
    count_key: str,
) -> int:
    value = support_info.get(count_key)
    if value is None:
        return len(road_ids)
    return int(value)


def _collect_validation_summary(validations: list[Any]) -> dict[str, Any]:
    validated_pair_count = 0
    rejected_pair_count = 0
    total_branch_cut_count = 0
    clockwise_reject_count = 0
    left_turn_trunk_reject_count = 0
    disconnected_after_prune_count = 0
    shared_trunk_conflict_count = 0
    dual_carriageway_separation_reject_count = 0
    formway_warning_count = 0
    branch_cut_component_keys: set[tuple[str, str]] = set()
    other_terminate_cut_keys: set[tuple[str, str]] = set()
    other_trunk_conflict_keys: set[tuple[str, str]] = set()
    transition_same_dir_block_keys: set[tuple[str, str]] = set()
    residual_component_keys: set[tuple[str, str]] = set()
    side_access_distance_block_keys: set[tuple[str, str]] = set()

    for validation in validations:
        if validation.validated_status == "validated":
            validated_pair_count += 1
        else:
            rejected_pair_count += 1

        if validation.reject_reason == "only_clockwise_loop":
            clockwise_reject_count += 1
        if validation.reject_reason == "left_turn_only_polluted_trunk":
            left_turn_trunk_reject_count += 1
        if validation.reject_reason == "disconnected_after_prune":
            disconnected_after_prune_count += 1
        if validation.reject_reason == "shared_trunk_conflict":
            shared_trunk_conflict_count += 1
        if validation.reject_reason == "dual_carriageway_separation_exceeded":
            dual_carriageway_separation_reject_count += 1
        if "formway_unreliable_warning" in validation.warning_codes:
            formway_warning_count += 1

        branch_cut_infos = validation.support_info.get("branch_cut_infos", ())
        total_branch_cut_count += len(branch_cut_infos)
        for branch_cut_info in branch_cut_infos:
            cut_key = (
                validation.pair_id,
                str(
                    branch_cut_info.get("component_id")
                    or f"{branch_cut_info.get('cut_reason')}::{branch_cut_info.get('road_id')}"
                ),
            )
            branch_cut_component_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") in {"hits_other_terminate", "branch_leads_to_other_terminate"}:
                other_terminate_cut_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") == "contains_other_validated_trunk":
                other_trunk_conflict_keys.add(cut_key)

        for component_info in validation.support_info.get("non_trunk_components", ()):
            component_key = (validation.pair_id, str(component_info.get("component_id", "")))
            if component_info.get("moved_to_step3_residual"):
                residual_component_keys.add(component_key)
            if component_info.get("decision_reason") == "side_access_distance_exceeded":
                side_access_distance_block_keys.add(component_key)
            if component_info.get("blocked_by_transition_same_dir"):
                transition_same_dir_block_keys.add(component_key)

    return {
        "candidate_pair_count": len(validations),
        "validated_pair_count": validated_pair_count,
        "rejected_pair_count": rejected_pair_count,
        "branch_cut_component_count": len(branch_cut_component_keys),
        "other_terminate_cut_count": len(other_terminate_cut_keys),
        "other_trunk_conflict_count": len(other_trunk_conflict_keys),
        "transition_same_dir_block_count": len(transition_same_dir_block_keys),
        "residual_component_count": len(residual_component_keys),
        "clockwise_reject_count": clockwise_reject_count,
        "left_turn_trunk_reject_count": left_turn_trunk_reject_count,
        "prune_branch_count": total_branch_cut_count,
        "disconnected_after_prune_count": disconnected_after_prune_count,
        "shared_trunk_conflict_count": shared_trunk_conflict_count,
        "dual_carriageway_separation_reject_count": dual_carriageway_separation_reject_count,
        "side_access_distance_block_count": len(side_access_distance_block_keys),
        "formway_warning_count": formway_warning_count,
    }


def _iter_validation_rows(validations: list[Any]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "candidate_status": validation.candidate_status,
            "validated_status": validation.validated_status,
            "reject_reason": validation.reject_reason or "",
            "trunk_mode": validation.trunk_mode,
            "trunk_found": validation.trunk_found,
            "counterclockwise_ok": validation.counterclockwise_ok,
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
            "transition_same_dir_blocked": validation.transition_same_dir_blocked,
            "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            "support_info": _compact_json(dict(validation.support_info)),
        }


def _iter_validated_rows(validations: list[Any]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "trunk_mode": validation.trunk_mode,
            "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            "warning_codes": ";".join(validation.warning_codes),
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
        }


def _iter_rejected_rows(validations: list[Any]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status == "validated":
            continue
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "reject_reason": validation.reject_reason or "",
            "warning_codes": ";".join(validation.warning_codes),
            "conflict_pair_id": validation.conflict_pair_id or "",
        }


def _iter_validated_link_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        yield _line_feature(
            a_node=context.semantic_nodes[validation.a_node_id],
            b_node=context.semantic_nodes[validation.b_node_id],
            properties={
                "pair_id": validation.pair_id,
                "a_node_id": validation.a_node_id,
                "b_node_id": validation.b_node_id,
                "strategy_id": strategy_id,
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
            },
        )


def _iter_trunk_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="trunk",
            road_ids=validation.trunk_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                "dual_carriageway_max_separation_m": validation.support_info.get(
                    "dual_carriageway_max_separation_m"
                ),
            },
        )
        if feature is not None:
            yield feature


def _iter_segment_body_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="segment_body",
            road_ids=validation.segment_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            },
        )
        if feature is not None:
            yield feature


def _iter_step3_residual_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="step3_residual",
            road_ids=validation.residual_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            },
        )
        if feature is not None:
            yield feature


def _iter_branch_cut_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        for branch_cut_info in validation.support_info.get("branch_cut_infos", ()):
            branch_cut_props = {key: value for key, value in branch_cut_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[branch_cut_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="branch_cut",
                extra_props=branch_cut_props,
            )


def _iter_member_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
    layer_role: str,
    road_ids_getter: Callable[[Any], Iterable[str]],
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        for road_id in road_ids_getter(validation):
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role=layer_role,
            )


def _iter_step3_residual_member_features(
    *,
    context: Step1GraphContext,
    validations: list[Any],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        for residual_info in validation.support_info.get("step3_residual_infos", ()):
            residual_props = {key: value for key, value in residual_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[residual_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="step3_residual_member",
                extra_props=residual_props,
            )


def _iter_validated_final_rows(validations: list[Any]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "single_pair_legal": validation.single_pair_legal,
            "arbitration_status": validation.arbitration_status,
            "validated_status": validation.validated_status,
            "lose_reason": validation.lose_reason,
            "trunk_mode": validation.trunk_mode,
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
        }


def _iter_pair_conflict_rows(arbitration_outcome: PairArbitrationOutcome) -> Iterable[dict[str, Any]]:
    for record in arbitration_outcome.conflict_records:
        for conflict_type in record.conflict_types:
            yield {
                "pair_id": record.pair_id,
                "conflict_pair_id": record.conflict_pair_id,
                "conflict_type": conflict_type,
                "shared_road_count": len(record.shared_road_ids),
                "shared_trunk_road_count": len(record.shared_trunk_road_ids),
            }


def _pair_conflict_components_payload(arbitration_outcome: PairArbitrationOutcome) -> list[dict[str, Any]]:
    return [
        {
            "component_id": component.component_id,
            "pair_ids": list(component.pair_ids),
            "component_size": len(component.pair_ids),
            "contested_road_ids": list(component.contested_road_ids),
            "strong_anchor_node_ids": list(component.strong_anchor_node_ids),
            "exact_solver_used": component.exact_solver_used,
            "fallback_greedy_used": component.fallback_greedy_used,
            "selected_option_ids": list(component.selected_option_ids),
        }
        for component in arbitration_outcome.components
    ]


def _iter_pair_arbitration_rows(
    validations: list[Any],
    arbitration_outcome: PairArbitrationOutcome,
) -> Iterable[dict[str, Any]]:
    validation_by_pair_id = {validation.pair_id: validation for validation in validations}
    for decision in arbitration_outcome.decisions:
        validation = validation_by_pair_id.get(decision.pair_id)
        if validation is None:
            continue
        yield {
            "pair_id": decision.pair_id,
            "component_id": decision.component_id,
            "single_pair_legal": decision.single_pair_legal,
            "arbitration_status": decision.arbitration_status,
            "endpoint_boundary_penalty": decision.endpoint_boundary_penalty,
            "strong_anchor_win_count": decision.strong_anchor_win_count,
            "corridor_naturalness_score": decision.corridor_naturalness_score,
            "contested_trunk_coverage_count": decision.contested_trunk_coverage_count,
            "contested_trunk_coverage_ratio": decision.contested_trunk_coverage_ratio,
            "pair_support_expansion_penalty": decision.pair_support_expansion_penalty,
            "internal_endpoint_penalty": decision.internal_endpoint_penalty,
            "body_connectivity_support": decision.body_connectivity_support,
            "semantic_conflict_penalty": decision.semantic_conflict_penalty,
            "lose_reason": decision.lose_reason,
        }


def _iter_corridor_conflict_features(
    *,
    context: Step1GraphContext,
    arbitration_outcome: PairArbitrationOutcome,
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    pair_ids_by_component_id = {
        component.component_id: component.pair_ids
        for component in arbitration_outcome.components
    }
    for component in arbitration_outcome.components:
        for road_id in component.contested_road_ids:
            road = context.roads.get(road_id)
            if road is None:
                continue
            yield _road_feature(
                road,
                pair_id="|".join(component.pair_ids),
                strategy_id=strategy_id,
                layer_role="corridor_conflict",
                extra_props={
                    "component_id": component.component_id,
                    "pair_ids": list(pair_ids_by_component_id[component.component_id]),
                    "road_id": road_id,
                },
            )


def _build_target_conflict_audit_xxxs7(
    *,
    validations: list[Any],
    arbitration_outcome: PairArbitrationOutcome,
    road_to_node_ids: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    target_pair_ids = ("S2:1019883__1026500", "S2:1026500__1026503")
    target_anchor_node_id = "500588029"
    validation_by_pair_id = {validation.pair_id: validation for validation in validations}
    decision_by_pair_id = {decision.pair_id: decision for decision in arbitration_outcome.decisions}
    pair_entries: dict[str, Any] = {}
    for pair_id in target_pair_ids:
        validation = validation_by_pair_id.get(pair_id)
        decision = decision_by_pair_id.get(pair_id)
        if validation is None or decision is None:
            pair_entries[pair_id] = {"present": False}
            continue
        arbitration_info = validation.support_info.get("arbitration", {})
        pair_entries[pair_id] = {
            "present": True,
            "single_pair_legal": validation.single_pair_legal,
            "arbitration_status": validation.arbitration_status,
            "validated_status": validation.validated_status,
            "lose_reason": validation.lose_reason,
            "component_id": validation.arbitration_component_id,
            "selected_option_id": validation.arbitration_option_id,
            "endpoint_boundary_penalty": arbitration_info.get("endpoint_boundary_penalty", 0),
            "strong_anchor_win_count": arbitration_info.get("strong_anchor_win_count", 0),
            "corridor_naturalness_score": arbitration_info.get("corridor_naturalness_score", 0),
            "contested_trunk_coverage_count": arbitration_info.get("contested_trunk_coverage_count", 0),
            "contested_trunk_coverage_ratio": arbitration_info.get("contested_trunk_coverage_ratio", 0.0),
            "pair_support_expansion_penalty": arbitration_info.get("pair_support_expansion_penalty", 0),
            "internal_endpoint_penalty": arbitration_info.get("internal_endpoint_penalty", 0),
            "body_connectivity_support": arbitration_info.get("body_connectivity_support", 0.0),
            "semantic_conflict_penalty": arbitration_info.get("semantic_conflict_penalty", 0),
        }

    anchor_owner_pair_ids: list[str] = []
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        candidate_road_ids = set(validation.support_info.get("segment_body_candidate_road_ids", ()))
        road_ids = (
            set(validation.trunk_road_ids)
            | set(validation.segment_road_ids)
            | set(validation.pruned_road_ids)
            | candidate_road_ids
        )
        node_ids: set[str] = set()
        for road_id in road_ids:
            endpoints = road_to_node_ids.get(road_id)
            if endpoints is None:
                continue
            node_ids.update(endpoints)
        if target_anchor_node_id in node_ids:
            anchor_owner_pair_ids.append(validation.pair_id)

    return {
        "target_pair_ids": list(target_pair_ids),
        "target_anchor_node_id": target_anchor_node_id,
        "pairs": pair_entries,
        "anchor_owner_pair_ids": anchor_owner_pair_ids,
        "target_anchor_winner_pair_ids": anchor_owner_pair_ids,
    }


def _write_step2_outputs_bundle(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    context: Step1GraphContext,
    validations: list[Any],
    arbitration_outcome: Optional[PairArbitrationOutcome] = None,
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    endpoint_pool_source_map: dict[str, tuple[str, ...]],
    formway_mode: str,
    debug: bool,
    progress_callback: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    if arbitration_outcome is None:
        arbitration_outcome = PairArbitrationOutcome(
            selected_options_by_pair_id={},
            decisions=[],
            conflict_records=[],
            components=[],
        )
    if road_to_node_ids is None:
        road_to_node_ids = {}
    validation_summary = _collect_validation_summary(validations)

    validated_pairs_path = out_dir / "validated_pairs.csv"
    rejected_pairs_path = out_dir / "rejected_pair_candidates.csv"
    pair_links_validated_path = out_dir / "pair_links_validated.gpkg"
    trunk_roads_path = out_dir / "trunk_roads.gpkg"
    segment_body_roads_path = out_dir / "segment_body_roads.gpkg"
    step3_residual_roads_path = out_dir / "step3_residual_roads.gpkg"
    segment_roads_path = out_dir / "segment_roads.gpkg"
    trunk_road_members_path = out_dir / "trunk_road_members.gpkg"
    segment_body_road_members_path = out_dir / "segment_body_road_members.gpkg"
    step3_residual_road_members_path = out_dir / "step3_residual_road_members.gpkg"
    segment_road_members_path = out_dir / "segment_road_members.gpkg"
    branch_cut_roads_path = out_dir / "branch_cut_roads.gpkg"
    candidate_channel_path = out_dir / "pair_candidate_channel.gpkg"
    validation_table_path = out_dir / "pair_validation_table.csv"
    validated_pairs_final_path = out_dir / "validated_pairs_final.csv"
    pair_conflict_table_path = out_dir / "pair_conflict_table.csv"
    pair_conflict_components_path = out_dir / "pair_conflict_components.json"
    pair_arbitration_table_path = out_dir / "pair_arbitration_table.csv"
    corridor_conflict_roads_path = out_dir / "corridor_conflict_roads.gpkg"
    target_conflict_audit_path = out_dir / "target_conflict_audit_xxxs7.json"
    working_graph_debug_path = out_dir / "working_graph_debug.gpkg"
    segment_summary_path = out_dir / "segment_summary.json"
    endpoint_pool_csv_path, endpoint_pool_summary_path, endpoint_pool_nodes_path = write_endpoint_pool_outputs(
        out_dir=out_dir,
        source_map=endpoint_pool_source_map,
        stage_id=strategy.strategy_id,
        semantic_nodes=context.semantic_nodes,
        debug=debug,
    )

    write_csv(
        validated_pairs_path,
        _iter_validated_rows(validations),
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "trunk_mode",
            "left_turn_excluded_mode",
            "warning_codes",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )
    write_csv(
        rejected_pairs_path,
        _iter_rejected_rows(validations),
        ["pair_id", "a_node_id", "b_node_id", "reject_reason", "warning_codes", "conflict_pair_id"],
    )
    write_csv(
        validated_pairs_final_path,
        _iter_validated_final_rows(validations),
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "single_pair_legal",
            "arbitration_status",
            "validated_status",
            "lose_reason",
            "trunk_mode",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )
    write_csv(
        pair_conflict_table_path,
        _iter_pair_conflict_rows(arbitration_outcome),
        ["pair_id", "conflict_pair_id", "conflict_type", "shared_road_count", "shared_trunk_road_count"],
    )
    write_json(pair_conflict_components_path, _pair_conflict_components_payload(arbitration_outcome))
    write_csv(
        pair_arbitration_table_path,
        _iter_pair_arbitration_rows(validations, arbitration_outcome),
        [
            "pair_id",
            "component_id",
            "single_pair_legal",
            "arbitration_status",
            "endpoint_boundary_penalty",
            "strong_anchor_win_count",
            "corridor_naturalness_score",
            "contested_trunk_coverage_count",
            "contested_trunk_coverage_ratio",
            "pair_support_expansion_penalty",
            "internal_endpoint_penalty",
            "body_connectivity_support",
            "semantic_conflict_penalty",
            "lose_reason",
        ],
    )
    write_vector(
        trunk_roads_path,
        _iter_trunk_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_vector(
        segment_body_roads_path,
        _iter_segment_body_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_vector(
        step3_residual_roads_path,
        _iter_step3_residual_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_vector(
        corridor_conflict_roads_path,
        _iter_corridor_conflict_features(
            context=context,
            arbitration_outcome=arbitration_outcome,
            strategy_id=strategy.strategy_id,
        ),
    )
    write_csv(
        validation_table_path,
        _iter_validation_rows(validations),
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "candidate_status",
            "validated_status",
            "reject_reason",
            "trunk_mode",
            "trunk_found",
            "counterclockwise_ok",
            "segment_body_road_count",
            "residual_road_count",
            "transition_same_dir_blocked",
            "left_turn_excluded_mode",
            "support_info",
        ],
    )
    write_json(
        target_conflict_audit_path,
        _build_target_conflict_audit_xxxs7(
            validations=validations,
            arbitration_outcome=arbitration_outcome,
            road_to_node_ids=road_to_node_ids,
        ),
    )

    segment_summary = {
        "strategy_id": strategy.strategy_id,
        "run_id": run_id,
        "strategy_out_dir": str(out_dir.resolve()),
        "formway_mode": formway_mode,
        **validation_summary,
        "conflict_component_count": len(arbitration_outcome.components),
        "arbitration_winner_count": sum(
            1 for item in arbitration_outcome.decisions if item.arbitration_status == "win"
        ),
        "arbitration_loser_count": sum(
            1 for item in arbitration_outcome.decisions if item.arbitration_status == "lose"
        ),
        "arbitration_fallback_component_count": sum(
            1 for item in arbitration_outcome.components if item.fallback_greedy_used
        ),
        "dual_carriageway_separation_gate_limit_m": MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        "side_access_distance_gate_limit_m": MAX_SIDE_ACCESS_DISTANCE_M,
        "debug": debug,
        "output_files": [
            endpoint_pool_csv_path.name,
            endpoint_pool_summary_path.name,
            validated_pairs_path.name,
            rejected_pairs_path.name,
            validated_pairs_final_path.name,
            pair_conflict_table_path.name,
            pair_conflict_components_path.name,
            pair_arbitration_table_path.name,
            trunk_roads_path.name,
            segment_body_roads_path.name,
            step3_residual_roads_path.name,
            corridor_conflict_roads_path.name,
            validation_table_path.name,
            target_conflict_audit_path.name,
            segment_summary_path.name,
        ],
    }
    if debug:
        write_vector(
            pair_links_validated_path,
            _iter_validated_link_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        write_vector(
            segment_roads_path,
            _iter_segment_body_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
        )
        write_vector(
            trunk_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="trunk_member",
                road_ids_getter=lambda validation: validation.trunk_road_ids,
            ),
        )
        write_vector(
            segment_body_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="segment_body_member",
                road_ids_getter=lambda validation: validation.segment_road_ids,
            ),
        )
        write_vector(
            step3_residual_road_members_path,
            _iter_step3_residual_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        write_vector(
            segment_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="segment_body_member",
                road_ids_getter=lambda validation: validation.segment_road_ids,
            ),
        )
        write_vector(
            branch_cut_roads_path,
            _iter_branch_cut_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "candidate_channel_write_started",
            output_file=candidate_channel_path.name,
            validation_count=len(validations),
        )
        write_vector(
            candidate_channel_path,
            _iter_candidate_channel_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "candidate_channel_write_completed",
            output_file=candidate_channel_path.name,
        )
        _emit_progress(
            progress_callback,
            "working_graph_debug_write_started",
            output_file=working_graph_debug_path.name,
            validation_count=len(validations),
        )
        write_vector(
            working_graph_debug_path,
            _iter_working_graph_debug_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "working_graph_debug_write_completed",
            output_file=working_graph_debug_path.name,
        )
        debug_output_files = [
            pair_links_validated_path.name,
            segment_roads_path.name,
            trunk_road_members_path.name,
            segment_body_road_members_path.name,
            step3_residual_road_members_path.name,
            segment_road_members_path.name,
            branch_cut_roads_path.name,
            candidate_channel_path.name,
            working_graph_debug_path.name,
        ]
        if endpoint_pool_nodes_path is not None:
            debug_output_files.append(endpoint_pool_nodes_path.name)
        segment_summary["output_files"].extend(debug_output_files)
    write_json(segment_summary_path, segment_summary)
    return segment_summary
