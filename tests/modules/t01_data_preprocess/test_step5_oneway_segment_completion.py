from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    load_vector_feature_collection,
    write_geojson,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import RIGHT_TURN_FORMWAY_BIT
from rcsd_topo_poc.modules.t01_data_preprocess.step5_oneway_segment_completion import (
    build_step5_input_artifacts_from_refreshed_paths,
    load_step5_input_artifacts_from_dir,
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
    mainnodeid: int | None = None,
    working_mainnodeid: int | None = None,
) -> dict:
    resolved_mainnodeid = node_id if mainnodeid is None else mainnodeid
    resolved_working_mainnodeid = (
        resolved_mainnodeid if working_mainnodeid is None else working_mainnodeid
    )
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": resolved_mainnodeid,
            "working_mainnodeid": resolved_working_mainnodeid,
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
    kind: str | None = None,
    sgrade: str | None = None,
    segmentid: str | None = None,
    segment_build_source: str | None = None,
) -> dict:
    properties = {
        "id": road_id,
        "snodeid": snodeid,
        "enodeid": enodeid,
        "direction": direction,
        "road_kind": road_kind,
        "formway": formway,
        "sgrade": sgrade,
        "segmentid": segmentid,
        "segment_build_source": segment_build_source,
    }
    if kind is not None:
        properties["kind"] = kind
    return {
        "properties": properties,
        "geometry": LineString(coords),
    }


def _build_step5_artifacts(node_path: Path, road_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        **build_step5_input_artifacts_from_refreshed_paths(
            node_path=node_path,
            road_path=road_path,
        ).__dict__
    )


def _road_props_by_id(path: Path) -> dict[str, dict]:
    doc = load_vector_feature_collection(path)
    return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in doc["features"]}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _write_step5_markers(root: Path) -> None:
    (root / "step5_summary.json").write_text("{}", encoding="utf-8")


def test_load_step5_input_artifacts_from_dir_supports_direct_and_alias_outputs(tmp_path: Path) -> None:
    direct_root = tmp_path / "direct_step5"
    alias_root = tmp_path / "alias_step5"
    direct_root.mkdir()
    alias_root.mkdir()

    node_features = [
        _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
        _node_feature(2, 1.0, 0.0, kind_2=4, grade_2=1, closed_con=3),
    ]
    road_features = [
        _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)]),
    ]
    write_geojson(direct_root / "nodes.geojson", node_features)
    write_geojson(direct_root / "roads.geojson", road_features)
    write_geojson(alias_root / "nodes_step5_refreshed.geojson", node_features)
    write_geojson(alias_root / "roads_step5_refreshed.geojson", road_features)
    _write_step5_markers(direct_root)
    _write_step5_markers(alias_root)

    direct_artifacts = load_step5_input_artifacts_from_dir(direct_root)
    alias_artifacts = load_step5_input_artifacts_from_dir(alias_root)

    assert direct_artifacts.refreshed_nodes_path.name == "nodes.geojson"
    assert direct_artifacts.refreshed_roads_path.name == "roads.geojson"
    assert alias_artifacts.refreshed_nodes_path.name == "nodes_step5_refreshed.geojson"
    assert alias_artifacts.refreshed_roads_path.name == "roads_step5_refreshed.geojson"
    assert tuple(road.road_id for road in direct_artifacts.step6_roads) == ("r1",)
    assert tuple(road.road_id for road in alias_artifacts.step6_roads) == ("r1",)


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
    assert road_props["r4"]["sgrade"] == "0-2单"
    assert road_props["r4"]["segment_build_source"] == "oneway_single_road_fallback"
    assert road_props["prot"]["segmentid"] == "6_3"
    assert road_props["prot"]["sgrade"] == "0-1双"

    assert _read_csv_rows(artifacts.unsegmented_csv_path) == []

    build_rows = _read_csv_rows(artifacts.build_table_path)
    assert len(build_rows) == 2
    assert build_rows[0]["road_ids"] == "r1,r2,r3"
    assert build_rows[0]["through_node_ids"] == "2,3"
    assert build_rows[1]["road_ids"] == "r4"
    assert build_rows[1]["segment_build_source"] == "oneway_single_road_fallback"


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
    assert road_props["main"]["sgrade"] == "0-2单"
    assert road_props["main"]["segment_build_source"] == "oneway_single_road_fallback"

    unsegmented_rows = _read_csv_rows(artifacts.unsegmented_csv_path)
    assert [row["road_id"] for row in unsegmented_rows] == ["rt_only"]
    row_by_id = {row["road_id"]: row for row in unsegmented_rows}
    assert row_by_id["rt_only"]["formway_has_bit7_or_bit8"] == "true"
    assert row_by_id["rt_only"]["audit_reason"] == "formway_bit7_or_bit8"
    assert artifacts.summary["unsegmented_formway_bit7_or_bit8_count"] == 1
    assert artifacts.summary["unsegmented_non_formway_bit7_or_bit8_count"] == 0
    assert artifacts.summary["unsegmented_non_formway_bit7_or_bit8_reason_counts"] == {}


