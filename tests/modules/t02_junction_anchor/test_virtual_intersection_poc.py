from __future__ import annotations

from dataclasses import replace
import json
import struct
import zlib
from pathlib import Path

import fiona
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_audit_assembler import (
    build_stage3_failure_audit_envelope,
    build_legacy_stage3_audit_envelope_from_step7_assembly,
    stage3_audit_record_dict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step7AcceptanceResult,
    Stage3Step3LegalSpaceResult,
    build_stage3_context,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_context_builder import (
    Stage3LegacyContextInputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_legacy_context_assembly import (
    Stage3LegacyStep7ScalarInputs,
    build_stage3_legacy_step7_assembly_from_settled_inputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_contract_assembly import (
    Stage3SuccessContractFinalDecisionInputs,
    Stage3SuccessContractIdentityInputs,
    Stage3SuccessContractStepSnapshotInputs,
    Stage3SuccessContractAssemblyInputs,
    assemble_stage3_success_contracts,
    build_stage3_success_contract_assembly_inputs,
    build_stage3_success_contract_assembly_inputs_from_results,
    build_stage3_success_step_results,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step3_legal_space import (
    Stage3Step3LegalSpaceInputs,
    build_stage3_step3_legal_space_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step4_rc_semantics import (
    Stage3Step4SemanticsInputs,
    build_stage3_step4_rc_semantics_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_step6_boundary import (
    build_stage3_step6_final_state_snapshot,
    build_stage3_step_snapshot_inputs_from_boundary,
    freeze_stage3_step5_baseline,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_foreign_model import (
    Stage3Step5ForeignModelInputs,
    build_stage3_step5_foreign_model_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    ROOT_CAUSE_LAYER_STEP4,
    ROOT_CAUSE_LAYER_STEP5,
    ROOT_CAUSE_LAYER_STEP6,
    Stage3OfficialReviewDecision,
    VISUAL_REVIEW_V2,
    VISUAL_REVIEW_V4,
    VISUAL_REVIEW_V5,
    derive_stage3_review_metadata,
    stage3_review_metadata_from_step7_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    Stage3AcceptanceHeuristicInputs,
    Stage3LegacyStep7Inputs,
    build_stage3_legacy_step7_assembly,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_snapshot_builder import (
    Stage3SuccessStep3SnapshotInputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    BUSINESS_MATCH_COMPLETE_RCSD,
    BUSINESS_MATCH_PARTIAL_RCSD,
    BUSINESS_MATCH_SWSD_ONLY,
    BranchEvidence,
    ParsedNode,
    ParsedRoad,
    _business_match_class,
    _branch_prefers_compact_local_support,
    _can_soft_exclude_outside_rc,
    _branch_has_minimal_local_road_touch,
    _branch_has_positive_rc_gap,
    _branch_has_local_road_mouth,
    _branch_uses_rc_tip_suppression,
    _audit_row,
    _build_grid,
    _build_positive_negative_rc_groups,
    _build_polygon_support_from_association,
    _covered_foreign_local_road_ids,
    _evaluate_stage3_acceptance_from_inputs,
    _effect_success_acceptance,
    _filter_loaded_features_to_patch,
    _filter_parsed_roads_to_patch,
    _has_structural_side_branch,
    _is_effective_rc_junction_node,
    _is_foreign_local_junction_node,
    _local_road_mouth_polygon_length_m,
    _max_nonmain_branch_polygon_length_m,
    _max_selected_side_branch_covered_length_m,
    _polygon_branch_length_m,
    _regularize_virtual_polygon_geometry,
    _rc_gap_branch_polygon_length_m,
    _resolve_current_patch_id_from_roads,
    _select_main_pair_with_semantic_conflict_guard,
    _select_positive_rc_road_ids,
    _status_from_risks,
    _write_debug_rendered_map,
    run_t02_virtual_intersection_poc,
)

CASE_PACKAGE_ROOT = normalize_runtime_path("/mnt/e/TestData/POC_Data/T02/Anchor")


def _existing_case_root(case_id: str, preferred_root: Path) -> Path:
    preferred_case_root = preferred_root / case_id
    if preferred_case_root.exists():
        return preferred_root
    fallback_case_root = CASE_PACKAGE_ROOT / case_id
    if fallback_case_root.exists():
        return CASE_PACKAGE_ROOT
    return preferred_root


def _required_case_root(case_id: str, preferred_root: Path) -> Path:
    root = _existing_case_root(case_id, preferred_root)
    if not (root / case_id).exists():
        pytest.skip(f"case fixture '{case_id}' is not available in {preferred_root} or {CASE_PACKAGE_ROOT}")
    return root


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _read_png_rgba(path: Path) -> np.ndarray:
    png_bytes = path.read_bytes()
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = None
    height = None
    idat_parts: list[bytes] = []
    while offset < len(png_bytes):
        chunk_length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        payload = png_bytes[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            break
    assert width is not None and height is not None
    raw_rows = zlib.decompress(b"".join(idat_parts))
    row_size = 1 + width * 4
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for row_index in range(height):
        row = raw_rows[row_index * row_size : (row_index + 1) * row_size]
        assert row[0] == 0
        image[row_index] = np.frombuffer(row[1:], dtype=np.uint8).reshape((width, 4))
    return image


def _write_poc_inputs(
    tmp_path: Path,
    *,
    representative_overrides: dict[str, object] | None = None,
    rc_west_inside: bool = True,
    include_rc_group: bool = True,
    include_far_outside_rc: bool = False,
) -> dict[str, Path]:
    representative_props = {
        "id": "100",
        "mainnodeid": "100",
        "has_evd": "yes",
        "is_anchor": "no",
        "kind": 701,
        "kind_2": 2048,
        "grade_2": 1,
    }
    if representative_overrides:
        representative_props.update(representative_overrides)

    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": representative_props,
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": representative_props["is_anchor"],
                    "kind": representative_props["kind"],
                    "kind_2": representative_props["kind_2"],
                    "grade_2": representative_props["grade_2"],
                },
                "geometry": Point(6.0, 2.0),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 60.0)]),
            },
            {
                "properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -60.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (55.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    drivezone_geometry = unary_union(
        [
            box(-12.0, -70.0, 12.0, 70.0),
            box(0.0, -12.0, 75.0, 12.0),
            box(-25.0, -8.0, 0.0, 8.0),
        ]
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": drivezone_geometry}],
        crs_text="EPSG:3857",
    )

    west_geometry = LineString([(-18.0, 0.0), (0.0, 0.0)]) if rc_west_inside else LineString([(-40.0, 30.0), (-20.0, 30.0)])
    rcsdroad_features = [
        {
            "properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2},
            "geometry": LineString([(0.0, 0.0), (0.0, 55.0)]),
        },
        {
            "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2},
            "geometry": LineString([(0.0, -55.0), (0.0, 0.0)]),
        },
        {
            "properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2},
            "geometry": LineString([(0.0, 0.0), (45.0, 0.0)]),
        },
        {
            "properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2},
            "geometry": west_geometry,
        },
    ]
    if include_far_outside_rc:
        rcsdroad_features.append(
            {
                "properties": {"id": "rc_far_noise", "snodeid": "907", "enodeid": "908", "direction": 2},
                "geometry": LineString([(82.0, 5.0), (94.0, 20.0)]),
            }
        )
    write_vector(rcsdroad_path, rcsdroad_features, crs_text="EPSG:3857")

    rcsdnode_features = [
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-18.0 if rc_west_inside else -40.0, 0.0 if rc_west_inside else 30.0)},
    ]
    if include_far_outside_rc:
        rcsdnode_features.extend(
            [
                {"properties": {"id": "907", "mainnodeid": None}, "geometry": Point(82.0, 5.0)},
                {"properties": {"id": "908", "mainnodeid": None}, "geometry": Point(94.0, 20.0)},
            ]
        )
    if include_rc_group:
        rcsdnode_features.insert(0, {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)})
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_compound_center_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": None,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 3,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": None,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 3,
                },
                "geometry": Point(12.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "connector", "snodeid": "101", "enodeid": "100", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "north", "snodeid": "101", "enodeid": "200", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (12.0, 60.0)]),
            },
            {
                "properties": {"id": "south", "snodeid": "300", "enodeid": "101", "direction": 2},
                "geometry": LineString([(12.0, -60.0), (12.0, 0.0)]),
            },
            {
                "properties": {"id": "east", "snodeid": "101", "enodeid": "400", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (60.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union(
                    [
                        box(-6.0, -8.0, 18.0, 8.0),
                        box(4.0, -70.0, 20.0, 70.0),
                        box(12.0, -12.0, 75.0, 12.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_north", "snodeid": "101", "enodeid": "901", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (12.0, 55.0)]),
            },
            {
                "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "101", "direction": 2},
                "geometry": LineString([(12.0, -55.0), (12.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east", "snodeid": "101", "enodeid": "903", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (45.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(12.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(12.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_failure_render_uses_red_mask_and_hatch_style(tmp_path: Path) -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=4,
        grade_2=1,
    )
    local_road = ParsedRoad(
        feature_index=0,
        properties={},
        geometry=LineString([(-6.0, 0.0), (6.0, 0.0)]),
        road_id="road_1",
        snodeid="100",
        enodeid="200",
        direction=2,
    )
    grid = _build_grid(representative_node.geometry, patch_size_m=40.0, resolution_m=1.0)
    drivezone_mask = np.ones((grid.height, grid.width), dtype=bool)
    polygon_geometry = representative_node.geometry.buffer(5.0)

    normal_path = tmp_path / "normal.png"
    rejected_path = tmp_path / "rejected.png"
    review_path = tmp_path / "review.png"

    common_kwargs = {
        "grid": grid,
        "drivezone_mask": drivezone_mask,
        "polygon_geometry": polygon_geometry,
        "representative_node": representative_node,
        "group_nodes": [representative_node],
        "local_nodes": [representative_node],
        "local_roads": [local_road],
        "local_rc_nodes": [],
        "local_rc_roads": [],
        "selected_rc_roads": [],
        "selected_rc_node_ids": set(),
        "excluded_rc_road_ids": set(),
        "excluded_rc_node_ids": set(),
    }

    _write_debug_rendered_map(out_path=normal_path, failure_reason=None, **common_kwargs)
    _write_debug_rendered_map(
        out_path=rejected_path,
        failure_reason="rejected_status:rc_outside_drivezone",
        **common_kwargs,
    )
    _write_debug_rendered_map(
        out_path=review_path,
        failure_reason="review_required_status:stable",
        **common_kwargs,
    )

    normal_image = _read_png_rgba(normal_path)
    rejected_image = _read_png_rgba(rejected_path)
    review_image = _read_png_rgba(review_path)

    rejected_center = rejected_image[rejected_image.shape[0] // 2, rejected_image.shape[1] // 2, :3]
    review_center = review_image[review_image.shape[0] // 2, review_image.shape[1] // 2, :3]
    normal_center = normal_image[normal_image.shape[0] // 2, normal_image.shape[1] // 2, :3]
    background_row = 14
    background_col = rejected_image.shape[1] // 2
    rejected_background = rejected_image[background_row, background_col, :3]
    review_background = review_image[background_row, background_col, :3]
    normal_background = normal_image[background_row, background_col, :3]
    assert tuple(rejected_image[0, rejected_image.shape[1] // 2, :3]) == (164, 0, 0)
    assert tuple(review_image[0, review_image.shape[1] // 2, :3]) == (176, 96, 0)
    assert int(rejected_background[1]) < int(normal_background[1]) - 8
    assert int(rejected_background[2]) < int(normal_background[2]) - 8
    assert int(review_background[1]) < int(normal_background[1]) - 8
    assert int(review_background[2]) < int(normal_background[2]) - 8
    assert int(review_background[1]) > int(rejected_background[1]) + 20
    assert np.any(np.all(review_image[:12, :, :3] == (255, 255, 255), axis=2))
    assert np.any(np.all(rejected_image[:12, :, :3] == (255, 255, 255), axis=2))
    assert tuple(rejected_center) != tuple(normal_center)
    assert tuple(review_center) != tuple(normal_center)


def test_stage3_review_metadata_prefers_status_suffix_over_review_required_keyword() -> None:
    review_metadata = derive_stage3_review_metadata(
        success=False,
        acceptance_class="review_required",
        acceptance_reason="review_required_status:surface_only",
        status="surface_only",
    )
    assert review_metadata.root_cause_layer == ROOT_CAUSE_LAYER_STEP6

    rc_metadata = derive_stage3_review_metadata(
        success=False,
        acceptance_class="review_required",
        acceptance_reason="review_required_status:no_valid_rc_connection",
        status="no_valid_rc_connection",
    )
    assert rc_metadata.root_cause_layer == ROOT_CAUSE_LAYER_STEP4


def _build_step7_test_inputs(
    *,
    acceptance_reason: str,
    acceptance_class: str = "review_required",
    status: str = "stable",
    success: bool = False,
) -> Stage3LegacyStep7Inputs:
    step3_result = build_stage3_step3_legal_space_result(
        Stage3Step3LegalSpaceInputs(
            template_class="single_sided_t_mouth",
            legal_activity_space_geometry=None,
            allowed_drivezone_geometry=None,
            must_cover_group_node_ids={"100"},
            single_sided_corridor_road_ids={"road_east"},
        )
    )
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids=set(),
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_rc_context_ids=set(),
            acceptance_reason=acceptance_reason,
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=2.5,
            foreign_strip_extent_m=3.0,
            foreign_overlap_zero_but_tail_present=True,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=2.5,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            polygon_aspect_ratio=1.6,
            polygon_compactness=0.28,
            polygon_bbox_fill_ratio=0.52,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=2.5,
            foreign_overlap_zero_but_tail_present=True,
        )
    )
    return Stage3LegacyStep7Inputs(
        context=build_stage3_context(
            representative_node_id="100",
            normalized_mainnodeid="100",
            template_class="single_sided_t_mouth",
            representative_kind=701,
            representative_kind_2=2048,
            representative_grade_2=1,
            semantic_junction_set={"100"},
            analysis_member_node_ids={"100"},
            group_node_ids={"100"},
            local_node_ids={"100", "101"},
            local_road_ids={"road_north", "road_east"},
            local_rc_node_ids={"901"},
            local_rc_road_ids={"rc_east"},
            road_branch_ids=("north", "east"),
            analysis_center_xy=(0.0, 0.0),
        ),
        step3_result=step3_result,
        step4_result=step4_result,
        step5_result=step5_result,
        step6_result=step6_result,
        success=success,
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
        status=status,
        representative_has_evd="yes",
        representative_is_anchor="no",
        representative_kind_2=2048,
        business_match_reason="partial_rcsd_context",
        single_sided_t_mouth_corridor_semantic_gap=False,
        final_uncovered_selected_endpoint_node_count=0,
        single_sided_unrelated_opposite_lane_trim_applied=True,
        soft_excluded_rc_corridor_trim_applied=False,
        post_trim_non_target_tail_length_m=2.5,
        foreign_overlap_zero_but_tail_present=True,
        step6_optimizer_events=(),
        selected_rc_node_count=1,
        selected_rc_road_count=1,
        polygon_support_rc_node_count=0,
        polygon_support_rc_road_count=0,
        invalid_rc_node_count=0,
        invalid_rc_road_count=0,
        drivezone_is_empty=False,
        polygon_is_empty=False,
        max_target_group_foreign_semantic_road_overlap_m=0.0,
        max_selected_side_branch_covered_length_m=2.5,
        max_nonmain_branch_polygon_length_m=3.0,
        polygon_aspect_ratio=1.6,
        polygon_compactness=0.28,
        polygon_bbox_fill_ratio=0.52,
    )


def _build_success_contract_input_groups_from_step7_inputs(
    step7_inputs: Stage3LegacyStep7Inputs,
    *,
    scalar_acceptance_reason: str | None = None,
    step4_result=None,
    step5_acceptance_reason: str | None = None,
    step6_geometry_review_reason: str | None = None,
) -> tuple[
    Stage3SuccessContractIdentityInputs,
    Stage3SuccessContractStepSnapshotInputs,
    Stage3SuccessContractFinalDecisionInputs,
]:
    step3_result = step7_inputs.step3_result
    assert step3_result is not None
    step4_result_value = step4_result if step4_result is not None else step7_inputs.step4_result
    step5_result = step7_inputs.step5_result
    assert step5_result is not None
    step6_result = step7_inputs.step6_result
    assert step6_result is not None
    effective_step5_acceptance_reason = (
        step5_acceptance_reason
        if step5_acceptance_reason is not None
        else step7_inputs.acceptance_reason
    )
    return (
        Stage3SuccessContractIdentityInputs(
            representative_node_id=step7_inputs.context.representative_node_id,
            normalized_mainnodeid=step7_inputs.context.normalized_mainnodeid,
            template_class=step7_inputs.context.template_class,
            representative_kind=step7_inputs.context.representative_kind,
            representative_kind_2=step7_inputs.context.representative_kind_2,
            representative_grade_2=step7_inputs.context.representative_grade_2,
            semantic_junction_set=step7_inputs.context.semantic_junction_set,
            analysis_member_node_ids=step7_inputs.context.analysis_member_node_ids,
            group_node_ids=step7_inputs.context.group_node_ids,
            local_node_ids=step7_inputs.context.local_node_ids,
            local_road_ids=step7_inputs.context.local_road_ids,
            local_rc_node_ids=step7_inputs.context.local_rc_node_ids,
            local_rc_road_ids=step7_inputs.context.local_rc_road_ids,
            road_branch_ids=step7_inputs.context.road_branch_ids,
            analysis_center_xy=step7_inputs.context.analysis_center_xy,
        ),
        Stage3SuccessContractStepSnapshotInputs(
            step3_legal_activity_space_geometry=step3_result.allowed_drivezone_geometry,
            step3_allowed_drivezone_geometry=step3_result.allowed_drivezone_geometry,
            step3_must_cover_group_node_ids=step3_result.must_cover_group_node_ids,
            step3_single_sided_corridor_road_ids=step3_result.single_sided_corridor_road_ids,
            step3_hard_boundary_road_ids=step3_result.hard_boundary_road_ids,
            step3_blockers=step3_result.step3_blockers,
            step4_result=step4_result_value,
            step5_foreign_semantic_node_ids=step5_result.foreign_semantic_node_ids,
            step5_foreign_road_arm_corridor_ids=step5_result.foreign_road_arm_corridor_ids,
            step5_foreign_rc_context_ids=step5_result.foreign_rc_context_ids,
            step5_acceptance_reason=effective_step5_acceptance_reason,
            step5_foreign_overlap_metric_m=step5_result.foreign_overlap_metric_m,
            step5_foreign_tail_length_m=step5_result.foreign_tail_length_m,
            step5_foreign_strip_extent_m=step5_result.foreign_strip_extent_m,
            step5_foreign_overlap_zero_but_tail_present=(
                step5_result.foreign_overlap_zero_but_tail_present
            ),
            step5_single_sided_unrelated_opposite_lane_trim_applied=step7_inputs.single_sided_unrelated_opposite_lane_trim_applied,
            step5_soft_excluded_rc_corridor_trim_applied=step7_inputs.soft_excluded_rc_corridor_trim_applied,
            step5_foreign_overlap_by_id={},
            step6_primary_solved_geometry=step6_result.primary_solved_geometry,
            step6_geometry_established=step6_result.geometry_established,
            step6_max_selected_side_branch_covered_length_m=(
                step7_inputs.max_selected_side_branch_covered_length_m
            ),
            step6_selected_node_repair_attempted=step6_result.selected_node_repair_attempted,
            step6_selected_node_repair_applied=step6_result.selected_node_repair_applied,
            step6_selected_node_repair_discarded_due_to_extra_roads=(
                step6_result.selected_node_repair_discarded_due_to_extra_roads
            ),
            step6_introduced_extra_local_road_ids=step6_result.introduced_extra_local_road_ids,
            step6_optimizer_events=step6_result.optimizer_events,
            step6_late_single_sided_branch_cap_cleanup_applied=(
                "late_single_sided_branch_cap_cleanup_applied"
                in step6_result.optimizer_events
            ),
            step6_late_post_soft_overlap_trim_applied=(
                "late_post_soft_overlap_trim_applied"
                in step6_result.optimizer_events
            ),
            step6_late_final_foreign_residue_trim_applied=(
                "late_final_foreign_residue_trim_applied"
                in step6_result.optimizer_events
            ),
            step6_late_single_sided_partial_branch_strip_cleanup_applied=(
                "late_single_sided_partial_branch_strip_cleanup_applied"
                in step6_result.optimizer_events
            ),
            step6_late_single_sided_corridor_mask_cleanup_applied=(
                "late_single_sided_corridor_mask_cleanup_applied"
                in step6_result.optimizer_events
            ),
            step6_late_single_sided_tail_clip_cleanup_applied=(
                "late_single_sided_tail_clip_cleanup_applied"
                in step6_result.optimizer_events
            ),
            step6_polygon_aspect_ratio=step7_inputs.polygon_aspect_ratio,
            step6_polygon_compactness=step7_inputs.polygon_compactness,
            step6_polygon_bbox_fill_ratio=step7_inputs.polygon_bbox_fill_ratio,
            step6_uncovered_selected_endpoint_node_ids=(
                step6_result.remaining_uncovered_selected_endpoint_node_ids
            ),
            step6_foreign_semantic_node_ids=step5_result.foreign_semantic_node_ids,
            step6_foreign_road_arm_corridor_ids=step5_result.foreign_road_arm_corridor_ids,
            step6_foreign_overlap_metric_m=step5_result.foreign_overlap_metric_m,
            step6_foreign_tail_length_m=step7_inputs.post_trim_non_target_tail_length_m,
            step6_foreign_overlap_zero_but_tail_present=step7_inputs.foreign_overlap_zero_but_tail_present,
            step6_geometry_review_reason=(
                step6_geometry_review_reason
                if step6_geometry_review_reason is not None
                else step6_result.geometry_review_reason
            ),
        ),
        Stage3SuccessContractFinalDecisionInputs(
            success=step7_inputs.success,
            acceptance_class=step7_inputs.acceptance_class,
            acceptance_reason=(
                scalar_acceptance_reason
                if scalar_acceptance_reason is not None
                else step7_inputs.acceptance_reason
            ),
            status=step7_inputs.status,
            representative_has_evd=step7_inputs.representative_has_evd,
            representative_is_anchor=step7_inputs.representative_is_anchor,
            representative_kind_2=step7_inputs.representative_kind_2,
            business_match_reason=step7_inputs.business_match_reason,
            single_sided_t_mouth_corridor_semantic_gap=step7_inputs.single_sided_t_mouth_corridor_semantic_gap,
            final_uncovered_selected_endpoint_node_count=step7_inputs.final_uncovered_selected_endpoint_node_count,
            selected_rc_node_count=step7_inputs.selected_rc_node_count,
            selected_rc_road_count=step7_inputs.selected_rc_road_count,
            polygon_support_rc_node_count=step7_inputs.polygon_support_rc_node_count,
            polygon_support_rc_road_count=step7_inputs.polygon_support_rc_road_count,
            invalid_rc_node_count=step7_inputs.invalid_rc_node_count,
            invalid_rc_road_count=step7_inputs.invalid_rc_road_count,
            drivezone_is_empty=step7_inputs.drivezone_is_empty,
            polygon_is_empty=step7_inputs.polygon_is_empty,
        ),
    )


def _build_success_contract_assembly_inputs_from_step7_inputs(
    step7_inputs: Stage3LegacyStep7Inputs,
    *,
    scalar_acceptance_reason: str | None = None,
    step4_result=None,
    step5_acceptance_reason: str | None = None,
    step6_geometry_review_reason: str | None = None,
) -> Stage3SuccessContractAssemblyInputs:
    identity_inputs, step_snapshot_inputs, final_decision_inputs = (
        _build_success_contract_input_groups_from_step7_inputs(
            step7_inputs,
            scalar_acceptance_reason=scalar_acceptance_reason,
            step4_result=step4_result,
            step5_acceptance_reason=step5_acceptance_reason,
            step6_geometry_review_reason=step6_geometry_review_reason,
        )
    )
    return build_stage3_success_contract_assembly_inputs(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=step_snapshot_inputs,
        final_decision_inputs=final_decision_inputs,
    )


def test_stage3_legacy_context_assembly_matches_direct_step7_builder() -> None:
    direct_inputs = _build_step7_test_inputs(
        acceptance_reason="foreign_tail_after_opposite_lane_trim",
        acceptance_class="review_required",
        status="stable",
        success=False,
    )
    direct_assembly = build_stage3_legacy_step7_assembly(direct_inputs)
    assembled = build_stage3_legacy_step7_assembly_from_settled_inputs(
        context_inputs=Stage3LegacyContextInputs(
            representative_node_id="100",
            normalized_mainnodeid="100",
            template_class="single_sided_t_mouth",
            representative_kind=701,
            representative_kind_2=2048,
            representative_grade_2=1,
            semantic_junction_set={"100"},
            analysis_member_node_ids={"100"},
            group_node_ids={"100"},
            local_node_ids={"100", "101"},
            local_road_ids={"road_north", "road_east"},
            local_rc_node_ids={"901"},
            local_rc_road_ids={"rc_east"},
            road_branch_ids=("north", "east"),
            analysis_center_xy=(0.0, 0.0),
        ),
        scalar_inputs=Stage3LegacyStep7ScalarInputs(
            success=False,
            acceptance_class="review_required",
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=2.5,
            foreign_overlap_zero_but_tail_present=True,
            step6_optimizer_events=(),
            selected_rc_node_count=1,
            selected_rc_road_count=1,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=2.5,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=1.6,
            polygon_compactness=0.28,
            polygon_bbox_fill_ratio=0.52,
        ),
        step3_result=direct_inputs.step3_result,
        step4_result=direct_inputs.step4_result,
        step5_result=direct_inputs.step5_result,
        step6_result=direct_inputs.step6_result,
    )
    assert assembled.step7_result == direct_assembly.step7_result
    assert assembled.step4_result == direct_assembly.step4_result
    assert assembled.step5_result == direct_assembly.step5_result
    assert assembled.step6_result == direct_assembly.step6_result


@pytest.mark.parametrize(
    (
        "acceptance_reason",
        "acceptance_class",
        "status",
        "success",
        "expected_acceptance_reason",
        "expected_root_cause_layer",
        "expected_visual_review_class",
    ),
    [
        (
            "stable",
            "accepted",
            "stable",
            True,
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
        (
            "stable_with_incomplete_t_mouth_rc_context",
            "review_required",
            "stable",
            False,
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
        (
            "foreign_tail_after_opposite_lane_trim",
            "review_required",
            "stable",
            False,
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
        (
            "surface_only",
            "review_required",
            "stable",
            False,
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
    ],
)
def test_success_path_contract_assembly_enforces_step5_step6_boundary_semantics(
    acceptance_reason: str,
    acceptance_class: str,
    status: str,
    success: bool,
    expected_acceptance_reason: str,
    expected_root_cause_layer: str,
    expected_visual_review_class: str,
) -> None:
    direct_inputs = _build_step7_test_inputs(
        acceptance_reason=acceptance_reason,
        acceptance_class=acceptance_class,
        status=status,
        success=success,
    )
    assembled = assemble_stage3_success_contracts(
        _build_success_contract_assembly_inputs_from_step7_inputs(direct_inputs)
    )
    assert (
        assembled.step7_assembly.step7_result.acceptance_reason
        == expected_acceptance_reason
    )
    assert assembled.review_metadata.root_cause_layer == expected_root_cause_layer
    assert (
        assembled.review_metadata.visual_review_class
        == expected_visual_review_class
    )
    assert (
        assembled.legacy_stage3_audit_envelope.audit_record.step7.acceptance_reason
        == expected_acceptance_reason
    )


def test_success_path_result_based_assembly_matches_grouped_input_builder() -> None:
    direct_inputs = _build_step7_test_inputs(
        acceptance_reason="foreign_tail_after_opposite_lane_trim",
        acceptance_class="review_required",
        status="stable",
        success=False,
    )
    identity_inputs, step_snapshot_inputs, final_decision_inputs = (
        _build_success_contract_input_groups_from_step7_inputs(direct_inputs)
    )
    step_results = build_stage3_success_step_results(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=step_snapshot_inputs,
    )
    grouped_inputs = build_stage3_success_contract_assembly_inputs(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=step_snapshot_inputs,
        final_decision_inputs=final_decision_inputs,
    )
    assembled_from_grouped = assemble_stage3_success_contracts(grouped_inputs)
    assembled_from_results = assemble_stage3_success_contracts(
        build_stage3_success_contract_assembly_inputs_from_results(
            step_results=step_results,
            final_decision_inputs=final_decision_inputs,
        )
    )
    assert assembled_from_results.step3_result == assembled_from_grouped.step3_result
    assert assembled_from_results.step5_result == assembled_from_grouped.step5_result
    assert assembled_from_results.step6_result == assembled_from_grouped.step6_result
    assert assembled_from_results.step7_assembly.step7_result == assembled_from_grouped.step7_assembly.step7_result
    assert (
        assembled_from_results.canonical_step7_result
        == assembled_from_results.step7_assembly.step7_result
    )
    assert (
        assembled_from_grouped.canonical_step7_result
        == assembled_from_grouped.step7_assembly.step7_result
    )
    assert (
        assembled_from_results.legacy_stage3_audit_envelope.review_metadata
        == assembled_from_grouped.legacy_stage3_audit_envelope.review_metadata
    )
    assert (
        assembled_from_results.legacy_stage3_audit_envelope.official_review_decision
        == assembled_from_grouped.legacy_stage3_audit_envelope.official_review_decision
    )


def test_stage3_boundary_builder_freezes_step5_baseline_and_keeps_step6_tail_state() -> None:
    step5_baseline = freeze_stage3_step5_baseline(
        foreign_semantic_node_ids={"n2", "n1"},
        foreign_road_arm_corridor_ids={"road_b", "road_a"},
        foreign_rc_context_ids={"rc_tail"},
        acceptance_reason="foreign_tail_after_opposite_lane_trim",
        foreign_overlap_metric_m=1.25,
        foreign_tail_length_m=None,
        foreign_strip_extent_m=4.5,
        foreign_overlap_zero_but_tail_present=None,
        single_sided_unrelated_opposite_lane_trim_applied=True,
        soft_excluded_rc_corridor_trim_applied=False,
        foreign_overlap_by_id={"road_b": 1.25},
    )
    step6_final_state = build_stage3_step6_final_state_snapshot(
        primary_solved_geometry=Point(0.0, 0.0).buffer(1.0),
        geometry_established=True,
        max_selected_side_branch_covered_length_m=2.0,
        selected_node_repair_attempted=True,
        selected_node_repair_applied=False,
        selected_node_repair_discarded_due_to_extra_roads=False,
        introduced_extra_local_road_ids={"road_extra"},
        optimizer_events=("late_tail_clip",),
        late_single_sided_branch_cap_cleanup_applied=False,
        late_post_soft_overlap_trim_applied=False,
        late_final_foreign_residue_trim_applied=True,
        late_single_sided_partial_branch_strip_cleanup_applied=False,
        late_single_sided_corridor_mask_cleanup_applied=False,
        late_single_sided_tail_clip_cleanup_applied=True,
        polygon_aspect_ratio=1.2,
        polygon_compactness=0.5,
        polygon_bbox_fill_ratio=0.7,
        uncovered_selected_endpoint_node_ids={"901"},
        foreign_semantic_node_ids={"n3"},
        foreign_road_arm_corridor_ids={"road_c"},
        foreign_overlap_metric_m=0.0,
        foreign_tail_length_m=2.75,
        foreign_overlap_zero_but_tail_present=True,
        geometry_review_reason="foreign_tail_after_opposite_lane_trim",
    )

    step_snapshot_inputs = build_stage3_step_snapshot_inputs_from_boundary(
        step3_inputs=Stage3SuccessStep3SnapshotInputs(
            legal_activity_space_geometry=Point(0.0, 0.0).buffer(5.0),
            allowed_drivezone_geometry=Point(0.0, 0.0).buffer(5.0),
            must_cover_group_node_ids={"100"},
            single_sided_corridor_road_ids={"road_main"},
            hard_boundary_road_ids={"road_block"},
            blockers=(),
        ),
        step4_result=None,
        step5_baseline=step5_baseline,
        step6_final_state=step6_final_state,
    )

    assert step5_baseline.foreign_tail_length_m is None
    assert step5_baseline.foreign_overlap_zero_but_tail_present is None
    assert step_snapshot_inputs.step5_foreign_tail_length_m is None
    assert step_snapshot_inputs.step5_foreign_overlap_zero_but_tail_present is None
    assert step_snapshot_inputs.step5_foreign_semantic_node_ids == ("n1", "n2")
    assert step_snapshot_inputs.step5_foreign_road_arm_corridor_ids == (
        "road_a",
        "road_b",
    )
    assert step_snapshot_inputs.step5_foreign_rc_context_ids == ("rc_tail",)
    assert step_snapshot_inputs.step6_foreign_tail_length_m == 2.75
    assert step_snapshot_inputs.step6_foreign_overlap_zero_but_tail_present is True
    assert step_snapshot_inputs.step6_foreign_semantic_node_ids == ("n3",)
    assert step_snapshot_inputs.step6_foreign_road_arm_corridor_ids == ("road_c",)
    assert "late_tail_clip" in step_snapshot_inputs.step6_optimizer_events


@pytest.mark.parametrize(
    (
        "name",
        "assembly_inputs",
        "expected_acceptance_reason",
        "expected_root_cause_layer",
        "expected_visual_review_class",
    ),
    [
        (
            "step5_wins_over_step4_when_blocking_foreign_baseline_exists",
            _build_success_contract_assembly_inputs_from_step7_inputs(
                _build_step7_test_inputs(
                    acceptance_reason="stable",
                    acceptance_class="accepted",
                    status="stable",
                    success=True,
                ),
                scalar_acceptance_reason="stable",
                step4_result=build_stage3_step4_rc_semantics_result(
                    Stage3Step4SemanticsInputs(
                        required_rc_node_ids={"901"},
                        required_rc_road_ids={"rc_north"},
                        support_rc_node_ids=set(),
                        support_rc_road_ids=set(),
                        excluded_rc_node_ids=set(),
                        excluded_rc_road_ids=set(),
                        selected_rc_endpoint_node_ids={"901"},
                        hard_selected_endpoint_node_ids={"901"},
                        business_match_reason=None,
                        single_sided_t_mouth_corridor_semantic_gap=True,
                        uncovered_selected_endpoint_node_ids={"901"},
                        selected_node_cover_repair_discarded_due_to_extra_roads=True,
                        multi_node_selected_cover_repair_applied=False,
                    )
                ),
                step5_acceptance_reason="stable",
                step6_geometry_review_reason="stable",
            ),
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
        (
            "step5_wins_over_legacy_step4_token",
            _build_success_contract_assembly_inputs_from_step7_inputs(
                _build_step7_test_inputs(
                    acceptance_reason="stable",
                    acceptance_class="accepted",
                    status="stable",
                    success=True,
                ),
                scalar_acceptance_reason="stable_with_incomplete_t_mouth_rc_context",
                step5_acceptance_reason="foreign_tail_after_opposite_lane_trim",
                step6_geometry_review_reason="stable",
            ),
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
        (
            "step5_wins_over_step6_when_blocking_foreign_baseline_exists",
            _build_success_contract_assembly_inputs_from_step7_inputs(
                _build_step7_test_inputs(
                    acceptance_reason="stable",
                    acceptance_class="accepted",
                    status="stable",
                    success=True,
                ),
                scalar_acceptance_reason="stable",
                step5_acceptance_reason="stable",
                step6_geometry_review_reason="surface_only",
            ),
            "foreign_tail_after_opposite_lane_trim",
            ROOT_CAUSE_LAYER_STEP5,
            VISUAL_REVIEW_V4,
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_success_path_audit_envelope_prefers_step_results_over_legacy_tokens(
    name: str,
    assembly_inputs: Stage3SuccessContractAssemblyInputs,
    expected_acceptance_reason: str,
    expected_root_cause_layer: str,
    expected_visual_review_class: str,
) -> None:
    del name
    assembled = assemble_stage3_success_contracts(assembly_inputs)
    assert assembled.step7_assembly.step7_result.acceptance_reason == expected_acceptance_reason
    assert assembled.review_metadata.root_cause_layer == expected_root_cause_layer
    assert assembled.review_metadata.visual_review_class == expected_visual_review_class
    assert (
        assembled.legacy_stage3_audit_envelope.audit_record.step7.root_cause_layer
        == expected_root_cause_layer
    )
    assert (
        assembled.legacy_stage3_audit_envelope.audit_record.step7.visual_review_class
        == expected_visual_review_class
    )


def test_success_path_step7_adapter_prefers_step_results_and_final_decision_without_legacy_scalar_fallback() -> None:
    direct_inputs = _build_step7_test_inputs(
        acceptance_reason="stable",
        acceptance_class="accepted",
        status="stable",
        success=True,
    )
    identity_inputs, step_snapshot_inputs, final_decision_inputs = (
        _build_success_contract_input_groups_from_step7_inputs(
            direct_inputs,
            scalar_acceptance_reason="stable",
            step5_acceptance_reason="foreign_tail_after_opposite_lane_trim",
            step6_geometry_review_reason="stable",
        )
    )
    step_results = build_stage3_success_step_results(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=step_snapshot_inputs,
    )
    assembled = assemble_stage3_success_contracts(
        build_stage3_success_contract_assembly_inputs_from_results(
            step_results=step_results,
            final_decision_inputs=final_decision_inputs,
        )
    )
    assert assembled.step7_assembly.step7_result.acceptance_reason == "foreign_tail_after_opposite_lane_trim"
    assert assembled.review_metadata.root_cause_layer == ROOT_CAUSE_LAYER_STEP5
    assert assembled.review_metadata.visual_review_class == VISUAL_REVIEW_V4


def test_stage3_step3_builder_records_must_cover_corridor_and_blockers() -> None:
    step3_result = build_stage3_step3_legal_space_result(
        Stage3Step3LegalSpaceInputs(
            template_class="single_sided_t_mouth",
            legal_activity_space_geometry={"type": "mock-space"},
            allowed_drivezone_geometry=None,
            must_cover_group_node_ids={"100", "101"},
            single_sided_corridor_road_ids={"road_east", "road_north"},
            hard_boundary_road_ids={"road_blocked"},
            step3_blockers={"drivezone_empty"},
        )
    )
    assert step3_result.template_class == "single_sided_t_mouth"
    assert step3_result.legal_activity_space_geometry == {"type": "mock-space"}
    assert step3_result.must_cover_group_node_ids == frozenset({"100", "101"})
    assert step3_result.single_sided_corridor_road_ids == frozenset(
        {"road_east", "road_north"}
    )
    assert step3_result.hard_boundary_road_ids == frozenset({"road_blocked"})
    assert step3_result.step3_blockers == ("drivezone_empty",)


def test_stage3_step7_builder_derives_review_fields_without_legacy_metadata_dependency() -> None:
    assembly = build_stage3_legacy_step7_assembly(
        _build_step7_test_inputs(
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            acceptance_class="review_required",
            status="stable",
            success=False,
        )
    )
    step7_result = assembly.step7_result
    assert step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP5
    assert step7_result.visual_review_class == VISUAL_REVIEW_V4
    assert step7_result.blocking_step == ROOT_CAUSE_LAYER_STEP5
    assert step7_result.legacy_review_metadata_source == "step7_acceptance_builder_v1"
    assert "root_cause_layer=step5" in step7_result.decision_basis


def test_stage3_audit_envelope_consumes_existing_step7_result_without_reclassification() -> None:
    assembly = build_stage3_legacy_step7_assembly(
        _build_step7_test_inputs(
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            acceptance_class="review_required",
            status="stable",
            success=False,
        )
    )
    envelope = build_legacy_stage3_audit_envelope_from_step7_assembly(
        mainnodeid="100",
        step7_assembly=assembly,
        representative_has_evd="yes",
        representative_is_anchor="no",
        representative_kind_2=2048,
    )
    assert envelope.audit_record.step7 == assembly.step7_result
    assert envelope.audit_record.context is not None
    assert envelope.audit_record.context.normalized_mainnodeid == "100"
    assert envelope.audit_record.step4 == assembly.step4_result
    assert envelope.review_metadata.root_cause_layer == assembly.step7_result.root_cause_layer
    assert envelope.review_metadata.visual_review_class == assembly.step7_result.visual_review_class


def test_stage3_audit_envelope_does_not_synthesize_step_results_from_legacy_signals() -> None:
    inputs = replace(
        _build_step7_test_inputs(
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            acceptance_class="review_required",
            status="stable",
            success=False,
        ),
        step3_result=None,
        step4_result=None,
        step5_result=None,
        step6_result=None,
    )
    assembly = build_stage3_legacy_step7_assembly(inputs)
    assert assembly.step4_result is None
    assert assembly.step5_result is None
    assert assembly.step6_result is None

    envelope = build_legacy_stage3_audit_envelope_from_step7_assembly(
        mainnodeid="100",
        step7_assembly=assembly,
        representative_has_evd="yes",
        representative_is_anchor="no",
        representative_kind_2=2048,
    )

    assert envelope.audit_record.step3 is None
    assert envelope.audit_record.step4 is None
    assert envelope.audit_record.step5 is None
    assert envelope.audit_record.step6 is None
    assert envelope.audit_record.step7 == assembly.step7_result
    assert envelope.review_metadata.root_cause_layer == ROOT_CAUSE_LAYER_STEP5
    assert envelope.review_metadata.visual_review_class == VISUAL_REVIEW_V4


def test_stage3_failure_audit_envelope_does_not_fabricate_step_details_from_failure_reason() -> None:
    envelope = build_stage3_failure_audit_envelope(
        mainnodeid="100",
        acceptance_reason="worker_exception",
        template_class="single_sided_t_mouth",
        status="worker_exception",
        representative_has_evd="yes",
        representative_is_anchor="no",
        representative_kind_2=2048,
    )

    assert envelope.audit_record.step3 is None
    assert envelope.audit_record.step4 is None
    assert envelope.audit_record.step5 is None
    assert envelope.audit_record.step6 is None
    assert envelope.audit_record.context is not None
    assert envelope.audit_record.context.template_class == "single_sided_t_mouth"
    assert envelope.audit_record.step7.mainnodeid == "100"
    assert envelope.audit_record.step7.root_cause_layer == ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
    assert envelope.audit_record.step7.visual_review_class == VISUAL_REVIEW_V5
    assert envelope.review_metadata.root_cause_layer == envelope.audit_record.step7.root_cause_layer
    audit_record_doc = stage3_audit_record_dict(envelope.audit_record)
    assert audit_record_doc["context"]["normalized_mainnodeid"] == "100"
    assert audit_record_doc["context"]["template_class"] == "single_sided_t_mouth"


def test_stage3_success_step_results_keep_step5_baseline_separate_from_step6_late_cleanup_metrics() -> None:
    identity_inputs, step_snapshot_inputs, final_decision_inputs = _build_success_contract_input_groups_from_step7_inputs(
        _build_step7_test_inputs(
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            acceptance_class="review_required",
            status="stable",
            success=False,
        )
    )
    step_results = build_stage3_success_step_results(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=replace(
            step_snapshot_inputs,
            step5_foreign_semantic_node_ids={"baseline_node"},
            step5_foreign_road_arm_corridor_ids={"baseline_road"},
            step5_foreign_overlap_by_id={"baseline_road": 8.5},
            step5_foreign_overlap_metric_m=8.5,
            step6_foreign_semantic_node_ids=(),
            step6_foreign_road_arm_corridor_ids=(),
            step6_foreign_overlap_metric_m=0.0,
            step6_foreign_tail_length_m=0.4,
            step6_foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=("late_final_foreign_residue_trim_applied",),
        ),
    )

    assert step_results.step5_result.foreign_overlap_metric_m == pytest.approx(8.5)
    assert step_results.step5_result.foreign_semantic_node_ids == frozenset({"baseline_node"})
    assert step_results.step5_result.foreign_road_arm_corridor_ids == frozenset({"baseline_road"})
    assert step_results.step5_result.foreign_baseline_established is True
    assert step_results.step5_result.blocking_foreign_established is True
    assert step_results.step5_result.canonical_foreign_established is True
    assert step_results.step5_result.canonical_foreign_reason == "foreign_tail_after_opposite_lane_trim"
    assert step_results.step5_result.foreign_tail_length_m == pytest.approx(2.5)
    assert step_results.step5_result.foreign_overlap_zero_but_tail_present is True
    assert (
        "foreign_overlap:baseline_road=8.500"
        in step_results.step5_result.foreign_overlap_records
    )
    assert (
        "foreign_overlap_metric_m=0.000"
        in step_results.step6_result.foreign_exclusion_validation
    )
    assert (
        "post_trim_non_target_tail_length_m=0.400"
        in step_results.step6_result.foreign_exclusion_validation
    )
    assert (
        "foreign_overlap_zero_but_tail_present"
        not in step_results.step6_result.foreign_exclusion_validation
    )
    assert (
        "late_final_foreign_residue_trim_applied"
        in step_results.step6_result.optimizer_events
    )
    assert step_results.step6_result.remaining_foreign_semantic_node_ids == frozenset()
    assert step_results.step6_result.remaining_foreign_road_arm_corridor_ids == frozenset()

    success_contracts = assemble_stage3_success_contracts(
        build_stage3_success_contract_assembly_inputs_from_results(
            step_results=step_results,
            final_decision_inputs=final_decision_inputs,
        )
    )
    assert success_contracts.step7_assembly.step7_result.post_trim_non_target_tail_length_m == pytest.approx(0.4)
    assert success_contracts.step7_assembly.step7_result.foreign_overlap_zero_but_tail_present is False
    assert success_contracts.step7_assembly.step7_result.step5_foreign_baseline_established is True
    assert success_contracts.step7_assembly.step7_result.step5_foreign_exclusion_established is True
    assert success_contracts.step7_assembly.step7_result.step5_canonical_reason == "foreign_tail_after_opposite_lane_trim"
    assert success_contracts.step7_assembly.step7_result.step5_foreign_residual_present is True


def test_stage3_success_step_results_keep_step4_boundary_separate_from_step6_late_cleanup_selected_state() -> None:
    explicit_step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901", "902"},
            required_rc_road_ids={"rc_north"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901", "902"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids={"902"},
        )
    )
    identity_inputs, step_snapshot_inputs, final_decision_inputs = (
        _build_success_contract_input_groups_from_step7_inputs(
            _build_step7_test_inputs(
                acceptance_reason="surface_only",
                acceptance_class="review_required",
                status="surface_only",
                success=False,
            ),
            step4_result=explicit_step4_result,
        )
    )
    step_results = build_stage3_success_step_results(
        identity_inputs=identity_inputs,
        step_snapshot_inputs=replace(
            step_snapshot_inputs,
            step4_result=explicit_step4_result,
            step6_uncovered_selected_endpoint_node_ids={"902"},
            step6_optimizer_events=(
                "late_single_sided_partial_branch_strip_cleanup_applied",
            ),
            step6_geometry_review_reason="surface_only",
        ),
    )

    assert step_results.step4_result is not None
    assert step_results.step4_result.hard_selected_endpoint_node_ids == frozenset(
        {"901"}
    )
    assert (
        step_results.step6_result.remaining_uncovered_selected_endpoint_node_ids
        == frozenset({"902"})
    )
    assert (
        "late_single_sided_partial_branch_strip_cleanup_applied"
        in step_results.step6_result.optimizer_events
    )

    success_contracts = assemble_stage3_success_contracts(
        build_stage3_success_contract_assembly_inputs_from_results(
            step_results=step_results,
            final_decision_inputs=final_decision_inputs,
        )
    )
    assert success_contracts.legacy_stage3_audit_envelope.audit_record.step4 is not None
    assert (
        success_contracts.legacy_stage3_audit_envelope.audit_record.step4.hard_selected_endpoint_node_ids
        == frozenset({"901"})
    )
    assert (
        success_contracts.legacy_stage3_audit_envelope.audit_record.step6.remaining_uncovered_selected_endpoint_node_ids
        == frozenset({"902"})
    )


def test_stage3_step4_builder_records_required_support_excluded_and_gap() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901", "902"},
            required_rc_road_ids={"rc_north"},
            support_rc_node_ids={"903"},
            support_rc_road_ids={"rc_support"},
            excluded_rc_node_ids={"904"},
            excluded_rc_road_ids={"rc_excluded"},
            selected_rc_endpoint_node_ids={"901", "902"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=True,
            uncovered_selected_endpoint_node_ids={"902"},
            selected_node_cover_repair_discarded_due_to_extra_roads=True,
            multi_node_selected_cover_repair_applied=True,
        )
    )
    assert step4_result.required_rc_node_ids == frozenset({"901", "902"})
    assert step4_result.support_rc_road_ids == frozenset({"rc_support"})
    assert step4_result.excluded_rc_road_ids == frozenset({"rc_excluded"})
    assert step4_result.hard_selected_endpoint_node_ids == frozenset({"901"})
    assert step4_result.uncovered_selected_endpoint_node_ids == frozenset({"902"})
    assert step4_result.selected_node_cover_repair_discarded_due_to_extra_roads is True
    assert step4_result.multi_node_selected_cover_repair_applied is True
    assert "single_sided_t_mouth_corridor_semantic_gap" in step4_result.stage3_rc_gap_records
    assert (
        "uncovered_selected_endpoint_node_ids=902"
        in step4_result.stage3_rc_gap_records
    )
    assert (
        "selected_node_cover_repair_discarded_due_to_extra_roads"
        in step4_result.stage3_rc_gap_records
    )
    assert "multi_node_selected_cover_repair_applied" in step4_result.stage3_rc_gap_records


def test_stage3_acceptance_wrapper_prefers_explicit_step4_boundary_result_over_legacy_bool_inputs() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_north"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=True,
            uncovered_selected_endpoint_node_ids={"901"},
            selected_node_cover_repair_discarded_due_to_extra_roads=True,
            multi_node_selected_cover_repair_applied=False,
        )
    )
    decision = _evaluate_stage3_acceptance_from_inputs(
        Stage3AcceptanceHeuristicInputs(
            status="stable",
            review_mode=False,
            template_class="single_sided_t_mouth",
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            associated_rc_road_count=1,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            min_invalid_rc_distance_to_center_m=None,
            local_rc_road_count=1,
            local_rc_node_count=1,
            effective_local_rc_node_count=1,
            local_road_count=2,
            local_node_count=2,
            connected_rc_group_count=1,
            nonmain_branch_connected_rc_group_count=0,
            negative_rc_group_count=0,
            positive_rc_group_count=0,
            road_branch_count=1,
            has_structural_side_branch=True,
            max_nonmain_edge_branch_road_support_m=0.0,
            max_nonmain_edge_branch_rc_support_m=0.0,
            excluded_local_rc_road_count=0,
            excluded_local_rc_node_count=0,
            covered_extra_local_node_count=0,
            covered_extra_local_road_count=0,
            has_main_edge_only_branch=False,
            representative_kind_2=2048,
            effective_associated_rc_node_count=0,
            associated_nonzero_mainnode_count=0,
            final_selected_node_cover_repair_discarded_due_to_extra_roads=False,
            single_sided_t_mouth_corridor_pattern_detected=True,
            single_sided_t_mouth_corridor_semantic_gap=True,
            multi_node_selected_cover_repair_applied=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            step4_result=step4_result,
        )
    )
    assert decision.effect_success is False
    assert decision.acceptance_class == "review_required"
    assert decision.acceptance_reason == "stable_with_incomplete_t_mouth_rc_context"


def test_stage3_step5_builder_records_foreign_sets_and_metrics() -> None:
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids={"2001"},
            foreign_road_arm_corridor_ids={"road_tail"},
            foreign_rc_context_ids={"rc_foreign"},
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            foreign_overlap_metric_m=1.25,
            foreign_tail_length_m=2.75,
            foreign_strip_extent_m=6.5,
            foreign_overlap_zero_but_tail_present=True,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={"road_tail": 1.25},
        )
    )
    assert step5_result.foreign_subtype == "tail_after_opposite_lane_trim"
    assert step5_result.foreign_road_arm_corridor_ids == frozenset({"road_tail"})
    assert "post_trim_non_target_tail_length_m=2.750" in step5_result.foreign_tail_records
    assert "foreign_overlap:road_tail=1.250" in step5_result.foreign_overlap_records


def test_stage3_step6_builder_records_optimizer_and_residual_validation() -> None:
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=True,
            selected_node_repair_applied=True,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids={"foreign_road"},
            optimizer_events=(
                "late_single_sided_branch_cap_cleanup_applied",
                "late_final_foreign_residue_trim_applied",
            ),
            polygon_aspect_ratio=1.8,
            polygon_compactness=0.31,
            polygon_bbox_fill_ratio=0.57,
            uncovered_selected_endpoint_node_ids={"901"},
            foreign_semantic_node_ids={"foreign_node"},
            foreign_road_arm_corridor_ids={"foreign_road"},
            foreign_overlap_metric_m=1.5,
            foreign_tail_length_m=2.0,
            foreign_overlap_zero_but_tail_present=True,
        )
    )
    assert "late_single_sided_branch_cap_cleanup_applied" in step6_result.optimizer_events
    assert (
        "final_uncovered_selected_endpoint_node_ids=901"
        in step6_result.must_cover_validation
    )
    assert step6_result.selected_node_repair_attempted is True
    assert step6_result.selected_node_repair_applied is True
    assert step6_result.introduced_extra_local_road_ids == ("foreign_road",)
    assert (
        "foreign_road_arm_corridor_ids=foreign_road"
        in step6_result.foreign_exclusion_validation
    )
    assert (
        "introduced_extra_local_road_ids=foreign_road"
        in step6_result.foreign_exclusion_validation
    )


def test_stage3_step7_prefers_explicit_step5_result_over_legacy_reason() -> None:
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids={"foreign_node"},
            foreign_road_arm_corridor_ids={"foreign_road"},
            foreign_rc_context_ids=set(),
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=2.5,
            foreign_strip_extent_m=3.0,
            foreign_overlap_zero_but_tail_present=True,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=None,
            step5_result=step5_result,
            step6_result=None,
            success=False,
            acceptance_class="review_required",
            acceptance_reason="outside_rc_gap_requires_review",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP5
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V4
    assert assembly.step7_result.blocking_step == ROOT_CAUSE_LAYER_STEP5
    assert assembly.step7_result.acceptance_reason == "foreign_tail_after_opposite_lane_trim"
    assert "step5_result_override_applied" in assembly.step5_signals


def test_stage3_step7_prefers_explicit_step4_result_over_legacy_counts() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids=set(),
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids={"foreign_node"},
            foreign_road_arm_corridor_ids={"foreign_road"},
            foreign_rc_context_ids=set(),
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            geometry_review_reason="stable_single_sided_mouth_geometry_requires_review",
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.step4_required_rc_established is True
    assert "required_rc_node_count=1" in assembly.step7_result.decision_basis
    assert "foreign_road_arm_corridor_count=1" in assembly.step7_result.decision_basis


def test_stage3_step7_prefers_explicit_step3_result_over_legacy_drivezone_flag() -> None:
    step3_result = build_stage3_step3_legal_space_result(
        Stage3Step3LegalSpaceInputs(
            template_class="single_sided_t_mouth",
            legal_activity_space_geometry=None,
            allowed_drivezone_geometry=None,
            must_cover_group_node_ids={"100"},
            single_sided_corridor_road_ids={"road_east"},
            step3_blockers={"drivezone_empty"},
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=step3_result,
            step4_result=None,
            step5_result=None,
            step6_result=None,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.step3_legal_space_established is False
    assert assembly.step7_result.root_cause_layer == "step3"
    assert assembly.step7_result.acceptance_reason == "drivezone_empty"
    assert "drivezone_empty" in assembly.step7_result.decision_basis
    assert "step3_result_override_applied" in assembly.step3_signals


def test_stage3_step7_prefers_explicit_step4_boundary_result_over_legacy_stable_reason() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=True,
            uncovered_selected_endpoint_node_ids={"901"},
            selected_node_cover_repair_discarded_due_to_extra_roads=True,
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=None,
            step6_result=None,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP4
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert (
        assembly.step7_result.acceptance_reason
        == "stable_with_incomplete_t_mouth_rc_context"
    )
    assert "step4_result_override_applied" in assembly.step4_signals


def test_stage3_step7_prefers_explicit_step6_result_over_legacy_polygon_empty() -> None:
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            optimizer_events=(
                "late_post_soft_overlap_trim_applied",
            ),
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.4,
            polygon_bbox_fill_ratio=0.6,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            geometry_review_reason="stable_single_sided_mouth_geometry_requires_review",
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=None,
            step5_result=None,
            step6_result=step6_result,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=True,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.step6_geometry_established is True
    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP6
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert assembly.step7_result.blocking_step == ROOT_CAUSE_LAYER_STEP6
    assert (
        assembly.step7_result.acceptance_reason
        == "stable_single_sided_mouth_geometry_requires_review"
    )
    assert "late_post_soft_overlap_trim_applied" in assembly.step6_optimizer_events
    assert "step6_result_override_applied" in assembly.step6_optimizer_events


def test_stage3_step7_does_not_promote_step5_from_late_cleanup_flags_when_step5_result_is_non_foreign() -> None:
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_rc_context_ids=set(),
            acceptance_reason="stable",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            polygon_aspect_ratio=1.1,
            polygon_compactness=0.5,
            polygon_bbox_fill_ratio=0.7,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=None,
            step5_result=step5_result,
            step6_result=step6_result,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=True,
            post_trim_non_target_tail_length_m=3.0,
            foreign_overlap_zero_but_tail_present=True,
            step6_optimizer_events=(
                "late_single_sided_branch_cap_cleanup_applied",
                "late_post_soft_overlap_trim_applied",
                "late_final_foreign_residue_trim_applied",
                "late_single_sided_partial_branch_strip_cleanup_applied",
                "late_single_sided_corridor_mask_cleanup_applied",
                "late_single_sided_tail_clip_cleanup_applied",
            ),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.acceptance_reason == "stable"
    assert assembly.step7_result.root_cause_layer != ROOT_CAUSE_LAYER_STEP5
    assert assembly.step7_result.visual_review_class != VISUAL_REVIEW_V4
    assert "late_final_foreign_residue_trim_applied" not in assembly.step6_optimizer_events


def test_stage3_step7_late_cleanup_provenance_does_not_override_explicit_step4_root_cause() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=True,
            uncovered_selected_endpoint_node_ids={"901"},
            selected_node_cover_repair_discarded_due_to_extra_roads=True,
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_rc_context_ids=set(),
            acceptance_reason="stable",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            optimizer_events=(
                "late_single_sided_branch_cap_cleanup_applied",
                "late_post_soft_overlap_trim_applied",
                "late_final_foreign_residue_trim_applied",
            ),
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.4,
            polygon_bbox_fill_ratio=0.6,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            geometry_review_reason="stable",
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP4
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert (
        assembly.step7_result.acceptance_reason
        == "stable_with_incomplete_t_mouth_rc_context"
    )
    assert "step4_result_override_applied" in assembly.step4_signals
    assert "late_final_foreign_residue_trim_applied" in assembly.step6_optimizer_events


def test_stage3_step7_late_cleanup_provenance_does_not_override_explicit_step5_root_cause() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="partial_rcsd_context",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids=set(),
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids={"foreign_node"},
            foreign_road_arm_corridor_ids={"foreign_road"},
            foreign_rc_context_ids=set(),
            acceptance_reason="foreign_tail_after_opposite_lane_trim",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=2.4,
            foreign_strip_extent_m=2.4,
            foreign_overlap_zero_but_tail_present=True,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=0.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            optimizer_events=(
                "late_single_sided_branch_cap_cleanup_applied",
                "late_post_soft_overlap_trim_applied",
                "late_final_foreign_residue_trim_applied",
                "late_single_sided_tail_clip_cleanup_applied",
            ),
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.4,
            polygon_bbox_fill_ratio=0.6,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids={"foreign_node"},
            foreign_road_arm_corridor_ids={"foreign_road"},
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=2.4,
            foreign_overlap_zero_but_tail_present=True,
            geometry_review_reason="stable",
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=0,
            selected_rc_road_count=0,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            polygon_aspect_ratio=None,
            polygon_compactness=None,
            polygon_bbox_fill_ratio=None,
        )
    )
    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP5
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V4
    assert assembly.step7_result.acceptance_reason == "foreign_tail_after_opposite_lane_trim"
    assert assembly.step7_result.step5_foreign_baseline_established is True
    assert assembly.step7_result.step5_foreign_exclusion_established is True
    assert assembly.step7_result.step5_foreign_subtype == "tail_after_opposite_lane_trim"
    assert "step5_result_override_applied" in assembly.step5_signals
    assert "late_single_sided_tail_clip_cleanup_applied" in assembly.step6_optimizer_events


def test_stage3_step7_overlap_only_step5_result_stays_step6_review_when_step5_canonical_not_established() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="matched_complete_rcsd_junction",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids=set(),
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            foreign_overlap_metric_m=0.9,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=10.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={"road-1": 0.9},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=8.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            optimizer_events=("late_post_soft_overlap_trim_applied",),
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.16,
            polygon_bbox_fill_ratio=0.28,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.9,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            geometry_review_reason="stable_single_sided_mouth_geometry_requires_review",
        )
    )
    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=False,
            acceptance_class="review_required",
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=1,
            selected_rc_road_count=2,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.9,
            max_selected_side_branch_covered_length_m=8.0,
            max_nonmain_branch_polygon_length_m=8.0,
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.16,
            polygon_bbox_fill_ratio=0.28,
        )
    )

    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP6
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert assembly.step7_result.acceptance_reason == "stable_single_sided_mouth_geometry_requires_review"
    assert assembly.step7_result.step5_foreign_baseline_established is True
    assert assembly.step7_result.step5_foreign_exclusion_established is False
    assert assembly.step7_result.step5_canonical_reason is None
    assert assembly.step7_result.step5_foreign_residual_present is True
    assert assembly.step7_result.step5_foreign_subtype == "semantic_road_overlap"
    assert "step5_result_override_applied" not in assembly.step5_signals
    assert "step5_residual_foreign_present" not in assembly.step5_signals
    assert "step5_baseline_established" in assembly.step5_signals
    assert "step5_baseline_retained_but_nonblocking" in assembly.step5_signals
    assert "step5_result_provenance_only" in assembly.step5_signals
    assert "step5_residual_present_but_nonblocking" in assembly.step5_signals


def test_stage3_step7_soft_trim_semantic_overlap_stays_as_step4_review_when_nonblocking() -> None:
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="outside_rc_gap_requires_review",
            foreign_overlap_metric_m=2.2,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=6.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            foreign_overlap_by_id={"road-1": 2.2},
        )
    )

    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="861032",
                normalized_mainnodeid="861032",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=None,
            step5_result=step5_result,
            step6_result=None,
            success=False,
            acceptance_class="review_required",
            acceptance_reason="outside_rc_gap_requires_review",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=2,
            selected_rc_road_count=2,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=2.2,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=6.0,
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.4,
            polygon_bbox_fill_ratio=0.6,
        )
    )

    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP4
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert assembly.step7_result.acceptance_reason == "outside_rc_gap_requires_review"
    assert assembly.step7_result.step5_foreign_baseline_established is True
    assert assembly.step7_result.step5_foreign_exclusion_established is False
    assert assembly.step7_result.step5_canonical_reason is None
    assert assembly.step7_result.step5_foreign_subtype == "semantic_road_overlap"
    assert "step5_result_override_applied" not in assembly.step5_signals
    assert "step5_baseline_established" in assembly.step5_signals
    assert "step5_baseline_retained_but_nonblocking" in assembly.step5_signals
    assert "step5_result_provenance_only" in assembly.step5_signals


def test_stage3_step7_step5_baseline_cleared_by_step6_final_state_falls_back_to_step6_review() -> None:
    step4_result = build_stage3_step4_rc_semantics_result(
        Stage3Step4SemanticsInputs(
            required_rc_node_ids={"901"},
            required_rc_road_ids={"rc_east"},
            support_rc_node_ids=set(),
            support_rc_road_ids=set(),
            excluded_rc_node_ids=set(),
            excluded_rc_road_ids=set(),
            selected_rc_endpoint_node_ids={"901"},
            hard_selected_endpoint_node_ids={"901"},
            business_match_reason="matched_complete_rcsd_junction",
            single_sided_t_mouth_corridor_semantic_gap=False,
            uncovered_selected_endpoint_node_ids=set(),
        )
    )
    step5_result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            foreign_overlap_metric_m=0.9,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=10.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={"road-1": 0.9},
        )
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=None,
            geometry_established=True,
            max_selected_side_branch_covered_length_m=8.0,
            selected_node_repair_attempted=False,
            selected_node_repair_applied=False,
            selected_node_repair_discarded_due_to_extra_roads=False,
            introduced_extra_local_road_ids=set(),
            optimizer_events=("late_post_soft_overlap_trim_applied",),
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.16,
            polygon_bbox_fill_ratio=0.28,
            uncovered_selected_endpoint_node_ids=set(),
            foreign_semantic_node_ids=set(),
            foreign_road_arm_corridor_ids=set(),
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            geometry_review_reason="stable_single_sided_mouth_geometry_requires_review",
        )
    )

    assembly = build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context(
                representative_node_id="100",
                normalized_mainnodeid="100",
                template_class="single_sided_t_mouth",
                representative_kind=701,
                representative_kind_2=2048,
                representative_grade_2=1,
            ),
            step3_result=None,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=False,
            acceptance_class="review_required",
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            status="stable",
            representative_has_evd="yes",
            representative_is_anchor="no",
            representative_kind_2=2048,
            business_match_reason=None,
            single_sided_t_mouth_corridor_semantic_gap=False,
            final_uncovered_selected_endpoint_node_count=0,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            step6_optimizer_events=(),
            selected_rc_node_count=1,
            selected_rc_road_count=2,
            polygon_support_rc_node_count=0,
            polygon_support_rc_road_count=0,
            invalid_rc_node_count=0,
            invalid_rc_road_count=0,
            drivezone_is_empty=False,
            polygon_is_empty=False,
            max_target_group_foreign_semantic_road_overlap_m=0.0,
            max_selected_side_branch_covered_length_m=8.0,
            max_nonmain_branch_polygon_length_m=8.0,
            polygon_aspect_ratio=1.2,
            polygon_compactness=0.16,
            polygon_bbox_fill_ratio=0.28,
        )
    )

    assert assembly.step7_result.root_cause_layer == ROOT_CAUSE_LAYER_STEP6
    assert assembly.step7_result.visual_review_class == VISUAL_REVIEW_V2
    assert (
        assembly.step7_result.acceptance_reason
        == "stable_single_sided_mouth_geometry_requires_review"
    )
    assert assembly.step7_result.step5_foreign_baseline_established is True
    assert assembly.step7_result.step5_foreign_exclusion_established is False
    assert assembly.step7_result.step5_canonical_reason is None
    assert assembly.step7_result.step5_foreign_residual_present is False
    assert assembly.step7_result.step5_foreign_subtype == "semantic_road_overlap"
    assert "step5_result_override_applied" not in assembly.step5_signals
    assert "step5_baseline_established" in assembly.step5_signals
    assert "step5_baseline_retained_but_nonblocking" in assembly.step5_signals
    assert "step5_baseline_cleared_by_step6_final_state" in assembly.step5_signals
    assert "step5_result_provenance_only" in assembly.step5_signals


def test_audit_row_review_fields_remain_consistent_for_foreign_tail_reason() -> None:
    row = _audit_row(
        scope="virtual_intersection_poc",
        status="warning",
        reason="foreign_tail_after_opposite_lane_trim",
        detail="tail remains after opposite lane trim",
        mainnodeid="100",
        feature_id="100",
    )
    assert row["root_cause_layer"] == ROOT_CAUSE_LAYER_STEP5
    assert row["visual_review_class"] == VISUAL_REVIEW_V4


def _write_support_decoupling_inputs(tmp_path: Path) -> dict[str, Path]:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)

    write_vector(
        paths["rcsdroad_path"],
        [
            {
                "properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 55.0)]),
            },
            {
                "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -55.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east_primary", "snodeid": "100", "enodeid": "905", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (20.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east_secondary", "snodeid": "905", "enodeid": "906", "direction": 2},
                "geometry": LineString([(20.0, 0.0), (44.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        paths["rcsdnode_path"],
        [
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "905", "mainnodeid": None}, "geometry": Point(20.0, 0.0)},
            {"properties": {"id": "906", "mainnodeid": None}, "geometry": Point(44.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return paths


def _load_case_package_inputs(case_id: str, *, case_root: Path = CASE_PACKAGE_ROOT) -> dict[str, Path]:
    case_dir = case_root / case_id
    return {
        "nodes_path": case_dir / "nodes.gpkg",
        "roads_path": case_dir / "roads.gpkg",
        "drivezone_path": case_dir / "drivezone.gpkg",
        "rcsdroad_path": case_dir / "rcsdroad.gpkg",
        "rcsdnode_path": case_dir / "rcsdnode.gpkg",
    }


def _run_case_package_case(
    tmp_path: Path,
    case_id: str,
    *,
    case_root: Path = CASE_PACKAGE_ROOT,
) -> tuple[object, dict, Path]:
    render_root = tmp_path / "renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid=case_id,
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **_load_case_package_inputs(case_id, case_root=case_root),
    )
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    return artifacts, status_doc, render_root


def _load_case_nodes_by_id(case_id: str) -> dict[str, Point]:
    doc = _load_vector_doc(CASE_PACKAGE_ROOT / case_id / "nodes.gpkg")
    return {
        str(feature["properties"]["id"]): shape(feature["geometry"])
        for feature in doc["features"]
    }


def _load_case_roads_by_id(case_id: str) -> dict[str, LineString]:
    doc = _load_vector_doc(CASE_PACKAGE_ROOT / case_id / "roads.gpkg")
    return {
        str(feature["properties"]["id"]): shape(feature["geometry"])
        for feature in doc["features"]
    }


def _load_case_rcsd_nodes_by_id(case_id: str) -> dict[str, Point]:
    doc = _load_vector_doc(CASE_PACKAGE_ROOT / case_id / "rcsdnode.gpkg")
    return {
        str(feature["properties"]["id"]): shape(feature["geometry"])
        for feature in doc["features"]
    }


def _load_case_rcsd_roads_by_id(case_id: str) -> dict[str, LineString]:
    doc = _load_vector_doc(CASE_PACKAGE_ROOT / case_id / "rcsdroad.gpkg")
    return {
        str(feature["properties"]["id"]): shape(feature["geometry"])
        for feature in doc["features"]
    }


def test_virtual_intersection_poc_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="missing", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "mainnodeid_not_found"


def test_virtual_intersection_poc_fails_when_target_out_of_scope(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"kind_2": 1})
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"


def test_virtual_intersection_poc_writes_debug_render_for_target_out_of_scope_failure(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"kind_2": 1})
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"
    assert status_doc["output_files"]["rendered_map_png"] == str(render_root / "100.png")


def test_virtual_intersection_poc_rejects_existing_anchor_status_for_explicit_case(tmp_path: Path) -> None:
    for anchor_status in ("yes", "fail1"):
        paths = _write_poc_inputs(tmp_path / anchor_status, representative_overrides={"is_anchor": anchor_status})
        artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
        assert artifacts.success is False
        status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
        assert status_doc["status"] == "mainnodeid_out_of_scope"
        assert status_doc["acceptance_class"] == "rejected"


def test_virtual_intersection_poc_generates_polygon_branch_evidence_and_rc_associations(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon_feature = polygon_doc["features"][0]
    polygon = shape(polygon_feature["geometry"])
    assert polygon.area > 100.0
    assert polygon.geom_type == "Polygon"
    assert len(polygon.interiors) == 0
    assert polygon_feature["properties"]["mainnodeid"] == "100"
    assert polygon_feature["properties"]["kind"] == 701
    assert polygon.buffer(0.5).covers(Point(6.0, 2.0))
    assert polygon.buffer(0.5).covers(Point(0.0, 55.0))
    assert polygon.buffer(0.5).covers(Point(0.0, -55.0))
    assert polygon.buffer(0.5).covers(Point(45.0, 0.0))

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert len(road_branches) >= 3
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2
    assert any(item["evidence_level"] in {"arm_partial", "arm_full_rc"} for item in road_branches if not item["is_main_direction"])

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"
    assert status_doc["representative_kind"] == 701

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert {"rc_north", "rc_south", "rc_east"} <= associated_road_ids
    assert "rc_west" not in associated_road_ids

    associated_nodes_doc = _load_vector_doc(artifacts.associated_rcsdnode_path)
    associated_node_ids = {feature["properties"]["id"] for feature in associated_nodes_doc["features"]}
    assert {"100", "901", "902", "903"} <= associated_node_ids


def test_virtual_intersection_poc_writes_debug_render_to_explicit_root(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is True
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()


def test_virtual_intersection_poc_errors_when_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "foreign_outside_drivezone_soft_excluded"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V4
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["business_match_reason"] == "partial_rcsd_context_after_excluding_incompatible_rcsd"
    assert status_doc["counts"]["excluded_rcsdroad_count"] >= 1


def test_virtual_intersection_poc_writes_debug_render_when_outside_rc_is_soft_excluded(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "foreign_outside_drivezone_soft_excluded"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V4
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["output_files"]["rendered_map_png"] == str(render_root / "100.png")


def test_virtual_intersection_poc_review_mode_soft_excludes_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        review_mode=True,
        **paths,
    )
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["review_mode"] is True
    assert "review_rc_outside_drivezone_excluded" in status_doc["risks"]
    assert status_doc["counts"]["review_excluded_rcsdroad_count"] >= 1

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "review_rc_outside_drivezone_excluded" for row in audit_doc)

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_west" not in associated_road_ids


def test_virtual_intersection_poc_writes_failure_styled_render_when_effect_not_accepted(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        review_mode=True,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["success"] is False
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    image = _read_png_rgba(artifacts.rendered_map_path)
    background = image[14, image.shape[1] // 2]
    assert int(background[0]) > int(background[1]) + 5
    assert int(background[1]) > int(background[2]) + 20
    assert np.any(np.all(image[:12, :, :3] == (255, 255, 255), axis=2))


def _assert_case_review_required_v2(
    status_doc: dict,
    *,
    allowed_statuses: set[str] | None = None,
    allowed_reasons: set[str] | None = None,
) -> None:
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    if allowed_statuses is not None:
        assert status_doc["status"] in allowed_statuses
    if allowed_reasons is not None:
        assert status_doc["acceptance_reason"] in allowed_reasons


def _assert_case_rejected_v4(
    status_doc: dict,
    *,
    allowed_statuses: set[str] | None = None,
    allowed_reasons: set[str] | None = None,
) -> None:
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V4
    if allowed_statuses is not None:
        assert status_doc["status"] in allowed_statuses
    if allowed_reasons is not None:
        assert status_doc["acceptance_reason"] in allowed_reasons


def test_case_package_698330_accepts_single_sided_trimmed_t_mouth_without_opposite_lane_overlap(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "698330")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={
            "stable_single_sided_mouth_geometry_requires_review",
            "stable_with_incomplete_t_mouth_rc_context",
        },
    )
    assert status_doc["counts"]["max_target_group_foreign_semantic_road_overlap_m"] <= 1.0
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()
    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("698330")
    roads = _load_case_roads_by_id("698330")
    assert polygon.buffer(0.5).covers(nodes["698330"])
    assert polygon.buffer(0.5).covers(nodes["709749"]) is False
    assert polygon.buffer(0.5).covers(nodes["607669479"]) is False
    assert polygon.buffer(0.5).covers(nodes["709743"]) is False
    assert abs(polygon.intersection(roads["621944468"]).length) > 0.5
    assert abs(polygon.intersection(roads["972225"]).length) <= 0.5
    assert abs(polygon.intersection(roads["972227"]).length) > 0.5


def test_case_package_699885_accepts_effect_success(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "699885")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"no_valid_rc_connection"},
        allowed_reasons={"rc_gap_without_connected_local_rcsd_evidence"},
    )
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()


def test_case_package_705817_accepts_effect_success(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "705817")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"no_valid_rc_connection"},
        allowed_reasons={"rc_gap_with_nonmain_branch_polygon_coverage"},
    )
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()


def test_case_package_706389_accepts_t_mouth_rc_context_without_covering_foreign_semantic_junction(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "706389")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={
            "stable_single_sided_mouth_geometry_requires_review",
            "stable_with_incomplete_t_mouth_rc_context",
        },
    )
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()

    nodes = _load_case_nodes_by_id("706389")
    roads = _load_case_roads_by_id("706389")
    rcsd_nodes = _load_case_rcsd_nodes_by_id("706389")
    assert status_doc["counts"]["associated_rcsdroad_count"] >= 4
    assert status_doc["counts"]["associated_rcsdnode_count"] >= 8
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert status_doc["template_class"] == "single_sided_t_mouth"
    assert not status_doc["excluded_negative_rc_groups"]
    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    assert polygon.buffer(0.5).covers(nodes["706389"])
    assert polygon.buffer(0.5).covers(nodes["522607717"]) is False
    assert polygon.buffer(0.5).covers(rcsd_nodes["5395732498090127"])
    assert polygon.buffer(0.5).covers(rcsd_nodes["5395732498090139"])
    assert abs(polygon.intersection(roads["627726937"]).length) <= 0.5
    assert abs(polygon.intersection(roads["527732809"]).length) <= 0.5


def test_case_package_707324_accepts_surface_only_when_local_rcsd_data_is_absent(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "707324")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"surface_only"},
        allowed_reasons={"surface_only_without_any_local_rcsd_data"},
    )


