from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    load_vector_feature_collection,
    write_geojson,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    _build_mainnode_groups,
    _load_nodes_and_roads,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step5_oneway_segment_completion import (
    run_step5_oneway_segment_completion,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step6_segment_aggregation import (
    run_step6_segment_aggregation,
)


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    kind_2: int,
    grade_2: int,
    closed_con: int,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": node_id,
            "working_mainnodeid": node_id,
            "kind": kind_2,
            "grade": grade_2,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "closed_con": closed_con,
        },
        "geometry": Point(x, y),
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    coords: list[tuple[float, float]],
    *,
    direction: int = 2,
    road_kind: int = 2,
    formway: int = 0,
    sgrade: str | None = None,
    segmentid: str | None = None,
) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "road_kind": road_kind,
            "formway": formway,
            "sgrade": sgrade,
            "segmentid": segmentid,
        },
        "geometry": LineString(coords),
    }


def _build_step5_artifacts(node_path: Path, road_path: Path) -> SimpleNamespace:
    (nodes, node_by_id, groups), (roads, _) = _load_nodes_and_roads(node_path=node_path, road_path=road_path)
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = {
        member_node_id: mainnode_id
        for mainnode_id, group in mainnode_groups.items()
        for member_node_id in group.member_node_ids
    }
    group_to_allowed_road_ids: dict[str, set[str]] = {}
    for road in roads:
        for node_id in (road.snodeid, road.enodeid):
            group_id = physical_to_semantic[node_id]
            group_to_allowed_road_ids.setdefault(group_id, set()).add(road.road_id)
    return SimpleNamespace(
        refreshed_nodes_path=node_path,
        refreshed_roads_path=road_path,
        step6_nodes=tuple(nodes),
        step6_roads=tuple(roads),
        step6_node_properties_map={node.node_id: dict(node.properties) for node in nodes},
        step6_road_properties_map={road.road_id: dict(road.properties) for road in roads},
        step6_mainnode_groups=mainnode_groups,
        step6_group_to_allowed_road_ids=group_to_allowed_road_ids,
    )


