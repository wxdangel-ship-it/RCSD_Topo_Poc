from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")


def load_real_case_bundle(case_id: str):
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")

    specs, _ = load_case_specs(case_root=REAL_ANCHOR_ROOT, case_ids=[case_id])
    context = build_step1_context(specs[0])
    template_result = classify_step2_template(context)
    case_result = build_step3_case_result(context, template_result)
    return context, template_result, case_result
