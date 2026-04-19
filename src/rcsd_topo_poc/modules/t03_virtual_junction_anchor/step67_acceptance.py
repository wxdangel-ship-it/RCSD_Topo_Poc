from __future__ import annotations

from typing import Any

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import (
    Step6Result,
    Step7Result,
    Step67Context,
)


ROOT_CAUSE_LAYER_STEP3 = "step3"
ROOT_CAUSE_LAYER_STEP4 = "step4"
ROOT_CAUSE_LAYER_STEP5 = "step5"
ROOT_CAUSE_LAYER_STEP6 = "step6"
ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT = "frozen-constraints conflict"

VISUAL_V1 = "V1 认可成功"
VISUAL_V2 = "V2 业务正确但几何待修"
VISUAL_V3 = "V3 漏包 required"
VISUAL_V4 = "V4 误包 foreign"
VISUAL_V5 = "V5 明确失败"


def _visual_audit_family(visual_class: str) -> str:
    if visual_class == VISUAL_V1:
        return "success"
    if visual_class == VISUAL_V2:
        return "risk"
    return "failure"


def _formal_status_extra_fields(extra_fields: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, value in extra_fields.items():
        if key == "manual_review_recommended":
            continue
        if key.startswith("visual_"):
            continue
        filtered[key] = value
    return filtered


def build_step7_result(step67_context: Step67Context, step6_result: Step6Result) -> Step7Result:
    step45_case_result = step67_context.step45_case_result
    step45_context = step67_context.step45_context
    step3_state = str(step45_context.step3_status_doc.get("step3_state") or "")
    step45_reason = step45_case_result.reason

    if step45_case_result.step45_state == "not_established":
        return Step7Result(
            step7_state="rejected",
            accepted=False,
            reason="step67_blocked_by_step45",
            visual_review_class=VISUAL_V5,
            root_cause_layer=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
            root_cause_type=step45_reason,
            note="step45 prerequisite not established",
            key_metrics={},
            audit_doc={
                "classification": {
                    "step7_state": "rejected",
                    "reason": "step67_blocked_by_step45",
                    "root_cause_layer": ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
                    "root_cause_type": step45_reason,
                }
            },
            extra_status_fields={
                "step3_state": step3_state,
                "step45_state": step45_case_result.step45_state,
                "step45_reason": step45_reason,
            },
        )

    if not step6_result.geometry_established:
        secondary = str(step6_result.secondary_root_cause or "")
        if secondary == "stage3_rc_gap":
            visual_class = VISUAL_V3
        elif "foreign" in secondary:
            visual_class = VISUAL_V4
        else:
            visual_class = VISUAL_V5
        return Step7Result(
            step7_state="rejected",
            accepted=False,
            reason="step67_rejected_after_step6_failure",
            visual_review_class=visual_class,
            root_cause_layer=ROOT_CAUSE_LAYER_STEP6,
            root_cause_type=secondary or step6_result.reason,
            note="step6 geometry not established",
            key_metrics={
                "review_signal_count": len(step6_result.review_signals),
                "problem_geometry": step6_result.problem_geometry,
            },
            audit_doc={
                "classification": {
                    "step7_state": "rejected",
                    "reason": "step67_rejected_after_step6_failure",
                    "root_cause_layer": ROOT_CAUSE_LAYER_STEP6,
                    "root_cause_type": secondary or step6_result.reason,
                }
            },
            extra_status_fields={
                "step3_state": step3_state,
                "step45_state": step45_case_result.step45_state,
                "step45_reason": step45_reason,
                "step6_state": step6_result.step6_state,
                "step6_reason": step6_result.reason,
            },
        )

    accepted_reason = "step67_accepted"
    accepted_note = "all frozen constraints satisfied and geometry established"
    accepted_visual_class = VISUAL_V1
    accepted_root_cause_layer = None
    accepted_root_cause_type = None
    accepted_extra_fields = {
        "step3_state": step3_state,
        "step45_state": step45_case_result.step45_state,
        "step45_reason": step45_reason,
        "step6_state": step6_result.step6_state,
        "step6_reason": step6_result.reason,
        "manual_review_recommended": False,
        "visual_audit_family": _visual_audit_family(VISUAL_V1),
    }

    if step45_reason == "step45_support_only":
        accepted_reason = "step67_accepted_after_support_only_convergence"
        accepted_note = "support-only hook zone successfully converged into legal virtual junction geometry"
        accepted_extra_fields["support_only_resolved"] = True

    if step3_state == "review" or step45_reason == "step45_upstream_step3_review":
        accepted_reason = "step67_accepted_with_upstream_step3_visual_risk"
        accepted_note = "accepted result inherits upstream Step3 review risk for visual audit"
        accepted_visual_class = VISUAL_V2
        accepted_root_cause_layer = ROOT_CAUSE_LAYER_STEP3
        accepted_root_cause_type = step45_reason or step3_state
        accepted_extra_fields["manual_review_recommended"] = True
        accepted_extra_fields["visual_audit_family"] = _visual_audit_family(VISUAL_V2)
        accepted_extra_fields["visual_risk_reasons"] = ["upstream_step3_review"]

    elif step6_result.problem_geometry or step6_result.review_signals:
        accepted_reason = "step67_accepted_with_visual_risk"
        accepted_note = "accepted result still carries visual audit risk signals"
        accepted_visual_class = VISUAL_V2
        accepted_root_cause_layer = ROOT_CAUSE_LAYER_STEP6
        accepted_root_cause_type = (
            step6_result.review_signals[0]
            if step6_result.review_signals
            else step6_result.reason
        )
        accepted_extra_fields["manual_review_recommended"] = True
        accepted_extra_fields["visual_audit_family"] = _visual_audit_family(VISUAL_V2)
        accepted_extra_fields["visual_risk_reasons"] = list(step6_result.review_signals) or [step6_result.reason]

    return Step7Result(
        step7_state="accepted",
        accepted=True,
        reason=accepted_reason,
        visual_review_class=accepted_visual_class,
        root_cause_layer=accepted_root_cause_layer,
        root_cause_type=accepted_root_cause_type,
        note=accepted_note,
        key_metrics={
            "review_signal_count": len(step6_result.review_signals),
            "problem_geometry": step6_result.problem_geometry,
        },
        audit_doc={
            "classification": {
                "step7_state": "accepted",
                "reason": accepted_reason,
                "root_cause_layer": accepted_root_cause_layer,
                "root_cause_type": accepted_root_cause_type,
            }
        },
        extra_status_fields=accepted_extra_fields,
    )


def build_step7_status_doc(step67_context: Step67Context, step6_result: Step6Result, step7_result: Step7Result) -> dict[str, Any]:
    step45_case_result = step67_context.step45_case_result
    return {
        "case_id": step67_context.step45_context.step1_context.case_spec.case_id,
        "template_class": step45_case_result.template_class,
        "association_class": step45_case_result.association_class,
        "step45_state": step45_case_result.step45_state,
        "step6_state": step6_result.step6_state,
        "geometry_established": step6_result.geometry_established,
        "step7_state": step7_result.step7_state,
        "accepted": step7_result.accepted,
        "reason": step7_result.reason,
        "root_cause_layer": step7_result.root_cause_layer,
        "root_cause_type": step7_result.root_cause_type,
        "note": step7_result.note,
        "key_metrics": step7_result.key_metrics,
        **_formal_status_extra_fields(step7_result.extra_status_fields),
    }
