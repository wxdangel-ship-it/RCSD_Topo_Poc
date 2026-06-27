from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)


def _segment(
    segment_id: str,
    pair_nodes: list[str],
    geometry: LineString,
    *,
    sgrade: str = "主双",
    roads: list[str] | None = None,
    junc_nodes: list[str] | None = None,
) -> dict:
    return {
        "properties": {
            "id": segment_id,
            "sgrade": sgrade,
            "pair_nodes": pair_nodes,
            "junc_nodes": junc_nodes or [],
            "roads": roads or [],
        },
        "geometry": geometry,
    }


def _road(
    road_id: str,
    snode: str,
    enode: str,
    geometry: LineString,
    *,
    source: int = 1,
    direction: int = 2,
    formway: int | None = None,
    extra_props: dict | None = None,
) -> dict:
    props = {
        "id": road_id,
        "source": source,
        "snodeid": snode,
        "enodeid": enode,
        "direction": direction,
    }
    if formway is not None:
        props["formway"] = formway
    if extra_props:
        props.update(extra_props)
    return {
        "properties": props,
        "geometry": geometry,
    }


def _node(node_id: str, point: Point, *, source: int = 1, mainnodeid: str | None = None) -> dict:
    return {
        "properties": {
            "id": node_id,
            "source": source,
            "mainnodeid": mainnodeid or node_id,
            "kind": 1,
            "kind_2": 1,
        },
        "geometry": point,
    }


def _relation(
    segment_id: str,
    pair_nodes: list[str],
    frcsd_road_ids: list[str],
    node_map: list[dict],
    *,
    status: str = "replaced",
    source_values: list[int] | None = None,
    relation_reason: str = "",
    risk_flags: list[str] | None = None,
) -> dict:
    return {
        "properties": {
            "swsd_segment_id": segment_id,
            "relation_status": status,
            "relation_reason": relation_reason,
            "swsd_pair_nodes": pair_nodes,
            "swsd_junc_nodes": [],
            "frcsd_road_ids": frcsd_road_ids,
            "frcsd_road_source_values": source_values or [1],
            "swsd_to_frcsd_node_map": node_map,
            "source_mix": "+".join(f"source_{value}" for value in (source_values or [1])),
            "risk_flags": risk_flags or [],
        },
        "geometry": None,
    }


def test_topology_audit_fails_dual_segment_without_reverse_path() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]))],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 0), (10, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(10, 0))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"]
    assert internal[0]["audit_status"] == "fail"
    assert internal[0]["audit_reason"] == "dual_segment_pair_nodes_not_bidirectional"
    assert internal[0]["path_forward"] is True
    assert internal[0]["path_reverse"] is False


def test_topology_audit_warns_when_relation_scope_misses_final_reverse_path() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]))],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (10, 0)]), direction=2),
            _road("r2", "10", "20", LineString([(0, 0), (10, 0)]), direction=3),
        ],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(10, 0))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    assert internal["audit_status"] == "warn"
    assert internal["audit_reason"] == "segment_relation_road_scope_incomplete_but_final_graph_connected"
    assert internal["path_reverse"] is False
    assert internal["final_path_reverse"] is True


def test_topology_audit_warns_when_relation_scope_misses_final_road_path() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (20, 0)]), roads=["sr1"])
        ],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2)],
        frcsd_roads=[
            _road("r1", "10", "30", LineString([(0, 0), (10, 0)]), direction=2),
            _road("r2", "30", "20", LineString([(10, 0), (20, 0)]), direction=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(20, 0)),
            _node("30", Point(10, 0)),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "segment_road_relation_scope_incomplete_but_final_graph_connected"
    assert road["undirected_connected"] is False
    assert road["final_undirected_connected"] is True


def test_topology_audit_accepts_surface_split_original_rcsd_road() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (20, 0)]))],
        frcsd_roads=[
            _road(
                "r1__t06surfmid_1",
                "10",
                "30",
                LineString([(0, 0), (10, 0)]),
                extra_props={"t06_split_original_road_id": "r1"},
            ),
            _road(
                "r1__t06surfmid_2",
                "30",
                "20",
                LineString([(10, 0), (20, 0)]),
                extra_props={"t06_split_original_road_id": "r1"},
            ),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(20, 0)),
            _node("30", Point(10, 0)),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    formal = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "formal_replacement_source_consistency"
    ][0]
    assert formal["audit_status"] == "pass"
    assert formal["audit_reason"] == "formal_replacement_uses_rcsd_source_only"


