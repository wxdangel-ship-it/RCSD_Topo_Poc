from __future__ import annotations

import fiona
from shapely.geometry import LineString, Point
from shapely.geometry import mapping
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_candidates import (
    _Road,
    _plan_dict,
    _read_points,
    _segment_plans,
)


def test_truth_free_plan_candidates_retain_complete_keep_path_and_abstain() -> None:
    roads = [
        _Road("r1", "n1", "n2", 2, 4, LineString([(0, 0), (10, 0)])),
        _Road("r2", "n2", "n3", 2, 4, LineString([(10, 0), (20, 0)])),
    ]
    raw_nodes = {
        "n1": Point(0, 0),
        "n2": Point(10, 0),
        "n3": Point(20, 0),
    }
    node_ids = list(raw_nodes)
    node_geometries = [raw_nodes[node_id] for node_id in node_ids]
    plans = _segment_plans(
        segment={
            "segment_id": "s1",
            "segment_type": "STANDARD",
            "pair_node_ids": ("a", "b"),
            "junc_node_ids": (),
            "swsd_road_ids": ("swsd1",),
            "geometry": LineString([(0, 0), (20, 0)]),
        },
        roads=roads,
        road_tree=STRtree([road.geometry for road in roads]),
        raw_nodes=raw_nodes,
        raw_node_ids=node_ids,
        raw_node_geometries=node_geometries,
        raw_node_tree=STRtree(node_geometries),
        swsd_nodes={"a": Point(0, 0), "b": Point(20, 0)},
        max_candidates=10,
    )
    assert any(
        plan.decision == "KEEP_SWSD" and plan.road_ids == ("swsd1",)
        for plan in plans
    )
    assert any(
        plan.decision == "USE_RCSD" and set(plan.road_ids) == {"r1", "r2"}
        for plan in plans
    )
    assert any(plan.decision == "ABSTAIN" and not plan.road_ids for plan in plans)


def test_swsd_semantic_anchor_targets_use_canonical_mainnodeid(tmp_path) -> None:
    path = tmp_path / "nodes.geojson"
    schema = {
        "geometry": "Point",
        "properties": {
            "id": "str",
            "mainnodeid": "str",
            "kind_2": "int",
        },
    }
    with fiona.open(
        path,
        "w",
        driver="GeoJSON",
        crs="EPSG:3857",
        schema=schema,
    ) as sink:
        sink.write(
            {
                "geometry": mapping(Point(0, 0)),
                "properties": {
                    "id": "member",
                    "mainnodeid": "semantic",
                    "kind_2": 4,
                },
            }
        )
        sink.write(
            {
                "geometry": mapping(Point(1, 0)),
                "properties": {
                    "id": "ordinary",
                    "mainnodeid": "0",
                    "kind_2": 1,
                },
            }
        )

    _, _, semantic_anchor_by_node = _read_points(path)

    assert semantic_anchor_by_node == {
        "member": "semantic",
        "semantic": "semantic",
    }


def test_plan_candidates_only_mark_proven_connector_tree_as_connector() -> None:
    roads = [
        _Road("main", "n1", "n4", 2, 4, LineString([(0, 0), (20, 0)])),
        _Road("c1", "n1", "x", 2, 4, LineString([(0, 0), (10, 2)])),
        _Road("c2", "x", "n4", 2, 4, LineString([(10, 2), (20, 0)])),
    ]
    raw_nodes = {
        "n1": Point(0, 0),
        "x": Point(10, 2),
        "n4": Point(20, 0),
    }
    node_ids = list(raw_nodes)
    plans = _segment_plans(
        segment={
            "segment_id": "s1",
            "segment_type": "STANDARD",
            "pair_node_ids": ("a", "b"),
            "junc_node_ids": (),
            "swsd_road_ids": ("swsd",),
            "geometry": LineString([(0, 0), (20, 0)]),
        },
        roads=roads,
        road_tree=STRtree([road.geometry for road in roads]),
        raw_nodes=raw_nodes,
        raw_node_ids=node_ids,
        raw_node_geometries=[raw_nodes[node_id] for node_id in node_ids],
        raw_node_tree=STRtree([raw_nodes[node_id] for node_id in node_ids]),
        swsd_nodes={"a": Point(0, 0), "b": Point(20, 0)},
        max_candidates=20,
    )
    connector_plan = next(
        plan
        for plan in plans
        if plan.generator == "INTERNAL_CONNECTOR_TREE"
        and {
            road_id
            for road_id, role in plan.road_roles
            if role == "INTERNAL_CONNECTOR"
        }
        == {"c1", "c2"}
    )
    payload = _plan_dict(
        "T10:case",
        "s1",
        connector_plan,
        LineString([(0, 0), (20, 0)]),
        roads,
        (),
        raw_nodes,
        {"a": Point(0, 0), "b": Point(20, 0)},
        ("a", "b"),
    )

    assert connector_plan.road_roles == (
        ("c1", "INTERNAL_CONNECTOR"),
        ("c2", "INTERNAL_CONNECTOR"),
        ("main", "MAIN"),
    )
    assert connector_plan.connector_tree_proof["hard_valid"] is True
    assert payload["owned_road_ids"] == ["c1", "c2", "main"]
    assert payload["internal_connector_road_ids"] == ["c1", "c2"]
    assert payload["internal_connector_tree_proof"]["external_leaf_node_ids"] == []
    assert not any(
        plan.generator == "CORRIDOR_COMPONENT" for plan in plans
    )
