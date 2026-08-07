from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_splice_materialization import (
    AttachmentOperation,
    LockedMiddleSplice,
    LockedRoadAttachment,
    ParentPiece,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AttachmentEndpoint,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    SegmentDecision,
)


@dataclass(frozen=True)
class DecodedMixedSplicePrediction:
    """Business choices emitted by the learned AdvanceRight heads."""

    rcsd_side: AttachmentEndpoint
    rcsd_parent_road_id: str
    rcsd_parent_fraction: float
    rcsd_parent_operation: AttachmentOperation
    rcsd_parent_piece: ParentPiece | None
    rcsd_child_road_id: str
    rcsd_child_endpoint: AttachmentEndpoint
    swsd_child_road_id: str
    rcsd_splice_fraction: float
    swsd_splice_fraction: float
    selected_rcsd_road_ids: tuple[str, ...]
    selected_swsd_road_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoundMixedSpliceRecipe:
    """Prediction bound to frozen T01 access identities and direction."""

    plan: PlanCandidate
    locked_attachments: tuple[LockedRoadAttachment, ...]
    middle_splice: LockedMiddleSplice


def decode_mixed_splice_prediction(
    prediction: Mapping[str, Any],
    *,
    require_automatic: bool = True,
) -> DecodedMixedSplicePrediction:
    """Decode model output without selecting or repairing any missing object."""

    if str(prediction.get("predicted_plan_type") or "") != "MIXED_SPLICE":
        raise ValueError("prediction is not a MIXED_SPLICE plan")
    if require_automatic and not bool(prediction.get("automatic_decision")):
        raise ValueError("MIXED_SPLICE prediction was not accepted automatically")
    if prediction.get("missing_geometry_proposal_types"):
        raise ValueError("MIXED_SPLICE prediction lacks a geometry proposal")

    proposals = list(prediction.get("selected_geometry_proposals") or ())
    attachments = [
        row
        for row in proposals
        if str(row.get("proposal_type") or "")
        in {"SOURCE_ATTACHMENT", "TARGET_ATTACHMENT"}
    ]
    splices = [
        row
        for row in proposals
        if str(row.get("proposal_type") or "") == "MIDDLE_SPLICE"
    ]
    if len(attachments) != 1 or len(splices) != 1:
        raise ValueError(
            "MIXED_SPLICE requires one RCSD attachment and one middle splice"
        )
    attachment = attachments[0]
    splice = splices[0]

    side = {
        "SOURCE_ATTACHMENT": AttachmentEndpoint.SOURCE,
        "TARGET_ATTACHMENT": AttachmentEndpoint.TARGET,
    }[str(attachment["proposal_type"])]
    operation = _enum_value(
        AttachmentOperation,
        attachment.get("operation"),
        field_name="RCSD parent operation",
    )
    parent_piece = _optional_enum_value(
        ParentPiece,
        attachment.get("parent_piece"),
        field_name="RCSD parent piece",
    )
    if operation is AttachmentOperation.REUSE_ENDPOINT and parent_piece is not None:
        raise ValueError("endpoint reuse must not select a split parent piece")
    endpoint = {
        0: AttachmentEndpoint.SOURCE,
        1: AttachmentEndpoint.TARGET,
    }.get(_optional_int(attachment.get("selected_endpoint_index")))
    if endpoint is None:
        raise ValueError("RCSD child endpoint is absent or outside {0, 1}")

    selected_rcsd = _unique_ids(
        prediction.get("raw_selected_candidate_road_ids") or (),
        field_name="selected RCSD Road set",
    )
    selected_swsd = _unique_ids(
        prediction.get("raw_selected_fixed_swsd_road_ids") or (),
        field_name="selected SWSD Road set",
    )
    rcsd_road_id = str(splice.get("selected_rcsd_road_id") or "")
    swsd_road_id = str(splice.get("swsd_road_id") or "")
    if not rcsd_road_id or not swsd_road_id:
        raise ValueError("middle splice Road pair is incomplete")
    if str(attachment.get("selected_rcsd_road_id") or "") != rcsd_road_id:
        raise ValueError("RCSD attachment Road differs from middle splice Road")
    if rcsd_road_id not in selected_rcsd:
        raise ValueError("middle RCSD Road is outside the selected complete plan")
    if swsd_road_id not in selected_swsd:
        raise ValueError("middle SWSD Road is outside the selected complete plan")

    return DecodedMixedSplicePrediction(
        rcsd_side=side,
        rcsd_parent_road_id=_required_id(
            attachment.get("target_ordinary_road_id"),
            field_name="RCSD parent Road",
        ),
        rcsd_parent_fraction=_fraction(
            attachment.get("target_fraction"),
            field_name="RCSD parent fraction",
        ),
        rcsd_parent_operation=operation,
        rcsd_parent_piece=parent_piece,
        rcsd_child_road_id=rcsd_road_id,
        rcsd_child_endpoint=endpoint,
        swsd_child_road_id=swsd_road_id,
        rcsd_splice_fraction=_fraction(
            splice.get("rcsd_fraction"),
            field_name="RCSD splice fraction",
        ),
        swsd_splice_fraction=_fraction(
            splice.get("swsd_fraction"),
            field_name="SWSD splice fraction",
        ),
        selected_rcsd_road_ids=selected_rcsd,
        selected_swsd_road_ids=selected_swsd,
    )


