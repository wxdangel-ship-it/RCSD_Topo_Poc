from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    load_vector_feature_collection,
    write_geojson,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step6_segment_aggregation import (
    run_step6_segment_aggregation,
    run_step6_segment_aggregation_from_records,
)


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    kind: int = 0,
    grade: int = 0,
    kind_2: int,
    grade_2: int,
    closed_con: int = 2,
    mainnodeid: int | None = None,
    working_mainnodeid: int | None = None,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "kind": kind,
            "grade": grade,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "closed_con": closed_con,
            "mainnodeid": mainnodeid,
            "working_mainnodeid": working_mainnodeid,
        },
        "geometry": Point(x, y),
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    coords: list[tuple[float, float]] | None = None,
    *,
    direction: int = 2,
    road_kind: int = 2,
    sgrade: str | None = None,
    segmentid: str | None = None,
    segment_build_source: str | None = None,
    leaf_node_id: str | None = None,
    multiline: bool = False,
) -> dict:
    if coords is None:
        coords = [(float(snodeid), 0.0), (float(enodeid), 0.0)]
    geometry = (
        MultiLineString(
            [
                LineString([coords[0], ((coords[0][0] + coords[1][0]) / 2.0, coords[0][1])]),
                LineString([((coords[0][0] + coords[1][0]) / 2.0, coords[0][1]), coords[1]]),
            ]
        )
        if multiline
        else LineString(coords)
    )
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "road_kind": road_kind,
            "sgrade": sgrade,
            "segmentid": segmentid,
            "segment_build_source": segment_build_source,
            "leaf_node_id": leaf_node_id,
        },
        "geometry": geometry,
    }


def _load_geojson(path: Path) -> dict:
    return load_vector_feature_collection(path)


def test_step6_builds_segment_inner_nodes_and_error_outputs(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind=4, grade=1, kind_2=4, grade_2=1),
            _node_feature(2, 1.0, 0.0, kind=0, grade=0, kind_2=0, grade_2=0),
            _node_feature(200, 1.1, 0.1, kind=0, grade=0, kind_2=0, grade_2=0, working_mainnodeid=2),
            _node_feature(3, 2.0, 0.0, kind=4, grade=1, kind_2=4, grade_2=1),
            _node_feature(4, 3.0, 0.0, kind=4, grade=1, kind_2=4, grade_2=1),
            _node_feature(5, 2.0, 1.0, kind=0, grade=0, kind_2=0, grade_2=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)], sgrade="0-1双", segmentid="1_4"),
            _road_feature("r2", 2, 3, [(1.0, 0.0), (2.0, 0.0)], sgrade="0-1双", segmentid="1_4", multiline=True),
            _road_feature("r3", 3, 4, [(2.0, 0.0), (3.0, 0.0)], sgrade="0-1双", segmentid="1_4"),
            _road_feature("r4", 3, 5, [(2.0, 0.0), (2.0, 1.0)]),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step6_case",
    )

    assert artifacts.summary["segment_count"] == 1
    assert artifacts.summary["segment_with_junc_count"] == 1
    assert artifacts.summary["segment_with_inner_nodes_count"] == 1
    assert artifacts.summary["segment_error_count"] == 1
    assert artifacts.summary["sgrade_adjusted_count"] == 1
    assert artifacts.summary["sgrade_conflict_count"] == 0
    assert artifacts.inner_nodes_summary["inner_segment_count"] == 1
    assert artifacts.inner_nodes_summary["inner_mainnode_count"] == 1
    assert artifacts.inner_nodes_summary["inner_node_count"] == 2

    segment_doc = _load_geojson(artifacts.segment_path)
    assert len(segment_doc["features"]) == 1
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_doc["features"][0]["geometry"]["type"] == "MultiLineString"
    assert segment_props["id"] == "1_4"
    assert segment_props["sgrade"] == "0-0双"
    assert segment_props["pair_nodes"] == "1,4"
    assert segment_props["junc_nodes"] == "3"
    assert segment_props["roads"] == "r1,r2,r3"

    inner_nodes_doc = _load_geojson(artifacts.inner_nodes_path)
    inner_ids = {str(feature["properties"]["id"]) for feature in inner_nodes_doc["features"]}
    assert inner_ids == {"2", "200"}
    for feature in inner_nodes_doc["features"]:
        assert feature["properties"]["segmentid"] == "1_4"
        assert "grade_2" in feature["properties"]
        assert "kind_2" in feature["properties"]
        assert "working_mainnodeid" not in feature["properties"]

    segment_error_doc = _load_geojson(artifacts.segment_error_path)
    assert len(segment_error_doc["features"]) == 1
    error_props = segment_error_doc["features"][0]["properties"]
    assert error_props["id"] == "1_4"
    assert error_props["error_type"] == "grade_kind_conflict"
    assert "3" in error_props["error_desc"]
    grade_kind_doc = _load_geojson(artifacts.error_layer_paths["grade_kind_conflict"])
    assert len(grade_kind_doc["features"]) == 1
    assert grade_kind_doc["features"][0]["properties"]["error_type"] == "grade_kind_conflict"
    sgrade_conflict_doc = _load_geojson(artifacts.error_layer_paths["s_grade_conflict"])
    assert len(sgrade_conflict_doc["features"]) == 0


