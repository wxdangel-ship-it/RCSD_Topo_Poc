from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad


def _tuple_str(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        items.append(str(value))
    return tuple(items)


def _tuple_mapping(values: Sequence[Mapping[str, Any]] | None) -> tuple[dict[str, Any], ...]:
    if not values:
        return ()
    return tuple(dict(value) for value in values)


@dataclass(frozen=True)
class Stage4DivStripContext:
    present: bool
    nearby: bool
    component_count: int
    selected_component_ids: tuple[str, ...]
    selection_mode: str
    evidence_source: str
    preferred_branch_ids: tuple[str, ...]
    ambiguous: bool
    constraint_geometry: Any
    event_anchor_geometry: Any
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "divstrip_present": self.present,
            "divstrip_nearby": self.nearby,
            "divstrip_component_count": self.component_count,
            "divstrip_component_selected": list(self.selected_component_ids),
            "selection_mode": self.selection_mode,
            "evidence_source": self.evidence_source,
            "preferred_branch_ids": list(self.preferred_branch_ids),
            "divstrip_component_ambiguous": self.ambiguous,
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "present": self.present,
                "nearby": self.nearby,
                "component_count": self.component_count,
                "selected_component_ids": list(self.selected_component_ids),
                "selection_mode": self.selection_mode,
                "evidence_source": self.evidence_source,
                "preferred_branch_ids": list(self.preferred_branch_ids),
                "ambiguous": self.ambiguous,
                "constraint_geometry": self.constraint_geometry,
                "event_anchor_geometry": self.event_anchor_geometry,
            }
        )
        return payload


@dataclass(frozen=True)
class Stage4ContinuousChainDecision:
    chain_component_id: str | None
    related_mainnodeids: tuple[str, ...]
    is_in_continuous_chain: bool
    chain_node_count: int
    chain_node_offset_m: float | None
    sequential_ok: bool
    chain_bidirectional: bool
    applied_to_event_interpretation: bool
    influence_mode: str
    risk_signals: tuple[str, ...] = ()

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "chain_component_id": self.chain_component_id,
            "related_mainnodeids": list(self.related_mainnodeids),
            "is_in_continuous_chain": self.is_in_continuous_chain,
            "chain_node_count": self.chain_node_count,
            "chain_node_offset_m": self.chain_node_offset_m,
            "sequential_ok": self.sequential_ok,
            "chain_bidirectional": self.chain_bidirectional,
            "applied_to_event_interpretation": self.applied_to_event_interpretation,
            "influence_mode": self.influence_mode,
            "risk_signals": list(self.risk_signals),
        }


@dataclass(frozen=True)
class Stage4MultibranchDecision:
    enabled: bool
    n: int
    main_pair_item_ids: tuple[str, ...]
    event_candidate_count: int
    event_candidates: tuple[dict[str, Any], ...]
    selected_event_index: int | None
    selected_event_branch_ids: tuple[str, ...]
    selected_event_source_branch_ids: tuple[str, ...]
    selected_side_branches: tuple[Any, ...]
    branches_used_count: int
    ambiguous: bool
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "multibranch_enabled": self.enabled,
            "multibranch_n": self.n,
            "main_pair_item_ids": list(self.main_pair_item_ids),
            "event_candidate_count": self.event_candidate_count,
            "event_candidates": [dict(candidate) for candidate in self.event_candidates],
            "selected_event_index": self.selected_event_index,
            "selected_event_branch_ids": list(self.selected_event_branch_ids),
            "selected_event_source_branch_ids": list(self.selected_event_source_branch_ids),
            "branches_used_count": self.branches_used_count,
            "multibranch_event_ambiguous": self.ambiguous,
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "enabled": self.enabled,
                "n": self.n,
                "main_pair_item_ids": list(self.main_pair_item_ids),
                "event_candidate_count": self.event_candidate_count,
                "event_candidates": [dict(candidate) for candidate in self.event_candidates],
                "selected_event_index": self.selected_event_index,
                "selected_event_branch_ids": list(self.selected_event_branch_ids),
                "selected_event_source_branch_ids": list(self.selected_event_source_branch_ids),
                "selected_side_branches": list(self.selected_side_branches),
                "branches_used_count": self.branches_used_count,
                "ambiguous": self.ambiguous,
            }
        )
        return payload


