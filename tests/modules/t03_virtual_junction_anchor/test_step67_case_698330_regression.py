from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    VISUAL_V1,
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import Step67Context


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")


def test_real_case_698330_keeps_selected_surface_length_after_foreign_mask_normalization() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["698330"],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0
    assert step45_case_result.audit_doc["step5"]["foreign_swsd_road_ids"] == []
    assert step45_case_result.audit_doc["step5"]["selected_surface_foreign_protection_applied"] is False
    for road_id in step45_context.selected_road_ids:
        road = next(road for road in step45_context.step1_context.roads if road.road_id == road_id)
        allowed_length = road.geometry.intersection(step45_context.step3_allowed_space_geometry).length
        final_length = road.geometry.intersection(step6_result.output_geometries.polygon_final_geometry).length
        assert final_length + 1e-6 >= allowed_length