def test_step6_pair_nodes_follow_segmentid_order(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1),
            _node_feature(4, 1.0, 0.0, kind_2=4, grade_2=1),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 4, [(0.0, 0.0), (1.0, 0.0)], sgrade="0-1双", segmentid="4_1_2"),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "out",
        run_id="pair_order_case",
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    assert segment_doc["features"][0]["properties"]["pair_nodes"] == "4,1"


def test_step6_degrades_when_segment_contains_multiple_sgrades(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0),
            _node_feature(3, 2.0, 0.0, kind_2=4, grade_2=1),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)], sgrade="0-1双", segmentid="1_3"),
            _road_feature("r2", 2, 3, [(1.0, 0.0), (2.0, 0.0)], sgrade="0-0双", segmentid="1_3"),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "out",
        run_id="sgrade_conflict_case",
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_props["id"] == "1_3"
    assert segment_props["sgrade"] == "0-0双"

    error_doc = _load_geojson(artifacts.segment_error_path)
    assert len(error_doc["features"]) == 1
    error_props = error_doc["features"][0]["properties"]
    assert error_props["error_type"] == "s_grade_conflict"
    assert error_props["old_sgrade"] == "0-0双,0-1双"
    assert error_props["new_sgrade"] == "0-0双"
    assert error_props["flag_s_grade_conflict"] is True
    assert "selected highest priority='0-0双'" in error_props["error_desc"]
    sgrade_conflict_doc = _load_geojson(artifacts.error_layer_paths["s_grade_conflict"])
    assert len(sgrade_conflict_doc["features"]) == 1
    assert sgrade_conflict_doc["features"][0]["properties"]["error_type"] == "s_grade_conflict"
    grade_kind_doc = _load_geojson(artifacts.error_layer_paths["grade_kind_conflict"])
    assert len(grade_kind_doc["features"]) == 0

    build_rows = artifacts.segment_build_table_path.read_text(encoding="utf-8")
    assert "s_grade_conflict" in build_rows
    assert artifacts.summary["segment_error_count"] == 1
    assert artifacts.summary["sgrade_conflict_count"] == 1
    assert artifacts.summary["grade_kind_conflict_count"] == 0


