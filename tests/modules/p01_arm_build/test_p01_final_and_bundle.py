from __future__ import annotations

from tests.modules.p01_arm_build.p01_test_support import *  # noqa: F401,F403


def test_frcsd_mixed_source_reference_source_priority() -> None:
    profile = ArmSourceProfile(
        dataset="FRCSD",
        arm_id="F_A",
        source_distribution={"1": 1, "2": 1},
        trunk_source_distribution={"1": 1},
        advance_left_source_distribution={},
        parallel_branch_source_distribution={"2": 1},
        source_mixed=True,
        risk_flags=("mixed_source_arm",),
    )

    reference, reason, issues = _choose_reference_source(
        profile,
        {"SWSD": ("S_A", "structure_matched"), "RCSD": ("R_A", "structure_matched")},
    )
    assert (reference, reason) == ("SWSD", "mixed_source_structure_matched_swsd")
    assert "mixed_source_arm" in issues

    reference, reason, _ = _choose_reference_source(
        profile,
        {"SWSD": (None, "unmatched"), "RCSD": ("R_A", "structure_matched")},
    )
    assert (reference, reason) == ("RCSD", "mixed_source_structure_matched_rcsd")

    reference, reason, issues = _choose_reference_source(
        profile,
        {"SWSD": (None, "unmatched"), "RCSD": (None, "unmatched")},
    )
    assert (reference, reason) == ("SWSD", "mixed_source_swsd_basic_rule_fallback")
    assert "low_confidence_swsd_basic_rule" in issues


def test_road_next_road_json_and_geojson_are_normalised(tmp_path: Path) -> None:
    swsd_path = tmp_path / "RoadNextRoad.json"
    swsd_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "roadId": -1,
                    "nextRoadId": -2,
                    "road_id": "r1",
                    "next_road_id": "r2",
                    "turnType": 8,
                    "type": 1,
                    "source": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    geojson_path = tmp_path / "RoadNextRoad.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id": 2,
                            "road_id": "r3",
                            "next_road_id": "r4",
                            "turntype": 4,
                            "source": 1,
                        },
                        "geometry": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    swsd = read_road_next_road(swsd_path)
    rcsd = read_road_next_road(geojson_path)

    assert swsd[0].road_id == "r1"
    assert swsd[0].next_road_id == "r2"
    assert swsd[0].raw_turn_type == "8"
    assert rcsd[0].road_id == "r3"
    assert rcsd[0].next_road_id == "r4"
    assert rcsd[0].raw_turn_type == "4"


