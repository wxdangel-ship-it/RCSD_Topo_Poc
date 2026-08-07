from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
    build_ordinary_plan_member_rows,
    condition_ordinary_plan_member_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_candidates import (
    _Road,
)


def test_member_rows_encode_endpoint_direction_and_plan_graph_role() -> None:
    roads = {
        "r1": _Road(
            "r1",
            "n1",
            "n2",
            2,
            4,
            LineString([(0, 0), (10, 0)]),
        ),
        "r2": _Road(
            "r2",
            "n2",
            "n3",
            2,
            4,
            LineString([(10, 0), (20, 0)]),
        ),
    }

    rows = build_ordinary_plan_member_rows(
        road_ids=("r1", "r2"),
        road_roles={"r1": "MAIN", "r2": "INTERNAL_CONNECTOR"},
        road_by_id=roads,
        segment_geometry=LineString([(0, 0), (20, 0)]),
        raw_nodes={
            "n1": Point(0, 0),
            "n2": Point(10, 0),
            "n3": Point(20, 0),
        },
        swsd_nodes={"s": Point(0, 0), "t": Point(20, 0)},
        pair_node_ids=("s", "t"),
    )

    assert len(rows) == 2
    assert all(
        len(row["features"]) == ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
        for row in rows
    )
    assert rows[0]["features"][0] == 1.0
    assert rows[1]["features"][1] == 1.0
    assert rows[0]["features"][20] == 1.0
    assert rows[1]["features"][21] == 1.0
    assert rows[0]["features"][23] == pytest.approx(1.0)


def test_member_conditioning_uses_anchor_ids_only_as_relations() -> None:
    base = ((0.0,) * ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,) * 2

    conditioned = condition_ordinary_plan_member_features(
        base_features=base,
        road_ids=("r1", "r2"),
        endpoint_ids=(("n1", "n2"), ("n2", "n3")),
        selected_road_ids={"r2"},
        selected_node_ids={"n1", "n3"},
    )

    assert all(
        len(row) == ORDINARY_PLAN_MEMBER_FEATURE_DIM
        for row in conditioned
    )
    assert conditioned[0][24:] == (0.0, 1.0, 0.0, 1.0)
    assert conditioned[1][24:] == (1.0, 0.0, 1.0, 1.0)
