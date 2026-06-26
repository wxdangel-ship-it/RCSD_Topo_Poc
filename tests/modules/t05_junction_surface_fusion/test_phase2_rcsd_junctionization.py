from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_anchor_funnel import build_junction_anchor_funnel
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import (
    Phase2Evidence,
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
        **(runner_kwargs or {}),
    )
    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (surface_path, nodes_path, rcsdroad_path, rcsdnode_path)}
    assert after == before
    return artifacts


def test_existing_rcsd_semantic_junction_outputs_success_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("100")],
        swsd_nodes=[_node(100, 0, 0, mainnodeid="100", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(10, 5, 0)],
        t03_rows=[
            {
                "target_id": "100",
                "case_id": "100",
                "junction_type": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": "10",
                "step7_state": "accepted",
                "base_id_candidate": "10",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
                "level": 2,
                "is_highway": 1,
                "swsd_point_x": 0,
                "swsd_point_y": 0,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"] == {"target_id": "100", "base_id": 10, "status": 0, "level": 1, "is_highway": 0}
    assert relation["geometry"]["type"] == "LineString"
    summary = _summary(artifacts)
    assert summary["consistency"]["status_0_base_id_nonzero"]
    funnel = summary["junction_anchor_funnel"]
    assert funnel["semantic_junction_kind_2_values"] == [4, 8, 16, 64, 128, 2048]
    assert funnel["top_level_funnel"]["semantic_junction_total"] == 1
    assert funnel["top_level_funnel"]["t05_phase2_target_total"] == 1
    assert funnel["top_level_funnel"]["relation_success_total"] == 1
    source_rows = {row["source_module"]: row for row in funnel["source_module_funnel"]}
    assert source_rows["T03"]["input_junction_total"] == 1
    assert source_rows["T03"]["success_evidence_junction_total"] == 1
    assert source_rows["T03"]["success_after_t05_total"] == 1
    assert artifacts.junction_anchor_funnel_summary_path is not None
    assert artifacts.junction_anchor_funnel_summary_path.exists()
    assert artifacts.junction_anchor_source_funnel_csv_path is not None
    assert artifacts.junction_anchor_source_funnel_csv_path.exists()
    assert artifacts.junction_anchor_kind2_funnel_csv_path is not None
    assert artifacts.junction_anchor_kind2_funnel_csv_path.exists()
    assert artifacts.junction_anchor_kind2_funnel_json_path is not None
    assert artifacts.junction_anchor_kind2_funnel_json_path.exists()
    assert artifacts.junction_anchor_failure_reasons_csv_path is not None
    assert artifacts.junction_anchor_failure_reasons_csv_path.exists()


def test_junction_anchor_funnel_business_aliases_kind2_and_consumability() -> None:
    funnel = build_junction_anchor_funnel(
        swsd_nodes=[
            {"properties": {"id": 100, "mainnodeid": 100, "kind_2": 4}},
            {"properties": {"id": 200, "mainnodeid": 200, "kind_2": 8}},
        ],
        evidence_rows=[
            Phase2Evidence("T03", {"target_id": "100", "status_suggested": 0, "base_id_candidate": 10}, "100", "c1"),
            Phase2Evidence("T03", {"target_id": "200", "status_suggested": 0, "base_id_candidate": 20}, "200", "c2"),
            Phase2Evidence("T04", {"target_id": "200", "status_suggested": 0, "base_id_candidate": 20}, "200", "c3"),
        ],
        relation_features=[
            {"properties": {"target_id": "100", "base_id": 10, "status": 0}},
            {"properties": {"target_id": "200", "base_id": 20, "status": 0}},
        ],
        audit_rows=[
            {"target_id": "100", "source_module": "T03", "status": 0},
            {"target_id": "200", "source_module": "T03|T04", "status": 0},
        ],
        relation_graph_consumability_rows=[
            {"target_id": "100", "graph_consumable": 1},
            {"target_id": "200", "graph_consumable": 0},
        ],
    )

    top_level = funnel["top_level_funnel"]
    assert top_level["relation_published_success_total"] == 2
    assert top_level["relation_graph_consumable_total"] == 1
    assert top_level["relation_graph_unconsumable_total"] == 1
    assert top_level["relation_graph_consumable_rate"] == 0.5
    assert top_level["relation_graph_unconsumable_rate"] == 0.5

    rows = {row["kind_2"]: row for row in funnel["kind2_funnel"]}
    assert rows[4]["junction_type"] == "center_junction"
    assert rows[4]["graph_consumable_success_total"] == 1
    assert rows[8]["junction_type"] == "merge"
    assert rows[8]["graph_unconsumable_success_total"] == 1

    source_rows = {row["source_module"]: row for row in funnel["source_module_funnel"]}
    assert source_rows["T03"]["input_junction_total"] == 2
    assert source_rows["T04"]["input_junction_total"] == 1
    assert "not mutually exclusive" in funnel["notes"][0]


def test_t10_side_group_candidate_supplements_road_split_decision_without_masking_it() -> None:
    side_group = SceneDecision(
        scene=SCENE_GROUP_EXISTING,
        action="group_existing_rcsd_nodes",
        reason="supplement_existing_relation_with_endpoint_rcsdnode_grouping",
        source_module=SOURCE_T10_SIDE_GROUP,
        source_case_id="991176",
        rcsdnode_ids=(10, 11),
    )
    road_split = SceneDecision(
        scene=SCENE_ROAD_SPLIT,
        action="split_rcsdroad_generate_rcsdnode",
        reason="t03_b2_road_only_support",
        source_module="T03",
        source_case_id="100",
        rcsdroad_ids=(1,),
    )

    assert choose_actionable_decisions([side_group, road_split]) == [road_split, side_group]


def test_t10_pair_anchor_cluster_is_supplemental_decision_only() -> None:
    pair_anchor = SceneDecision(
        scene=SCENE_GROUP_EXISTING,
        action="group_existing_rcsd_nodes",
        reason="supplement_existing_relation_with_pair_anchor_endpoint_cluster",
        source_module=SOURCE_T10_PAIR_ANCHOR_CLUSTER,
        source_case_id="991176",
        rcsdnode_ids=(20, 21),
    )
    road_split = SceneDecision(
        scene=SCENE_ROAD_SPLIT,
        action="split_rcsdroad_generate_rcsdnode",
        reason="t03_b2_road_only_support",
        source_module="T03",
        source_case_id="100",
        rcsdroad_ids=(1,),
    )

    assert choose_actionable_decisions([pair_anchor]) == []
    assert choose_actionable_decisions([pair_anchor, road_split]) == [road_split, pair_anchor]


def test_phase2_rcsdroad_out_preserves_multilinestring_input_geometry(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("120")],
        swsd_nodes=[_node(120, 0, 0, mainnodeid="120")],
        rcsd_roads=[
            {
                "properties": {"id": 1, "snodeid": 1, "enodeid": 2, "direction": "B"},
                "geometry": MultiLineString([[(0, 0), (5, 0)], [(5, 0), (10, 0)]]),
            }
        ],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 10, 0), _node(10, 5, 0)],
        t03_rows=[
            {
                "target_id": "120",
                "case_id": "120",
                "junction_type": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": "10",
                "step7_state": "accepted",
                "base_id_candidate": "10",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
            }
        ],
    )

    geometries = [feature.geometry.geom_type for feature in read_vector_layer(artifacts.rcsdroad_out_path).features]
    assert geometries == ["MultiLineString"]