def test_road_next_road_movement_excludes_advance_left_only_receiving_trunk(tmp_path: Path) -> None:
    nodes_path, roads_path = _movement_fixture(tmp_path)
    rnr_path = tmp_path / "RoadNextRoad.json"
    rnr_path.write_text(
        json.dumps(
            [
                {"id": "straight", "road_id": "w_in", "next_road_id": "e_main", "turnType": "left_code"},
                {"id": "adv_left", "road_id": "n_adv_left", "next_road_id": "e_left_recv", "turnType": "straight_code"},
                {"id": "outside", "road_id": "outside_a", "next_road_id": "outside_b", "turnType": "4"},
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(
        loaded,
        junction_id="C",
        right_turn_formway_values={"128"},
        road_next_road_records=read_road_next_road(rnr_path),
        has_road_next_road_input=True,
    )

    from_w = _arm_id_by_seed(result, "w_in")
    from_n = _arm_id_by_seed(result, "n_adv_left")
    to_e = _arm_id_by_seed(result, "e_main")
    straight = next(item for item in result.arm_movements if item.from_arm_id == from_w and item.to_arm_id == to_e)
    left = next(item for item in result.arm_movements if item.from_arm_id == from_n and item.to_arm_id == to_e)
    correction = next(item for item in result.trunk_corrections if item.arm_id == to_e)

    assert len(result.arm_movements) == len(result.final_arms) * len(result.final_arms)
    assert result.metrics["road_movement_input_record_count"] == 3
    assert result.metrics["road_movement_case_scoped_record_count"] == 2
    assert result.metrics["road_movement_out_of_scope_skipped_count"] == 1
    assert result.metrics["road_movement_evidence_count"] == 2
    assert result.metrics["road_movement_mapped_count"] == 2
    assert result.metrics["road_movement_unmapped_count"] == 0
    assert "road_movement_cross_junction_or_out_of_scope" not in result.issue_report.issue_counts
    assert straight.movement_type == "straight"
    assert straight.permission_evidence_status == "allowed_supported"
    assert left.movement_type == "left"
    assert left.has_advance_left_road_evidence is True
    assert correction.trunk_correction_status == "corrected"
    assert correction.movement_excluded_receiving_road_ids == ("e_left_recv",)
    assert "e_left_recv" not in correction.corrected_trunk_road_ids
    assert "e_main" in correction.corrected_trunk_road_ids
    assert any(role.road_id == "e_left_recv" and role.exclude_from_trunk for role in result.arm_receiving_road_roles)
    assert result.corrected_final_arms
    assert result.corrected_final_arms[0].final_arm["advance_left_turn_road_ids"] is not None


def test_road_next_road_without_straight_receiving_does_not_exclude_trunk(tmp_path: Path) -> None:
    nodes_path, roads_path = _movement_fixture(tmp_path)
    rnr_path = tmp_path / "RoadNextRoad.json"
    rnr_path.write_text(
        json.dumps([{"id": "adv_left", "road_id": "n_adv_left", "next_road_id": "e_left_recv", "turnType": 1}]),
        encoding="utf-8",
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(
        loaded,
        junction_id="C",
        right_turn_formway_values={"128"},
        road_next_road_records=read_road_next_road(rnr_path),
        has_road_next_road_input=True,
    )

    to_e = _arm_id_by_seed(result, "e_main")
    correction = next(item for item in result.trunk_corrections if item.arm_id == to_e)

    assert correction.trunk_correction_status == "straight_evidence_missing"
    assert correction.movement_excluded_receiving_road_ids == tuple()
    assert "e_left_recv" in correction.corrected_trunk_road_ids


def test_frcsd_road_next_road_same_source_inheritance(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    swsd_rnr = tmp_path / "swsd_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_allowed", "road_id": "s_w_in", "next_road_id": "s_e_main", "turnType": 9},
                {"id": "s_allowed_all_exit", "road_id": "s_w_in", "next_road_id": "s_e_left_recv", "turnType": 9},
                {"id": "s_adv_left", "road_id": "s_n_adv_left", "next_road_id": "s_e_left_recv", "turnType": 9},
            ]
        ),
        encoding="utf-8",
    )
    frcsd_rnr = tmp_path / "frcsd_rnr.json"
    frcsd_rnr.write_text(
        json.dumps(
            [
                {"id": "f_allowed", "road_id": "f_w_in", "next_road_id": "f_e_main", "turnType": 9},
                {"id": "f_allowed_all_exit", "road_id": "f_w_in", "next_road_id": "f_e_left_recv", "turnType": 9},
                {"id": "f_adv_left", "road_id": "f_n_adv_left", "next_road_id": "f_e_left_recv", "turnType": 9},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    frcsd_records = read_road_next_road(frcsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads, frcsd_records)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": frcsd_records},
    )
    geojson = final_geojson(final)

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in geojson["features"]}
    assert ("f_w_in", "f_e_main") in pairs
    assert ("f_w_in", "f_e_left_recv") in pairs
    assert final.metrics["frcsd_same_source_inherited_count"] >= 1
    assert all(item.match_status == "matched" for item in final.source_road_map)
    assert geojson["features"][0]["geometry"] is None
    assert {"id", "road_id", "next_road_id", "type", "source", "turntype", "city_code"} <= set(
        geojson["features"][0]["properties"]
    )
    assert all(set(profile.source_distribution) <= {"2"} for profile in final.arm_source_profiles)
    assert any(rule.rule_status == "full_allowed" for rule in final.source_arm_pass_rules_swsd)
    assert any(decision.generation_scope == "all_target_exit_roads" for decision in final.final_generation_decisions)
    conflict_result_f = replace(
        result_f,
        final_arms=tuple(
            replace(arm, validation_status="conflict", validation_id="validation_conflict", validation_confidence="none")
            for arm in result_f.final_arms
        ),
    )
    conflict_final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": conflict_result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": frcsd_records},
    )
    assert "final_arm_validation_conflict" in conflict_final.issue_report["issue_counts"]
    assert any("final_arm_validation_conflict" in item.issue_flags for item in conflict_final.audit)


