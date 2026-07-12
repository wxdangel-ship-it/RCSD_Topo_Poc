from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_final_topology_metric import (
    annotate_final_frcsd_topology_rows,
    summarize_final_frcsd_topology,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    summarize_topology_connectivity_audit,
)


def _row(layer: str, reason: str, **properties):
    return {
        "properties": {
            "audit_layer": layer,
            "audit_status": "fail",
            "audit_reason": reason,
            **properties,
        },
        "geometry": None,
    }


def test_final_metric_only_counts_transition_and_independent_attachment() -> None:
    rows = [
        _row("segment_internal_connectivity", "segment_relation_failed", swsd_segment_id="failed"),
        _row(
            "segment_internal_connectivity",
            "segment_corridor_coverage_dropped_after_replacement",
            swsd_segment_id="coverage",
        ),
        _row(
            "segment_road_connectivity",
            "segment_road_endpoint_mapping_missing",
            swsd_segment_id="mapping",
            swsd_road_id="sr1",
        ),
        _row(
            "segment_junction_connectivity",
            "junction_incident_segment_mapped_points_diverged",
            swsd_node_id="j1",
            swsd_segment_ids=["s2", "s1"],
        ),
        _row(
            "patch_road_attachment",
            "patch_attachment_mainnode_not_merged",
            swsd_road_id="patch",
            swsd_node_id="n1",
            frcsd_road_id="r1",
        ),
    ]

    summary = summarize_final_frcsd_topology(rows)

    assert summary == {
        "final_frcsd_topology_fail_row_count": 2,
        "final_frcsd_topology_fail_count": 2,
        "final_frcsd_segment_transition_fail_count": 1,
        "final_frcsd_independent_attachment_fail_count": 1,
    }
    assert rows[0]["properties"]["counts_in_final_frcsd_topology_fail"] is False
    assert rows[3]["properties"]["final_topology_category"] == "segment_transition"


def test_advance_right_metric_uses_lineage_and_endpoint_without_collapsing_roads() -> None:
    rows = [
        _row(
            "advance_right_endpoint_connectivity",
            "advance_right_leaf_endpoint_unattached",
            topology_road_lineage_id="road_a",
            topology_endpoint_index=0,
            frcsd_road_id="generated_a1",
        ),
        _row(
            "advance_right_endpoint_connectivity",
            "advance_right_leaf_endpoint_unattached",
            topology_road_lineage_id="road_a",
            topology_endpoint_index=0,
            frcsd_road_id="generated_a2",
        ),
        _row(
            "advance_right_endpoint_connectivity",
            "advance_right_leaf_endpoint_unattached",
            topology_road_lineage_id="road_a",
            topology_endpoint_index=1,
            frcsd_road_id="generated_a2",
        ),
        _row(
            "advance_right_endpoint_connectivity",
            "advance_right_leaf_endpoint_unattached",
            topology_road_lineage_id="road_b",
            topology_endpoint_index=0,
            frcsd_road_id="generated_b",
            swsd_segment_ids=[],
        ),
    ]

    summary = summarize_final_frcsd_topology(rows)

    assert summary["final_frcsd_topology_fail_row_count"] == 4
    assert summary["final_frcsd_topology_fail_count"] == 3
    assert summary["final_frcsd_independent_attachment_fail_count"] == 3
    assert rows[0]["properties"]["final_topology_object_key"] == rows[1]["properties"]["final_topology_object_key"]
    assert rows[0]["properties"]["final_topology_object_key"] != rows[2]["properties"]["final_topology_object_key"]
    assert rows[2]["properties"]["final_topology_object_key"] != rows[3]["properties"]["final_topology_object_key"]


def test_legacy_audit_fail_rows_remain_separate_from_formal_metric() -> None:
    rows = [
        _row("segment_internal_connectivity", "segment_relation_failed", swsd_segment_id="failed"),
        _row(
            "segment_junction_connectivity",
            "junction_incident_segment_mapped_points_diverged",
            swsd_node_id="j1",
            swsd_segment_ids=["s1", "s2"],
        ),
    ]

    summary = summarize_topology_connectivity_audit(rows)

    assert summary["topology_connectivity_fail_count"] == 2
    assert summary["topology_audit_fail_row_count"] == 2
    assert summary["final_frcsd_topology_fail_count"] == 1
    assert summary["final_frcsd_segment_transition_fail_count"] == 1


def test_annotation_clears_formal_metric_when_fail_is_downgraded() -> None:
    rows = [
        _row(
            "segment_junction_connectivity",
            "junction_incident_segment_mapped_points_diverged",
            swsd_node_id="j1",
            swsd_segment_ids=["s1", "s2"],
        )
    ]
    annotate_final_frcsd_topology_rows(rows)
    rows[0]["properties"]["audit_status"] = "warn"
    rows[0]["properties"]["audit_reason"] = "junction_incident_segments_share_t05_semantic_group"

    annotate_final_frcsd_topology_rows(rows)

    assert rows[0]["properties"]["counts_in_final_frcsd_topology_fail"] is False
    assert rows[0]["properties"]["final_topology_object_key"] == ""