def test_t02_existing_rcsdintersection_uses_evidence_rcsd_point(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("150")],
        swsd_nodes=[_node(150, 0, 0, mainnodeid="150")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t02_rows=[
            {
                "target_id": "150",
                "representative_node_id": "150",
                "relation_source": "T02_INPUT",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "77",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 77,
                "rcsd_point_x": 20,
                "rcsd_point_y": 0,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] == 77
    coords = relation["geometry"]["coordinates"]
    assert coords[0] != coords[1]


def test_relation_graph_consumability_audit_reports_graph_unusable_base(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("160"), _surface("161", x=20)],
        swsd_nodes=[
            _node(160, 0, 0, mainnodeid="160"),
            _node(161, 20, 0, mainnodeid="161"),
        ],
        rcsd_roads=[_road(1, (-10, 0), (30, 0), snodeid=1, enodeid=2)],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 30, 0)],
        t02_rows=[
            {
                "target_id": "160",
                "representative_node_id": "160",
                "relation_source": "T02_INPUT",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "1",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 1,
                "rcsd_point_x": -10,
                "rcsd_point_y": 0,
            },
            {
                "target_id": "161",
                "representative_node_id": "161",
                "relation_source": "T02_INPUT",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "99",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 99,
                "rcsd_point_x": 20,
                "rcsd_point_y": 0,
            },
        ],
    )

    rows = json.loads(artifacts.relation_graph_consumability_audit_json_path.read_text(encoding="utf-8"))["rows"]
    rows_by_target = {row["target_id"]: row for row in rows}
    assert rows_by_target["160"]["graph_consumability_status"] == "base_node_graph_incident"
    assert rows_by_target["160"]["graph_consumable"] == 1
    assert rows_by_target["160"]["incident_rcsdnode_ids"] == "1"
    assert rows_by_target["161"]["graph_consumability_status"] == "base_id_not_found_in_rcsdnode_out"
    assert rows_by_target["161"]["graph_consumable"] == 0
    assert rows_by_target["161"]["recommended_action"] == "upstream_relation_or_junctionization_review"
    summary = _summary(artifacts)
    assert summary["relation_graph_consumability_row_count"] == 2
    assert summary["relation_graph_consumable_count"] == 1
    assert summary["relation_graph_unconsumable_success_count"] == 1
    assert summary["relation_graph_consumability_passed"] is False


