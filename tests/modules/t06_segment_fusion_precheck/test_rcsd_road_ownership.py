from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_road_ownership import (
    _second_degree_connectivity_road_ids,
    build_and_write_rcsd_road_ownership,
    reconcile_final_road_segment_assignments,
    sync_segment_relation_ownership_fields,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    coords: list[tuple[float, float]],
    *,
    formway: int = 0,
    source: int | None = None,
) -> dict:
    props = {
        "id": road_id,
        "snodeid": snodeid,
        "enodeid": enodeid,
        "formway": formway,
    }
    if source is not None:
        props["source"] = source
    return feature(props, LineString(coords))


def _segment(segment_id: str, coords: list[tuple[float, float]], *, segment_type: str = "normal") -> dict:
    return feature(
        {
            "id": segment_id,
            "segment_type": segment_type,
            "pair_nodes": "" if segment_type == "advance_right" else "1,2",
            "junc_nodes": "",
            "roads": "",
        },
        LineString(coords),
    )


def test_second_degree_connectivity_road_ids_use_published_group_closure() -> None:
    rows = [
        feature(
            {
                "connectivity_kind": "second_degree_bridge",
                "rcsd_road_ids": ["bridge", "direct_context"],
            },
            None,
        ),
        feature(
            {
                "connectivity_kind": "other_reviewed",
                "rcsd_road_ids": ["review_only"],
            },
            None,
        ),
    ]
    assert _second_degree_connectivity_road_ids(rows) == {"bridge", "direct_context"}


def test_ownership_is_unique_and_connectivity_does_not_count_as_segment_replacement(tmp_path) -> None:
    rcsd_roads = [
        _road("selected", "1", "2", [(0, 0), (10, 0)]),
        _road("bridge", "2", "3", [(10, 0), (20, 0)]),
        _road("right", "3", "4", [(20, 0), (30, 0)]),
        _road("advance", "5", "6", [(0, 20), (10, 20)], formway=128),
        _road("reality", "7", "8", [(1000, 1000), (1010, 1000)]),
    ]
    frcsd_roads = [
        _road("selected", "1", "2", [(0, 0), (10, 0)], source=1),
        _road("bridge", "2", "3", [(10, 0), (20, 0)], source=1),
        _road("right", "3", "4", [(20, 0), (30, 0)], source=1),
        _road("advance", "5", "6", [(0, 20), (10, 20)], formway=128, source=1),
    ]
    segments = [
        _segment("left_segment", [(0, 0), (10, 0)]),
        _segment("right_segment", [(20, 0), (30, 0)]),
        _segment("advance_segment", [(0, 20), (10, 20)], segment_type="advance_right"),
    ]
    added = {
        "selected": ["left_segment"],
        "bridge": ["left_segment", "right_segment"],
        "right": ["right_segment"],
        "advance": ["left_segment"],
    }

    outputs = build_and_write_rcsd_road_ownership(
        step_root=tmp_path,
        rcsd_roads=rcsd_roads,
        frcsd_roads=frcsd_roads,
        swsd_segments=segments,
        added_road_to_segments=added,
        connectivity_supplement_road_ids={"bridge"},
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        source_field_name="source",
        rcsd_source_value=1,
    )

    by_id = {
        row["properties"]["rcsd_road_id"]: row["properties"]
        for row in outputs.ownership_rows
    }
    assert len(by_id) == len(rcsd_roads)
    assert by_id["selected"]["owner_segment_id"] == "left_segment"
    assert by_id["bridge"]["owner_type"] == "multi_segment_connectivity"
    assert by_id["bridge"]["replacement_action"] == "include_connectivity"
    assert by_id["bridge"]["count_in_rcsd_road_metric"] is True
    assert by_id["bridge"]["count_in_segment_metric"] is False
    assert by_id["advance"]["owner_segment_id"] == "advance_segment"
    assert by_id["advance"]["owner_segment_type"] == "advance_right"
    assert by_id["advance"]["count_in_segment_metric"] is False
    assert by_id["reality"]["owner_type"] == "reality_change"
    assert outputs.summary["ownership_duplicate_count"] == 0
    assert outputs.summary["ownership_missing_count"] == 0
    assert outputs.summary["connectivity_group_count"] == 1
    assert outputs.ownership_paths["gpkg"].exists()
    assert outputs.connectivity_group_paths["csv"].exists()

    relation_rows = [
        feature({"swsd_segment_id": "left_segment", "frcsd_road_ids": ["selected", "bridge"]}, None),
        feature({"swsd_segment_id": "right_segment", "frcsd_road_ids": ["right", "bridge"]}, None),
    ]
    sync_segment_relation_ownership_fields(
        relation_rows,
        ownership_rows=outputs.ownership_rows,
        connectivity_group_rows=outputs.connectivity_group_rows,
    )
    left = relation_rows[0]["properties"]
    assert left["owned_frcsd_road_ids"] == ["selected"]
    assert left["frcsd_road_ids"] == ["selected"]
    assert left["connectivity_group_ids"]
    assert left["related_connectivity_road_ids"] == ["bridge"]

    assignment_stats = reconcile_final_road_segment_assignments(
        frcsd_roads=frcsd_roads,
        added_road_to_segments=added,
        ownership_rows=outputs.ownership_rows,
        source_field_name="source",
        rcsd_source_value=1,
    )
    final_by_id = {road["properties"]["id"]: road["properties"] for road in frcsd_roads}
    assert final_by_id["selected"]["t06_swsd_segment_ids"] == ["left_segment"]
    assert final_by_id["right"]["t06_swsd_segment_ids"] == ["right_segment"]
    assert final_by_id["bridge"]["t06_swsd_segment_ids"] == []
    assert final_by_id["advance"]["t06_swsd_segment_ids"] == ["advance_segment"]
    assert assignment_stats["final_rcsd_road_multi_segment_assignment_count"] == 0


