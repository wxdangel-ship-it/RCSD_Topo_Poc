from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access import (
    AccessRoad,
    FinalRoad,
    access_truth_targets,
    classify_access_target,
    junc_access_requirement,
    normalized_final_road_id,
)


def test_split_final_road_normalizes_to_original_rcsd_road() -> None:
    assert (
        normalized_final_road_id(
            {
                "id": "generated",
                "source_road_id": "",
                "t06_split_original_road_id": "original",
            }
        )
        == "original"
    )


def test_access_truth_uses_junc_node_map_and_incident_split_road() -> None:
    roads = {
        "original": AccessRoad(
            road_id="original",
            source="RCSD",
            start_node_id="a",
            end_node_id="b",
            geometry=LineString([(0, 0), (10, 0)]),
        )
    }
    final_roads = [
        FinalRoad(
            road_id="left",
            normalized_road_id="original",
            start_node_id="a",
            end_node_id="mapped",
            geometry=LineString([(0, 0), (4, 0)]),
            source=1,
        ),
        FinalRoad(
            road_id="right",
            normalized_road_id="original",
            start_node_id="mapped",
            end_node_id="b",
            geometry=LineString([(4, 0), (10, 0)]),
            source=1,
        ),
    ]
    targets, state = access_truth_targets(
        junc_node_id="junc",
            relation={
                "swsd_to_frcsd_node_map": (
                    '[{"swsd_node_id":"junc",'
                    '"frcsd_node_ids":["mapped"]}]'
                ),
                "frcsd_road_ids": '["original"]',
            },
        final_roads=final_roads,
        final_nodes={"mapped": Point(4, 0)},
        final_node_closure={"mapped": ("mapped",)},
        access_roads=roads,
    )
    assert state == "RESOLVED"
    assert len(targets) == 1
    assert targets[0]["road_id"] == "original"
    assert targets[0]["target_fraction"] == 0.4
    assert targets[0]["target_operation"] == "SPLIT_ROAD"


def test_missing_relation_map_is_unknown_not_anchor_failure() -> None:
    targets, state = access_truth_targets(
        junc_node_id="junc",
        relation={},
        final_roads=[],
        final_nodes={},
        final_node_closure={},
        access_roads={},
    )
    assert targets == []
    assert state == "JUNC_NODE_MAP_UNKNOWN"


def test_access_target_role_distinguishes_owned_and_connectivity() -> None:
    relation = {
        "frcsd_road_ids": "['owned']",
        "owned_frcsd_road_ids": "['owned']",
        "related_connectivity_road_ids": "['shared']",
        "pruned_non_owner_frcsd_road_ids": "['other']",
    }
    assert classify_access_target("owned", relation) == "OWNED_CARRIER"
    assert (
        classify_access_target("shared", relation)
        == "CONNECTIVITY_REFERENCE"
    )
    assert classify_access_target("other", relation) == "PRUNED_NON_OWNER"
    assert (
        classify_access_target("unknown", relation)
        == "UNCLASSIFIED_INCIDENT"
    )


def test_access_truth_accepts_python_list_node_map_and_unique_geometry_lineage() -> None:
    roads = {
        "raw": AccessRoad(
            road_id="raw",
            source="RCSD",
            start_node_id="a",
            end_node_id="b",
            geometry=LineString([(0, 0), (10, 0)]),
        )
    }
    targets, state = access_truth_targets(
        junc_node_id="junc",
        relation={
            "swsd_to_frcsd_node_map": (
                "[{'swsd_node_id':'junc',"
                "'frcsd_node_ids':['mapped']}]"
            ),
            "frcsd_road_ids": "['generated']",
        },
        final_roads=[
            FinalRoad(
                road_id="generated",
                normalized_road_id="generated",
                start_node_id="a",
                end_node_id="mapped",
                geometry=LineString([(0, 0), (4, 0)]),
                source=1,
            )
        ],
        final_nodes={"mapped": Point(4, 0)},
        final_node_closure={"mapped": ("mapped",)},
        access_roads=roads,
    )
    assert state == "RESOLVED"
    assert targets[0]["road_id"] == "raw"
    assert targets[0]["source_lineage"] == "GEOMETRY_UNIQUE"
    assert targets[0]["access_business_role"] == "DIRECT_CARRIER"


def test_access_truth_keeps_geometry_equivalent_lineages_as_multi_solution() -> None:
    roads = {
        road_id: AccessRoad(
            road_id=road_id,
            source="RCSD",
            start_node_id="a",
            end_node_id="b",
            geometry=LineString([(0, 0), (10, 0)]),
        )
        for road_id in ("raw_a", "raw_b")
    }
    targets, state = access_truth_targets(
        junc_node_id="junc",
        relation={
            "swsd_to_frcsd_node_map": (
                '[{"swsd_node_id":"junc",'
                '"frcsd_node_ids":["mapped"]}]'
            ),
            "frcsd_road_ids": '["generated"]',
        },
        final_roads=[
            FinalRoad(
                road_id="generated",
                normalized_road_id="generated",
                start_node_id="a",
                end_node_id="mapped",
                geometry=LineString([(0, 0), (4, 0)]),
                source=1,
            )
        ],
        final_nodes={"mapped": Point(4, 0)},
        final_node_closure={"mapped": ("mapped",)},
        access_roads=roads,
    )

    assert state == "RESOLVED"
    assert {row["road_id"] for row in targets} == {"raw_a", "raw_b"}
    assert {
        row["source_lineage"] for row in targets
    } == {"GEOMETRY_MULTI_ACCEPTABLE"}


def test_detached_and_exempt_junc_nodes_do_not_require_access() -> None:
    relation = {
        "detached_junc_nodes": '["detached"]',
        "junc_kind2_exempt_nodes": "['exempt']",
    }

    assert (
        junc_access_requirement("detached", relation)
        == "DETACHED_JUNC_NODE_NO_ACCESS_REQUIRED"
    )
    assert (
        junc_access_requirement("exempt", relation)
        == "EXEMPT_JUNC_NODE_NO_REQUIRED_ACCESS"
    )
    assert junc_access_requirement("required", relation) == "REQUIRED"
