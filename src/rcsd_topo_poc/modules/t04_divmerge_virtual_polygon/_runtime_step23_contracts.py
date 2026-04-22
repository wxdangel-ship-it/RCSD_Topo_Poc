from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad


@dataclass(frozen=True)
class Stage4RecallWindow:
    drivezone_hard_boundary: bool = True
    diverge_trunk_backward_max_m: float = 50.0
    diverge_branch_forward_max_m: float = 200.0
    merge_trunk_forward_max_m: float = 50.0
    merge_branch_backward_max_m: float = 200.0
    semantic_boundary_clamp_enabled: bool = True
    window_mode: str = "high_recall_local_context"
    scene_filter_mode: str = "drivezone_bounded_spatial_query"
    patch_membership_mode: str = "scene_supplement_only"


@dataclass(frozen=True)
class Stage4NegativeExclusionContext:
    source_priority: tuple[str, ...]
    rcsd_nodes: tuple[ParsedNode, ...]
    rcsd_roads: tuple[ParsedRoad, ...]
    swsd_nodes: tuple[ParsedNode, ...]
    swsd_roads: tuple[ParsedRoad, ...]
    road_geometry_only_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "source_priority": list(self.source_priority),
            "rcsd_node_count": len(self.rcsd_nodes),
            "rcsd_road_count": len(self.rcsd_roads),
            "swsd_node_count": len(self.swsd_nodes),
            "swsd_road_count": len(self.swsd_roads),
            "road_geometry_only_count": len(self.road_geometry_only_ids),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Stage4LocalContext:
    current_patch_id: str | None
    representative_node_id: str
    group_node_ids: tuple[str, ...]
    direct_target_rc_nodes: tuple[ParsedNode, ...]
    exact_target_rc_nodes: tuple[ParsedNode, ...]
    primary_main_rc_node: ParsedNode | None
    rcsdnode_seed_mode: str
    patch_size_m: float
    seed_center: Any
    grid: Any
    drivezone_union: Any
    drivezone_mask: Any
    scene_drivezone_feature_count: int
    scene_road_count: int
    local_nodes: tuple[ParsedNode, ...]
    local_roads: tuple[ParsedRoad, ...]
    local_rcsd_nodes: tuple[ParsedNode, ...]
    local_rcsd_roads: tuple[ParsedRoad, ...]
    local_divstrip_features: tuple[LoadedFeature, ...]
    queried_divstrip_feature_count: int
    local_divstrip_union: Any
    patch_drivezone_union: Any
    patch_drivezone_mask: Any
    patch_roads: tuple[ParsedRoad, ...]
    patch_divstrip_features: tuple[LoadedFeature, ...]
    patch_divstrip_union: Any
    recall_window: Stage4RecallWindow
    negative_exclusion_context: Stage4NegativeExclusionContext

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "current_patch_id": self.current_patch_id,
            "representative_node_id": self.representative_node_id,
            "group_node_ids": list(self.group_node_ids),
            "direct_target_rc_node_ids": [node.node_id for node in self.direct_target_rc_nodes],
            "exact_target_rc_node_ids": [node.node_id for node in self.exact_target_rc_nodes],
            "primary_main_rc_node_id": None if self.primary_main_rc_node is None else self.primary_main_rc_node.node_id,
            "rcsdnode_seed_mode": self.rcsdnode_seed_mode,
            "patch_size_m": self.patch_size_m,
            "drivezone_hard_boundary": self.recall_window.drivezone_hard_boundary,
            "scene_drivezone_feature_count": self.scene_drivezone_feature_count,
            "scene_road_count": self.scene_road_count,
            "local_node_count": len(self.local_nodes),
            "local_road_count": len(self.local_roads),
            "local_rcsdnode_count": len(self.local_rcsd_nodes),
            "local_rcsdroad_count": len(self.local_rcsd_roads),
            "queried_divstrip_feature_count": self.queried_divstrip_feature_count,
            "local_divstrip_feature_count": len(self.local_divstrip_features),
            "patch_road_count": len(self.patch_roads),
            "patch_divstrip_feature_count": len(self.patch_divstrip_features),
            "recall_window": {
                "window_mode": self.recall_window.window_mode,
                "scene_filter_mode": self.recall_window.scene_filter_mode,
                "patch_membership_mode": self.recall_window.patch_membership_mode,
                "diverge_trunk_backward_max_m": self.recall_window.diverge_trunk_backward_max_m,
                "diverge_branch_forward_max_m": self.recall_window.diverge_branch_forward_max_m,
                "merge_trunk_forward_max_m": self.recall_window.merge_trunk_forward_max_m,
                "merge_branch_backward_max_m": self.recall_window.merge_branch_backward_max_m,
                "semantic_boundary_clamp_enabled": self.recall_window.semantic_boundary_clamp_enabled,
            },
            "negative_exclusion_context": self.negative_exclusion_context.to_audit_summary(),
        }


