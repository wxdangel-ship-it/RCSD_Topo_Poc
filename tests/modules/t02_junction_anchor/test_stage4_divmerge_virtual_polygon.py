from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fiona
import pytest
from shapely.geometry import GeometryCollection, LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_execution_contract import (
    build_stage4_representative_fields,
    evaluate_stage4_candidate_admission,
    finalize_stage4_acceptance,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step7_contract import (
    Stage4Step7DecisionInputs,
    build_stage4_step7_acceptance_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon import (
    run_t02_stage4_divmerge_virtual_polygon,
    run_t02_stage4_divmerge_virtual_polygon_cli,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    _build_local_surface_clip_geometry,
    _build_selected_support_corridor_geometry,
    _cover_check,
    _pick_reference_s,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step3_topology_skeleton import (
    _chain_candidates_from_topology,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_event_interpretation import (
    _analyze_divstrip_context,
    _evaluate_primary_rcsdnode_tolerance,
    _infer_primary_main_rc_node_from_local_context,
    _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover,
    _resolve_effective_target_rc_nodes,
    _resolve_operational_kind_2,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_geometric_support import (
    _clip_simple_event_span_window_by_divstrip_context,
    _refine_complex_event_span_window_by_divstrip_context,
    _resolve_parallel_centerline,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step6_polygon_assembly import (
    _is_expected_continuous_chain_multilobe_geometry,
    _refine_expected_continuous_chain_polygon_contour,
    _resolve_preferred_polygon_clip_geometry,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_surface_assembly_utils import (
    _build_group_node_fact_support_surface_union,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    _resolve_selected_component_connector_span_limit_m,
    _should_apply_selected_support_corridor,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    ParsedRoad,
    _bitmap_text_width,
    _failure_overlay_palette,
)


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _assert_stage4_tri_state(status_doc: dict[str, object]) -> None:
    acceptance_class = str(status_doc["acceptance_class"])
    business_outcome_class = str(status_doc["business_outcome_class"])
    visual_review_class = str(status_doc["visual_review_class"])
    if acceptance_class == "accepted":
        assert business_outcome_class == "success"
        assert visual_review_class.startswith("V1")
        return
    if acceptance_class == "review_required":
        assert business_outcome_class == "risk"
        assert visual_review_class.startswith("V2")
        return
    if acceptance_class == "rejected":
        assert business_outcome_class == "failure"
        assert visual_review_class.startswith(("V3", "V4", "V5"))
        return
    raise AssertionError(f"unexpected acceptance_class: {acceptance_class!r}")


def test_expected_continuous_chain_multilobe_geometry_accepts_bounded_two_lobe_shape() -> None:
    assert _is_expected_continuous_chain_multilobe_geometry(
        complex_junction=True,
        continuous_chain_applied=True,
        continuous_chain_present=True,
        continuous_chain_sequential_ok=True,
        component_mask_used_support_fallback=False,
        parallel_competitor_present=False,
        selected_component_surface_diags=(
            {"component_index": 0, "ok": True, "start_offset_m": -25.0, "end_offset_m": 10.0},
            {"component_index": 1, "ok": True, "start_offset_m": -25.0, "end_offset_m": 10.0},
        ),
        complex_multibranch_lobe_diags=(
            {"ok": True, "candidate_start_offset_m": -28.0, "candidate_end_offset_m": 28.0},
            {"ok": True, "candidate_start_offset_m": -28.0, "candidate_end_offset_m": 21.7},
        ),
    ) is True


@pytest.mark.parametrize(
    ("selected_component_surface_diags", "complex_multibranch_lobe_diags", "continuous_chain_present"),
    [
        (
            (
                {"component_index": 0, "ok": True},
                {"component_index": 1, "ok": True},
                {"component_index": 2, "ok": True},
            ),
            (
                {"ok": True},
                {"ok": True},
            ),
            True,
        ),
        (
            (
                {"component_index": 0, "ok": True},
                {"component_index": 1, "ok": True},
                {"component_index": "connector_0", "ok": False, "reason": "connector_span_exceeds_limit"},
            ),
            (
                {"ok": True},
                {"ok": True},
            ),
            False,
        ),
    ],
)
def test_expected_continuous_chain_multilobe_geometry_rejects_unbounded_or_nonchain_shapes(
    selected_component_surface_diags: tuple[dict[str, object], ...],
    complex_multibranch_lobe_diags: tuple[dict[str, object], ...],
    continuous_chain_present: bool,
) -> None:
    assert _is_expected_continuous_chain_multilobe_geometry(
        complex_junction=True,
        continuous_chain_applied=continuous_chain_present,
        continuous_chain_present=continuous_chain_present,
        continuous_chain_sequential_ok=continuous_chain_present,
        component_mask_used_support_fallback=False,
        parallel_competitor_present=False,
        selected_component_surface_diags=selected_component_surface_diags,
        complex_multibranch_lobe_diags=complex_multibranch_lobe_diags,
    ) is False


def test_selected_support_corridor_activates_for_large_full_fill_parallel_ratio() -> None:
    assert _should_apply_selected_support_corridor(
        allow_full_axis_drivezone_fill=True,
        parallel_competitor_present=False,
        parallel_side_geometry=box(0, 0, 8, 5),
        local_surface_clip_geometry=box(0, 0, 10, 10),
    ) is True


def test_selected_support_corridor_stays_disabled_for_small_parallel_ratio() -> None:
    assert _should_apply_selected_support_corridor(
        allow_full_axis_drivezone_fill=True,
        parallel_competitor_present=False,
        parallel_side_geometry=box(0, 0, 2, 2),
        local_surface_clip_geometry=box(0, 0, 10, 10),
    ) is False


def test_build_selected_support_corridor_clips_to_drivezone_and_anchor() -> None:
    corridor = _build_selected_support_corridor_geometry(
        drivezone_union=box(0, 0, 20, 10),
        clip_geometry=box(2, 1, 18, 9),
        selected_support_union=LineString([(4, 5), (16, 5)]).buffer(0.1),
        event_anchor_geometry=Point(10, 5).buffer(0.2),
        support_buffer_m=2.0,
    )

    assert not corridor.is_empty
    assert corridor.within(box(2, 1, 18, 9))
    assert corridor.intersects(Point(10, 5).buffer(0.5))


def test_stage4_candidate_admission_accepts_in_scope_candidate() -> None:
    admission = evaluate_stage4_candidate_admission(
        has_evd="yes",
        is_anchor="no",
        source_kind=None,
        source_kind_2=8,
        supported_kind=True,
        out_of_scope_reason="mainnodeid_out_of_scope",
    )

    assert admission.admitted is True
    assert admission.reason is None
    assert admission.detail is None


def test_stage4_candidate_admission_rejects_out_of_scope_candidate() -> None:
    admission = evaluate_stage4_candidate_admission(
        has_evd="no",
        is_anchor="no",
        source_kind=None,
        source_kind_2=8,
        supported_kind=True,
        out_of_scope_reason="mainnodeid_out_of_scope",
    )

    assert admission.admitted is False
    assert admission.reason == "mainnodeid_out_of_scope"
    assert "has_evd=no" in str(admission.detail)


def test_stage4_acceptance_contract_supports_explicit_rejected_path() -> None:
    decision = finalize_stage4_acceptance(
        review_reasons=["coverage_incomplete"],
        hard_rejection_reasons=["missing_required_field"],
        flow_success=True,
    )

    assert decision.acceptance_class == "rejected"
    assert decision.acceptance_reason == "missing_required_field"
    assert decision.success is False
    assert decision.flow_success is True
    assert decision.review_reasons == ("coverage_incomplete",)
    assert decision.hard_rejection_reasons == ("missing_required_field",)


def test_stage4_step7_rejects_off_trunk_full_axis_drivezone_fill_geometry() -> None:
    representative_fields = build_stage4_representative_fields(
        mainnodeid="73462878",
        source_kind=None,
        source_kind_2=16,
        kind_2=16,
        grade_2=1,
    )
    step4_result = SimpleNamespace(
        review_signals=(),
        hard_rejection_signals=(),
        risk_signals=(),
        legacy_step5_readiness=SimpleNamespace(ready=True),
        evidence_decision=SimpleNamespace(
            primary_source="divstrip_direct",
            selection_mode="divstrip_primary",
            fallback_used=False,
        ),
        reverse_tip_decision=SimpleNamespace(used=False),
    )
    step6_result = SimpleNamespace(
        geometry_state=SimpleNamespace(value="geometry_built_with_risk"),
        geometry_risk_signals=SimpleNamespace(
            signals=("component_reseeded_after_clip", "full_axis_drivezone_fill")
        ),
        legacy_step7_bridge=SimpleNamespace(ready=True),
    )

    result = build_stage4_step7_acceptance_result(
        Stage4Step7DecisionInputs(
            representative_node_id="73462878",
            representative_mainnodeid="73462878",
            representative_fields=representative_fields,
            step4_event_interpretation=step4_result,
            step6_polygon_assembly=step6_result,
            primary_main_rc_node_present=True,
            direct_target_rc_node_ids=(),
            effective_target_rc_node_ids=("5395474060682239",),
            coverage_missing_ids=(),
            primary_rcsdnode_tolerance={
                "reason": "rcsdnode_main_off_trunk",
                "rcsdnode_coverage_mode": "off_trunk",
                "rcsdnode_tolerance_rule": "diverge_main_seed_on_pre_trunk_le_20m",
                "rcsdnode_tolerance_applied": False,
            },
            flow_success=True,
        )
    )

    assert result.decision.acceptance_class == "rejected"
    assert result.decision.acceptance_reason == "foreign_corridor_off_trunk_full_axis_drivezone_fill"
    assert result.decision.business_outcome_class == "failure"
    assert result.decision.visual_review_class.startswith("V4")
    assert "foreign_corridor_off_trunk_full_axis_drivezone_fill" in result.decision.hard_rejection_reasons


def test_stage4_step7_demotes_parallel_side_split_geometry_to_review() -> None:
    representative_fields = build_stage4_representative_fields(
        mainnodeid="30434673",
        source_kind=None,
        source_kind_2=16,
        kind_2=16,
        grade_2=1,
    )
    step4_result = SimpleNamespace(
        review_signals=(),
        hard_rejection_signals=(),
        risk_signals=(),
        legacy_step5_readiness=SimpleNamespace(ready=True),
        evidence_decision=SimpleNamespace(
            primary_source="divstrip_direct",
            selection_mode="divstrip_primary",
            fallback_used=False,
        ),
        reverse_tip_decision=SimpleNamespace(used=False),
    )
    step6_result = SimpleNamespace(
        geometry_state=SimpleNamespace(value="geometry_built_with_risk"),
        geometry_risk_signals=SimpleNamespace(
            signals=("component_reseeded_after_clip", "parallel_side_split")
        ),
        parallel_side_clip_applied=True,
        full_fill_applied=False,
        legacy_step7_bridge=SimpleNamespace(ready=True),
    )

    result = build_stage4_step7_acceptance_result(
        Stage4Step7DecisionInputs(
            representative_node_id="30434673",
            representative_mainnodeid="30434673",
            representative_fields=representative_fields,
            step4_event_interpretation=step4_result,
            step6_polygon_assembly=step6_result,
            primary_main_rc_node_present=True,
            direct_target_rc_node_ids=("30434673",),
            effective_target_rc_node_ids=("30434673",),
            coverage_missing_ids=(),
            primary_rcsdnode_tolerance={
                "reason": None,
                "rcsdnode_coverage_mode": "trunk_window_tolerated",
                "rcsdnode_lateral_dist_m": 1.6,
                "rcsdnode_tolerance_applied": True,
            },
            flow_success=True,
        )
    )

    assert result.decision.acceptance_class == "review_required"
    assert result.decision.acceptance_reason == "geometry_built_with_risk"
    assert result.decision.visual_review_class.startswith("V2")
    assert "parallel_side_split" in result.decision.review_reasons


def test_stage4_step7_rejects_parallel_side_full_fill_foreign_geometry() -> None:
    representative_fields = build_stage4_representative_fields(
        mainnodeid="987998",
        source_kind=None,
        source_kind_2=16,
        kind_2=16,
        grade_2=1,
    )
    step4_result = SimpleNamespace(
        review_signals=(),
        hard_rejection_signals=(),
        risk_signals=(),
        legacy_step5_readiness=SimpleNamespace(ready=True),
        evidence_decision=SimpleNamespace(
            primary_source="divstrip_direct",
            selection_mode="divstrip_primary",
            fallback_used=False,
        ),
        reverse_tip_decision=SimpleNamespace(used=False),
    )
    step6_result = SimpleNamespace(
        geometry_state=SimpleNamespace(value="geometry_built_with_risk"),
        geometry_risk_signals=SimpleNamespace(
            signals=("component_reseeded_after_clip", "full_axis_drivezone_fill", "parallel_side_split")
        ),
        parallel_side_clip_applied=True,
        full_fill_applied=True,
        legacy_step7_bridge=SimpleNamespace(ready=True),
    )

    result = build_stage4_step7_acceptance_result(
        Stage4Step7DecisionInputs(
            representative_node_id="987998",
            representative_mainnodeid="987998",
            representative_fields=representative_fields,
            step4_event_interpretation=step4_result,
            step6_polygon_assembly=step6_result,
            primary_main_rc_node_present=True,
            direct_target_rc_node_ids=("987998",),
            effective_target_rc_node_ids=("987998",),
            coverage_missing_ids=(),
            primary_rcsdnode_tolerance={
                "reason": None,
                "rcsdnode_coverage_mode": "exact_cover",
                "rcsdnode_lateral_dist_m": 30.0,
                "rcsdnode_tolerance_applied": False,
            },
            flow_success=True,
        )
    )

    assert result.decision.acceptance_class == "rejected"
    assert result.decision.acceptance_reason == "foreign_corridor_parallel_side_full_axis_drivezone_fill"
    assert result.decision.business_outcome_class == "failure"
    assert result.decision.visual_review_class.startswith("V4")
    assert "foreign_corridor_parallel_side_full_axis_drivezone_fill" in result.decision.hard_rejection_reasons


def test_stage4_representative_fields_fallback_kind_to_kind2() -> None:
    fields = build_stage4_representative_fields(
        mainnodeid="100",
        source_kind=None,
        source_kind_2=16,
        kind_2=16,
        grade_2=1,
    )

    assert fields.mainnodeid == "100"
    assert fields.kind == 16
    assert fields.source_kind is None
    assert fields.source_kind_2 == 16


def test_stage4_failure_overlay_banner_labels_keep_cn_review_and_rejected_text() -> None:
    review_label = _failure_overlay_palette(
        "review_required_anything",
        failure_class="review_required",
    )["label"]
    rejected_label = _failure_overlay_palette(
        "rejected_anything",
        failure_class="rejected",
    )["label"]

    assert review_label == "REVIEW / 待复核"
    assert rejected_label == "REJECTED / 失败"
    assert _bitmap_text_width(review_label, scale=1) > _bitmap_text_width("REVIEW", scale=1)
    assert _bitmap_text_width(rejected_label, scale=1) > _bitmap_text_width("REJECTED", scale=1)


@pytest.mark.parametrize(
    ("acceptance_class", "expected_exit_code"),
    [
        ("accepted", 0),
        ("review_required", 0),
        ("rejected", 0),
        ("", 2),
    ],
)
def test_stage4_cli_treats_formal_verdicts_as_normal_completion(
    monkeypatch: pytest.MonkeyPatch,
    acceptance_class: str,
    expected_exit_code: int,
) -> None:
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon.run_t02_stage4_divmerge_virtual_polygon",
        lambda **_kwargs: SimpleNamespace(status_doc={"acceptance_class": acceptance_class}),
    )

    exit_code = run_t02_stage4_divmerge_virtual_polygon_cli(SimpleNamespace(
        nodes_path="nodes.gpkg",
        roads_path="roads.gpkg",
        drivezone_path="drivezone.gpkg",
        divstripzone_path="divstripzone.gpkg",
        rcsdroad_path="rcsdroad.gpkg",
        rcsdnode_path="rcsdnode.gpkg",
        mainnodeid="100",
        out_root="out",
        run_id="run",
        nodes_layer=None,
        roads_layer=None,
        drivezone_layer=None,
        divstripzone_layer=None,
        rcsdroad_layer=None,
        rcsdnode_layer=None,
        nodes_crs=None,
        roads_crs=None,
        drivezone_crs=None,
        divstripzone_crs=None,
        rcsdroad_crs=None,
        rcsdnode_crs=None,
        debug=False,
        debug_render_root=None,
    ))

    assert exit_code == expected_exit_code

def _write_fixture(
    tmp_path: Path,
    *,
    kind_2: int,
    kind: int | None = None,
    divstrip_mode: str = "nearby_single",
    rcsdroad_outside_drivezone: bool = False,
    rcsdnode_outside_drivezone: bool = False,
    main_rcsdnode_geometry: Point | None = None,
    main_rcsdnode_id: str = "100",
    main_rcsdnode_mainnodeid: str | None = "100",
    extra_node_features: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    node_features = [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind": kind,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind": kind,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(6.0, 2.0),
            },
    ]
    if extra_node_features:
        node_features.extend(extra_node_features)
    write_vector(nodes_path, node_features, crs_text="EPSG:3857")
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    if divstrip_mode == "nearby_single":
        divstrip_geometries = [box(18.0, -4.0, 30.0, 4.0)]
    elif divstrip_mode == "road_near_seed_far":
        divstrip_geometries = [box(36.0, -4.0, 48.0, 4.0)]
    elif divstrip_mode == "not_nearby":
        divstrip_geometries = [box(68.0, 42.0, 78.0, 52.0)]
    elif divstrip_mode == "ambiguous_two_nearby":
        divstrip_geometries = [box(14.0, -8.0, 20.0, -2.0), box(24.0, 2.0, 30.0, 8.0)]
    else:
        raise ValueError(f"Unsupported divstrip_mode: {divstrip_mode}")
    write_vector(
        divstripzone_path,
        [{"properties": {"id": f"dz_{index}"}, "geometry": geometry} for index, geometry in enumerate(divstrip_geometries)],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    rcsdnode_features = [
        {
            "properties": {"id": main_rcsdnode_id, "mainnodeid": main_rcsdnode_mainnodeid},
            "geometry": main_rcsdnode_geometry or Point(0.0, 0.0),
        },
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
    ]
    if rcsdroad_outside_drivezone:
        rcsdroad_path = tmp_path / "rcsdroad_outside.gpkg"
        write_vector(
            rcsdroad_path,
            [
                {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 155.0)])},
                {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
                {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            ],
            crs_text="EPSG:3857",
        )
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    elif rcsdnode_outside_drivezone:
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
        "divstrip_union": unary_union(divstrip_geometries),
    }


def _write_multibranch_fixture(tmp_path: Path, *, kind_2: int) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": kind_2, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": kind_2, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    side_specs = [
        ("branch_east", (0.0, 0.0), (50.0, 0.0), "100", "401"),
        ("branch_northeast", (0.0, 0.0), (30.0, 52.0), "100", "402"),
        ("branch_southeast", (0.0, 0.0), (30.0, -52.0), "100", "403"),
    ]
    roads = [
        {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
        {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
    ]
    rcsd_roads = [
        {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
        {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
    ]
    rcsd_nodes = [
        {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
    ]
    for branch_id, start, end, start_node, end_node in side_specs:
        road_id = branch_id
        if kind_2 == 16:
            road_props = {"id": road_id, "snodeid": start_node, "enodeid": end_node, "direction": 2}
            rc_props = {"id": f"rc_{road_id}", "snodeid": start_node, "enodeid": f"9{end_node}", "direction": 2}
            rc_end = end
        else:
            road_props = {"id": road_id, "snodeid": end_node, "enodeid": start_node, "direction": 2}
            rc_props = {"id": f"rc_{road_id}", "snodeid": f"9{end_node}", "enodeid": start_node, "direction": 2}
            rc_end = end
        roads.append({"properties": road_props, "geometry": LineString([start, end])})
        rcsd_roads.append({"properties": rc_props, "geometry": LineString([start, rc_end])})
        rcsd_nodes.append({"properties": {"id": f"9{end_node}", "mainnodeid": None}, "geometry": Point(*end)})
    write_vector(roads_path, roads, crs_text="EPSG:3857")
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": unary_union([box(-12.0, -75.0, 12.0, 75.0), box(0.0, -20.0, 70.0, 20.0), box(0.0, 0.0, 45.0, 65.0), box(0.0, -65.0, 45.0, 0.0)])}],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {
                "properties": {"id": "divstrip_multi"},
                "geometry": box(10.0, -34.0, 36.0, 4.0) if kind_2 == 8 else box(10.0, -4.0, 36.0, 34.0),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(rcsdroad_path, rcsd_roads, crs_text="EPSG:3857")
    write_vector(rcsdnode_path, rcsd_nodes, crs_text="EPSG:3857")
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_reverse_tip_fixture(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"
    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_west", "snodeid": "401", "enodeid": "100", "direction": 2}, "geometry": LineString([(-40.0, 0.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "402", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": unary_union([box(-50.0, -12.0, 60.0, 12.0), box(-12.0, -70.0, 12.0, 70.0)])}],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [{"properties": {"id": "divstrip_east"}, "geometry": box(18.0, -4.0, 30.0, 4.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2}, "geometry": LineString([(-35.0, 0.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (42.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(42.0, 0.0)},
            {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-35.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_continuous_chain_fixture(
    tmp_path: Path,
    *,
    representative_kind_2: int = 8,
    representative_kind: int | None = None,
) -> dict[str, Path]:
    fixture = _write_fixture(
        tmp_path,
        kind_2=representative_kind_2,
        kind=representative_kind,
        divstrip_mode="nearby_single",
    )
    nodes_path = fixture["nodes_path"]
    existing_features = _load_vector_doc(nodes_path)["features"]
    write_vector(
        nodes_path,
        [
            {
                "properties": feature["properties"],
                "geometry": shape(feature["geometry"]),
            }
            for feature in existing_features
        ]
        + [
            {"properties": {"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1}, "geometry": Point(24.0, 0.0)},
            {"properties": {"id": "201", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1}, "geometry": Point(29.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": fixture["nodes_path"],
        "roads_path": fixture["roads_path"],
        "drivezone_path": fixture["drivezone_path"],
        "divstripzone_path": fixture["divstripzone_path"],
        "rcsdroad_path": fixture["rcsdroad_path"],
        "rcsdnode_path": fixture["rcsdnode_path"],
    }


@pytest.mark.parametrize("kind_2", [8, 16])
def test_stage4_accepts_kind_8_and_16_with_nearby_divstrip(tmp_path: Path, kind_2: int) -> None:
    fixture = _write_fixture(tmp_path, kind_2=kind_2, divstrip_mode="nearby_single")
    original_nodes = _load_vector_doc(fixture["nodes_path"])
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id=f"kind_{kind_2}",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is (kind_2 == 16)
    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon_feature = polygon_doc["features"][0]
    polygon_geometry = shape(polygon_feature["geometry"])
    assert polygon_feature["properties"]["acceptance_class"] == (
        "review_required" if kind_2 == 8 else "accepted"
    )
    assert polygon_feature["properties"]["divstrip_present"] == 1
    assert polygon_feature["properties"]["divstrip_nearby"] == 1
    assert polygon_feature["properties"]["divstrip_component_count"] == 1
    assert polygon_feature["properties"]["selection_mode"] == "divstrip_primary"
    assert polygon_feature["properties"]["evidence_source"] == "drivezone+divstrip+roads+rcsd+seed"
    assert polygon_geometry.intersection(fixture["divstrip_union"]).area == pytest.approx(0.0)
    min_x, min_y, max_x, max_y = polygon_geometry.bounds
    assert max_y - min_y <= 120.0

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["divstrip_component_count"] == 1
    assert status_doc["divstrip"]["divstrip_component_selected"] == ["divstrip_component_0"]
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"
    assert status_doc["event_shape"]["event_span_start_m"] >= -25.0
    assert status_doc["event_shape"]["event_span_end_m"] <= 25.0
    if kind_2 == 8:
        assert status_doc["acceptance_reason"] == "reverse_tip_used"
        assert status_doc["review_reasons"] == ["reverse_tip_used"]
    else:
        assert status_doc["acceptance_reason"] == "stable"
        assert status_doc["review_reasons"] == []
    assert audit_doc["rows"][0]["evidence_source"] == "drivezone+divstrip+roads+rcsd+seed"
    assert _load_vector_doc(fixture["nodes_path"]) == original_nodes


def test_stage4_prefers_tip_projection_when_tip_and_first_hit_both_exist(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="prefer_tip_projection",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["event_shape"]["event_tip_s_m"] is not None
    assert status_doc["event_shape"]["event_split_pick_source"] == "divstrip_tip_projection_window"


def test_stage4_uses_adjacent_semantic_junction_boundary_even_when_neighbor_is_not_stage4_candidate(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        extra_node_features=[
            {
                "properties": {
                    "id": "500",
                    "mainnodeid": "500",
                    "has_evd": "yes",
                    "is_anchor": "yes",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 34.0),
            },
            {
                "properties": {
                    "id": "501",
                    "mainnodeid": "500",
                    "has_evd": "yes",
                    "is_anchor": "yes",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(2.0, 38.0),
            },
        ],
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="semantic_boundary_neighbor",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    previous_boundary_offset = status_doc["event_shape"]["semantic_prev_boundary_offset_m"]
    next_boundary_offset = status_doc["event_shape"]["semantic_next_boundary_offset_m"]
    assert previous_boundary_offset is not None or next_boundary_offset is not None
    if previous_boundary_offset is not None:
        assert status_doc["event_shape"]["event_span_start_m"] > float(previous_boundary_offset)
    if next_boundary_offset is not None:
        assert status_doc["event_shape"]["event_span_end_m"] < float(next_boundary_offset)


def test_pick_reference_s_prefers_tip_projection_over_drivezone_split() -> None:
    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=12.0,
        divstrip_ref_source="tip_projection",
        drivezone_split_s=8.0,
        max_offset_m=30.0,
    )

    assert chosen_s == pytest.approx(12.0)
    assert position_source == "divstrip_ref"
    assert split_pick_source == "divstrip_tip_projection_window"


def test_primary_rcsdnode_exact_cover_overrides_off_trunk_when_offset_is_valid() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 25.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
            geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="300",
            direction=2,
        )
    ]
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, 20.0, 15.0, 30.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=local_roads,
        selected_roads=local_roads,
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 40.0),
    )

    assert result["reason"] is None
    assert result["rcsdnode_coverage_mode"] == "exact_cover"
    assert result["covered"] is True
    assert result["rcsdnode_lateral_dist_m"] == pytest.approx(25.0)


def test_primary_rcsdnode_selected_road_corridor_tolerance_extends_polygon() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 8.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    selected_side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "100", "enodeid": "301", "direction": 2},
        geometry=LineString([(0.0, 8.0), (20.0, 8.0)]),
        road_id="road_b",
        snodeid="100",
        enodeid="301",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, -2.0, 15.0, 2.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road, selected_side_road],
        selected_roads=[selected_side_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 20.0),
    )

    assert result["reason"] is None
    assert result["rcsdnode_coverage_mode"] == "selected_road_corridor_tolerated"
    assert result["covered"] is True
    assert result["extended_polygon_geometry"].buffer(0).covers(primary_main_rc_node.geometry)


def test_primary_rcsdnode_selected_road_corridor_tolerance_respects_support_clip() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 8.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    selected_side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "100", "enodeid": "301", "direction": 2},
        geometry=LineString([(0.0, 8.0), (20.0, 8.0)]),
        road_id="road_b",
        snodeid="100",
        enodeid="301",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, -2.0, 15.0, 2.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road, selected_side_road],
        selected_roads=[selected_side_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 20.0),
        support_clip_geometry=box(-10.0, -3.0, 30.0, 3.0),
    )

    assert result["reason"] == "rcsdnode_main_off_trunk"
    assert result["rcsdnode_coverage_mode"] != "selected_road_corridor_tolerated"
    assert result["covered"] is False


def test_infer_primary_rcsdnode_can_use_preferred_main_branch_when_trunk_is_ambiguous() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=16,
        grade_2=1,
    )
    primary_candidate = ParsedNode(
        feature_index=1,
        properties={"id": "910", "mainnodeid": "0"},
        geometry=Point(0.0, -8.0),
        node_id="910",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    side_candidate = ParsedNode(
        feature_index=2,
        properties={"id": "911", "mainnodeid": "0"},
        geometry=Point(-8.0, 0.0),
        node_id="911",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "300", "enodeid": "100", "direction": 2},
        geometry=LineString([(0.0, -20.0), (0.0, 0.0)]),
        road_id="road_a",
        snodeid="300",
        enodeid="100",
        direction=2,
    )
    side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "301", "enodeid": "100", "direction": 2},
        geometry=LineString([(-20.0, 0.0), (0.0, 0.0)]),
        road_id="road_b",
        snodeid="301",
        enodeid="100",
        direction=2,
    )
    selected_rcsd_road = ParsedRoad(
        feature_index=2,
        properties={"id": "rc_a", "snodeid": "100", "enodeid": "910", "direction": 2},
        geometry=LineString([(0.0, 0.0), (0.0, -8.0)]),
        road_id="rc_a",
        snodeid="100",
        enodeid="910",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=270.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
        SimpleNamespace(
            branch_id="road_2",
            road_ids=["road_b"],
            angle_deg=180.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
    ]

    unstable = _infer_primary_main_rc_node_from_local_context(
        local_rcsd_nodes=[primary_candidate, side_candidate],
        selected_rcsd_roads=[selected_rcsd_road],
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        local_roads=[trunk_road, side_road],
        kind_2=16,
    )
    preferred = _infer_primary_main_rc_node_from_local_context(
        local_rcsd_nodes=[primary_candidate, side_candidate],
        selected_rcsd_roads=[selected_rcsd_road],
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        local_roads=[trunk_road, side_road],
        kind_2=16,
        preferred_trunk_branch_id="road_1",
    )

    assert unstable["primary_main_rc_node"] is None
    assert unstable["seed_mode"] == "trunk_unstable"
    assert preferred["seed_mode"] == "inferred_local_trunk_window"
    assert preferred["primary_main_rc_node"].node_id == "910"


def test_primary_rcsdnode_tolerance_uses_preferred_main_branch_when_trunk_is_ambiguous() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=16,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "910", "mainnodeid": "0"},
        geometry=Point(0.0, -8.0),
        node_id="910",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "300", "enodeid": "100", "direction": 2},
        geometry=LineString([(0.0, -20.0), (0.0, 0.0)]),
        road_id="road_a",
        snodeid="300",
        enodeid="100",
        direction=2,
    )
    side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "301", "enodeid": "100", "direction": 2},
        geometry=LineString([(-20.0, 0.0), (0.0, 0.0)]),
        road_id="road_b",
        snodeid="301",
        enodeid="100",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=270.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
        SimpleNamespace(
            branch_id="road_2",
            road_ids=["road_b"],
            angle_deg=180.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
    ]

    unstable = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(-2.0, -12.0, 2.0, -1.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        local_roads=[trunk_road, side_road],
        selected_roads=[trunk_road],
        kind_2=16,
        drivezone_union=box(-20.0, -25.0, 10.0, 10.0),
    )
    preferred = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(-2.0, -12.0, 2.0, -1.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        local_roads=[trunk_road, side_road],
        selected_roads=[trunk_road],
        kind_2=16,
        drivezone_union=box(-20.0, -25.0, 10.0, 10.0),
        preferred_trunk_branch_id="road_1",
    )

    assert unstable["rcsdnode_coverage_mode"] == "trunk_unstable"
    assert preferred["trunk_branch_id"] == "road_1"
    assert preferred["rcsdnode_coverage_mode"] == "exact_cover"
    assert preferred["covered"] is True


def test_effective_target_rc_nodes_include_selected_road_corridor_tolerance() -> None:
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "910", "mainnodeid": "0"},
        geometry=Point(0.0, -8.0),
        node_id="910",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )

    result = _resolve_effective_target_rc_nodes(
        direct_target_rc_nodes=[],
        primary_main_rc_node=primary_main_rc_node,
        primary_rcsdnode_tolerance={"rcsdnode_coverage_mode": "selected_road_corridor_tolerated"},
    )

    assert [node.node_id for node in result] == ["910"]


def test_reselect_inferred_primary_rcsdnode_prefers_alternate_exact_cover() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    inferred_off_trunk_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 22.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    alternate_exact_cover_node = ParsedNode(
        feature_index=2,
        properties={"id": "201", "mainnodeid": "0"},
        geometry=Point(10.0, 14.0),
        node_id="201",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]
    polygon_geometry = box(5.0, 12.0, 15.0, 16.0)
    initial_tolerance = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=polygon_geometry,
        primary_main_rc_node=inferred_off_trunk_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road],
        selected_roads=[trunk_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 30.0),
    )

    selected_node, selected_tolerance = _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover(
        primary_main_rc_node=inferred_off_trunk_node,
        primary_rcsdnode_tolerance=initial_tolerance,
        representative_node=representative_node,
        selected_rcsd_nodes=[inferred_off_trunk_node, alternate_exact_cover_node],
        direct_target_rc_nodes=[],
        rcsdnode_seed_mode="inferred_local_trunk_window",
        polygon_geometry=polygon_geometry,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road],
        selected_roads=[trunk_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 30.0),
    )

    assert selected_node is not None
    assert selected_node.node_id == "201"
    assert selected_tolerance["rcsdnode_coverage_mode"] == "exact_cover"
    assert selected_tolerance["rcsdnode_reselected_exact_cover"] is True
    assert selected_tolerance["rcsdnode_reselected_from_node_id"] == "200"
    assert selected_tolerance["rcsdnode_reselected_to_node_id"] == "201"


def test_reselect_inferred_primary_rcsdnode_keeps_current_when_no_alternate_exact_cover() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=16,
        grade_2=1,
    )
    current_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 20.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    alternate_node = ParsedNode(
        feature_index=2,
        properties={"id": "201", "mainnodeid": "0"},
        geometry=Point(10.0, 40.0),
        node_id="201",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "300", "enodeid": "100", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="300",
        enodeid="100",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        )
    ]
    polygon_geometry = box(5.0, -2.0, 15.0, 2.0)
    initial_tolerance = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=polygon_geometry,
        primary_main_rc_node=current_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road],
        selected_roads=[trunk_road],
        kind_2=16,
        drivezone_union=box(-10.0, -10.0, 30.0, 50.0),
    )

    selected_node, selected_tolerance = _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover(
        primary_main_rc_node=current_node,
        primary_rcsdnode_tolerance=initial_tolerance,
        representative_node=representative_node,
        selected_rcsd_nodes=[current_node, alternate_node],
        direct_target_rc_nodes=[],
        rcsdnode_seed_mode="inferred_local_trunk_window",
        polygon_geometry=polygon_geometry,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road],
        selected_roads=[trunk_road],
        kind_2=16,
        drivezone_union=box(-10.0, -10.0, 30.0, 50.0),
    )

    assert selected_node is current_node
    assert selected_tolerance["reason"] == "rcsdnode_main_off_trunk"
    assert not selected_tolerance.get("rcsdnode_reselected_exact_cover", False)


