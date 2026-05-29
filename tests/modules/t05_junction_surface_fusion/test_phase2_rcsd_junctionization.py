from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
    run_t05_phase2_rcsd_junctionization_and_relation,
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
    properties = {"id": node_id, "mainnodeid": props.pop("mainnodeid", None), "kind": props.pop("kind", 4)}
    properties.update(props)
    return {"properties": properties, "geometry": Point(x, y)}


def _road(road_id: int, start: tuple[float, float], end: tuple[float, float], snodeid: int = 1, enodeid: int = 2):
    return {
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": "B"},
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
    assert _summary(artifacts)["consistency"]["status_0_base_id_nonzero"]


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


def test_t07_historical_anchor_relation_without_surface_outputs_success(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("999", x=50)],
        swsd_nodes=[
            _node(999, 50, 0, mainnodeid="999"),
            _node(900, 0, 0, mainnodeid="900", grade=2, closed_con=2),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0), _node(55, 5, 0)],
        t07_rows=[
            {
                "target_id": "900",
                "case_id": "900",
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
    assert relations["900"]["properties"] == {"target_id": "900", "base_id": 55, "status": 0, "level": 1, "is_highway": 1}
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
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


def test_no_related_rcsd_outputs_failure_with_base_id_zero(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("200")],
        swsd_nodes=[_node(200, 0, 0, mainnodeid="200")],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1, -10, 0), _node(2, 10, 0)],
        t03_rows=[
            {
                "target_id": "200",
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
    assert relation["properties"]["status"] == 1
    assert relation["properties"]["base_id"] == 0
    coords = relation["geometry"]["coordinates"]
    assert coords[0] == coords[1]


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
        swsd_nodes=[_node(550, 0, 10, mainnodeid="550")],
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
