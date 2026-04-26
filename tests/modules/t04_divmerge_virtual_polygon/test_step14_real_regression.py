from __future__ import annotations

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403

def test_real_case_17943587_keeps_same_case_merge_branch_continuation_and_nested_pair_geometry() -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_17943587"
    )

    branch_road_memberships = event_unit.unit_envelope.branch_road_memberships
    merge_branch_1 = _find_branch_id_with_required_roads(
        branch_road_memberships,
        {"510969745"},
    )
    merge_branch_2 = _find_branch_id_with_required_roads(
        branch_road_memberships,
        {"607951495", "528620938"},
    )

    assert merge_branch_1 != merge_branch_2
    assert "607951495" not in set(branch_road_memberships[merge_branch_1])
    assert "510969745" not in set(branch_road_memberships[merge_branch_2])
    assert set(event_unit.unit_envelope.event_branch_ids) == {merge_branch_1, merge_branch_2}
    assert set(event_unit.unit_envelope.boundary_branch_ids) == {merge_branch_1, merge_branch_2}
    assert "55353233" in set(event_unit.unit_envelope.branch_bridge_node_ids[merge_branch_2])
    assert event_unit.pair_local_summary["operational_kind_hint"] == 8

    pair_middle = event_unit.pair_local_middle_geometry
    structure_face = event_unit.pair_local_structure_face_geometry
    pair_region = event_unit.pair_local_region_geometry

    assert pair_middle is not None and not pair_middle.is_empty
    assert structure_face is not None and not structure_face.is_empty
    assert pair_region is not None and not pair_region.is_empty
    assert structure_face.buffer(1e-6).covers(pair_middle)
    assert pair_region.buffer(1e-6).covers(structure_face)
    assert pair_middle.equals(structure_face) is False
    assert event_unit.selected_evidence_state == "found"
    assert event_unit.selected_evidence_summary["candidate_id"] == "node_17943587:divstrip:1:01"
    assert event_unit.selected_evidence_summary["node_fallback_only"] is False
    assert float(event_unit.selected_evidence_summary["reference_distance_to_origin_m"]) > 3.0
    assert event_unit.fact_reference_point is not None
    assert event_unit.selected_evidence_region_geometry is not None
    assert event_unit.selected_evidence_region_geometry.buffer(1e-6).covers(event_unit.fact_reference_point)
    assert float(
        event_unit.fact_reference_point.distance(event_unit.unit_context.representative_node.geometry)
    ) < float(event_unit.selected_evidence_summary["reference_distance_to_origin_m"])
    _assert_selected_candidate_region_is_pair_local_container(event_unit)

    sibling_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353233"
    )
    sibling_branch_road_memberships = sibling_unit.unit_envelope.branch_road_memberships
    sibling_merge_branch = _find_branch_id_with_required_roads(
        sibling_branch_road_memberships,
        {"502953712", "41727506", "620950831"},
    )
    assert set(sibling_branch_road_memberships[sibling_merge_branch]) == {
        "502953712",
        "41727506",
        "620950831",
    }
    assert "605949403" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert "607962170" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    sibling_output_branch = _find_branch_id_with_road(
        sibling_branch_road_memberships,
        "607951495",
    )
    assert set(sibling_branch_road_memberships[sibling_output_branch]) == {"607951495"}
    assert "529824990" not in set(sibling_branch_road_memberships[sibling_output_branch])

    local_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353248"
    )
    local_branch_road_memberships = local_unit.unit_envelope.branch_road_memberships
    local_merge_branch = _find_branch_id_with_required_roads(
        local_branch_road_memberships,
        {"41727506", "620950831"},
    )
    assert "607962170" not in set(local_branch_road_memberships[local_merge_branch])
    local_axis_branch = _find_branch_id_with_road(
        local_branch_road_memberships,
        "502953712",
    )
    assert set(local_branch_road_memberships[local_axis_branch]) == {"502953712"}
    assert local_unit.pair_local_summary["pair_scan_truncated_to_local"] is True
    assert set(local_unit.unit_envelope.event_branch_ids) == set(local_unit.unit_envelope.boundary_branch_ids)
    assert local_axis_branch not in set(local_unit.unit_envelope.event_branch_ids)
    _assert_one_sided_offsets(local_unit.pair_local_summary["valid_scan_offsets_m"])
    assert local_unit.selected_evidence_state == "found"
    assert local_unit.selected_evidence_summary["candidate_id"] == "node_55353248:divstrip:1:01"
    assert local_unit.selected_evidence_summary["node_fallback_only"] is False
    assert float(local_unit.selected_evidence_summary["reference_distance_to_origin_m"]) > 3.0
    assert local_unit.fact_reference_point is not None
    assert local_unit.selected_evidence_region_geometry is not None
    assert local_unit.selected_evidence_region_geometry.buffer(1e-6).covers(local_unit.fact_reference_point)
    assert float(
        local_unit.fact_reference_point.distance(local_unit.unit_context.representative_node.geometry)
    ) < float(local_unit.selected_evidence_summary["reference_distance_to_origin_m"])
    _assert_selected_candidate_region_is_pair_local_container(local_unit)
    assert local_unit.pair_local_middle_geometry is not None
    assert local_unit.pair_local_structure_face_geometry is not None
    assert float(local_unit.selected_candidate_region_geometry.area) >= float(
        local_unit.pair_local_structure_face_geometry.area
    )
    assert float(local_unit.pair_local_middle_geometry.area) == pytest.approx(
        float(local_unit.pair_local_summary["pair_local_middle_area_m2"]),
        abs=1e-3,
    )