def test_t07_existing_rcsdintersection_rebases_missing_base_from_single_surface_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("170")],
        swsd_nodes=[_node(170, 0, 0, mainnodeid="170", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (0, 0), (10, 0), snodeid=700, enodeid=2)],
        rcsd_nodes=[_node(700, 0, 0, mainnodeid="700"), _node(2, 10, 0)],
        t07_rows=[
            {
                "target_id": "170",
                "case_id": "170",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 999,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 700
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["reason"] == "existing_rcsdintersection_surface_1v1_rcsdnode_rebased"
    graph_rows = json.loads(artifacts.relation_graph_consumability_audit_json_path.read_text(encoding="utf-8"))["rows"]
    assert graph_rows[0]["graph_consumability_status"] == "base_node_graph_incident"


def test_t07_existing_rcsdintersection_rebases_zero_base_from_single_surface_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("172")],
        swsd_nodes=[_node(172, 0, 0, mainnodeid="172", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (0, 0), (10, 0), snodeid=701, enodeid=2)],
        rcsd_nodes=[_node(701, 0, 0, mainnodeid="701"), _node(2, 10, 0)],
        t07_rows=[
            {
                "target_id": "172",
                "case_id": "172",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "701",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 0,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 701
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["reason"] == "existing_rcsdintersection_surface_1v1_rcsdnode_rebased"


def test_t07_existing_rcsdintersection_missing_base_without_surface_node_fails(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("171", x=100)],
        swsd_nodes=[_node(171, 100, 0, mainnodeid="171", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (0, 0), (10, 0), snodeid=1, enodeid=2)],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 10, 0)],
        t07_rows=[
            {
                "target_id": "171",
                "case_id": "171",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 999,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "failure"
    assert audit_rows[0]["reason"] == "t07_rcsdintersection_base_not_in_rcsdnode_out"
    graph_rows = json.loads(artifacts.relation_graph_consumability_audit_json_path.read_text(encoding="utf-8"))["rows"]
    assert graph_rows[0]["graph_consumability_status"] == "relation_not_success"
    summary = _summary(artifacts)
    assert summary["relation_graph_unconsumable_success_count"] == 0
    assert summary["junction_anchor_funnel"]["t05_failure_breakdown"]["t05_closure_failure_total"] == 1


def test_t07_existing_rcsdintersection_groups_multiple_rcsd_semantic_nodes(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("151")],
        swsd_nodes=[_node(151, 0, 0, mainnodeid="151", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(70, -1, 0, mainnodeid="70"),
            _node(71, 1, 0, mainnodeid="71"),
        ],
        t07_rows=[
            {
                "target_id": "151",
                "case_id": "151",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 70,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] in {70, 71}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "group_existing_rcsd_nodes"
    assert audit_rows[0]["reason"] == "existing_rcsdintersection_multi_rcsdnode_surface"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "70|71"
    assert len(read_vector_layer(artifacts.rcsdnode_grouped_path).features) == 2


def test_t10_side_group_endpoint_candidate_supplements_existing_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("152")],
        swsd_nodes=[_node(152, 0, 0, mainnodeid="152", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-1, 0), (1, 0), snodeid=80, enodeid=81)],
        rcsd_nodes=[
            _node(80, -1, 0, mainnodeid="80"),
            _node(81, 1, 0, mainnodeid="81"),
        ],
        t03_rows=[
            {
                "target_id": "152",
                "case_id": "152",
                "junction_type": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": "80",
                "step7_state": "accepted",
                "base_id_candidate": "80",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
            }
        ],
        t10_side_group_rows=[
            {
                "case_id": "991176",
                "swsd_segment_id": "152_153",
                "target_id": "152",
                "endpoint_index": "0",
                "source_problem_status": "requires_upstream_side_group_or_rcsd_directionality_review",
                "rcsd_primary_node_id": "80",
                "candidate_rcsdnode_ids": "80|81",
                "candidate_rcsdnode_count": "2",
                "side_group_action": "supplement_existing_relation_with_endpoint_rcsdnode_grouping",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] in {80, 81}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["source_module"] == "T03|T10_SIDE_GROUP"
    assert audit_rows[0]["reason"] == "multiple_base_id_merged"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "80|81"


def test_t10_side_group_endpoint_candidate_is_not_standalone_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("159")],
        swsd_nodes=[_node(159, 0, 0, mainnodeid="159", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-1, 0), (1, 0), snodeid=82, enodeid=83)],
        rcsd_nodes=[
            _node(82, -1, 0, mainnodeid="82"),
            _node(83, 1, 0, mainnodeid="83"),
        ],
        t10_side_group_rows=[
            {
                "case_id": "991176",
                "swsd_segment_id": "159_160",
                "target_id": "159",
                "endpoint_index": "0",
                "source_problem_status": "requires_upstream_side_group_or_rcsd_directionality_review",
                "rcsd_primary_node_id": "82",
                "candidate_rcsdnode_ids": "82|83",
                "candidate_rcsdnode_count": "2",
                "side_group_action": "supplement_existing_relation_with_endpoint_rcsdnode_grouping",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "missing_relation_evidence"


def test_t10_pair_anchor_endpoint_cluster_supplements_existing_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("162")],
        swsd_nodes=[_node(162, 0, 0, mainnodeid="162", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-1, 0), (1, 0), snodeid=84, enodeid=85)],
        rcsd_nodes=[
            _node(84, -1, 0, mainnodeid="84"),
            _node(85, 1, 0, mainnodeid="85"),
        ],
        t07_rows=[
            {
                "target_id": "162",
                "case_id": "162",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 84,
            }
        ],
        t10_pair_anchor_rows=[
            {
                "case_id": "991176",
                "swsd_segment_id": "161_162",
                "target_id": "162",
                "endpoint_index": "1",
                "source_problem_status": "requires_upstream_iteration",
                "rcsd_primary_node_id": "84",
                "endpoint_cluster_rcsdnode_ids": "84|85",
                "endpoint_cluster_node_count": "2",
                "candidate_rcsdnode_ids_from_pair_sets": "85",
                "pair_anchor_cluster_action": "supplement_existing_relation_with_pair_anchor_endpoint_cluster",
                "auto_consumable_by_t05": "true",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] in {84, 85}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["source_module"] == "T07|T10_PAIR_ANCHOR_CLUSTER"
    assert audit_rows[0]["reason"] == "multiple_base_id_merged"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "84|85"


def test_t10_pair_anchor_endpoint_cluster_is_not_standalone_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("163")],
        swsd_nodes=[_node(163, 0, 0, mainnodeid="163", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-1, 0), (1, 0), snodeid=86, enodeid=87)],
        rcsd_nodes=[
            _node(86, -1, 0, mainnodeid="86"),
            _node(87, 1, 0, mainnodeid="87"),
        ],
        t10_pair_anchor_rows=[
            {
                "case_id": "991176",
                "swsd_segment_id": "163_164",
                "target_id": "163",
                "endpoint_index": "0",
                "source_problem_status": "requires_upstream_iteration",
                "rcsd_primary_node_id": "86",
                "endpoint_cluster_rcsdnode_ids": "86|87",
                "endpoint_cluster_node_count": "2",
                "candidate_rcsdnode_ids_from_pair_sets": "87",
                "pair_anchor_cluster_action": "supplement_existing_relation_with_pair_anchor_endpoint_cluster",
                "auto_consumable_by_t05": "true",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "missing_relation_evidence"


def test_t10_side_group_endpoint_candidate_supplements_road_split_grouping(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("158")],
        swsd_nodes=[_node(158, 0, 0, mainnodeid="158", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0), snodeid=1, enodeid=2)],
        rcsd_nodes=[
            _node(1, -10, 0, mainnodeid="1"),
            _node(2, 10, 0, mainnodeid="2"),
            _node(91, 2, 0, mainnodeid="91"),
        ],
        t03_rows=[
            {
                "target_id": "158",
                "case_id": "158",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "base_id_candidate": -1,
                "status_suggested": 1,
                "relation_state": "rcsd_present_not_junction",
                "reason": "synthetic_road_split",
            }
        ],
        t10_side_group_rows=[
            {
                "case_id": "991176",
                "swsd_segment_id": "158_159",
                "target_id": "158",
                "endpoint_index": "0",
                "source_problem_status": "requires_upstream_side_group_or_rcsd_directionality_review",
                "rcsd_primary_node_id": "100",
                "candidate_rcsdnode_ids": "100|91",
                "candidate_rcsdnode_count": "2",
                "side_group_action": "supplement_existing_relation_with_endpoint_rcsdnode_grouping",
            }
        ],
        runner_kwargs={"next_node_id_start": 100},
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 100
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "road_only_split"
    assert audit_rows[0]["source_module"] == "T03"
    assert audit_rows[0]["new_rcsdnode_ids"] == "100"
    assert audit_rows[0]["original_rcsdnode_ids"] == "91"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "91|100"
    output_nodes = {
        feature.properties["id"]: feature.properties.get("mainnodeid")
        for feature in read_vector_layer(artifacts.rcsdnode_out_path).features
    }
    assert str(output_nodes[91]) == "100"
    assert str(output_nodes[100]) == "100"


def test_t07_existing_rcsdintersection_groups_nearby_nonbase_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("153")],
        swsd_nodes=[_node(153, 0, 0, mainnodeid="153", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (0, 0), (8.5, 0), snodeid=90, enodeid=91)],
        rcsd_nodes=[
            _node(90, 0, 0, mainnodeid="90"),
            _node(91, 8.5, 0, mainnodeid=0),
        ],
        t07_rows=[
            {
                "target_id": "153",
                "case_id": "153",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 90,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] == 90
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "group_existing_rcsd_nodes"
    assert audit_rows[0]["reason"] == "existing_rcsdintersection_nearby_nonbase_node_grouping"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "90|91"
    grouped = {
        feature.properties["id"]: feature.properties["mainnodeid"]
        for feature in read_vector_layer(artifacts.rcsdnode_grouped_path).features
    }
    assert grouped == {90: 90, 91: 90}


def test_t07_existing_rcsdintersection_keeps_nearby_success_base_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("154"), _surface("155", x=30.0)],
        swsd_nodes=[
            _node(154, 0, 0, mainnodeid="154", grade=2, closed_con=1),
            _node(155, 30, 0, mainnodeid="155", grade=2, closed_con=1),
        ],
        rcsd_roads=[_road(1, (0, 0), (8.5, 0), snodeid=92, enodeid=93)],
        rcsd_nodes=[
            _node(92, 0, 0, mainnodeid="92"),
            _node(93, 8.5, 0, mainnodeid=0),
        ],
        t07_rows=[
            {
                "target_id": "154",
                "case_id": "154",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 92,
            },
            {
                "target_id": "155",
                "case_id": "155",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 93,
            },
        ],
    )

    audit_rows = {
        row["target_id"]: row
        for row in csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8"))
    }
    assert audit_rows["154"]["scene"] == "direct_existing_rcsd_junction"
    assert audit_rows["154"]["grouped_rcsdnode_ids"] == ""
    output_nodes = {
        feature.properties["id"]: feature.properties.get("mainnodeid")
        for feature in read_vector_layer(artifacts.rcsdnode_out_path).features
    }
    assert str(output_nodes[93]) == "0"


