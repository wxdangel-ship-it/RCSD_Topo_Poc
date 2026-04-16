from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_facts import (
    BUSINESS_OUTCOME_FAILURE,
    BUSINESS_OUTCOME_RISK,
    BUSINESS_OUTCOME_SUCCESS,
    ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    ROOT_CAUSE_LAYER_STEP4,
    ROOT_CAUSE_LAYER_STEP5,
    ROOT_CAUSE_LAYER_STEP6,
    VISUAL_REVIEW_V1,
    VISUAL_REVIEW_V2,
    VISUAL_REVIEW_V3,
    VISUAL_REVIEW_V4,
    VISUAL_REVIEW_V5,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_execution_contract import (
    Stage4RepresentativeFields,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import (
    Stage4EventInterpretationResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_step6_contract import (
    Stage4PolygonAssemblyResult,
)


FROZEN_CONSTRAINT_REASON_PREFIXES = (
    "missing_required_field",
    "invalid_crs",
    "mainnodeid_not_found",
    "mainnodeid_out_of_scope",
    "step4_legacy_step5_adapter_not_ready",
    "step6_legacy_step7_adapter_not_ready",
)
STEP4_HARD_REJECTION_TOKENS = (
    "coverage_incomplete",
    "rcsd_outside_drivezone",
    "rcsdnode_main_off_trunk",
    "rcsdnode_main_out_of_window",
    "rcsdnode_main_direction_invalid",
    "divstrip_component_ambiguous",
    "multibranch_event_ambiguous",
    "complex_kind_ambiguous",
    "continuous_chain_review",
)
STEP5_FOREIGN_TOKENS = (
    "foreign",
    "opposite",
    "outside_drivezone_soft_excluded",
    "foreign_corridor",
)
OFF_TRUNK_FULL_AXIS_FOREIGN_REASON = "foreign_corridor_off_trunk_full_axis_drivezone_fill"
PARALLEL_SIDE_FULL_FILL_FOREIGN_REASON = "foreign_corridor_parallel_side_full_axis_drivezone_fill"
PARALLEL_SIDE_FOREIGN_LATERAL_DIST_THRESHOLD_M = 20.0
STEP6_REVIEW_RISK_SIGNALS = frozenset(
    {
        "multi_component_surface",
        "complex_multibranch_lobe",
        "parallel_side_split",
        "cross_section_only_clip",
        "component_support_fallback",
    }
)
STEP6_ACCEPTABLE_RISK_SIGNALS = frozenset(
    {
        "component_reseeded_after_clip",
        "full_axis_drivezone_fill",
    }
)


def _dedupe_strings(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return tuple(items)


def _bool_int(value: bool) -> int:
    return 1 if value else 0


def _reason_tokens(reason: str | None) -> str:
    return str(reason or "").strip().lower()


def _reason_is_frozen_constraint(reason: str | None) -> bool:
    token = _reason_tokens(reason)
    return any(token.startswith(prefix) for prefix in FROZEN_CONSTRAINT_REASON_PREFIXES)


def _infer_root_cause_layer(reason: str | None) -> str | None:
    token = _reason_tokens(reason)
    if not token:
        return None
    if _reason_is_frozen_constraint(token):
        return ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
    if any(marker in token for marker in STEP5_FOREIGN_TOKENS):
        return ROOT_CAUSE_LAYER_STEP5
    if any(marker in token for marker in STEP4_HARD_REJECTION_TOKENS) or any(
        marker in token
        for marker in (
            "divstrip",
            "multibranch",
            "continuous_chain",
            "complex_kind",
            "rcsd",
            "coverage",
            "event_interpretation",
            "reverse_tip",
        )
    ):
        return ROOT_CAUSE_LAYER_STEP4
    if any(
        marker in token
        for marker in (
            "geometry",
            "component_",
            "cross_section",
            "parallel_side",
            "full_axis",
            "drivezone_fill",
            "polygon",
            "support_fallback",
            "lobe",
        )
    ):
        return ROOT_CAUSE_LAYER_STEP6
    return ROOT_CAUSE_LAYER_STEP6


def resolve_stage4_output_mainnodeid(
    *,
    representative_node_id: str,
    representative_mainnodeid: str | None,
) -> str:
    return str(representative_mainnodeid or representative_node_id)


@dataclass(frozen=True)
class Stage4ConditionalRCSDStatus:
    required: bool
    applied: bool
    primary_main_rcsdnode_present: bool
    direct_target_count: int
    effective_target_count: int
    coverage_mode: str | None
    tolerance_rule: str | None
    tolerance_applied: bool
    coverage_missing_ids: tuple[str, ...]
    review_reasons: tuple[str, ...]
    hard_rejection_reasons: tuple[str, ...]

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "applied": self.applied,
            "primary_main_rcsdnode_present": self.primary_main_rcsdnode_present,
            "direct_target_count": self.direct_target_count,
            "effective_target_count": self.effective_target_count,
            "coverage_mode": self.coverage_mode,
            "tolerance_rule": self.tolerance_rule,
            "tolerance_applied": self.tolerance_applied,
            "coverage_missing_ids": list(self.coverage_missing_ids),
            "review_reasons": list(self.review_reasons),
            "hard_rejection_reasons": list(self.hard_rejection_reasons),
        }


@dataclass(frozen=True)
class Stage4FrozenConstraintsConflict:
    has_conflict: bool
    reasons: tuple[str, ...]

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class Stage4DecisionBasis:
    items: tuple[str, ...]

    def to_audit_summary(self) -> list[str]:
        return list(self.items)


@dataclass(frozen=True)
class Stage4ReviewMetadata:
    root_cause_layer: str | None
    root_cause_type: str | None
    visual_review_class: str
    business_outcome_class: str

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "root_cause_layer": self.root_cause_layer,
            "root_cause_type": self.root_cause_type,
            "visual_review_class": self.visual_review_class,
            "business_outcome_class": self.business_outcome_class,
        }


@dataclass(frozen=True)
class Stage4Step7DecisionInputs:
    representative_node_id: str
    representative_mainnodeid: str | None
    representative_fields: Stage4RepresentativeFields
    step4_event_interpretation: Stage4EventInterpretationResult
    step6_polygon_assembly: Stage4PolygonAssemblyResult
    primary_main_rc_node_present: bool
    direct_target_rc_node_ids: tuple[str, ...] = ()
    effective_target_rc_node_ids: tuple[str, ...] = ()
    coverage_missing_ids: tuple[str, ...] = ()
    primary_rcsdnode_tolerance: Mapping[str, Any] = field(default_factory=dict)
    base_review_reasons: tuple[str, ...] = ()
    base_hard_rejection_reasons: tuple[str, ...] = ()
    flow_success: bool = True


@dataclass(frozen=True)
class Stage4AcceptanceDecision:
    acceptance_class: str
    acceptance_reason: str
    success: bool
    flow_success: bool
    review_reasons: tuple[str, ...]
    hard_rejection_reasons: tuple[str, ...]
    business_outcome_class: str
    visual_review_class: str
    root_cause_layer: str | None
    root_cause_type: str | None

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "acceptance_class": self.acceptance_class,
            "acceptance_reason": self.acceptance_reason,
            "success": self.success,
            "flow_success": self.flow_success,
            "review_reasons": list(self.review_reasons),
            "hard_rejection_reasons": list(self.hard_rejection_reasons),
            "business_outcome_class": self.business_outcome_class,
            "visual_review_class": self.visual_review_class,
            "root_cause_layer": self.root_cause_layer,
            "root_cause_type": self.root_cause_type,
        }


@dataclass(frozen=True)
class Stage4Step7AcceptanceResult:
    output_mainnodeid: str
    conditional_rcsd_status: Stage4ConditionalRCSDStatus
    frozen_constraints_conflict: Stage4FrozenConstraintsConflict
    decision_basis: Stage4DecisionBasis
    decision: Stage4AcceptanceDecision

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "final_acceptance_and_publishing",
            "output_mainnodeid": self.output_mainnodeid,
            "conditional_rcsd_status": self.conditional_rcsd_status.to_audit_summary(),
            "frozen_constraints_conflict": self.frozen_constraints_conflict.to_audit_summary(),
            "decision_basis": self.decision_basis.to_audit_summary(),
            "decision": self.decision.to_audit_summary(),
        }


