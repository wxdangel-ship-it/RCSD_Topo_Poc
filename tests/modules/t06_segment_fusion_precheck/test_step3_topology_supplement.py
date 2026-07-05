from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_supplement import (
    FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON,
    TOPOLOGY_SUPPLEMENT_SPLIT_REASON,
    exclude_retained_swsd_carriers_from_formal_replacements,
    materialize_topology_supplement_rcsd_roads,
)


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": 2, "source": 2},
        "geometry": LineString(coords),
    }


def _node(node_id: str, x: float, y: float = 0.0) -> dict:
    return {"properties": {"id": node_id, "mainnodeid": node_id, "source": 1}, "geometry": Point(x, y)}


def _attachment_row(road_id: str, swsd_node_id: str, rcsd_node_id: str, segment_ids: list[str] | None = None) -> dict:
    return {
        "properties": {
            "action": "reuse_generated_rcsd_node_for_retained_swsd_segment",
            "swsd_advance_road_id": road_id,
            "swsd_node_id": swsd_node_id,
            "generated_rcsd_node_id": rcsd_node_id,
            "replacement_segment_ids": segment_ids or [],
        },
        "geometry": Point(0, 0),
    }


def test_materialize_topology_supplement_keeps_detached_carrier() -> None:
    swsd_road_by_id = {
        "sw_topo": _road("sw_topo", "a", "b", [(0, 0), (10, 0)]),
        "sw_detached": _road("sw_detached", "d1", "d2", [(0, 1), (10, 1)]),
    }
    swsd_road_by_id["sw_topo"]["properties"]["formway"] = 128
    rcsd_nodes = [_node("10", 0.25), _node("20", 9.75)]
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    rcsd_roads: list[dict] = []
    rcsd_road_by_id: dict[str, dict] = {}
    added_road_to_segments: dict[str, list[str]] = {}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=["sw_topo", "sw_detached"],
        detached_junc_nodes=["d1"],
        swsd_road_ids=["sw_removed"],
        rcsd_road_ids=["rr_seed"],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        attachment_audit_rows=[
            _attachment_row("sw_topo", "a", "10"),
            _attachment_row("sw_topo", "b", "20"),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["candidate_road_count"] == 1
    assert stats["materialized_road_count"] == 1
    assert stats["detached_carrier_preserved_count"] == 1
    assert unit.retained_detached_swsd_road_ids == ["sw_detached"]
    assert unit.swsd_road_ids == ["sw_removed", "sw_topo"]
    generated_id = "sw_topo__t06toposupp_1"
    assert unit.rcsd_road_ids == ["rr_seed"]
    assert added_road_to_segments[generated_id] == ["s1"]
    generated = rcsd_road_by_id[generated_id]
    assert generated["properties"]["source"] == 1
    assert generated["properties"]["snodeid"] == "10"
    assert generated["properties"]["enodeid"] == "20"
    assert generated["properties"]["source_road_id"] == "sw_topo"
    assert generated["properties"]["t06_split_reason"] == TOPOLOGY_SUPPLEMENT_SPLIT_REASON
    assert list(generated["geometry"].coords)[0][:2] == (0.25, 0.0)
    assert list(generated["geometry"].coords)[-1][:2] == (9.75, 0.0)


def test_materialize_restores_covered_formal_body_from_retained_scope() -> None:
    retained_body = _road("body", "a", "d", [(0, 0), (100, 0)])
    retained_body["properties"]["segmentid"] = "s1"
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 1), (100, 1)]),
    }
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=["body"],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        rcsd_road_ids=["rr"],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id={"body": retained_body},
        swsd_node_by_id={},
        rcsd_roads=[],
        rcsd_nodes=[],
        rcsd_road_by_id={"rr": rcsd_road},
        rcsd_node_by_id={},
        attachment_audit_rows=[],
        added_road_to_segments={"rr": ["s1"]},
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["formal_body_retained_restored_count"] == 1
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.swsd_road_ids == ["body"]