def test_case_package_707267_accepts_compact_near_center_outside_rc_after_trim(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "707267")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"weak_branch_support"},
        allowed_reasons={"outside_rc_gap_requires_review"},
    )
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert status_doc["template_class"] == "center_junction"
    assert status_doc["counts"]["associated_rcsdroad_count"] >= 2
    assert status_doc["counts"]["associated_rcsdnode_count"] >= 2


def test_case_package_584253_preserves_compact_kind4_polygon_and_associates_positive_rc_roads(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "584253")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"no_valid_rc_connection"},
        allowed_reasons={"rc_gap_with_nonmain_branch_polygon_coverage"},
    )
    assert status_doc["counts"]["associated_rcsdroad_count"] == 2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_724123_accepts_trimmed_single_sided_corridor_without_opposite_lane_overlap(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "724123")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )
    assert status_doc["counts"]["max_target_group_foreign_semantic_road_overlap_m"] <= 1.0

    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("724123")
    roads = _load_case_roads_by_id("724123")
    assert polygon.buffer(0.5).covers(nodes["724123"])
    assert polygon.buffer(0.5).covers(nodes["723406"]) is False
    assert polygon.buffer(0.5).covers(nodes["14445461"]) is False
    assert abs(polygon.intersection(roads["1024939"]).length) <= 0.5