@dataclass(frozen=True)
class Stage4KindResolution:
    source_kind: int | None
    source_kind_2: int | None
    operational_kind_2: int | None
    complex_junction: bool
    ambiguous: bool
    kind_resolution_mode: str
    merge_score: float | None
    diverge_score: float | None
    merge_hits: int | None
    diverge_hits: int | None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_kind_2": self.source_kind_2,
            "operational_kind_2": self.operational_kind_2,
            "complex_junction": self.complex_junction,
            "kind_resolution_ambiguous": self.ambiguous,
            "kind_resolution_mode": self.kind_resolution_mode,
            "merge_score": self.merge_score,
            "diverge_score": self.diverge_score,
            "merge_hits": self.merge_hits,
            "diverge_hits": self.diverge_hits,
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "source_kind": self.source_kind,
                "source_kind_2": self.source_kind_2,
                "operational_kind_2": self.operational_kind_2,
                "complex_junction": self.complex_junction,
                "ambiguous": self.ambiguous,
                "kind_resolution_mode": self.kind_resolution_mode,
                "merge_score": self.merge_score,
                "diverge_score": self.diverge_score,
                "merge_hits": self.merge_hits,
                "diverge_hits": self.diverge_hits,
            }
        )
        return payload


@dataclass(frozen=True)
class Stage4ReverseTipDecision:
    attempted: bool
    used: bool
    trigger: str | None
    position_source_forward: str | None
    position_source_reverse: str | None
    position_source_final: str | None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "reverse_tip_attempted": self.attempted,
            "reverse_tip_used": self.used,
            "reverse_trigger": self.trigger,
            "position_source_forward": self.position_source_forward,
            "position_source_reverse": self.position_source_reverse,
            "position_source_final": self.position_source_final,
        }


@dataclass(frozen=True)
class Stage4EventReference:
    event_axis_branch_id: str | None
    event_origin_source: str
    event_position_source: str
    event_split_pick_source: str
    event_chosen_s_m: float | None
    event_tip_s_m: float | None
    event_first_divstrip_hit_s_m: float | None
    event_drivezone_split_s_m: float | None
    divstrip_ref_source: str | None
    divstrip_ref_offset_m: float | None
    event_recenter_applied: bool
    event_recenter_shift_m: float | None
    event_recenter_direction: str | None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "event_axis_branch_id": self.event_axis_branch_id,
            "event_origin_source": self.event_origin_source,
            "event_position_source": self.event_position_source,
            "event_split_pick_source": self.event_split_pick_source,
            "event_chosen_s_m": self.event_chosen_s_m,
            "event_tip_s_m": self.event_tip_s_m,
            "event_first_divstrip_hit_s_m": self.event_first_divstrip_hit_s_m,
            "event_drivezone_split_s_m": self.event_drivezone_split_s_m,
            "divstrip_ref_source": self.divstrip_ref_source,
            "divstrip_ref_offset_m": self.divstrip_ref_offset_m,
            "event_recenter_applied": self.event_recenter_applied,
            "event_recenter_shift_m": self.event_recenter_shift_m,
            "event_recenter_direction": self.event_recenter_direction,
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "event_axis_branch_id": self.event_axis_branch_id,
                "event_origin_source": self.event_origin_source,
                "position_source": self.event_position_source,
                "split_pick_source": self.event_split_pick_source,
                "chosen_s_m": self.event_chosen_s_m,
                "tip_s_m": self.event_tip_s_m,
                "first_divstrip_hit_dist_m": self.event_first_divstrip_hit_s_m,
                "s_drivezone_split_m": self.event_drivezone_split_s_m,
                "divstrip_ref_source": self.divstrip_ref_source,
                "divstrip_ref_offset_m": self.divstrip_ref_offset_m,
            }
        )
        return payload


@dataclass(frozen=True)
class Stage4EvidenceDecision:
    primary_source: str
    selection_mode: str
    fallback_used: bool
    fallback_mode: str | None
    risk_signals: tuple[str, ...] = ()

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "evidence_source": self.primary_source,
            "selection_mode": self.selection_mode,
            "fallback_used": self.fallback_used,
            "fallback_mode": self.fallback_mode,
            "risk_signals": list(self.risk_signals),
        }