@dataclass(frozen=True)
class Stage4BranchResult:
    member_node_ids: tuple[str, ...]
    augmented_member_node_ids: tuple[str, ...]
    road_branches: tuple[Any, ...]
    road_branch_ids: tuple[str, ...]
    road_to_branch: Mapping[str, Any]
    road_branches_by_id: Mapping[str, Any]
    main_branch_ids: tuple[str, ...]
    through_node_policy: str
    through_node_candidate_ids: tuple[str, ...]

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "member_node_ids": list(self.member_node_ids),
            "augmented_member_node_ids": list(self.augmented_member_node_ids),
            "branch_count": len(self.road_branches),
            "road_branch_ids": list(self.road_branch_ids),
            "main_branch_ids": list(self.main_branch_ids),
            "through_node_policy": self.through_node_policy,
            "through_node_candidate_ids": list(self.through_node_candidate_ids),
        }


@dataclass(frozen=True)
class Stage4ChainContext:
    chain_component_id: str | None
    related_mainnodeids: tuple[str, ...]
    related_seed_nodes: tuple[ParsedNode, ...]
    is_in_continuous_chain: bool
    chain_node_count: int
    chain_node_offset_m: float | None
    sequential_ok: bool
    chain_bidirectional: bool
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> dict[str, Any]:
        if self.raw:
            return dict(self.raw)
        return {
            "chain_component_id": self.chain_component_id,
            "related_mainnodeids": list(self.related_mainnodeids),
            "related_seed_nodes": list(self.related_seed_nodes),
            "is_in_continuous_chain": self.is_in_continuous_chain,
            "chain_node_count": self.chain_node_count,
            "chain_node_offset_m": self.chain_node_offset_m,
            "sequential_ok": self.sequential_ok,
            "chain_bidirectional": self.chain_bidirectional,
        }

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "chain_component_id": self.chain_component_id,
            "related_mainnodeids": list(self.related_mainnodeids),
            "related_seed_node_ids": [node.node_id for node in self.related_seed_nodes],
            "is_in_continuous_chain": self.is_in_continuous_chain,
            "chain_node_count": self.chain_node_count,
            "chain_node_offset_m": self.chain_node_offset_m,
            "sequential_ok": self.sequential_ok,
            "chain_bidirectional": self.chain_bidirectional,
        }


@dataclass(frozen=True)
class Stage4SkeletonStability:
    has_minimum_branches: bool
    main_pair_resolved: bool
    branch_count: int
    chain_augmented: bool
    unstable_reasons: tuple[str, ...]
    legacy_step4_adapter_required: bool = True

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "has_minimum_branches": self.has_minimum_branches,
            "main_pair_resolved": self.main_pair_resolved,
            "branch_count": self.branch_count,
            "chain_augmented": self.chain_augmented,
            "unstable_reasons": list(self.unstable_reasons),
            "legacy_step4_adapter_required": self.legacy_step4_adapter_required,
        }


@dataclass(frozen=True)
class Stage4TopologySkeleton:
    branch_result: Stage4BranchResult
    chain_context: Stage4ChainContext
    stability: Stage4SkeletonStability

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "branch_result": self.branch_result.to_audit_summary(),
            "chain_context": self.chain_context.to_audit_summary(),
            "stability": self.stability.to_audit_summary(),
        }


@dataclass(frozen=True)
class Stage4LegacyStep4Bridge:
    local_context: Stage4LocalContext
    topology_skeleton: Stage4TopologySkeleton


@dataclass(frozen=True)
class Stage4LegacyStep4Readiness:
    ready: bool
    reasons: tuple[str, ...]


def wrap_stage4_chain_context(raw: Mapping[str, Any]) -> Stage4ChainContext:
    related_seed_nodes = tuple(raw.get("related_seed_nodes", ()))
    return Stage4ChainContext(
        chain_component_id=raw.get("chain_component_id"),
        related_mainnodeids=tuple(str(item) for item in raw.get("related_mainnodeids", ()) if item is not None),
        related_seed_nodes=related_seed_nodes,
        is_in_continuous_chain=bool(raw.get("is_in_continuous_chain", False)),
        chain_node_count=int(raw.get("chain_node_count", 0) or 0),
        chain_node_offset_m=raw.get("chain_node_offset_m"),
        sequential_ok=bool(raw.get("sequential_ok", False)),
        chain_bidirectional=bool(raw.get("chain_bidirectional", False)),
        raw=dict(raw),
    )


def evaluate_stage4_legacy_step4_readiness(
    topology_skeleton: Stage4TopologySkeleton,
) -> Stage4LegacyStep4Readiness:
    reasons: list[str] = []
    if not topology_skeleton.stability.has_minimum_branches:
        reasons.append("insufficient_branch_count")
    if not topology_skeleton.stability.main_pair_resolved:
        reasons.append("main_pair_unresolved")
    return Stage4LegacyStep4Readiness(
        ready=not reasons,
        reasons=tuple(reasons),
    )