def _road_props_by_id(path: Path) -> dict[str, dict]:
    doc = load_vector_feature_collection(path)
    return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in doc["features"]}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def test_oneway_completion_builds_three_phase_segments_and_excludes_formway_128_from_residual(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(101, 0.0, 0.0, kind_2=8, grade_2=1, closed_con=1),
            _node_feature(102, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(103, 2.0, 0.0, kind_2=8, grade_2=1, closed_con=3),
            _node_feature(201, 0.0, 10.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(202, 1.0, 10.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(203, 2.0, 10.0, kind_2=4, grade_2=2, closed_con=3),
            _node_feature(301, 0.0, 20.0, kind_2=4, grade_2=3, closed_con=2),
            _node_feature(302, 1.0, 20.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(303, 2.0, 20.0, kind_2=4, grade_2=3, closed_con=3),
            _node_feature(401, 0.0, 30.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(402, 1.0, 30.0, kind_2=4, grade_2=1, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r00a", 101, 102, [(0.0, 0.0), (1.0, 0.0)]),
            _road_feature("r00b", 102, 103, [(1.0, 0.0), (2.0, 0.0)]),
            _road_feature("r01a", 201, 202, [(0.0, 10.0), (1.0, 10.0)]),
            _road_feature("r01b", 202, 203, [(1.0, 10.0), (2.0, 10.0)]),
            _road_feature("r02a", 301, 302, [(0.0, 20.0), (1.0, 20.0)]),
            _road_feature("r02b", 302, 303, [(1.0, 20.0), (2.0, 20.0)]),
            _road_feature("r128", 401, 402, [(0.0, 30.0), (1.0, 30.0)], formway=128),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_phases",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["r00a"]["sgrade"] == "0-0单"
    assert road_props["r00b"]["sgrade"] == "0-0单"
    assert road_props["r00a"]["segmentid"] == road_props["r00b"]["segmentid"]

    assert road_props["r01a"]["sgrade"] == "0-1单"
    assert road_props["r01b"]["sgrade"] == "0-1单"
    assert road_props["r01a"]["segmentid"] == road_props["r01b"]["segmentid"]

    assert road_props["r02a"]["sgrade"] == "0-2单"
    assert road_props["r02b"]["sgrade"] == "0-2单"
    assert road_props["r02a"]["segmentid"] == road_props["r02b"]["segmentid"]

    assert road_props["r128"]["segmentid"] is None
    assert artifacts.summary["built_segment_count"] == 3
    assert artifacts.summary["unsegmented_road_count"] == 0
    assert artifacts.summary["unsegmented_excluded_formway_128_count"] == 1
    assert _read_csv_rows(artifacts.unsegmented_csv_path) == []


def test_oneway_completion_respects_through_branch_choice_and_existing_segmentid(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(4, 3.0, 0.0, kind_2=4, grade_2=1, closed_con=3),
            _node_feature(5, 2.5, 0.5, kind_2=4, grade_2=1, closed_con=3),
            _node_feature(6, 2.0, -1.0, kind_2=4, grade_2=1, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)]),
            _road_feature("r2", 2, 3, [(1.0, 0.0), (2.0, 0.0)]),
            _road_feature("r3", 3, 4, [(2.0, 0.0), (3.0, 0.0)]),
            _road_feature("r4", 3, 5, [(2.0, 0.0), (2.5, 0.5)]),
            _road_feature("prot", 6, 3, [(2.0, -1.0), (2.0, 0.0)], sgrade="0-1双", segmentid="6_3"),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_branch",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    segment_id = road_props["r1"]["segmentid"]
    assert segment_id is not None
    assert road_props["r1"]["sgrade"] == "0-1单"
    assert road_props["r2"]["segmentid"] == segment_id
    assert road_props["r3"]["segmentid"] == segment_id
    assert road_props["r4"]["segmentid"] is None
    assert road_props["prot"]["segmentid"] == "6_3"
    assert road_props["prot"]["sgrade"] == "0-1双"

    unsegmented_rows = _read_csv_rows(artifacts.unsegmented_csv_path)
    assert [row["road_id"] for row in unsegmented_rows] == ["r4"]

    build_rows = _read_csv_rows(artifacts.build_table_path)
    assert len(build_rows) == 1
    assert build_rows[0]["road_ids"] == "r1,r2,r3"
    assert build_rows[0]["through_node_ids"] == "2,3"


def test_step6_keeps_oneway_zero_zero_grade_without_promoting_to_dual(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)], sgrade="0-0单", segmentid="1_3"),
            _road_feature("r2", 2, 3, [(1.0, 0.0), (2.0, 0.0)], sgrade="0-0单", segmentid="1_3"),
        ],
    )

    artifacts = run_step6_segment_aggregation(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "step6_out",
        run_id="step6_oneway_grade",
    )

    segment_doc = load_vector_feature_collection(artifacts.segment_path)
    props = segment_doc["features"][0]["properties"]
    assert props["sgrade"] == "0-0单"
    assert artifacts.summary["sgrade_adjusted_count"] == 0


def test_oneway_completion_excludes_right_turn_only_roads(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, kind_2=4, grade_2=1, closed_con=3),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature(
                "rt_only",
                1,
                2,
                [(0.0, 0.0), (1.0, 0.0)],
                formway=(1 << RIGHT_TURN_FORMWAY_BIT) + 1,
            ),
            _road_feature("main", 2, 3, [(1.0, 0.0), (2.0, 0.0)]),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_right_turn_excluded",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["rt_only"]["segmentid"] is None
    assert road_props["rt_only"]["sgrade"] is None
    assert road_props["main"]["segmentid"] is None

    unsegmented_rows = _read_csv_rows(artifacts.unsegmented_csv_path)
    assert [row["road_id"] for row in unsegmented_rows] == ["rt_only", "main"]