def test_oneway_completion_allows_road_kind_1_and_kind_128_terminate(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

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
            _road_feature("hw1", 1, 2, [(0.0, 0.0), (1.0, 0.0)], road_kind=1),
            _road_feature("hw2", 2, 3, [(1.0, 0.0), (2.0, 0.0)], road_kind=1),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_highway_kind128",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["hw1"]["sgrade"] == "0-1单"
    assert road_props["hw2"]["sgrade"] == "0-1单"
    assert road_props["hw1"]["segmentid"] == road_props["hw2"]["segmentid"]
    assert artifacts.summary["road_kind_1_built_road_count"] == 2
    assert artifacts.summary["kind_2_128_terminate_count"] == 1
    phase_01 = next(item for item in artifacts.summary["phase_summaries"] if item["phase_id"] == "0-1单")
    assert phase_01["road_kind_1_candidate_count"] == 2
    assert phase_01["kind_2_128_terminate_count"] == 1


def test_oneway_completion_does_not_use_kind_128_for_zero_zero_phase(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=128, grade_2=1, closed_con=1),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, kind_2=8, grade_2=1, closed_con=3),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r1", 1, 2, [(0.0, 0.0), (1.0, 0.0)]),
            _road_feature("r2", 2, 3, [(1.0, 0.0), (2.0, 0.0)]),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_kind128_not_zero_zero",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["r1"]["sgrade"] == "0-2单"
    assert road_props["r2"]["sgrade"] == "0-2单"
    assert road_props["r1"]["segment_build_source"] == "oneway_single_road_fallback"
    assert road_props["r2"]["segment_build_source"] == "oneway_single_road_fallback"
    phase_00 = next(item for item in artifacts.summary["phase_summaries"] if item["phase_id"] == "0-0单")
    assert phase_00["terminate_node_count"] == 1
    assert artifacts.summary["final_fallback_road_count"] == 2


def test_oneway_completion_final_fallback_handles_phase_mismatch_and_same_group(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=3),
            _node_feature(2, 1.0, 0.0, kind_2=8, grade_2=1, closed_con=1),
            _node_feature(31, 0.0, 1.0, kind_2=4, grade_2=3, closed_con=2, mainnodeid=30),
            _node_feature(32, 1.0, 1.0, kind_2=4, grade_2=3, closed_con=2, mainnodeid=30),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("phase_mismatch", 1, 2, [(0.0, 0.0), (1.0, 0.0)], road_kind=1),
            _road_feature("same_group", 31, 32, [(0.0, 1.0), (1.0, 1.0)], road_kind=3),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="oneway_final_fallback",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["phase_mismatch"]["segmentid"] == "1_2"
    assert road_props["phase_mismatch"]["sgrade"] == "0-2单"
    assert road_props["phase_mismatch"]["segment_build_source"] == "oneway_single_road_fallback"
    assert road_props["same_group"]["segmentid"] == "30_30"
    assert road_props["same_group"]["sgrade"] == "0-2单"
    assert road_props["same_group"]["segment_build_source"] == "oneway_single_road_fallback"
    assert artifacts.summary["final_fallback_segment_count"] == 2
    assert artifacts.summary["final_fallback_road_count"] == 2
    assert artifacts.summary["road_kind_1_built_road_count"] == 1
    assert artifacts.summary["unsegmented_road_count"] == 0


