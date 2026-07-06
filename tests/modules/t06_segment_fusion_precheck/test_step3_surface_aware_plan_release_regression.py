from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_aware_plan_release import (
    _filter_visual_topology_rollback_plan_ids,
    _visual_conflict_rollback_plan_ids,
    _visual_conflict_unconditional_rollback_plan_ids,
)


def test_visual_conflict_directed_path_fail_rolls_back_without_uncovered_geometry(tmp_path) -> None:
    added_fail_keys = {
        (
            "segment_road_connectivity",
            "s_visual",
            "",
            "",
            "segment_road_directed_path_missing",
        )
    }
    released = [{"plan_id": "standard:s_visual", "segment_id": "s_visual", "group_segment_ids": ["s_visual"]}]
    plan_rows = [
        {
            "properties": {
                "replacement_plan_id": "standard:s_visual",
                "swsd_uncovered_by_rcsd_ratio": 0.0,
            }
        }
    ]

    rollback_ids = _visual_conflict_rollback_plan_ids(
        added_fail_keys,
        released,
        tmp_path / "unused_swsd_segment.gpkg",
        incident_segments_by_node={},
    )
    unconditional_ids = _visual_conflict_unconditional_rollback_plan_ids(
        added_fail_keys,
        released,
        tmp_path / "unused_swsd_segment.gpkg",
        incident_segments_by_node={},
    )

    assert _filter_visual_topology_rollback_plan_ids(rollback_ids, plan_rows) == set()
    assert _filter_visual_topology_rollback_plan_ids(
        rollback_ids,
        plan_rows,
        unconditional_plan_ids=unconditional_ids,
    ) == {"standard:s_visual"}