def test_topology_audit_warns_group_path_corridor_retained_swsd_source() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (20, 0)]), roads=["sr1"])],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2)],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (20, 0)]), direction=2),
            _road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2),
        ],
        frcsd_nodes=[
            _node("1", Point(0, 0), source=2),
            _node("2", Point(20, 0), source=2),
            _node("10", Point(0, 0)),
            _node("20", Point(20, 0)),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1", "sr1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
                status="replaced+retained_swsd",
                source_values=[1, 2],
                relation_reason="group_path_corridor_local_coverage_retained_swsd",
                risk_flags=["group_path_corridor_replacement", "group_path_corridor_local_coverage_retained_swsd"],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    formal = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "formal_replacement_source_consistency"
    ][0]
    assert formal["audit_status"] == "warn"
    assert formal["audit_reason"] == "group_path_corridor_contains_retained_swsd_source_review"


def test_topology_audit_treats_retained_detached_swsd_road_as_carrier() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (20, 0)]), roads=["sr1"])
        ],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2)],
        frcsd_roads=[
            _road("r1", "10", "30", LineString([(0, 10), (10, 10)]), direction=2),
            _road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2),
        ],
        frcsd_nodes=[
            _node("1", Point(0, 0), source=2),
            _node("2", Point(20, 0), source=2),
            _node("10", Point(0, 10)),
            _node("20", Point(20, 10)),
            _node("30", Point(10, 10)),
        ],
        segment_relation_rows=[
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced+retained_swsd",
                    "swsd_pair_nodes": ["1", "2"],
                    "swsd_junc_nodes": [],
                    "frcsd_road_ids": ["r1"],
                    "retained_detached_swsd_road_ids": ["sr1"],
                    "frcsd_road_source_values": [1],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                        {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                    ],
                    "source_mix": "source_1",
                },
                "geometry": None,
            }
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "segment_road_relation_scope_incomplete_but_final_graph_connected"
    assert road["frcsd_node_ids"] == ["1", "2"]
    assert road["final_undirected_connected"] is True


def test_topology_audit_fails_retained_swsd_endpoint_without_mainnode_closure() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (20, 0)]), roads=["sr1"])
        ],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2)],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 10), (20, 10)]), direction=2),
            _road("sr1", "1", "2", LineString([(0, 0), (20, 0)]), source=2, direction=2),
        ],
        frcsd_nodes=[
            {
                "properties": {"id": "1", "source": 2, "semantic_junction_group_id": "SJG:10"},
                "geometry": Point(0, 0),
            },
            {
                "properties": {"id": "2", "source": 2, "semantic_junction_group_id": "SJG:20"},
                "geometry": Point(20, 0),
            },
            _node("10", Point(0, 10), source=1, mainnodeid="10"),
            _node("20", Point(20, 10), source=1, mainnodeid="20"),
        ],
        segment_relation_rows=[
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced+retained_swsd",
                    "swsd_pair_nodes": ["1", "2"],
                    "swsd_junc_nodes": [],
                    "frcsd_road_ids": ["r1", "sr1"],
                    "retained_detached_swsd_road_ids": ["sr1"],
                    "frcsd_road_source_values": [1, 2],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                        {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                    ],
                    "source_mix": "source_1+source_2",
                },
                "geometry": None,
            }
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    endpoint_rows = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "retained_swsd_endpoint_closure"
    ]
    assert [row["audit_status"] for row in endpoint_rows] == ["fail", "fail"]
    assert {row["audit_reason"] for row in endpoint_rows} == {"semantic_group_only_mainnode_not_closed"}
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_retained_swsd_endpoint_closure_fail_count"] == 2