def evaluate_stage4_conditional_rcsd_status(
    *,
    direct_target_rc_node_ids: Sequence[str],
    effective_target_rc_node_ids: Sequence[str],
    primary_main_rc_node_present: bool,
    coverage_missing_ids: Sequence[str],
    primary_rcsdnode_tolerance: Mapping[str, Any],
) -> Stage4ConditionalRCSDStatus:
    direct_target_ids = _dedupe_strings(direct_target_rc_node_ids)
    effective_target_ids = _dedupe_strings(effective_target_rc_node_ids)
    missing_ids = _dedupe_strings(coverage_missing_ids)
    tolerance_reason = str(primary_rcsdnode_tolerance.get("reason") or "").strip() or None
    tolerance_rule = str(primary_rcsdnode_tolerance.get("rcsdnode_tolerance_rule") or "").strip() or None
    coverage_mode = str(primary_rcsdnode_tolerance.get("rcsdnode_coverage_mode") or "").strip() or None
    tolerance_applied = bool(primary_rcsdnode_tolerance.get("rcsdnode_tolerance_applied", False))

    required = bool(direct_target_ids)
    review_reasons: list[str] = []
    hard_rejection_reasons: list[str] = []

    if required:
        if missing_ids:
            hard_rejection_reasons.append("coverage_incomplete")
        if tolerance_reason in {
            "rcsdnode_main_off_trunk",
            "rcsdnode_main_out_of_window",
            "rcsdnode_main_direction_invalid",
            "rcsd_outside_drivezone",
        }:
            hard_rejection_reasons.append(str(tolerance_reason))
    elif primary_main_rc_node_present and tolerance_reason in {
        "rcsdnode_main_off_trunk",
        "rcsdnode_main_out_of_window",
        "rcsdnode_main_direction_invalid",
    }:
        review_reasons.append(str(tolerance_reason))

    return Stage4ConditionalRCSDStatus(
        required=required,
        applied=required or tolerance_applied or primary_main_rc_node_present,
        primary_main_rcsdnode_present=primary_main_rc_node_present,
        direct_target_count=len(direct_target_ids),
        effective_target_count=len(effective_target_ids),
        coverage_mode=coverage_mode,
        tolerance_rule=tolerance_rule,
        tolerance_applied=tolerance_applied,
        coverage_missing_ids=missing_ids,
        review_reasons=_dedupe_strings(review_reasons),
        hard_rejection_reasons=_dedupe_strings(hard_rejection_reasons),
    )