def test_t07_existing_rcsdintersection_keeps_road_split_endpoint_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("156"), _surface("157", x=40.0)],
        swsd_nodes=[
            _node(156, 0, 0, mainnodeid="156", grade=2, closed_con=1),
            _node(157, 40, 0, mainnodeid="157", grade=2, closed_con=1),
        ],
        rcsd_roads=[
            _road(1, (0, 0), (8.5, 0), snodeid=94, enodeid=95),
            _road(2, (8.5, 0), (40, 0), snodeid=95, enodeid=96),
        ],
        rcsd_nodes=[
            _node(94, 0, 0, mainnodeid="94"),
            _node(95, 8.5, 0, mainnodeid=0),
            _node(96, 40, 0, mainnodeid=0),
        ],
        t07_rows=[
            {
                "target_id": "156",
                "case_id": "156",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": 94,
            }
        ],
        t03_rows=[
            {
                "target_id": "157",
                "case_id": "157",
                "junction_type": "single_sided_t_mouth",
                "association_class": "B",
                "support_rcsdroad_ids": "2",
                "step7_state": "accepted",
                "surface_candidate_present": 1,
                "base_id_candidate": -1,
                "status_suggested": 1,
                "relation_state": "rcsd_present_not_junction",
                "reason": "synthetic_road_split_endpoint",
            }
        ],
    )

    audit_rows = {
        row["target_id"]: row
        for row in csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8"))
    }
    assert audit_rows["156"]["scene"] == "direct_existing_rcsd_junction"
    assert audit_rows["156"]["grouped_rcsdnode_ids"] == ""
    output_nodes = {
        feature.properties["id"]: feature.properties.get("mainnodeid")
        for feature in read_vector_layer(artifacts.rcsdnode_out_path).features
    }
    assert str(output_nodes[95]) == "0"