def test_topology_audit_warns_when_corridor_gap_is_manual_review_scale() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (200, 0)]), sgrade="0-1单")],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 0), (150, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(200, 0))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    assert internal["audit_status"] == "warn"
    assert internal["audit_reason"] == "segment_corridor_coverage_manual_review_after_replacement"
    assert internal["final_corridor_uncovered_ratio"] == 0.175


def test_topology_audit_keeps_fail_when_final_corridor_is_still_uncovered() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单")],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 50), (100, 50)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 50)), _node("20", Point(100, 50))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    assert internal["audit_status"] == "fail"
    assert internal["audit_reason"] == "segment_corridor_coverage_dropped_after_replacement"
    assert internal["final_corridor_uncovered_ratio"] == 1.0


def test_topology_audit_warns_group_path_corridor_local_coverage_gap() -> None:
    relation = _relation(
        "s1",
        ["1", "2"],
        ["r1"],
        [
            {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
            {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
        ],
    )
    relation["properties"]["relation_reason"] = "group_path_corridor_replacement"
    relation["properties"]["risk_flags"] = ["group_path_corridor_replacement"]

    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单", roads=["sr1"])],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (100, 0)]), source=2, direction=2)],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 0), (30, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(30, 0))],
        segment_relation_rows=[relation],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert internal["audit_status"] == "warn"
    assert internal["audit_reason"] == "group_path_corridor_segment_local_coverage_review"
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "group_path_corridor_road_local_coverage_review"


def test_topology_audit_warns_group_path_corridor_local_road_endpoint_gap() -> None:
    relation = _relation(
        "s1",
        ["1", "3"],
        ["r_pair"],
        [
            {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
            {"swsd_node_id": "2", "frcsd_node_ids": ["30"], "mapping_status": "mapped"},
            {"swsd_node_id": "3", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
        ],
    )
    relation["properties"]["relation_reason"] = "group_path_corridor_replacement"
    relation["properties"]["risk_flags"] = ["group_path_corridor_replacement"]

    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment(
                "s1",
                ["1", "3"],
                LineString([(0, 0), (100, 0)]),
                sgrade="0-1单",
                roads=["sw1"],
                junc_nodes=["2"],
            )
        ],
        swsd_roads=[_road("sw1", "1", "2", LineString([(0, 0), (50, 0)]), source=2, direction=2)],
        frcsd_roads=[_road("r_pair", "10", "20", LineString([(0, 0), (100, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(100, 0)), _node("30", Point(50, 30))],
        segment_relation_rows=[relation],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "group_path_corridor_road_endpoint_connectivity_review"
    assert road["recommended_owner"] == "T06_step3_group_replacement_manual_audit"


def test_topology_audit_warns_group_path_corridor_local_road_direction_gap() -> None:
    relation = _relation(
        "s1",
        ["1", "2"],
        ["r1"],
        [
            {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
            {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
        ],
    )
    relation["properties"]["relation_reason"] = "group_path_corridor_replacement"
    relation["properties"]["risk_flags"] = ["group_path_corridor_replacement"]

    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单", roads=["sw1"])],
        swsd_roads=[_road("sw1", "1", "2", LineString([(0, 0), (100, 0)]), source=2, direction=2)],
        frcsd_roads=[_road("r1", "20", "10", LineString([(100, 0), (0, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(100, 0))],
        segment_relation_rows=[relation],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "group_path_corridor_road_directionality_review"
    assert road["recommended_owner"] == "T06_step3_group_replacement_manual_audit"


def test_topology_audit_fails_final_road_with_missing_endpoint_node() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2)],
        frcsd_nodes=[_node("1", Point(0, 0), source=2)],
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    integrity = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "final_road_node_integrity"
    ][0]
    assert integrity["audit_status"] == "fail"
    assert integrity["audit_reason"] == "final_road_endpoint_node_missing"
    assert integrity["frcsd_node_ids"] == ["2"]
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_final_road_node_integrity_fail_count"] == 1


def test_topology_audit_uses_existing_endpoint_node_when_source_field_is_missing() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[_road("sr1", "1", "5415248413001429", LineString([(0, 0), (10, 0)]), source=2)],
        frcsd_nodes=[
            _node("1", Point(0, 0), source=2),
            {"properties": {"id": 5415248413001429, "mainnodeid": "99"}, "geometry": Point(10, 0)},
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    integrity = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "final_road_node_integrity"
    ][0]
    assert integrity["audit_status"] == "pass"
    assert integrity["audit_reason"] == "final_road_node_integrity_passed"


def test_topology_audit_warns_retained_swsd_road_endpoint_geometry_offset() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2)],
        frcsd_nodes=[
            _node("1", Point(0, 0), source=2),
            _node("2", Point(10, 5), source=2),
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    integrity = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "final_road_node_integrity"
    ][0]
    assert integrity["audit_status"] == "warn"
    assert integrity["audit_reason"] == "final_road_endpoint_geometry_offset"
    assert integrity["recommended_owner"] == "upstream_swsd_baseline"
    assert integrity["projected_gap_m"] == 5.0


def test_topology_audit_allows_final_road_with_same_start_and_end_node() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[_road("sr1", "1", "1", LineString([(0, 0), (0, 0)]), source=2)],
        frcsd_nodes=[_node("1", Point(0, 0), source=2)],
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    integrity = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "final_road_node_integrity"
    ][0]
    assert integrity["audit_status"] == "pass"
    assert integrity["audit_reason"] == "final_road_node_integrity_passed"
    assert integrity["frcsd_node_ids"] == ["1", "1"]


def test_topology_audit_fails_replaced_segment_road_when_internal_endpoint_mapping_missing() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment(
                "s1",
                ["1", "4"],
                LineString([(0, 0), (30, 0)]),
                roads=["sr1", "sr2", "sr3"],
                junc_nodes=["2", "3"],
            )
        ],
        swsd_roads=[
            _road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2, direction=2),
            _road("sr2", "2", "3", LineString([(10, 0), (20, 0)]), source=2, direction=2),
            _road("sr3", "3", "4", LineString([(20, 0), (30, 0)]), source=2, direction=2),
        ],
        frcsd_roads=[_road("r1", "10", "40", LineString([(0, 0), (30, 0)]), direction=0)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("40", Point(30, 0))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "4"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "4", "frcsd_node_ids": ["40"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    assert internal["audit_status"] == "pass"

    road_rows = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_road_connectivity"
    ]
    by_road = {row["swsd_road_id"]: row for row in road_rows}
    assert by_road["sr2"]["audit_status"] == "fail"
    assert by_road["sr2"]["audit_reason"] == "segment_road_endpoint_mapping_missing"
    assert by_road["sr2"]["missing_mapping_count"] == 2


def test_topology_audit_checks_segment_road_original_direction_only() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), roads=["sr1"])
        ],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2, direction=2)],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 0), (10, 0)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(10, 0))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "pass"
    assert road["path_forward"] is True
    assert road["path_reverse"] is False


