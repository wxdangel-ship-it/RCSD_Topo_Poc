from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
        Stage3Step7AcceptanceResult,
    )


FAILURE_BUCKET_OFFICIAL_REVIEW_CASE = "official_review_case"
FAILURE_BUCKET_OFFICIAL_FAILURE = "official_failure"
STAGE3_ALLOWED_KIND_2_VALUES = frozenset({4, 2048})
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_facts import (
    BUSINESS_OUTCOME_FAILURE,
    ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    ROOT_CAUSE_LAYER_STEP3,
    ROOT_CAUSE_LAYER_STEP4,
    ROOT_CAUSE_LAYER_STEP5,
    ROOT_CAUSE_LAYER_STEP6,
    VISUAL_REVIEW_V1,
    VISUAL_REVIEW_V2,
    VISUAL_REVIEW_V3,
    VISUAL_REVIEW_V4,
    VISUAL_REVIEW_V5,
    derive_stage3_review_fields,
)


@dataclass(frozen=True)
class Stage3ReviewMetadata:
    root_cause_layer: str | None
    root_cause_type: str | None
    visual_review_class: str
    business_outcome_class: str


@dataclass(frozen=True)
class Stage3OfficialReviewDecision:
    official_review_eligible: bool
    blocking_reason: str | None
    failure_bucket: str


def resolve_stage3_output_mainnodeid(*, representative_node_id: str, representative_mainnodeid: str | None) -> str:
    return representative_mainnodeid or representative_node_id


def _is_missing_stage3_output_value(value: Any | None) -> bool:
    return value is None or value == ""