@dataclass(frozen=True)
class Stage4LegacyStep5Readiness:
    ready: bool
    reasons: tuple[str, ...]

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class Stage4LegacyStep5Bridge:
    divstrip_context: Stage4DivStripContext
    multibranch_decision: Stage4MultibranchDecision
    kind_resolution: Stage4KindResolution
    selected_side_branches: tuple[Any, ...]
    selected_branch_ids: tuple[str, ...]
    selected_event_branch_ids: tuple[str, ...]
    selected_road_ids: tuple[str, ...]
    selected_event_road_ids: tuple[str, ...]
    selected_rcsdroad_ids: tuple[str, ...]
    selected_rcsdnode_ids: tuple[str, ...]
    rcsdroad_selection_mode: str
    rcsdnode_seed_mode: str
    primary_main_rc_node: ParsedNode | None
    selected_roads: tuple[ParsedRoad, ...]
    selected_event_roads: tuple[ParsedRoad, ...]
    selected_rcsd_roads: tuple[ParsedRoad, ...]
    selected_rcsd_nodes: tuple[ParsedNode, ...]
    effective_target_rc_nodes: tuple[ParsedNode, ...]
    complex_local_support_roads: tuple[ParsedRoad, ...]
    seed_support_geometries: tuple[Any, ...]
    divstrip_constraint_geometry: Any
    event_anchor_geometry: Any
    localized_divstrip_reference_geometry: Any
    event_axis_branch: Any
    event_axis_branch_id: str | None
    event_axis_centerline: Any
    provisional_event_origin: Any
    initial_event_axis_unit_vector: tuple[float, float] | None
    boundary_branch_a: Any
    boundary_branch_b: Any
    branch_a_centerline: Any
    branch_b_centerline: Any
    event_cross_half_len_m: float
    event_reference_raw: Mapping[str, Any]
    event_origin_point: Any
    event_origin_source: str
    event_axis_unit_vector: tuple[float, float] | None
    event_recenter_applied: bool
    event_recenter_shift_m: float | None
    event_recenter_direction: str | None

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "selected_branch_ids": list(self.selected_branch_ids),
            "selected_event_branch_ids": list(self.selected_event_branch_ids),
            "selected_road_count": len(self.selected_roads),
            "selected_event_road_count": len(self.selected_event_roads),
            "selected_rcsdroad_count": len(self.selected_rcsd_roads),
            "selected_rcsdnode_count": len(self.selected_rcsd_nodes),
            "effective_target_rc_node_ids": [node.node_id for node in self.effective_target_rc_nodes],
            "complex_local_support_road_count": len(self.complex_local_support_roads),
            "event_axis_branch_id": self.event_axis_branch_id,
            "event_origin_source": self.event_origin_source,
            "event_recenter_applied": self.event_recenter_applied,
            "event_recenter_shift_m": self.event_recenter_shift_m,
            "event_recenter_direction": self.event_recenter_direction,
        }


@dataclass(frozen=True)
class Stage4EventInterpretationResult:
    representative_mainnodeid: str | None
    representative_node_id: str
    evidence_decision: Stage4EvidenceDecision
    divstrip_context: Stage4DivStripContext
    continuous_chain_decision: Stage4ContinuousChainDecision
    multibranch_decision: Stage4MultibranchDecision
    kind_resolution: Stage4KindResolution
    reverse_tip_decision: Stage4ReverseTipDecision
    event_reference: Stage4EventReference
    review_signals: tuple[str, ...]
    hard_rejection_signals: tuple[str, ...]
    risk_signals: tuple[str, ...]
    legacy_step5_bridge: Stage4LegacyStep5Bridge
    legacy_step5_readiness: Stage4LegacyStep5Readiness

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "fact_event_interpretation",
            "representative_mainnodeid": self.representative_mainnodeid,
            "representative_node_id": self.representative_node_id,
            "evidence_decision": self.evidence_decision.to_audit_summary(),
            "divstrip_context": self.divstrip_context.to_audit_summary(),
            "continuous_chain": self.continuous_chain_decision.to_audit_summary(),
            "multibranch": self.multibranch_decision.to_audit_summary(),
            "kind_resolution": self.kind_resolution.to_audit_summary(),
            "reverse_tip": self.reverse_tip_decision.to_audit_summary(),
            "event_reference": self.event_reference.to_audit_summary(),
            "review_signals": list(self.review_signals),
            "hard_rejection_signals": list(self.hard_rejection_signals),
            "risk_signals": list(self.risk_signals),
            "legacy_step5_adapter": self.legacy_step5_readiness.to_audit_summary(),
            "legacy_step5_bridge": self.legacy_step5_bridge.to_audit_summary(),
        }


