from __future__ import annotations

from tests.modules.t05_junction_surface_fusion.phase2_test_support import *  # noqa: F401,F403


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


def test_t03_road_only_split_groups_near_endpoint_support_node(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("451")],
        swsd_nodes=[_node(451, 0.5, 0, mainnodeid="451", kind_2=4)],
        rcsd_roads=[
            _road(1, (-10, 0), (10, 0), snodeid=1, enodeid=2),
            _road(2, (0, 10), (10, 10), snodeid=3, enodeid=4),
        ],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(3, 0, 10),
            _node(4, 10, 10),
        ],
        t03_rows=[
            {
                "target_id": "451",
                "case_id": "451",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1|2",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 5
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["original_rcsdnode_ids"] == "3"
    assert audit_rows[0]["new_rcsdnode_ids"] == "5"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == "3|5"
    assert audit_rows[0]["projection_point_count"] == "2"
    assert audit_rows[0]["split_point_count"] == "1"
    output_nodes = {
        feature.properties["id"]: feature.properties.get("mainnodeid")
        for feature in read_vector_layer(artifacts.rcsdnode_out_path).features
    }
    assert str(output_nodes[3]) == "5"
    assert str(output_nodes[5]) == "5"


def test_t03_road_only_split_does_not_group_multiple_near_endpoint_support_nodes(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("452")],
        swsd_nodes=[_node(452, 0.5, 0, mainnodeid="452", kind_2=4)],
        rcsd_roads=[
            _road(1, (-10, 0), (10, 0), snodeid=1, enodeid=2),
            _road(2, (0, 10), (10, 10), snodeid=3, enodeid=4),
            _road(3, (0, -10), (10, -10), snodeid=5, enodeid=6),
        ],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(3, 0, 10),
            _node(4, 10, 10),
            _node(5, 0, -10),
            _node(6, 10, -10),
        ],
        t03_rows=[
            {
                "target_id": "452",
                "case_id": "452",
                "junction_type": "center_junction",
                "association_class": "B",
                "support_rcsdroad_ids": "1|2|3",
                "step7_state": "accepted",
                "relation_state": "rcsd_present_not_junction",
                "status_suggested": 1,
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    assert relation["properties"]["base_id"] == 7
    audit_rows = list(csv.DictReader(artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8")))
    assert audit_rows[0]["original_rcsdnode_ids"] == ""
    assert audit_rows[0]["new_rcsdnode_ids"] == "7"
    assert audit_rows[0]["grouped_rcsdnode_ids"] == ""
    output_nodes = {
        feature.properties["id"]: feature.properties.get("mainnodeid")
        for feature in read_vector_layer(artifacts.rcsdnode_out_path).features
    }
    assert output_nodes[3] is None
    assert output_nodes[5] is None
    assert output_nodes[7] is None


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


def test_t04_fallback_handoff_without_alignment_type_splits(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("525")],
        swsd_nodes=[_node(525, 0, 10, mainnodeid="525")],
        rcsd_roads=[_road(1, (0, 0), (100, 0))],
        rcsd_nodes=[_node(1, 0, 0), _node(2, 100, 0)],
        t04_rows=[
            {
                "target_id": "525",
                "case_id": "525",
                "junction_type": "merge",
                "surface_scenario_type": "main_evidence_with_rcsdroad_fallback",
                "final_state": "accepted",
                "fallback_rcsdroad_ids": "1",
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
    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["status"] == 0
    audit = list(csv.DictReader(artifacts.relation_audit_csv_path.open("r", encoding="utf-8")))[0]
    assert audit["source_module"] == "T04"
    assert audit["reason"] == "main_evidence_with_rcsdroad_fallback"


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
