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
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import build_step7_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import Step67Context


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")


def test_real_case_520394575_stays_rejected_when_step3_and_anchor_data_exist() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["520394575"],
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

    assert step6_result.geometry_established is False
    assert step6_result.audit_doc["assembly"]["directional_cut_rule"]["mode"] == "directional_selected_road_cut"
    assert step6_result.audit_doc["assembly"]["directional_cut_rule"]["branch_count"] >= 1
    assert step7_result.step7_state == "rejected"