def test_case_package_761318_preserves_t_mouth_rc_context(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "761318")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={
            "stable_single_sided_mouth_geometry_requires_review",
            "stable_with_incomplete_t_mouth_rc_context",
        },
    )
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert status_doc["template_class"] == "single_sided_t_mouth"
    assert status_doc["counts"]["associated_rcsdroad_count"] >= 3
    assert status_doc["counts"]["associated_rcsdnode_count"] >= 2
    assert not status_doc["excluded_negative_rc_groups"]

    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("761318")
    roads = _load_case_roads_by_id("761318")
    rcsd_nodes = _load_case_rcsd_nodes_by_id("761318")
    assert polygon.buffer(0.5).covers(nodes["761318"])
    assert polygon.buffer(0.5).covers(nodes["14547400"])
    assert polygon.buffer(0.5).covers(rcsd_nodes["5384375395091111"])
    assert abs(polygon.intersection(roads["605422519"]).length) <= 0.5


def test_case_package_500860756_remains_successful_after_kind2048_main_rc_group_preservation(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "500860756")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={
            "stable_overlap_requires_review",
            "stable_with_incomplete_t_mouth_rc_context",
        },
    )
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert status_doc["selected_positive_rc_groups"] == ["rc_group_1", "rc_group_2"]
    assert not status_doc["excluded_negative_rc_groups"]


