from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_supplement import (
    TOPOLOGY_SUPPLEMENT_SPLIT_REASON,
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


def test_materialize_topology_supplement_preserves_non_advance_carrier() -> None:
    swsd_road_by_id = {"sw_regular": _road("sw_regular", "a", "b", [(0, 0), (10, 0)])}
    rcsd_nodes = [_node("10", 0.25), _node("20", 9.75)]
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    unit = SimpleNamespace(
        segment_id="s1",
        retained_detached_swsd_road_ids=["sw_regular"],
        detached_junc_nodes=[],
        swsd_road_ids=[],
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
