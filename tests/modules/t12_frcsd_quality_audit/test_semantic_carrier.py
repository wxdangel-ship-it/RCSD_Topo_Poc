from __future__ import annotations

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.anchor_portals import (
    AnchorRecord,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    GraphBundle,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import PathResult
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.semantic_carrier import (
    evaluate_portal_constrained_semantic_carrier,
)


def test_zero_length_canonical_overlap_is_not_a_physical_carrier() -> None:
    anchor = AnchorRecord(
        target_id="target",
        base_id="portal",
        source_module="T03",
        reason="",
        scene="",
        grouped_node_ids=("portal",),
    )
    result = evaluate_portal_constrained_semantic_carrier(
        path=PathResult(
            start="semantic",
            end="semantic",
            node_ids=("semantic",),
            road_ids=(),
            length_m=0.0,
        ),
        metrics={"accepted_equivalent_carrier": True},
        graph=GraphBundle(directed={}, incoming={}, undirected={}, edges={}),
        start_portals=[{"raw_id": "portal"}],
        end_portals=[{"raw_id": "portal"}],
        source_anchor=anchor,
        target_anchor=anchor,
        source_truth_surface=None,
        target_truth_surface=None,
        canonicalizer=NodeCanonicalizer(
            aliases={"portal": "semantic"},
            semantic_node_ids=frozenset({"semantic"}),
        ),
        raw_node_points={"portal": Point(0, 0)},
        portal_radius_m=50.0,
    )

    assert result["accepted_equivalent_carrier"] is False
    assert result["rejection_reason"] == "semantic_path_has_no_physical_road"