def test_resolve_parallel_centerline_ignores_excluded_current_junction_roads() -> None:
    axis_centerline = LineString([(0.0, 0.0), (30.0, 0.0)])
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_selected", "snodeid": "100", "enodeid": "101", "direction": 2},
            geometry=LineString([(0.0, 0.0), (30.0, 0.0)]),
            road_id="road_selected",
            snodeid="100",
            enodeid="101",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_current_junction", "snodeid": "100", "enodeid": "102", "direction": 2},
            geometry=LineString([(0.0, 6.0), (30.0, 6.0)]),
            road_id="road_current_junction",
            snodeid="100",
            enodeid="102",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_other_corridor", "snodeid": "500", "enodeid": "501", "direction": 2},
            geometry=LineString([(0.0, -18.0), (30.0, -18.0)]),
            road_id="road_other_corridor",
            snodeid="500",
            enodeid="501",
            direction=2,
        ),
    ]

    result = _resolve_parallel_centerline(
        local_roads=local_roads,
        selected_road_ids={"road_selected"},
        excluded_road_ids={"road_current_junction"},
        axis_centerline=axis_centerline,
        axis_unit_vector=(1.0, 0.0),
        reference_point=Point(15.0, 0.0),
        parallel_side_sign=-1,
    )

    assert result is not None
    assert result.equals(local_roads[2].geometry)