def test_topology_audit_uses_identity_nodes_for_retained_swsd_supplement_road() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), roads=["sr1"])
        ],
        swsd_roads=[_road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2, direction=2)],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (10, 0)]), direction=3),
            _road("sr1", "1", "2", LineString([(0, 0), (10, 0)]), source=2, direction=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(10, 0)),
            _node("1", Point(0, 0), source=2),
            _node("2", Point(10, 0), source=2),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1", "sr1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
                status="replaced+retained_swsd",
                source_values=[1, 2],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "pass"
    assert road["frcsd_node_ids"] == ["1", "2"]
    assert road["path_forward"] is True
    internal = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_internal_connectivity"
    ][0]
    assert internal["audit_status"] == "pass"
    assert internal["frcsd_node_ids"] == ["10", "1", "20", "2"]
    assert internal["path_forward"] is True


def test_topology_audit_fails_junction_when_incident_segments_diverge() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), sgrade="0-1单"),
            _segment("s2", ["2", "3"], LineString([(10, 0), (20, 0)]), sgrade="0-1单"),
        ],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (10, 0)])),
            _road("sr2", "2", "3", LineString([(20, 0), (30, 0)]), source=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(10, 0)),
            _node("2", Point(20, 0), source=2),
            _node("3", Point(30, 0), source=2),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            ),
            _relation(
                "s2",
                ["2", "3"],
                ["sr2"],
                [
                    {"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"},
                    {"swsd_node_id": "3", "frcsd_node_ids": ["3"], "mapping_status": "identity"},
                ],
                status="retained_swsd",
                source_values=[2],
            ),
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    junction = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_junction_connectivity"
        and row["properties"]["swsd_node_id"] == "2"
    ][0]
    assert junction["audit_status"] == "fail"
    assert junction["audit_reason"] == "junction_incident_segment_mapped_points_diverged"
    assert junction["max_pairwise_distance_m"] == 10.0


