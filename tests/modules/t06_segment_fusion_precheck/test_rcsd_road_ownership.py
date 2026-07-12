from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_road_ownership import (
    build_and_write_rcsd_road_ownership,
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
        feature({"swsd_segment_id": "left_segment"}, None),
        feature({"swsd_segment_id": "right_segment"}, None),
    ]
    sync_segment_relation_ownership_fields(
        relation_rows,
        ownership_rows=outputs.ownership_rows,
        connectivity_group_rows=outputs.connectivity_group_rows,
    )
    left = relation_rows[0]["properties"]
    assert left["owned_frcsd_road_ids"] == ["selected"]
    assert left["connectivity_group_ids"]
    assert left["related_connectivity_road_ids"] == ["bridge"]
