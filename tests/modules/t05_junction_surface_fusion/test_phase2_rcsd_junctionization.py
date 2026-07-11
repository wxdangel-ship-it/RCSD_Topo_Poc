from __future__ import annotations

from tests.modules.t05_junction_surface_fusion.phase2_test_support import *  # noqa: F401,F403


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
    assert artifacts.junction_anchor_failure_reasons_csv_path is not None
    assert artifacts.junction_anchor_failure_reasons_csv_path.exists()


def test_t11_manual_relation_overrides_existing_1v1_with_group_relation(tmp_path: Path) -> None:
    artifacts = _run_phase2(
        tmp_path,
        surface_features=[_surface("605415675")],
        swsd_nodes=[_node(605415675, 0, 0, mainnodeid="605415675", grade=2, closed_con=1)],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[_node(1001, -1, 0), _node(1002, 1, 0), _node(2001, 20, 0)],
        t04_rows=[
            {
                "target_id": "605415675",
                "case_id": "605415675",
                "base_id_candidate": "2001",
                "status_suggested": "0",
                "relation_state": "success_required_rcsd_junction",
            }
        ],
        t11_manual_rows=[
            {
                "case_id": "605415675",
                "target_id": "605415675",
                "manual_relation_type": "1vN_rcsd_junction",
                "selected_ids": "1001|1002",
                "comment": "",
            }
        ],
    )

    relation = _relation_features(artifacts.relation_geojson_path)[0]
    assert relation["properties"]["target_id"] == "605415675"
    assert relation["properties"]["base_id"] in {1001, 1002}
    with artifacts.rcsd_junctionization_audit_csv_path.open("r", encoding="utf-8", newline="") as handle:
        audit = list(csv.DictReader(handle))[0]
    assert audit["source_module"] == "T11_MANUAL"
    assert audit["reason"] == "t11_manual_1vN_rcsd_junction"


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