def test_topology_audit_accepts_junction_when_mainnode_is_closed() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), sgrade="0-1单"),
            _segment("s2", ["2", "3"], LineString([(10, 0), (20, 0)]), sgrade="0-1单"),
        ],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (10, 0)])),
            _road("sr2", "2", "3", LineString([(20, 0), (30, 0)]), source=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(10, 0), mainnodeid="20"),
            _node("2", Point(20, 0), source=2, mainnodeid="20"),
            _node("3", Point(30, 0), source=2),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            ),
            _relation(
                "s2",
                ["2", "3"],
                ["sr2"],
                [
                    {"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"},
                    {"swsd_node_id": "3", "frcsd_node_ids": ["3"], "mapping_status": "identity"},
                ],
                status="retained_swsd",
                source_values=[2],
            ),
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    junction = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_junction_connectivity"
        and row["properties"]["swsd_node_id"] == "2"
    ][0]
    assert junction["audit_status"] == "warn"
    assert junction["audit_reason"] == "junction_incident_segment_mainnode_closed_but_geometry_diverged"
    assert junction["action"] == "semantic_mainnode_closure_verified"
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_segment_junction_connectivity_fail_count"] == 0


def test_topology_audit_warns_mixed_source_junction_when_mainnode_is_not_closed() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), sgrade="0-1单"),
            _segment("s2", ["2", "3"], LineString([(10, 0), (20, 0)]), sgrade="0-1单"),
        ],
        frcsd_roads=[
            _road("r1", "10", "20", LineString([(0, 0), (10, 0)])),
            _road("sr2", "2", "3", LineString([(10, 0), (20, 0)]), source=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(10, 0), mainnodeid="20"),
            _node("2", Point(10, 0), source=2, mainnodeid="2"),
            _node("3", Point(20, 0), source=2),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            ),
            _relation(
                "s2",
                ["2", "3"],
                ["sr2"],
                [
                    {"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"},
                    {"swsd_node_id": "3", "frcsd_node_ids": ["3"], "mapping_status": "identity"},
                ],
                status="retained_swsd",
                source_values=[2],
            ),
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    junction = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_junction_connectivity"
        and row["properties"]["swsd_node_id"] == "2"
    ][0]
    assert junction["audit_status"] == "warn"
    assert junction["audit_reason"] == "junction_incident_semantic_mainnode_not_closed"
    assert junction["max_pairwise_distance_m"] == 0.0


def test_topology_audit_fails_patch_attachment_with_isolated_rcsd_node() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[],
        frcsd_nodes=[
            _node("2", Point(0, 0), source=2),
            _node("100", Point(0, 0), source=1),
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "sr1",
                    "swsd_node_id": "2",
                    "action": "split_rcsd_road_for_retained_swsd_segment",
                    "action_reason": "retained_swsd_segment_endpoint_projects_to_mid_selected_rcsd_road",
                    "rcsd_road_id": "rr1",
                    "generated_rcsd_node_id": "100",
                    "projected_gap_m": 0.0,
                    "replacement_segment_ids": ["s1"],
                },
                "geometry": Point(0, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "patch_road_attachment"][0]
    assert patch["audit_status"] == "fail"
    assert patch["audit_reason"] == "patch_attachment_rcsd_node_isolated"
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_fail_count"] == 1