def test_analyze_divstrip_context_simple_prefers_seed_nearest_component() -> None:
    main_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_main", "snodeid": "100", "enodeid": "200", "direction": 2},
        geometry=LineString([(0.0, 0.0), (50.0, 0.0)]),
        road_id="road_main",
        snodeid="100",
        enodeid="200",
        direction=2,
    )
    side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_side", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (30.0, 20.0)]),
        road_id="road_side",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(branch_id="road_1", road_ids=["road_main"]),
        SimpleNamespace(branch_id="road_2", road_ids=["road_side"]),
    ]
    result = _analyze_divstrip_context(
        local_divstrip_features=[
            SimpleNamespace(geometry=box(6.0, -1.5, 11.0, 1.5)),
            SimpleNamespace(geometry=box(20.0, -1.5, 25.0, 1.5)),
        ],
        seed_union=Point(0.0, 0.0),
        road_branches=road_branches,
        local_roads=[main_road, side_road],
        main_branch_ids={"road_1"},
        drivezone_union=box(-5.0, -10.0, 60.0, 30.0),
        event_branch_ids={"road_2"},
        allow_compound_pair_merge=False,
    )

    assert result["nearby"] is True
    assert result["selected_component_ids"] == ["divstrip_component_0"]


def test_clip_simple_event_span_window_first_hit_keeps_wider_default_pad_without_direct_targets() -> None:
    base_window = {
        "start_offset_m": -20.0,
        "end_offset_m": 20.0,
        "semantic_protected_start_m": -1.5,
        "semantic_protected_end_m": 1.5,
    }
    divstrip_geometry = box(6.0, -1.0, 9.0, 1.0)

    clipped_tip = _clip_simple_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        direct_target_rc_nodes=[],
        selected_roads=None,
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=1,
        is_complex_junction=False,
        event_split_pick_source="divstrip_tip_projection_window",
    )
    clipped_first_hit = _clip_simple_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        direct_target_rc_nodes=[],
        selected_roads=None,
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=1,
        is_complex_junction=False,
        event_split_pick_source="divstrip_first_hit_window",
    )

    assert clipped_tip["end_offset_m"] == pytest.approx(18.5)
    assert clipped_first_hit["end_offset_m"] == pytest.approx(20.0)
    assert clipped_first_hit["start_offset_m"] <= clipped_tip["start_offset_m"]


