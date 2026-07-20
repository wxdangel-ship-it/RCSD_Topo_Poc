from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.anchor_portals import (
    AnchorRecord,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_graph,
    build_node_context,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.surface_portal_carrier import (
    evaluate_t07_road_surface_carrier,
)


def _anchor(target_id: str, base_id: str) -> AnchorRecord:
    return AnchorRecord(
        target_id=target_id,
        base_id=base_id,
        source_module="T07",
        reason="unit_test",
        scene="",
        grouped_node_ids=(base_id,),
    )


def _evaluate(
    roads: list[dict[str, object]],
    nodes: list[tuple[str, Point]],
    *,
    reference: LineString | None = None,
):
    node_frame = gpd.GeoDataFrame(
        {
            "id": [node_id for node_id, _ in nodes],
            "geometry": [point for _, point in nodes],
        },
        crs="EPSG:3857",
    )
    road_frame = gpd.GeoDataFrame(roads, crs="EPSG:3857")
    canonicalizer, _, raw_points = build_node_context(node_frame)
    graph = build_graph(road_frame, canonicalizer)
    return evaluate_t07_road_surface_carrier(
        graph=graph,
        canonicalizer=canonicalizer,
        raw_node_points=raw_points,
        source_anchor=_anchor("p0", "a"),
        target_anchor=_anchor("p1", "b"),
        source_surface=box(-2, -2, 2, 2),
        target_surface=box(98, -2, 102, 2),
        source_surface_id="surface0",
        target_surface_id="surface1",
        source_swsd_point=Point(0, 0),
        target_swsd_point=Point(100, 0),
        reference_geometry=reference or LineString([(0, 0), (100, 0)]),
        reference_length_m=100.0,
        config=AuditConfig(),
    )


def test_surface_intersections_preserve_road_direction_and_contact_order() -> None:
    nodes = [("a", Point(0, 0)), ("b", Point(100, 0))]
    forward = _evaluate(
        [
            {
                "id": "road",
                "snodeid": "a",
                "enodeid": "b",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        nodes,
    )
    reverse = _evaluate(
        [
            {
                "id": "road",
                "snodeid": "a",
                "enodeid": "b",
                "direction": 3,
                "source": 1,
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        nodes,
    )

    assert forward.evidence["accepted_equivalent_carrier"] is True
    assert forward.evidence["road_ids"] == ["road"]
    assert forward.evidence["source_access_kind"] == "road_surface_intersection"
    assert forward.evidence["target_access_kind"] == "road_surface_intersection"
    assert reverse.evidence["accepted_equivalent_carrier"] is False
    assert reverse.evidence["rejection_reason"] == "surface_portal_path_missing"


def test_anchor_one_hop_frontier_accepts_distance_risks_as_audit_only() -> None:
    result = _evaluate(
        [
            {
                "id": "carrier",
                "snodeid": "a",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 0), (100, 60)]),
            },
            {
                "id": "target_access",
                "snodeid": "b",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(100, 0), (100, 60)]),
            },
        ],
        [
            ("a", Point(0, 0)),
            ("b", Point(100, 0)),
            ("frontier", Point(100, 60)),
        ],
    )

    assert result.evidence["accepted_equivalent_carrier"] is True
    assert result.evidence["road_ids"] == ["carrier"]
    assert result.evidence["target_access_kind"] == "anchor_one_hop_frontier"
    assert result.evidence["target_access_road_ids"] == ["target_access"]
    assert result.evidence["max_corridor_distance_m"] > 50.0
    assert result.evidence["distance_gate_role"] == "audit_only"


def test_path_length_remains_a_hard_equivalence_gate() -> None:
    result = _evaluate(
        [
            {
                "id": "carrier",
                "snodeid": "a",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 0), (0, 200), (300, 200)]),
            },
            {
                "id": "target_access",
                "snodeid": "b",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(100, 0), (300, 200)]),
            },
        ],
        [
            ("a", Point(0, 0)),
            ("b", Point(100, 0)),
            ("frontier", Point(300, 200)),
        ],
    )

    assert result.evidence["accepted_equivalent_carrier"] is False
    assert result.evidence["rejection_reason"] == "surface_portal_path_not_length_equivalent"
    assert result.evidence["length_ratio"] == pytest.approx(4.98)


def test_two_unoriented_frontiers_cannot_replace_road_surface_contact() -> None:
    result = _evaluate(
        [
            {
                "id": "source_access",
                "snodeid": "source_frontier",
                "enodeid": "a",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 20), (0, 0)]),
            },
            {
                "id": "carrier",
                "snodeid": "source_frontier",
                "enodeid": "target_frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 20), (100, 20)]),
            },
            {
                "id": "target_access",
                "snodeid": "b",
                "enodeid": "target_frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(100, 0), (100, 20)]),
            },
        ],
        [
            ("a", Point(0, 0)),
            ("b", Point(100, 0)),
            ("source_frontier", Point(0, 20)),
            ("target_frontier", Point(100, 20)),
        ],
    )

    assert result.evidence["accepted_equivalent_carrier"] is False
    assert result.evidence["rejection_reason"] == "surface_portal_path_missing"


def test_one_hop_frontier_support_road_must_belong_to_the_surface() -> None:
    result = _evaluate(
        [
            {
                "id": "carrier",
                "snodeid": "a",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(0, 0), (100, 60)]),
            },
            {
                "id": "remote_target_access",
                "snodeid": "b",
                "enodeid": "frontier",
                "direction": 2,
                "source": 1,
                "geometry": LineString([(200, 200), (300, 200)]),
            },
        ],
        [
            ("a", Point(0, 0)),
            ("b", Point(100, 0)),
            ("frontier", Point(100, 60)),
        ],
    )

    assert result.evidence["accepted_equivalent_carrier"] is False
    assert result.evidence["rejection_reason"] == "surface_portal_path_missing"
