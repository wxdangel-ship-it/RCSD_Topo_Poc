from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.group_replacement_audit import build_group_replacement_audit_rows
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationRecord


def test_group_replacement_audit_blocks_when_external_anchor_segment_is_not_replaceable() -> None:
    rows = build_group_replacement_audit_rows(
        fusion_units=[_segment("s1_s2", ["s1", "s2"]), _segment("sx_s3", ["sx", "s3"])],
        segments=[_segment("s1_s2", ["s1", "s2"]), _segment("sx_s3", ["sx", "s3"])],
        relation_map={
            "s1": RelationRecord("s1", 10, 0, {}),
            "s2": RelationRecord("s2", 20, 0, {}),
            "sx": RelationRecord("sx", 30, 0, {}),
        },
        rcsd_roads=[
            _road("r1", "10", "30", [(0, 0), (50, 0)]),
            _road("r2", "30", "20", [(50, 0), (100, 0)]),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30"})),
        replaceable_rows=[],
        rejected_rows=[_rejected("sx_s3", "rcsd_not_bidirectional_for_swsd_dual")],
        failure_business_audit_rows=[_failure("s1_s2", ["s1", "s2"], ["10", "20"])],
    )

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["audit_status"] == "blocked_group_closure_incomplete"
    assert props["corridor_audit_status"] == "blocked_group_closure_incomplete"
    assert props["unexpected_mapped_swsd_target_ids"] == ["sx"]
    assert props["rejected_group_segment_ids"] == ["sx_s3"]
    assert props["path_corridor_blocked_segment_ids"] == ["sx_s3"]
    assert props["repair_recommendation"] == "upstream_anchor_or_step1_group_scope_required"


def test_group_replacement_audit_separates_side_incident_from_path_corridor() -> None:
    side_segment = _segment("sx_s3", ["sx", "s3"], [(50, 0), (50, 100)])
    rows = build_group_replacement_audit_rows(
        fusion_units=[_segment("s1_s2", ["s1", "s2"]), side_segment],
        segments=[_segment("s1_s2", ["s1", "s2"]), side_segment],
        relation_map={
            "s1": RelationRecord("s1", 10, 0, {}),
            "s2": RelationRecord("s2", 20, 0, {}),
            "sx": RelationRecord("sx", 30, 0, {}),
        },
        rcsd_roads=[
            _road("r1", "10", "30", [(0, 0), (50, 0)]),
            _road("r2", "30", "20", [(50, 0), (100, 0)]),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30"})),
        replaceable_rows=[],
        rejected_rows=[_rejected("sx_s3", "rcsd_not_bidirectional_for_swsd_dual")],
        failure_business_audit_rows=[_failure("s1_s2", ["s1", "s2"], ["10", "20"])],
    )

    props = rows[0]["properties"]
    assert props["audit_status"] == "blocked_group_closure_incomplete"
    assert props["corridor_audit_status"] == "candidate_group_closure_ready"
    assert props["blocked_group_segment_ids"] == ["sx_s3"]
    assert props["path_corridor_blocked_segment_ids"] == []
    assert props["side_incident_group_segment_ids"] == ["sx_s3"]


def test_group_replacement_audit_reports_directionality_when_group_probe_fails() -> None:
    rows = build_group_replacement_audit_rows(
        fusion_units=[_segment("s1_s2", ["s1", "s2"]), _segment("sx_s3", ["sx", "s3"])],
        segments=[_segment("s1_s2", ["s1", "s2"]), _segment("sx_s3", ["sx", "s3"])],
        relation_map={
            "s1": RelationRecord("s1", 10, 0, {}),
            "s2": RelationRecord("s2", 20, 0, {}),
            "sx": RelationRecord("sx", 30, 0, {}),
        },
        rcsd_roads=[
            _road("r1", "10", "30", [(0, 0), (50, 0)], direction=2),
            _road("r2", "30", "20", [(50, 0), (100, 0)], direction=2),
        ],
        rcsd_nodes=[_node("10"), _node("20"), _node("30")],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30"})),
        replaceable_rows=[],
        rejected_rows=[_rejected("sx_s3", "rcsd_not_bidirectional_for_swsd_dual")],
        failure_business_audit_rows=[_failure("s1_s2", ["s1", "s2"], ["10", "20"])],
    )

    props = rows[0]["properties"]
    assert props["group_probe_status"] == "failed"
    assert props["group_probe_reason"] == "rcsd_not_bidirectional_for_swsd_dual"
    assert props["repair_recommendation"] == "upstream_anchor_or_rcsd_directionality_required"
    assert "bidirectional RCSD Segment" in props["notes"]


def _segment(segment_id: str, pair_nodes: list[str], coords: list[tuple[float, float]] | None = None) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": segment_id,
            "pair_nodes": pair_nodes,
            "junc_nodes": [],
            "sgrade": "dual",
        },
        "geometry": LineString(coords or [(0, 0), (100, 0)]),
    }


def _road(road_id: str, source: str, target: str, coords: list[tuple[float, float]], *, direction: int = 0) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": source,
            "enodeid": target,
            "direction": direction,
        },
        "geometry": LineString(coords),
    }


def _node(node_id: str) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": node_id,
            "mainnodeid": node_id,
            "kind": 4,
        },
        "geometry": None,
    }


def _rejected(segment_id: str, reason: str) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "swsd_segment_id": segment_id,
            "reject_reason": reason,
        },
        "geometry": None,
    }


def _failure(segment_id: str, pair_nodes: list[str], rcsd_pair_nodes: list[str]) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "swsd_segment_id": segment_id,
            "segment_outcome": "rejected",
            "reject_reason": "rcsd_not_bidirectional_for_swsd_dual",
            "failure_business_category": "directionality_mismatch_fixable",
            "swsd_pair_nodes": pair_nodes,
            "swsd_junc_nodes": [],
            "rcsd_pair_nodes": rcsd_pair_nodes,
        },
        "geometry": None,
    }
