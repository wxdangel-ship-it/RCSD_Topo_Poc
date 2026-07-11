from __future__ import annotations

import csv


import json


from pathlib import Path


from shapely.geometry import LineString, MultiLineString, Point, box


from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer


from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import (
    SCENE_GROUP_EXISTING,
    SCENE_ROAD_SPLIT,
    SceneDecision,
)


from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
    run_t05_phase2_rcsd_junctionization_and_relation,
)


from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_scene_classifier import (
    SOURCE_T10_PAIR_ANCHOR_CLUSTER,
    SOURCE_T10_SIDE_GROUP,
    choose_actionable_decisions,
)


def _surface(target_id: str, x: float = 0.0):
    return {
        "properties": {
            "surface_id": f"JAS:{target_id}",
            "mainnodeid": target_id,
            "patch_id": "P1",
            "junction_type": "center_junction",
            "kind_2": 4,
            "surface_sources": "T03",
            "is_multi_source_merged": 0,
        },
        "geometry": box(x - 5.0, -5.0, x + 5.0, 5.0),
    }


def _node(node_id: int, x: float, y: float, **props):
    properties = {
        "id": node_id,
        "mainnodeid": props.pop("mainnodeid", None),
        "kind": props.pop("kind", 4),
        "kind_2": props.pop("kind_2", 4),
    }
    properties.update(props)
    return {"properties": properties, "geometry": Point(x, y)}


def _road(road_id: int, start: tuple[float, float], end: tuple[float, float], snodeid: int = 1, enodeid: int = 2, **props):
    properties = {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": "B"}
    properties.update(props)
    return {
        "properties": properties,
        "geometry": LineString([start, end]),
    }


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def _run_phase2(
    tmp_path: Path,
    *,
    surface_features: list[dict],
    swsd_nodes: list[dict],
    rcsd_roads: list[dict],
    rcsd_nodes: list[dict],
    t02_rows: list[dict] | None = None,
    t07_rows: list[dict] | None = None,
    t03_rows: list[dict] | None = None,
    t04_rows: list[dict] | None = None,
    t10_side_group_rows: list[dict] | None = None,
    t10_pair_anchor_rows: list[dict] | None = None,
    t11_manual_rows: list[dict] | None = None,
    runner_kwargs: dict | None = None,
):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    surface_path = _write(inputs / "junction_anchor_surface.gpkg", surface_features)
    fusion_audit_path = _write_csv(inputs / "junction_anchor_surface_fusion_audit.csv", [], ["surface_id", "mainnodeid"])
    nodes_path = _write(inputs / "nodes.gpkg", swsd_nodes)
    rcsdroad_path = _write(inputs / "RCSDRoad.gpkg", rcsd_roads)
    rcsdnode_path = _write(inputs / "RCSDNode.gpkg", rcsd_nodes)
    t02_path = _write_csv(inputs / "t02_swsd_rcsd_relation_evidence.csv", t02_rows or [], _T02_FIELDS)
    t07_path = _write_csv(inputs / "t07_swsd_rcsd_relation_evidence.csv", t07_rows or [], _T07_FIELDS)
    t03_path = _write_csv(inputs / "t03_swsd_rcsd_relation_evidence.csv", t03_rows or [], _T03_FIELDS)
    t04_path = _write_csv(inputs / "t04_swsd_rcsd_relation_evidence.csv", t04_rows or [], _T04_FIELDS)
    t10_side_group_path = _write_csv(inputs / "t10_upstream_side_group_endpoint_candidates.csv", t10_side_group_rows or [], _T10_SIDE_GROUP_FIELDS)
    t10_pair_anchor_path = _write_csv(inputs / "t10_upstream_pair_anchor_endpoint_clusters.csv", t10_pair_anchor_rows or [], _T10_PAIR_ANCHOR_FIELDS)
    t11_manual_path = _write_csv(inputs / "t11_segment_anchor_manual_audit.csv", t11_manual_rows or [], _T11_MANUAL_FIELDS)
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (surface_path, nodes_path, rcsdroad_path, rcsdnode_path)}
    artifacts = run_t05_phase2_rcsd_junctionization_and_relation(
        junction_surface_path=surface_path,
        fusion_audit_path=fusion_audit_path,
        nodes_path=nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        t02_relation_evidence_path=t02_path,
        t03_relation_evidence_path=t03_path,
        t04_relation_evidence_path=t04_path,
        out_root=tmp_path / "out",
        run_id="run",
        t07_relation_evidence_path=t07_path,
        t10_side_group_endpoint_candidate_path=t10_side_group_path if t10_side_group_rows is not None else None,
        t10_pair_anchor_endpoint_cluster_path=t10_pair_anchor_path if t10_pair_anchor_rows is not None else None,
        t11_manual_relation_path=t11_manual_path if t11_manual_rows is not None else None,
        **(runner_kwargs or {}),
    )
    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (surface_path, nodes_path, rcsdroad_path, rcsdnode_path)}
    assert after == before
    return artifacts


