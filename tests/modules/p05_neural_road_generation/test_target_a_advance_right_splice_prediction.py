from __future__ import annotations

from copy import deepcopy

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_splice_materialization import (
    AttachmentOperation,
    ParentPiece,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_splice_prediction import (
    bind_mixed_splice_prediction,
    decode_mixed_splice_prediction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AttachmentEndpoint,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    RoadSource,
    SegmentDecision,
)


def _prediction(
    *,
    operation: str = "REUSE_ENDPOINT",
    parent_piece: str | None = None,
) -> dict[str, object]:
    attachment = {
        "proposal_id": "attach",
        "proposal_type": "SOURCE_ATTACHMENT",
        "operation": operation,
        "selected_rcsd_road_id": "ar-rcsd",
        "selected_endpoint_index": 0,
        "target_ordinary_road_id": "left-parent",
        "target_fraction": 0.0 if operation == "REUSE_ENDPOINT" else 0.6,
    }
    if parent_piece is not None:
        attachment["parent_piece"] = parent_piece
    return {
        "predicted_plan_type": "MIXED_SPLICE",
        "automatic_decision": True,
        "missing_geometry_proposal_types": [],
        "raw_selected_candidate_road_ids": ["ar-rcsd"],
        "raw_selected_fixed_swsd_road_ids": ["ar-swsd"],
        "selected_geometry_proposals": [
            attachment,
            {
                "proposal_id": "splice",
                "proposal_type": "MIDDLE_SPLICE",
                "operation": "SPLICE",
                "selected_rcsd_road_id": "ar-rcsd",
                "swsd_road_id": "ar-swsd",
                "rcsd_fraction": 0.75,
                "swsd_fraction": 0.25,
            },
        ],
    }


def test_prediction_adapter_binds_only_explicit_and_frozen_fields() -> None:
    decoded = decode_mixed_splice_prediction(_prediction())
    assert decoded.rcsd_side is AttachmentEndpoint.SOURCE
    assert decoded.rcsd_parent_operation is AttachmentOperation.REUSE_ENDPOINT
    assert decoded.rcsd_child_endpoint is AttachmentEndpoint.SOURCE

    bound = bind_mixed_splice_prediction(
        decoded,
        plan_id="plan",
        advance_right_segment_id="ar",
        source_segment_id="left",
        target_segment_id="right",
        source_access_binding_id="left@ar",
        target_access_binding_id="right@ar",
        source_access_road_id="left-parent",
        target_access_road_id="right-parent",
        swsd_parent_fraction=0.0,
        swsd_child_endpoint=AttachmentEndpoint.TARGET,
        frozen_direction=2,
    )
    assert (
        bound.plan.decision
        is SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE
    )
    assert bound.plan.source_condition == (
        RoadSource.RCSD,
        RoadSource.SWSD,
    )
    assert {row.side for row in bound.locked_attachments} == {
        AttachmentEndpoint.SOURCE,
        AttachmentEndpoint.TARGET,
    }
    assert bound.middle_splice.rcsd_fraction == 0.75
    assert bound.middle_splice.swsd_fraction == 0.25


def test_prediction_adapter_rejects_cross_head_road_mismatch() -> None:
    prediction = deepcopy(_prediction())
    prediction["selected_geometry_proposals"][1][
        "selected_rcsd_road_id"
    ] = "other"
    with pytest.raises(
        ValueError,
        match="attachment Road differs",
    ):
        decode_mixed_splice_prediction(prediction)


def test_split_recipe_requires_the_learned_final_parent_piece() -> None:
    decoded = decode_mixed_splice_prediction(
        _prediction(operation="SPLIT_ROAD")
    )
    with pytest.raises(
        ValueError,
        match="lacks its final parent piece",
    ):
        bind_mixed_splice_prediction(
            decoded,
            plan_id="plan",
            advance_right_segment_id="ar",
            source_segment_id="left",
            target_segment_id="right",
            source_access_binding_id="left@ar",
            target_access_binding_id="right@ar",
            source_access_road_id="left-parent",
            target_access_road_id="right-parent",
            swsd_parent_fraction=0.0,
            swsd_child_endpoint=AttachmentEndpoint.TARGET,
            frozen_direction=2,
        )

    decoded_with_piece = decode_mixed_splice_prediction(
        _prediction(
            operation="SPLIT_ROAD",
            parent_piece=ParentPiece.SOURCE_PART.value,
        )
    )
    assert (
        decoded_with_piece.rcsd_parent_piece
        is ParentPiece.SOURCE_PART
    )