def test_frcsd_rule_projection_uses_entering_from_roads_and_exiting_target_roads(tmp_path: Path) -> None:
    def write_source_fixture(prefix: str) -> tuple[Path, Path]:
        nodes_path = tmp_path / f"{prefix}_opposed_nodes.gpkg"
        roads_path = tmp_path / f"{prefix}_opposed_roads.gpkg"
        _write_nodes(
            nodes_path,
            [
                ("C", "C", 0.0, 0.0, "4"),
                ("W", None, -20.0, 0.0, "1"),
                ("E", None, 20.0, 0.0, "1"),
            ],
        )
        _write_roads(
            roads_path,
            [
                (f"{prefix}_w_in", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
                (f"{prefix}_e_out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
                (f"{prefix}_e_in", "E", "C", 2, "0", [(20.0, 1.0), (0.0, 1.0)]),
            ],
        )
        return nodes_path, roads_path

    f_nodes = tmp_path / "f_opposed_nodes.gpkg"
    f_roads = tmp_path / "f_opposed_roads.gpkg"
    _write_nodes(
        f_nodes,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("W", None, -20.0, 0.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads_with_source(
        f_roads,
        [
            ("f_w_in", "W", "C", 2, "0", "2", [(-20.0, 0.0), (0.0, 0.0)]),
            ("f_e_out", "C", "E", 2, "0", "2", [(0.0, 0.0), (20.0, 0.0)]),
            ("f_e_in", "E", "C", 2, "0", "2", [(20.0, 1.0), (0.0, 1.0)]),
        ],
    )
    swsd_nodes, swsd_roads = write_source_fixture("s")
    rcsd_nodes, rcsd_roads = write_source_fixture("r")
    swsd_rnr = tmp_path / "swsd_direction_filtered_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_allowed_exit", "road_id": "s_w_in", "next_road_id": "s_e_out"},
                {"id": "s_ignore_inbound_target", "road_id": "s_w_in", "next_road_id": "s_e_in"},
                {"id": "s_ignore_outbound_from", "road_id": "s_e_out", "next_road_id": "s_w_in"},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", f_nodes, f_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in final_geojson(final)["features"]}
    assert ("f_w_in", "f_e_out") in pairs
    assert ("f_w_in", "f_e_in") not in pairs
    assert all(from_road_id != "f_e_out" for from_road_id, _ in pairs)


def test_frcsd_source_geometry_mapping_normalises_crs_before_rounded_exact_match(tmp_path: Path) -> None:
    to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    lonlat_nodes = {
        "C": (114.0, 22.0),
        "N": (114.0, 22.001),
        "W": (113.999, 22.0),
        "E": (114.001, 22.0),
    }
    source_nodes = [(node_id, mainnode, *to_3857(x, y), kind) for node_id, mainnode, x, y, kind in [
        ("C", "C", *lonlat_nodes["C"], "4"),
        ("N", None, *lonlat_nodes["N"], "1"),
        ("W", None, *lonlat_nodes["W"], "1"),
        ("E", None, *lonlat_nodes["E"], "1"),
    ]]
    source_roads = [
        ("s_n_adv_left", "N", "C", 2, "256", [to_3857(*lonlat_nodes["N"]), to_3857(*lonlat_nodes["C"])]),
        ("s_w_in", "W", "C", 2, "0", [to_3857(*lonlat_nodes["W"]), to_3857(*lonlat_nodes["C"])]),
        ("s_e_main", "C", "E", 2, "0", [to_3857(*lonlat_nodes["C"]), to_3857(*lonlat_nodes["E"])]),
    ]
    frcsd_nodes = [(node_id, mainnode, x, y, kind) for node_id, mainnode, x, y, kind in [
        ("C", "C", *lonlat_nodes["C"], "4"),
        ("N", None, *lonlat_nodes["N"], "1"),
        ("W", None, *lonlat_nodes["W"], "1"),
        ("E", None, *lonlat_nodes["E"], "1"),
    ]]
    frcsd_roads = [
        ("f_n_adv_left", "N", "C", 2, "256", "2", [lonlat_nodes["N"], lonlat_nodes["C"]]),
        ("f_w_in", "W", "C", 2, "0", "2", [lonlat_nodes["W"], lonlat_nodes["C"]]),
        ("f_e_main", "C", "E", 2, "0", "2", [lonlat_nodes["C"], lonlat_nodes["E"]]),
    ]

    swsd_nodes = tmp_path / "swsd_nodes_3857.gpkg"
    swsd_roads = tmp_path / "swsd_roads_3857.gpkg"
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    f_nodes = tmp_path / "frcsd_nodes_4326.gpkg"
    f_roads = tmp_path / "frcsd_roads_4326.gpkg"
    _write_nodes(swsd_nodes, source_nodes, crs="EPSG:3857")
    _write_roads(swsd_roads, source_roads, crs="EPSG:3857")
    _write_nodes(f_nodes, frcsd_nodes, crs="EPSG:4326")
    _write_roads_with_source(f_roads, frcsd_roads, crs="EPSG:4326")
    swsd_rnr = tmp_path / "swsd_rnr.json"
    swsd_rnr.write_text(
        json.dumps([{"id": "s_allowed", "road_id": "s_w_in", "next_road_id": "s_e_main"}]),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)

    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", f_nodes, f_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert all(item.match_status == "matched" for item in final.source_road_map)
    assert any(item.source_road_id == "s_w_in" for item in final.source_road_map)
    assert final.metrics["frcsd_same_source_inherited_count"] >= 1


def test_frcsd_source_policy_records_prohibited_and_missing_right_carrier_issue(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert any(item.permission_status == "prohibited" for item in final.source_movement_policy_swsd)
    assert any(item.permission_status == "prohibited" for item in final.source_movement_policy_rcsd)
    assert final.metrics["frcsd_generated_road_next_road_count"] == 0
    assert all(item.generated_road_ids == tuple() for item in final.final_generation_decisions)


def test_frcsd_road_next_road_cross_source_uses_primary_source(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="1", to_source="2")
    rcsd_rnr = tmp_path / "rcsd_rnr.geojson"
    rcsd_rnr.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"id": "r_allowed", "road_id": "r_w_in", "next_road_id": "r_e_main", "turntype": 1},
                    },
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"id": "r_allowed_all_exit", "road_id": "r_w_in", "next_road_id": "r_e_left_recv", "turntype": 1},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    rcsd_records = read_road_next_road(rcsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads, rcsd_records)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": rcsd_records, "FRCSD": tuple()},
    )

    generated = [
        item
        for item in final.audit
        if item.f_road_id == "f_w_in" and item.f_next_road_id == "f_e_main" and item.permission_status == "allowed"
    ]
    assert generated
    assert generated[0].primary_source == "RCSD"
    assert generated[0].generation_rule == "cross_source_primary_source_policy"
    assert final.metrics["frcsd_cross_source_generated_count"] >= 1