def test_build_local_surface_clip_geometry_localizes_full_fill_simple_case_by_divstrip_window() -> None:
    drivezone = box(-30.0, -10.0, 30.0, 10.0)
    axis_window = box(-12.0, -8.0, 12.0, 8.0)
    cross_section_surface = box(-6.0, -4.0, 6.0, 4.0)
    divstrip_event_window = box(-8.0, -5.0, 8.0, 5.0)
    divstrip_constraint_geometry = box(-2.0, -1.0, 2.0, 1.0)

    clip_geometry = _build_local_surface_clip_geometry(
        cross_section_surface_geometry=cross_section_surface,
        divstrip_event_window=divstrip_event_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_window_geometry=axis_window,
        drivezone_union=drivezone,
        is_complex_junction=False,
        multibranch_enabled=False,
        selected_component_count=1,
        allow_full_axis_drivezone_fill=True,
    )

    assert not clip_geometry.is_empty
    assert clip_geometry.within(axis_window)
    assert clip_geometry.intersects(divstrip_event_window)


def test_build_local_surface_clip_geometry_uses_divstrip_and_surface_intersection_for_complex_case() -> None:
    drivezone = box(-40.0, -20.0, 40.0, 20.0)
    axis_window = box(-30.0, -15.0, 30.0, 15.0)
    cross_section_surface = box(-18.0, -6.0, 18.0, 6.0)
    divstrip_event_window = box(-10.0, -10.0, 10.0, 10.0)
    divstrip_constraint_geometry = box(-4.0, -2.0, 4.0, 2.0)

    clip_geometry = _build_local_surface_clip_geometry(
        cross_section_surface_geometry=cross_section_surface,
        divstrip_event_window=divstrip_event_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_window_geometry=axis_window,
        drivezone_union=drivezone,
        is_complex_junction=True,
        multibranch_enabled=True,
        selected_component_count=2,
        allow_full_axis_drivezone_fill=False,
    )

    assert not clip_geometry.is_empty
    assert clip_geometry.within(drivezone)
    assert clip_geometry.intersects(divstrip_event_window)
    assert clip_geometry.intersects(cross_section_surface)


