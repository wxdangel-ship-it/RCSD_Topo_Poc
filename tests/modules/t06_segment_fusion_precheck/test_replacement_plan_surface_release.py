from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import (
    _blocked_standard_member_absorbable_by_path_group,
    build_problem_registry_rows,
    build_replacement_plan_rows,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import T06Step3Artifacts
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_aware_plan_release as release_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_aware_plan_release import (
    _points_by_id,
    _block_postplan_anchor_rows_for_baseline,
    _postplan_anchor_added_fail_keys,
    _postplan_anchor_release_items,
    _release_allowed,
    _rollback_postplan_anchor_release_rows,
    _rollback_items_for_plan_rows,
    _rollback_plan_ids,
    _rollback_plan_ids_for_failed_segments,
    _rollback_visual_conflict_release_rows,
    _topology_fail_keys,
    _visual_conflict_non_replaced_plan_ids,
    _visual_conflict_release_plan_rows,
    _visual_conflict_rollback_plan_ids,
)


def _validation_runtime_state() -> SimpleNamespace:
    return SimpleNamespace(
        authoritative_transition_closure_rows=[],
        topology_connectivity_audit_rows=[],
        segment_relation_rows=[],
        frcsd_roads=[],
        swsd_segments=[],
        swsd_roads=[],
        swsd_nodes=[],
        step2_replaceable_rows=[],
        connectivity_supplement_road_ids=set(),
    )


def test_postplan_anchor_added_fail_keys_exclude_advance_right_layer() -> None:
    ordinary = ("segment_endpoint_connectivity", "s1", "n1", "r1", "endpoint_unattached")
    advance_right = (
        "advance_right_endpoint_connectivity",
        '["ar1"]',
        "",
        "",
        "advance_right_leaf_endpoint_unattached",
    )

    assert _postplan_anchor_added_fail_keys({ordinary, advance_right}) == {ordinary}


def test_topology_fail_keys_ignore_generated_advance_right_road_id(monkeypatch, tmp_path) -> None:
    audit_path = tmp_path / "t06_step3_topology_connectivity_audit.gpkg"
    audit_path.touch()
    monkeypatch.setattr(
        release_module,
        "read_features",
        lambda _path: [
            {
                "properties": {
                    "audit_status": "fail",
                    "audit_layer": "advance_right_endpoint_connectivity",
                    "audit_reason": "advance_right_leaf_endpoint_unattached",
                    "swsd_segment_ids": ["s1"],
                    "frcsd_road_id": "generated_road_1",
                    "topology_road_lineage_id": "original_advance_right",
                    "topology_endpoint_index": 0,
                }
            }
        ],
    )

    assert _topology_fail_keys(tmp_path) == {
        (
            "advance_right_endpoint_connectivity",
            '["s1"]',
            "",
            'independent_attachment:["advance_right_endpoint_connectivity","original_advance_right",0,"advance_right_leaf_endpoint_unattached"]',
            "advance_right_leaf_endpoint_unattached",
        )
    }


def test_postplan_anchor_release_builds_strict_baseline_and_topology_rollback() -> None:
    rows = [
        {
            "properties": {
                "replacement_plan_id": "standard:s1",
                "swsd_segment_id": "s1",
                "group_segment_ids": ["s1"],
                "plan_status": "ready",
                "execution_action": "replace",
                "source_reason": "postplan_anchor_gate_deferred_to_step3_topology",
                "upstream_owner": "T06_step3_topology_connectivity_audit",
                "postplan_anchor_gate_original_reason": "junction_alignment_between_replacement_plans_diverged",
                "postplan_anchor_gate_evidence": "blocked_junction_divergence_shared_rcsd_road",
                "risk_flags": ["postplan_anchor_gate_deferred_to_step3_topology"],
                "notes": "released",
            }
        }
    ]

    released = _postplan_anchor_release_items(rows)
    assert released == [
        {
            "plan_id": "standard:s1",
            "segment_id": "s1",
            "group_segment_ids": ["s1"],
            "original_reason": "junction_alignment_between_replacement_plans_diverged",
            "evidence": "blocked_junction_divergence_shared_rcsd_road",
            "independent_surface_release": False,
        }
    ]
    baseline = _block_postplan_anchor_rows_for_baseline(release_module._copy_plan_rows(rows), {"standard:s1"})
    assert baseline[0]["properties"]["plan_status"] == "blocked"
    assert baseline[0]["properties"]["source_reason"] == "junction_alignment_between_replacement_plans_diverged"

    rolled_back = _rollback_postplan_anchor_release_rows(release_module._copy_plan_rows(rows), {"standard:s1"})
    props = rolled_back[0]["properties"]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "postplan_anchor_gate_failed_topology_gate"
    assert "postplan_anchor_gate_failed_topology_gate" in props["risk_flags"]


def test_surface_aware_release_requires_passed_surface_closure() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}
    incident = {"n1": ["s_replace", "s_retained"], "n2": ["s_replace"]}
    ready_segments = {"s_replace"}

    allowed, triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed_surface_1v1", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert allowed
    assert triggers[0]["swsd_node_id"] == "n1"

    generic_allowed, generic_triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert generic_allowed
    assert generic_triggers[0]["surface_status"][1] == "auto_closed"

    blocked, blocked_triggers = _release_allowed(
        props,
        {"n1": ("fail", "blocked_by_patch_conflict", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert not blocked
    assert blocked_triggers[0]["ok"] is False


def test_surface_aware_release_does_not_release_visual_only_risk() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["visual_consistency_outside_manual_audit"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}

    allowed, triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed_surface_1v1", 25.0)},
        swsd_points,
        rcsd_points,
        {"n1": ["s_replace", "s_retained"], "n2": ["s_replace"]},
        {"s_replace"},
    )

    assert not allowed
    assert triggers == []


def test_surface_aware_release_accepts_original_pair_endpoint_without_surface_row() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "original_rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}

    allowed, triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        {"n1": ["s_replace"], "n2": ["s_replace"]},
        set(),
    )

    assert allowed
    assert triggers == [
        {
            "swsd_node_id": "n1",
            "rcsd_node_id": "r1",
            "distance_m": 25.0,
            "surface_status": ["pass", "auto_closed_selected_replacement_endpoint", 25.0],
            "ok": True,
        }
    ]


def test_surface_aware_release_uses_mainnodeid_fallback_when_exact_point_has_no_trigger() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "original_rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(5, 0), "r2": Point(5, 0)}
    swsd_fallback_points = {"n1": Point(-30, 0)}
    rcsd_fallback_points = {"r1": Point(5, 0)}

    allowed, triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        {"n1": ["s_replace"]},
        set(),
        swsd_fallback_points=swsd_fallback_points,
        rcsd_fallback_points=rcsd_fallback_points,
    )

    assert allowed
    assert triggers == [
        {
            "swsd_node_id": "n1",
            "rcsd_node_id": "r1",
            "distance_m": 35.0,
            "surface_status": ["pass", "auto_closed_selected_replacement_endpoint", 35.0],
            "ok": True,
            "point_source": "mainnodeid_fallback",
        }
    ]