def wrap_stage4_divstrip_context(raw: Mapping[str, Any]) -> Stage4DivStripContext:
    return Stage4DivStripContext(
        present=bool(raw.get("present", False)),
        nearby=bool(raw.get("nearby", False)),
        component_count=int(raw.get("component_count", 0) or 0),
        selected_component_ids=_tuple_str(raw.get("selected_component_ids")),
        selection_mode=str(raw.get("selection_mode", "roads_fallback")),
        evidence_source=str(raw.get("evidence_source", "drivezone+roads+rcsd+seed")),
        preferred_branch_ids=_tuple_str(raw.get("preferred_branch_ids")),
        ambiguous=bool(raw.get("ambiguous", False)),
        constraint_geometry=raw.get("constraint_geometry"),
        event_anchor_geometry=raw.get("event_anchor_geometry"),
        raw=dict(raw),
    )


def wrap_stage4_multibranch_decision(raw: Mapping[str, Any]) -> Stage4MultibranchDecision:
    return Stage4MultibranchDecision(
        enabled=bool(raw.get("enabled", False)),
        n=int(raw.get("n", 0) or 0),
        main_pair_item_ids=_tuple_str(raw.get("main_pair_item_ids")),
        event_candidate_count=int(raw.get("event_candidate_count", 0) or 0),
        event_candidates=_tuple_mapping(raw.get("event_candidates")),
        selected_event_index=(
            None
            if raw.get("selected_event_index") is None
            else int(raw.get("selected_event_index"))
        ),
        selected_event_branch_ids=_tuple_str(raw.get("selected_event_branch_ids")),
        selected_event_source_branch_ids=_tuple_str(raw.get("selected_event_source_branch_ids")),
        selected_side_branches=tuple(raw.get("selected_side_branches", ()) or ()),
        branches_used_count=int(raw.get("branches_used_count", 0) or 0),
        ambiguous=bool(raw.get("ambiguous", False)),
        raw=dict(raw),
    )


def wrap_stage4_kind_resolution(raw: Mapping[str, Any]) -> Stage4KindResolution:
    return Stage4KindResolution(
        source_kind=raw.get("source_kind"),
        source_kind_2=raw.get("source_kind_2"),
        operational_kind_2=raw.get("operational_kind_2"),
        complex_junction=bool(raw.get("complex_junction", False)),
        ambiguous=bool(raw.get("ambiguous", False)),
        kind_resolution_mode=str(raw.get("kind_resolution_mode", "unknown")),
        merge_score=raw.get("merge_score"),
        diverge_score=raw.get("diverge_score"),
        merge_hits=raw.get("merge_hits"),
        diverge_hits=raw.get("diverge_hits"),
        raw=dict(raw),
    )


def resolve_stage4_continuous_chain_decision(
    *,
    chain_context: Mapping[str, Any],
    kind_resolution: Stage4KindResolution,
    review_signal: str | None,
) -> Stage4ContinuousChainDecision:
    influence_mode = "none"
    applied = bool(chain_context.get("is_in_continuous_chain", False) and chain_context.get("sequential_ok", False))
    if applied and str(kind_resolution.kind_resolution_mode).startswith("continuous_chain"):
        influence_mode = "kind_resolution"
    elif applied:
        influence_mode = "event_interpretation_context"
    return Stage4ContinuousChainDecision(
        chain_component_id=normalize_id(chain_context.get("chain_component_id")),
        related_mainnodeids=_tuple_str(chain_context.get("related_mainnodeids")),
        is_in_continuous_chain=bool(chain_context.get("is_in_continuous_chain", False)),
        chain_node_count=int(chain_context.get("chain_node_count", 0) or 0),
        chain_node_offset_m=chain_context.get("chain_node_offset_m"),
        sequential_ok=bool(chain_context.get("sequential_ok", False)),
        chain_bidirectional=bool(chain_context.get("chain_bidirectional", False)),
        applied_to_event_interpretation=applied,
        influence_mode=influence_mode,
        risk_signals=() if review_signal is None else (review_signal,),
    )

