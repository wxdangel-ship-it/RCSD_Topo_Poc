from __future__ import annotations

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    REASON_MAINNODEID_OUT_OF_SCOPE,
    _is_stage4_supported_node_kind,
    _node_source_kind,
    _node_source_kind_2,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode

from .case_models import T04AdmissionResult


def _resolve_t04_output_kind(*, source_kind: int | None, source_kind_2: int | None) -> int | None:
    return source_kind if source_kind is not None else source_kind_2


def build_step1_admission(
    *,
    representative_node: ParsedNode,
    group_nodes: tuple[ParsedNode, ...],
) -> T04AdmissionResult:
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    admitted = (
        representative_node.has_evd == "yes"
        and representative_node.is_anchor == "no"
        and _is_stage4_supported_node_kind(representative_node)
    )
    reject_detail = None
    if not admitted:
        reject_detail = (
            "T04 candidate admission rejected: "
            f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
            f"kind={source_kind}, kind_2={source_kind_2}."
        )
    return T04AdmissionResult(
        mainnodeid=str(normalize_id(representative_node.mainnodeid or representative_node.node_id) or representative_node.node_id),
        representative_node_id=representative_node.node_id,
        group_node_ids=tuple(node.node_id for node in group_nodes),
        admitted=admitted,
        reason=None if admitted else REASON_MAINNODEID_OUT_OF_SCOPE,
        detail=reject_detail,
        source_kind=source_kind,
        source_kind_2=source_kind_2,
        output_kind=_resolve_t04_output_kind(source_kind=source_kind, source_kind_2=source_kind_2),
        grade_2=representative_node.grade_2,
    )