def test_real_simple_three_arm_cases_keep_direct_event_pair_branches() -> None:
    expected_case_roads = {
        "785671": {
            "event_roads": {"980348", "527854843"},
            "axis_road": "600961614",
        },
        "987998": {
            "event_roads": {"1026704", "1078428"},
            "axis_road": "1035952",
        },
        "30434673": {
            "event_roads": {"530277767", "76761971"},
            "axis_road": "76761972",
        },
    }
    missing_cases = [case_id for case_id in expected_case_roads if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_case_roads),
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    for case_id, expected in expected_case_roads.items():
        case_result = build_case_result(load_case_bundle(case_by_id[case_id]))
        assert len(case_result.event_units) == 1
        event_unit = case_result.event_units[0]
        branch_road_memberships = event_unit.unit_envelope.branch_road_memberships

        event_branch_ids = {
            _find_branch_id_with_road(branch_road_memberships, road_id)
            for road_id in expected["event_roads"]
        }
        axis_branch_id = _find_branch_id_with_road(
            branch_road_memberships,
            expected["axis_road"],
        )

        assert event_unit.spec.split_mode == "one_case_one_unit"
        assert len(event_unit.unit_envelope.branch_ids) == 3
        assert event_branch_ids == set(event_unit.unit_envelope.event_branch_ids)
        assert event_branch_ids == set(event_unit.unit_envelope.boundary_branch_ids)
        assert axis_branch_id not in event_branch_ids
        assert set(branch_road_memberships[axis_branch_id]) == {expected["axis_road"]}
        assert event_unit.pair_local_summary["event_branch_ids"] == list(event_unit.unit_envelope.event_branch_ids)
        assert event_unit.pair_local_summary["boundary_branch_ids"] == list(event_unit.unit_envelope.boundary_branch_ids)
        _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])

def test_real_simple_two_branch_cases_prefer_divstrip_evidence_over_synthetic_middle_container() -> None:
    expected_candidates = {
        "785671": "event_unit_01:divstrip:2:01",
        "987998": "event_unit_01:divstrip:3:01",
        "30434673": "event_unit_01:divstrip:3:01",
    }
    missing_cases = [case_id for case_id in expected_candidates if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_candidates),
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    for case_id, expected_candidate_id in expected_candidates.items():
        case_result = build_case_result(load_case_bundle(case_by_id[case_id]))
        event_unit = case_result.event_units[0]
        selected = event_unit.selected_evidence_summary

        assert event_unit.selected_evidence_state == "found"
        assert selected["candidate_id"] == expected_candidate_id
        assert selected["upper_evidence_kind"] == "divstrip"
        assert selected["layer"] == 2
        assert selected["node_fallback_only"] is False
        assert float(selected["pair_middle_overlap_ratio"]) > 0.0
        _assert_selected_candidate_region_is_pair_local_container(event_unit)