def _normalize_stage3_flag(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.lower()


def _coerce_optional_int(value: Any | None) -> int | None:
    if _is_missing_stage3_output_value(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_stage3_output_kind(
    *,
    representative_kind: Any | None,
    representative_kind_2: Any | None = None,
    representative_properties: Mapping[str, Any] | None = None,
) -> Any | None:
    if not _is_missing_stage3_output_value(representative_kind):
        return representative_kind
    if representative_properties is not None:
        properties_kind = representative_properties.get("kind")
        if not _is_missing_stage3_output_value(properties_kind):
            return properties_kind
        properties_kind_2 = representative_properties.get("kind_2")
        if not _is_missing_stage3_output_value(properties_kind_2):
            return properties_kind_2
    if not _is_missing_stage3_output_value(representative_kind_2):
        return representative_kind_2
    return None


def resolve_stage3_output_kind_source(
    *,
    representative_kind: Any | None,
    representative_kind_2: Any | None = None,
    representative_properties: Mapping[str, Any] | None = None,
) -> str | None:
    if not _is_missing_stage3_output_value(representative_kind):
        return "nodes.kind"
    if representative_properties is not None:
        properties_kind = representative_properties.get("kind")
        if not _is_missing_stage3_output_value(properties_kind):
            return "nodes.kind"
        properties_kind_2 = representative_properties.get("kind_2")
        if not _is_missing_stage3_output_value(properties_kind_2):
            return "nodes.kind_2"
    if not _is_missing_stage3_output_value(representative_kind_2):
        return "nodes.kind_2"
    return None


def build_stage3_polygon_properties(
    *,
    representative_properties: Mapping[str, Any],
    representative_kind: Any | None,
    representative_node_id: str,
    representative_mainnodeid: str | None,
    status: str,
    kind_2: int | None,
    grade_2: int | None,
) -> dict[str, Any]:
    return {
        "mainnodeid": resolve_stage3_output_mainnodeid(
            representative_node_id=representative_node_id,
            representative_mainnodeid=representative_mainnodeid,
        ),
        "kind": resolve_stage3_output_kind(
            representative_kind=representative_kind,
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "kind_source": resolve_stage3_output_kind_source(
            representative_kind=representative_kind,
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "status": status,
        "representative_node_id": representative_node_id,
        "kind_2": kind_2,
        "grade_2": grade_2,
    }


def derive_stage3_review_metadata(
    *,
    success: bool,
    acceptance_class: str | None,
    acceptance_reason: str | None,
    status: str | None,
) -> Stage3ReviewMetadata:
    fields = derive_stage3_review_fields(
        success=success,
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
        status=status,
    )
    return Stage3ReviewMetadata(
        root_cause_layer=fields.root_cause_layer,
        root_cause_type=fields.root_cause_type,
        visual_review_class=fields.visual_review_class,
        business_outcome_class=fields.business_outcome_class,
    )


def stage3_review_metadata_dict(metadata: Stage3ReviewMetadata) -> dict[str, Any]:
    return {
        "root_cause_layer": metadata.root_cause_layer,
        "root_cause_type": metadata.root_cause_type,
        "visual_review_class": metadata.visual_review_class,
        "business_outcome_class": metadata.business_outcome_class,
    }


def stage3_review_metadata_from_step7_result(
    step7_result: "Stage3Step7AcceptanceResult",
    *,
    official_review_decision: Stage3OfficialReviewDecision | None = None,
) -> Stage3ReviewMetadata:
    if (
        official_review_decision is not None
        and not official_review_decision.official_review_eligible
    ):
        blocking_reason = (
            official_review_decision.blocking_reason
            or ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
        )
        return Stage3ReviewMetadata(
            root_cause_layer=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
            root_cause_type=str(blocking_reason),
            visual_review_class=VISUAL_REVIEW_V5,
            business_outcome_class=BUSINESS_OUTCOME_FAILURE,
        )
    return Stage3ReviewMetadata(
        root_cause_layer=step7_result.root_cause_layer,
        root_cause_type=step7_result.root_cause_type or step7_result.acceptance_reason or step7_result.status,
        visual_review_class=step7_result.visual_review_class,
        business_outcome_class=step7_result.business_outcome_class,
    )


def _derive_stage3_gate_blocking_reason(
    *,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    representative_kind_2: Any | None,
) -> str | None:
    normalized_has_evd = _normalize_stage3_flag(representative_has_evd)
    normalized_is_anchor = _normalize_stage3_flag(representative_is_anchor)
    normalized_kind_2 = _coerce_optional_int(representative_kind_2)

    if normalized_has_evd is not None and normalized_has_evd != "yes":
        return f"representative has_evd={normalized_has_evd}; excluded by Stage3 input gate"
    if normalized_is_anchor is not None and normalized_is_anchor != "no":
        return f"representative is_anchor={normalized_is_anchor}; excluded by Stage3 input gate"
    if normalized_kind_2 is not None and normalized_kind_2 not in STAGE3_ALLOWED_KIND_2_VALUES:
        return f"representative kind_2={normalized_kind_2}; excluded by Stage3 input gate"
    return None


def derive_stage3_official_review_decision(
    *,
    success: bool,
    business_outcome_class: str | None,
    acceptance_class: str | None,
    acceptance_reason: str | None,
    status: str | None,
    root_cause_layer: str | None,
    representative_has_evd: Any | None = None,
    representative_is_anchor: Any | None = None,
    representative_kind_2: Any | None = None,
) -> Stage3OfficialReviewDecision:
    gate_blocking_reason = _derive_stage3_gate_blocking_reason(
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        representative_kind_2=representative_kind_2,
    )
    if gate_blocking_reason is not None:
        return Stage3OfficialReviewDecision(
            official_review_eligible=False,
            blocking_reason=gate_blocking_reason,
            failure_bucket=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
        )

    token_parts = [acceptance_reason, status, root_cause_layer]
    normalized_token = " ".join(
        str(part).strip().lower()
        for part in token_parts
        if part is not None and str(part).strip()
    )
    if root_cause_layer == ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT or any(
        key in normalized_token
        for key in (
            "out_of_scope",
            "anchor_gate",
            "representative_node_missing",
            "mainnodeid_not_found",
            "mainnodeid_out_of_scope",
            "missing_required_field",
            "invalid_crs",
        )
    ):
        blocking_reason = acceptance_reason or status or root_cause_layer or ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
        return Stage3OfficialReviewDecision(
            official_review_eligible=False,
            blocking_reason=str(blocking_reason),
            failure_bucket=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
        )

    if (
        business_outcome_class == BUSINESS_OUTCOME_FAILURE
        or acceptance_class == "rejected"
        or (business_outcome_class is None and not success)
    ):
        return Stage3OfficialReviewDecision(
            official_review_eligible=True,
            blocking_reason=None,
            failure_bucket=FAILURE_BUCKET_OFFICIAL_FAILURE,
        )

    return Stage3OfficialReviewDecision(
        official_review_eligible=True,
        blocking_reason=None,
        failure_bucket=FAILURE_BUCKET_OFFICIAL_REVIEW_CASE,
    )


def stage3_official_review_decision_from_step7_result(
    step7_result: "Stage3Step7AcceptanceResult",
    *,
    representative_has_evd: Any | None = None,
    representative_is_anchor: Any | None = None,
    representative_kind_2: Any | None = None,
) -> Stage3OfficialReviewDecision:
    return derive_stage3_official_review_decision(
        success=step7_result.success,
        business_outcome_class=step7_result.business_outcome_class,
        acceptance_class=step7_result.acceptance_class,
        acceptance_reason=step7_result.acceptance_reason,
        status=step7_result.status,
        root_cause_layer=step7_result.root_cause_layer,
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        representative_kind_2=representative_kind_2,
    )


def stage3_official_review_decision_dict(decision: Stage3OfficialReviewDecision) -> dict[str, Any]:
    return {
        "official_review_eligible": decision.official_review_eligible,
        "blocking_reason": decision.blocking_reason,
        "failure_bucket": decision.failure_bucket,
    }
