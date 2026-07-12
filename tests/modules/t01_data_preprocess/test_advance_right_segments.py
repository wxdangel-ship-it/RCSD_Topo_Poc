from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.advance_right_segments import (
    ADVANCE_RIGHT_SEGMENT_TYPE,
    assign_advance_right_segments,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import load_vector_feature_collection
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    NodeFeatureRecord,
    RoadFeatureRecord,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step6_segment_aggregation import (
    run_step6_segment_aggregation_from_records,
)


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    formway: int,
    segmentid: str | None = None,
) -> RoadFeatureRecord:
    return RoadFeatureRecord(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=2,
        formway=formway,
        road_kind=2,
        properties={
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": 2,
            "formway": formway,
            "road_kind": 2,
            "sgrade": None,
            "segmentid": segmentid,
        },
        geometry=LineString([(float(snodeid), 0.0), (float(enodeid), 0.0)]),
    )


def _node(node_id: str) -> NodeFeatureRecord:
    return NodeFeatureRecord(
        node_id=node_id,
        mainnodeid=None,
        semantic_node_id=node_id,
        grade=0,
        kind=0,
        properties={
            "id": node_id,
            "kind": 0,
            "grade": 0,
            "kind_2": 0,
            "grade_2": 0,
            "closed_con": 2,
            "working_mainnodeid": None,
        },
        geometry=Point(float(node_id), 0.0),
    )


def test_assigns_connected_advance_right_components_without_overwriting_normal_segment() -> None:
    roads = [
        _road("a", "1", "2", formway=128),
        _road("b", "2", "3", formway=129),
        _road("c", "8", "9", formway=128),
        _road("normal", "3", "4", formway=0),
        _road("preassigned", "5", "6", formway=128, segmentid="5_6"),
    ]
    properties = {road.road_id: dict(road.properties) for road in roads}

    summary = assign_advance_right_segments(roads=roads, road_properties_map=properties)

    assert summary.segment_count == 2
    assert summary.road_count == 3
    assert summary.skipped_preassigned_road_count == 1
    assert properties["a"]["segmentid"] == properties["b"]["segmentid"]
    assert properties["a"]["segment_type"] == ADVANCE_RIGHT_SEGMENT_TYPE
    assert properties["c"]["segmentid"] != properties["a"]["segmentid"]
    assert properties["normal"]["segmentid"] is None
    assert properties["preassigned"]["segmentid"] == "5_6"


def test_step6_outputs_advance_right_segment_without_anchor_nodes(tmp_path: Path) -> None:
    roads = [
        _road("a", "1", "2", formway=128),
        _road("b", "2", "3", formway=128),
        _road("normal", "3", "4", formway=0, segmentid="3_4"),
    ]
    nodes = [_node(str(index)) for index in range(1, 5)]
    road_properties_map = {road.road_id: dict(road.properties) for road in roads}

    artifacts = run_step6_segment_aggregation_from_records(
        nodes=nodes,
        roads=roads,
        out_root=tmp_path / "out",
        node_path=tmp_path / "nodes.gpkg",
        road_path=tmp_path / "roads.gpkg",
        run_id="advance_right",
        road_properties_map=road_properties_map,
    )

    segment_doc = load_vector_feature_collection(artifacts.segment_path)
    features_by_type = {
        feature["properties"]["segment_type"]: feature
        for feature in segment_doc["features"]
    }
    advance = features_by_type[ADVANCE_RIGHT_SEGMENT_TYPE]["properties"]
    assert advance["pair_nodes"] in (None, "")
    assert advance["junc_nodes"] in (None, "")
    assert advance["roads"] == "a,b"
    assert artifacts.summary["normal_segment_count"] == 1
    assert artifacts.summary["advance_right_segment_count"] == 1
    assert artifacts.summary["advance_right_road_count"] == 2