def test_real_case_17943587_node_55353239_keeps_local_three_arm_and_selects_local_divstrip_evidence() -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353239"
    )

    assert event_unit.unit_envelope.branch_road_memberships == {
        "road_1": ("607962170",),
        "road_2": ("620950831",),
        "road_3": ("41727506",),
    }
    assert event_unit.selected_evidence_state == "found"
    assert event_unit.selected_evidence_summary["candidate_id"] == "node_55353239:divstrip:1:01"
    assert event_unit.selected_evidence_summary["selection_status"] == "selected"
    assert event_unit.selected_evidence_summary["node_fallback_only"] is False
    assert float(event_unit.selected_evidence_summary["reference_distance_to_origin_m"]) > 3.0
    assert event_unit.review_state == "STEP4_REVIEW"

    representative_node_geometry = event_unit.unit_context.representative_node.geometry
    assert event_unit.pair_local_region_geometry is not None
    assert event_unit.pair_local_structure_face_geometry is not None
    assert event_unit.pair_local_middle_geometry is not None
    assert event_unit.pair_local_region_geometry.buffer(1e-6).covers(representative_node_geometry)
    assert event_unit.pair_local_structure_face_geometry.buffer(1e-6).covers(representative_node_geometry)
    _assert_selected_candidate_region_is_pair_local_container(event_unit)

def test_real_case_857993_keeps_node_857993_local_and_stops_node_870089_at_direct_branches() -> None:
    if not (REAL_ANCHOR_2_ROOT / "857993").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '857993'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["857993"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))

    node_857993 = next(item for item in case_result.event_units if item.spec.event_unit_id == "node_857993")
    assert node_857993.unit_envelope.branch_road_memberships == {
        "road_1": ("619715536",),
        "road_2": ("12557730",),
        "road_3": ("1112045",),
    }

    node_870089 = next(item for item in case_result.event_units if item.spec.event_unit_id == "node_870089")
    memberships = node_870089.unit_envelope.branch_road_memberships
    left_branch_id = _find_branch_id_with_road(memberships, "617462076")
    right_branch_id = _find_branch_id_with_road(memberships, "509954401")
    axis_branch_id = _find_branch_id_with_road(memberships, "619715536")

    assert set(memberships[left_branch_id]) == {"617462076"}
    assert set(memberships[right_branch_id]) == {"509954401"}
    assert set(memberships[axis_branch_id]) == {"619715536"}
    assert "517458735" not in set(memberships[left_branch_id])
    assert "1124251" not in set(memberships[right_branch_id])
    assert set(node_870089.unit_envelope.event_branch_ids) == {left_branch_id, right_branch_id}

    assert node_857993.selected_evidence_state == "found"
    assert node_857993.selected_evidence_summary["candidate_id"] == "node_857993:divstrip:3:01"
    assert node_857993.selected_evidence_summary["layer"] == 2
    assert node_857993.selected_evidence_summary["selected_after_reselection"] is False
    _assert_selected_candidate_region_is_pair_local_container(node_857993)
    _assert_one_sided_offsets(node_857993.pair_local_summary["valid_scan_offsets_m"])
    expected_node_857993_pair_signature = _stable_boundary_pair_signature(
        node_857993.unit_envelope.branch_road_memberships,
        node_857993.unit_envelope.boundary_branch_ids,
    )
    assert node_857993.pair_local_summary["boundary_pair_signature"] == expected_node_857993_pair_signature
    assert node_857993.pair_local_summary["region_id"] == f"node_857993:{expected_node_857993_pair_signature}"

    assert node_870089.selected_evidence_state == "found"
    assert node_870089.selected_evidence_summary["candidate_id"] == "node_870089:divstrip:3:01"
    assert node_870089.selected_evidence_summary["layer"] == 2
    assert node_870089.selected_evidence_summary["node_fallback_only"] is False
    assert float(node_870089.selected_evidence_summary["reference_distance_to_origin_m"]) > 3.0
    assert node_870089.fact_reference_point is not None
    assert node_870089.selected_evidence_region_geometry is not None
    assert node_870089.selected_evidence_region_geometry.buffer(1e-6).covers(node_870089.fact_reference_point)
    assert float(
        node_870089.fact_reference_point.distance(node_870089.unit_context.representative_node.geometry)
    ) < float(node_870089.selected_evidence_summary["reference_distance_to_origin_m"])
    _assert_selected_candidate_region_is_pair_local_container(node_870089)
    assert node_870089.pair_local_middle_geometry is not None
    assert node_870089.pair_local_structure_face_geometry is not None
    assert set(node_870089.unit_envelope.event_branch_ids) == set(node_870089.unit_envelope.boundary_branch_ids)
    assert axis_branch_id not in set(node_870089.unit_envelope.event_branch_ids)
    assert node_870089.pair_local_summary["pair_scan_truncated_to_local"] is True
    _assert_one_sided_offsets(node_870089.pair_local_summary["valid_scan_offsets_m"])
    expected_node_870089_pair_signature = _stable_boundary_pair_signature(
        node_870089.unit_envelope.branch_road_memberships,
        node_870089.unit_envelope.boundary_branch_ids,
    )
    assert node_870089.pair_local_summary["boundary_pair_signature"] == expected_node_870089_pair_signature
    assert node_870089.pair_local_summary["region_id"] == f"node_870089:{expected_node_870089_pair_signature}"
    assert float(node_870089.selected_candidate_region_geometry.area) >= float(
        node_870089.pair_local_structure_face_geometry.area
    )

    assert node_857993.selected_evidence_summary["axis_signature"] == "619715536"
    assert node_870089.selected_evidence_summary["point_signature"] == "619715536:0.0"