def test_materialize_topology_supplement_preserves_non_advance_carrier() -> None:
    swsd_road_by_id = {"sw_regular": _road("sw_regular", "a", "b", [(0, 0), (10, 0)])}
    rcsd_nodes = [_node("10", 0.25), _node("20", 9.75)]
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=["sw_regular"],
        detached_junc_nodes=[],
        swsd_road_ids=["sw_regular"],
        rcsd_road_ids=[],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[],
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id={},
        rcsd_node_by_id=rcsd_node_by_id,
        attachment_audit_rows=[
            _attachment_row("sw_regular", "a", "10"),
            _attachment_row("sw_regular", "b", "20"),
        ],
        added_road_to_segments={},
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["candidate_road_count"] == 0
    assert stats["materialized_road_count"] == 0
    assert stats["non_advance_carrier_preserved_count"] == 1
    assert unit.retained_detached_swsd_road_ids == ["sw_regular"]
    assert unit.swsd_road_ids == []


def test_materialize_retained_advance_carrier_from_attachment_audit() -> None:
    carrier = _road("sw_adv", "a", "b", [(0, 0), (10, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_nodes = [_node("10", 0.5), _node("20", 9.5)]
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    rcsd_roads: list[dict] = []
    rcsd_road_by_id: dict[str, dict] = {}
    added_road_to_segments: dict[str, list[str]] = {}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        attachment_audit_rows=[
            _attachment_row("sw_adv", "a", "10", ["s1"]),
            _attachment_row("sw_adv", "b", "20", ["s1", "outside"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    generated_id = "sw_adv__t06toposupp_1"
    assert stats["candidate_road_count"] == 1
    assert stats["materialized_road_count"] == 1
    assert unit.rcsd_road_ids == []
    assert unit.swsd_road_ids == ["sw_adv"]
    assert added_road_to_segments[generated_id] == ["s1"]
    generated = rcsd_road_by_id[generated_id]
    assert generated["properties"]["source"] == 1
    assert generated["properties"]["formway"] == 128
    assert generated["properties"]["snodeid"] == "10"
    assert generated["properties"]["enodeid"] == "20"
    assert generated["properties"]["source_road_id"] == "sw_adv"


def test_materialize_retained_advance_reuses_existing_rcsd_advance_without_duplicate() -> None:
    carrier = _road("sw_adv", "a", "b", [(0, 0), (10, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(0, 0), (9, 0)]),
    }
    added_road_to_segments: dict[str, list[str]] = {}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=[],
        rcsd_road_by_id={"rr_adv": rcsd_road},
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "a", "10", ["s1"]),
            _attachment_row("sw_adv", "b", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 1
    assert unit.swsd_road_ids == ["sw_adv"]
    assert unit.rcsd_road_ids == ["rr_adv"]
    assert added_road_to_segments == {"rr_adv": ["s1"]}


def test_materialize_mixed_advance_keeps_swsd_carrier_when_rcsd_only_partially_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_repl": _road("sw_repl", "a", "b", [(0, 0), (10, 0)]),
        "sw_ret": _road("sw_ret", "c", "d", [(20, 0), (30, 0)]),
        "sw_adv": carrier,
    }
    swsd_road_by_id["sw_repl"]["properties"]["segmentid"] = "s1"
    swsd_road_by_id["sw_ret"]["properties"]["segmentid"] = "s_ret"
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=[],
        rcsd_road_by_id={"rr_adv": rcsd_road},
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 1
    assert stats["mixed_advance_right_externalized_count"] == 1
    assert unit.swsd_road_ids == []
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.rcsd_road_ids == ["rr_adv"]
    assert carrier["properties"]["t06_mixed_advance_right_carrier"] == 1
    assert added_road_to_segments == {"rr_adv": ["s1"]}


def test_materialize_mixed_advance_splits_retained_swsd_side_at_rcsd_boundary() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_repl": _road("sw_repl", "a", "b", [(0, 0), (10, 0)]),
        "sw_ret": _road("sw_ret", "c", "d", [(20, 0), (30, 0)]),
        "sw_adv": carrier,
    }
    swsd_road_by_id["sw_repl"]["properties"]["segmentid"] = "s1"
    swsd_road_by_id["sw_ret"]["properties"]["segmentid"] = "s_ret"
    rcsd_nodes = [_node("10", 10, 0.5), _node("14", 14, 0.5), _node("22", 22, 0.5)]
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "14", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    retained_side_rcsd_road = {
        "properties": {"id": "rr_retained_side", "snodeid": "14", "enodeid": "22", "source": 1, "formway": 128},
        "geometry": LineString([(14, 0.5), (22, 0.5)]),
    }
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[rcsd_road, retained_side_rcsd_road],
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id={"rr_adv": rcsd_road, "rr_retained_side": retained_side_rcsd_road},
        rcsd_node_by_id=rcsd_node_by_id,
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "14", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["mixed_advance_right_boundary_split_count"] == 1
    assert stats["mixed_advance_right_retained_side_rcsd_excluded_count"] == 1
    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 1
    assert unit.swsd_road_ids == []
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.rcsd_road_ids == ["rr_adv"]
    assert carrier["properties"]["snodeid"] == "14"
    assert carrier["properties"]["enodeid"] == "c"
    assert carrier["properties"]["t06_mixed_advance_right_split_reason"] == "mixed_advance_right_retained_swsd_side"
    assert carrier["properties"]["t06_mixed_advance_right_rcsd_road_ids"] == ["rr_adv"]
    assert carrier["properties"]["t06_mixed_advance_right_excluded_rcsd_road_ids"] == ["rr_retained_side"]
    assert list(carrier["geometry"].coords)[0][:2] == (14.0, 0.5)
    assert list(carrier["geometry"].coords)[-1][:2] == (20.0, 0.0)
    assert added_road_to_segments == {"rr_adv": ["s1"]}


def test_materialize_attachment_advance_keeps_swsd_carrier_when_rcsd_only_partially_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=[],
        rcsd_road_by_id={"rr_adv": rcsd_road},
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 1
    assert stats["mixed_advance_right_externalized_count"] == 1
    assert unit.swsd_road_ids == []
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.rcsd_road_ids == ["rr_adv"]
    assert carrier["properties"]["t06_mixed_advance_right_carrier"] == 1
    assert added_road_to_segments == {"rr_adv": ["s1"]}


def test_materialize_attachment_advance_uses_rcsd_group_when_all_incident_segments_replaced() -> None:
    carrier = _road("sw_adv", "b", "c", [(0, 0), (100, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_left": _road("sw_left", "a", "b", [(-10, 0), (0, 0)]),
        "sw_adv": carrier,
        "sw_right": _road("sw_right", "c", "d", [(100, 0), (110, 0)]),
    }
    swsd_road_by_id["sw_left"]["properties"]["segmentid"] = "s_left"
    swsd_road_by_id["sw_right"]["properties"]["segmentid"] = "s_right"
    rcsd_roads = [
        {
            "properties": {"id": "rr_adv_1", "snodeid": "10", "enodeid": "11", "source": 1, "formway": 128},
            "geometry": LineString([(0, 0.5), (25, 0.5)]),
        },
        {
            "properties": {"id": "rr_adv_2", "snodeid": "11", "enodeid": "12", "source": 1, "formway": 128},
            "geometry": LineString([(25, 0.5), (50, 0.5)]),
        },
        {
            "properties": {"id": "rr_adv_3", "snodeid": "12", "enodeid": "20", "source": 1, "formway": 128},
            "geometry": LineString([(50, 0.5), (54, 0.5), (54, 20)]),
        },
    ]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    left_unit = SimpleNamespace(
        segment_id="s_left",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    right_unit = SimpleNamespace(
        segment_id="s_right",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [left_unit, right_unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=[],
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s_left", "s_right"]),
            _attachment_row("sw_adv", "c", "20", ["s_left", "s_right"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 3
    assert left_unit.swsd_road_ids == ["sw_adv"]
    assert right_unit.swsd_road_ids == ["sw_adv"]
    assert left_unit.retained_detached_swsd_road_ids == []
    assert right_unit.retained_detached_swsd_road_ids == []
    assert left_unit.rcsd_road_ids == ["rr_adv_1", "rr_adv_2", "rr_adv_3"]
    assert right_unit.rcsd_road_ids == ["rr_adv_1", "rr_adv_2", "rr_adv_3"]
    assert "t06_mixed_advance_right_carrier" not in carrier["properties"]
    assert added_road_to_segments == {
        "rr_adv_1": ["s_left", "s_right"],
        "rr_adv_2": ["s_left", "s_right"],
        "rr_adv_3": ["s_left", "s_right"],
    }


def test_materialize_mixed_advance_uses_rcsd_when_existing_corridor_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_repl": _road("sw_repl", "a", "b", [(0, 0), (10, 0)]),
        "sw_ret": _road("sw_ret", "c", "d", [(20, 0), (30, 0)]),
        "sw_adv": carrier,
    }
    swsd_road_by_id["sw_repl"]["properties"]["segmentid"] = "s1"
    swsd_road_by_id["sw_ret"]["properties"]["segmentid"] = "s_ret"
    rcsd_roads = [
        {
            "properties": {"id": "rr_adv_1", "snodeid": "10", "enodeid": "11", "source": 1, "formway": 128},
            "geometry": LineString([(10, 0.5), (15, 0.5)]),
        },
        {
            "properties": {"id": "rr_adv_2", "snodeid": "11", "enodeid": "20", "source": 1, "formway": 128},
            "geometry": LineString([(15, 0.5), (20, 0.5)]),
        },
    ]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=[],
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 2
    assert unit.swsd_road_ids == ["sw_adv"]
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.rcsd_road_ids == ["rr_adv_1", "rr_adv_2"]
    assert "t06_mixed_advance_right_carrier" not in carrier["properties"]
    assert added_road_to_segments == {"rr_adv_1": ["s1"], "rr_adv_2": ["s1"]}


def test_materialize_recovers_removed_undercovered_mixed_advance_carrier() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=["sw_adv"],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=[],
        rcsd_road_by_id={"rr_adv": rcsd_road},
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["recovered_undercovered_mixed_advance_right_count"] == 1
    assert stats["reused_existing_rcsd_advance_count"] == 1
    assert stats["mixed_advance_right_externalized_count"] == 1
    assert unit.swsd_road_ids == []
    assert unit.retained_detached_swsd_road_ids == []
    assert unit.rcsd_road_ids == ["rr_adv"]
    assert carrier["properties"]["t06_mixed_advance_right_carrier"] == 1
    assert added_road_to_segments == {"rr_adv": ["s1"]}


def test_materialize_does_not_recover_removed_advance_when_rcsd_corridor_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_roads = [
        {
            "properties": {"id": "rr_adv_1", "snodeid": "10", "enodeid": "11", "source": 1, "formway": 128},
            "geometry": LineString([(10, 0.5), (15, 0.5)]),
        },
        {
            "properties": {"id": "rr_adv_2", "snodeid": "11", "enodeid": "20", "source": 1, "formway": 128},
            "geometry": LineString([(15, 0.5), (20, 0.5)]),
        },
    ]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=["sw_adv"],
        rcsd_road_ids=[],
    )
    added_road_to_segments: dict[str, list[str]] = {}

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=[],
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "b", "10", ["s1"]),
            _attachment_row("sw_adv", "c", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["recovered_undercovered_mixed_advance_right_count"] == 0
    assert unit.swsd_road_ids == ["sw_adv"]
    assert unit.retained_detached_swsd_road_ids == []
    assert "t06_mixed_advance_right_carrier" not in carrier["properties"]
    assert added_road_to_segments == {}


def test_materialize_retained_advance_reuses_existing_rcsd_advance_corridor_without_duplicate() -> None:
    carrier = _road("sw_adv", "a", "b", [(0, 0), (50, 0), (100, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_roads = [
        {
            "properties": {"id": "rr_adv_1", "snodeid": "10", "enodeid": "11", "source": 1, "formway": 128},
            "geometry": LineString([(0, 4), (50, 4)]),
        },
        {
            "properties": {"id": "rr_adv_2", "snodeid": "11", "enodeid": "20", "source": 1, "formway": 128},
            "geometry": LineString([(50, 4), (100, 4)]),
        },
    ]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    added_road_to_segments: dict[str, list[str]] = {}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        rcsd_road_ids=[],
    )

    stats = materialize_topology_supplement_rcsd_roads(
        [unit],
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id={},
        rcsd_roads=rcsd_roads,
        rcsd_nodes=[],
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id={},
        attachment_audit_rows=[
            _attachment_row("sw_adv", "a", "10", ["s1"]),
            _attachment_row("sw_adv", "b", "20", ["s1"]),
        ],
        added_road_to_segments=added_road_to_segments,
        source_field_name="source",
        rcsd_source_value=1,
        retained_swsd_roads=[carrier],
    )

    assert stats["materialized_road_count"] == 0
    assert stats["reused_existing_rcsd_advance_count"] == 2
    assert unit.swsd_road_ids == ["sw_adv"]
    assert unit.rcsd_road_ids == ["rr_adv_1", "rr_adv_2"]
    assert "sw_adv__t06toposupp_1" not in rcsd_road_by_id
    assert added_road_to_segments == {"rr_adv_1": ["s1"], "rr_adv_2": ["s1"]}


def test_duplicate_advance_exclusion_skips_mixed_swsd_carrier_when_rcsd_only_partially_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_repl": _road("sw_repl", "a", "b", [(0, 0), (10, 0)]),
        "sw_ret": _road("sw_ret", "c", "d", [(20, 0), (30, 0)]),
        "sw_adv": carrier,
    }
    swsd_road_by_id["sw_repl"]["properties"]["segmentid"] = "s1"
    swsd_road_by_id["sw_ret"]["properties"]["segmentid"] = "s_ret"
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=[],
        rcsd_road_ids=["rr_adv"],
    )

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments={"rr_adv": ["s1"]},
        removed_road_to_segments={},
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id={"rr_adv": rcsd_road},
    )

    assert stats["extra_removed_road_to_segments"] == {}
    assert carrier["properties"]["t06_mixed_advance_right_carrier"] == 1


def test_duplicate_advance_exclusion_skips_marked_swsd_carrier_when_rcsd_only_partially_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    carrier["properties"]["t06_mixed_advance_right_carrier"] = 1
    swsd_road_by_id = {"sw_adv": carrier}
    rcsd_road = {
        "properties": {"id": "rr_adv", "snodeid": "10", "enodeid": "20", "source": 1, "formway": 128},
        "geometry": LineString([(10, 0.5), (14, 0.5)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["sw_adv"],
        rcsd_road_ids=["rr_adv"],
    )

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments={"rr_adv": ["s1"]},
        removed_road_to_segments={},
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id={"rr_adv": rcsd_road},
    )

    assert stats["extra_removed_road_to_segments"] == {}


def test_duplicate_advance_exclusion_removes_mixed_swsd_carrier_when_rcsd_corridor_covers() -> None:
    carrier = _road("sw_adv", "b", "c", [(10, 0), (20, 0)])
    carrier["properties"]["formway"] = 128
    swsd_road_by_id = {
        "sw_repl": _road("sw_repl", "a", "b", [(0, 0), (10, 0)]),
        "sw_ret": _road("sw_ret", "c", "d", [(20, 0), (30, 0)]),
        "sw_adv": carrier,
    }
    swsd_road_by_id["sw_repl"]["properties"]["segmentid"] = "s1"
    swsd_road_by_id["sw_ret"]["properties"]["segmentid"] = "s_ret"
    rcsd_roads = {
        "rr_adv_1": {
            "properties": {"id": "rr_adv_1", "snodeid": "10", "enodeid": "11", "source": 1, "formway": 128},
            "geometry": LineString([(10, 0.5), (15, 0.5)]),
        },
        "rr_adv_2": {
            "properties": {"id": "rr_adv_2", "snodeid": "11", "enodeid": "20", "source": 1, "formway": 128},
            "geometry": LineString([(15, 0.5), (20, 0.5)]),
        },
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=[],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=[],
        rcsd_road_ids=["rr_adv_1", "rr_adv_2"],
    )

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments={"rr_adv_1": ["s1"], "rr_adv_2": ["s1"]},
        removed_road_to_segments={},
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id=rcsd_roads,
    )

    assert stats["extra_removed_road_to_segments"] == {"sw_adv": ["t06_duplicate_unsegmented_advance_right"]}
    assert "t06_mixed_advance_right_carrier" not in carrier["properties"]


def test_exclude_retained_body_carrier_records_formal_corridor_review_risk() -> None:
    retained_body = _road("body", "a", "d", [(0, 0), (100, 0)])
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 100), (100, 100)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["body"],
        rcsd_road_ids=["rr"],
    )
    added_road_to_segments = {"rr": ["s1"]}

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments={},
        swsd_road_by_id={"body": retained_body},
        rcsd_road_by_id={"rr": rcsd_road},
    )

    assert stats["deactivated_segment_count"] == 0
    assert stats["corridor_unavailable_segment_count"] == 1
    assert unit.status == "passed"
    assert unit.reason == ""
    assert FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON in unit.risk_flags
    assert "formal_replacement_corridor_coverage_review" in unit.risk_flags
    assert "manual_review_required" in unit.risk_flags
    assert added_road_to_segments == {"rr": ["s1"]}


def test_surface_aware_release_allows_wide_formal_body_corridor() -> None:
    retained_body = _road("body", "a", "d", [(0, 0), (100, 0)])
    retained_body["properties"]["segmentid"] = "s1"
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 50), (100, 50)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["body"],
        rcsd_road_ids=["rr"],
        risk_flags=[
            "junction_alignment_to_retained_swsd_exceeds_topology_gate",
            "junction_alignment_surface_audit_release",
        ],
    )
    added_road_to_segments = {"rr": ["s1"]}

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments={},
        swsd_road_by_id={"body": retained_body},
        rcsd_road_by_id={"rr": rcsd_road},
    )

    assert stats["deactivated_segment_count"] == 0
    assert unit.status == "passed"
    assert "surface_aware_formal_corridor_release" in unit.risk_flags
    assert "manual_review_required" in unit.risk_flags
    assert added_road_to_segments == {"rr": ["s1"]}


def test_relation_release_allows_wide_formal_body_corridor() -> None:
    retained_body = _road("body", "a", "d", [(0, 0), (100, 0)])
    retained_body["properties"]["segmentid"] = "s1"
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 50), (100, 50)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["body"],
        rcsd_road_ids=["rr"],
        risk_flags=[
            "junction_alignment_to_retained_swsd_exceeds_topology_gate",
            "junction_alignment_t05_relation_release",
        ],
    )
    added_road_to_segments = {"rr": ["s1"]}

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments={},
        swsd_road_by_id={"body": retained_body},
        rcsd_road_by_id={"rr": rcsd_road},
    )

    assert stats["deactivated_segment_count"] == 0
    assert unit.status == "passed"
    assert "surface_aware_formal_corridor_release" in unit.risk_flags
    assert "manual_review_required" in unit.risk_flags
    assert added_road_to_segments == {"rr": ["s1"]}


