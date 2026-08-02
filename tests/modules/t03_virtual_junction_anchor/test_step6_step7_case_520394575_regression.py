from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import build_step7_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import FinalizationContext


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")


def test_real_case_520394575_stays_rejected_when_step3_and_anchor_data_exist() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["520394575"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is False
    assert step6_result.reason == "step6_blocked_by_association"
    assert step6_result.extra_status_fields["association_reason"] == (
        "association_raw_multi_component_unmatched_support"
    )
    raw_guard = step6_result.extra_status_fields["raw_topology_guard_audit"]
    assert raw_guard["unmatched_support"] is True
    assert raw_guard["unmatched_support_component_ids"]
    assert step7_result.step7_state == "rejected"