def test_real_case_73462878_keeps_pair_space_on_event_branches_only() -> None:
    if not (REAL_ANCHOR_2_ROOT / "73462878").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '73462878'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["73462878"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    assert len(case_result.event_units) == 1
    event_unit = case_result.event_units[0]
    memberships = event_unit.unit_envelope.branch_road_memberships

    axis_branch_id = _find_branch_id_with_road(memberships, "516876825")
    left_branch_id = _find_branch_id_with_road(memberships, "527735857")
    right_branch_id = _find_branch_id_with_road(memberships, "617735601")

    assert set(event_unit.unit_envelope.event_branch_ids) == {left_branch_id, right_branch_id}
    assert set(event_unit.unit_envelope.boundary_branch_ids) == {left_branch_id, right_branch_id}
    assert axis_branch_id not in set(event_unit.unit_envelope.event_branch_ids)
    assert event_unit.selected_evidence_state == "found"
    assert event_unit.selected_evidence_summary["candidate_id"] == "event_unit_01:divstrip:0:01"
    assert event_unit.selected_evidence_summary["layer"] == 2
    _assert_selected_candidate_region_is_pair_local_container(event_unit)
    _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])

def test_real_case_17943587_pair_space_stays_on_boundary_pair_without_reverse_backtrace() -> None:
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_units = {item.spec.event_unit_id: item for item in case_result.event_units}

    for unit_id in ("node_17943587", "node_55353233", "node_55353248"):
        event_unit = event_units[unit_id]
        assert set(event_unit.unit_envelope.event_branch_ids) == set(event_unit.unit_envelope.boundary_branch_ids)
        _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])
        expected_pair_signature = _stable_boundary_pair_signature(
            event_unit.unit_envelope.branch_road_memberships,
            event_unit.unit_envelope.boundary_branch_ids,
        )
        assert event_unit.pair_local_summary["boundary_pair_signature"] == expected_pair_signature
        assert event_unit.pair_local_summary["region_id"] == f"{unit_id}:{expected_pair_signature}"
        _assert_selected_candidate_region_is_pair_local_container(event_unit)
        if unit_id == "node_55353248":
            assert event_unit.pair_local_summary["pair_scan_truncated_to_local"] is True
            assert max(float(item) for item in event_unit.pair_local_summary["valid_scan_offsets_m"]) >= 96.0

    sibling_unit = event_units["node_55353233"]
    sibling_branch_road_memberships = sibling_unit.unit_envelope.branch_road_memberships
    sibling_merge_branch = _find_branch_id_with_required_roads(
        sibling_branch_road_memberships,
        {"502953712", "41727506", "620950831"},
    )
    assert set(sibling_branch_road_memberships[sibling_merge_branch]) == {
        "502953712",
        "41727506",
        "620950831",
    }
    assert "605949403" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert "607962170" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert max(float(item) for item in sibling_unit.pair_local_summary["valid_scan_offsets_m"]) >= 96.0
