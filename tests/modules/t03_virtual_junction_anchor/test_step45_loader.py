from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import load_step45_case_specs, load_step45_context
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a


def test_step45_loader_reads_step3_prerequisites_and_selected_roads(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")

    specs, preflight = load_step45_case_specs(case_root=case_root, exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)

    assert preflight["raw_case_count"] == 1
    assert context.step1_context.case_spec.case_id == "100001"
    assert context.template_result.template_class == "center_junction"
    assert context.step3_status_doc["step3_state"] == "established"
    assert context.selected_road_ids == ("road_h", "road_v")
    assert context.step3_allowed_space_geometry is not None
