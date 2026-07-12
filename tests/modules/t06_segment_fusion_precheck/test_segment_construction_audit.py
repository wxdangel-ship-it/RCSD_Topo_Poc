from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.segment_construction_audit import (
    SIDE_ROAD_ONLY_REPLACEMENT_BLOCK_REASON,
    apply_side_road_only_replacement_gate,
    build_and_write_segment_construction_audit,
)


def _segment(segment_id: str, *, segment_type: str = "normal") -> dict:
    return feature(
        {
            "id": segment_id,
            "segment_type": segment_type,
            "pair_nodes": "1,2" if segment_type == "normal" else "",
            "junc_nodes": "3" if segment_type == "normal" else "",
            "roads": "main1,main2,side" if segment_id == "side_missing" else "main1,main2",
        },
        LineString([(0, 0), (10, 0)]),
    )


def test_construction_audit_separates_complete_side_missing_and_anchor_failures(tmp_path) -> None:
    segments = [
        _segment("complete"),
        _segment("side_missing"),
        _segment("junc_failed"),
        _segment("pair_failed"),
        _segment("advance", segment_type="advance_right"),
    ]
    replaceable = [
        feature({"swsd_segment_id": "complete"}, None),
        feature({"swsd_segment_id": "side_missing"}, None),
    ]
    step2_rejected = [
        feature({"swsd_segment_id": "junc_failed", "reject_reason": "missing_junc_relation"}, None),
        feature({"swsd_segment_id": "pair_failed", "reject_reason": "missing_pair_relation"}, None),
    ]
    relations = [
        feature({"swsd_segment_id": "complete", "relation_status": "replaced", "relation_reason": "passed"}, None),
        feature(
            {
                "swsd_segment_id": "side_missing",
                "relation_status": "replaced+retained_swsd",
                "relation_reason": "side retained",
                "retained_detached_swsd_road_ids": ["side"],
            },
            None,
        ),
    ]

    outputs = build_and_write_segment_construction_audit(
        step_root=tmp_path,
        swsd_segments=segments,
        swsd_roads=[
            feature({"id": "main1", "snodeid": "1", "enodeid": "2"}, LineString([(0, 0), (5, 0)])),
            feature({"id": "main2", "snodeid": "2", "enodeid": "3"}, LineString([(5, 0), (10, 0)])),
            feature({"id": "side", "snodeid": "2", "enodeid": "4"}, LineString([(5, 0), (5, 5)])),
        ],
        swsd_nodes=[
            feature({"id": str(node_id), "mainnodeid": ""}, Point(float(node_id), 0))
            for node_id in range(1, 5)
        ],
        step1_rejected_rows=[],
        step2_replaceable_rows=replaceable,
        step2_rejected_rows=step2_rejected,
        segment_relation_rows=relations,
    )

    by_id = {
        row["properties"]["swsd_segment_id"]: row["properties"]
        for row in outputs.rows
    }
    assert by_id["complete"]["construction_class"] == "2a_complete"
    assert by_id["side_missing"]["construction_class"] == "2b_main_complete_side_missing"
    assert by_id["junc_failed"]["construction_class"] == "pair_only"
    assert by_id["pair_failed"]["construction_class"] == "pair_incomplete"
    assert outputs.summary["normal_segment_replaceable_count"] == 2
    assert outputs.summary["normal_segment_replaced_count"] == 2
    assert outputs.summary["advance_right_segment_count"] == 1


