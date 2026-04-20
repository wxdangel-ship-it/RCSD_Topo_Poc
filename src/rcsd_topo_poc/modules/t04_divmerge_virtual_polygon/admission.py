from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_execution_contract import (
    evaluate_stage4_candidate_admission,
    resolve_stage4_output_kind,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    REASON_MAINNODEID_OUT_OF_SCOPE,
    _is_stage4_supported_node_kind,
    _node_source_kind,
    _node_source_kind_2,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode

from .case_models import T04AdmissionResult


def build_step1_admission(
    *,
    representative_node: ParsedNode,
    group_nodes: tuple[ParsedNode, ...],
) -> T04AdmissionResult:
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    admission = evaluate_stage4_candidate_admission(
        has_evd=representative_node.has_evd,
        is_anchor=representative_node.is_anchor,
        source_kind=source_kind,
        source_kind_2=source_kind_2,
        supported_kind=_is_stage4_supported_node_kind(representative_node),
        out_of_scope_reason=REASON_MAINNODEID_OUT_OF_SCOPE,
    )
    return T04AdmissionResult(
        mainnodeid=str(normalize_id(representative_node.mainnodeid or representative_node.node_id) or representative_node.node_id),
        representative_node_id=representative_node.node_id,
        group_node_ids=tuple(node.node_id for node in group_nodes),
        admitted=admission.admitted,
        reason=admission.reason,
        detail=admission.detail,
        source_kind=source_kind,
        source_kind_2=source_kind_2,
        output_kind=resolve_stage4_output_kind(source_kind=source_kind, source_kind_2=source_kind_2),
        grade_2=representative_node.grade_2,
    )