def test_topology_audit_fails_final_advance_right_leaf_endpoint() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[
            _road("adv", "10", "99", LineString([(0, 0), (10, 1)]), formway=128),
            _road("main", "10", "20", LineString([(0, 0), (20, 0)])),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(20, 0)),
            _node("99", Point(10, 1)),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["adv", "main"],
                [],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    advance_rows = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "advance_right_endpoint_connectivity"
    ]
    assert [row["audit_status"] for row in advance_rows] == ["pass", "fail"]
    assert advance_rows[1]["audit_reason"] == "advance_right_leaf_endpoint_unattached"
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_advance_right_endpoint_connectivity_fail_count"] == 1


def test_topology_audit_passes_advance_right_cross_source_mainnode_attachment() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[
            _road("main", "10", "20", LineString([(0, 0), (-10, 0)])),
            _road("adv", "10", "99", LineString([(0, 0), (10, 0)]), formway=128),
            _road("sw1", "1", "sw_attach", LineString([(5, 0), (10, 0)]), source=2),
            _road("sw2", "sw_attach", "2", LineString([(10, 0), (15, 0)]), source=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(-10, 0)),
            _node("99", Point(10, 0), mainnodeid="99"),
            _node("1", Point(5, 0), source=2),
            _node("2", Point(15, 0), source=2),
            _node("sw_attach", Point(10, 0), source=2, mainnodeid="99"),
        ],
        segment_relation_rows=[_relation("s1", ["1", "2"], ["adv"], [])],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    advance_rows = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "advance_right_endpoint_connectivity"
    ]
    assert [row["audit_status"] for row in advance_rows] == ["pass", "pass"]
    assert advance_rows[1]["mapped_node_count"] == 3


def test_topology_audit_fails_patch_attachment_when_mainnode_is_not_merged() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[
            _road("rr1", "100", "101", LineString([(0, 0), (10, 0)]), source=1),
        ],
        frcsd_nodes=[
            _node("2", Point(0, 0), source=2, mainnodeid="2"),
            _node("100", Point(0, 0), source=1, mainnodeid="100"),
            _node("101", Point(10, 0), source=1, mainnodeid="101"),
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "patch1",
                    "swsd_node_id": "2",
                    "action": "split_rcsd_road_for_swsd_advance",
                    "action_reason": "advance_right_projection_mid_selected_rcsd_road",
                    "rcsd_road_id": "rr1",
                    "generated_rcsd_node_id": "100",
                    "projected_gap_m": 0.0,
                    "replacement_segment_ids": ["s1"],
                },
                "geometry": Point(0, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "patch_road_attachment"][0]
    assert patch["audit_status"] == "fail"
    assert patch["audit_reason"] == "patch_attachment_mainnode_not_merged"


def test_topology_audit_passes_split_advance_when_swsd_node_is_replaced() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[
            _road("rr1a", "100", "900", LineString([(0, 0), (5, 0)]), source=1),
            _road("rr1b", "900", "101", LineString([(5, 0), (10, 0)]), source=1),
        ],
        frcsd_nodes=[
            _node("100", Point(0, 0), source=1),
            _node("900", Point(5, 0), source=1),
            _node("101", Point(10, 0), source=1),
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "patch1",
                    "swsd_node_id": "2",
                    "action": "split_rcsd_road_for_swsd_advance",
                    "action_reason": "advance_right_projection_mid_selected_rcsd_road",
                    "rcsd_road_id": "rr1",
                    "generated_rcsd_node_id": "900",
                    "projected_gap_m": 0.0,
                    "replacement_segment_ids": ["s1"],
                },
                "geometry": Point(5, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "patch_road_attachment"][0]
    assert patch["audit_status"] == "pass"
    assert patch["audit_reason"] == "patch_attachment_connected_to_frcsd_node"