def test_case_package_769081_excludes_foreign_mainnode_group_nearby_junction(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "769081")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )

    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("769081")
    rcsd_nodes = _load_case_rcsd_nodes_by_id("769081")
    assert polygon.buffer(0.5).covers(nodes["769081"])
    assert polygon.buffer(0.5).covers(rcsd_nodes["5389378295308746"])
    assert polygon.buffer(0.5).covers(rcsd_nodes["5389396044546351"])
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert sum(
        len(getattr(component, "interiors", []))
        for component in ([polygon] if polygon.geom_type == "Polygon" else polygon.geoms)
    ) == 0


def test_case_package_698418_accepts_surface_only_without_connected_local_rcsd_evidence(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "698418")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "surface_only"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "surface_only_without_connected_local_rcsd_evidence"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_705014_accepts_surface_only_without_connected_local_rcsd_evidence(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "705014")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "surface_only"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "surface_only_without_connected_local_rcsd_evidence"


def test_case_package_709632_accepts_ambiguous_main_rc_gap_when_polygon_covers_nonmain_branch(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "709632")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] in {"ambiguous_rc_match", "no_valid_rc_connection"}
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] in {
        "ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage",
        "rc_gap_without_connected_local_rcsd_evidence",
    }
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_758888_soft_excludes_remote_outside_rc_and_accepts(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "758888")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )
    assert status_doc["status"] != "rc_outside_drivezone"


