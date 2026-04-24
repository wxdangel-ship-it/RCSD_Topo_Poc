from __future__ import annotations

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403

def test_positive_rcsd_present_side_label_mismatch_does_not_drop_to_c() -> None:
    representative_node = _parsed_node("1001", 0.0, 0.0, mainnodeid="1001", has_evd="yes", kind_2=16, grade_2=1)
    selected_evidence_region_geometry = Point(6.0, 0.0).buffer(4.0)
    pair_local_region_geometry = Polygon([(-12, -12), (20, -12), (20, 12), (-12, 12), (-12, -12)])
    pair_local_middle_geometry = Polygon([(-2, -4), (18, -4), (18, 4), (-2, 4), (-2, -4)])

    scoped_roads = [
        _parsed_road("road_1", [(-10.0, 0.0), (0.0, 0.0)], snodeid="s_1", enodeid="1001"),
        _parsed_road("road_2", [(0.0, 0.0), (10.0, 8.0)], snodeid="1001", enodeid="s_2"),
    ]
    pair_local_rcsd_roads = [
        _parsed_road("rc_road_axis", [(0.0, 0.0), (6.0, 0.0)], snodeid="1001", enodeid="rc_1"),
        _parsed_road("rc_road_event", [(6.0, 0.0), (15.0, -8.0)], snodeid="rc_1", enodeid="rc_2"),
    ]
    pair_local_rcsd_nodes = [
        _parsed_node("rc_1", 6.0, 0.0, mainnodeid="1001"),
    ]

    decision = resolve_positive_rcsd_selection(
        event_unit_id="synthetic_label_mismatch",
        operational_kind_hint=16,
        representative_node=representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=Point(6.0, 0.0),
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        scoped_rcsd_roads=pair_local_rcsd_roads,
        scoped_rcsd_nodes=pair_local_rcsd_nodes,
        pair_local_scope_rcsd_roads=pair_local_rcsd_roads,
        pair_local_scope_rcsd_nodes=pair_local_rcsd_nodes,
        scoped_roads=scoped_roads,
        boundary_branch_ids=("road_1", "road_2"),
        preferred_axis_branch_id="road_1",
        scoped_input_branch_ids=("road_1",),
        scoped_output_branch_ids=("road_2",),
        branch_road_memberships={"road_1": ("road_1",), "road_2": ("road_2",)},
        axis_vector=(1.0, 0.0),
    )

    assert decision.pair_local_rcsd_empty is False
    assert decision.positive_rcsd_present is True
    assert decision.positive_rcsd_consistency_level in {"A", "B"}
    assert decision.positive_rcsd_consistency_level != "C"
    assert decision.required_rcsd_node == "rc_1"
    assert decision.axis_polarity_inverted is True