def test_frcsd_road_next_road_rcsd_to_swsd_fallback(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="1", to_source="2")
    swsd_rnr = tmp_path / "swsd_fallback_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_fallback", "road_id": "s_w_in", "next_road_id": "s_e_main", "turnType": 1},
                {"id": "s_fallback_all_exit", "road_id": "s_w_in", "next_road_id": "s_e_left_recv", "turnType": 1},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    rcsd_target_arm = _arm_id_by_seed(result_r, "r_e_main")
    result_r = replace(
        result_r,
        final_arms=tuple(arm for arm in result_r.final_arms if arm.final_arm_id != rcsd_target_arm),
        arm_movements=tuple(
            movement
            for movement in result_r.arm_movements
            if movement.from_arm_id != rcsd_target_arm and movement.to_arm_id != rcsd_target_arm
        ),
    )
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    fallback = [
        item
        for item in final.audit
        if item.f_road_id == "f_w_in" and item.f_next_road_id == "f_e_main" and item.permission_status == "allowed"
    ]
    assert fallback
    assert fallback[0].generation_rule == "rcsd_to_swsd_fallback"
    assert fallback[0].reference_source == "SWSD"
    assert final.metrics["frcsd_fallback_to_swsd_count"] >= 1


def test_frcsd_rule_projection_does_not_require_exact_source_match(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes = tmp_path / "frcsd_shifted_nodes.gpkg"
    frcsd_roads = tmp_path / "frcsd_shifted_roads.gpkg"
    _write_nodes(
        frcsd_nodes,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("W", None, -20.0, 0.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads_with_source(
        frcsd_roads,
        [
            ("f_n_adv_left", "N", "C", 2, "256", "2", [(0.0, 20.0), (0.0, 0.0)]),
            ("f_w_in", "W", "C", 2, "0", "2", [(-20.0, 0.05), (0.0, 0.05)]),
            ("f_e_main", "C", "E", 2, "0", "2", [(0.0, 0.0), (20.0, 0.0)]),
            ("f_e_left_recv", "C", "E", 2, "0", "2", [(0.0, 1.0), (20.0, 1.0)]),
        ],
    )
    swsd_rnr = tmp_path / "swsd_full_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_allowed_main", "road_id": "s_w_in", "next_road_id": "s_e_main"},
                {"id": "s_allowed_branch", "road_id": "s_w_in", "next_road_id": "s_e_left_recv"},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)
    result_s = _with_left_recv_as_parallel(result_s, "s")
    result_f = _with_left_recv_as_parallel(result_f, "f")

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in final_geojson(final)["features"]}
    assert {("f_w_in", "f_e_main"), ("f_w_in", "f_e_left_recv")} <= pairs
    assert any(item.f_road_id == "f_w_in" and item.match_status == "source_geometry_match_missing" for item in final.source_road_map)
    assert any(item.generation_basis == "rule_projected" for item in final.audit)


def test_frcsd_rule_projection_reports_trunk_partial_target_coverage(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    swsd_rnr = tmp_path / "swsd_partial_rnr.json"
    swsd_rnr.write_text(json.dumps([{"id": "s_partial", "road_id": "s_w_in", "next_road_id": "s_e_main"}]), encoding="utf-8")
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)
    result_s = _with_left_recv_as_parallel(result_s, "s")
    result_f = _with_left_recv_as_parallel(result_f, "f")

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in final_geojson(final)["features"]}
    assert ("f_w_in", "f_e_main") in pairs
    assert ("f_w_in", "f_e_left_recv") not in pairs
    assert any(
        decision.rule_status == "trunk_only_allowed" and decision.generation_scope == "trunk_only"
        for decision in final.final_generation_decisions
    )