def evaluate_stage4_frozen_constraints_conflict(
    *,
    output_mainnodeid: str,
    representative_fields: Stage4RepresentativeFields,
    step4_event_interpretation: Stage4EventInterpretationResult,
    step6_polygon_assembly: Stage4PolygonAssemblyResult,
) -> Stage4FrozenConstraintsConflict:
    reasons: list[str] = []
    if not str(output_mainnodeid).strip():
        reasons.append("missing_required_field:mainnodeid")
    if representative_fields.kind is None:
        reasons.append("missing_required_field:kind")
    if not step4_event_interpretation.legacy_step5_readiness.ready:
        reasons.append("step4_legacy_step5_adapter_not_ready")
    if not step6_polygon_assembly.legacy_step7_bridge.ready:
        reasons.append("step6_legacy_step7_adapter_not_ready")
    return Stage4FrozenConstraintsConflict(
        has_conflict=bool(reasons),
        reasons=_dedupe_strings(reasons),
    )


def _resolve_review_metadata(
    *,
    business_outcome_class: str,
    acceptance_reason: str,
    frozen_constraints_conflict: Stage4FrozenConstraintsConflict,
) -> Stage4ReviewMetadata:
    if business_outcome_class == BUSINESS_OUTCOME_SUCCESS:
        return Stage4ReviewMetadata(
            root_cause_layer=None,
            root_cause_type=None,
            visual_review_class=VISUAL_REVIEW_V1,
            business_outcome_class=BUSINESS_OUTCOME_SUCCESS,
        )

    if frozen_constraints_conflict.has_conflict:
        reason = frozen_constraints_conflict.reasons[0]
        return Stage4ReviewMetadata(
            root_cause_layer=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
            root_cause_type=reason,
            visual_review_class=VISUAL_REVIEW_V5,
            business_outcome_class=BUSINESS_OUTCOME_FAILURE,
        )

    root_cause_layer = _infer_root_cause_layer(acceptance_reason)
    if business_outcome_class == BUSINESS_OUTCOME_RISK:
        return Stage4ReviewMetadata(
            root_cause_layer=root_cause_layer or ROOT_CAUSE_LAYER_STEP6,
            root_cause_type=acceptance_reason,
            visual_review_class=VISUAL_REVIEW_V2,
            business_outcome_class=BUSINESS_OUTCOME_RISK,
        )

    if root_cause_layer == ROOT_CAUSE_LAYER_STEP5:
        visual_review_class = VISUAL_REVIEW_V4
    elif root_cause_layer == ROOT_CAUSE_LAYER_STEP4:
        visual_review_class = VISUAL_REVIEW_V3
    else:
        visual_review_class = VISUAL_REVIEW_V5
    return Stage4ReviewMetadata(
        root_cause_layer=root_cause_layer,
        root_cause_type=acceptance_reason,
        visual_review_class=visual_review_class,
        business_outcome_class=BUSINESS_OUTCOME_FAILURE,
    )