def test_t07_multiple_intersections_for_group_builds_existing_rcsd_group(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("152")],
        swsd_nodes=[_node(152, 0, 0, mainnodeid="152", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(80, -1, 0, mainnodeid="80"),
            _node(81, 1, 0, mainnodeid="81"),
        ],
        t07_rows=[
            {
                "target_id": "152",
                "case_id": "152",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "80|81",
                "relation_state": "multiple_intersections_for_group",
                "status_suggested": 1,
                "base_id_candidate": "80|81",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] in {80, 81}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "group_existing_rcsd_nodes"
    assert audit_rows[0]["reason"] == "t07_multiple_intersections_for_group"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "80|81"


def test_t07_historical_anchor_relation_without_surface_outputs_success(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("999", x=50)],
        swsd_nodes=[
            _node(999, 50, 0, mainnodeid="999"),
            _node(900, 0, 0, mainnodeid="900.0", grade=2, closed_con=2),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(55, 5, 0)],
        t07_rows=[
            {
                "target_id": "900.0",
                "case_id": "900.0",
                "junction_type": "center_junction",
                "relation_source": "T07",
                "relation_target_type": "RCSDNode",
                "relation_state": "success_historical_anchor",
                "status_suggested": 0,
                "base_id_candidate": 55,
                "rcsd_point_x": 5,
                "rcsd_point_y": 0,
            }
        ],
    )

    relations = {feature["properties"]["target_id"]: feature for feature in _relation_features(artifacts.relation_geojson_path)}
    assert "900.0" not in relations
    assert relations["900"]["properties"] == {"target_id": "900", "base_id": 55, "status": 0, "level": 1, "is_highway": 1}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert "900.0" not in {row["target_id"] for row in audit_rows}
    assert {row["target_id"]: row for row in audit_rows}["900"]["source_module"] == "T07"
    assert _summary(artifacts)["performance"]["data_volume"]["t07_evidence_row_count"] == 1


def test_t07_direct_relation_takes_precedence_over_t03_road_only_split(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("901")],
        swsd_nodes=[_node(901, 0, 1, mainnodeid="901", kind_2=4)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(56, 5, 0)],
        t07_rows=[
            {
                "target_id": "901",
                "case_id": "901",
                "relation_source": "T07",
                "relation_target_type": "RCSDNode",
                "relation_state": "success_historical_anchor",
                "status_suggested": 0,
                "base_id_candidate": 56,
            }
        ],
        t03_rows=[
            {
                "target_id": "901",
                "case_id": "901",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 56
    assert len(read_vector_layer(artifacts.rcsdroad_split_path).features) == 0


def test_upstream_base_id_candidate_takes_precedence_over_required_node_grouping(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("902")],
        swsd_nodes=[_node(902, 0, 0, mainnodeid="902")],
        rcsd_roads=[_road(1, (-10, 0), (20, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 20, 0), _node(60, 5, 0), _node(61, 8, 0)],
        t03_rows=[
            {
                "target_id": "902",
                "case_id": "902",
                "junction_type": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": "60|61",
                "step7_state": "accepted",
                "base_id_candidate": "60",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] == 60
    assert len(read_vector_layer(artifacts.rcsdnode_grouped_path).features) == 0


def test_t04_partial_handoff_groups_local_and_semantic_required_nodes(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("903")],
        swsd_nodes=[_node(903, 0, 0, mainnodeid="903")],
        rcsd_roads=[_road(1, (-10, 0), (20, 0))],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 20, 0),
            _node(6532, 0, 0, mainnodeid=0),
            _node(2175, 3, 0, mainnodeid=0),
        ],
        t04_rows=[
            {
                "target_id": "903",
                "case_id": "903",
                "junction_type": "diverge",
                "scene_type": "diverge",
                "final_state": "accepted",
                "swsd_relation_type": "partial",
                "required_rcsd_node_ids": "6532",
                "semantic_required_rcsd_node_ids": "2175",
                "selected_rcsdnode_ids": "2175",
                "selected_rcsdroad_ids": "1",
                "surface_candidate_present": 1,
                "base_id_candidate": "6532",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
                "rcsd_point_x": 0,
                "rcsd_point_y": 0,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] == 6532
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "group_existing_rcsd_nodes"
    assert audit_rows[0]["reason"] == "t04_road_surface_fork_partial_handoff_group"
    assert set(audit_rows[0]["grouped_rcsdnode_ids"].split("|")) == {"6532", "2175"}


def test_no_related_rcsd_outputs_failure_with_base_id_zero(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("200.0")],
        swsd_nodes=[_node(200, 0, 0, mainnodeid="200", has_evd="yes", is_anchor="yes")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "200.0",
                "case_id": "200",
                "association_class": "C",
                "step7_state": "accepted",
                "relation_state": "no_related_rcsd",
                "status_suggested": 1,
                "base_id_candidate": -1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["target_id"] == "200"
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    junction_audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert junction_audit_rows[0]["target_id"] == "200"
    coords = relation["geometry"]["coordinates"]
    assert coords[0] == coords[1]
    summary = _summary(artifacts)
    assert "swsdnode_out_count" not in summary
    assert "swsdnode_out" not in summary["output_paths"]


def test_t03_no_related_without_accepted_surface_outputs_failure_only(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("201")],
        swsd_nodes=[_node(201, 0, 0, mainnodeid="201", has_evd="yes", is_anchor="no")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "201",
                "case_id": "201",
                "step7_state": "rejected",
                "relation_state": "no_related_rcsd",
                "status_suggested": 1,
                "base_id_candidate": -1,
            }
        ],
    )

    assert _relation_features(artifacts.relation_geojson_path)[0]["properties"]["status"] == 1
    summary = _summary(artifacts)
    assert "swsdnode_out_count" not in summary


def test_no_related_scene_keeps_failure_even_when_reason_is_no_existing_rcsdintersection(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("203")],
        swsd_nodes=[_node(203, 0, 0, mainnodeid="203", has_evd="yes", is_anchor="yes")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t07_rows=[
            {
                "target_id": "203",
                "case_id": "203",
                "relation_state": "no_existing_rcsdintersection",
                "status_suggested": 1,
                "base_id_candidate": -1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    junction_audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert junction_audit_rows[0]["scene"] == "no_related_rcsd"
    assert junction_audit_rows[0]["reason"] == "no_existing_rcsdintersection"
    summary = _summary(artifacts)
    assert "swsdnode_out_count" not in summary


def test_t04_accepted_no_related_without_rcsd_candidate_outputs_failure_only(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[{**_surface("202"), "properties": {**_surface("202")["properties"], "surface_sources": "T04"}}],
        swsd_nodes=[_node(202, 0, 0, mainnodeid="202", has_evd="yes", is_anchor="yes")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t04_rows=[
            {
                "target_id": "202",
                "case_id": "202",
                "final_state": "accepted",
                "relation_state": "no_related_rcsd",
                "status_suggested": 1,
                "base_id_candidate": -1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    summary = _summary(artifacts)
    assert "swsdnode_out_count" not in summary


def test_t04_fail4_fallback_relation_without_surface_outputs_success(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("999", x=50)],
        swsd_nodes=[
            _node(999, 50, 0, mainnodeid="999"),
            _node(800, 0, 0, mainnodeid="800", is_anchor="fail4_fallback", grade=2, closed_con=1),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(20, 5, 0, mainnodeid="20"),
            _node(21, 6, 0, mainnodeid="20"),
        ],
        t04_rows=[
            {
                "target_id": "800",
                "case_id": "800",
                "junction_type": "diverge",
                "final_state": "rejected",
                "required_rcsd_node_ids": "21",
                "surface_candidate_present": 0,
                "base_id_candidate": 20,
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
                "reason": "fail4_fallback:required_rcsd_node_group_resolved",
                "swsd_point_x": 0,
                "swsd_point_y": 0,
                "rcsd_point_x": 5,
                "rcsd_point_y": 0,
            }
        ],
    )

    relations = {feature["properties"]["target_id"]: feature for feature in _relation_features(artifacts.relation_geojson_path)}
    assert relations["800"]["properties"]["status"] == 0
    assert relations["800"]["properties"]["base_id"] == 20
    assert relations["800"]["properties"]["level"] == 1
    assert relations["800"]["properties"]["is_highway"] == 0


def test_t03_a_multi_rcsdnode_grouping_does_not_split_road(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("300")],
        swsd_nodes=[_node(300, 0, 0, mainnodeid="300")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(20, 1, 0), _node(21, 8, 0)],
        t03_rows=[
            {
                "target_id": "300",
                "case_id": "300",
                "junction_type": "center_junction",
                "association_class": "A",
                "required_rcsdnode_ids": "20|21",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            }
        ],
    )

    out_nodes = {row["id"]: row for row in _layer_props(artifacts.rcsdnode_out_path)}
    assert out_nodes[20]["mainnodeid"] == 20
    assert out_nodes[21]["mainnodeid"] == 20
    assert _relation_features(artifacts.relation_geojson_path)[0]["properties"]["base_id"] == 20
    assert len(read_vector_layer(artifacts.rcsdroad_split_path).features) == 0


def test_t03_b2_road_only_split_generates_node_and_removes_original_road(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("400")],
        swsd_nodes=[
            _node(400, -3, 1, mainnodeid="400", kind_2=4),
            _node(401, 3, 1, mainnodeid="400", kind_2=4),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "400",
                "case_id": "400",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 3
    out_road_ids = {row["id"] for row in _layer_props(artifacts.rcsdroad_out_path)}
    assert 1 not in out_road_ids
    assert len(out_road_ids) == 3
    generated = _layer_props(artifacts.rcsdnode_generated_path)
    assert {row["id"] for row in generated} == {3, 4}
    assert {row["mainnodeid"] for row in generated} == {3}
    assert _summary(artifacts)["consistency"]["split_original_roads_removed_from_active"]


def test_t03_road_only_near_endpoint_reuses_existing_rcsdnode(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("450")],
        swsd_nodes=[_node(450, 0.5, 0, mainnodeid="450", kind_2=4)],
        rcsd_roads=[_road(1, (0, 0), (10, 0), snodeid=1, enodeid=2)],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "450",
                "case_id": "450",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 1
    assert len(read_vector_layer(artifacts.rcsdroad_split_path).features) == 0
    assert len(read_vector_layer(artifacts.rcsdnode_generated_path).features) == 0
    out_road_ids = {row["id"] for row in _layer_props(artifacts.rcsdroad_out_path)}
    assert 1 in out_road_ids
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["reason"] == "road_only_projection_near_endpoint_reuse_rcsdnode"
    assert audit_rows[0]["original_rcsdnode_ids"] == "1"


def test_t03_road_only_reuses_active_descendant_when_source_road_was_split(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("400"), _surface("401", x=6.0)],
        swsd_nodes=[
            _node(400, -3, 0, mainnodeid="400", kind_2=4),
            _node(401, 6, 0, mainnodeid="401", kind_2=4),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0), snodeid=1, enodeid=2)],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "400",
                "case_id": "400",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            },
            {
                "target_id": "401",
                "case_id": "401",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            },
        ],
    )

    relations = sorted(_relation_features(artifacts.relation_geojson_path), key=lambda item: item["properties"]["target_id"])
    assert [row["properties"]["status"] for row in relations] == [0, 0]
    assert [row["properties"]["base_id"] for row in relations] == [3, 4]
    out_road_ids = {row["id"] for row in _layer_props(artifacts.rcsdroad_out_path)}
    assert 1 not in out_road_ids
    assert len(out_road_ids) == 3
    split_road_ids = {row["id"] for row in _layer_props(artifacts.rcsdroad_split_path)}
    assert split_road_ids == out_road_ids
    audit_rows = {
        row["target_id"]: row
        for row in csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8"))
    }
    assert audit_rows["401"]["projection_point_count"] == "1"
    assert audit_rows["401"]["split_point_count"] == "1"


def test_phase2_progress_and_performance_summary_are_sparse(tmp_path: Path, capsys) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("475")],
        swsd_nodes=[_node(475, 0, 0, mainnodeid="475")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(30, 0, 0)],
        t03_rows=[
            {
                "target_id": "475",
                "case_id": "475",
                "association_class": "A",
                "required_rcsdnode_ids": "30",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            }
        ],
        runner_kwargs={"progress": True, "progress_interval": 1, "readonly_workers": 2},
    )

    output = capsys.readouterr().out
    assert "[T05 Phase2] data volume" in output
    assert "[T05 Phase2] plan" in output
    assert "[T05 Phase2] done" in output
    performance = _summary(artifacts)["performance"]
    assert performance["data_volume"]["surface_count"] == 1
    assert performance["plan"]["direct_target_count"] == 1
    assert performance["plan"]["readonly_target_count"] == 1
    assert performance["readonly_workers"] == 2
    assert "rcsdroad_out" in performance["output_timings_sec"]
    assert performance["output_sizes_bytes"]["rcsdroad_out"] > 0
    assert "total_sec" in performance["timings_sec"]
    module_audit = _summary(artifacts)["module_relation_audit_summary"]
    t03_semantic = [
        row for row in module_audit
        if row["source_module"] == "T03" and row["scenario"] == "pre_success_rcsd_semantic_relation"
    ][0]
    assert t03_semantic["input_count"] == 1
    assert t03_semantic["scenario_input_count"] == 1
    assert t03_semantic["relation_success_count"] == 1
    assert artifacts.module_relation_audit_csv_path.is_file()


def test_t04_fact_reference_fallback_controls_split_location(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("500")],
        swsd_nodes=[_node(500, 0, 10, mainnodeid="500")],
        rcsd_roads=[_road(1, (0, 0), (100, 0))],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 100, 0)],
        t04_rows=[
            {
                "target_id": "500",
                "case_id": "500",
                "junction_type": "merge",
                "scene_type": "main_evidence_with_rcsdroad_fallback",
                "rcsd_alignment_type": "rcsdroad_only_alignment",
                "final_state": "accepted",
                "selected_rcsdroad_ids": "1",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
                "fact_reference_x": 50,
                "fact_reference_y": 5,
            }
        ],
    )

    generated_feature = read_vector_layer(artifacts.rcsdnode_generated_path).features[0]
    assert round(generated_feature.geometry.x, 6) == 50
    assert round(generated_feature.geometry.y, 6) == 0
    assert generated_feature.properties["mainnodeid"] in (None, "")
    assert _relation_features(artifacts.relation_geojson_path)[0]["properties"]["status"] == 0