def test_surface_aware_release_accepts_optional_junc_anchor_mapping_without_surface_row() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "optional_junc_nodes": ["j1"],
        "optional_junc_rcsd_nodes": ["rj1"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(10, 0), "j1": Point(4, 0)}
    rcsd_points = {"r1": Point(0, 0), "r2": Point(10, 0), "rj1": Point(30, 0)}
    incident = {"j1": ["s_replace", "s_retained"], "n1": ["s_replace"], "n2": ["s_replace"]}

    allowed, triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        incident,
        {"s_replace"},
        {"j1"},
    )

    assert allowed
    assert triggers == [
        {
            "swsd_node_id": "j1",
            "rcsd_node_id": "rj1",
            "distance_m": 26.0,
            "surface_status": ["pass", "auto_closed_step2_optional_junc_anchor", 26.0],
            "ok": True,
        }
    ]

    blocked, blocked_triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        incident,
        {"s_replace"},
        set(),
    )

    assert not blocked
    assert blocked_triggers[0]["ok"] is False


def test_surface_aware_point_index_uses_mainnodeid() -> None:
    points = _points_by_id(
        [
            {"properties": {"id": "sub1", "mainnodeid": "main1"}, "geometry": Point(1, 2)},
            {"properties": {"node_id": "node2"}, "geometry": Point(3, 4)},
        ]
    )

    assert points["sub1"].equals(Point(1, 2))
    assert points["main1"].equals(Point(1, 2))
    assert points["node2"].equals(Point(3, 4))


def test_surface_aware_point_index_prefers_exact_id_over_mainnodeid_fallback() -> None:
    points = _points_by_id(
        [
            {"properties": {"id": "exact1"}, "geometry": Point(0, 0)},
            {"properties": {"id": "sub1", "mainnodeid": "exact1"}, "geometry": Point(10, 0)},
            {"properties": {"id": "sub2", "mainnodeid": "main2"}, "geometry": Point(20, 0)},
        ]
    )

    assert points["exact1"].equals(Point(0, 0))
    assert points["sub1"].equals(Point(10, 0))
    assert points["sub2"].equals(Point(20, 0))
    assert points["main2"].equals(Point(20, 0))


def test_surface_aware_release_rolls_back_plans_that_add_topology_failures() -> None:
    added_fail_keys = {
        ("segment_internal_connectivity", "s_group_member", "", "", "segment_corridor_coverage_dropped_after_replacement"),
        ("segment_junction_connectivity", "", "n1", "", "junction_incident_segment_mapping_missing"),
    }
    released = [
        {"plan_id": "standard:s_ok", "segment_id": "s_ok", "group_segment_ids": []},
        {"plan_id": "standard:s_direct", "segment_id": "s_direct", "group_segment_ids": []},
        {"plan_id": "group_path_corridor:s_group", "segment_id": "s_group", "group_segment_ids": ["s_group", "s_group_member"]},
    ]
    incident = {"n1": ["s_direct"], "n2": ["s_direct"], "n3": ["s_ok"]}

    assert _rollback_plan_ids_for_failed_segments(added_fail_keys, released, incident) == {
        "standard:s_direct",
        "group_path_corridor:s_group",
    }


def test_surface_aware_release_rollback_prefers_explicit_junction_segments() -> None:
    added_fail_keys = {
        (
            "segment_junction_connectivity",
            '["s_direct"]',
            "n1",
            "",
            "junction_incident_segment_mapping_missing",
        )
    }
    released = [
        {"plan_id": "standard:s_direct", "segment_id": "s_direct", "group_segment_ids": []},
        {"plan_id": "standard:s_neighbor", "segment_id": "s_neighbor", "group_segment_ids": []},
    ]
    incident = {"n1": ["s_direct", "s_neighbor"]}

    assert _rollback_plan_ids_for_failed_segments(added_fail_keys, released, incident) == {"standard:s_direct"}