def test_case_package_789616_accepts_compact_strong_mouth_after_excluding_near_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "789616")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_793460_rejects_foreign_semantic_road_intrusion(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "793460")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "stable_overlap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()


def test_case_package_861032_accepts_supported_compact_mainline_after_excluding_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "861032")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("861032")
    assert polygon.buffer(0.5).covers(nodes["861034"]) is False


def test_case_package_912232_accepts_rc_gap_without_connected_local_rcsd_evidence(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(
        tmp_path,
        "912232",
        case_root=_required_case_root("912232", Path.cwd()),
    )
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rc_gap_without_connected_local_rcsd_evidence"


def test_case_package_1126819_accepts_surface_only_after_excluding_disconnected_outside_rc(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(
        tmp_path,
        "1126819",
        case_root=_required_case_root("1126819", Path.cwd()),
    )
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "surface_only"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "surface_only_without_connected_local_rcsd_evidence"


def test_case_package_1180126_accepts_surface_only_after_excluding_disconnected_outside_rc(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(
        tmp_path,
        "1180126",
        case_root=_required_case_root("1180126", Path.cwd()),
    )
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "surface_only"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "surface_only_without_connected_local_rcsd_evidence"


def test_case_package_967104_accepts_excluded_negative_rc_tail_when_stable_core_remains(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(
        tmp_path,
        "967104",
        case_root=_required_case_root("967104", Path.cwd()),
    )
    assert artifacts.success is True
    assert status_doc["success"] is True
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_954218_accepts_stable_core_after_excluding_remote_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "954218")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "stable_overlap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_960599_accepts_stable_core_after_excluding_remote_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "960599")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] in {"stable", "no_valid_rc_connection"}
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] in {
        "foreign_outside_drivezone_soft_excluded",
        "outside_rc_gap_requires_review",
        "rc_gap_without_connected_local_rcsd_evidence",
    }


def test_case_package_998122_accepts_stable_core_after_excluding_remote_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "998122")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )


