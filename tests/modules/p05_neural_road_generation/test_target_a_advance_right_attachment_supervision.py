from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_attachment_supervision import (
    resolve_final_access_parent,
    resolve_action_position,
)


def _road() -> SimpleNamespace:
    return SimpleNamespace(
        snodeid="n0",
        enodeid="n1",
        geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
    )


def _final_road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    source_road_id: str = "",
    split_original_road_id: str = "",
) -> SimpleNamespace:
    x0 = float(snodeid.removeprefix("n"))
    x1 = float(enodeid.removeprefix("n"))
    return SimpleNamespace(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        source_road_id=source_road_id,
        split_original_road_id=split_original_road_id,
        geometry=LineString([(x0, 0.0), (x1, 0.0)]),
    )


def test_split_position_uses_t06_generated_node_as_label_only_truth() -> None:
    result = resolve_action_position(
        {
            "action": "split_rcsd_road_for_swsd_advance",
            "generated_rcsd_node_id": "generated",
        },
        road=_road(),
        final_nodes={"generated": Point(4.0, 0.0)},
    )

    assert result["fraction"] == pytest.approx(0.4)
    assert result["gap_m"] == pytest.approx(0.0)
    assert result["state"] == "T06_GENERATED_NODE_PROJECTED_TO_PARENT_ROAD"


def test_reused_position_must_be_parent_road_endpoint() -> None:
    result = resolve_action_position(
        {
            "action": "reuse_existing_rcsd_endpoint_node",
            "rcsd_node_id": "n1",
        },
        road=_road(),
        final_nodes={"n1": Point(10.0, 0.0)},
    )

    assert result["fraction"] == pytest.approx(1.0)
    assert result["state"] == "T06_REUSED_ENDPOINT"


def test_reused_position_rejects_non_endpoint_without_silent_fix() -> None:
    with pytest.raises(ValueError, match="T06_REUSED_NODE_NOT_PARENT_ENDPOINT"):
        resolve_action_position(
            {
                "action": "reuse_existing_rcsd_endpoint_node",
                "rcsd_node_id": "middle",
            },
            road=_road(),
            final_nodes={"middle": Point(5.0, 0.0)},
        )


def test_final_access_parent_is_piece_leading_to_owned_carrier() -> None:
    selected = resolve_final_access_parent(
        {
            "rcsd_road_id": "pre_break",
            "generated_rcsd_node_id": "n1",
        },
        adjacent_segment_id="segment",
        relation={
            "relation_status": "replaced",
            "owned_frcsd_road_ids": "['owned']",
            "frcsd_road_ids": "['owned']",
            "related_connectivity_road_ids": "['pre_break']",
            "related_special_junction_internal_road_ids": "[]",
        },
        final_roads=[
            _final_road(
                "away",
                "n0",
                "n1",
                split_original_road_id="pre_break",
            ),
            _final_road(
                "toward",
                "n1",
                "n2",
                split_original_road_id="pre_break",
            ),
            _final_road("carrier", "n2", "n3", source_road_id="owned"),
        ],
    )

    assert selected.road_id == "toward"


def test_final_access_parent_rejects_non_rcsd_adjacent_result() -> None:
    with pytest.raises(
        ValueError,
        match="ADJACENT_SEGMENT_FINAL_SOURCE_NOT_RCSD",
    ):
        resolve_final_access_parent(
            {
                "rcsd_road_id": "pre_break",
                "generated_rcsd_node_id": "n1",
            },
            adjacent_segment_id="segment",
            relation={"relation_status": "failed"},
            final_roads=[],
        )
