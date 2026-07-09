from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor, BufferSegmentResult
from .parsing import unique_preserve_order
from .relation_mapping import RelationCheck


SINGLE_RCSD_BIDIRECTIONAL_CONFLICT = "swsd_single_rcsd_bidirectional_reality_conflict"
SINGLE_RCSD_BIDIRECTIONAL_ACTION = "replace_full_bidirectional_rcsd"


@dataclass(frozen=True)
class SingleDirectionRealityContext:
    buffer_extractor: BufferSegmentExtractor
    segment_geometry: Any
    all_relation_base_ids: set[str]
    unexpected_relation_base_ids: set[str]
    config: BufferExtractionConfig


def resolve_single_rcsd_bidirectional_reality(
    context: SingleDirectionRealityContext,
    directionality: str,
    relation: RelationCheck,
    optional_allowed_rcsd_nodes: list[str],
    directed_pair_nodes: list[str],
    base_result: BufferSegmentResult,
) -> tuple[BufferSegmentResult, dict[str, Any]]:
    if directionality != "single" or not base_result.ok:
        return base_result, {}

    bidirectional_result = context.buffer_extractor.extract(
        segment_geometry=context.segment_geometry,
        relation=relation,
        optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
        all_relation_base_ids=context.all_relation_base_ids,
        unexpected_relation_base_ids=context.unexpected_relation_base_ids,
        directed_pair_nodes=[],
        require_directed_pair=False,
        require_bidirectional=True,
        config=context.config,
    )
    if not bidirectional_result.ok:
        return base_result, {}

    forward_road_ids = unique_preserve_order(base_result.retained_road_ids)
    bidirectional_road_ids = unique_preserve_order(bidirectional_result.retained_road_ids)
    forward_road_id_set = set(forward_road_ids)
    reverse_or_extra_road_ids = [road_id for road_id in bidirectional_road_ids if road_id not in forward_road_id_set]
    resolved_result = replace(
        bidirectional_result,
        directed_rcsd_pair_nodes=base_result.directed_rcsd_pair_nodes,
    )
    return resolved_result, {
        "directionality_conflict_status": SINGLE_RCSD_BIDIRECTIONAL_CONFLICT,
        "directionality_conflict_action": SINGLE_RCSD_BIDIRECTIONAL_ACTION,
        "directionality_conflict_reason": (
            "single SWSD Segment has bidirectional RCSD closure inside anchored buffer; "
            "replace full RCSD closure and emit SWSD currentness audit"
        ),
        "forward_rcsd_road_ids": forward_road_ids,
        "bidirectional_rcsd_road_ids": bidirectional_road_ids,
        "reverse_or_extra_rcsd_road_ids": reverse_or_extra_road_ids,
    }
