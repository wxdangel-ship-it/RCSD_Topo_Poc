from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    ORDINARY_PLAN_ARM_COUNT,
    ORDINARY_PLAN_ARM_FEATURE_DIM,
    build_ordinary_plan_arm_rows,
    condition_ordinary_plan_arm_features,
)


def test_arm_rows_preserve_two_ends_and_nearest_road_sidecars() -> None:
    roads = {
        "r1": SimpleNamespace(
            road_id="r1",
            start_node_id="n1",
            end_node_id="n2",
            geometry=LineString([(0.0, 0.0), (50.0, 0.0)]),
        ),
        "r2": SimpleNamespace(
            road_id="r2",
            start_node_id="n2",
            end_node_id="n3",
            geometry=LineString([(50.0, 0.0), (100.0, 0.0)]),
        ),
    }
    rows = build_ordinary_plan_arm_rows(
        road_ids=("r1", "r2"),
        road_roles={"r1": "MAIN", "r2": "MAIN"},
        road_by_id=roads,
        segment_geometry=LineString([(0.0, 0.0), (100.0, 0.0)]),
        node_points={
            "n1": Point(0.0, 0.0),
            "n2": Point(50.0, 0.0),
            "n3": Point(100.0, 0.0),
        },
        pair_points=(Point(0.0, 0.0), Point(100.0, 0.0)),
    )

    assert len(rows) == ORDINARY_PLAN_ARM_COUNT
    assert [row["nearest_road_id"] for row in rows] == ["r1", "r2"]
    assert [row["nearest_node_id"] for row in rows] == ["n1", "n3"]
    assert all(
        len(row["features"]) == ORDINARY_PLAN_ARM_BASE_FEATURE_DIM
        for row in rows
    )
    assert rows[0]["features"][3] == 1.0
    assert rows[0]["features"][9] == 1.0
    assert rows[0]["features"][10] == 1.0


def test_arm_conditioning_adds_oof_anchor_relations_without_ids() -> None:
    base = (
        (0.0,) * ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
        (0.0,) * ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    )

    values = condition_ordinary_plan_arm_features(
        base_features=base,
        nearest_road_ids=("r1", "r2"),
        nearest_node_ids=("n1", "n2"),
        arm_anchor_ids=("a1", "a2"),
        selected_road_ids={"r1"},
        selected_node_ids={"n2"},
        selected_road_ids_by_anchor={"a1": {"r1"}},
        selected_node_ids_by_anchor={"a2": {"n2"}},
    )

    assert all(len(row) == ORDINARY_PLAN_ARM_FEATURE_DIM for row in values)
    assert values[0][13:16] == (1.0, 0.0, 1.0)
    assert values[0][16:19] == (1.0, 0.0, 1.0)
    assert values[0][19:22] == (0.0, 0.0, 0.0)
    assert values[1][13:16] == (0.0, 1.0, 1.0)
    assert values[1][16:19] == (0.0, 1.0, 1.0)
    assert values[1][19:22] == (0.0, 0.0, 0.0)
