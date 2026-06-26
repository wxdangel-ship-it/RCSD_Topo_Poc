from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import read_features, write_feature_triplet
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import (
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_FRCSD_NODE_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_topology_audit import (
    SURFACE_TOPOLOGY_AUDIT_STEM,
    _apply_step2_plan_relation_node_map_updates,
    _load_step2_dropped_junc_nodes,
    _load_step2_optional_junc_mappings,
    run_surface_topology_postprocess,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
)


def test_surface_topology_postprocess_closes_safe_cross_source_junction(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    surface_path = tmp_path / "junction_anchor_surface.gpkg"
    t04_audit_path = tmp_path / "divmerge_virtual_anchor_surface_audit.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "20", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(10, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1", "s2"]',
                    "frcsd_node_ids": '["20", "2"]',
                    "max_pairwise_distance_m": 10.0,
                },
                Point(5, 0),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"}],
        [LineString([(10, 0), (20, 0)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(surface_path, [{"surface_id": "j1", "patch_id": "100"}], [Polygon([(-1, -1), (11, -1), (11, 1), (-1, 1)])])
    _write_layer(t04_audit_path, [], [])
    _write_empty_step3_dependencies(step_root)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t05_surface_path=surface_path,
        t04_audit_path=t04_audit_path,
        apply_closure=True,
    )

    assert summary["surface_topology_auto_closed_count"] == 1
    assert summary["surface_topology_fail_count"] == 0
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "20"
    surface_rows = read_features(step_root / f"{SURFACE_TOPOLOGY_AUDIT_STEM}.gpkg")
    assert surface_rows[0]["properties"]["audit_reason"] == "auto_closed"


def test_surface_topology_postprocess_uses_t07_one_to_one_fallback(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    t07_surface_path = tmp_path / "t07_rcsdintersection_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "0", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(10, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(10, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(10, 0), (20, 0)]), LineString([(10, 0), (20, 1)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        t07_surface_path,
        [
            {
                "id": "20",
                "target_id": "2",
                "representative_node_id": "2",
                "mainnodeid": "2",
                "base_id_candidate": "20",
                "source_rcsdintersection_id": "20",
                "matched_rcsdintersection_ids": "20",
                "final_state": "accepted",
            }
        ],
        [Polygon([(9, -1), (11, -1), (11, 1), (9, 1)])],
    )
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t07_surface_path=t07_surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_surface_1v1_closed_count"] == 1
    assert summary["surface_topology_single_node_default_mapped_count"] == 0
    assert summary["surface_topology_relation_node_map_update_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "2"
    assert str(nodes["20"]["mainnodeid"]) == "2"
    relation = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")[0]["properties"]
    node_map = json.loads(relation["swsd_to_frcsd_node_map"])
    assert node_map[0]["frcsd_node_ids"] == ["20"]
    assert node_map[0]["mapping_status"] == "surface_1v1_fallback"


def test_surface_topology_postprocess_uses_t07_mainnode_alias_fallback(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    t07_surface_path = tmp_path / "t07_rcsdintersection_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "21", "mainnodeid": "20", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(10, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(10, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"}],
        [LineString([(10, 0), (20, 0)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        t07_surface_path,
        [
            {
                "id": "20",
                "target_id": "2",
                "representative_node_id": "2",
                "mainnodeid": "2",
                "base_id_candidate": "20",
                "source_rcsdintersection_id": "20",
                "final_state": "accepted",
            }
        ],
        [Polygon([(9, -1), (11, -1), (11, 1), (9, 1)])],
    )
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t07_surface_path=t07_surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_surface_1v1_closed_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "20"
    relation = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")[0]["properties"]
    node_map = json.loads(relation["swsd_to_frcsd_node_map"])
    assert node_map[0]["frcsd_node_ids"] == ["21"]


def test_surface_topology_postprocess_closes_existing_cross_source_one_to_one_with_surface(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    surface_path = tmp_path / "junction_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "20", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(5, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1", "s2"]',
                    "frcsd_node_ids": '["20", "2"]',
                    "max_pairwise_distance_m": 5.0,
                },
                Point(5, 0),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(5, 0), (20, 0)]), LineString([(5, 0), (20, 1)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(surface_path, [{"surface_id": "j1", "patch_id": ""}], [Polygon([(-1, -1), (6, -1), (6, 1), (-1, 1)])])
    _write_empty_step3_dependencies(step_root)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t05_surface_path=surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_existing_cross_source_1v1_closed_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "20"


def test_surface_topology_postprocess_uses_t04_patch_one_to_one_evidence(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    t04_surface_path = tmp_path / "divmerge_virtual_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "20", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(10, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1", "s2"]',
                    "frcsd_node_ids": '["20", "2"]',
                    "max_pairwise_distance_m": 10.0,
                },
                Point(10, 0),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(10, 0), (20, 0)]), LineString([(10, 0), (20, 1)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        t04_surface_path,
        [
            {
                "anchor_id": "2",
                "case_id": "2",
                "mainnodeid": "2",
                "patch_id": "100",
                "final_state": "accepted",
            }
        ],
        [Polygon([(9, -1), (11, -1), (11, 1), (9, 1)])],
    )
    _write_empty_step3_dependencies(step_root)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t04_surface_path=t04_surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_t04_patch_1v1_closed_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "20"


def test_surface_topology_postprocess_does_not_close_distant_t04_patch_one_to_one(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    t04_surface_path = tmp_path / "divmerge_virtual_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "20", "source": 1}, Point(0, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(25, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s1", "s2"]',
                    "frcsd_node_ids": '["20", "2"]',
                    "max_pairwise_distance_m": 25.0,
                },
                Point(25, 0),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(25, 0), (35, 0)]), LineString([(25, 0), (35, 1)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        t04_surface_path,
        [
            {
                "anchor_id": "2",
                "case_id": "2",
                "mainnodeid": "2",
                "patch_id": "100",
                "final_state": "accepted",
            }
        ],
        [Polygon([(24, -1), (26, -1), (26, 1), (24, 1)])],
    )
    _write_empty_step3_dependencies(step_root)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t04_surface_path=t04_surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_t04_patch_1v1_closed_count"] == 0
    assert summary["surface_topology_fail_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "2"


def test_surface_topology_postprocess_uses_t04_rejected_node_one_to_one_evidence(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    t04_audit_path = tmp_path / "divmerge_virtual_anchor_surface_audit.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "30", "mainnodeid": "0", "source": 1}, Point(9, 0)),
            _feature({"id": "3", "mainnodeid": "3", "source": 2}, Point(0, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "3",
                    "swsd_segment_ids": '["s_replaced", "s_retained"]',
                    "frcsd_node_ids": '["3"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(0, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "3", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_retained",
                    "relation_status": "retained_swsd",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "3", "frcsd_node_ids": ["3"], "mapping_status": "identity"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (0, 10)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "3", "enodeid": "4", "patch_id": "100"}],
        [LineString([(0, 0), (0, 10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        t04_audit_path,
        [
            {
                "anchor_id": "3",
                "case_id": "3",
                "publish_target": "rejected_index",
                "reject_reason": "multi_component_result",
                "required_rcsd_node_ids": "30",
                "required_rcsd_node_count": 1,
                "hard_must_cover_ok": True,
                "forbidden_overlap": False,
                "cut_violation": False,
                "post_cleanup_forbidden_ok": True,
                "post_cleanup_terminal_cut_ok": True,
                "post_cleanup_lateral_limit_ok": True,
                "post_cleanup_must_cover_ok": True,
                "fallback_overexpansion_detected": False,
            }
        ],
        [Point(0, 0)],
    )
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t04_audit_path=t04_audit_path,
        apply_closure=True,
    )

    assert summary["surface_topology_fail_count"] == 0
    assert summary["surface_topology_t04_rejected_node_1v1_closed_count"] == 1
    assert summary["surface_topology_blocked_by_t04_reject_count"] == 0
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["3"]["mainnodeid"]) == "3"
    assert str(nodes["30"]["mainnodeid"]) == "3"
    relation_rows = {
        item["properties"]["swsd_segment_id"]: item["properties"]
        for item in read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    }
    replaced_map = json.loads(relation_rows["s_replaced"]["swsd_to_frcsd_node_map"])
    retained_map = json.loads(relation_rows["s_retained"]["swsd_to_frcsd_node_map"])
    assert replaced_map[0]["frcsd_node_ids"] == ["30"]
    assert replaced_map[0]["mapping_status"] == "t04_rejected_node_1v1_fallback"
    assert "t04_rejected_node_1v1_fallback_node_map" in json.loads(relation_rows["s_replaced"]["risk_flags"])
    assert retained_map[0]["frcsd_node_ids"] == ["3"]
    surface_rows = read_features(step_root / f"{SURFACE_TOPOLOGY_AUDIT_STEM}.gpkg")
    assert surface_rows[0]["properties"]["audit_reason"] == "auto_closed_t04_rejected_node_1v1"


def test_surface_topology_postprocess_closes_relation_mapped_retained_boundary(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "200", "source": 1}, Point(10, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(0, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s_replaced", "s_retained"]',
                    "frcsd_node_ids": '["20", "2"]',
                    "max_pairwise_distance_m": 10.0,
                },
                Point(0, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": ["20"], "mapping_status": "mapped"}],
                    "risk_flags": [],
                },
                LineString([(10, 0), (15, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_retained",
                    "relation_status": "retained_swsd",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (0, 10)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(0, 0), (0, 10)]), LineString([(0, 0), (0, -10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        apply_closure=True,
    )

    assert summary["surface_topology_fail_count"] == 0
    assert summary["surface_topology_relation_mapped_boundary_1v1_closed_count"] == 1
    assert summary["surface_topology_blocked_by_patch_conflict_count"] == 0
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "200"
    assert str(nodes["20"]["mainnodeid"]) == "200"
    surface_rows = read_features(step_root / f"{SURFACE_TOPOLOGY_AUDIT_STEM}.gpkg")
    assert surface_rows[0]["properties"]["audit_reason"] == "auto_closed_relation_mapped_boundary_1v1"


def test_surface_topology_postprocess_uses_step2_optional_junc_one_to_one_mapping(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    step2_root = tmp_path / "step2_extract_rcsd_segments"
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    surface_path = tmp_path / "junction_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "30", "mainnodeid": "300", "source": 1}, Point(0, 0)),
            _feature({"id": "3", "mainnodeid": "3", "source": 2}, Point(10, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "3",
                    "swsd_segment_ids": '["s1"]',
                    "frcsd_node_ids": '["3"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(10, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "3", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            )
        ],
    )
    write_feature_triplet(
        step_root=step2_root,
        stem=STEP2_FAILURE_BUSINESS_AUDIT_STEM,
        fieldnames=["swsd_segment_id", "optional_junc_nodes", "optional_junc_rcsd_nodes", "rcsd_junc_nodes"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "optional_junc_nodes": ["4", "3"],
                    "optional_junc_rcsd_nodes": ["30"],
                    "rcsd_junc_nodes": ["40", "30"],
                },
                LineString([(0, 0), (10, 0)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "3", "enodeid": "4", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "3", "enodeid": "5", "patch_id": "200"},
        ],
        [LineString([(10, 0), (20, 0)]), LineString([(10, 0), (20, 1)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(surface_path, [{"surface_id": "j1", "patch_id": ""}], [Polygon([(9, -1), (11, -1), (11, 1), (9, 1)])])
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t05_surface_path=surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_step2_junc_1v1_closed_count"] == 0
    assert summary["surface_topology_relation_node_map_update_count"] == 1
    relation = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")[0]["properties"]
    node_map = json.loads(relation["swsd_to_frcsd_node_map"])
    assert node_map[0]["frcsd_node_ids"] == ["30"]
    assert node_map[0]["mapping_status"] == "step2_optional_junc_plan_map"


def test_step2_plan_relation_preprocess_realigns_optional_and_dropped_junctions(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    step2_root = tmp_path / "step2_extract_rcsd_segments"
    step2_root.mkdir()

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "drop", "frcsd_node_ids": ["r1"], "node_role": "junc_node", "mapping_status": "mapped"},
                        {"swsd_node_id": "a", "frcsd_node_ids": ["r2"], "node_role": "junc_node", "mapping_status": "mapped"},
                        {"swsd_node_id": "b", "frcsd_node_ids": ["r3"], "node_role": "junc_node", "mapping_status": "mapped"},
                    ],
                    "risk_flags": [],
                },
                LineString([(0, 0), (1, 0)]),
            )
        ],
    )
    write_feature_triplet(
        step_root=step2_root,
        stem=STEP2_REPLACEMENT_PLAN_STEM,
        fieldnames=[
            "swsd_segment_id",
            "optional_junc_nodes",
            "optional_junc_rcsd_nodes",
            "dropped_junc_nodes",
        ],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "optional_junc_nodes": ["a", "b"],
                    "optional_junc_rcsd_nodes": ["r1", "r2"],
                    "dropped_junc_nodes": ["drop"],
                },
                LineString([(0, 0), (1, 0)]),
            )
        ],
    )

    updated = _apply_step2_plan_relation_node_map_updates(
        step_root=step_root,
        step2_junc_mappings=_load_step2_optional_junc_mappings(step_root),
        step2_dropped_junc_nodes=_load_step2_dropped_junc_nodes(step_root),
    )

    assert updated == 1
    relation = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")[0]["properties"]
    node_map = {item["swsd_node_id"]: item for item in json.loads(relation["swsd_to_frcsd_node_map"])}
    assert node_map["drop"]["frcsd_node_ids"] == ["drop"]
    assert node_map["drop"]["mapping_status"] == "identity_dropped_junc_not_consumed"
    assert node_map["a"]["frcsd_node_ids"] == ["r1"]
    assert node_map["a"]["mapping_status"] == "step2_optional_junc_plan_map"
    assert node_map["b"]["frcsd_node_ids"] == ["r2"]
    assert "dropped_junc_retained_swsd_node_map" in json.loads(relation["risk_flags"])
    assert "step2_optional_junc_plan_node_map" in json.loads(relation["risk_flags"])


def test_step2_junc_loader_uses_step3_summary_input_path(tmp_path: Path) -> None:
    step_root = tmp_path / "case_run" / "step3_segment_replacement"
    step_root.mkdir(parents=True)
    step2_root = tmp_path / "real_t06" / "step2_extract_rcsd_segments"
    step2_root.mkdir(parents=True)
    (step_root / "t06_step3_summary.json").write_text(
        json.dumps({"input_paths": {"step2_replaceable_path": str(step2_root / "t06_rcsd_segment_replaceable.gpkg")}}),
        encoding="utf-8",
    )
    write_feature_triplet(
        step_root=step2_root,
        stem=STEP2_REPLACEMENT_PLAN_STEM,
        fieldnames=["swsd_segment_id", "dropped_junc_nodes"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "dropped_junc_nodes": ["drop"],
                },
                LineString([(0, 0), (1, 0)]),
            )
        ],
    )

    assert _load_step2_dropped_junc_nodes(step_root) == {"s1": ["drop"]}


def test_surface_topology_postprocess_remaps_surface_nearest_multi_candidate(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"
    surface_path = tmp_path / "junction_anchor_surface.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "near", "mainnodeid": "near", "source": 1}, Point(1.2, 0)),
            _feature({"id": "far", "mainnodeid": "far", "source": 1}, Point(30, 0)),
            _feature({"id": "9", "mainnodeid": "9", "source": 2}, Point(0, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "swsd_node_id": "9",
                    "swsd_segment_ids": '["s_near", "s_far", "s_ret"]',
                    "frcsd_node_ids": '["near", "far", "9"]',
                    "max_pairwise_distance_m": 30.0,
                },
                Point(0, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_near",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "9", "frcsd_node_ids": ["near"], "mapping_status": "mapped"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (1, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_far",
                    "relation_status": "replaced",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "9", "frcsd_node_ids": ["far"], "mapping_status": "mapped"}],
                    "risk_flags": [],
                },
                LineString([(1, 0), (30, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_ret",
                    "relation_status": "retained_swsd",
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "9", "frcsd_node_ids": ["9"], "mapping_status": "identity"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (0, 1)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "9", "enodeid": "10", "patch_id": "100"}],
        [LineString([(0, 0), (20, 0)])],
    )
    _write_layer(swsd_segment_path, [], [])
    _write_layer(
        surface_path,
        [{"surface_id": "j9", "mainnodeid": "9", "patch_id": "100"}],
        [Polygon([(-1, -1), (2, -1), (2, 1), (-1, 1)])],
    )
    _write_empty_step3_dependencies(step_root, include_relation=False)

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t05_surface_path=surface_path,
        apply_closure=True,
    )

    assert summary["surface_topology_surface_nearest_multi_candidate_closed_count"] == 1
    assert summary["surface_topology_relation_node_map_update_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["9"]["mainnodeid"]) == "near"
    assert str(nodes["far"]["mainnodeid"]) == "far"
    relations = {
        item["properties"]["swsd_segment_id"]: item["properties"]
        for item in read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    }
    far_map = json.loads(relations["s_far"]["swsd_to_frcsd_node_map"])
    retained_map = json.loads(relations["s_ret"]["swsd_to_frcsd_node_map"])
    assert far_map[0]["frcsd_node_ids"] == ["near"]
    assert far_map[0]["mapping_status"] == "surface_nearest_multi_candidate_fallback"
    assert retained_map[0]["frcsd_node_ids"] == ["9"]


def test_surface_topology_postprocess_uses_selected_replacement_endpoint_fallback(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "200", "source": 1}, Point(1, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(0, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_frcsd_road",
        fieldnames=["id", "source", "snodeid", "enodeid", "direction"],
        features=[_feature({"id": "rr1", "source": 1, "snodeid": "20", "enodeid": "21", "direction": 2}, LineString([(1, 0), (10, 0)]))],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s_replaced", "s_retained"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(0, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "frcsd_road_ids", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["rr1"],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_retained",
                    "relation_status": "retained_swsd",
                    "frcsd_road_ids": [],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (0, 10)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [
            {"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"},
            {"id": "sr2", "source": 2, "snodeid": "2", "enodeid": "4", "patch_id": "200"},
        ],
        [LineString([(0, 0), (0, 10)]), LineString([(0, 0), (0, -10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_advance_right_attachment_audit",
        fieldnames=["swsd_node_id", "action", "action_reason"],
        features=[],
    )

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        apply_closure=True,
    )

    assert summary["surface_topology_selected_replacement_endpoint_closed_count"] == 1
    assert summary["surface_topology_blocked_by_patch_conflict_count"] == 0
    assert summary["surface_topology_relation_node_map_update_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "200"
    relations = {
        item["properties"]["swsd_segment_id"]: item["properties"]
        for item in read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    }
    replaced_map = json.loads(relations["s_replaced"]["swsd_to_frcsd_node_map"])
    retained_map = json.loads(relations["s_retained"]["swsd_to_frcsd_node_map"])
    assert replaced_map[0]["frcsd_node_ids"] == ["20"]
    assert replaced_map[0]["mapping_status"] == "selected_replacement_endpoint_fallback"
    assert retained_map[0]["frcsd_node_ids"] == ["2"]


def test_surface_topology_postprocess_uses_swsd_default_mainnode_for_selected_endpoint(
    tmp_path: Path,
) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source"],
        features=[
            _feature({"id": "20", "mainnodeid": "0", "source": 1}, Point(1, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(0, 0)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_frcsd_road",
        fieldnames=["id", "source", "snodeid", "enodeid", "direction"],
        features=[_feature({"id": "rr1", "source": 1, "snodeid": "20", "enodeid": "21", "direction": 2}, LineString([(1, 0), (10, 0)]))],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s_replaced", "s_retained"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(0, 0),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "frcsd_road_ids", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["rr1"],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_retained",
                    "relation_status": "retained_swsd",
                    "frcsd_road_ids": [],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": ["2"], "mapping_status": "identity"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (0, 10)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"}],
        [LineString([(0, 0), (0, 10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_advance_right_attachment_audit",
        fieldnames=["swsd_node_id", "action", "action_reason"],
        features=[],
    )

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        apply_closure=True,
    )

    assert summary["surface_topology_selected_replacement_endpoint_closed_count"] == 1
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    assert str(nodes["2"]["mainnodeid"]) == "2"
    assert str(nodes["20"]["mainnodeid"]) == "2"
    relations = {
        item["properties"]["swsd_segment_id"]: item["properties"]
        for item in read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    }
    replaced_map = json.loads(relations["s_replaced"]["swsd_to_frcsd_node_map"])
    retained_map = json.loads(relations["s_retained"]["swsd_to_frcsd_node_map"])
    assert replaced_map[0]["frcsd_node_ids"] == ["20"]
    assert replaced_map[0]["mapping_status"] == "selected_replacement_endpoint_fallback"
    assert retained_map[0]["frcsd_node_ids"] == ["2"]


def test_surface_topology_postprocess_materializes_selected_replacement_midroad_node(
    tmp_path: Path,
) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source", "t06_generated_reason"],
        features=[
            _feature({"id": "100", "mainnodeid": "100", "source": 1}, Point(0, 0)),
            _feature({"id": "101", "mainnodeid": "101", "source": 1}, Point(10, 0)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(5, 0.5)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_frcsd_road",
        fieldnames=["id", "source", "snodeid", "enodeid", "direction", "t06_split_original_road_id", "t06_split_reason"],
        features=[
            _feature(
                {"id": "rr1", "source": 1, "snodeid": "100", "enodeid": "101", "direction": 2},
                LineString([(0, 0), (10, 0)]),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s_replaced"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(5, 0.5),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "frcsd_road_ids", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["rr1"],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 0), (10, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "s_shared",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["rr1"],
                    "swsd_to_frcsd_node_map": [],
                    "risk_flags": [],
                },
                LineString([(0, -1), (10, -1)]),
            ),
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"}],
        [LineString([(5, 0.5), (5, 10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_advance_right_attachment_audit",
        fieldnames=["swsd_node_id", "action", "action_reason"],
        features=[],
    )

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        apply_closure=True,
    )

    assert summary["surface_topology_selected_replacement_midroad_closed_count"] == 1
    assert summary["surface_topology_selected_replacement_midroad_materialized_count"] == 1
    assert summary["surface_topology_relation_node_map_update_count"] == 2
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    generated_nodes = [
        props for props in nodes.values() if props.get("t06_generated_reason") == "surface_topology_selected_replacement_midroad"
    ]
    assert len(generated_nodes) == 1
    generated_node_id = str(generated_nodes[0]["id"])
    assert str(nodes["2"]["mainnodeid"]) == generated_node_id
    roads = read_features(step_root / "t06_frcsd_road.gpkg")
    split_roads = [item["properties"] for item in roads if item["properties"].get("t06_split_original_road_id") == "rr1"]
    assert len(split_roads) == 2
    assert generated_node_id in {
        str(split_roads[0]["enodeid"]),
        str(split_roads[1]["snodeid"]),
    }
    relations = {
        item["properties"]["swsd_segment_id"]: item["properties"]
        for item in read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    }
    relation = relations["s_replaced"]
    node_map = json.loads(relation["swsd_to_frcsd_node_map"])
    assert node_map[0]["frcsd_node_ids"] == [generated_node_id]
    assert node_map[0]["mapping_status"] == "selected_replacement_midroad_projection"
    split_ids = [str(split_roads[0]["id"]), str(split_roads[1]["id"])]
    assert json.loads(relation["frcsd_road_ids"]) == split_ids
    assert json.loads(relations["s_shared"]["frcsd_road_ids"]) == split_ids


def test_surface_topology_postprocess_materializes_parallel_selected_midroad_nodes(
    tmp_path: Path,
) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    swsd_roads_path = tmp_path / "roads.gpkg"
    swsd_segment_path = tmp_path / "segment.gpkg"

    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_FRCSD_NODE_STEM,
        fieldnames=["id", "mainnodeid", "source", "t06_generated_reason"],
        features=[
            _feature({"id": "100", "mainnodeid": "100", "source": 1}, Point(0, 0)),
            _feature({"id": "101", "mainnodeid": "101", "source": 1}, Point(10, 0)),
            _feature({"id": "102", "mainnodeid": "102", "source": 1}, Point(0, 4)),
            _feature({"id": "103", "mainnodeid": "103", "source": 1}, Point(10, 4)),
            _feature({"id": "2", "mainnodeid": "2", "source": 2}, Point(5, 2)),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_frcsd_road",
        fieldnames=["id", "source", "snodeid", "enodeid", "direction", "t06_split_original_road_id", "t06_split_reason"],
        features=[
            _feature({"id": "rr1", "source": 1, "snodeid": "100", "enodeid": "101", "direction": 2}, LineString([(0, 0), (10, 0)])),
            _feature({"id": "rr2", "source": 1, "snodeid": "102", "enodeid": "103", "direction": 2}, LineString([(0, 4), (10, 4)])),
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
        features=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapping_missing",
                    "swsd_node_id": "2",
                    "swsd_segment_ids": '["s_replaced"]',
                    "frcsd_node_ids": '["2"]',
                    "max_pairwise_distance_m": 0.0,
                },
                Point(5, 2),
            )
        ],
    )
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_swsd_frcsd_segment_relation",
        fieldnames=["swsd_segment_id", "relation_status", "frcsd_road_ids", "swsd_to_frcsd_node_map", "risk_flags"],
        features=[
            _feature(
                {
                    "swsd_segment_id": "s_replaced",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["rr1", "rr2"],
                    "swsd_to_frcsd_node_map": [{"swsd_node_id": "2", "frcsd_node_ids": [], "mapping_status": "missing"}],
                    "risk_flags": [],
                },
                LineString([(0, 2), (10, 2)]),
            )
        ],
    )
    _write_layer(
        swsd_roads_path,
        [{"id": "sr1", "source": 2, "snodeid": "2", "enodeid": "3", "patch_id": "100"}],
        [LineString([(5, 2), (5, 10)])],
    )
    _write_layer(swsd_segment_path, [], [])
    write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_advance_right_attachment_audit",
        fieldnames=["swsd_node_id", "action", "action_reason"],
        features=[],
    )

    summary = run_surface_topology_postprocess(
        step_root=step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        apply_closure=True,
    )

    assert summary["surface_topology_selected_replacement_midroad_closed_count"] == 1
    assert summary["surface_topology_selected_replacement_midroad_materialized_count"] == 2
    nodes = {item["properties"]["id"]: item["properties"] for item in read_features(step_root / "t06_frcsd_node.gpkg")}
    generated_ids = [
        str(props["id"])
        for props in nodes.values()
        if props.get("t06_generated_reason") == "surface_topology_selected_replacement_midroad"
    ]
    assert len(generated_ids) == 2
    assert {str(nodes[node_id]["mainnodeid"]) for node_id in generated_ids} == {generated_ids[0]}
    assert str(nodes["2"]["mainnodeid"]) == generated_ids[0]
    roads = read_features(step_root / "t06_frcsd_road.gpkg")
    split_by_original = {}
    for item in roads:
        original_id = item["properties"].get("t06_split_original_road_id")
        if original_id:
            split_by_original.setdefault(original_id, []).append(str(item["properties"]["id"]))
    assert {key: len(value) for key, value in split_by_original.items()} == {"rr1": 2, "rr2": 2}
    relation = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")[0]["properties"]
    node_map = json.loads(relation["swsd_to_frcsd_node_map"])
    assert node_map[0]["frcsd_node_ids"] == generated_ids
    assert json.loads(relation["frcsd_road_ids"]) == [*split_by_original["rr1"], *split_by_original["rr2"]]


def _write_empty_step3_dependencies(step_root: Path, *, include_relation: bool = True) -> None:
    for stem, fieldnames in {
        "t06_frcsd_road": ["id", "source", "snodeid", "enodeid", "direction"],
        "t06_step3_swsd_frcsd_segment_relation": ["swsd_segment_id", "relation_status"],
        "t06_step3_advance_right_attachment_audit": ["swsd_node_id", "action", "action_reason"],
    }.items():
        if stem == "t06_step3_swsd_frcsd_segment_relation" and not include_relation:
            continue
        write_feature_triplet(step_root=step_root, stem=stem, fieldnames=fieldnames, features=[])


def _write_layer(path: Path, rows: list[dict], geometries: list) -> None:
    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:3857")
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG")


def _feature(properties: dict, geometry) -> dict:
    return {"properties": properties, "geometry": geometry}