def test_frcsd_rule_projection_reports_parallel_branch_partial_target_coverage(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    swsd_rnr = tmp_path / "swsd_parallel_partial_rnr.json"
    swsd_rnr.write_text(
        json.dumps([{"id": "s_parallel_partial", "road_id": "s_w_in", "next_road_id": "s_e_main"}]),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)
    result_s = _with_left_recv_as_parallel(result_s, "s")
    result_f = _with_left_recv_as_parallel(result_f, "f")
    result_s = _with_road_as_parallel(result_s, "s_w_in")
    result_f = _with_road_as_parallel(result_f, "f_w_in")

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in final_geojson(final)["features"]}
    assert ("f_e_left_recv", "f_e_main") not in pairs
    assert any(
        decision.from_road_role == "parallel_branch"
        and decision.rule_status == "data_error_partial_target_coverage"
        for decision in final.final_generation_decisions
    )
    assert "data_error_partial_target_coverage" in final.issue_report["issue_counts"]


def test_frcsd_rule_projection_allows_advance_left_and_uturn_special_scopes(tmp_path: Path) -> None:
    def write_source_fixture(prefix: str) -> tuple[Path, Path]:
        nodes_path = tmp_path / f"{prefix}_special_nodes.gpkg"
        roads_path = tmp_path / f"{prefix}_special_roads.gpkg"
        _write_nodes(
            nodes_path,
            [
                ("C", "C", 0.0, 0.0, "4"),
                ("N", None, 0.0, 20.0, "1"),
                ("E", None, 20.0, 0.0, "1"),
            ],
        )
        _write_roads(
            roads_path,
            [
                (f"{prefix}_n_adv_left", "N", "C", 2, "256", [(0.0, 20.0), (0.0, 0.0)]),
                (f"{prefix}_e_in", "E", "C", 2, "0", [(20.0, 0.0), (0.0, 0.0)]),
                (f"{prefix}_e_main", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
                (f"{prefix}_e_left_recv", "C", "E", 2, "0", [(0.0, 1.0), (20.0, 1.0)]),
            ],
        )
        return nodes_path, roads_path

    swsd_nodes, swsd_roads = write_source_fixture("s")
    rcsd_nodes, rcsd_roads = write_source_fixture("r")
    frcsd_nodes = tmp_path / "f_special_nodes.gpkg"
    frcsd_roads = tmp_path / "f_special_roads.gpkg"
    _write_nodes(
        frcsd_nodes,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads_with_source(
        frcsd_roads,
        [
            ("f_n_adv_left", "N", "C", 2, "256", "2", [(0.0, 20.0), (0.0, 0.0)]),
            ("f_e_in", "E", "C", 2, "0", "2", [(20.0, 0.0), (0.0, 0.0)]),
            ("f_e_main", "C", "E", 2, "0", "2", [(0.0, 0.0), (20.0, 0.0)]),
            ("f_e_left_recv", "C", "E", 2, "0", "2", [(0.0, 1.0), (20.0, 1.0)]),
        ],
    )
    swsd_rnr = tmp_path / "swsd_special_scope_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_adv_left_only", "road_id": "s_n_adv_left", "next_road_id": "s_e_left_recv"},
                {"id": "s_uturn_trunk_only", "road_id": "s_e_in", "next_road_id": "s_e_main"},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)
    result_s = _with_left_recv_as_parallel(result_s, "s")
    result_f = _with_left_recv_as_parallel(result_f, "f")

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert any(
        decision.from_road_role == "advance_left"
        and decision.rule_status == "left_receiving_only_allowed"
        and decision.generation_scope == "left_receiving_only"
        for decision in final.final_generation_decisions
    )
    assert any(
        decision.movement_type == "uturn"
        and decision.from_road_role == "trunk"
        and decision.rule_status == "trunk_only_allowed"
        for decision in final.final_generation_decisions
    )
    assert "data_error_partial_target_coverage" not in final.issue_report["issue_counts"]


def test_frcsd_rule_projection_parallel_branch_full_allowed(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    swsd_rnr = tmp_path / "swsd_parallel_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_parallel_main", "road_id": "s_w_in", "next_road_id": "s_e_main"},
                {"id": "s_parallel_branch", "road_id": "s_w_in", "next_road_id": "s_e_left_recv"},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)
    result_s = _with_left_recv_as_parallel(result_s, "s")
    result_f = _with_left_recv_as_parallel(result_f, "f")
    result_s = _with_road_as_parallel(result_s, "s_w_in")
    result_f = _with_road_as_parallel(result_f, "f_w_in")

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert any(
        decision.from_road_role == "parallel_branch"
        and decision.rule_status == "full_allowed"
        and decision.generated_road_ids == ("f_w_in",)
        for decision in final.final_generation_decisions
    )