def test_t04_fact_reference_fallback_reads_case_event_evidence_point(tmp_path: Path) -> None:
    case_root = tmp_path / "t04_cases"
    case_dir = case_root / "500"
    case_dir.mkdir(parents=True)
    _write(
        case_dir / "step4_event_evidence.gpkg",
        [
            {
                "properties": {
                    "case_id": "500",
                    "event_unit_id": "event_unit_01",
                    "geometry_role": "fact_reference_point",
                    "surface_scenario_type": "main_evidence_with_rcsdroad_fallback",
                },
                "geometry": Point(50, 5),
            }
        ],
    )
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("500")],
        swsd_nodes=[_node(500, 0, 10, mainnodeid="500")],
        rcsd_roads=[_road(1, (0, 0), (100, 0))],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 100, 0)],
        t04_rows=[
            {
                "target_id": "500",
                "case_id": "500",
                "junction_type": "merge",
                "surface_scenario_type": "main_evidence_with_rcsdroad_fallback",
                "rcsd_alignment_type": "rcsdroad_only_alignment",
                "final_state": "accepted",
                "selected_rcsdroad_ids": "1",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
        runner_kwargs={"t04_case_root": case_root},
    )

    generated_feature = read_vector_layer(artifacts.rcsdnode_generated_path).features[0]
    assert round(generated_feature.geometry.x, 6) == 50
    assert round(generated_feature.geometry.y, 6) == 0
    assert _relation_features(artifacts.relation_geojson_path)[0]["properties"]["status"] == 0


def test_t04_surface_scenario_fallback_splits_even_when_evidence_state_is_no_related_rcsd(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[{**_surface("550"), "properties": {**_surface("550")["properties"], "junction_type": "diverge", "kind_2": 16}}],
        swsd_nodes=[_node(550, 0, 10, mainnodeid="550", has_evd="yes", is_anchor="yes")],
        rcsd_roads=[_road(1, (0, 0), (100, 0))],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 100, 0)],
        t04_rows=[
            {
                "target_id": "550",
                "case_id": "550",
                "junction_type": "diverge",
                "scene_type": "diverge",
                "surface_scenario_type": "no_main_evidence_with_rcsdroad_fallback_and_swsd",
                "rcsd_alignment_type": "rcsdroad_only_alignment",
                "final_state": "accepted",
                "fallback_rcsdroad_ids": "1",
                "relation_state": "no_related_rcsd",
                "status_suggested": 1,
                "swsd_point_x": 60,
                "swsd_point_y": 10,
            }
        ],
    )

    generated_feature = read_vector_layer(artifacts.rcsdnode_generated_path).features[0]
    assert round(generated_feature.geometry.x, 6) == 60
    assert round(generated_feature.geometry.y, 6) == 0
    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 3
    assert "swsdnode_out_count" not in _summary(artifacts)