def test_oneway_completion_builds_bidirectional_dead_end_leaf_segment(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("dead_dual", 1, 2, [(0.0, 0.0), (1.0, 0.0)], direction=1),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="dead_end_dual",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["dead_dual"]["segmentid"] == "1_2"
    assert road_props["dead_dual"]["sgrade"] == "0-2双"
    assert road_props["dead_dual"]["segment_build_source"] == "dead_end_leaf"
    assert road_props["dead_dual"]["leaf_node_id"] == "2"
    assert artifacts.summary["dead_end_segment_count"] == 1
    assert artifacts.summary["dead_end_road_count"] == 1
    assert artifacts.summary["unsegmented_road_count"] == 0


def test_oneway_completion_builds_reciprocal_oneway_dead_end_leaf_segment(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(101, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2, mainnodeid=100),
            _node_feature(102, 0.0, 0.1, kind_2=4, grade_2=1, closed_con=2, mainnodeid=100),
            _node_feature(200, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("dead_out", 101, 200, [(0.0, 0.0), (1.0, 0.0)], direction=2, road_kind=1),
            _road_feature("dead_in", 102, 200, [(0.0, 0.1), (1.0, 0.0)], direction=3, road_kind=1),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="dead_end_oneway_pair",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["dead_out"]["segmentid"] == "100_200"
    assert road_props["dead_in"]["segmentid"] == "100_200"
    assert road_props["dead_out"]["sgrade"] == "0-2双"
    assert road_props["dead_in"]["sgrade"] == "0-2双"
    assert road_props["dead_out"]["leaf_node_id"] == "200"
    assert artifacts.summary["dead_end_segment_count"] == 1
    assert artifacts.summary["dead_end_oneway_pair_segment_count"] == 1
    assert artifacts.summary["dead_end_road_count"] == 2
    assert artifacts.summary["unsegmented_road_count"] == 0


def test_oneway_completion_builds_unpaired_oneway_with_final_fallback(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("oneway_only", 1, 2, [(0.0, 0.0), (1.0, 0.0)], direction=2, road_kind=1),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="dead_end_unpaired_oneway",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["oneway_only"]["segmentid"] == "1_2"
    assert road_props["oneway_only"]["sgrade"] == "0-2单"
    assert road_props["oneway_only"]["segment_build_source"] == "oneway_single_road_fallback"
    assert artifacts.summary["dead_end_segment_count"] == 0
    assert artifacts.summary["final_fallback_segment_count"] == 1
    assert artifacts.summary["final_fallback_road_count"] == 1
    assert artifacts.summary["unsegmented_road_count"] == 0


def test_oneway_completion_builds_residual_bidirectional_road_with_final_fallback(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("residual_dual", 1, 2, [(0.0, 0.0), (1.0, 0.0)], direction=1, road_kind=3),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="fallback_residual_dual",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["residual_dual"]["segmentid"] == "1_2"
    assert road_props["residual_dual"]["sgrade"] == "0-2双"
    assert road_props["residual_dual"]["segment_build_source"] == "oneway_single_road_fallback"
    assert artifacts.summary["dead_end_segment_count"] == 0
    assert artifacts.summary["final_fallback_segment_count"] == 1
    assert artifacts.summary["final_fallback_road_count"] == 1
    assert artifacts.summary["final_fallback_summary"]["bidirectional_built_road_count"] == 1
    assert artifacts.summary["unsegmented_road_count"] == 0


def test_oneway_completion_merges_two_attachment_side_segment_into_high_grade_main(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 10.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(3, 20.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(4, 10.0, 10.0, kind_2=4, grade_2=2, closed_con=2),
            _node_feature(5, 10.0, 80.0, kind_2=4, grade_2=2, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature(
                "main_a",
                1,
                2,
                [(0.0, 0.0), (10.0, 0.0)],
                direction=0,
                sgrade="0-0双",
                segmentid="1_3",
                segment_build_source="step4_high_grade_terminal_demotion",
            ),
            _road_feature(
                "main_b",
                2,
                3,
                [(10.0, 0.0), (20.0, 0.0)],
                direction=0,
                sgrade="0-0双",
                segmentid="1_3",
                segment_build_source="step4_high_grade_terminal_demotion",
            ),
            _road_feature(
                "near_side_a",
                2,
                4,
                [(10.0, 0.0), (10.0, 10.0)],
                direction=0,
                sgrade="0-2双",
                segmentid="2_3",
            ),
            _road_feature(
                "near_side_b",
                4,
                3,
                [(10.0, 10.0), (20.0, 0.0)],
                direction=0,
                sgrade="0-2双",
                segmentid="2_3",
            ),
            _road_feature("far_side", 2, 5, [(10.0, 0.0), (10.0, 80.0)], direction=0, sgrade="0-2双", segmentid="2_5"),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=tmp_path / "out",
        run_id="side_attachment_merge",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["near_side_a"]["segmentid"] == "1_3"
    assert road_props["near_side_a"]["sgrade"] == "0-0双"
    assert road_props["near_side_a"]["segment_build_source"] == "side_attachment_merge"
    assert road_props["near_side_a"]["pre_merge_segmentid"] == "2_3"
    assert road_props["near_side_a"]["pre_merge_sgrade"] == "0-2双"
    assert road_props["near_side_b"]["segmentid"] == "1_3"
    assert road_props["near_side_b"]["sgrade"] == "0-0双"
    assert road_props["near_side_b"]["segment_build_source"] == "side_attachment_merge"
    assert road_props["near_side_b"]["pre_merge_segmentid"] == "2_3"
    assert road_props["far_side"]["segmentid"] == "2_5"
    assert road_props["far_side"]["sgrade"] == "0-2双"

    merge_summary = artifacts.summary["side_attachment_merge_summary"]
    assert merge_summary["distance_gate_mode"] == "main_segment_buffer_covers_candidate_geometry"
    assert merge_summary["merged_segment_count"] == 1
    assert merge_summary["merged_road_count"] == 2
    assert merge_summary["min_main_attachment_count"] == 2

    step6_artifacts = run_step6_segment_aggregation(
        road_path=artifacts.refreshed_roads_path,
        node_path=artifacts.refreshed_nodes_path,
        out_root=tmp_path / "step6",
        run_id="side_attachment_merge_step6",
    )
    assert step6_artifacts.summary["segment_count"] == 2
    assert step6_artifacts.summary["segment_error_count"] == 0


def test_oneway_completion_rejects_isolated_single_attachment_candidates(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 10.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(3, 20.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(4, 10.0, 10.0, kind_2=16, grade_2=2, closed_con=2),
            _node_feature(5, 10.0, 12.0, kind_2=2048, grade_2=2, closed_con=2),
            _node_feature(6, 10.0, 14.0, kind_2=16, grade_2=2, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("main_a", 1, 2, [(0.0, 0.0), (10.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature("main_b", 2, 3, [(10.0, 0.0), (20.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature(
                "single_ramp",
                2,
                4,
                [(10.0, 0.0), (10.0, 10.0)],
                direction=2,
                kind="060a",
                sgrade="0-1单",
                segmentid="2_4",
            ),
            _road_feature(
                "single_link",
                2,
                5,
                [(10.0, 0.0), (10.0, 12.0)],
                direction=2,
                kind="0601",
                sgrade="0-1单",
                segmentid="2_5",
            ),
            _road_feature(
                "fallback_ramp",
                2,
                6,
                [(10.0, 0.0), (10.0, 14.0)],
                direction=2,
                kind="0601",
                sgrade="0-2单",
                segmentid="2_6",
                segment_build_source="oneway_single_road_fallback",
            ),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=tmp_path / "out",
        run_id="side_attachment_reject_ramp",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["single_ramp"]["segmentid"] == "2_4"
    assert road_props["single_ramp"]["sgrade"] == "0-1单"
    assert road_props["single_ramp"].get("segment_build_source") is None
    assert road_props["single_link"]["segmentid"] == "2_5"
    assert road_props["single_link"]["sgrade"] == "0-1单"
    assert road_props["single_link"].get("segment_build_source") is None
    assert road_props["fallback_ramp"]["segmentid"] == "2_6"
    assert road_props["fallback_ramp"]["sgrade"] == "0-2单"
    assert road_props["fallback_ramp"]["segment_build_source"] == "oneway_single_road_fallback"

    merge_summary = artifacts.summary["side_attachment_merge_summary"]
    assert merge_summary["merged_segment_count"] == 0
    assert merge_summary["skipped_insufficient_attachment_count"] == 1


def test_oneway_completion_allows_connected_candidate_component_with_two_main_attachments(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 10.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(3, 20.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(4, 10.0, 10.0, kind_2=2048, grade_2=2, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("main_a", 1, 2, [(0.0, 0.0), (10.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature("main_b", 2, 3, [(10.0, 0.0), (20.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature(
                "side_a",
                2,
                4,
                [(10.0, 0.0), (10.0, 10.0)],
                direction=2,
                kind="060a",
                sgrade="0-1单",
                segmentid="2_4",
            ),
            _road_feature(
                "side_b",
                4,
                3,
                [(10.0, 10.0), (20.0, 0.0)],
                direction=2,
                kind="060a",
                sgrade="0-1单",
                segmentid="4_3",
            ),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=tmp_path / "out",
        run_id="side_attachment_connected_component",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["side_a"]["segmentid"] == "1_3"
    assert road_props["side_a"]["segment_build_source"] == "side_attachment_merge"
    assert road_props["side_b"]["segmentid"] == "1_3"
    assert road_props["side_b"]["segment_build_source"] == "side_attachment_merge"

    merge_summary = artifacts.summary["side_attachment_merge_summary"]
    assert merge_summary["merged_component_count"] == 1
    assert merge_summary["merged_segment_count"] == 2
    assert merge_summary["merged_road_count"] == 2
    assert merge_summary["merged_segments"][0]["from_segmentids"] == "2_4,4_3"
    assert merge_summary["merged_segments"][0]["attachment_node_ids"] == "2,3"


def test_oneway_completion_arbitrates_multi_main_side_attachment_by_attachment_count(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 10.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(3, 20.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(4, 10.0, 10.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(5, 20.0, 10.0, kind_2=4, grade_2=1, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("main_a", 1, 2, [(0.0, 0.0), (10.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature("main_b", 2, 3, [(10.0, 0.0), (20.0, 0.0)], direction=0, sgrade="0-0双", segmentid="1_3"),
            _road_feature("main_e", 2, 4, [(10.0, 0.0), (10.0, 10.0)], direction=0, sgrade="0-0双", segmentid="1_4"),
            _road_feature("main_c", 2, 4, [(10.0, 0.0), (10.0, 10.0)], direction=0, sgrade="0-0双", segmentid="2_5"),
            _road_feature("main_d", 4, 5, [(10.0, 10.0), (20.0, 10.0)], direction=0, sgrade="0-0双", segmentid="2_5"),
            _road_feature(
                "candidate",
                2,
                4,
                [(10.0, 0.0), (10.0, 10.0)],
                direction=2,
                kind="0601",
                sgrade="0-1单",
                segmentid="2_4",
            ),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=tmp_path / "out",
        run_id="side_attachment_arbitration",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["candidate"]["segmentid"] == "1_4"
    merge_summary = artifacts.summary["side_attachment_merge_summary"]
    assert merge_summary["multi_main_match_candidate_count"] == 1
    assert merge_summary["arbitrated_segments"][0]["candidate_segmentid"] == "2_4"
    assert merge_summary["arbitrated_segments"][0]["chosen_main_segmentid"] == "1_4"


def test_oneway_completion_excludes_dead_end_leaf_formway_128_and_right_turn_only(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind_2=4, grade_2=1, closed_con=2),
            _node_feature(2, 1.0, 0.0, kind_2=0, grade_2=0, closed_con=0),
            _node_feature(3, 0.0, 1.0, kind_2=0, grade_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("dead_formway_128", 1, 2, [(0.0, 0.0), (1.0, 0.0)], direction=1, formway=128),
            _road_feature(
                "dead_right_turn",
                1,
                3,
                [(0.0, 0.0), (0.0, 1.0)],
                direction=1,
                formway=(1 << RIGHT_TURN_FORMWAY_BIT) + 1,
            ),
        ],
    )

    artifacts = run_step5_oneway_segment_completion(
        step5_artifacts=_build_step5_artifacts(node_path, road_path),
        out_root=out_root,
        run_id="dead_end_excluded_roads",
        debug=False,
    )

    road_props = _road_props_by_id(artifacts.refreshed_roads_path)
    assert road_props["dead_formway_128"]["segmentid"] is None
    assert road_props["dead_right_turn"]["segmentid"] is None
    assert artifacts.summary["dead_end_segment_count"] == 0
    assert artifacts.summary["unsegmented_road_count"] == 1
    assert artifacts.summary["unsegmented_excluded_formway_128_count"] == 1
