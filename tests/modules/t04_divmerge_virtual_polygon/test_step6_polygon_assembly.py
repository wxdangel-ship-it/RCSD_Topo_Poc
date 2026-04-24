from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import polygon_assembly
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.polygon_assembly import (
    build_step6_polygon_assembly,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    T04Step5CaseResult,
    T04Step5UnitResult,
)

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


def test_t04_step6_canvas_respects_terminal_window_domain() -> None:
    drivezone = Polygon([(-60, -30), (160, -30), (160, 30), (-60, 30), (-60, -30)])
    case_result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id="window_case"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    must_cover = unary_union([Point(20, 0).buffer(2.5), Point(80, 0).buffer(2.5)])
    allowed = Polygon([(-40, -12), (140, -12), (140, 12), (-40, 12), (-40, -12)])
    terminal_window = Polygon([(0, -30), (100, -30), (100, 30), (0, 30), (0, -30)])
    cut_lines = unary_union(
        [
            LineString([(0, -24), (0, 24)]),
            LineString([(100, -24), (100, 24)]),
        ]
    )
    step5_result = T04Step5CaseResult(
        case_id="window_case",
        unit_results=(),
        case_must_cover_domain=must_cover,
        case_allowed_growth_domain=allowed,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=cut_lines,
        case_terminal_window_domain=terminal_window,
        case_terminal_support_corridor_geometry=LineString([(0, 0), (100, 0)]).buffer(6.0, cap_style=2),
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
    )

    result = build_step6_polygon_assembly(case_result, step5_result)

    assert result.assembly_canvas_geometry is not None
    assert result.final_case_polygon is not None
    assert result.assembly_canvas_geometry.bounds[0] >= -0.75
    assert result.assembly_canvas_geometry.bounds[2] <= 100.75
    assert result.final_case_polygon.bounds[0] >= -0.75
    assert result.final_case_polygon.bounds[2] <= 100.75


def test_t04_step6_terminal_window_does_not_expand_grid_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    drivezone = Polygon([(-60, -30), (160, -30), (160, 30), (-60, 30), (-60, -30)])
    case_result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id="wide_window_case"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    must_cover = unary_union([Point(20, 0).buffer(2.5), Point(80, 0).buffer(2.5)])
    allowed = Polygon([(-40, -12), (140, -12), (140, 12), (-40, 12), (-40, -12)])
    terminal_window = Polygon(
        [(-5000, -5000), (5000, -5000), (5000, 5000), (-5000, 5000), (-5000, -5000)]
    )
    observed_patch_sizes: list[float] = []
    real_build_grid = polygon_assembly._build_grid

    def guarded_build_grid(center: Point, *, patch_size_m: float, resolution_m: float):
        observed_patch_sizes.append(float(patch_size_m))
        assert patch_size_m < 300.0
        return real_build_grid(center, patch_size_m=patch_size_m, resolution_m=resolution_m)

    monkeypatch.setattr(polygon_assembly, "_build_grid", guarded_build_grid)
    step5_result = T04Step5CaseResult(
        case_id="wide_window_case",
        unit_results=(),
        case_must_cover_domain=must_cover,
        case_allowed_growth_domain=allowed,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=None,
        case_terminal_window_domain=terminal_window,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
    )

    result = build_step6_polygon_assembly(case_result, step5_result)

    assert observed_patch_sizes
    assert result.assembly_canvas_geometry is not None


def test_t04_step6_rejects_oversized_grid_before_allocating_arrays() -> None:
    drivezone = Polygon([(-3000, -3000), (3000, -3000), (3000, 3000), (-3000, 3000), (-3000, -3000)])
    case_result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id="oversized_grid_case"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    step5_result = T04Step5CaseResult(
        case_id="oversized_grid_case",
        unit_results=(),
        case_must_cover_domain=Point(0, 0).buffer(2.5),
        case_allowed_growth_domain=drivezone,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=None,
        case_terminal_window_domain=None,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
    )

    with pytest.raises(ValueError, match="step6_grid_too_large"):
        build_step6_polygon_assembly(case_result, step5_result)


def test_t04_step6_rechecks_effective_b_node_target_after_raster_assembly() -> None:
    drivezone = Polygon([(-20, -20), (80, -20), (80, 20), (-20, 20), (-20, -20)])
    case_result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id="effective_b_node_case"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    must_cover = Point(0, 0).buffer(2.5)
    target_b_node = Point(20, 0).buffer(2.5)
    allowed = unary_union(
        [
            Point(0, 0).buffer(4.0),
            target_b_node,
            Polygon([(0, -1), (20, -1), (20, 1), (0, 1), (0, -1)]),
        ]
    )
    unit = T04Step5UnitResult(
        event_unit_id="event_unit_01",
        event_type="diverge",
        review_state="STEP4_REVIEW",
        positive_rcsd_consistency_level="B",
        positive_rcsd_support_level="secondary_support",
        required_rcsd_node="target_node",
        legacy_step5_ready=True,
        legacy_step5_reasons=(),
        localized_evidence_core_geometry=None,
        fact_reference_patch_geometry=None,
        required_rcsd_node_patch_geometry=None,
        target_b_node_patch_geometry=target_b_node,
        fallback_support_strip_geometry=None,
        unit_must_cover_domain=must_cover,
        unit_allowed_growth_domain=allowed,
        unit_forbidden_domain=None,
        unit_terminal_cut_constraints=None,
        unit_terminal_window_domain=None,
        terminal_support_corridor_geometry=None,
    )
    step5_result = T04Step5CaseResult(
        case_id="effective_b_node_case",
        unit_results=(unit,),
        case_must_cover_domain=must_cover,
        case_allowed_growth_domain=allowed,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=None,
        case_terminal_window_domain=None,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
    )

    result = build_step6_polygon_assembly(case_result, step5_result)

    assert result.b_node_target_covered is True
    assert "b_node_not_covered" not in set(result.review_reasons)


def test_t04_step6_reapplies_case_limits_after_hole_fill() -> None:
    drivezone = Polygon([(-20, -20), (80, -20), (80, 20), (-20, 20), (-20, -20)])
    case_result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id="post_fill_limit_case"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    outer = Polygon([(0, -10), (50, -10), (50, 10), (0, 10), (0, -10)])
    inner_hole = Polygon([(20, -3), (30, -3), (30, 3), (20, 3), (20, -3)])
    allowed = outer.difference(inner_hole)
    must_cover = unary_union([Point(5, 0).buffer(2.5), Point(45, 0).buffer(2.5)])
    step5_result = T04Step5CaseResult(
        case_id="post_fill_limit_case",
        unit_results=(),
        case_must_cover_domain=must_cover,
        case_allowed_growth_domain=allowed,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=None,
        case_terminal_window_domain=None,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
    )

    result = build_step6_polygon_assembly(case_result, step5_result)

    assert result.final_case_polygon is not None
    assert float(result.final_case_polygon.difference(allowed).area) == pytest.approx(0.0, abs=1e-6)
    assert result.unexpected_hole_count == 0
    assert result.business_hole_count == 1


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
