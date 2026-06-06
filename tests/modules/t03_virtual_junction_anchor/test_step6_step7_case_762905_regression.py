from __future__ import annotations

from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, shape

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import FinalizationContext
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    write_case_outputs as write_step3_case_outputs,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import build_step6_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    VISUAL_V1,
    VISUAL_V2,
    build_step7_result,
)


REAL_T03_ROOT = Path("/mnt/e/TestData/POC_Data/T03")


def _write_step3_for_case(case_root: Path, step3_root: Path, case_id: str) -> None:
    specs, _ = load_case_specs(case_root=case_root, case_ids=[case_id], exclude_case_ids=[])
    context = build_step1_context(specs[0])
    template_result = classify_step2_template(context)
    case_result = build_step3_case_result(context, template_result)
    write_step3_case_outputs(run_root=step3_root, context=context, case_result=case_result)


def _rcsd_node_covered(case_root: Path, case_id: str, node_id: str, polygon) -> bool:
    with fiona.open(case_root / case_id / "rcsdnode.gpkg") as src:
        for feature in src:
            properties = dict(feature["properties"])
            if str(properties.get("id")) != node_id:
                continue
            return bool(polygon is not None and polygon.buffer(1.0).contains(shape(feature["geometry"])))
    raise AssertionError(f"missing RCSDNode {node_id}")


def _rcsd_line_cover_ratio(case_root: Path, case_id: str, left_node_id: str, right_node_id: str, polygon) -> float:
    points = {}
    with fiona.open(case_root / case_id / "rcsdnode.gpkg") as src:
        for feature in src:
            properties = dict(feature["properties"])
            node_id = str(properties.get("id"))
            if node_id in {left_node_id, right_node_id}:
                points[node_id] = shape(feature["geometry"])
    if set(points) != {left_node_id, right_node_id}:
        raise AssertionError(f"missing RCSDNode pair: {left_node_id}, {right_node_id}")
    line = LineString([points[left_node_id], points[right_node_id]])
    return line.intersection(polygon).length / line.length if polygon is not None and line.length > 0.0 else 0.0


def _run_real_case_finalization(case_id: str, tmp_path: Path):
    if not (REAL_T03_ROOT / case_id).is_dir():
        pytest.skip(f"missing decoded T03 case: {REAL_T03_ROOT / case_id}")

    step3_root = tmp_path / "step3"
    _write_step3_for_case(REAL_T03_ROOT, step3_root, case_id)
    specs, _ = load_association_case_specs(
        case_root=REAL_T03_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)
    return association_context, association_case_result, step6_result, step7_result


def test_real_case_762905_single_sided_strong_rcsdnode_is_kept_inside_final_polygon(tmp_path: Path) -> None:
    case_id = "762905"
    if not (REAL_T03_ROOT / case_id).is_dir():
        pytest.skip(f"missing decoded T03 case: {REAL_T03_ROOT / case_id}")

    step3_root = tmp_path / "step3"
    _write_step3_for_case(REAL_T03_ROOT, step3_root, case_id)
    specs, _ = load_association_case_specs(
        case_root=REAL_T03_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)
    polygon = step6_result.output_geometries.polygon_final_geometry

    assert association_case_result.association_class == "A"
    assert association_case_result.extra_status_fields["t_mouth_strong_related_rcsdnode_ids"] == [
        "5384380731228487",
        "5384380731228527",
    ]
    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step6_result.extra_status_fields["local_required_rcsdnode_ids"] == [
        "5384380731228487",
        "5384380731228527",
    ]
    assert step6_result.extra_status_fields["semantic_intra_rcsdnode_line_count"] == 2
    assert step6_result.extra_status_fields["semantic_intra_rcsdnode_line_cover_ratio"] == pytest.approx(1.0)
    for node_id in [
        "5384380731228487",
        "5384380731228505",
        "5384380731228527",
        "5384380731228501",
    ]:
        assert _rcsd_node_covered(REAL_T03_ROOT, case_id, node_id, polygon)
    assert _rcsd_line_cover_ratio(
        REAL_T03_ROOT,
        case_id,
        "5384380731228505",
        "5384380731228487",
        polygon,
    ) == pytest.approx(1.0)
    assert _rcsd_line_cover_ratio(
        REAL_T03_ROOT,
        case_id,
        "5384380731228501",
        "5384380731228527",
        polygon,
    ) == pytest.approx(1.0)