def test_case_package_788820_accepts_compact_multi_group_core_after_soft_excluding_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "788820")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"outside_rc_gap_requires_review"},
    )


def test_case_package_851884_accepts_after_trimming_unrelated_opposite_lane_corridor(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "851884")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={
            "foreign_outside_drivezone_soft_excluded",
            "foreign_tail_after_opposite_lane_trim",
        },
    )
    assert status_doc["template_class"] == "single_sided_t_mouth"
    assert status_doc["single_sided_unrelated_opposite_lane_trim_applied"] is True
    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    nodes = _load_case_nodes_by_id("851884")
    roads = _load_case_roads_by_id("851884")
    assert polygon.buffer(0.5).covers(nodes["851885"]) is False
    assert abs(polygon.intersection(roads["58285203"]).length) <= 0.5


def test_case_package_928223_accepts_stable_core_after_excluding_remote_negative_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "928223")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_983405_accepts_strong_side_coverage_after_soft_excluding_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "983405")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_989924_accepts_nonzero_mainnode_supported_core_after_soft_excluding_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "989924")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "stable_sparse_rc_context_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_967163_accepts_rc_gap_with_only_weak_unselected_edge_rc_groups(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "967163")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_885744_accepts_compact_edge_rc_tail_rc_gap(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "885744")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["acceptance_reason"] in {
        "rc_gap_with_compact_edge_rc_tail",
        "rc_gap_without_connected_local_rcsd_evidence",
    }


def test_case_package_879458_accepts_long_weak_unselected_edge_branch_rc_gap(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "879458")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["acceptance_reason"] in {
        "rc_gap_with_long_weak_unselected_edge_branch",
        "rc_gap_with_nonmain_branch_polygon_coverage",
        "rc_gap_without_connected_local_rcsd_evidence",
    }

    polygon = shape(_load_vector_doc(artifacts.virtual_polygon_path)["features"][0]["geometry"])
    roads = _load_case_roads_by_id("879458")
    assert 6.0 <= polygon.intersection(roads["622504163"]).length <= 12.0


def test_case_package_54265667_rejects_foreign_swsd_intrusion_even_with_strong_rc_context(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "54265667")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is False
    assert status_doc["status"] == "mainnodeid_out_of_scope"
    assert status_doc["acceptance_class"] == "rejected"


def test_case_package_1213535_accepts_compact_ambiguous_main_rc_gap(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "1213535")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "ambiguous_rc_match"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "ambiguous_main_rc_gap_with_compact_polygon"


def test_case_package_1226342_accepts_compact_ambiguous_main_rc_gap(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "1226342")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "ambiguous_rc_match"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "soft_overlap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_1220073_accepts_compact_local_mouth_rc_gap(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "1220073")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rc_gap_with_compact_local_mouth_geometry"


def test_case_package_1192979_accepts_stable_core_after_excluding_remote_outside_rc(tmp_path: Path) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "1192979")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()


def test_case_package_500669133_accepts_remote_outside_rc_when_no_effective_local_rcsd_junction_exists(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "500669133")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "outside_rc_gap_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["effective_local_rcsdnode_count"] == 0
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_500863721_accepts_rc_gap_without_effective_local_rcsd_junction_evidence(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "500863721")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rc_gap_without_connected_local_rcsd_evidence"
    assert status_doc["counts"]["effective_local_rcsdnode_count"] == 0


def test_case_package_941714_accepts_stable_core_after_soft_excluding_remote_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "941714")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"outside_rc_gap_requires_review"},
    )


def test_case_package_787133_accepts_compact_t_shape_after_soft_excluding_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "787133")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )


def test_case_package_854878_accepts_compact_single_group_core_after_soft_excluding_outside_rc_tail(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "854878")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "stable"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "stable_sparse_rc_context_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2


def test_case_package_948228_accepts_compact_mainline_rc_gap_without_selected_positive_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "948228")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rc_gap_with_compact_mainline_geometry"


def test_case_package_917475_accepts_rc_gap_without_structural_side_branch(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "917475")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["acceptance_reason"] in {
        "rc_gap_without_structural_side_branch",
        "rc_gap_without_connected_local_rcsd_evidence",
    }


def test_case_package_47130796_accepts_compact_ambiguous_main_rc_gap_with_supported_polygon(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "47130796")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "ambiguous_rc_match"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "ambiguous_main_rc_gap_with_compact_supported_polygon"


def test_case_package_74192363_accepts_rc_gap_with_single_weak_edge_side_branch(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "74192363")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_match_class"] == BUSINESS_MATCH_PARTIAL_RCSD
    assert status_doc["acceptance_reason"] in {
        "rc_gap_with_single_weak_edge_side_branch",
        "rc_gap_without_connected_local_rcsd_evidence",
    }


def test_case_package_74232960_accepts_compact_mainline_rc_gap(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "74232960")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "no_valid_rc_connection"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rc_gap_with_compact_mainline_geometry"


def test_case_package_74419702_accepts_stable_core_after_soft_excluding_remote_outside_rc(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "74419702")
    assert artifacts.success is False
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )
    assert status_doc["counts"]["covered_extra_local_node_count"] == 0
    assert status_doc["counts"]["covered_extra_local_road_count"] == 0


def test_case_package_520394575_remains_rejected_as_hard_failure(tmp_path: Path) -> None:
    artifacts, status_doc, render_root = _run_case_package_case(tmp_path, "520394575")
    assert artifacts.success is False
    assert status_doc["success"] is False
    assert status_doc["flow_success"] is False
    assert status_doc["status"] == "rc_outside_drivezone"
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rc_outside_drivezone"
    render_path = render_root / "520394575.png"
    assert render_path.is_file()
    image = _read_png_rgba(render_path)
    assert tuple(image[0, 0]) == (164, 0, 0, 255)
    background = image[min(100, image.shape[0] - 1), min(100, image.shape[1] - 1), :3]
    assert int(background[0]) > int(background[1]) + 15
    assert int(background[0]) > int(background[2]) + 15


def test_is_foreign_local_junction_node_treats_degree3_node_without_mainnode_as_foreign() -> None:
    node = ParsedNode(
        feature_index=0,
        properties={},
        geometry=Point(10.0, 0.0),
        node_id="foreign",
        mainnodeid=None,
        has_evd=None,
        is_anchor=None,
        kind_2=0,
        grade_2=0,
    )
    assert _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"foreign": 3},
    ) is True


def test_is_foreign_local_junction_node_ignores_foreign_group_member_with_degree2() -> None:
    node = ParsedNode(
        feature_index=0,
        properties={},
        geometry=Point(10.0, 0.0),
        node_id="foreign_group_member",
        mainnodeid="other",
        has_evd="yes",
        is_anchor="no",
        kind_2=2048,
        grade_2=3,
    )
    assert _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"foreign_group_member": 2},
    ) is False


def test_is_foreign_local_junction_node_preserves_same_group_member() -> None:
    node = ParsedNode(
        feature_index=0,
        properties={},
        geometry=Point(10.0, 0.0),
        node_id="same_group_member",
        mainnodeid="target",
        has_evd="yes",
        is_anchor="no",
        kind_2=4,
        grade_2=3,
    )
    assert _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"same_group_member": 2},
    ) is False


def test_covered_foreign_local_road_ids_flags_intrusion_near_foreign_semantic_endpoint() -> None:
    local_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="target",
            mainnodeid="target",
            has_evd="yes",
            is_anchor="no",
            kind_2=4,
            grade_2=3,
        ),
        ParsedNode(
            feature_index=1,
            properties={},
            geometry=Point(16.0, 0.0),
            node_id="foreign",
            mainnodeid=None,
            has_evd="yes",
            is_anchor="no",
            kind_2=4,
            grade_2=3,
        ),
        ParsedNode(
            feature_index=2,
            properties={},
            geometry=Point(32.0, 0.0),
            node_id="remote",
            mainnodeid=None,
            has_evd="yes",
            is_anchor="no",
            kind_2=4,
            grade_2=3,
        ),
    ]
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={},
            geometry=LineString([(0.0, 0.0), (16.0, 0.0)]),
            road_id="road_target_foreign",
            snodeid="target",
            enodeid="foreign",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={},
            geometry=LineString([(16.0, 0.0), (32.0, 0.0)]),
            road_id="road_foreign_remote",
            snodeid="foreign",
            enodeid="remote",
            direction=2,
        ),
    ]

    intrusion_polygon = box(13.5, -3.0, 20.5, 3.0)
    covered_ids = _covered_foreign_local_road_ids(
        polygon_geometry=intrusion_polygon,
        local_roads=local_roads,
        local_nodes=local_nodes,
        allowed_road_ids=set(),
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"target": 1, "foreign": 3, "remote": 1},
        analysis_center=Point(0.0, 0.0),
    )
    assert covered_ids == ["road_foreign_remote", "road_target_foreign"]

    non_intrusion_polygon = box(1.0, -3.0, 7.0, 3.0)
    covered_ids = _covered_foreign_local_road_ids(
        polygon_geometry=non_intrusion_polygon,
        local_roads=local_roads,
        local_nodes=local_nodes,
        allowed_road_ids=set(),
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"target": 1, "foreign": 3, "remote": 1},
        analysis_center=Point(0.0, 0.0),
    )
    assert covered_ids == []


def test_select_main_pair_with_semantic_conflict_guard_keeps_distant_foreign_semantic_main_arm() -> None:
    branches = [
        BranchEvidence(
            branch_id="east_far",
            angle_deg=0.0,
            branch_type="road",
            road_ids=["road_east_far"],
            has_outgoing_support=True,
            drivezone_support_m=40.0,
            road_support_m=40.0,
        ),
        BranchEvidence(
            branch_id="west_main",
            angle_deg=180.0,
            branch_type="road",
            road_ids=["road_west_main"],
            has_incoming_support=True,
            drivezone_support_m=40.0,
            road_support_m=40.0,
        ),
    ]
    local_nodes = [
        ParsedNode(0, {}, Point(0.0, 0.0), "target", "target", "yes", "no", 4, 3),
        ParsedNode(1, {}, Point(40.0, 0.0), "foreign_far", "other", "yes", "no", 4, 3),
        ParsedNode(2, {}, Point(-40.0, 0.0), "west_end", None, "yes", "no", 0, 0),
    ]
    local_roads = [
        ParsedRoad(0, {}, LineString([(0.0, 0.0), (40.0, 0.0)]), "road_east_far", "target", "foreign_far", 2),
        ParsedRoad(1, {}, LineString([(0.0, 0.0), (-40.0, 0.0)]), "road_west_main", "target", "west_end", 2),
    ]

    main_pair, direct_foreign_branch_ids = _select_main_pair_with_semantic_conflict_guard(
        branches,
        center=Point(0.0, 0.0),
        local_roads=local_roads,
        local_nodes=local_nodes,
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"target": 2, "foreign_far": 3, "west_end": 1},
        semantic_mainnodeids={"target", "other"},
    )

    assert set(main_pair) == {"east_far", "west_main"}
    assert direct_foreign_branch_ids == set()


def test_select_main_pair_with_semantic_conflict_guard_marks_near_foreign_semantic_arm_as_conflict() -> None:
    branches = [
        BranchEvidence(
            branch_id="east_near",
            angle_deg=0.0,
            branch_type="road",
            road_ids=["road_east_near"],
            has_outgoing_support=True,
            drivezone_support_m=12.0,
            road_support_m=12.0,
        ),
        BranchEvidence(
            branch_id="west_main",
            angle_deg=180.0,
            branch_type="road",
            road_ids=["road_west_main"],
            has_incoming_support=True,
            drivezone_support_m=40.0,
            road_support_m=40.0,
        ),
    ]
    local_nodes = [
        ParsedNode(0, {}, Point(0.0, 0.0), "target", "target", "yes", "no", 4, 3),
        ParsedNode(1, {}, Point(8.0, 0.0), "foreign_near", "other", "yes", "no", 4, 3),
        ParsedNode(2, {}, Point(-40.0, 0.0), "west_end", None, "yes", "no", 0, 0),
    ]
    local_roads = [
        ParsedRoad(0, {}, LineString([(0.0, 0.0), (8.0, 0.0)]), "road_east_near", "target", "foreign_near", 2),
        ParsedRoad(1, {}, LineString([(0.0, 0.0), (-40.0, 0.0)]), "road_west_main", "target", "west_end", 2),
    ]

    main_pair, direct_foreign_branch_ids = _select_main_pair_with_semantic_conflict_guard(
        branches,
        center=Point(0.0, 0.0),
        local_roads=local_roads,
        local_nodes=local_nodes,
        target_group_node_ids={"target"},
        normalized_mainnodeid="target",
        local_road_degree_by_node_id={"target": 2, "foreign_near": 3, "west_end": 1},
        semantic_mainnodeids={"target", "other"},
    )

    assert set(main_pair) == {"east_near", "west_main"}
    assert direct_foreign_branch_ids == {"east_near"}


def test_is_effective_rc_junction_node_accepts_degree3_zero_mainnodeid() -> None:
    node = ParsedNode(
        feature_index=0,
        properties={},
        geometry=Point(0.0, 0.0),
        node_id="rc",
        mainnodeid=None,
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    assert _is_effective_rc_junction_node(
        node=node,
        local_rc_road_degree_by_node_id={"rc": 3},
    ) is True


def test_case_package_513244637_accepts_remote_outside_rc_when_only_degree2_rcsd_nodes_exist(
    tmp_path: Path,
) -> None:
    artifacts, status_doc, _ = _run_case_package_case(tmp_path, "513244637")
    assert artifacts.success is False
    _assert_case_review_required_v2(
        status_doc,
        allowed_statuses={"stable", "weak_branch_support"},
        allowed_reasons={"outside_rc_gap_requires_review"},
    )
    assert status_doc["counts"]["effective_local_rcsdnode_count"] == 0


def test_virtual_intersection_poc_ignores_far_rc_outside_drivezone_noise(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_far_outside_rc=True)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"
    assert status_doc["risks"] == []

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_far_noise" not in associated_road_ids


def test_virtual_intersection_poc_without_rc_group_still_associates_rc_roads(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "ambiguous_rc_match"}
    assert artifacts.success is (status_doc["status"] == "stable")

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert associated_road_ids


def test_virtual_intersection_poc_uses_compound_center_when_short_link_neighbor_forms_main_axis(tmp_path: Path) -> None:
    paths = _write_compound_center_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "surface_only"}
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "stable_compound_center_requires_review"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert artifacts.success is False

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "compound_center_applied" for row in audit_doc)

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.buffer(0.5).covers(Point(0.0, 0.0))


def test_virtual_intersection_poc_polygon_support_can_expand_beyond_conservative_association(tmp_path: Path) -> None:
    paths = _write_support_decoupling_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_east_secondary" not in associated_road_ids

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["status"] == "ambiguous_rc_match"
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["visual_review_class"] == VISUAL_REVIEW_V2
    assert status_doc["counts"]["polygon_support_rcsdroad_count"] >= status_doc["counts"]["associated_rcsdroad_count"]

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.buffer(0.5).covers(Point(10.0, 0.0))


def test_status_from_risks_marks_node_component_conflict_before_stable() -> None:
    assert _status_from_risks(["node_component_conflict"], has_associated_roads=True) == "node_component_conflict"


