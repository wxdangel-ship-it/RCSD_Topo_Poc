from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import load_association_case_specs, load_association_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_association_case_result
from tests.modules.t03_virtual_junction_anchor._association_helpers import build_center_case_a, build_center_case_b, write_step3_prerequisite


def test_association_state_follows_upstream_step3_review(tmp_path: Path) -> None:
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

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.association_state == "review"
    assert result.reason == "association_upstream_step3_review"


def test_association_state_support_only_maps_to_review(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100002")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100002"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.association_state == "review"
    assert result.reason == "association_support_only"
    assert result.extra_status_fields["rcsd_semantic_core_missing"] is True