def test_resolve_preferred_polygon_clip_geometry_prefers_local_surface_for_expected_multilobe_case() -> None:
    cross_section_surface = box(-16.0, -6.0, 16.0, 6.0)
    local_surface_clip = box(-10.0, -4.0, 10.0, 4.0)
    preferred_clip_geometry, preferred_clip_mode = _resolve_preferred_polygon_clip_geometry(
        local_surface_clip_geometry=local_surface_clip,
        axis_window_geometry=box(-20.0, -8.0, 20.0, 8.0),
        cross_section_surface_geometry=cross_section_surface,
        expected_continuous_chain_multilobe_geometry=True,
    )

    assert preferred_clip_mode == "local_surface_clip"
    assert preferred_clip_geometry.equals(local_surface_clip)


def test_resolve_preferred_polygon_clip_geometry_expected_multilobe_falls_back_to_cross_section_without_local_clip() -> None:
    cross_section_surface = box(-16.0, -6.0, 16.0, 6.0)
    preferred_clip_geometry, preferred_clip_mode = _resolve_preferred_polygon_clip_geometry(
        local_surface_clip_geometry=GeometryCollection(),
        axis_window_geometry=box(-20.0, -8.0, 20.0, 8.0),
        cross_section_surface_geometry=cross_section_surface,
        expected_continuous_chain_multilobe_geometry=True,
    )

    assert preferred_clip_mode == "cross_section_surface"
    assert preferred_clip_geometry.equals(cross_section_surface)


def test_resolve_preferred_polygon_clip_geometry_prefers_cross_section_for_complex_fact_surface() -> None:
    cross_section_surface = box(-18.0, -6.0, 18.0, 6.0)
    preferred_clip_geometry, preferred_clip_mode = _resolve_preferred_polygon_clip_geometry(
        local_surface_clip_geometry=box(-10.0, -4.0, 10.0, 4.0),
        axis_window_geometry=box(-20.0, -8.0, 20.0, 8.0),
        cross_section_surface_geometry=cross_section_surface,
        expected_continuous_chain_multilobe_geometry=False,
        prefer_cross_section_surface_geometry=True,
    )

    assert preferred_clip_mode == "cross_section_surface"
    assert preferred_clip_geometry.equals(cross_section_surface)