def test_side_road_only_gate_allows_attached_side_and_blocks_pair_to_pair_retention() -> None:
    segments = {
        "side_ok": _segment("side_missing"),
        "parallel_blocked": feature(
            {
                "id": "parallel_blocked",
                "segment_type": "normal",
                "pair_nodes": "1,2",
                "junc_nodes": "3",
                "roads": "main1,main2,parallel",
            },
            LineString([(0, 0), (10, 0)]),
        ),
    }
    segments["side_ok"]["properties"]["id"] = "side_ok"
    roads = [
        feature({"id": "main1", "snodeid": "1", "enodeid": "3"}, LineString([(0, 0), (5, 0)])),
        feature({"id": "main2", "snodeid": "3", "enodeid": "2"}, LineString([(5, 0), (10, 0)])),
        feature({"id": "side", "snodeid": "3", "enodeid": "4"}, LineString([(5, 0), (5, 5)])),
        feature({"id": "parallel", "snodeid": "1", "enodeid": "2"}, LineString([(0, 1), (10, 1)])),
    ]
    road_by_id = {row["properties"]["id"]: row for row in roads}
    nodes = [
        feature({"id": str(node_id), "mainnodeid": ""}, Point(float(node_id), 0))
        for node_id in range(1, 5)
    ]
    units = [
        SimpleNamespace(
            segment_id="side_ok",
            status="passed",
            reason="replaceable",
            retained_detached_swsd_road_ids=["side"],
            risk_flags=[],
        ),
        SimpleNamespace(
            segment_id="parallel_blocked",
            status="passed",
            reason="replaceable",
            retained_detached_swsd_road_ids=["parallel"],
            risk_flags=[],
        ),
        SimpleNamespace(
            segment_id="side_ok",
            status="passed",
            reason="replaceable",
            retained_detached_swsd_road_ids=["external"],
            risk_flags=[],
        ),
    ]
    added = {"rcsd1": ["side_ok", "parallel_blocked"], "rcsd2": ["parallel_blocked"]}

    stats = apply_side_road_only_replacement_gate(
        units=units,
        segment_by_id=segments,
        swsd_road_by_id=road_by_id,
        swsd_nodes=nodes,
        added_road_to_segments=added,
    )

    assert stats["candidate_mixed_segment_count"] == 2
    assert stats["allowed_segment_ids"] == ["side_ok"]
    assert stats["blocked_segment_ids"] == ["parallel_blocked"]
    assert units[0].status == "passed"
    assert units[1].status == "failed"
    assert units[1].reason == SIDE_ROAD_ONLY_REPLACEMENT_BLOCK_REASON
    assert units[2].status == "passed"
    assert units[2].retained_detached_swsd_road_ids == []
    assert units[2].external_retained_swsd_carrier_ids == ["external"]
    assert stats["external_carrier_segment_count"] == 1
    assert stats["external_carrier_road_count"] == 1
    assert added == {"rcsd1": ["side_ok"]}


def test_side_road_only_gate_uses_t01_side_attachment_provenance() -> None:
    segment = feature(
        {
            "id": "seg",
            "segment_type": "normal",
            "pair_nodes": "1,2",
            "junc_nodes": "",
            "roads": "main,side_loop",
        },
        LineString([(0, 0), (10, 0)]),
    )
    roads = [
        feature({"id": "main", "snodeid": "1", "enodeid": "2"}, LineString([(0, 0), (10, 0)])),
        feature(
            {
                "id": "side_loop",
                "snodeid": "1",
                "enodeid": "2",
                "segment_build_source": "side_attachment_merge",
                "side_attachment_merged_into_segmentid": "seg",
            },
            LineString([(0, 0), (5, 2), (10, 0)]),
        ),
    ]
    unit = SimpleNamespace(
        segment_id="seg",
        status="passed",
        reason="replaceable",
        retained_detached_swsd_road_ids=["side_loop"],
        risk_flags=[],
    )

    stats = apply_side_road_only_replacement_gate(
        units=[unit],
        segment_by_id={"seg": segment},
        swsd_road_by_id={row["properties"]["id"]: row for row in roads},
        swsd_nodes=[
            feature({"id": "1", "mainnodeid": ""}, Point(0, 0)),
            feature({"id": "2", "mainnodeid": ""}, Point(10, 0)),
        ],
        added_road_to_segments={"rr": ["seg"]},
    )

    assert unit.status == "passed"
    assert stats["allowed_segment_ids"] == ["seg"]
    assert stats["blocked_segment_ids"] == []