def test_aggregated_rcsd_unit_upgrades_multiple_partial_local_units() -> None:
    representative_node = _parsed_node("2002", 0.0, 0.0, mainnodeid="2002", has_evd="yes", kind_2=16, grade_2=1)
    selected_evidence_region_geometry = Point(7.0, 0.0).buffer(5.0)
    pair_local_region_geometry = Polygon([(-14, -16), (24, -16), (24, 16), (-14, 16), (-14, -16)])
    pair_local_middle_geometry = Polygon([(-2, -4), (20, -4), (20, 4), (-2, 4), (-2, -4)])

    scoped_roads = [
        _parsed_road("road_1", [(-10.0, 0.0), (0.0, 0.0)], snodeid="s_1", enodeid="2002"),
        _parsed_road("road_2", [(0.0, 0.0), (10.0, 8.0)], snodeid="2002", enodeid="s_2"),
        _parsed_road("road_3", [(0.0, 0.0), (10.0, -8.0)], snodeid="2002", enodeid="s_3"),
    ]
    pair_local_rcsd_roads = [
        _parsed_road("rc_axis", [(0.0, 0.0), (6.0, 0.0)], snodeid="2002", enodeid="rc_1"),
        _parsed_road("rc_mid", [(6.0, 0.0), (12.0, 0.0)], snodeid="rc_1", enodeid="rc_2"),
        _parsed_road("rc_right", [(6.0, 0.0), (12.0, 8.0)], snodeid="rc_1", enodeid="rc_3"),
        _parsed_road("rc_left", [(12.0, 0.0), (18.0, -8.0)], snodeid="rc_2", enodeid="rc_4"),
    ]
    pair_local_rcsd_nodes = [
        _parsed_node("rc_1", 6.0, 0.0, mainnodeid="2002"),
        _parsed_node("rc_2", 12.0, 0.0, mainnodeid="2002"),
    ]

    decision = resolve_positive_rcsd_selection(
        event_unit_id="synthetic_aggregated",
        operational_kind_hint=16,
        representative_node=representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=Point(7.0, 0.0),
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        scoped_rcsd_roads=pair_local_rcsd_roads,
        scoped_rcsd_nodes=pair_local_rcsd_nodes,
        pair_local_scope_rcsd_roads=pair_local_rcsd_roads,
        pair_local_scope_rcsd_nodes=pair_local_rcsd_nodes,
        scoped_roads=scoped_roads,
        boundary_branch_ids=("road_1", "road_2", "road_3"),
        preferred_axis_branch_id="road_1",
        scoped_input_branch_ids=("road_1",),
        scoped_output_branch_ids=("road_2", "road_3"),
        branch_road_memberships={
            "road_1": ("road_1",),
            "road_2": ("road_2",),
            "road_3": ("road_3",),
        },
        axis_vector=(1.0, 0.0),
    )

    assert decision.positive_rcsd_present is True
    assert decision.aggregated_rcsd_unit_id is not None
    assert decision.positive_rcsd_consistency_level == "A"
    assert set(decision.selected_rcsdroad_ids) >= {"rc_axis", "rc_mid", "rc_right"}
    aggregated_units = decision.positive_rcsd_audit["aggregated_rcsd_units"]
    selected_aggregated = next(
        item for item in aggregated_units if item["unit_id"] == decision.aggregated_rcsd_unit_id
    )
    assert set(selected_aggregated["road_ids"]) >= {"rc_axis", "rc_mid", "rc_right", "rc_left"}
    assert set(selected_aggregated["event_side_road_ids"]) >= {"rc_right", "rc_left"}
    assert decision.required_rcsd_node in {"rc_1", "rc_2"}
    if decision.first_hit_rcsdroad_ids:
        assert decision.first_hit_rcsd_road_geometry is not None
    assert decision.local_rcsd_unit_geometry is not None
    assert decision.positive_rcsd_road_geometry is not None
    assert decision.positive_rcsd_node_geometry is not None
    assert decision.positive_rcsd_geometry is not None
    assert decision.primary_main_rc_node_geometry is not None
    assert decision.required_rcsd_node_geometry is not None

def test_geometry_normalization_keeps_line_and_point_geometries() -> None:
    line = LineString([(0.0, 0.0), (1.0, 1.0)])
    point = Point(0.0, 0.0)

    normalized_line = _normalize_geometry(line)
    normalized_point = _normalize_geometry(point)
    union_line = _union_geometry([line])
    union_point = _union_geometry([point])

    assert normalized_line is not None and normalized_line.geom_type == "LineString"
    assert normalized_point is not None and normalized_point.geom_type == "Point"
    assert union_line is not None and union_line.geom_type == "LineString"
    assert union_point is not None and union_point.geom_type == "Point"

