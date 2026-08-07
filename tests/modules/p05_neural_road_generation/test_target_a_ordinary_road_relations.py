from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_relations import (
    ROAD_RELATION_FEATURE_NAMES,
    build_sparse_road_relation_rows,
)


def test_sparse_road_relations_capture_near_nonshared_connectors() -> None:
    rows = build_sparse_road_relation_rows(
        [
            {
                "road_id": "main",
                "source": "RCSD",
                "start_node_id": "a",
                "end_node_id": "b",
            },
            {
                "road_id": "connector",
                "source": "RCSD",
                "start_node_id": "c",
                "end_node_id": "d",
            },
            {
                "road_id": "far",
                "source": "RCSD",
                "start_node_id": "e",
                "end_node_id": "f",
            },
        ],
        raw_road_by_id={
            "main": SimpleNamespace(
                geometry=LineString([(0.0, 0.0), (10.0, 0.0)])
            ),
            "connector": SimpleNamespace(
                geometry=LineString([(9.5, 0.4), (9.5, 4.0)])
            ),
            "far": SimpleNamespace(
                geometry=LineString([(100.0, 0.0), (110.0, 0.0)])
            ),
        },
        swsd_road_by_id={},
    )
    assert len(rows) == 1
    assert (rows[0]["left_index"], rows[0]["right_index"]) == (0, 1)
    values = dict(
        zip(ROAD_RELATION_FEATURE_NAMES, rows[0]["feature_values"])
    )
    assert values["shares_endpoint_node_id"] == 0.0
    assert values["distance_le_1m"] == 1.0
    assert values["both_rcsd"] == 1.0
    assert values["orientation_known"] == 1.0