def test_special_junction_internal_road_has_no_segment_owner_or_relation_carrier(tmp_path) -> None:
    rcsd_roads = [_road("internal", "j1a", "j1b", [(0, 0), (5, 5)])]
    frcsd_roads = [_road("internal", "j1a", "j1b", [(0, 0), (5, 5)], source=1)]
    segments = [
        _segment("left_segment", [(-10, 0), (0, 0)]),
        _segment("right_segment", [(5, 5), (15, 5)]),
    ]
    added = {"internal": ["left_segment", "right_segment"]}

    outputs = build_and_write_rcsd_road_ownership(
        step_root=tmp_path,
        rcsd_roads=rcsd_roads,
        frcsd_roads=frcsd_roads,
        swsd_segments=segments,
        added_road_to_segments=added,
        connectivity_supplement_road_ids=set(),
        special_junction_ids_by_road={"internal": ["junction_1"]},
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        source_field_name="source",
        rcsd_source_value=1,
    )

    ownership = outputs.ownership_rows[0]["properties"]
    assert ownership["owner_type"] == "special_junction_internal"
    assert ownership["owner_segment_id"] == ""
    assert ownership["special_junction_ids"] == ["junction_1"]
    assert ownership["related_segment_ids"] == ["left_segment", "right_segment"]
    assert ownership["count_in_segment_metric"] is False

    relation_rows = [
        feature({"swsd_segment_id": "left_segment", "frcsd_road_ids": ["internal"]}, None),
        feature({"swsd_segment_id": "right_segment", "frcsd_road_ids": ["internal"]}, None),
    ]
    sync_segment_relation_ownership_fields(
        relation_rows,
        ownership_rows=outputs.ownership_rows,
        connectivity_group_rows=outputs.connectivity_group_rows,
    )
    for row in relation_rows:
        props = row["properties"]
        assert props["frcsd_road_ids"] == []
        assert props["owned_frcsd_road_ids"] == []
        assert props["related_special_junction_internal_road_ids"] == ["internal"]

    stats = reconcile_final_road_segment_assignments(
        frcsd_roads=frcsd_roads,
        added_road_to_segments=added,
        ownership_rows=outputs.ownership_rows,
        source_field_name="source",
        rcsd_source_value=1,
    )
    assert frcsd_roads[0]["properties"]["t06_swsd_segment_ids"] == []
    assert added["internal"] == []
    assert stats["final_rcsd_road_unassigned_count"] == 1


def test_final_assignment_rejects_unresolved_multi_segment_provenance() -> None:
    frcsd_roads = [_road("unresolved", "1", "2", [(0, 0), (10, 0)], source=1)]
    frcsd_roads[0]["properties"]["t06_swsd_segment_ids"] = ["left", "right"]

    try:
        reconcile_final_road_segment_assignments(
            frcsd_roads=frcsd_roads,
            added_road_to_segments={"unresolved": ["left", "right"]},
            ownership_rows=[],
            source_field_name="source",
            rcsd_source_value=1,
        )
    except ValueError as exc:
        assert "multi-Segment" in str(exc)
    else:
        raise AssertionError("unresolved multi-Segment final Road must fail")