def test_topology_audit_warns_patch_attachment_when_alternate_rcsd_mainnode_is_attached() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[
            _road("rr1", "100", "101", LineString([(0, 0), (10, 0)]), source=1),
            _road("rr2", "102", "103", LineString([(0.5, 0), (10, 1)]), source=1),
        ],
        frcsd_nodes=[
            _node("2", Point(0, 0), source=2, mainnodeid="102"),
            _node("100", Point(0, 0), source=1, mainnodeid="100"),
            _node("101", Point(10, 0), source=1, mainnodeid="101"),
            _node("102", Point(0.5, 0), source=1, mainnodeid="102"),
            _node("103", Point(10, 1), source=1, mainnodeid="103"),
        ],
        segment_relation_rows=[],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "patch1",
                    "swsd_node_id": "2",
                    "action": "split_rcsd_road_for_swsd_advance",
                    "action_reason": "advance_right_projection_mid_selected_rcsd_road",
                    "rcsd_road_id": "rr1",
                    "generated_rcsd_node_id": "100",
                    "projected_gap_m": 0.0,
                    "replacement_segment_ids": ["s1"],
                },
                "geometry": Point(0, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "patch_road_attachment"][0]
    assert patch["audit_status"] == "warn"
    assert patch["audit_reason"] == "patch_attachment_merged_to_alternate_rcsd_node"


def test_topology_audit_warns_no_safe_projection_without_replacement_context() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        frcsd_roads=[],
        frcsd_nodes=[],
        segment_relation_rows=[],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "patch1",
                    "swsd_node_id": "free_end",
                    "action": "audit_no_safe_rcsd_projection",
                    "action_reason": "no_selected_rcsd_road_within_20m",
                    "replacement_segment_ids": [],
                },
                "geometry": Point(0, 0),
            },
            {
                "properties": {
                    "swsd_advance_road_id": "patch2",
                    "swsd_node_id": "replacement_end",
                    "action": "audit_no_safe_rcsd_projection",
                    "action_reason": "no_selected_rcsd_road_within_20m",
                    "replacement_segment_ids": ["s1"],
                },
                "geometry": Point(10, 0),
            },
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch_rows = {
        row["properties"]["swsd_road_id"]: row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "patch_road_attachment"
    }
    assert patch_rows["patch1"]["audit_status"] == "warn"
    assert patch_rows["patch1"]["audit_reason"] == "retained_patch_endpoint_without_replacement_context"
    assert patch_rows["patch1"]["recommended_owner"] == "upstream_swsd_baseline"
    assert patch_rows["patch2"]["audit_status"] == "fail"
    assert patch_rows["patch2"]["audit_reason"] == "patch_road_endpoint_has_no_safe_frcsd_projection"
    summary = summarize_topology_connectivity_audit(rows)
    assert summary["topology_connectivity_patch_road_attachment_warn_count"] == 1
    assert summary["topology_connectivity_patch_road_attachment_fail_count"] == 1
    assert summary["topology_connectivity_segment_internal_connectivity_fail_count"] == 0


def test_topology_audit_warns_for_strict_geometry_offset_inside_corridor() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[_segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单")],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 10), (100, 10)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 10)), _node("20", Point(100, 10))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    internal = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_internal_connectivity"][0]
    assert internal["audit_status"] == "warn"
    assert internal["audit_reason"] == "segment_strict_geometry_coverage_outside_5m"
    assert internal["uncovered_ratio"] == 1.0
    assert internal["corridor_uncovered_ratio"] == 0.0


def test_topology_audit_warns_replaced_segment_road_outside_precise_coverage() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单", roads=["sw1"])
        ],
        swsd_roads=[_road("sw1", "1", "2", LineString([(0, 0), (100, 0)]), source=2, direction=2)],
        frcsd_roads=[_road("r1", "10", "20", LineString([(0, 3), (100, 3)]), direction=2)],
        frcsd_nodes=[_node("10", Point(0, 3)), _node("20", Point(100, 3))],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            )
        ],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "segment_road_strict_geometry_coverage_outside_2m"
    assert road["coverage_buffer_m"] == 2.0
    assert road["final_path_forward"] is True