def test_effect_success_acceptance_promotes_supported_gap_cases_and_keeps_weak_gap_under_review() -> None:
    assert _effect_success_acceptance(
        status="stable",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=1,
        local_rc_node_count=1,
        local_road_count=1,
        local_node_count=1,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (True, "accepted", "stable")
    assert _effect_success_acceptance(
        status="surface_only",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=0,
        local_rc_node_count=0,
        local_road_count=0,
        local_node_count=0,
        connected_rc_group_count=0,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "surface_only_without_any_local_rcsd_data")
    assert _effect_success_acceptance(
        status="surface_only",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=4,
        local_rc_node_count=2,
        local_road_count=10,
        local_node_count=5,
        connected_rc_group_count=0,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "surface_only_without_connected_local_rcsd_evidence")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=0,
        local_rc_node_count=0,
        local_road_count=0,
        local_node_count=0,
        connected_rc_group_count=0,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "rc_gap_without_connected_local_rcsd_evidence")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=1,
        local_rc_node_count=2,
        local_road_count=6,
        local_node_count=3,
        connected_rc_group_count=0,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "rc_gap_without_substantive_nonmain_branch_coverage")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=4.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=0,
        local_rc_node_count=1,
        local_road_count=5,
        local_node_count=2,
        connected_rc_group_count=0,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "rc_gap_with_nonmain_branch_polygon_coverage")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=4,
        local_rc_node_count=2,
        local_road_count=4,
        local_node_count=1,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == (False, "review_required", "rc_gap_with_compact_local_mouth_geometry")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=19,
        local_rc_node_count=11,
        effective_local_rc_node_count=1,
        local_road_count=9,
        local_node_count=3,
        connected_rc_group_count=2,
        nonmain_branch_connected_rc_group_count=2,
        negative_rc_group_count=0,
        positive_rc_group_count=0,
        road_branch_count=3,
        has_structural_side_branch=False,
    ) == (False, "review_required", "rc_gap_with_compact_mainline_geometry")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=16,
        local_rc_node_count=15,
        effective_local_rc_node_count=8,
        local_road_count=13,
        local_node_count=6,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
        positive_rc_group_count=1,
        road_branch_count=2,
        has_structural_side_branch=False,
    ) == (False, "review_required", "rc_gap_without_structural_side_branch")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=14,
        local_rc_node_count=11,
        effective_local_rc_node_count=1,
        local_road_count=12,
        local_node_count=5,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
        positive_rc_group_count=1,
        road_branch_count=3,
        has_structural_side_branch=False,
        max_nonmain_edge_branch_road_support_m=16.473,
        max_nonmain_edge_branch_rc_support_m=48.8,
    ) == (False, "review_required", "rc_gap_with_single_weak_edge_side_branch")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=9,
        local_rc_node_count=6,
        effective_local_rc_node_count=1,
        local_road_count=9,
        local_node_count=3,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
        positive_rc_group_count=1,
        road_branch_count=3,
        has_structural_side_branch=False,
        max_nonmain_edge_branch_road_support_m=32.421,
        max_nonmain_edge_branch_rc_support_m=80.1,
    ) == (False, "review_required", "rc_gap_with_compact_edge_rc_tail")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=15,
        local_rc_node_count=11,
        effective_local_rc_node_count=5,
        local_road_count=27,
        local_node_count=13,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
        positive_rc_group_count=1,
        road_branch_count=3,
        has_structural_side_branch=False,
        max_nonmain_edge_branch_road_support_m=66.584,
        max_nonmain_edge_branch_rc_support_m=4.4,
    ) == (False, "review_required", "rc_gap_with_long_weak_unselected_edge_branch")
    assert _effect_success_acceptance(
        status="node_component_conflict",
        review_mode=False,
        max_selected_side_branch_covered_length_m=19.0,
        max_nonmain_branch_polygon_length_m=14.0,
        associated_rc_road_count=2,
        polygon_support_rc_road_count=2,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=2,
        local_rc_node_count=2,
        local_road_count=6,
        local_node_count=4,
        connected_rc_group_count=2,
        nonmain_branch_connected_rc_group_count=1,
        negative_rc_group_count=0,
    ) == (False, "review_required", "review_required_status:node_component_conflict")
    assert _effect_success_acceptance(
        status="ambiguous_rc_match",
        review_mode=False,
        max_selected_side_branch_covered_length_m=18.0,
        max_nonmain_branch_polygon_length_m=10.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=10,
        local_rc_node_count=6,
        local_road_count=12,
        local_node_count=5,
        connected_rc_group_count=2,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=1,
    ) == (False, "review_required", "ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage")
    assert _effect_success_acceptance(
        status="ambiguous_rc_match",
        review_mode=False,
        max_selected_side_branch_covered_length_m=1.399,
        max_nonmain_branch_polygon_length_m=8.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=1,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=15,
        local_rc_node_count=10,
        local_road_count=21,
        local_node_count=12,
        connected_rc_group_count=3,
        nonmain_branch_connected_rc_group_count=1,
        negative_rc_group_count=2,
    ) == (False, "review_required", "ambiguous_main_rc_gap_with_compact_polygon")
    assert _effect_success_acceptance(
        status="ambiguous_rc_match",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=4.5,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=8,
        local_rc_node_count=6,
        effective_local_rc_node_count=0,
        local_road_count=7,
        local_node_count=3,
        connected_rc_group_count=2,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=1,
        positive_rc_group_count=1,
        road_branch_count=3,
        has_structural_side_branch=False,
    ) == (False, "review_required", "ambiguous_main_rc_gap_with_compact_supported_polygon")
    review_mode_false_result = _effect_success_acceptance(
        status="stable",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=1,
        local_rc_node_count=1,
        local_road_count=1,
        local_node_count=1,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    )
    assert _effect_success_acceptance(
        status="stable",
        review_mode=True,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
        min_invalid_rc_distance_to_center_m=None,
        local_rc_road_count=1,
        local_rc_node_count=1,
        local_road_count=1,
        local_node_count=1,
        connected_rc_group_count=1,
        nonmain_branch_connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) == review_mode_false_result


def test_step5_foreign_model_inferrs_subtype_from_facts_when_acceptance_reason_is_review_mode() -> None:
    result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=("r-1",),
            foreign_rc_context_ids=(),
            acceptance_reason="review_mode",
            foreign_overlap_metric_m=4.2,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=None,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=True,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={"r-1": 4.2},
        )
    )

    assert result.foreign_subtype == "corridor_intrusion"
    assert result.blocking_foreign_established is True
    assert result.canonical_foreign_established is True
    assert result.canonical_foreign_reason == "foreign_corridor_intrusion"


def test_step5_foreign_model_treats_overlap_only_as_provenance_not_blocking() -> None:
    result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            foreign_overlap_metric_m=0.9,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=10.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={"road-1": 0.9},
        )
    )

    assert result.foreign_subtype == "semantic_road_overlap"
    assert result.blocking_foreign_established is False
    assert result.canonical_foreign_established is False
    assert result.canonical_foreign_reason is None


def test_step5_foreign_model_treats_soft_trim_semantic_overlap_as_provenance_not_blocking() -> None:
    result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="outside_rc_gap_requires_review",
            foreign_overlap_metric_m=2.2,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=6.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            foreign_overlap_by_id={"road-1": 2.2},
        )
    )

    assert result.foreign_subtype == "semantic_road_overlap"
    assert result.blocking_foreign_established is False
    assert result.canonical_foreign_established is False
    assert result.canonical_foreign_reason is None


def test_step5_foreign_model_keeps_soft_trim_without_overlap_as_blocking_outside_drivezone() -> None:
    result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="outside_rc_gap_requires_review",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=6.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            foreign_overlap_by_id={},
        )
    )

    assert result.foreign_subtype == "outside_drivezone_or_corridor"
    assert result.blocking_foreign_established is True
    assert result.canonical_foreign_established is True
    assert result.canonical_foreign_reason == "foreign_outside_drivezone_soft_excluded"


def test_step5_foreign_model_does_not_infer_outside_drivezone_from_strip_extent_alone() -> None:
    result = build_stage3_step5_foreign_model_result(
        Stage3Step5ForeignModelInputs(
            foreign_semantic_node_ids=(),
            foreign_road_arm_corridor_ids=(),
            foreign_rc_context_ids=(),
            acceptance_reason="stable_single_sided_mouth_geometry_requires_review",
            foreign_overlap_metric_m=0.0,
            foreign_tail_length_m=0.0,
            foreign_strip_extent_m=10.0,
            foreign_overlap_zero_but_tail_present=False,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            foreign_overlap_by_id={},
        )
    )

    assert result.foreign_subtype is None
    assert result.blocking_foreign_established is False
    assert result.canonical_foreign_established is False
    assert result.canonical_foreign_reason is None


def test_stage3_review_metadata_from_step7_result_prefers_ineligible_gate_decision() -> None:
    step7_result = Stage3Step7AcceptanceResult(
        mainnodeid="922217",
        template_class="single_sided_t_mouth",
        status="stable",
        success=False,
        business_outcome_class="risk",
        acceptance_class="review_required",
        acceptance_reason="review_mode",
        root_cause_layer="step3",
        root_cause_type="review_mode",
        visual_review_class=VISUAL_REVIEW_V2,
        step3_legal_space_established=True,
        step4_required_rc_established=False,
        step5_foreign_exclusion_established=False,
        step6_geometry_established=True,
    )
    decision = Stage3OfficialReviewDecision(
        official_review_eligible=False,
        blocking_reason="representative is_anchor=yes; excluded by Stage3 input gate",
        failure_bucket=ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    )

    metadata = stage3_review_metadata_from_step7_result(
        step7_result,
        official_review_decision=decision,
    )

    assert metadata.root_cause_layer == ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
    assert metadata.visual_review_class == VISUAL_REVIEW_V5
    assert metadata.root_cause_type == decision.blocking_reason


def test_can_soft_exclude_outside_rc_accepts_remote_tail_but_rejects_near_center_conflict() -> None:
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=9.8,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=19.538,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=7.954,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=2.482,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="surface_only",
        selected_rc_road_count=0,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=1.183,
        connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=7.399,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=1.304,
        connected_rc_group_count=2,
        negative_rc_group_count=1,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=10.108,
        connected_rc_group_count=3,
        negative_rc_group_count=1,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=2,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=12.182,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=4,
        polygon_support_rc_road_count=4,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=4.0,
        min_invalid_rc_distance_to_center_m=9.393,
        connected_rc_group_count=2,
        negative_rc_group_count=0,
        effective_local_rc_node_count=4,
        local_road_count=6,
        local_node_count=3,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=4,
        polygon_support_rc_road_count=4,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=12.766,
        connected_rc_group_count=2,
        negative_rc_group_count=0,
        effective_local_rc_node_count=6,
        local_road_count=6,
        local_node_count=2,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=13.861,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=0.4,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        local_road_count=3,
        local_node_count=1,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=7.954,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=2.482,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        local_road_count=11,
        local_node_count=5,
    ) is True


def test_business_match_class_maps_internal_statuses_to_business_semantics() -> None:
    assert _business_match_class(
        status="stable",
        acceptance_class="accepted",
        associated_rc_road_count=3,
        polygon_support_rc_road_count=3,
        local_rc_road_count=4,
        excluded_rc_road_count=0,
    ) == BUSINESS_MATCH_COMPLETE_RCSD
    assert _business_match_class(
        status="ambiguous_rc_match",
        acceptance_class="accepted",
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
        local_rc_road_count=4,
        excluded_rc_road_count=0,
    ) == BUSINESS_MATCH_PARTIAL_RCSD
    assert _business_match_class(
        status="surface_only",
        acceptance_class="accepted",
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
        local_rc_road_count=0,
        excluded_rc_road_count=0,
    ) == BUSINESS_MATCH_SWSD_ONLY
    assert _business_match_class(
        status="stable",
        acceptance_class="accepted",
        associated_rc_road_count=3,
        polygon_support_rc_road_count=3,
        local_rc_road_count=4,
        excluded_rc_road_count=1,
    ) == BUSINESS_MATCH_PARTIAL_RCSD


def test_max_selected_side_branch_covered_length_ignores_main_and_edge_only_branches() -> None:
    polygon = box(-6.0, -6.0, 12.0, 6.0)
    local_roads = [
        ParsedRoad(0, {}, LineString([(0.0, 0.0), (0.0, 40.0)]), "main_1", "100", "200", 2),
        ParsedRoad(1, {}, LineString([(0.0, 0.0), (0.0, -40.0)]), "main_2", "300", "100", 2),
        ParsedRoad(2, {}, LineString([(0.0, 0.0), (20.0, 0.0)]), "side_selected", "100", "400", 2),
        ParsedRoad(3, {}, LineString([(0.0, 0.0), (-20.0, 0.0)]), "side_edge_only", "500", "100", 2),
    ]
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=90.0,
            branch_type="road",
            road_ids=["main_1"],
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=270.0,
            branch_type="road",
            road_ids=["main_2"],
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=0.0,
            branch_type="road",
            road_ids=["side_selected"],
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
        ),
        BranchEvidence(
            branch_id="road_4",
            angle_deg=180.0,
            branch_type="road",
            road_ids=["side_edge_only"],
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="edge_only",
        ),
    ]

    covered_length_m = _max_selected_side_branch_covered_length_m(
        polygon_geometry=polygon,
        road_branches=road_branches,
        local_roads=local_roads,
    )

    assert round(covered_length_m, 3) == 12.0


def test_max_nonmain_branch_polygon_length_includes_edge_only_nonmain_coverage() -> None:
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=90.0,
            branch_type="road",
            is_main_direction=True,
            polygon_length_m=18.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=0.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=False,
            evidence_level="edge_only",
            polygon_length_m=7.544,
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=180.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            polygon_length_m=10.0,
        ),
    ]

    assert _max_nonmain_branch_polygon_length_m(road_branches=road_branches) == 10.0


def test_build_positive_negative_rc_groups_deduplicates_same_group_top_candidates() -> None:
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=210.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            drivezone_support_m=100.0,
            rc_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=30.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            drivezone_support_m=100.0,
            rc_support_m=100.0,
        ),
    ]
    road_branches[0].rcsdroad_ids = ["rc_group_1", "rc_group_2"]
    road_branches[1].rcsdroad_ids = ["rc_group_1", "rc_group_2"]
    rc_branches = [
        BranchEvidence(branch_id="rc_group_1", angle_deg=30.0, branch_type="rc_group", road_support_m=91.119),
        BranchEvidence(branch_id="rc_group_2", angle_deg=208.0, branch_type="rc_group", road_support_m=359.034),
    ]
    risks: list[str] = []

    positive, negative = _build_positive_negative_rc_groups(
        kind_2=2048,
        road_branches=road_branches,
        rc_branches=rc_branches,
        risks=risks,
        has_rc_group_nodes=False,
    )

    assert positive == {"rc_group_2"}
    assert negative == {"rc_group_1"}
    assert "ambiguous_rc_match" not in risks


def test_build_polygon_support_from_association_clears_orphan_support_nodes() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(80.0, 0.0), "901", None, None, None, None, None),
        ParsedNode(1, {}, Point(140.0, 0.0), "902", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(80.0, 0.0), (140.0, 0.0)]), "rc_far", "901", "902", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_far"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        analysis_center=group_nodes[0].geometry,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is True
    assert support_road_ids == set()
    assert support_node_ids == set()


def test_build_polygon_support_from_association_skips_extension_when_positive_road_lacks_both_local_endpoints() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(8.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(24.0, 0.0), "ext", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(60.0, 0.0), (8.0, 0.0)]), "rc_main", "far_missing", "near", 2),
        ParsedRoad(1, {}, LineString([(8.0, 0.0), (24.0, 0.0)]), "rc_ext", "near", "ext", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        analysis_center=group_nodes[0].geometry,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main"}
    assert "rc_ext" not in support_road_ids
    assert support_node_ids == {"near"}


def test_build_polygon_support_from_association_filters_far_endpoint_nodes() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(12.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(48.0, 0.0), "far", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(12.0, 0.0), (48.0, 0.0)]), "rc_main", "near", "far", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        analysis_center=group_nodes[0].geometry,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main"}
    assert support_node_ids == {"near"}


def test_build_polygon_support_from_association_keeps_nonzero_mainnode_endpoint_within_reasonable_group_distance() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(14.0, 0.0), "near_mainnode", "rc_mainnode", None, None, None, None),
        ParsedNode(1, {}, Point(85.0, 0.0), "far_zero", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(14.0, 0.0), (85.0, 0.0)]), "rc_main", "near_mainnode", "far_zero", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        analysis_center=group_nodes[0].geometry,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main"}
    assert support_node_ids == {"near_mainnode"}


def test_build_polygon_support_from_association_allows_single_sided_local_connector() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(8.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(4.0, 9.0), "branch_tip", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(50.0, -40.0), (8.0, 0.0)]), "rc_main", "far_missing", "near", 2),
        ParsedRoad(1, {}, LineString([(8.0, 0.0), (4.0, 9.0)]), "rc_branch", "near", "branch_tip", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        analysis_center=group_nodes[0].geometry,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main", "rc_branch"}
    assert support_node_ids == {"near", "branch_tip"}


def test_virtual_intersection_poc_writes_debug_rendered_map_when_enabled(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        **paths,
    )
    assert artifacts.success is True
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()
    assert artifacts.rendered_map_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_virtual_intersection_poc_accepts_no_valid_rc_connection_when_polygon_preserves_nonmain_branch_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _write_poc_inputs(tmp_path)

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._select_positive_rc_road_ids",
        lambda **_: ({"missing_rc"}, set(), set()),
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._build_polygon_support_from_association",
        lambda **_: (set(), set(), False),
    )

    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", debug=True, **paths)

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["status"] in {"stable", "no_valid_rc_connection"}
    assert status_doc["acceptance_reason"] in {"stable", "rc_gap_with_nonmain_branch_polygon_coverage"}
    assert status_doc["counts"]["max_selected_side_branch_covered_length_m"] >= 10.0
    assert status_doc["counts"]["max_nonmain_branch_polygon_length_m"] >= 10.0


