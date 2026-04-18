from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import load_step45_case_specs, load_step45_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import build_step45_case_result
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a, build_center_case_b, write_step3_prerequisite


def test_step45_state_follows_upstream_step3_review(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")
    write_step3_prerequisite(
        step3_root,
        "100001",
        template_class="center_junction",
        step3_state="review",
        selected_road_ids=["road_h", "road_v"],
        reason="step3_review_required",
    )

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert result.step45_state == "review"
    assert result.reason == "step45_upstream_step3_review"


def test_step45_state_support_only_maps_to_review(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100002")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100002"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert result.step45_state == "review"
    assert result.reason == "step45_support_only"
    assert result.extra_status_fields["rcsd_semantic_core_missing"] is True