def test_positive_rcsd_present_structural_conflict_can_drop_to_c() -> None:
    representative_node = _parsed_node("3001", 0.0, 0.0, mainnodeid="3001", has_evd="yes", kind_2=16, grade_2=1)
    selected_evidence_region_geometry = Point(7.0, 0.0).buffer(4.0)
    pair_local_region_geometry = Polygon([(-12, -12), (18, -12), (18, 12), (-12, 12), (-12, -12)])
    pair_local_middle_geometry = Polygon([(-2, -4), (16, -4), (16, 4), (-2, 4), (-2, -4)])

    scoped_roads = [
        _parsed_road("road_1", [(-10.0, 0.0), (0.0, 0.0)], snodeid="s_1", enodeid="3001"),
        _parsed_road("road_2", [(0.0, 0.0), (10.0, 8.0)], snodeid="3001", enodeid="s_2"),
        _parsed_road("road_3", [(0.0, 0.0), (10.0, -8.0)], snodeid="3001", enodeid="s_3"),
    ]
    pair_local_rcsd_roads = [
        _parsed_road("rc_right", [(6.0, 0.0), (14.0, 6.0)], snodeid="rc_1", enodeid="rc_2"),
        _parsed_road("rc_left", [(6.0, 0.0), (14.0, -6.0)], snodeid="rc_1", enodeid="rc_3"),
    ]
    pair_local_rcsd_nodes = [
        _parsed_node("rc_1", 6.0, 0.0, mainnodeid="3001"),
    ]

    decision = resolve_positive_rcsd_selection(
        event_unit_id="synthetic_structural_conflict",
        operational_kind_hint=16,
        representative_node=representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=Point(6.0, 0.0),
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        scoped_rcsd_roads=pair_local_rcsd_roads,
        scoped_rcsd_nodes=pair_local_rcsd_nodes,
        pair_local_scope_rcsd_roads=pair_local_rcsd_roads,
        pair_local_scope_rcsd_nodes=pair_local_rcsd_nodes,
        scoped_roads=scoped_roads,
        boundary_branch_ids=("road_1", "road_2", "road_3"),
        preferred_axis_branch_id="road_1",
        scoped_input_branch_ids=("road_1",),
        scoped_output_branch_ids=("road_2", "road_3"),
        branch_road_memberships={
            "road_1": ("road_1",),
            "road_2": ("road_2",),
            "road_3": ("road_3",),
        },
        axis_vector=(1.0, 0.0),
    )

    assert decision.positive_rcsd_present is True
    assert decision.positive_rcsd_consistency_level == "C"
    assert decision.positive_rcsd_support_level == "no_support"
    assert decision.required_rcsd_node == "rc_1"

def test_required_rcsd_node_decouples_from_primary_main_rc_node() -> None:
    representative_node = _parsed_node("4001", 0.0, 0.0, mainnodeid="4001", has_evd="yes", kind_2=16, grade_2=1)
    selected_evidence_region_geometry = Point(8.0, 0.0).buffer(5.0)
    pair_local_region_geometry = Polygon([(-12, -14), (24, -14), (24, 14), (-12, 14), (-12, -14)])
    pair_local_middle_geometry = Polygon([(-2, -4), (20, -4), (20, 4), (-2, 4), (-2, -4)])

    scoped_roads = [
        _parsed_road("road_1", [(-10.0, 0.0), (0.0, 0.0)], snodeid="s_1", enodeid="4001"),
        _parsed_road("road_2", [(0.0, 0.0), (10.0, 8.0)], snodeid="4001", enodeid="s_2"),
        _parsed_road("road_3", [(0.0, 0.0), (10.0, -8.0)], snodeid="4001", enodeid="s_3"),
    ]
    pair_local_rcsd_roads = [
        _parsed_road("rc_axis_near", [(0.0, 0.0), (4.0, 0.0)], snodeid="4001", enodeid="rc_near"),
        _parsed_road("rc_axis_far", [(4.0, 0.0), (9.0, 0.0)], snodeid="rc_near", enodeid="rc_far"),
        _parsed_road("rc_event_left", [(9.0, 0.0), (15.0, -7.0)], snodeid="rc_far", enodeid="rc_l"),
        _parsed_road("rc_event_right", [(9.0, 0.0), (15.0, 7.0)], snodeid="rc_far", enodeid="rc_r"),
    ]
    pair_local_rcsd_nodes = [
        _parsed_node("rc_near", 4.0, 0.0, mainnodeid="4001"),
        _parsed_node("rc_far", 9.0, 0.0, mainnodeid="4001"),
    ]

    decision = resolve_positive_rcsd_selection(
        event_unit_id="synthetic_required_decoupled",
        operational_kind_hint=16,
        representative_node=representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=Point(8.0, 0.0),
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        scoped_rcsd_roads=pair_local_rcsd_roads,
        scoped_rcsd_nodes=pair_local_rcsd_nodes,
        pair_local_scope_rcsd_roads=pair_local_rcsd_roads,
        pair_local_scope_rcsd_nodes=pair_local_rcsd_nodes,
        scoped_roads=scoped_roads,
        boundary_branch_ids=("road_1", "road_2", "road_3"),
        preferred_axis_branch_id="road_1",
        scoped_input_branch_ids=("road_1",),
        scoped_output_branch_ids=("road_2", "road_3"),
        branch_road_memberships={
            "road_1": ("road_1",),
            "road_2": ("road_2",),
            "road_3": ("road_3",),
        },
        axis_vector=(1.0, 0.0),
    )

    assert decision.positive_rcsd_consistency_level == "A"
    assert decision.primary_main_rc_node_id == "rc_near"
    assert decision.required_rcsd_node == "rc_far"
    assert decision.required_rcsd_node != decision.primary_main_rc_node_id
    assert decision.required_rcsd_node_source == "aggregated_structural_required"