def _relation_features(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def _layer_props(path: Path) -> list[dict]:
    return [feature.properties for feature in read_vector_layer(path).features]


def _summary(artifacts) -> dict:
    return json.loads(artifacts.summary_path.read_text(encoding="utf-8"))


_T3_BASE_FIELDS = [
    "target_id",
    "case_id",
    "junction_type",
    "template_class",
    "association_class",
    "required_rcsdnode_ids",
    "required_rcsdroad_ids",
    "support_rcsdnode_ids",
    "support_rcsdroad_ids",
    "step7_state",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
]


_T03_FIELDS = [*_T3_BASE_FIELDS, "rcsd_point_x", "rcsd_point_y"]


_T04_FIELDS = [
    "target_id",
    "case_id",
    "junction_type",
    "scene_type",
    "surface_scenario_type",
    "rcsd_alignment_type",
    "final_state",
    "swsd_relation_type",
    "required_rcsd_node_ids",
    "semantic_required_rcsd_node_ids",
    "selected_rcsdnode_ids",
    "selected_rcsdroad_ids",
    "fallback_rcsdroad_ids",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
    "fact_reference_x",
    "fact_reference_y",
]


_T02_FIELDS = [
    "target_id",
    "representative_node_id",
    "relation_source",
    "relation_target_type",
    "matched_rcsdintersection_ids",
    "relation_state",
    "status_suggested",
    "base_id_candidate",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]


_T07_FIELDS = [
    *_T03_FIELDS,
    "relation_source",
    "relation_target_type",
    "matched_rcsdintersection_ids",
    "surface_candidate_present",
]


_T10_SIDE_GROUP_FIELDS = [
    "case_id",
    "swsd_segment_id",
    "target_id",
    "endpoint_index",
    "source_problem_status",
    "rcsd_primary_node_id",
    "candidate_rcsdnode_ids",
    "candidate_rcsdnode_count",
    "candidate_rcsd_pair_node_sets",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "side_group_action",
    "manual_review_required",
    "problem_registry_path",
]


_T10_PAIR_ANCHOR_FIELDS = [
    "case_id",
    "swsd_segment_id",
    "target_id",
    "endpoint_index",
    "source_problem_status",
    "rcsd_primary_node_id",
    "endpoint_cluster_rcsdnode_ids",
    "endpoint_cluster_node_count",
    "candidate_rcsdnode_ids_from_pair_sets",
    "candidate_rcsd_pair_node_sets",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "pair_anchor_cluster_action",
    "auto_consumable_by_t05",
    "manual_review_required",
    "problem_registry_path",
]


_T11_MANUAL_FIELDS = ["case_id", "target_id", "manual_relation_type", "selected_ids", "comment"]


__all__=[name for name in globals() if not name.startswith("__")]