def test_wide_formal_body_corridor_records_review_risk_without_surface_release() -> None:
    retained_body = _road("body", "a", "d", [(0, 0), (100, 0)])
    retained_body["properties"]["segmentid"] = "s1"
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 50), (100, 50)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["body"],
        rcsd_road_ids=["rr"],
        risk_flags=[],
    )
    added_road_to_segments = {"rr": ["s1"]}

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments={},
        swsd_road_by_id={"body": retained_body},
        rcsd_road_by_id={"rr": rcsd_road},
    )

    assert stats["deactivated_segment_count"] == 0
    assert stats["corridor_unavailable_segment_count"] == 1
    assert unit.status == "passed"
    assert unit.reason == ""
    assert FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON in unit.risk_flags
    assert "formal_replacement_corridor_coverage_review" in unit.risk_flags
    assert "manual_review_required" in unit.risk_flags
    assert added_road_to_segments == {"rr": ["s1"]}


def test_exclude_retained_carrier_allows_side_attachment_merge() -> None:
    retained_side = _road("side", "a", "d", [(0, 0), (100, 0)])
    retained_side["properties"]["segment_build_source"] = "side_attachment_merge"
    rcsd_road = {
        "properties": {"id": "rr", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 100), (100, 100)]),
    }
    unit = SimpleNamespace(
        status="passed",
        reason="",
        segment_id="s1",
        pair_nodes=["a", "b"],
        junc_nodes=[],
        detached_junc_nodes=["d"],
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=["side"],
        rcsd_road_ids=["rr"],
    )
    added_road_to_segments = {"rr": ["s1"]}

    stats = exclude_retained_swsd_carriers_from_formal_replacements(
        [unit],
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments={},
        swsd_road_by_id={"side": retained_side},
        rcsd_road_by_id={"rr": rcsd_road},
    )

    assert stats["deactivated_segment_count"] == 0
    assert unit.status == "passed"
    assert added_road_to_segments == {"rr": ["s1"]}