def test_refine_expected_continuous_chain_polygon_contour_smooths_notched_outline() -> None:
    polygon_geometry = box(0.0, 0.0, 4.0, 4.0).difference(box(3.2, 1.5, 4.0, 2.5)).buffer(0)
    preferred_clip_geometry = box(0.0, 0.0, 4.2, 4.2)
    parallel_side_geometry = box(-0.2, -0.2, 4.0, 4.2)

    refined_geometry, applied = _refine_expected_continuous_chain_polygon_contour(
        polygon_geometry=polygon_geometry,
        preferred_clip_geometry=preferred_clip_geometry,
        parallel_side_geometry=parallel_side_geometry,
        drivezone_union=box(-1.0, -1.0, 6.0, 6.0),
    )

    assert applied is True
    assert not refined_geometry.is_empty
    assert refined_geometry.area > polygon_geometry.area
    assert refined_geometry.within(preferred_clip_geometry.buffer(1e-6))
    assert refined_geometry.exterior.length < polygon_geometry.exterior.length


def test_refine_expected_continuous_chain_polygon_contour_rejects_overexpanded_candidate() -> None:
    polygon_geometry = box(0.0, 0.0, 4.0, 4.0).difference(box(1.0, 1.0, 4.0, 3.0)).buffer(0)
    preferred_clip_geometry = box(0.0, 0.0, 4.2, 4.2)

    refined_geometry, applied = _refine_expected_continuous_chain_polygon_contour(
        polygon_geometry=polygon_geometry,
        preferred_clip_geometry=preferred_clip_geometry,
        parallel_side_geometry=GeometryCollection(),
        drivezone_union=box(-1.0, -1.0, 6.0, 6.0),
    )

    assert applied is False
    assert refined_geometry.equals(polygon_geometry)


def test_resolve_selected_component_connector_span_limit_extends_for_two_fact_complex_case() -> None:
    assert _resolve_selected_component_connector_span_limit_m(allow_extended_connector_span=False) == pytest.approx(72.0)
    assert _resolve_selected_component_connector_span_limit_m(allow_extended_connector_span=True) == pytest.approx(140.0)


def test_build_group_node_fact_support_surface_union_adds_uncovered_member_node_surface() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "17943587", "mainnodeid": "17943587", "has_evd": "yes", "is_anchor": "no", "kind_2": 128, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="17943587",
        mainnodeid="17943587",
        has_evd="yes",
        is_anchor="no",
        kind_2=128,
        grade_2=1,
    )
    member_node = ParsedNode(
        feature_index=1,
        properties={"id": "55353239", "mainnodeid": "17943587", "has_evd": "yes", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
        geometry=Point(0.0, 40.0),
        node_id="55353239",
        mainnodeid="17943587",
        has_evd="yes",
        is_anchor="no",
        kind_2=0,
        grade_2=0,
    )
    road_left = ParsedRoad(
        feature_index=0,
        properties={"id": "road_left", "snodeid": "55353239", "enodeid": "left_far", "direction": 2},
        geometry=LineString([(0.0, 40.0), (-8.0, 80.0)]),
        road_id="road_left",
        snodeid="55353239",
        enodeid="left_far",
        direction=2,
    )
    road_right = ParsedRoad(
        feature_index=1,
        properties={"id": "road_right", "snodeid": "55353239", "enodeid": "right_far", "direction": 2},
        geometry=LineString([(0.0, 40.0), (8.0, 80.0)]),
        road_id="road_right",
        snodeid="55353239",
        enodeid="right_far",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="branch_left",
            road_ids=["road_left"],
            angle_deg=135.0,
            has_incoming_support=False,
            has_outgoing_support=True,
            road_support_m=40.0,
            drivezone_support_m=40.0,
            rc_support_m=0.0,
        ),
        SimpleNamespace(
            branch_id="branch_right",
            road_ids=["road_right"],
            angle_deg=45.0,
            has_incoming_support=False,
            has_outgoing_support=True,
            road_support_m=40.0,
            drivezone_support_m=40.0,
            rc_support_m=0.0,
        ),
    ]

    fact_surface_geometry, node_diags = _build_group_node_fact_support_surface_union(
        representative_node=representative_node,
        group_nodes=[representative_node, member_node],
        existing_surface_geometry=GeometryCollection(),
        axis_centerline=LineString([(0.0, -20.0), (0.0, 90.0)]),
        axis_unit_vector=(0.0, 1.0),
        kind_2=16,
        road_branches=road_branches,
        selected_branch_ids={"branch_left", "branch_right"},
        road_lookup={"road_left": road_left, "road_right": road_right},
        drivezone_union=box(-20.0, -20.0, 20.0, 90.0),
        parallel_centerline=None,
        resolution_m=1.0,
        cross_half_len_m=20.0,
    )

    assert not fact_surface_geometry.is_empty
    assert fact_surface_geometry.intersects(member_node.geometry.buffer(2.0))
    assert any(
        item.get("component_index") == "fact_node_55353239" and bool(item.get("ok", False))
        for item in node_diags
    )


def test_refine_complex_event_span_window_by_divstrip_context_uses_component_span() -> None:
    base_window = {
        "start_offset_m": -12.0,
        "end_offset_m": 48.0,
        "semantic_protected_start_m": -12.0,
        "semantic_protected_end_m": 48.0,
        "candidate_offset_count": 10,
        "expansion_source": "semantic_context_refined",
    }
    divstrip_geometry = unary_union([box(-18.0, -2.0, -10.0, 2.0), box(12.0, -2.0, 24.0, 2.0)])
    selected_event_roads_geometry = unary_union(
        [
            LineString([(-20.0, 0.0), (0.0, 0.0)]).buffer(1.0, cap_style=2, join_style=2),
            LineString([(0.0, 0.0), (26.0, 0.0)]).buffer(1.0, cap_style=2, join_style=2),
        ]
    )

    refined = _refine_complex_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        selected_roads_geometry=selected_event_roads_geometry,
        selected_event_roads_geometry=selected_event_roads_geometry,
        selected_rcsd_roads_geometry=GeometryCollection(),
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=2,
        is_complex_junction=True,
    )

    assert refined["start_offset_m"] < -12.0
    assert refined["end_offset_m"] < 48.0
    assert refined["expansion_source"] == "complex_divstrip_component_context"


def test_refine_complex_event_span_window_by_divstrip_context_uses_local_road_clip_to_expand_forward_branch() -> None:
    base_window = {
        "start_offset_m": -100.0,
        "end_offset_m": 10.0,
        "semantic_protected_start_m": -100.0,
        "semantic_protected_end_m": 10.0,
        "candidate_offset_count": 8,
        "expansion_source": "semantic_context_refined",
    }
    divstrip_geometry = unary_union([box(-32.0, -2.0, -24.0, 2.0), box(-8.0, -2.0, -4.0, 2.0)])

    refined = _refine_complex_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        selected_roads_geometry=LineString([(-55.0, 0.0), (180.0, 0.0)]),
        selected_event_roads_geometry=LineString([(-55.0, 0.0), (180.0, 0.0)]),
        selected_rcsd_roads_geometry=GeometryCollection(),
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=2,
        is_complex_junction=True,
    )

    assert refined["end_offset_m"] > 10.0
    assert refined["end_offset_m"] < 30.0
    assert refined["start_offset_m"] <= -38.0
    assert refined["expansion_source"] == "complex_divstrip_component_context"


def test_resolve_operational_kind_2_accepts_complex_multibranch_event_without_side_branches() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 128, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=128,
        grade_2=1,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        ),
        SimpleNamespace(
            branch_id="road_2",
            road_ids=["road_b"],
            angle_deg=180.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
    ]

    result = _resolve_operational_kind_2(
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        preferred_branch_ids={"road_1", "road_2"},
        local_roads=[],
        divstrip_context={
            "constraint_geometry": None,
            "nearby": False,
            "ambiguous": False,
        },
        chain_context={
            "is_in_continuous_chain": False,
            "sequential_ok": False,
        },
        multibranch_context={
            "enabled": True,
            "selected_event_index": 0,
            "ambiguous": False,
        },
    )

    assert result["complex_junction"] is True
    assert result["ambiguous"] is False
    assert result["operational_kind_2"] == 16
    assert result["kind_resolution_mode"] == "complex_multibranch_event"


def test_chain_candidates_continue_through_degree_3_node_when_trunk_direction_is_clear() -> None:
    local_nodes = [
        ParsedNode(
            feature_index=0,
            properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=1,
            properties={"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, 0.0),
            node_id="200",
            mainnodeid="200",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
    ]
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "150", "direction": 2},
            geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="150",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_b", "snodeid": "150", "enodeid": "200", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, 0.0)]),
            road_id="road_b",
            snodeid="150",
            enodeid="200",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_side", "snodeid": "150", "enodeid": "250", "direction": 2},
            geometry=LineString([(10.0, 0.0), (10.0, 10.0)]),
            road_id="road_side",
            snodeid="150",
            enodeid="250",
            direction=2,
        ),
    ]

    chain_candidates, diag = _chain_candidates_from_topology(
        representative_node_id="100",
        representative_chain_kind_2=16,
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=50.0,
    )

    assert [node.node_id for node, _distance in chain_candidates] == ["200"]
    assert diag["chain_graph_node_count"] >= 4