def test_step6_keeps_oneway_grade_without_promoting_to_bidirectional(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(10, 0.0, 0.0, kind_2=8, grade_2=1, closed_con=3),
            _node_feature(11, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(12, 2.0, 0.0, kind_2=8, grade_2=1, closed_con=3),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 10, 11, [(0.0, 0.0), (1.0, 0.0)], sgrade="0-0单", segmentid="10_12"),
            _road_feature("r2", 11, 12, [(1.0, 0.0), (2.0, 0.0)], sgrade="0-0单", segmentid="10_12"),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "out",
        run_id="oneway_grade_case",
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_props["id"] == "10_12"
    assert segment_props["sgrade"] == "0-0单"
    assert artifacts.summary["sgrade_adjusted_count"] == 0


def test_step6_counts_road_kind_1_oneway_roads_for_inner_node_detection(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, kind_2=128, grade_2=2, closed_con=3),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("hw1", 1, 2, [(0.0, 0.0), (1.0, 0.0)], road_kind=1, sgrade="0-1单", segmentid="1_3"),
            _road_feature("hw2", 2, 3, [(1.0, 0.0), (2.0, 0.0)], road_kind=1, sgrade="0-1单", segmentid="1_3"),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "out",
        run_id="oneway_road_kind_1_step6",
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_props["id"] == "1_3"
    assert segment_props["sgrade"] == "0-1单"
    assert segment_props["junc_nodes"] in (None, "")
    inner_doc = _load_geojson(artifacts.inner_nodes_path)
    assert [feature["properties"]["id"] for feature in inner_doc["features"]] == [2]


def test_step6_keeps_dead_end_leaf_grade_without_promoting_to_zero_zero(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind=4, grade=1, kind_2=4, grade_2=1),
            _node_feature(2, 1.0, 0.0, kind=4, grade=1, kind_2=4, grade_2=1),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature(
                "dead_dual",
                1,
                2,
                [(0.0, 0.0), (1.0, 0.0)],
                direction=1,
                sgrade="0-2双",
                segmentid="1_2",
                segment_build_source="dead_end_leaf",
                leaf_node_id="2",
            ),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "out",
        run_id="dead_end_leaf_step6",
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_props["id"] == "1_2"
    assert segment_props["sgrade"] == "0-2双"
    assert segment_props["junc_nodes"] in (None, "")
    assert artifacts.summary["dead_end_segment_count"] == 1
    assert artifacts.summary["sgrade_adjusted_count"] == 0


def test_step6_resolves_decimal_alias_pair_node_from_inmemory_groups(tmp_path: Path) -> None:
    nodes = [
        NodeFeatureRecord(
            node_id="698433",
            mainnodeid=None,
            semantic_node_id="698433",
            grade=1,
            kind=4,
            properties={
                "id": "698433",
                "kind": 4,
                "grade": 1,
                "kind_2": 4,
                "grade_2": 1,
                "working_mainnodeid": None,
            },
            geometry=Point(0.0, 0.0),
        ),
        NodeFeatureRecord(
            node_id="699847",
            mainnodeid="699847.0",
            semantic_node_id="699847",
            grade=1,
            kind=4,
            properties={
                "id": "699847",
                "kind": 4,
                "grade": 1,
                "kind_2": 4,
                "grade_2": 1,
                "working_mainnodeid": "699847.0",
            },
            geometry=Point(1.0, 0.0),
        ),
    ]
    roads = [
        RoadFeatureRecord(
            road_id="r_alias",
            snodeid="698433",
            enodeid="699847",
            direction=2,
            formway=0,
            road_kind=2,
            properties={
                "id": "r_alias",
                "snodeid": "698433",
                "enodeid": "699847",
                "direction": 2,
                "formway": 0,
                "road_kind": 2,
                "sgrade": "0-1双",
                "segmentid": "698433_699847.0",
            },
            geometry=LineString([(0.0, 0.0), (1.0, 0.0)]),
        )
    ]
    mainnode_groups = {
        "698433": MainnodeGroup("698433", "698433", ("698433",), 1, 4),
        "699847": MainnodeGroup("699847", "699847", ("699847",), 1, 4),
    }

    artifacts = run_step6_segment_aggregation_from_records(
        nodes=nodes,
        roads=roads,
        out_root=tmp_path / "out",
        node_path=tmp_path / "nodes.gpkg",
        road_path=tmp_path / "roads.gpkg",
        run_id="decimal_alias_pair_node",
        mainnode_groups=mainnode_groups,
    )

    segment_doc = _load_geojson(artifacts.segment_path)
    segment_props = segment_doc["features"][0]["properties"]
    assert segment_props["id"] == "698433_699847.0"
    assert segment_props["pair_nodes"] == "698433,699847.0"
    assert segment_props["sgrade"] == "0-0双"
    assert segment_props["junc_nodes"] in (None, "")
    assert artifacts.summary["segment_count"] == 1
