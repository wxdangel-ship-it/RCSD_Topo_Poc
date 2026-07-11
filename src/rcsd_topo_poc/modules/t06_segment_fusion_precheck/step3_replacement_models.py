from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplacementUnit:
    segment_id: str
    pair_nodes: list[str]
    junc_nodes: list[str]
    junc_kind2_exempt_nodes: list[str]
    original_junc_nodes: list[str]
    original_swsd_road_ids: list[str]
    swsd_road_ids: list[str]
    retained_detached_swsd_road_ids: list[str]
    detached_junc_nodes: list[str]
    rcsd_road_ids: list[str]
    retained_node_ids: list[str]
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    geometry: Any
    status: str = "passed"
    reason: str = "replaceable"
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)
    group_replacement_plan_ids: list[str] = field(default_factory=list)
    group_replacement_source_segment_ids: list[str] = field(default_factory=list)
    group_replacement_segment_ids: list[str] = field(default_factory=list)
    group_replacement_buffer_distances_m: list[float] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

@dataclass
class SpecialJunctionGroup:
    special_junction_id: str
    associated_segment_ids: list[str]
    rcsd_junction_node_ids: list[str]
    rcsd_junction_road_ids: list[str]

@dataclass
class JunctionState:
    c_id: str
    replacement_segment_ids: list[str] = field(default_factory=list)
    retained_segment_ids: list[str] = field(default_factory=list)
    mapped_rcsd_semantic_ids: list[str] = field(default_factory=list)
    original_member_node_ids: list[str] = field(default_factory=list)
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    remaining_swsd_node_ids: list[str] = field(default_factory=list)
    added_rcsd_node_ids: list[str] = field(default_factory=list)
    advance_attachment_rcsd_node_ids: list[str] = field(default_factory=list)
    original_main_props: dict[str, Any] = field(default_factory=dict)

__all__ = ["JunctionState", "ReplacementUnit", "SpecialJunctionGroup"]