def test_virtual_intersection_poc_can_soft_exclude_outside_rc_and_accept_when_nonmain_branch_coverage_remains(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._select_positive_rc_road_ids",
        lambda **_: ({"missing_rc"}, set(), set()),
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._build_polygon_support_from_association",
        lambda **_: (set(), set(), False),
    )

    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", debug=True, **paths)

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    _assert_case_rejected_v4(
        status_doc,
        allowed_statuses={"stable"},
        allowed_reasons={"foreign_outside_drivezone_soft_excluded"},
    )
    assert status_doc["counts"]["max_selected_side_branch_covered_length_m"] >= 9.5
    assert status_doc["counts"]["max_nonmain_branch_polygon_length_m"] >= 9.5
    assert status_doc["counts"]["excluded_rcsdroad_count"] >= 1


def test_has_structural_side_branch_requires_real_side_support() -> None:
    weak_side = BranchEvidence(
        branch_id="road_3",
        angle_deg=300.0,
        branch_type="road",
        road_support_m=15.0,
        drivezone_support_m=4.0,
        rc_support_m=0.0,
        is_main_direction=False,
        selected_for_polygon=False,
        evidence_level="edge_only",
    )
    strong_side = BranchEvidence(
        branch_id="road_4",
        angle_deg=140.0,
        branch_type="road",
        road_support_m=32.0,
        drivezone_support_m=24.0,
        rc_support_m=0.0,
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
    )
    assert _has_structural_side_branch([weak_side]) is False
    assert _has_structural_side_branch([weak_side, strong_side]) is True


def test_select_positive_rc_road_ids_keeps_dual_centered_roads_for_non_t_case() -> None:
    center = Point(0.0, 0.0)
    road_a = ParsedRoad(
        feature_index=0,
        properties={},
        geometry=LineString([(8.0, 8.0), (-30.0, -30.0)]),
        road_id="road_a",
        snodeid="a1",
        enodeid="a2",
        direction=2,
    )
    road_b = ParsedRoad(
        feature_index=1,
        properties={},
        geometry=LineString([(8.0, -8.0), (-30.0, 30.0)]),
        road_id="road_b",
        snodeid="b1",
        enodeid="b2",
        direction=2,
    )
    side_candidate = ParsedRoad(
        feature_index=2,
        properties={},
        geometry=LineString([(8.0, -8.0), (28.0, -28.0)]),
        road_id="side_candidate",
        snodeid="b1",
        enodeid="c1",
        direction=2,
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=225.0,
        branch_type="rc_group",
        road_ids=["road_a", "road_b"],
    )
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=45.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
            drivezone_support_m=100.0,
            road_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=225.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
            drivezone_support_m=100.0,
            road_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=300.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=False,
            evidence_level="edge_only",
            drivezone_support_m=4.0,
            road_support_m=10.0,
        ),
    ]
    positive_ids, adjacent_ids, excluded_ids = _select_positive_rc_road_ids(
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        local_rc_roads=[road_a, road_b, side_candidate],
        center=center,
        road_branches=road_branches,
    )
    assert positive_ids == {"road_a", "road_b"}
    assert adjacent_ids == set()
    assert excluded_ids == set()


def test_select_positive_rc_road_ids_prefers_proximal_terminal_spur_over_distal_spur() -> None:
    center = Point(0.0, 0.0)
    selected = ParsedRoad(
        feature_index=0,
        properties={},
        geometry=LineString([(10.0, 0.0), (-25.0, 25.0)]),
        road_id="selected",
        snodeid="n1",
        enodeid="n2",
        direction=2,
    )
    proximal_spur = ParsedRoad(
        feature_index=1,
        properties={},
        geometry=LineString([(10.0, 0.0), (12.0, 18.0)]),
        road_id="proximal_spur",
        snodeid="n1",
        enodeid="n3",
        direction=2,
    )
    distal_spur = ParsedRoad(
        feature_index=2,
        properties={},
        geometry=LineString([(-25.0, 25.0), (-45.0, 28.0)]),
        road_id="distal_spur",
        snodeid="n2",
        enodeid="n4",
        direction=2,
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=135.0,
        branch_type="rc_group",
        road_ids=["selected"],
    )
    road_branches = [
        BranchEvidence(
            branch_id="road_main_a",
            angle_deg=315.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=80.0,
            road_support_m=80.0,
        ),
        BranchEvidence(
            branch_id="road_main_b",
            angle_deg=135.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=80.0,
            road_support_m=80.0,
        ),
        BranchEvidence(
            branch_id="road_side",
            angle_deg=90.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=20.0,
            road_support_m=20.0,
        ),
    ]
    positive_ids, adjacent_ids, excluded_ids = _select_positive_rc_road_ids(
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        local_rc_roads=[selected, proximal_spur, distal_spur],
        center=center,
        road_branches=road_branches,
    )
    assert positive_ids == {"selected"}
    assert adjacent_ids == {"proximal_spur"}
    assert "distal_spur" in excluded_ids


def test_branch_uses_rc_tip_suppression_requires_supported_positive_group() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1", "rc_2"],
    )

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is False

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids={"rc_2"},
    ) is True


def test_branch_uses_rc_tip_suppression_keeps_negative_group_suppressed() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1"],
    )

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups=set(),
        negative_rc_groups={"rc_group_1"},
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is True


def test_branch_has_positive_rc_gap_requires_positive_group_without_supported_roads() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1", "rc_2"],
    )

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is True

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids={"rc_1"},
    ) is False

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups={"rc_group_1"},
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is False


def test_rc_gap_branch_polygon_length_supports_partial_and_edge_only_side_branches() -> None:
    partial_branch = BranchEvidence(
        branch_id="road_partial",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="arm_partial",
        drivezone_support_m=19.5,
        road_support_m=15.0,
    )
    edge_branch = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        drivezone_support_m=7.5,
        road_support_m=7.5,
    )

    assert _rc_gap_branch_polygon_length_m(partial_branch) == 12.0
    assert _rc_gap_branch_polygon_length_m(edge_branch) == 6.0


def test_branch_has_local_road_mouth_detects_small_edge_only_side_branch_without_rc_group() -> None:
    local_mouth = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=7.5,
        road_support_m=7.5,
    )
    low_drivezone_but_clear_mouth = BranchEvidence(
        branch_id="road_low_drivezone",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=1.1,
        road_support_m=21.0,
        rc_support_m=1.3,
    )
    moderate_drivezone_local_mouth = BranchEvidence(
        branch_id="road_moderate_drivezone",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=4.7,
        road_support_m=17.0,
        rc_support_m=3.1,
    )
    strong_long_local_mouth = BranchEvidence(
        branch_id="road_strong_long_local_mouth",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        selected_for_polygon=False,
        rcsdroad_ids=[],
        drivezone_support_m=5.8,
        road_support_m=66.6,
        rc_support_m=4.4,
    )
    weak_edge = BranchEvidence(
        branch_id="road_weak",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=2.0,
        road_support_m=2.0,
    )
    rc_backed_edge = BranchEvidence(
        branch_id="road_rc_backed",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=7.5,
        road_support_m=7.5,
        rc_support_m=9.0,
    )

    assert _branch_has_local_road_mouth(local_mouth) is True
    assert _branch_has_local_road_mouth(low_drivezone_but_clear_mouth) is True
    assert _branch_has_local_road_mouth(moderate_drivezone_local_mouth) is True
    assert _branch_has_local_road_mouth(strong_long_local_mouth) is True
    assert _branch_has_local_road_mouth(weak_edge) is False
    assert _branch_has_local_road_mouth(rc_backed_edge) is False
    assert _local_road_mouth_polygon_length_m(low_drivezone_but_clear_mouth) == 10.0
    assert _local_road_mouth_polygon_length_m(moderate_drivezone_local_mouth) == 10.0
    assert _local_road_mouth_polygon_length_m(strong_long_local_mouth) == 10.0


def test_branch_has_minimal_local_road_touch_detects_small_rc_gap_side_branch() -> None:
    weak_edge = BranchEvidence(
        branch_id="road_weak",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=2.3,
        road_support_m=2.3,
        rc_support_m=1.9,
    )
    stronger_edge = BranchEvidence(
        branch_id="road_stronger",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=3.3,
        road_support_m=3.4,
        rc_support_m=2.8,
    )

    assert _branch_has_minimal_local_road_touch(weak_edge) is True
    assert _branch_has_minimal_local_road_touch(stronger_edge) is False


def test_polygon_branch_length_keeps_selected_partial_side_branch_from_being_overcompressed() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=24.1,
        road_support_m=15.6,
        rc_support_m=0.0,
    )

    assert _polygon_branch_length_m(branch) == 10.0


def test_polygon_branch_length_expands_strong_selected_partial_side_branch_without_rc() -> None:
    branch = BranchEvidence(
        branch_id="road_side_strong",
        angle_deg=180.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=100.0,
        road_support_m=231.0,
        rc_support_m=3.8,
    )

    assert _polygon_branch_length_m(branch) == 14.0


def test_branch_prefers_compact_local_support_only_for_weak_local_mouths() -> None:
    weak_local_mouth = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=4.7,
        road_support_m=17.0,
        rc_support_m=3.1,
    )
    strong_partial_branch = BranchEvidence(
        branch_id="road_partial",
        angle_deg=180.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=100.0,
        road_support_m=231.0,
        rc_support_m=3.8,
    )

    assert _branch_prefers_compact_local_support(
        weak_local_mouth,
        branch_has_local_road_mouth=True,
        branch_has_minimal_local_road_touch=False,
    ) is True
    assert _branch_prefers_compact_local_support(
        strong_partial_branch,
        branch_has_local_road_mouth=False,
        branch_has_minimal_local_road_touch=False,
    ) is False


def test_can_soft_exclude_outside_rc_only_when_remaining_polygon_evidence_is_strong() -> None:
    assert _can_soft_exclude_outside_rc(
        status="no_valid_rc_connection",
        selected_rc_road_count=0,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=None,
        connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="node_component_conflict",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=2,
        max_selected_side_branch_covered_length_m=19.984,
        max_nonmain_branch_polygon_length_m=14.0,
        min_invalid_rc_distance_to_center_m=None,
        connected_rc_group_count=2,
        negative_rc_group_count=0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=20.168,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=None,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
    ) is False
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=0,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=None,
        connected_rc_group_count=0,
        negative_rc_group_count=0,
    ) is False
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=12.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=1,
        local_road_count=8,
        local_node_count=4,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=12.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        local_road_count=11,
        local_node_count=5,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=12.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=2,
        effective_associated_rc_node_count=1,
        local_road_count=16,
        local_node_count=7,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=14.0,
        min_invalid_rc_distance_to_center_m=12.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=2,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=1,
        local_road_count=16,
        local_node_count=5,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=4,
        polygon_support_rc_road_count=4,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        min_invalid_rc_distance_to_center_m=5.1,
        connected_rc_group_count=2,
        negative_rc_group_count=0,
        effective_local_rc_node_count=4,
        effective_associated_rc_node_count=4,
        associated_nonzero_mainnode_count=6,
        local_road_count=5,
        local_node_count=2,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=2,
        max_selected_side_branch_covered_length_m=2.1,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=5.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=9,
        local_node_count=5,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=2.1,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=5.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=9,
        local_node_count=5,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=10.3,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=10.2,
        connected_rc_group_count=3,
        negative_rc_group_count=2,
        effective_local_rc_node_count=1,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=11,
        local_node_count=7,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=32.7,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=6.3,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=9,
        local_node_count=4,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=7.8,
        min_invalid_rc_distance_to_center_m=0.2,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=4,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=2,
        local_road_count=15,
        local_node_count=7,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=7.8,
        min_invalid_rc_distance_to_center_m=0.2,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=4,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=2,
        local_road_count=15,
        local_node_count=7,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=12.0,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=2,
        effective_associated_rc_node_count=0,
        local_road_count=11,
        local_node_count=5,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=19.19685489088945,
        max_nonmain_branch_polygon_length_m=14.0,
        min_invalid_rc_distance_to_center_m=0.806225775176404,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=5,
        local_node_count=2,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=19.2334681718727,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=5,
        effective_associated_rc_node_count=2,
        associated_nonzero_mainnode_count=4,
        local_road_count=27,
        local_node_count=15,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=16.115692541591233,
        max_nonmain_branch_polygon_length_m=10.0,
        min_invalid_rc_distance_to_center_m=1.2309912134740568,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=3,
        effective_associated_rc_node_count=1,
        associated_nonzero_mainnode_count=2,
        local_road_count=15,
        local_node_count=8,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=7.954244332086263,
        max_nonmain_branch_polygon_length_m=8.0,
        min_invalid_rc_distance_to_center_m=2.4824408965853655,
        connected_rc_group_count=1,
        negative_rc_group_count=0,
        effective_local_rc_node_count=0,
        effective_associated_rc_node_count=0,
        associated_nonzero_mainnode_count=0,
        local_road_count=11,
        local_node_count=5,
    ) is False


def test_regularize_virtual_polygon_geometry_keeps_single_seeded_component_without_holes() -> None:
    seeded = box(0.0, 0.0, 6.0, 6.0)
    detached = box(20.0, 0.0, 24.0, 4.0)
    holed = Polygon(
        seeded.exterior.coords,
        [box(1.0, 1.0, 2.0, 2.0).exterior.coords],
    )
    geometry = unary_union([holed, detached])
    drivezone = box(-5.0, -5.0, 30.0, 10.0)
    seed_geometry = box(0.0, 0.0, 1.0, 1.0)

    regularized = _regularize_virtual_polygon_geometry(
        geometry=geometry,
        drivezone_union=drivezone,
        seed_geometry=seed_geometry,
    )

    assert regularized.geom_type == "Polygon"
    assert len(regularized.interiors) == 0
    assert regularized.intersects(seed_geometry)
    assert not regularized.intersects(detached)


def _write_patch_filtered_poc_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_noise_patch2", "snodeid": "500", "enodeid": "501", "direction": 2, "patchid": "p2"}, "geometry": LineString([(35.0, 42.0), (62.0, 42.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {"properties": {"patchid": "p1"}, "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)])},
            {"properties": {"patchid": "p2"}, "geometry": box(30.0, 34.0, 70.0, 50.0)},
        ],
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
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_patch_resolution_and_filtering_uses_unique_incident_road_patch() -> None:
    group_nodes = [
        ParsedNode(0, {"id": "100"}, Point(0.0, 0.0), "100", "100", "yes", "no", 2048, 1),
        ParsedNode(1, {"id": "101"}, Point(6.0, 2.0), "101", "100", "yes", "no", 2048, 1),
    ]
    roads = [
        ParsedRoad(0, {"id": "r1", "snodeid": "100", "enodeid": "200", "direction": 2, "patchid": "p1"}, LineString([(0.0, 0.0), (0.0, 10.0)]), "r1", "100", "200", 2),
        ParsedRoad(1, {"id": "r2", "snodeid": "300", "enodeid": "100", "direction": 2, "patchid": "p1"}, LineString([(0.0, -10.0), (0.0, 0.0)]), "r2", "300", "100", 2),
        ParsedRoad(2, {"id": "r3", "snodeid": "500", "enodeid": "501", "direction": 2, "patchid": "p2"}, LineString([(20.0, 20.0), (30.0, 20.0)]), "r3", "500", "501", 2),
    ]

    current_patch_id = _resolve_current_patch_id_from_roads(group_nodes=group_nodes, roads=roads)

    assert current_patch_id == "p1"
    assert [road.road_id for road in _filter_parsed_roads_to_patch(roads, patch_id=current_patch_id)] == ["r1", "r2"]


def test_stage3_uses_only_same_patch_roads_and_drivezone(tmp_path: Path) -> None:
    paths = _write_patch_filtered_poc_inputs(tmp_path)

    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="same_patch_only",
        debug=False,
        **paths,
    )

    assert artifacts.status_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    counts = status_doc["counts"]
    assert counts["current_patch_id"] == "p1"
    assert counts["same_patch_filter_applied"] is True
    assert counts["local_road_count"] == 3
    assert counts["local_drivezone_feature_count"] == 1
