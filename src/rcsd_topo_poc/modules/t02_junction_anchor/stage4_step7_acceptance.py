from __future__ import annotations

from typing import Any

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import Stage4EventInterpretationResult
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_step6_contract import Stage4PolygonAssemblyResult
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step7_contract import (
    Stage4Step7AcceptanceResult,
    Stage4Step7DecisionInputs,
    build_stage4_step7_acceptance_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode

def _build_stage4_step7_acceptance(
    *,
    representative_node: ParsedNode,
    representative_fields,
    step4_event_interpretation: Stage4EventInterpretationResult,
    step6_polygon_assembly: Stage4PolygonAssemblyResult,
    primary_main_rc_node: ParsedNode | None,
    direct_target_rc_nodes: list[ParsedNode],
    effective_target_rc_nodes: list[ParsedNode],
    coverage_missing_ids: list[str],
    primary_rcsdnode_tolerance: dict[str, Any],
    base_review_reasons: list[str],
    base_hard_rejection_reasons: list[str],
    flow_success: bool,
) -> Stage4Step7AcceptanceResult:
    return build_stage4_step7_acceptance_result(
        Stage4Step7DecisionInputs(
            representative_node_id=representative_node.node_id,
            representative_mainnodeid=representative_node.mainnodeid,
            representative_fields=representative_fields,
            step4_event_interpretation=step4_event_interpretation,
            step6_polygon_assembly=step6_polygon_assembly,
            primary_main_rc_node_present=primary_main_rc_node is not None,
            direct_target_rc_node_ids=tuple(node.node_id for node in direct_target_rc_nodes),
            effective_target_rc_node_ids=tuple(node.node_id for node in effective_target_rc_nodes),
            coverage_missing_ids=tuple(coverage_missing_ids),
            primary_rcsdnode_tolerance=dict(primary_rcsdnode_tolerance),
            base_review_reasons=tuple(base_review_reasons),
            base_hard_rejection_reasons=tuple(base_hard_rejection_reasons),
            flow_success=flow_success,
        )
    )

