from __future__ import annotations

from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_compact_target_portal import (
    restore_compact_semantic_target_connectivity,
)


def test_compact_semantic_targets_restore_raw_surface_connectivity() -> None:
    raw = box(0, 0, 20, 10)
    split = box(0, 0, 8, 10).union(box(12, 0, 20, 10))
    terminals = {"left": Point(5, 5), "right": Point(15, 5)}

    result, portal, audit = restore_compact_semantic_target_connectivity(
        surface=split,
        raw_road_surface=raw,
        allowed_surface=raw,
        target_geometries=(Point(8, 5), Point(12, 5)),
        terminals=terminals,
        association_reason="association_support_only",
        input_geometry_invalid_feature_count=0,
        bridge_half_width_m=2.0,
    )

    assert result is not None
    assert portal is not None
    assert audit["applied"] is True
    assert audit["after"]["equivalent"] is True
    assert audit["silent_fix"] is False


def test_distant_semantic_targets_do_not_bypass_compact_gate() -> None:
    raw = box(0, 0, 60, 10)
    split = box(0, 0, 8, 10).union(box(52, 0, 60, 10))
    terminals = {"left": Point(5, 5), "right": Point(55, 5)}

    result, portal, audit = restore_compact_semantic_target_connectivity(
        surface=split,
        raw_road_surface=raw,
        allowed_surface=raw,
        target_geometries=(Point(8, 5), Point(52, 5)),
        terminals=terminals,
        association_reason="association_support_only",
        input_geometry_invalid_feature_count=0,
        bridge_half_width_m=2.0,
    )

    assert result.equals(split)
    assert portal is None
    assert audit["applied"] is False
    assert "semantic_target_span_above_gate" in audit["eligibility_failures"]