def test_chain_candidates_stop_when_degree_3_continuation_is_ambiguous() -> None:
    local_nodes = [
        ParsedNode(
            feature_index=0,
            properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=1,
            properties={"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, 1.75),
            node_id="200",
            mainnodeid="200",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=2,
            properties={"id": "300", "mainnodeid": "300", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, -1.75),
            node_id="300",
            mainnodeid="300",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
    ]
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "150", "direction": 2},
            geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="150",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_b", "snodeid": "150", "enodeid": "200", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, 1.75)]),
            road_id="road_b",
            snodeid="150",
            enodeid="200",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_c", "snodeid": "150", "enodeid": "300", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, -1.75)]),
            road_id="road_c",
            snodeid="150",
            enodeid="300",
            direction=2,
        ),
    ]

    chain_candidates, diag = _chain_candidates_from_topology(
        representative_node_id="100",
        representative_chain_kind_2=16,
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=50.0,
    )

    assert chain_candidates == []
    assert diag["chain_graph_node_count"] >= 4


def test_stage4_falls_back_to_roads_when_divstrip_not_nearby(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="not_nearby")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_not_nearby",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "reverse_tip_used"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is False
    assert status_doc["divstrip"]["divstrip_component_count"] == 1
    assert status_doc["divstrip"]["divstrip_component_selected"] == []
    assert status_doc["divstrip"]["selection_mode"] == "roads_fallback"
    assert status_doc["review_reasons"] == ["reverse_tip_used", "fallback_to_weak_evidence"]
    assert audit_doc["rows"][0]["evidence_source"] == "drivezone+roads+rcsd+seed"
    assert artifacts.virtual_polygon_path.is_file()


def test_stage4_accepts_without_divstrip_input_by_falling_back_to_roads(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="no_divstrip_input",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "fallback_to_weak_evidence"
    assert status_doc["divstrip"]["divstrip_present"] is False
    assert status_doc["divstrip"]["divstrip_nearby"] is False
    assert status_doc["divstrip"]["selection_mode"] == "roads_fallback"
    assert status_doc["divstrip"]["evidence_source"] == "drivezone+roads+rcsd+seed"


def test_stage4_accepts_complex_kind_128_and_writes_rendered_map(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=128, kind=128, divstrip_mode="nearby_single")
    rendered_root = tmp_path / "renders"
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="complex_kind_128",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
        debug=True,
        debug_render_root=rendered_root,
    )

    assert artifacts.success is True
    assert artifacts.rendered_map_path == rendered_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    assert (artifacts.out_root / "stage4_debug" / "100.png").is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["kind"] == 128
    assert status_doc["source_kind"] == 128
    assert status_doc["source_kind_2"] == 128
    assert status_doc["kind_2"] == 16
    assert status_doc["kind_resolution"]["complex_junction"] is True
    assert status_doc["kind_resolution"]["kind_resolution_mode"] == "divstrip_event_position"
    assert status_doc["kind_resolution"]["kind_resolution_ambiguous"] is False
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is False
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"
    assert status_doc["output_files"]["rendered_map"] == str(rendered_root / "100.png")


def test_stage4_prefers_event_anchor_when_divstrip_has_two_seed_nearby_components(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="ambiguous_two_nearby")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_ambiguous",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["divstrip_component_count"] == 2
    assert len(status_doc["divstrip"]["divstrip_component_selected"]) == 1
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_accepts_diverge_main_rcsdnode_within_pre_trunk_window(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -18.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="diverge_pre_trunk_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_rule"] == "diverge_main_seed_on_pre_trunk_le_20m"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] in {False, True}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] in {"exact_cover", "trunk_window_tolerated"}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_offset_m"] == pytest.approx(18.0, abs=1.0)


def test_stage4_accepts_merge_main_rcsdnode_within_post_trunk_window(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=8,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, 18.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="merge_post_trunk_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "reverse_tip_used"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_1"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_rule"] == "merge_main_seed_on_post_trunk_le_20m"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] in {False, True}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] in {"exact_cover", "trunk_window_tolerated"}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_offset_m"] == pytest.approx(18.0, abs=1.0)