def bind_mixed_splice_prediction(
    decoded: DecodedMixedSplicePrediction,
    *,
    plan_id: str,
    advance_right_segment_id: str,
    source_segment_id: str,
    target_segment_id: str,
    source_access_binding_id: str,
    target_access_binding_id: str,
    source_access_road_id: str,
    target_access_road_id: str,
    swsd_parent_fraction: float,
    swsd_child_endpoint: AttachmentEndpoint,
    frozen_direction: int,
) -> BoundMixedSpliceRecipe:
    """Bind learned choices to frozen identities without adding a choice."""

    identifiers = {
        "plan id": plan_id,
        "AdvanceRight Segment": advance_right_segment_id,
        "source Segment": source_segment_id,
        "target Segment": target_segment_id,
        "source access binding": source_access_binding_id,
        "target access binding": target_access_binding_id,
        "source access Road": source_access_road_id,
        "target access Road": target_access_road_id,
    }
    for label, value in identifiers.items():
        _required_id(value, field_name=label)
    if source_segment_id == target_segment_id:
        raise ValueError("AdvanceRight adjacent Segments must differ")
    if frozen_direction not in {0, 1, 2, 3}:
        raise ValueError("frozen AdvanceRight direction is outside the formal enum")
    swsd_parent_fraction = _fraction(
        swsd_parent_fraction,
        field_name="SWSD frozen parent fraction",
    )
    if swsd_parent_fraction not in {0.0, 1.0}:
        raise ValueError("SWSD parent must reuse a frozen Road endpoint")
    if (
        decoded.rcsd_parent_operation is AttachmentOperation.SPLIT_ROAD
        and decoded.rcsd_parent_piece is None
    ):
        raise ValueError(
            "learned interior RCSD split lacks its final parent piece"
        )

    source_condition = (
        (RoadSource.RCSD, RoadSource.SWSD)
        if decoded.rcsd_side is AttachmentEndpoint.SOURCE
        else (RoadSource.SWSD, RoadSource.RCSD)
    )
    access_road_by_side = {
        AttachmentEndpoint.SOURCE: source_access_road_id,
        AttachmentEndpoint.TARGET: target_access_road_id,
    }
    binding_by_side = {
        AttachmentEndpoint.SOURCE: source_access_binding_id,
        AttachmentEndpoint.TARGET: target_access_binding_id,
    }
    if (
        access_road_by_side[decoded.rcsd_side]
        != decoded.rcsd_parent_road_id
    ):
        raise ValueError(
            "learned RCSD parent differs from the frozen selected access Road"
        )
    swsd_side = (
        AttachmentEndpoint.TARGET
        if decoded.rcsd_side is AttachmentEndpoint.SOURCE
        else AttachmentEndpoint.SOURCE
    )

    plan = PlanCandidate(
        plan_id=plan_id,
        segment_id=advance_right_segment_id,
        decision=SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE,
        roads=tuple(
            RoadUse(
                source_kind,
                road_id,
                RoadRole.ADVANCE_RIGHT,
                advance_right_segment_id,
                frozen_direction,
            )
            for source_kind, road_ids in (
                (RoadSource.RCSD, decoded.selected_rcsd_road_ids),
                (RoadSource.SWSD, decoded.selected_swsd_road_ids),
            )
            for road_id in road_ids
        ),
        source_access_road_id=source_access_road_id,
        target_access_road_id=target_access_road_id,
        node_recipes=(
            {
                "source_segment_id": source_segment_id,
                "target_segment_id": target_segment_id,
            },
        ),
        source_condition=source_condition,
    )
    plan.validate(advance_right=True)
    locked = (
        LockedRoadAttachment(
            side=decoded.rcsd_side,
            parent_access_binding_id=binding_by_side[decoded.rcsd_side],
            parent_source_road_id=decoded.rcsd_parent_road_id,
            parent_fraction=decoded.rcsd_parent_fraction,
            operation=decoded.rcsd_parent_operation,
            parent_piece=decoded.rcsd_parent_piece,
            child_source_kind=RoadSource.RCSD,
            child_source_road_id=decoded.rcsd_child_road_id,
            child_endpoint=decoded.rcsd_child_endpoint,
        ),
        LockedRoadAttachment(
            side=swsd_side,
            parent_access_binding_id=binding_by_side[swsd_side],
            parent_source_road_id=access_road_by_side[swsd_side],
            parent_fraction=swsd_parent_fraction,
            operation=AttachmentOperation.REUSE_ENDPOINT,
            parent_piece=None,
            child_source_kind=RoadSource.SWSD,
            child_source_road_id=decoded.swsd_child_road_id,
            child_endpoint=swsd_child_endpoint,
        ),
    )
    return BoundMixedSpliceRecipe(
        plan=plan,
        locked_attachments=tuple(
            sorted(locked, key=lambda row: row.side.value)
        ),
        middle_splice=LockedMiddleSplice(
            rcsd_source_road_id=decoded.rcsd_child_road_id,
            swsd_source_road_id=decoded.swsd_child_road_id,
            rcsd_fraction=decoded.rcsd_splice_fraction,
            swsd_fraction=decoded.swsd_splice_fraction,
            direction=frozen_direction,
        ),
    )


def _unique_ids(
    values: Sequence[Any],
    *,
    field_name: str,
) -> tuple[str, ...]:
    result = tuple(str(value) for value in values if str(value))
    if not result or len(result) != len(set(result)):
        raise ValueError(f"{field_name} is empty or contains duplicates")
    return result


def _fraction(value: Any, *, field_name: str) -> float:
    if value is None:
        raise ValueError(f"{field_name} is absent")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field_name} is outside [0, 1]")
    return result


def _required_id(value: Any, *, field_name: str) -> str:
    result = str(value or "")
    if not result:
        raise ValueError(f"{field_name} is empty")
    return result


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _enum_value(
    enum_type: type[AttachmentOperation],
    value: Any,
    *,
    field_name: str,
) -> AttachmentOperation:
    try:
        return enum_type(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} is unsupported") from error


def _optional_enum_value(
    enum_type: type[ParentPiece],
    value: Any,
    *,
    field_name: str,
) -> ParentPiece | None:
    if value in {None, ""}:
        return None
    try:
        return enum_type(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} is unsupported") from error


__all__ = [
    "BoundMixedSpliceRecipe",
    "DecodedMixedSplicePrediction",
    "bind_mixed_splice_prediction",
    "decode_mixed_splice_prediction",
]
