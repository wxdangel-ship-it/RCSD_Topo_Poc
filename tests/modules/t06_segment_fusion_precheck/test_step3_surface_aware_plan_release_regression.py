from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_final_topology_gate as gate_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_final_topology_gate import (
    FINAL_TOPOLOGY_HARD_GATE_REASON,
    block_final_topology_gate_rows,
    final_topology_gate_decision,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_replacement_plan_reader as plan_reader
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


def test_replacement_plan_reader_keeps_geometryless_csv_action(tmp_path, monkeypatch) -> None:
    gpkg_path = tmp_path / "t06_segment_replacement_plan.gpkg"
    csv_path = tmp_path / "t06_segment_replacement_plan.csv"
    gpkg_path.write_bytes(b"placeholder")
    csv_path.write_text(
        "replacement_plan_id,execution_scope,plan_status,execution_action\n"
        "standard:s1,standard_segment,ready,replace\n"
        "special_junction:j1,special_junction_group_internal,ready,include_context\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plan_reader,
        "read_features",
        lambda _path: [
            {
                "properties": {
                    "replacement_plan_id": "standard:s1",
                    "execution_scope": "standard_segment",
                },
                "geometry": {"type": "LineString", "coordinates": []},
            }
        ],
    )

    rows = plan_reader.read_replacement_plan_rows(gpkg_path)

    assert [row["properties"]["replacement_plan_id"] for row in rows] == ["standard:s1", "special_junction:j1"]
    assert rows[1]["geometry"] is None


def test_final_topology_gate_maps_transition_to_all_ready_incident_plans(tmp_path, monkeypatch) -> None:
    (tmp_path / "t06_step3_topology_connectivity_audit.gpkg").write_bytes(b"placeholder")
    monkeypatch.setattr(
        gate_module,
        "read_features",
        lambda _path: [
            {
                "properties": {
                    "counts_in_final_frcsd_topology_fail": True,
                    "audit_status": "fail",
                    "final_topology_category": "segment_transition",
                    "final_topology_object_key": "transition:j1",
                    "audit_layer": "segment_junction_connectivity",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "j1",
                    "swsd_segment_ids": ["s1", "s2", "s_retained"],
                }
            }
        ],
    )
    plan_rows = [
        _plan("standard:s1", "s1"),
        _plan("standard:s2", "s2"),
        _plan("standard:s_blocked", "s_retained", status="blocked"),
    ]

    decision = final_topology_gate_decision(tmp_path, plan_rows)

    assert decision["repairable_failure_count"] == 1
    assert decision["rollback_plan_ids"] == ["standard:s1", "standard:s2"]


def test_final_topology_gate_maps_source1_attachment_by_exact_rcsd_road(tmp_path, monkeypatch) -> None:
    (tmp_path / "t06_step3_topology_connectivity_audit.gpkg").write_bytes(b"placeholder")
    monkeypatch.setattr(
        gate_module,
        "read_features",
        lambda _path: [
            {
                "properties": {
                    "counts_in_final_frcsd_topology_fail": True,
                    "audit_status": "fail",
                    "final_topology_category": "independent_attachment",
                    "final_topology_object_key": "attachment:r2",
                    "audit_layer": "advance_right_endpoint_connectivity",
                    "audit_reason": "advance_right_leaf_endpoint_unattached",
                    "source_mix": "source_1",
                    "frcsd_road_id": "r2",
                    "topology_road_lineage_id": "r2",
                    "swsd_segment_ids": ["s1", "s2"],
                }
            }
        ],
    )
    plan_rows = [
        _plan("standard:s1", "s1", road_ids=["r1"]),
        _plan("standard:s2", "s2", road_ids=["r2"]),
    ]

    decision = final_topology_gate_decision(tmp_path, plan_rows)

    assert decision["rollback_plan_ids"] == ["standard:s2"]


def test_final_topology_gate_keeps_source2_inherited_attachment_visible(tmp_path, monkeypatch) -> None:
    (tmp_path / "t06_step3_topology_connectivity_audit.gpkg").write_bytes(b"placeholder")
    monkeypatch.setattr(
        gate_module,
        "read_features",
        lambda _path: [
            {
                "properties": {
                    "counts_in_final_frcsd_topology_fail": True,
                    "audit_status": "fail",
                    "final_topology_category": "independent_attachment",
                    "audit_layer": "advance_right_endpoint_connectivity",
                    "audit_reason": "advance_right_leaf_endpoint_unattached",
                    "source_mix": "source_2",
                    "frcsd_road_id": "sw1",
                    "topology_road_lineage_id": "sw1",
                    "topology_endpoint_index": 0,
                    "swsd_segment_ids": ["s1"],
                }
            }
        ],
    )

    decision = final_topology_gate_decision(tmp_path, [_plan("standard:s1", "s1")])

    assert decision["repairable_failure_count"] == 0
    assert decision["inherited_failure_count"] == 1
    assert decision["rollback_plan_ids"] == []


def test_block_final_topology_gate_rows_records_explicit_reason() -> None:
    rows = block_final_topology_gate_rows(
        [_plan("standard:s1", "s1"), _plan("standard:s2", "s2")],
        {"standard:s1"},
        failure_node_ids_by_plan_id={"standard:s1": {"n1"}},
    )

    blocked = rows[0]["properties"]
    assert blocked["plan_status"] == "blocked"
    assert blocked["execution_action"] == "hold"
    assert blocked["source_reason"] == FINAL_TOPOLOGY_HARD_GATE_REASON
    assert blocked["final_topology_hard_gate_failure_node_ids"] == ["n1"]
    assert rows[1]["properties"]["plan_status"] == "ready"


def _plan(
    plan_id: str,
    segment_id: str,
    *,
    status: str = "ready",
    road_ids: list[str] | None = None,
) -> dict:
    return {
        "properties": {
            "replacement_plan_id": plan_id,
            "swsd_segment_id": segment_id,
            "plan_status": status,
            "execution_action": "replace" if status == "ready" else "hold",
            "rcsd_road_ids": road_ids or [],
            "risk_flags": [],
        },
        "geometry": None,
    }