def test_stage4_polygon_writes_contract_kind_and_audit_fields(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=8,
        kind=None,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, 18.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="polygon_contract_fields",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    props = polygon_doc["features"][0]["properties"]
    assert props["mainnodeid"] == "100"
    assert props["kind"] == 8
    assert props["kind_2"] == 8
    assert props["divstrip_component_selected"] == '["divstrip_component_0"]'
    assert props["rcsdnode_tolerance_rule"] == "merge_main_seed_on_post_trunk_le_20m"
    assert props["rcsdnode_coverage_mode"] in {"exact_cover", "trunk_window_tolerated"}
    assert props["acceptance_class"] == "review_required"
    assert props["business_outcome_class"] == "risk"
    assert str(props["visual_review_class"]).startswith("V2")
    assert props["root_cause_layer"] == "step4"
    assert "review_reason=reverse_tip_used" in str(props["decision_basis"])


def test_stage4_status_exposes_step2_local_context_summary(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step2_context_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    step2_context = status_doc["step2_context"]
    assert step2_context["drivezone_hard_boundary"] is True
    assert step2_context["recall_window"]["diverge_trunk_backward_max_m"] == 50.0
    assert step2_context["recall_window"]["diverge_branch_forward_max_m"] == 200.0
    assert step2_context["recall_window"]["merge_trunk_forward_max_m"] == 50.0
    assert step2_context["recall_window"]["merge_branch_backward_max_m"] == 200.0
    assert step2_context["recall_window"]["scene_filter_mode"] == "drivezone_bounded_spatial_query"
    assert step2_context["recall_window"]["patch_membership_mode"] == "scene_supplement_only"
    assert step2_context["negative_exclusion_context"]["source_priority"] == ["rcsd", "swsd", "road_geometry"]
    assert step2_context["negative_exclusion_context"]["notes"] == [
        "step2_provisional_negative_exclusion_context",
        "final_geometric_exclusion_deferred_to_step5",
    ]


def test_stage4_status_exposes_step3_skeleton_summary(tmp_path: Path) -> None:
    fixture = _write_continuous_chain_fixture(tmp_path, representative_kind_2=16, representative_kind=128)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step3_skeleton_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    step3_skeleton = status_doc["step3_skeleton"]
    assert step3_skeleton["branch_result"]["branch_count"] >= 2
    assert step3_skeleton["branch_result"]["through_node_policy"] == "degree2_passthrough_does_not_break_branch"
    assert "through_node_candidate_ids" in step3_skeleton["branch_result"]
    assert step3_skeleton["stability"]["has_minimum_branches"] is True
    assert step3_skeleton["stability"]["main_pair_resolved"] is True
    assert step3_skeleton["stability"]["legacy_step4_adapter_required"] is True
    assert "related_mainnodeids" in step3_skeleton["chain_context"]
    assert "is_in_continuous_chain" in step3_skeleton["chain_context"]
    assert status_doc["step3_legacy_step4_adapter"]["required"] is True
    assert status_doc["step3_legacy_step4_adapter"]["ready"] is True


def test_stage4_status_exposes_step4_interpretation_summary(tmp_path: Path) -> None:
    fixture = _write_multibranch_fixture(tmp_path, kind_2=8)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step4_interpretation_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    step4_interpretation = status_doc["step4_interpretation"]
    assert step4_interpretation["scope"] == "fact_event_interpretation"
    assert step4_interpretation["evidence_decision"]["evidence_source"] == "multibranch_event"
    assert step4_interpretation["multibranch"]["multibranch_enabled"] is True
    assert step4_interpretation["multibranch"]["event_candidate_count"] >= 3
    assert step4_interpretation["kind_resolution"]["kind_resolution_mode"] in {
        "direct_kind_2",
        "complex_multibranch_event",
    }
    assert step4_interpretation["legacy_step5_adapter"]["ready"] is True
    assert status_doc["step4_legacy_step5_adapter"]["required"] is True
    assert status_doc["step4_legacy_step5_adapter"]["ready"] is True


def test_stage4_status_exposes_step4_reverse_tip_and_risk_signals(tmp_path: Path) -> None:
    fixture = _write_reverse_tip_fixture(tmp_path)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step4_reverse_tip_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    step4_interpretation = status_doc["step4_interpretation"]
    assert step4_interpretation["reverse_tip"]["reverse_tip_attempted"] is True
    assert step4_interpretation["reverse_tip"]["reverse_tip_used"] is True
    assert "reverse_tip_used" in step4_interpretation["risk_signals"]
    assert step4_interpretation["event_reference"]["event_position_source"] == "divstrip_ref"
    assert step4_interpretation["evidence_decision"]["selection_mode"] == "reverse_tip_divstrip"


def test_stage4_status_exposes_step5_geometric_support_domain_summary(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step5_support_domain_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    step5_support_domain = status_doc["step5_geometric_support_domain"]
    assert step5_support_domain["scope"] == "geometric_support_domain"
    assert step5_support_domain["span_window"]["final"]["start_offset_m"] is not None
    assert step5_support_domain["span_window"]["final"]["end_offset_m"] is not None
    assert step5_support_domain["exclusion_context"]["source_priority"] == ["rcsd", "swsd", "road_geometry"]
    assert step5_support_domain["surface_assembly"]["axis_window_present"] is True
    assert step5_support_domain["surface_assembly"]["cross_section_sample_count"] >= 0
    assert step5_support_domain["component_mask_popcount"] > 0


def test_stage4_status_exposes_step6_polygon_assembly_summary(tmp_path: Path) -> None:
    fixture = _write_multibranch_fixture(tmp_path, kind_2=8)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="step6_polygon_assembly_summary",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    step6_polygon_assembly = status_doc["step6_polygon_assembly"]
    assert step6_polygon_assembly["scope"] == "polygon_assembly"
    assert step6_polygon_assembly["polygon_built"] is True
    assert step6_polygon_assembly["geometry_state"] in {"geometry_built", "geometry_built_with_risk"}
    assert status_doc["geometry_state"] == step6_polygon_assembly["geometry_state"]
    assert status_doc["geometry_risk_signals"] == step6_polygon_assembly["geometry_risk_signals"]
    assert status_doc["step6_legacy_step7_adapter"]["required"] is True
    assert status_doc["step6_legacy_step7_adapter"]["ready"] is True
    assert status_doc["step7_acceptance"]["scope"] == "final_acceptance_and_publishing"
    assert status_doc["step7_acceptance"]["decision"]["acceptance_class"] == status_doc["acceptance_class"]
    assert status_doc["step7_acceptance"]["decision"]["visual_review_class"] == status_doc["visual_review_class"]
    assert status_doc["step7_acceptance"]["frozen_constraints_conflict"]["has_conflict"] is False


def test_stage4_marks_main_rcsdnode_out_of_window_as_rejected(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -28.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="main_rcsdnode_out_of_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsdnode_main_out_of_window"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] is False
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] == "out_of_window"
    assert status_doc["coverage_missing_ids"] == []


def test_stage4_infers_primary_rcsdnode_when_direct_mainnodeid_group_is_missing(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -18.0),
        main_rcsdnode_id="910",
        main_rcsdnode_mainnodeid=None,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="infer_local_rcsdnode",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    rcsdnode_link_doc = json.loads(artifacts.rcsdnode_link_json_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert rcsdnode_link_doc["target_node_ids"] == ["910"]
    assert "910" in rcsdnode_link_doc["linked_node_ids"]


def test_stage4_does_not_reject_when_direct_mainnodeid_group_is_missing_and_local_rcsdnode_is_weak(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=8,
        divstrip_mode="not_nearby",
        main_rcsdnode_geometry=Point(0.0, 30.0),
        main_rcsdnode_id="910",
        main_rcsdnode_mainnodeid=None,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="infer_local_rcsdnode_review",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    rcsdnode_link_doc = json.loads(artifacts.rcsdnode_link_json_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rcsdnode_main_out_of_window"
    assert status_doc["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["flow_success"] is True
    assert rcsdnode_link_doc["target_node_ids"] == []
    assert rcsdnode_link_doc["coverage_missing_ids"] == []


def test_stage4_ignores_unselected_outside_rcsd_features_in_case_package(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single")
    rcsdroad_doc = _load_vector_doc(fixture["rcsdroad_path"])
    write_vector(
        fixture["rcsdroad_path"],
        [
            {"properties": feature["properties"], "geometry": shape(feature["geometry"])}
            for feature in rcsdroad_doc["features"]
        ]
        + [
            {
                "properties": {"id": "rc_far_outside", "snodeid": "990", "enodeid": "991", "direction": 2},
                "geometry": LineString([(120.0, 120.0), (160.0, 160.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    rcsdnode_doc = _load_vector_doc(fixture["rcsdnode_path"])
    write_vector(
        fixture["rcsdnode_path"],
        [
            {"properties": feature["properties"], "geometry": shape(feature["geometry"])}
            for feature in rcsdnode_doc["features"]
        ]
        + [
            {"properties": {"id": "990", "mainnodeid": None}, "geometry": Point(120.0, 120.0)},
            {"properties": {"id": "991", "mainnodeid": None}, "geometry": Point(160.0, 160.0)},
        ],
        crs_text="EPSG:3857",
    )

    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="ignore_outside_unselected_rcs",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "reverse_tip_used"


@pytest.mark.parametrize("kind_2", [8, 16])
def test_stage4_accepts_multibranch_event_with_clear_selected_pair(tmp_path: Path, kind_2: int) -> None:
    fixture = _write_multibranch_fixture(tmp_path, kind_2=kind_2)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id=f"multibranch_{kind_2}",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["multibranch"]["multibranch_enabled"] is True
    assert status_doc["multibranch"]["multibranch_n"] >= 3
    assert status_doc["multibranch"]["event_candidate_count"] >= 3
    assert status_doc["multibranch"]["selected_event_index"] == 0
    assert status_doc["multibranch"]["selected_event_branch_ids"] == (
        ["branch_east", "branch_southeast"] if kind_2 == 8 else ["branch_east", "branch_northeast"]
    )
    assert status_doc["multibranch"]["branches_used_count"] == 2


def test_stage4_uses_reverse_tip_when_reverse_retry_improves_branch_positioning(tmp_path: Path) -> None:
    fixture = _write_reverse_tip_fixture(tmp_path)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="reverse_tip",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    node_link_doc = json.loads(artifacts.node_link_json_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "reverse_tip_used"
    assert status_doc["reverse_tip"]["reverse_tip_attempted"] is True
    assert status_doc["reverse_tip"]["reverse_tip_used"] is True
    assert status_doc["reverse_tip"]["reverse_trigger"] == "forward_divstrip_mismatch"
    assert status_doc["reverse_tip"]["position_source_forward"] == "divstrip_primary"
    assert status_doc["reverse_tip"]["position_source_reverse"] == "reverse_tip_divstrip"
    assert status_doc["reverse_tip"]["position_source_final"] == "reverse_tip_divstrip"
    assert "road_east" in node_link_doc["selected_road_ids"]
    assert "road_west" not in node_link_doc["selected_road_ids"]


def test_stage4_accepts_continuous_chain_when_only_single_side_matched(tmp_path: Path) -> None:
    fixture = _write_continuous_chain_fixture(tmp_path)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="continuous_chain",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_stage4_tri_state(status_doc)
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "reverse_tip_used"
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is True
    assert status_doc["continuous_chain"]["chain_component_id"] == "100__200"
    assert status_doc["continuous_chain"]["related_mainnodeids"] == ["200"]
    assert status_doc["continuous_chain"]["chain_node_count"] == 2
    assert status_doc["continuous_chain"]["sequential_ok"] is True


def test_stage4_accepts_complex_kind_128_with_continuous_chain_and_divstrip_priority(tmp_path: Path) -> None:
    fixture = _write_continuous_chain_fixture(
        tmp_path,
        representative_kind_2=128,
        representative_kind=128,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="complex_continuous_chain",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["kind"] == 128
    assert status_doc["kind_2"] == 16
    assert status_doc["kind_resolution"]["complex_junction"] is True
    assert status_doc["kind_resolution"]["kind_resolution_mode"] == "continuous_chain_divstrip_event"
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is True
    assert status_doc["continuous_chain"]["sequential_ok"] is True
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_prioritizes_divstrip_near_road_even_when_far_from_seed(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="road_near_seed_far")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_road_priority",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_rejects_when_divstrip_crs_override_is_invalid(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_invalid_crs",
        divstripzone_crs="EPSG:not-a-crs",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "invalid_crs_or_unprojectable"


def test_stage4_rejects_when_rcsdnode_or_rcsdroad_leaves_drivezone(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single", rcsdroad_outside_drivezone=True)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="outside_drivezone",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_stage4_rejects_when_rcsdnode_leaves_drivezone(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -155.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="rcsdnode_outside_drivezone",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_cover_check_requires_true_geometric_coverage() -> None:
    missing_ids = _cover_check(
        box(0.0, 0.0, 1.0, 1.0),
        [
            ParsedNode(
                feature_index=0,
                properties={},
                geometry=Point(0.5, 0.5),
                node_id="inside",
                mainnodeid="100",
                has_evd="yes",
                is_anchor="no",
                kind_2=8,
                grade_2=1,
            ),
            ParsedNode(
                feature_index=1,
                properties={},
                geometry=Point(1.2, 0.5),
                node_id="near_outside",
                mainnodeid=None,
                has_evd=None,
                is_anchor=None,
                kind_2=None,
                grade_2=None,
            ),
        ],
    )

    assert missing_ids == ["near_outside"]