def build_stage4_step7_acceptance_result(
    inputs: Stage4Step7DecisionInputs,
) -> Stage4Step7AcceptanceResult:
    output_mainnodeid = resolve_stage4_output_mainnodeid(
        representative_node_id=inputs.representative_node_id,
        representative_mainnodeid=inputs.representative_mainnodeid,
    )
    conditional_rcsd_status = evaluate_stage4_conditional_rcsd_status(
        direct_target_rc_node_ids=inputs.direct_target_rc_node_ids,
        effective_target_rc_node_ids=inputs.effective_target_rc_node_ids,
        primary_main_rc_node_present=inputs.primary_main_rc_node_present,
        coverage_missing_ids=inputs.coverage_missing_ids,
        primary_rcsdnode_tolerance=inputs.primary_rcsdnode_tolerance,
    )
    frozen_constraints_conflict = evaluate_stage4_frozen_constraints_conflict(
        output_mainnodeid=output_mainnodeid,
        representative_fields=inputs.representative_fields,
        step4_event_interpretation=inputs.step4_event_interpretation,
        step6_polygon_assembly=inputs.step6_polygon_assembly,
    )

    review_reasons = list(
        _dedupe_strings(
            (
                *inputs.base_review_reasons,
                *inputs.step4_event_interpretation.review_signals,
                *conditional_rcsd_status.review_reasons,
            )
        )
    )
    hard_rejection_reasons = list(
        _dedupe_strings(
            (
                *inputs.base_hard_rejection_reasons,
                *inputs.step4_event_interpretation.hard_rejection_signals,
                *conditional_rcsd_status.hard_rejection_reasons,
            )
        )
    )

    geometry_state = inputs.step6_polygon_assembly.geometry_state.value
    geometry_risk_signals = tuple(inputs.step6_polygon_assembly.geometry_risk_signals.signals)
    step4_risk_signals = tuple(inputs.step4_event_interpretation.risk_signals)
    parallel_side_clip_applied = bool(
        getattr(inputs.step6_polygon_assembly, "parallel_side_clip_applied", False)
    )
    full_fill_applied = bool(getattr(inputs.step6_polygon_assembly, "full_fill_applied", False))
    lateral_dist_raw = inputs.primary_rcsdnode_tolerance.get("rcsdnode_lateral_dist_m")
    try:
        rcsdnode_lateral_dist_m = (
            None if lateral_dist_raw in {None, ""} else float(lateral_dist_raw)
        )
    except (TypeError, ValueError):
        rcsdnode_lateral_dist_m = None
    review_geometry_risks = tuple(
        signal for signal in geometry_risk_signals if signal in STEP6_REVIEW_RISK_SIGNALS
    )
    accepted_geometry_risks = tuple(
        signal for signal in geometry_risk_signals if signal in STEP6_ACCEPTABLE_RISK_SIGNALS
    )

    if review_geometry_risks and "geometry_built_with_risk" not in review_reasons:
        review_reasons.append("geometry_built_with_risk")
    review_reasons.extend(signal for signal in review_geometry_risks if signal not in review_reasons)
    review_reasons.extend(signal for signal in step4_risk_signals if signal not in review_reasons)

    if geometry_state == "geometry_not_built":
        hard_rejection_reasons.append("geometry_not_built")

    if (
        not conditional_rcsd_status.required
        and conditional_rcsd_status.coverage_mode == "off_trunk"
        and "rcsdnode_main_off_trunk" in review_reasons
        and "full_axis_drivezone_fill" in geometry_risk_signals
        and OFF_TRUNK_FULL_AXIS_FOREIGN_REASON not in hard_rejection_reasons
    ):
        hard_rejection_reasons.append(OFF_TRUNK_FULL_AXIS_FOREIGN_REASON)
        accepted_geometry_risks = tuple(
            signal for signal in accepted_geometry_risks if signal != "full_axis_drivezone_fill"
        )

    if (
        full_fill_applied
        and parallel_side_clip_applied
        and conditional_rcsd_status.coverage_mode == "exact_cover"
        and rcsdnode_lateral_dist_m is not None
        and rcsdnode_lateral_dist_m >= PARALLEL_SIDE_FOREIGN_LATERAL_DIST_THRESHOLD_M
        and PARALLEL_SIDE_FULL_FILL_FOREIGN_REASON not in hard_rejection_reasons
    ):
        hard_rejection_reasons.append(PARALLEL_SIDE_FULL_FILL_FOREIGN_REASON)
        accepted_geometry_risks = tuple(
            signal
            for signal in accepted_geometry_risks
            if signal not in {"full_axis_drivezone_fill", "component_reseeded_after_clip"}
        )

    decision_basis_items = [
        f"output_mainnodeid={output_mainnodeid}",
        f"evidence_source={inputs.step4_event_interpretation.evidence_decision.primary_source}",
        f"selection_mode={inputs.step4_event_interpretation.evidence_decision.selection_mode}",
        f"geometry_state={geometry_state}",
        f"conditional_rcsd_required={conditional_rcsd_status.required}",
        f"conditional_rcsd_coverage_mode={conditional_rcsd_status.coverage_mode}",
        f"step6_parallel_side_clip_applied={parallel_side_clip_applied}",
        f"step6_full_fill_applied={full_fill_applied}",
        f"frozen_constraints_conflict={frozen_constraints_conflict.has_conflict}",
    ]
    if rcsdnode_lateral_dist_m is not None:
        decision_basis_items.append(f"rcsdnode_lateral_dist_m={rcsdnode_lateral_dist_m:.3f}")
    decision_basis_items.extend(f"geometry_risk={signal}" for signal in geometry_risk_signals)
    decision_basis_items.extend(f"step4_risk={signal}" for signal in step4_risk_signals)
    decision_basis_items.extend(f"review_reason={reason}" for reason in review_reasons)
    decision_basis_items.extend(f"hard_rejection_reason={reason}" for reason in hard_rejection_reasons)
    if accepted_geometry_risks:
        decision_basis_items.append(
            "accepted_geometry_risks=" + ",".join(accepted_geometry_risks)
        )
    if inputs.step4_event_interpretation.reverse_tip_decision.used:
        decision_basis_items.append("reverse_tip_used=true")
    if inputs.step4_event_interpretation.evidence_decision.fallback_used:
        decision_basis_items.append("weak_evidence_fallback=true")
    decision_basis = Stage4DecisionBasis(items=_dedupe_strings(decision_basis_items))

    if frozen_constraints_conflict.has_conflict:
        acceptance_reason = frozen_constraints_conflict.reasons[0]
        business_outcome_class = BUSINESS_OUTCOME_FAILURE
    elif hard_rejection_reasons:
        acceptance_reason = hard_rejection_reasons[0]
        business_outcome_class = BUSINESS_OUTCOME_FAILURE
    elif review_reasons:
        acceptance_reason = review_reasons[0]
        business_outcome_class = BUSINESS_OUTCOME_RISK
    else:
        acceptance_reason = "stable"
        business_outcome_class = BUSINESS_OUTCOME_SUCCESS

    review_metadata = _resolve_review_metadata(
        business_outcome_class=business_outcome_class,
        acceptance_reason=acceptance_reason,
        frozen_constraints_conflict=frozen_constraints_conflict,
    )
    acceptance_class = (
        "accepted"
        if business_outcome_class == BUSINESS_OUTCOME_SUCCESS
        else ("review_required" if business_outcome_class == BUSINESS_OUTCOME_RISK else "rejected")
    )
    decision = Stage4AcceptanceDecision(
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
        success=business_outcome_class == BUSINESS_OUTCOME_SUCCESS,
        flow_success=inputs.flow_success,
        review_reasons=_dedupe_strings(review_reasons),
        hard_rejection_reasons=_dedupe_strings(hard_rejection_reasons),
        business_outcome_class=review_metadata.business_outcome_class,
        visual_review_class=review_metadata.visual_review_class,
        root_cause_layer=review_metadata.root_cause_layer,
        root_cause_type=review_metadata.root_cause_type,
    )
    return Stage4Step7AcceptanceResult(
        output_mainnodeid=output_mainnodeid,
        conditional_rcsd_status=conditional_rcsd_status,
        frozen_constraints_conflict=frozen_constraints_conflict,
        decision_basis=decision_basis,
        decision=decision,
    )