def test_topology_audit_downgrades_junction_surface_release_corridor_gap() -> None:
    base_relation = _relation(
        "s1",
        ["1", "2"],
        ["r1"],
        [
            {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
            {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
        ],
    )
    base_kwargs = {
        "swsd_segments": [
            _segment("s1", ["1", "2"], LineString([(0, 0), (100, 0)]), sgrade="0-1单", roads=["sw1"])
        ],
        "swsd_roads": [_road("sw1", "1", "2", LineString([(0, 0), (100, 0)]), source=2, direction=2)],
        "frcsd_roads": [_road("r1", "10", "20", LineString([(0, 30), (100, 30)]), direction=2)],
        "frcsd_nodes": [_node("10", Point(0, 30)), _node("20", Point(100, 30))],
        "advance_right_audit_rows": [],
        "source_field_name": "source",
        "swsd_source_value": 2,
        "rcsd_source_value": 1,
    }
    plain_rows = build_topology_connectivity_audit_rows(segment_relation_rows=[base_relation], **base_kwargs)
    plain_road = [
        row["properties"] for row in plain_rows if row["properties"]["audit_layer"] == "segment_road_connectivity"
    ][0]
    assert plain_road["audit_status"] == "fail"
    assert plain_road["audit_reason"] == "segment_road_corridor_coverage_dropped_after_replacement"

    relation = _relation(
        "s1",
        ["1", "2"],
        ["r1"],
        [
            {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
            {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
        ],
    )
    relation["properties"]["risk_flags"] = ["junction_surface_coverage_release"]

    rows = build_topology_connectivity_audit_rows(
        segment_relation_rows=[relation],
        **base_kwargs,
    )

    road = [row["properties"] for row in rows if row["properties"]["audit_layer"] == "segment_road_connectivity"][0]
    assert road["audit_status"] == "warn"
    assert road["audit_reason"] == "segment_road_corridor_coverage_inside_junction_surface_review"
    assert road["action"] == "manual_review_required"


def test_topology_audit_prefers_attachment_node_for_junction_connectivity() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[
            _segment("s1", ["1", "2"], LineString([(0, 0), (10, 0)]), sgrade="0-1单"),
            _segment("s2", ["2", "3"], LineString([(10, 0), (20, 0)]), sgrade="0-1单"),
        ],
        frcsd_roads=[
            _road("r1a", "10", "100", LineString([(0, 0), (10, 0)])),
            _road("r1b", "100", "20", LineString([(10, 0), (30, 0)])),
            _road("sr2", "2", "3", LineString([(10, 0), (20, 0)]), source=2),
        ],
        frcsd_nodes=[
            _node("10", Point(0, 0)),
            _node("20", Point(30, 0)),
            _node("100", Point(10, 0)),
            _node("2", Point(10, 0), source=2),
            _node("3", Point(20, 0), source=2),
        ],
        segment_relation_rows=[
            _relation(
                "s1",
                ["1", "2"],
                ["r1a", "r1b"],
                [
                    {"swsd_node_id": "1", "frcsd_node_ids": ["10"], "mapping_status": "mapped"},
                    {"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"},
                ],
            ),
            _relation(
                "s2",
                ["2", "3"],
                ["sr2"],
                [
                    {"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"},
                    {"swsd_node_id": "3", "frcsd_node_ids": ["3"], "mapping_status": "identity"},
                ],
                status="retained_swsd",
                source_values=[2],
            ),
        ],
        advance_right_audit_rows=[
            {
                "properties": {
                    "swsd_advance_road_id": "sr2",
                    "swsd_node_id": "2",
                    "action": "split_rcsd_road_for_retained_swsd_segment",
                    "action_reason": "retained_swsd_segment_endpoint_projects_to_mid_selected_rcsd_road",
                    "rcsd_road_id": "r1a",
                    "generated_rcsd_node_id": "100",
                    "projected_gap_m": 0.0,
                    "replacement_segment_ids": ["s1", "s2"],
                },
                "geometry": Point(10, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    junction = [
        row["properties"]
        for row in rows
        if row["properties"]["audit_layer"] == "segment_junction_connectivity"
        and row["properties"]["swsd_node_id"] == "2"
    ][0]
    assert junction["audit_status"] == "pass"
    assert junction["frcsd_node_ids"] == ["100"]