def test_kind_64_roundabout_groups_connected_rcsd_semantic_junctions(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[
            {
                "properties": {
                    "surface_id": "JAS:900",
                    "mainnodeid": "900",
                    "patch_id": "P1",
                    "junction_type": "unknown",
                    "kind_2": 64,
                    "surface_sources": "T07",
                    "is_multi_source_merged": 0,
                },
                "geometry": box(-5, -5, 5, 5),
            },
            {
                "properties": {
                    "surface_id": "support:900:2",
                    "mainnodeid": "",
                    "patch_id": "P1",
                    "junction_type": "center_junction",
                    "kind_2": 4,
                    "surface_sources": "T03",
                    "is_multi_source_merged": 0,
                },
                "geometry": box(9, -5, 15, 5),
            },
        ],
        swsd_nodes=[
            _node(900, 0, 0, mainnodeid="900", kind_2=64, grade=2, closed_con=2),
            _node(901, 12, 0, mainnodeid="900", kind_2=64),
        ],
        rcsd_roads=[
            _road(100, (-2, 0), (12, 0), snodeid=10, enodeid=20, roadtype=8),
        ],
        rcsd_nodes=[
            _node(10, -2, 0, mainnodeid=10),
            _node(11, -1, 0, mainnodeid=10),
            _node(20, 12, 0, mainnodeid=20),
            _node(21, 13, 0, mainnodeid=20),
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] in {10, 11, 20, 21}
    out_nodes = {row["id"]: row for row in _layer_props(artifacts.rcsdnode_out_path)}
    assert {out_nodes[node_id]["mainnodeid"] for node_id in (10, 11, 20, 21)} == {relation["properties"]["base_id"]}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["scene"] == "roundabout_rcsd_semantic_grouping"
    assert audit_rows[0]["original_rcsdroad_ids"] == "100"
    assert audit_rows[0]["reason"] == "kind_2_64_roundabout_connected_rcsd_junctions"
    assert _summary(artifacts)["performance"]["plan"]["roundabout_target_count"] == 1


def test_kind_64_roundabout_requires_roadtype_8_connectivity(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[
            {
                "properties": {
                    "surface_id": "JAS:910",
                    "mainnodeid": "910",
                    "patch_id": "P1",
                    "junction_type": "unknown",
                    "kind_2": 64,
                    "surface_sources": "T07",
                    "is_multi_source_merged": 0,
                },
                "geometry": box(-5, -5, 15, 5),
            }
        ],
        swsd_nodes=[
            _node(910, 0, 0, mainnodeid="910", kind_2=64),
            _node(911, 12, 0, mainnodeid="910", kind_2=64),
        ],
        rcsd_roads=[
            _road(100, (-2, 0), (12, 0), snodeid=10, enodeid=20, roadtype=1),
        ],
        rcsd_nodes=[
            _node(10, -2, 0, mainnodeid=10),
            _node(20, 12, 0, mainnodeid=20),
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    assert len(read_vector_layer(artifacts.rcsdnode_grouped_path).features) == 0
    assert _summary(artifacts)["performance"]["plan"]["roundabout_target_count"] == 0


def test_missing_grade_and_closed_con_stay_minus_one(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("600")],
        swsd_nodes=[_node(600, 0, 0, mainnodeid="600")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(30, 0, 0)],
        t03_rows=[
            {
                "target_id": "600",
                "case_id": "600",
                "association_class": "A",
                "required_rcsdnode_ids": "30",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["level"] == -1
    assert relation["properties"]["is_highway"] == -1


def test_multiple_existing_candidates_are_grouped_to_one_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("700")],
        swsd_nodes=[_node(700, 0, 0, mainnodeid="700")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(40, 1, 0), _node(41, 8, 0)],
        t03_rows=[
            {
                "target_id": "700",
                "case_id": "700",
                "association_class": "A",
                "required_rcsdnode_ids": "40",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            }
        ],
        t04_rows=[
            {
                "target_id": "700",
                "case_id": "700",
                "junction_type": "complex_divmerge",
                "required_rcsd_node_ids": "41",
                "final_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            }
        ],
    )

    relations = _relation_features(artifacts.relation_geojson_path)
    assert len(relations) == 1
    assert relations[0]["properties"]["target_id"] == "700"
    out_nodes = {row["id"]: row for row in _layer_props(artifacts.rcsdnode_out_path)}
    assert out_nodes[40]["mainnodeid"] == 40
    assert out_nodes[41]["mainnodeid"] == 40
    assert _summary(artifacts)["consistency"]["target_id_unique"]


def test_relation_cardinality_qc_reports_many_targets_to_one_base(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("810"), _surface("811", x=20)],
        swsd_nodes=[
            _node(810, 0, 0, mainnodeid="810"),
            _node(811, 20, 0, mainnodeid="811"),
        ],
        rcsd_roads=[_road(1, (-10, 0), (30, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 30, 0), _node(50, 5, 0)],
        t03_rows=[
            {
                "target_id": "810",
                "case_id": "810",
                "association_class": "A",
                "required_rcsdnode_ids": "50",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            },
            {
                "target_id": "811",
                "case_id": "811",
                "association_class": "A",
                "required_rcsdnode_ids": "50",
                "step7_state": "accepted",
                "relation_state": "success_required_rcsd_junction",
                "status_suggested": 0,
            },
        ],
    )

    summary = _summary(artifacts)
    assert summary["relation_cardinality_error_count"] == 1
    assert summary["relation_cardinality_blocking_error_count"] == 0
    assert summary["many_target_to_one_base_count"] == 1
    assert summary["relation_cardinality_removed_target_count"] == 0
    assert summary["relation_cardinality_removed_relation_count"] == 0
    relation_features = _relation_features(artifacts.relation_geojson_path)
    assert {feature["properties"]["target_id"] for feature in relation_features} == {"810", "811"}
    assert summary["consistency"]["relation_cardinality_passed"] is True
    assert summary["passed"] is True
    error_rows = json.loads(artifacts.relation_cardinality_errors_json_path.read_text(encoding="utf-8"))["rows"]
    assert error_rows == [
        {
            "error_type": "many_target_to_one_base",
            "target_id": "810|811",
            "base_id": "50",
            "related_target_ids": "810|811",
            "introduced_by_module": "T03",
            "source_modules": "T03",
            "source_case_ids": "810|811",
            "scenes": "direct_existing_rcsd_junction",
            "reasons": "success_required_rcsd_junction",
        }
    ]


def test_multiple_unmergeable_base_ids_block_without_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("800")],
        swsd_nodes=[_node(800, 0, 0, mainnodeid="800")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t02_rows=[
            {
                "target_id": "800",
                "representative_node_id": "800",
                "relation_source": "T02_INPUT",
                "relation_target_type": "RCSDIntersection",
                "matched_rcsdintersection_ids": "90|91",
                "relation_state": "existing_rcsdintersection_matched",
                "status_suggested": 0,
                "base_id_candidate": "90|91",
            }
        ],
    )

    assert _relation_features(artifacts.relation_geojson_path) == []
    blocking_rows = json.loads(artifacts.blocking_errors_json_path.read_text(encoding="utf-8"))["rows"]
    assert blocking_rows[0]["reason"] == "multiple_base_id_unmergeable"
    summary = _summary(artifacts)
    assert summary["passed"] is False
    assert summary["consistency"]["target_id_unique"]


def test_phase2_canonicalizes_rcsd_member_nodes_before_grouping(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("900")],
        swsd_nodes=[_node(900, 0, 0, mainnodeid="900", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[
            _node(10, 1, 0, mainnodeid=20),
            _node(20, 0, 0, mainnodeid=20),
            _node(30, 5, 0, mainnodeid=30),
        ],
        t03_rows=[
            {
                "target_id": "900",
                "case_id": "900",
                "junction_type": "single_sided_t_mouth",
                "association_class": "A",
                "required_rcsdnode_ids": "10|30",
                "step7_state": "accepted",
                "base_id_candidate": "10|30",
                "status_suggested": 0,
                "relation_state": "success_required_rcsd_junction",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["base_id"] == 20
    out_nodes = {row["id"]: row for row in _layer_props(artifacts.rcsdnode_out_path)}
    assert out_nodes[10]["mainnodeid"] == 20
    assert out_nodes[20]["mainnodeid"] == 20
    assert out_nodes[30]["mainnodeid"] == 20
    summary = _summary(artifacts)
    assert summary["rcsdnode_grouped_count"] == 3
    assert summary["relation_cardinality_passed"] is True


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