def test_real_case_21497119_single_sided_degree1_rcsdnode_stays_support_only(tmp_path: Path) -> None:
    case_id = "21497119"
    if not (REAL_T03_ROOT / case_id).is_dir():
        pytest.skip(f"missing decoded T03 case: {REAL_T03_ROOT / case_id}")

    step3_root = tmp_path / "step3"
    _write_step3_for_case(REAL_T03_ROOT, step3_root, case_id)
    specs, _ = load_association_case_specs(
        case_root=REAL_T03_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert association_context.step3_status_doc["step3_state"] == "review"
    assert association_case_result.association_class == "B"
    assert association_case_result.reason == "association_support_only"
    assert association_case_result.extra_status_fields["required_rcsdnode_ids"] == []
    assert association_case_result.extra_status_fields["required_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["support_rcsdroad_ids"] == [
        "5384380731228186",
        "5384380731228263",
    ]
    assert association_case_result.extra_status_fields["required_rcsdnode_gate_audit"]["5384380731228527"][
        "gate_decision"
    ] == "dropped"
    assert association_case_result.extra_status_fields["required_rcsdnode_gate_audit"]["5384380731228527"][
        "gate_reason"
    ] == "single_sided_required_core_singleton_degree_below_semantic_threshold"
    assert step6_result.geometry_established is True
    assert step6_result.audit_doc["assembly"]["support_only_tiny_fragment_pruned"] is True
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    assert step6_result.extra_status_fields["semantic_intra_rcsdnode_line_count"] == 0
    assert step7_result.step7_state == "accepted"
    assert step7_result.reason == "step7_accepted_with_upstream_step3_visual_risk"


def test_real_case_698542_support_only_far_support_lobe_is_filtered(tmp_path: Path) -> None:
    _association_context, association_case_result, step6_result, step7_result = _run_real_case_finalization(
        "698542",
        tmp_path,
    )

    assert association_case_result.association_class == "B"
    assert association_case_result.reason == "association_support_only"
    assert step6_result.geometry_established is True
    assert step6_result.audit_doc["assembly"]["support_only_seam_bridge_applied"] is True
    assert step6_result.audit_doc["assembly"]["support_only_seam_bridge_metrics"]["component_count"] == 1
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    assert step6_result.extra_status_fields["max_component_target_distance_m"] == 0.0
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1


def test_real_case_948240_support_only_two_lobe_single_sided_is_visual_audit(tmp_path: Path) -> None:
    _association_context, association_case_result, step6_result, step7_result = _run_real_case_finalization(
        "948240",
        tmp_path,
    )

    assert association_case_result.association_class == "B"
    assert association_case_result.reason == "association_support_only"
    assert step6_result.geometry_established is True
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 2
    assert step6_result.extra_status_fields["max_component_target_distance_m"] <= 9.0
    assert step6_result.extra_status_fields["foreign_exclusion_ok"] is True
    assert "polygon_multicomponent" in step6_result.review_signals
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V2


def test_real_case_956407_center_two_node_bridge_is_inherited_by_step6(tmp_path: Path) -> None:
    association_context, association_case_result, step6_result, step7_result = _run_real_case_finalization(
        "956407",
        tmp_path,
    )

    assert association_case_result.association_class == "A"
    assert association_case_result.reason == "association_established"
    assert association_context.step3_status_doc["two_node_t_bridge_applied"] is True
    assert step6_result.geometry_established is True
    assert step6_result.audit_doc["assembly"]["step3_two_node_t_bridge_inherited"] is True
    assert step6_result.audit_doc["assembly"]["target_node_connection_bridge_applied"] is True
    assert step6_result.extra_status_fields["target_node_connection_cover_ratio"] == 1.0
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1


def test_real_case_520394575_support_only_fragmented_surface_stays_rejected(tmp_path: Path) -> None:
    case_id = "520394575"
    if not (REAL_T03_ROOT / case_id).is_dir():
        pytest.skip(f"missing decoded T03 case: {REAL_T03_ROOT / case_id}")

    step3_root = tmp_path / "step3"
    _write_step3_for_case(REAL_T03_ROOT, step3_root, case_id)
    specs, _ = load_association_case_specs(
        case_root=REAL_T03_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert association_case_result.reason == "association_support_only"
    assert step6_result.geometry_established is False
    assert step6_result.reason == "step6_single_sided_shape_artifact"
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] >= 3
    assert step7_result.step7_state == "rejected"