def test_road_only_local_rcsd_unit_keeps_required_none() -> None:
    representative_node = _parsed_node("5001", 0.0, 0.0, mainnodeid="5001", has_evd="yes", kind_2=16, grade_2=1)
    selected_evidence_region_geometry = Point(6.0, 0.0).buffer(4.0)
    pair_local_region_geometry = Polygon([(-12, -12), (18, -12), (18, 12), (-12, 12), (-12, -12)])
    pair_local_middle_geometry = Polygon([(-2, -4), (16, -4), (16, 4), (-2, 4), (-2, -4)])

    scoped_roads = [
        _parsed_road("road_1", [(-10.0, 0.0), (0.0, 0.0)], snodeid="s_1", enodeid="5001"),
        _parsed_road("road_2", [(0.0, 0.0), (10.0, 8.0)], snodeid="5001", enodeid="s_2"),
        _parsed_road("road_3", [(0.0, 0.0), (10.0, -8.0)], snodeid="5001", enodeid="s_3"),
    ]
    pair_local_rcsd_roads = [
        _parsed_road("rc_axis", [(0.0, 0.0), (6.0, 0.0)], snodeid="ep_1", enodeid="ep_2"),
        _parsed_road("rc_left", [(6.0, 0.0), (14.0, -6.0)], snodeid="ep_2", enodeid="ep_3"),
        _parsed_road("rc_right", [(6.0, 0.0), (14.0, 6.0)], snodeid="ep_2", enodeid="ep_4"),
    ]

    decision = resolve_positive_rcsd_selection(
        event_unit_id="synthetic_road_only",
        operational_kind_hint=16,
        representative_node=representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=Point(6.0, 0.0),
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        scoped_rcsd_roads=pair_local_rcsd_roads,
        scoped_rcsd_nodes=(),
        pair_local_scope_rcsd_roads=pair_local_rcsd_roads,
        pair_local_scope_rcsd_nodes=(),
        scoped_roads=scoped_roads,
        boundary_branch_ids=("road_1", "road_2", "road_3"),
        preferred_axis_branch_id="road_1",
        scoped_input_branch_ids=("road_1",),
        scoped_output_branch_ids=("road_2", "road_3"),
        branch_road_memberships={
            "road_1": ("road_1",),
            "road_2": ("road_2",),
            "road_3": ("road_3",),
        },
        axis_vector=(1.0, 0.0),
    )

    assert decision.local_rcsd_unit_kind == "road_only"
    assert decision.required_rcsd_node in {"", None}
    assert decision.required_rcsd_node_source in {"", None}
    assert decision.positive_rcsd_consistency_level in {"B", "C"}