def test_frcsd_source_geometry_mapping_missing_and_ambiguous_are_issues(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    duplicate_path = tmp_path / "s_duplicate_roads.gpkg"
    _write_roads(
        duplicate_path,
        [
            ("s_w_in", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            ("s_w_in_dup", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            ("s_e_main", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("s_e_left_recv", "C", "E", 2, "0", [(0.0, 1.0), (20.0, 1.0)]),
            ("s_n_adv_left", "N", "C", 2, "256", [(0.0, 20.0), (0.0, 0.0)]),
        ],
    )
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, duplicate_path)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert final.metrics["frcsd_source_geometry_match_ambiguous_count"] >= 1
    assert "ambiguous_source_geometry_match" in final.issue_report["issue_counts"]


def test_dataset_review_context_excludes_far_unrelated_roads(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S", include_far_noise=True)
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    geometries, road_ids, node_ids = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)

    assert "S_far_noise" not in road_ids
    assert "Sfar_a" not in node_ids
    assert bounds[2] < 120.0
    assert bounds[3] < 60.0


def test_dataset_review_context_stays_near_junction_for_long_traces(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S", include_far_trace=True)
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    geometries, road_ids, _ = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)

    assert any("S1_far_trace" in trace.traced_road_ids for trace in result.traces)
    assert "S1_far_trace" not in road_ids
    assert bounds[2] < 120.0


def test_local_arm_candidates_group_current_seed_trends_with_optional_final_fallback(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S")
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    assert len(result.final_arms) == len(result.initial_arms)
    assert {arm.merge_status for arm in result.final_arms} == {"not_applied"}
    assert len(result.local_arm_candidates) == 4
    west = next(item for item in result.local_arm_candidates if item.bidirectional_seed_road_ids == ("S1_bi",))
    east = next(item for item in result.local_arm_candidates if item.outbound_seed_road_ids == ("S1_east_seed",))

    assert west.build_status == "candidate"
    assert east.local_stub_road_ids == ("S1_east_continue", "S1_east_seed")
    assert "S1_right_turn" not in {seed for item in result.local_arm_candidates for seed in item.source_seed_road_ids}
    assert result.metrics["local_arm_candidate_count"] == 4


def test_final_arms_use_local_candidate_fallback_when_trace_fragments_same_local_arm(tmp_path: Path) -> None:
    nodes_path = tmp_path / "fallback_nodes.gpkg"
    roads_path = tmp_path / "fallback_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("D", None, 20.0, 0.0, "0"),
            ("B", None, 10.0, 0.5, "1"),
            ("T", "T", 20.0, 0.8, "4"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("dead_seed", "C", "D", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("live_seed", "C", "B", 2, "0", [(0.0, 0.0), (10.0, 0.5)]),
            ("live_continue", "B", "T", 2, "0", [(10.0, 0.5), (20.0, 0.8)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert len(result.initial_arms) == 2
    assert len(result.local_arm_candidates) == 1
    assert len(result.final_arms) == 1
    assert result.final_arms[0].source_initial_arm_ids == ("A1", "A2")
    assert result.final_arms[0].merge_status == "local_candidate_fallback"
    assert result.metrics["final_arm_count"] == 1
    assert result.metrics["local_arm_fragmentation_gap"] == 1


def test_through_tie_break_avoids_near_parallel_one_hop_dead_end(tmp_path: Path) -> None:
    nodes_path = tmp_path / "tie_nodes.gpkg"
    roads_path = tmp_path / "tie_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("G", None, 10.0, 0.0, "1"),
            ("D", None, 20.0, 0.1, "0"),
            ("L", None, 20.0, 0.5, "1"),
            ("T", "T", 30.0, 1.0, "4"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("seed", "C", "G", 2, "0", [(0.0, 0.0), (10.0, 0.0)]),
            ("dead_candidate", "G", "D", 2, "0", [(10.0, 0.0), (20.0, 0.1)]),
            ("live_candidate", "G", "L", 2, "0", [(10.0, 0.0), (20.0, 0.5)]),
            ("live_continue", "L", "T", 2, "0", [(20.0, 0.5), (30.0, 1.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("FRCSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.traces[0].traced_road_ids == ("seed", "live_candidate", "live_continue")
    assert "dead_candidate" not in result.traces[0].traced_road_ids
    assert result.decisions[0].outgoing_road_id == "live_candidate"
    assert "tie_break=near_parallel_non_dead_end_over_one_hop_dead_end" in result.decisions[0].decision_reason


def test_kind_aware_t_junction_and_kind4_stop_rules(tmp_path: Path) -> None:
    nodes_path = tmp_path / "kind_nodes.gpkg"
    roads_path = tmp_path / "kind_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("JM", "JM", 0.0, 0.0, "4"),
            ("TM", None, 10.0, 0.0, "2048"),
            ("EM", None, 20.0, 0.0, "1"),
            ("NM", None, 10.0, 10.0, "1"),
            ("JS", "JS", 0.0, 40.0, "4"),
            ("TS", None, 0.0, 50.0, "2048"),
            ("WS", None, -10.0, 50.0, "1"),
            ("ES", None, 10.0, 50.0, "1"),
            ("JK", "JK", 0.0, 80.0, "4"),
            ("K4", None, 10.0, 80.0, "4"),
            ("EK", None, 20.0, 80.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("main_seed", "JM", "TM", 2, "0", [(0.0, 0.0), (10.0, 0.0)]),
            ("main_continue", "TM", "EM", 2, "0", [(10.0, 0.0), (20.0, 0.0)]),
            ("main_side", "TM", "NM", 2, "0", [(10.0, 0.0), (10.0, 10.0)]),
            ("side_seed", "JS", "TS", 2, "0", [(0.0, 40.0), (0.0, 50.0)]),
            ("side_left", "WS", "TS", 2, "0", [(-10.0, 50.0), (0.0, 50.0)]),
            ("side_right", "TS", "ES", 2, "0", [(0.0, 50.0), (10.0, 50.0)]),
            ("kind4_seed", "JK", "K4", 2, "0", [(0.0, 80.0), (10.0, 80.0)]),
            ("kind4_continue", "K4", "EK", 2, "0", [(10.0, 80.0), (20.0, 80.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    mainline = build_dataset_arm_result(loaded, junction_id="JM", right_turn_formway_values={"128"})
    assert any(decision.status == "t_mainline_through" for decision in mainline.decisions)
    assert any("main_continue" in trace.traced_road_ids for trace in mainline.traces)

    side = build_dataset_arm_result(loaded, junction_id="JS", right_turn_formway_values={"128"})
    assert side.traces[0].stop_type == "t_side_terminal"
    assert side.traces[0].traced_road_ids == ("side_seed",)

    kind4 = build_dataset_arm_result(loaded, junction_id="JK", right_turn_formway_values={"128"})
    assert kind4.traces[0].stop_type == "dead_end"
    assert kind4.traces[0].traced_road_ids == ("kind4_seed", "kind4_continue")


def test_p01_text_bundle_roundtrip_uses_bfs_context_not_far_spatial_noise(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_noise=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_noise=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_noise=True, road_source="2")
    bundle_path = tmp_path / "p01_case_bundle.txt"
    swsd_road_node_road = tmp_path / "SWSD_RoadNodeRoad.json"
    swsd_road_node_road.write_text(
        json.dumps(
            [
                {"id": "s_keep", "road_id": "S1_in", "next_road_id": "S1_out", "turnType": "raw_keep"},
                {"id": "s_far", "road_id": "S_far_noise", "next_road_id": "S_far_other", "turnType": "raw_far"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rcsd_road_next_road = tmp_path / "RCSD_RoadNextRoad.geojson"
    rcsd_road_next_road.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {
                            "id": "r_keep",
                            "road_id": "R1_in",
                            "next_road_id": "R1_out",
                            "turntype": "audit_only",
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {
                            "id": "r_far",
                            "road_id": "R_far_noise",
                            "next_road_id": "R_far_other",
                            "turntype": "audit_far",
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        swsd_road_node_road=swsd_road_node_road,
        rcsd_road_next_road=rcsd_road_next_road,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=1,
    )

    assert artifacts.success, artifacts.failure_detail
    assert bundle_path.is_file()
    assert artifacts.bundle_size_bytes <= P01_TEXT_BUNDLE_LIMIT_BYTES

    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_bundle")
    assert decoded.success
    swsd_decoded = decoded.out_dir / "SWSD"
    road_ids = _feature_ids(swsd_decoded / "roads.gpkg")
    node_ids = _feature_ids(swsd_decoded / "nodes.gpkg")

    assert "S1_east_seed" in road_ids
    assert "S1_east_continue" in road_ids
    assert "S_far_noise" not in road_ids
    assert "Sfar_a" not in node_ids
    with fiona.open(decoded.out_dir / "FRCSD" / "roads.gpkg") as src:
        schema_keys = {key.lower() for key in src.schema["properties"]}
        decoded_roads = [dict(feature["properties"]) for feature in src]
    assert "source" in schema_keys
    assert "grade_2" in schema_keys
    assert {str(item.get("source") or item.get("Source")) for item in decoded_roads} == {"2"}
    swsd_rnr_payload = json.loads((decoded.out_dir / "SWSD" / "RoadNodeRoad.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in swsd_rnr_payload] == ["s_keep"]
    rcsd_rnr_payload = json.loads((decoded.out_dir / "RCSD" / "RoadNextRoad.geojson").read_text(encoding="utf-8"))
    assert [feature["properties"]["id"] for feature in rcsd_rnr_payload["features"]] == ["r_keep"]

    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    assert manifest["encoder_info"]["selection"] == "semantic-road-topology-bfs"
    assert manifest["datasets"]["SWSD"]["selected_road_count"] < 10
    assert manifest["datasets"]["SWSD"]["optional_relation_inputs"]["RoadNodeRoad.json"]["included_record_count"] == 1
    assert manifest["datasets"]["RCSD"]["optional_relation_inputs"]["RoadNextRoad.geojson"]["included_record_count"] == 1


def test_p01_text_bundle_resolves_dataset_junction_id_prefixes(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S")
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "C")
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "D")
    bundle_path = tmp_path / "p01_prefixed_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,RC1,FD1",
        out_txt=bundle_path,
        bfs_depth=1,
    )

    assert artifacts.success, artifacts.failure_detail

    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_prefixed")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert manifest["junction_group"] == {"SWSD": "S1", "RCSD": "RC1", "FRCSD": "FD1"}
    assert manifest["datasets"]["RCSD"]["resolved_group_id"] == "C1"
    assert manifest["datasets"]["FRCSD"]["resolved_group_id"] == "D1"
    assert _feature_ids(decoded.out_dir / "RCSD" / "nodes.gpkg")
    assert _feature_ids(decoded.out_dir / "FRCSD" / "roads.gpkg")


def test_p01_text_bundle_auto_fit_expands_to_deeper_trace_context(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_trace=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_trace=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_trace=True)
    bundle_path = tmp_path / "p01_auto_fit_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=1,
        auto_fit=True,
        max_bfs_depth=2,
    )

    assert artifacts.success, artifacts.failure_detail
    assert artifacts.selected_bfs_depth == 2
    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_auto_fit")
    road_ids = _feature_ids(decoded.out_dir / "SWSD" / "roads.gpkg")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert "S1_far_trace" in road_ids
    assert manifest["auto_fit"]["selected_bfs_depth"] == 2
    assert [attempt["bfs_depth"] for attempt in manifest["auto_fit"]["attempts"]] == [2]


def test_p01_text_bundle_splits_when_text_limit_is_too_small(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_trace=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_trace=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_trace=True)
    bundle_path = tmp_path / "p01_split_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=2,
        max_text_size_bytes=40_000,
    )

    assert artifacts.success, artifacts.failure_detail
    assert len(artifacts.part_txt_paths) > 1
    assert all(path.is_file() and path.stat().st_size <= 40_000 for path in artifacts.part_txt_paths)

    decoded = run_p01_decode_text_bundle(bundle_txt=artifacts.part_txt_paths[-1], out_dir=tmp_path / "decoded_split")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert set(manifest["datasets"]) == {"SWSD", "RCSD", "FRCSD"}
    assert (decoded.out_dir / "SWSD" / "roads.gpkg").is_file()
    assert (decoded.out_dir / "RCSD" / "roads.gpkg").is_file()
    assert (decoded.out_dir / "FRCSD" / "roads.gpkg").is_file()
    size_report = json.loads((decoded.out_dir / "size_report.json").read_text(encoding="utf-8"))
    assert size_report["split_bundle"]["enabled"] is True


def test_review_line_points_accepts_3d_coordinates() -> None:
    project = _projector((0.0, 0.0, 10.0, 10.0), left=0, top=0, width=100, height=100)

    points = _line_points(LineString([(0.0, 0.0, 5.0), (10.0, 10.0, 6.0)]), project)

    assert len(points) == 2
    assert all(len(point) == 2 for point in points)


def test_write_gpkg_layers_reports_locked_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gpkg_path = tmp_path / "review_layers.gpkg"
    gpkg_path.write_bytes(b"locked")
    original_unlink = Path.unlink

    def locked_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == gpkg_path:
            raise PermissionError("locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)

    with pytest.raises(RuntimeError, match="new --run-id"):
        write_gpkg_layers(gpkg_path, layers=[], crs=None, crs_wkt=None)


def test_p01_source_does_not_reference_grade_fields() -> None:
    source_dir = Path("src/rcsd_topo_poc/modules/p01_arm_build")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    assert "grade" not in source_text.lower()