def build_stage4_failure_step7_result(
    *,
    output_mainnodeid: str,
    kind: int | None,
    reason: str,
    flow_success: bool,
) -> Stage4Step7AcceptanceResult:
    acceptance_reason = str(reason)
    frozen_constraints_conflict = Stage4FrozenConstraintsConflict(
        has_conflict=_reason_is_frozen_constraint(reason),
        reasons=(acceptance_reason,) if _reason_is_frozen_constraint(reason) else (),
    )
    review_metadata = _resolve_review_metadata(
        business_outcome_class=BUSINESS_OUTCOME_FAILURE,
        acceptance_reason=acceptance_reason,
        frozen_constraints_conflict=frozen_constraints_conflict,
    )
    return Stage4Step7AcceptanceResult(
        output_mainnodeid=output_mainnodeid,
        conditional_rcsd_status=Stage4ConditionalRCSDStatus(
            required=False,
            applied=False,
            primary_main_rcsdnode_present=False,
            direct_target_count=0,
            effective_target_count=0,
            coverage_mode=None,
            tolerance_rule=None,
            tolerance_applied=False,
            coverage_missing_ids=(),
            review_reasons=(),
            hard_rejection_reasons=(),
        ),
        frozen_constraints_conflict=frozen_constraints_conflict,
        decision_basis=Stage4DecisionBasis(
            items=_dedupe_strings(
                (
                    f"output_mainnodeid={output_mainnodeid}",
                    f"kind={kind}",
                    f"failure_reason={acceptance_reason}",
                    f"frozen_constraints_conflict={frozen_constraints_conflict.has_conflict}",
                )
            )
        ),
        decision=Stage4AcceptanceDecision(
            acceptance_class="rejected",
            acceptance_reason=acceptance_reason,
            success=False,
            flow_success=flow_success,
            review_reasons=(),
            hard_rejection_reasons=(acceptance_reason,),
            business_outcome_class=review_metadata.business_outcome_class,
            visual_review_class=review_metadata.visual_review_class,
            root_cause_layer=review_metadata.root_cause_layer,
            root_cause_type=review_metadata.root_cause_type,
        ),
    )
