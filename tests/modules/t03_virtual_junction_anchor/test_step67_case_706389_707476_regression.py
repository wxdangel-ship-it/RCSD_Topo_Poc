from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import (
    VISUAL_V1,
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import Step67Context


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")


@pytest.mark.parametrize("case_id", ["706389", "707476"])
def test_real_cases_706389_and_707476_recover_after_foreign_mask_normalization(case_id: str) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
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
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0
    assert step6_result.audit_doc["assembly"]["foreign_mask_mode"] == "road_like_1m_mask"
    assert step6_result.audit_doc["assembly"]["foreign_mask_sources"] == ["excluded_rcsdroad_geometry"]
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1


def test_real_case_706389_uses_single_sided_horizontal_semantic_plus_5m_cut() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["706389"],
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

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step7_result.step7_state == "accepted"
    assert branches["58163436"]["window_mode"] in {
        "single_sided_semantic_plus_5m",
        "single_sided_preserve_candidate_boundary",
    }
    assert branches["629431331"]["window_mode"] in {
        "single_sided_semantic_plus_5m",
        "single_sided_preserve_candidate_boundary",
    }
    assert branches["58163436"]["special_rule_applied"] is True
    assert branches["629431331"]["special_rule_applied"] is True
    assert branches["58163436"]["cut_length_m"] > 40.0
    assert branches["629431331"]["cut_length_m"] > 40.0
    assert branches["617732646"]["window_mode"] == "cut_at_20m"
    assert branches["617732646"]["cut_length_m"] == 20.0