def test_surface_aware_release_rollback_does_not_block_unreleased_candidate_plan_carriers(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.gpkg"
    write_vector(
        segment_path,
        [_feature({"id": "s_group", "pair_nodes": ["n1", "n2"], "junc_nodes": []}, LineString([(0, 0), (1, 0)]))],
        crs_text="EPSG:3857",
    )
    added_fail_keys = {
        (
            "segment_junction_connectivity",
            '["s_group", "s_retained"]',
            "n1",
            "",
            "junction_incident_segment_mapping_missing",
        )
    }
    released = [{"plan_id": "standard:s_release", "segment_id": "s_release", "group_segment_ids": []}]
    plan_rows = [
        {
            "properties": {
                "replacement_plan_id": "group_path_corridor:s_group",
                "swsd_segment_id": "s_group",
                "group_segment_ids": ["s_group", "s_peer"],
            }
        },
        {
            "properties": {
                "replacement_plan_id": "standard:s_unrelated",
                "swsd_segment_id": "s_unrelated",
                "group_segment_ids": [],
            }
        },
    ]

    assert _rollback_items_for_plan_rows(plan_rows)[0]["plan_id"] == "group_path_corridor:s_group"
    assert _rollback_plan_ids(added_fail_keys, released, plan_rows, segment_path) == set()


def test_surface_aware_release_rollback_keeps_t05_semantic_release_as_risk(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.gpkg"
    write_vector(
        segment_path,
        [_feature({"id": "s_release", "pair_nodes": ["n1", "n2"], "junc_nodes": []}, LineString([(0, 0), (1, 0)]))],
        crs_text="EPSG:3857",
    )
    added_fail_keys = {
        (
            "segment_junction_connectivity",
            "[\"s_release\"]",
            "",
            "",
            "segment_junction_connectivity_missing",
        )
    }
    released = [
        {
            "plan_id": "standard:s_release",
            "segment_id": "s_release",
            "group_segment_ids": ["s_release"],
            "triggers": [
                {"surface_status": ["pass", "auto_closed_t05_semantic_junction_relation", 25.964], "ok": True}
            ],
        }
    ]

    assert _rollback_plan_ids(added_fail_keys, released, [], segment_path) == set()


def test_surface_aware_release_does_not_promote_path_corridor_group_scope() -> None:
    allow, triggers = _release_allowed(
        {
            "source_reason": "junction_alignment_to_retained_swsd_exceeds_topology_gate",
            "execution_scope": "path_corridor_group",
            "swsd_pair_nodes": ["A"],
            "rcsd_pair_nodes": ["R"],
        },
        surface_status={},
        swsd_points={"A": Point(0, 0)},
        rcsd_points={"R": Point(50, 0)},
        incident={"A": ["A_B"]},
        ready_segments=set(),
        t05_relation_by_target={"A": "R"},
        rcsd_semantic_ids_by_node={"R": {"R"}},
    )

    assert allow is False
    assert triggers == []


def test_visual_conflict_release_keeps_source_reason_and_adds_release_risk() -> None:
    rows = [
        _feature(
            {
                "replacement_plan_id": "standard:s_visual",
                "swsd_segment_id": "s_visual",
                "plan_status": "blocked",
                "execution_action": "hold",
                "source_reason": "visual_consistency_road_conflict_with_primary_replacement_plan",
                "risk_flags": ["manual_review_required"],
            }
        ),
        _feature(
            {
                "replacement_plan_id": "standard:s_other",
                "swsd_segment_id": "s_other",
                "plan_status": "blocked",
                "execution_action": "hold",
                "source_reason": "junction_alignment_to_retained_swsd_exceeds_topology_gate",
            }
        ),
    ]

    released_rows, released = _visual_conflict_release_plan_rows(rows)

    visual_props = released_rows[0]["properties"]
    other_props = released_rows[1]["properties"]
    assert visual_props["plan_status"] == "ready"
    assert visual_props["execution_action"] == "replace"
    assert visual_props["source_reason"] == "visual_consistency_road_conflict_with_primary_replacement_plan"
    assert "visual_conflict_controlled_release" in visual_props["risk_flags"]
    assert other_props["plan_status"] == "blocked"
    assert released == [
        {
            "plan_id": "standard:s_visual",
            "segment_id": "s_visual",
            "scope": None,
            "group_segment_ids": [],
            "release_reason": "visual_consistency_road_conflict_with_primary_replacement_plan",
        }
    ]


def test_visual_conflict_rollback_only_blocks_visual_release_plan(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.gpkg"
    write_vector(
        segment_path,
        [_feature({"id": "s_visual", "pair_nodes": ["n1", "n2"], "junc_nodes": []}, LineString([(0, 0), (1, 0)]))],
        crs_text="EPSG:3857",
    )
    added_fail_keys = {
        (
            "segment_junction_connectivity",
            '["s_visual", "s_primary"]',
            "n1",
            "",
            "junction_incident_segment_mapped_points_diverged",
        )
    }
    released = [{"plan_id": "standard:s_visual", "segment_id": "s_visual", "group_segment_ids": []}]

    rollback_ids = _visual_conflict_rollback_plan_ids(added_fail_keys, released, segment_path)

    assert rollback_ids == {"standard:s_visual"}

    rows = [
        _feature(
            {
                "replacement_plan_id": "standard:s_visual",
                "plan_status": "ready",
                "execution_action": "replace",
                "source_reason": "visual_consistency_road_conflict_with_primary_replacement_plan",
                "risk_flags": ["visual_conflict_controlled_release"],
            }
        ),
        _feature(
            {
                "replacement_plan_id": "standard:s_primary",
                "plan_status": "ready",
                "execution_action": "replace",
                "source_reason": "passed",
                "risk_flags": [],
            }
        ),
    ]

    rolled_back = _rollback_visual_conflict_release_rows(rows, rollback_ids)

    assert rolled_back[0]["properties"]["plan_status"] == "blocked"
    assert rolled_back[0]["properties"]["execution_action"] == "hold"
    assert "visual_conflict_release_failed_topology_gate" in rolled_back[0]["properties"]["risk_flags"]
    assert rolled_back[1]["properties"]["plan_status"] == "ready"


def test_visual_conflict_release_does_not_rollback_for_advance_right_leaf_audit(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.gpkg"
    write_vector(
        segment_path,
        [_feature({"id": "s_visual", "pair_nodes": ["n1", "n2"], "junc_nodes": []}, LineString([(0, 0), (1, 0)]))],
        crs_text="EPSG:3857",
    )
    added_fail_keys = {
        (
            "advance_right_endpoint_connectivity",
            '["s_visual", "s_peer"]',
            "",
            "r_leaf",
            "advance_right_leaf_endpoint_unattached",
        )
    }
    released = [{"plan_id": "standard:s_visual", "segment_id": "s_visual", "group_segment_ids": ["s_visual"]}]

    assert _visual_conflict_rollback_plan_ids(added_fail_keys, released, segment_path) == set()


def test_visual_conflict_release_rolls_back_for_segment_connectivity_fail(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.gpkg"
    write_vector(
        segment_path,
        [_feature({"id": "s_visual", "pair_nodes": ["n1", "n2"], "junc_nodes": []}, LineString([(0, 0), (1, 0)]))],
        crs_text="EPSG:3857",
    )
    added_fail_keys = {
        (
            "segment_road_connectivity",
            "s_visual",
            "",
            "",
            "segment_road_endpoints_not_connected",
        )
    }
    released = [{"plan_id": "standard:s_visual", "segment_id": "s_visual", "group_segment_ids": ["s_visual"]}]

    assert _visual_conflict_rollback_plan_ids(added_fail_keys, released, segment_path) == {"standard:s_visual"}


def test_visual_conflict_non_replaced_release_is_rolled_back(tmp_path: Path) -> None:
    step_root = tmp_path / "step3"
    step_root.mkdir()
    write_vector(
        step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [
            _feature({"swsd_segment_id": "s_replaced", "relation_status": "replaced"}, LineString([(0, 0), (1, 0)])),
            _feature({"swsd_segment_id": "s_mixed", "relation_status": "replaced+retained_swsd"}, LineString([(0, 0), (1, 1)])),
            _feature({"swsd_segment_id": "s_retained", "relation_status": "retained_swsd"}, LineString([(0, 1), (1, 1)])),
        ],
        crs_text="EPSG:3857",
    )
    released = [
        {"plan_id": "standard:s_replaced", "segment_id": "s_replaced", "group_segment_ids": []},
        {"plan_id": "standard:s_mixed", "segment_id": "s_mixed", "group_segment_ids": []},
        {"plan_id": "standard:s_retained", "segment_id": "s_retained", "group_segment_ids": []},
    ]

    assert _visual_conflict_non_replaced_plan_ids(step_root, released) == {
        "standard:s_mixed",
        "standard:s_retained",
    }


def test_surface_aware_visual_release_reuses_candidate_when_no_rollback(monkeypatch, tmp_path) -> None:
    step_root = tmp_path / "run" / "step3_segment_replacement"
    step_root.mkdir(parents=True)
    (tmp_path / "t06_segment_replacement_plan.gpkg").write_text("plan", encoding="utf-8")
    original_plan = tmp_path / "replacement_plan.gpkg"
    original_plan.write_text("plan", encoding="utf-8")
    summary_path = step_root / "t06_step3_summary.json"
    summary_path.write_text(
        '{"input_paths": {"step2_replacement_plan_path": "' + str(original_plan).replace("\\", "\\\\") + '"}}',
        encoding="utf-8",
    )
    calls = []
    runtime_state = _validation_runtime_state()
    topology_gate_audit_rows = []

    def fake_run_step3(*, write_feature_json_outputs=True, **kwargs):
        calls.append((write_feature_json_outputs, kwargs.get("step2_replacement_plan_path")))
        return T06Step3Artifacts(
            run_id="run",
            run_root=tmp_path / "run",
            step_root=step_root,
            frcsd_road_gpkg_path=step_root / "road.gpkg",
            frcsd_node_gpkg_path=step_root / "node.gpkg",
            replacement_units_gpkg_path=step_root / "units.gpkg",
            swsd_frcsd_segment_relation_gpkg_path=step_root / "relation.gpkg",
            junction_rebuild_audit_gpkg_path=step_root / "junction.gpkg",
            summary_path=summary_path,
        )

    def fake_write_plan_json(step_root_arg, rows, suffix):
        path = step_root_arg / f"plan_{suffix}.json"
        path.write_text("[]", encoding="utf-8")
        return path

    monkeypatch.setattr(release_module, "_run_step3", fake_run_step3)
    monkeypatch.setattr(
        release_module,
        "_run_surface",
        lambda *args, **kwargs: {"_step3_surface_runtime_state": runtime_state},
    )
    monkeypatch.setattr(release_module, "promote_validation_step3_outputs", lambda artifacts, _root: artifacts)
    monkeypatch.setattr(release_module, "publish_deferred_validation_outputs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(release_module, "refresh_rcsd_road_ownership_after_surface", lambda **_kwargs: None)
    monkeypatch.setattr(release_module, "refresh_segment_construction_audit_after_surface", lambda **_kwargs: None)
    monkeypatch.setattr(release_module, "_topology_fail_keys", lambda *args, **kwargs: set())
    monkeypatch.setattr(release_module, "_external_baseline_step3_root", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "_preflight_replacement_plan_rows", lambda *args, **kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(release_module, "read_replacement_plan_rows", lambda *args, **kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(release_module, "read_features", lambda *_args, **_kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(
        release_module,
        "_preplanned_surface_release_plan_rows",
        lambda *args, **kwargs: ([_feature({"replacement_plan_id": "standard:s1"})], [{"plan_id": "standard:s1"}]),
    )
    monkeypatch.setattr(
        release_module,
        "_visual_conflict_release_plan_rows",
        lambda rows: (rows, [{"plan_id": "standard:s1", "segment_id": "s1", "group_segment_ids": []}]),
    )
    monkeypatch.setattr(release_module, "_write_plan_json", fake_write_plan_json)
    monkeypatch.setattr(release_module, "_rollback_plan_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(release_module, "_visual_conflict_non_replaced_plan_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(release_module, "_visual_conflict_rollback_plan_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(
        release_module,
        "final_topology_gate_decision",
        lambda _root, _rows, audit_rows=None: (
            topology_gate_audit_rows.append(audit_rows)
            or {"rollback_plan_ids": [], "repairable_failures": [], "repairable_failure_count": 0}
        ),
    )

    release_module.run_surface_aware_step3_segment_replacement(
        step2_replaceable_path=tmp_path / "replaceable.gpkg",
        step2_special_junction_group_audit_path=None,
        step2_group_replacement_audit_path=None,
        swsd_segment_path=tmp_path / "segment.gpkg",
        swsd_roads_path=tmp_path / "roads.gpkg",
        swsd_nodes_path=tmp_path / "nodes.gpkg",
        rcsdroad_path=tmp_path / "rcsdroad.gpkg",
        rcsdnode_path=tmp_path / "rcsdnode.gpkg",
        out_root=tmp_path,
        run_id="run",
        surface_inputs={"t05_surface_path": tmp_path / "surface.gpkg"},
        surface_topology_closure=True,
        progress=False,
    )

    assert len(calls) == 1
    assert calls[0][1].name == "plan_candidate.json"
    assert [call[0] for call in calls] == [False]
    assert topology_gate_audit_rows[-1] is runtime_state.topology_connectivity_audit_rows


def test_surface_aware_visual_release_skips_surface_safe_intermediate_rerun(monkeypatch, tmp_path) -> None:
    step_root = tmp_path / "run" / "step3_segment_replacement"
    step_root.mkdir(parents=True)
    (tmp_path / "t06_segment_replacement_plan.gpkg").write_text("plan", encoding="utf-8")
    original_plan = tmp_path / "replacement_plan.gpkg"
    original_plan.write_text("plan", encoding="utf-8")
    summary_path = step_root / "t06_step3_summary.json"
    summary_path.write_text(
        '{"input_paths": {"step2_replacement_plan_path": "' + str(original_plan).replace("\\", "\\\\") + '"}}',
        encoding="utf-8",
    )
    calls = []
    current_plan = {"name": None}

    def fake_run_step3(*, write_feature_json_outputs=True, **kwargs):
        plan = kwargs.get("step2_replacement_plan_path")
        current_plan["name"] = plan.name if plan else None
        calls.append((write_feature_json_outputs, current_plan["name"]))
        return T06Step3Artifacts(
            run_id="run",
            run_root=tmp_path / "run",
            step_root=step_root,
            frcsd_road_gpkg_path=step_root / "road.gpkg",
            frcsd_node_gpkg_path=step_root / "node.gpkg",
            replacement_units_gpkg_path=step_root / "units.gpkg",
            swsd_frcsd_segment_relation_gpkg_path=step_root / "relation.gpkg",
            junction_rebuild_audit_gpkg_path=step_root / "junction.gpkg",
            summary_path=summary_path,
        )

    baseline_fail = ("segment_junction_connectivity", "s_base", "", "", "base_fail")
    surface_fail = ("segment_junction_connectivity", "s_surface", "", "", "surface_fail")
    visual_fail = ("segment_junction_connectivity", "s_visual", "", "", "visual_fail")

    def fake_topology_fail_keys(_step_root, _runtime_state=None):
        if current_plan["name"] == "t06_step3_surface_aware_replacement_plan_candidate.json":
            return {baseline_fail, surface_fail}
        if current_plan["name"] == "t06_step3_surface_aware_replacement_plan_visual_candidate.json":
            return {baseline_fail, visual_fail}
        return {baseline_fail}

    monkeypatch.setattr(release_module, "_run_step3", fake_run_step3)
    monkeypatch.setattr(
        release_module,
        "_run_surface",
        lambda *args, **kwargs: {"_step3_surface_runtime_state": _validation_runtime_state()},
    )
    monkeypatch.setattr(release_module, "promote_validation_step3_outputs", lambda artifacts, _root: artifacts)
    monkeypatch.setattr(release_module, "publish_deferred_validation_outputs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(release_module, "refresh_rcsd_road_ownership_after_surface", lambda **_kwargs: None)
    monkeypatch.setattr(release_module, "refresh_segment_construction_audit_after_surface", lambda **_kwargs: None)
    monkeypatch.setattr(release_module, "_topology_fail_keys", fake_topology_fail_keys)
    monkeypatch.setattr(release_module, "_external_baseline_step3_root", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "_preflight_replacement_plan_rows", lambda *args, **kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(release_module, "read_replacement_plan_rows", lambda *args, **kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(release_module, "read_features", lambda *_args, **_kwargs: [_feature({"replacement_plan_id": "standard:s1"})])
    monkeypatch.setattr(release_module, "_incident_segments_by_node", lambda _rows: {})
    monkeypatch.setattr(
        release_module,
        "_preplanned_surface_release_plan_rows",
        lambda *args, **kwargs: (
            [_feature({"replacement_plan_id": "standard:s_surface"})],
            [{"plan_id": "standard:s_surface", "segment_id": "s_surface", "group_segment_ids": []}],
        ),
    )
    monkeypatch.setattr(release_module, "_rollback_plan_ids", lambda *args, **kwargs: {"standard:s_surface"})
    monkeypatch.setattr(
        release_module,
        "_visual_conflict_release_plan_rows",
        lambda rows: (
            [*rows, _feature({"replacement_plan_id": "standard:s_visual", "swsd_uncovered_by_rcsd_ratio": 1.0})],
            [{"plan_id": "standard:s_visual", "segment_id": "s_visual", "group_segment_ids": []}],
        ),
    )
    monkeypatch.setattr(release_module, "_visual_conflict_non_replaced_plan_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(release_module, "_visual_conflict_rollback_plan_ids", lambda *args, **kwargs: {"standard:s_visual"})

    release_module.run_surface_aware_step3_segment_replacement(
        step2_replaceable_path=tmp_path / "replaceable.gpkg",
        step2_special_junction_group_audit_path=None,
        step2_group_replacement_audit_path=None,
        swsd_segment_path=tmp_path / "segment.gpkg",
        swsd_roads_path=tmp_path / "roads.gpkg",
        swsd_nodes_path=tmp_path / "nodes.gpkg",
        rcsdroad_path=tmp_path / "rcsdroad.gpkg",
        rcsdnode_path=tmp_path / "rcsdnode.gpkg",
        out_root=tmp_path,
        run_id="run",
        surface_inputs={"t05_surface_path": tmp_path / "surface.gpkg"},
        surface_topology_closure=True,
        progress=False,
    )

    assert [call[1] for call in calls] == [
        "t06_step3_surface_aware_replacement_plan_candidate.json",
        "t06_step3_surface_aware_replacement_plan_topology_safe.json",
    ]
    assert [call[0] for call in calls] == [False, False]
    assert "t06_step3_surface_aware_replacement_plan_visual_candidate.json" not in [call[1] for call in calls]
    assert (step_root / "t06_step3_surface_aware_replacement_plan_topology_safe.json").is_file()


def test_visual_manual_release_allows_small_pair_attachment_gap_to_retained_incident_segment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 25.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.2,
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_near", "r2"],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": ["r_near", "r2"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_error_swsd_nodes": ["n1", "n2"],
                    "pair_anchor_error_original_rcsd_nodes": [""],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r2", "r1"],
                }
            )
        ],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s_replace", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s_retained", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("r_near", 22, 0), _node("r2", 10, 0)],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert "visual_manual_release_pair_attachment_gap_accepted" in props["risk_flags"]
    assert "junction_alignment_to_retained_swsd_exceeds_topology_gate" not in props["risk_flags"]


def test_pair_anchor_repair_attachment_gap_is_risk_not_blocker() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "original_rcsd_pair_nodes": ["r1"],
                    "pair_anchor_error_swsd_nodes": ["n1", "n2"],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r2", "r1"],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": ["r1", "r2"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_error_swsd_nodes": ["n1", "n2"],
                    "pair_anchor_error_original_rcsd_nodes": ["r1", ""],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r2", "r1"],
                }
            )
        ],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s_replace", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s_retained", "pair_nodes": ["n2", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 100, 0), _node("n3", 100, 10)],
        rcsd_nodes=[_node("r1", 0, 0), _node("r2", 180, 0)],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert "pair_anchor_repair_attachment_gap_accepted" in props["risk_flags"]
    assert "junction_alignment_to_retained_swsd_exceeds_topology_gate" not in props["risk_flags"]


def test_replacement_plan_blocks_replacement_plans_mapping_same_junction_to_diverged_rcsd_nodes() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": ["r3", "r4"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("r1", 0, 0), _node("r2", 10, 0), _node("r3", 10, 0), _node("r4", 0, 10)],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "blocked"
    assert by_segment["s2"]["plan_status"] == "blocked"
    assert by_segment["s1"]["source_reason"] == "junction_alignment_between_replacement_plans_diverged"
    assert by_segment["s2"]["source_reason"] == "junction_alignment_between_replacement_plans_diverged"


def test_replacement_plan_does_not_block_valid_peer_for_pair_anchor_mismatch_candidate() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "valid_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_good", "r2"],
                    "rcsd_road_ids": ["rr_valid"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "original_rcsd_pair_nodes": ["r_good", "r3"],
                    "rcsd_pair_nodes": ["r_bad", "r3"],
                    "rcsd_road_ids": ["rr_mismatch"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_error_swsd_nodes": ["n1"],
                    "pair_anchor_error_original_rcsd_nodes": ["r_good"],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r_bad"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "valid_segment", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "mismatch_segment", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[
            _node("r_good", 0, 0),
            _node("r_bad", 20, 0),
            _node("r2", 10, 0),
            _node("r3", 0, 10),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["valid_segment"]["plan_status"] == "ready"
    assert by_segment["valid_segment"]["execution_action"] == "replace"
    assert "junction_alignment_peer_pair_anchor_mismatch_ignored" in by_segment["valid_segment"]["risk_flags"]
    assert by_segment["mismatch_segment"]["plan_status"] == "blocked"
    assert by_segment["mismatch_segment"]["execution_action"] == "hold"
    assert by_segment["mismatch_segment"]["source_reason"] == "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative"
    assert "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative" in by_segment["mismatch_segment"]["risk_flags"]


def test_replacement_plan_postplan_releases_nonmanual_high_confidence_pair_anchor_candidate() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "valid_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_good", "r2"],
                    "rcsd_road_ids": ["rr_valid"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "original_rcsd_pair_nodes": ["r_good", "r3"],
                    "rcsd_pair_nodes": ["r_bad", "r3"],
                    "rcsd_road_ids": ["rr_mismatch"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_error_swsd_nodes": ["n1"],
                    "pair_anchor_error_original_rcsd_nodes": ["r_good"],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r_bad"],
                    "repair_recommendation": "high_confidence_pair_anchor_candidate",
                    "manual_review_required": False,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "valid_segment", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "mismatch_segment", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[
            _node("r_good", 0, 0),
            _node("r_bad", 20, 0),
            _node("r2", 10, 0),
            _node("r3", 0, 10),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    props = by_segment["mismatch_segment"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["postplan_anchor_gate_original_reason"] == "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative"
    assert props["postplan_anchor_gate_evidence"] == "failure_business_audit_high_confidence_pair_anchor_repair"


def test_replacement_plan_postplan_releases_shared_road_divergence_peers() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr_shared"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "swsd_junc_nodes": ["j1", "j2"],
                    "rcsd_pair_nodes": ["r3", "r4"],
                    "rcsd_junc_nodes": ["rj1", "rj2"],
                    "optional_junc_nodes": ["j1", "j2"],
                    "optional_junc_rcsd_nodes": ["rj1"],
                    "rcsd_road_ids": ["rr_shared"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[
            _node("n1", 0, 0),
            _node("n2", 10, 0),
            _node("n3", 0, 10),
            _node("j1", 5, 0),
            _node("j2", 5, 10),
        ],
        rcsd_nodes=[
            _node("r1", 0, 0),
            _node("r2", 10, 0),
            _node("r3", 10, 0),
            _node("r4", 0, 10),
            _node("rj1", 5, 0),
            _node("rj2", 5, 10),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "ready"
    assert by_segment["s2"]["plan_status"] == "ready"
    assert by_segment["s1"]["postplan_anchor_gate_peer_segment_ids"] == ["s2"]
    assert by_segment["s2"]["postplan_anchor_gate_peer_segment_ids"] == ["s1"]
    assert by_segment["s1"]["postplan_anchor_gate_evidence"] == "blocked_junction_divergence_shared_rcsd_road"


def test_replacement_plan_postplan_keeps_incomplete_pair_anchor_blocked() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_incomplete",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_far"],
                    "rcsd_road_ids": ["rr1"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s_incomplete", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s_retained", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("r_far", 30, 0)],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "blocked"
    assert props["source_reason"] == "junction_alignment_to_retained_swsd_exceeds_topology_gate"
    assert "postplan_anchor_gate_evidence" not in props


def test_replacement_plan_uses_optional_junction_nodes_after_dropped_junction() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "cross_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n_shared", "n2"],
                    "rcsd_pair_nodes": ["r_shared", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "main_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["m1", "m2"],
                    "swsd_junc_nodes": ["dropped", "n_shared", "n_other"],
                    "optional_junc_nodes": ["n_shared", "n_other"],
                    "dropped_junc_nodes": ["dropped"],
                    "rcsd_pair_nodes": ["rm1", "rm2"],
                    "rcsd_junc_nodes": ["r_shared", "r_other"],
                    "optional_junc_rcsd_nodes": ["r_shared", "r_other"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "cross_segment", "pair_nodes": ["n_shared", "n2"]}),
            _feature({"id": "main_segment", "pair_nodes": ["m1", "m2"], "junc_nodes": ["dropped", "n_shared", "n_other"]}),
        ],
        swsd_nodes=[
            _node("n_shared", 0, 0),
            _node("n2", 0, 10),
            _node("m1", 20, 0),
            _node("m2", 20, 10),
            _node("dropped", 50, 0),
            _node("n_other", 100, 0),
        ],
        rcsd_nodes=[
            _node("r_shared", 0, 0),
            _node("r2", 0, 10),
            _node("rm1", 20, 0),
            _node("rm2", 20, 10),
            _node("r_other", 100, 0),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["cross_segment"]["plan_status"] == "ready"
    assert by_segment["main_segment"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["cross_segment"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["main_segment"]["risk_flags"]


def test_replacement_plan_keeps_diverged_junction_ready_when_pair_anchor_bridge_connects_nodes() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": [30, 40],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_bridge_road_ids": ["rr_bridge"],
                    "pair_anchor_bridge_length_m": 12.0,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[
            _road("rr1", 10, 20),
            _road("rr2", 30, 40),
            _road("rr_bridge", 10, 30),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30", "40"})),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("10", 0, 0), _node("20", 10, 0), _node("30", 10, 0), _node("40", 0, 10)],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "ready"
    assert by_segment["s2"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge" in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge" in by_segment["s2"]["risk_flags"]


def test_problem_registry_marks_plan_covered_and_upstream_required_segments() -> None:
    plan_rows = [
        _feature(
            {
                "plan_status": "ready",
                "execution_action": "replace",
                "execution_scope": "path_corridor_group",
                "source_artifact": "t06_segment_replacement_plan",
                "group_segment_ids": ["s1", "s2"],
            }
        )
    ]
    rows = build_problem_registry_rows(
        rejected_rows=[
            _feature({"swsd_segment_id": "s3", "reject_reason": "missing_pair_relation", "failed_pair_nodes": [3, 4]})
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_directed_path_missing",
                    "failure_business_category": "directionality_mismatch_fixable",
                    "upstream_issue_owner": "T03/T04/T05_or_T06_group_replacement",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s4",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_pair_nodes_not_distinct",
                    "failure_business_category": "multi_anchor_ambiguous",
                    "upstream_issue_owner": "T05",
                    "manual_review_required": True,
                    "swsd_pair_nodes": [4, 5],
                    "rcsd_pair_nodes": [40, 40],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s5",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_not_bidirectional_for_swsd_dual",
                    "root_cause_category": "full_rcsd_graph_one_direction_only",
                    "failure_business_category": "directionality_mismatch_fixable",
                    "upstream_issue_owner": "T03/T04/T05_or_T06_group_replacement",
                    "manual_review_required": True,
                    "swsd_pair_nodes": [5, 6],
                    "rcsd_pair_nodes": [50, 60],
                    "candidate_rcsd_pair_node_sets": [[50, 60], [51, 61]],
                    "pair_anchor_error_swsd_nodes": [6],
                    "pair_anchor_error_original_rcsd_nodes": [60],
                    "pair_anchor_error_candidate_rcsd_nodes": [61],
                    "pair_anchor_endpoint_cluster_nodes": [[50], [61]],
                    "pair_anchor_bridge_road_ids": ["rr_bridge"],
                    "pair_anchor_bridge_length_m": 6.5,
                    "pair_anchor_diagnostic_source": "buffer_only_candidate_pair",
                    "pair_anchor_diagnostic_reason": "candidate_anchor_mismatch",
                }
            )
        ],
        replacement_plan_rows=plan_rows,
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s2"]["problem_status"] == "covered_by_replacement_plan"
    assert by_segment["s2"]["recommended_module"] == "T03/T04/T05"
    assert by_segment["s3"]["problem_status"] == "requires_upstream_iteration"
    assert by_segment["s3"]["recommended_module"] == "T03/T04/T05"
    assert by_segment["s4"]["problem_status"] == "accepted_non_replaceable"
    assert by_segment["s4"]["recommended_module"] == "T06"
    assert by_segment["s4"]["feedback_action"] == "record_as_t06_non_replaceable_no_upstream_rerun"
    assert by_segment["s4"]["replan_trigger"] == "no_current_rerun_required"
    assert by_segment["s4"]["manual_review_required"] is False
    assert by_segment["s5"]["problem_status"] == "requires_upstream_side_group_or_rcsd_directionality_review"
    assert by_segment["s5"]["upstream_issue_owner"] == "T03/T04/T05_or_RCSD_directionality_review"
    assert by_segment["s5"]["recommended_module"] == "T03/T04/T05_or_RCSD_source_review"
    assert by_segment["s5"]["feedback_action"] == "evaluate_T03_T04_T05_side_grouping_before_rcsd_directionality_data_review"
    assert by_segment["s5"]["replan_trigger"] == "upstream_module_rerun_required"
    assert by_segment["s5"]["manual_review_required"] is True
    assert by_segment["s5"]["pair_anchor_endpoint_cluster_nodes"] == [[50], [61]]
    assert by_segment["s5"]["pair_anchor_error_swsd_nodes"] == ["6"]
    assert by_segment["s5"]["pair_anchor_error_candidate_rcsd_nodes"] == ["61"]
    assert by_segment["s5"]["pair_anchor_bridge_road_ids"] == ["rr_bridge"]
    assert by_segment["s5"]["pair_anchor_bridge_length_m"] == 6.5
    assert by_segment["s5"]["pair_anchor_diagnostic_source"] == "buffer_only_candidate_pair"
    assert by_segment["s5"]["pair_anchor_diagnostic_reason"] == "candidate_anchor_mismatch"


def _feature(properties: dict, geometry: LineString | None = None) -> dict:
    return {"properties": properties, "geometry": geometry or LineString([(0, 0), (1, 0)])}


def _road(road_id: str, snode: int | str, enode: int | str, coords: list[tuple[float, float]] | None = None) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode},
        "geometry": LineString(coords or [(float(snode), 0), (float(enode), 0)]),
    }


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
