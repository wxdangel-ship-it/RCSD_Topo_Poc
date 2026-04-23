from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


@pytest.mark.smoke
def test_t04_step6_outputs_synthetic_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step6",
        run_id="synthetic_t04_step6",
    )

    result_case_dir = run_root / "cases" / "1001"
    step6_status = json.loads((result_case_dir / "step6_status.json").read_text(encoding="utf-8"))
    step6_audit = json.loads((result_case_dir / "step6_audit.json").read_text(encoding="utf-8"))

    assert step6_status["assembly_state"] in {"assembled", "assembled_with_review"}
    assert step6_status["component_count"] == 1
    assert step6_status["hard_must_cover_ok"] is True
    assert step6_status["unexpected_hole_count"] == 0
    assert step6_status["forbidden_overlap_area_m2"] == pytest.approx(0.0, abs=1e-6)
    assert "assembly_canvas_geometry" in step6_audit
    assert "hard_seed_geometry" in step6_audit
    assert (result_case_dir / "final_case_polygon.gpkg").is_file()

    fiona = pytest.importorskip("fiona")
    with fiona.open(result_case_dir / "final_case_polygon.gpkg") as src:
        rows = list(src)
    assert len(rows) == 1
    assert rows[0]["properties"]["component_count"] == 1


@pytest.mark.smoke
def test_t04_step6_pair_local_empty_case_keeps_single_component(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1002"
    _build_pair_local_empty_rcsd_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step6_pair_local_empty",
        run_id="synthetic_t04_step6_pair_local_empty",
    )

    result_case_dir = run_root / "cases" / "1002"
    step6_status = json.loads((result_case_dir / "step6_status.json").read_text(encoding="utf-8"))

    assert step6_status["assembly_state"] in {"assembled", "assembled_with_review"}
    assert step6_status["component_count"] == 1
    assert step6_status["hard_must_cover_ok"] is True
    assert (result_case_dir / "final_case_polygon.gpkg").is_file()


@pytest.mark.smoke
def test_t04_step6_multi_event_case_reports_conflict_without_breaking_constraints(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step6_multi",
        run_id="synthetic_t04_step6_multi",
    )

    result_case_dir = run_root / "cases" / "2002"
    step5_status = json.loads((result_case_dir / "step5_status.json").read_text(encoding="utf-8"))
    step6_status = json.loads((result_case_dir / "step6_status.json").read_text(encoding="utf-8"))

    assert step5_status["case_bridge_zone_geometry"]["present"] is True
    assert step6_status["assembly_state"] == "assembly_failed"
    assert step6_status["component_count"] > 1
    assert step6_status["hard_must_cover_ok"] is True
    assert step6_status["forbidden_overlap_area_m2"] == pytest.approx(0.0, abs=1e-6)
    assert step6_status["cut_violation"] is False
    assert "multi_component_result" in set(step6_status["review_reasons"])
    assert "hard_must_cover_disconnected" not in set(step6_status["review_reasons"])
    assert (result_case_dir / "final_case_polygon.gpkg").is_file()
