from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    _build_terminal_window_domain,
)

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


def test_t04_step5_terminal_window_uses_semantic_anchors_for_diverge() -> None:
    drivezone = Polygon([(-40, -40), (140, -40), (140, 40), (-40, 40), (-40, -40)])
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=LineString([(0, 0), (100, 0)]),
        event_origin_point=Point(0, 0),
        selected_event_roads=(),
        selected_roads=(),
    )
    unit_result = SimpleNamespace(
        fact_reference_point=Point(80, 0),
        required_rcsd_node_geometry=Point(20, 0),
        interpretation=SimpleNamespace(
            kind_resolution=SimpleNamespace(operational_kind_2=16),
            legacy_step5_bridge=legacy_bridge,
        ),
    )

    window = _build_terminal_window_domain(unit_result, drivezone_union=drivezone)

    assert window is not None
    assert window.bounds[0] == pytest.approx(0.0, abs=1e-6)
    assert window.bounds[2] == pytest.approx(100.0, abs=1e-6)
    assert window.covers(Point(20, 0))
    assert window.covers(Point(80, 0))
    assert not window.covers(Point(-5, 0))
    assert not window.covers(Point(105, 0))


def test_t04_step5_terminal_window_falls_back_when_axis_misses_anchors() -> None:
    drivezone = Polygon([(-30, -30), (70, -30), (70, 30), (-30, 30), (-30, -30)])
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=LineString([(100, 0), (140, 0)]),
        event_origin_point=Point(100, 0),
        selected_event_roads=(),
        selected_roads=(),
    )
    unit_result = SimpleNamespace(
        fact_reference_point=Point(10, 0),
        required_rcsd_node_geometry=Point(30, 0),
        interpretation=SimpleNamespace(
            kind_resolution=SimpleNamespace(operational_kind_2=8),
            legacy_step5_bridge=legacy_bridge,
        ),
    )

    window = _build_terminal_window_domain(unit_result, drivezone_union=drivezone)

    assert window is not None
    assert window.bounds[0] == pytest.approx(-10.0, abs=1e-6)
    assert window.bounds[2] == pytest.approx(50.0, abs=1e-6)
    assert window.covers(Point(10, 0))
    assert window.covers(Point(30, 0))
    assert not window.covers(Point(-15, 0))
    assert not window.covers(Point(55, 0))


@pytest.mark.smoke
def test_t04_step5_outputs_synthetic_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step5",
        run_id="synthetic_t04_step5",
    )

    result_case_dir = run_root / "cases" / "1001"
    case_step5 = json.loads((result_case_dir / "step5_status.json").read_text(encoding="utf-8"))
    case_step5_audit = json.loads((result_case_dir / "step5_audit.json").read_text(encoding="utf-8"))
    unit_dir = next((result_case_dir / "event_units").iterdir())
    unit_step5 = json.loads((unit_dir / "step5_status.json").read_text(encoding="utf-8"))
    unit_step5_audit = json.loads((unit_dir / "step5_audit.json").read_text(encoding="utf-8"))

    assert case_step5["unit_count"] == 1
    assert case_step5["case_must_cover_domain"]["present"] is True
    assert case_step5["case_allowed_growth_domain"]["present"] is True
    assert case_step5["case_forbidden_domain"]["present"] is True
    assert case_step5["case_terminal_cut_constraints"]["present"] is True
    assert "case_terminal_window_domain" in case_step5
    assert "case_terminal_support_corridor_geometry" in case_step5
    assert "unit_results" in case_step5
    assert case_step5_audit["drivezone_outside_enforced_by_allowed_domain"] is True

    assert unit_step5["unit_must_cover_domain"]["present"] is True
    assert unit_step5["unit_allowed_growth_domain"]["present"] is True
    assert unit_step5["unit_forbidden_domain"]["present"] is True
    assert unit_step5["unit_terminal_cut_constraints"]["present"] is True
    assert "unit_terminal_window_domain" in unit_step5
    assert "terminal_support_corridor_geometry" in unit_step5
    assert case_step5["case_terminal_cut_constraints"]["length_m"] <= 60.0
    assert unit_step5["must_cover_components"]["localized_evidence_core_geometry"] is True
    assert unit_step5["must_cover_components"]["fact_reference_patch_geometry"] is True
    assert "support_road_ids" in unit_step5_audit
    assert "positive_rcsd_road_ids" in unit_step5_audit
    assert set(unit_step5_audit["positive_rcsd_road_ids"]) == set(
        case_step5_audit["unit_results"][0]["positive_rcsd_road_ids"]
    )

    fiona = pytest.importorskip("fiona")
    with fiona.open(result_case_dir / "step5_domains.gpkg") as src:
        rows = list(src)
    domain_roles = {row["properties"]["domain_role"] for row in rows}
    component_roles = {row["properties"]["component_role"] for row in rows}
    assert {
        "case_must_cover_domain",
        "case_allowed_growth_domain",
        "case_forbidden_domain",
        "case_terminal_cut_constraints",
        "unit_must_cover_domain",
        "unit_allowed_growth_domain",
        "unit_forbidden_domain",
        "unit_terminal_cut_constraints",
    }.issubset(domain_roles)
    assert {
        "localized_evidence_core_geometry",
        "fact_reference_patch_geometry",
    }.issubset(component_roles)


@pytest.mark.smoke
def test_t04_step5_pair_local_empty_case_materializes_fallback_strip(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1002"
    _build_pair_local_empty_rcsd_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step5_pair_local_empty",
        run_id="synthetic_t04_step5_pair_local_empty",
    )

    unit_dir = next((run_root / "cases" / "1002" / "event_units").iterdir())
    unit_step5 = json.loads((unit_dir / "step5_status.json").read_text(encoding="utf-8"))

    assert unit_step5["positive_rcsd_consistency_level"] == "C"
    assert unit_step5["must_cover_components"]["fallback_support_strip_geometry"] is True
    assert unit_step5["fallback_support_strip_geometry"]["present"] is True
    assert unit_step5["unit_must_cover_domain"]["present"] is True


@pytest.mark.smoke
def test_t04_step5_multi_event_case_writes_bridge_zone(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step5_multi",
        run_id="synthetic_t04_step5_multi",
    )

    result_case_dir = run_root / "cases" / "2002"
    case_step5 = json.loads((result_case_dir / "step5_status.json").read_text(encoding="utf-8"))

    assert case_step5["unit_count"] == 3
    assert case_step5["case_bridge_zone_geometry"]["present"] is True
    assert case_step5["case_allowed_growth_domain"]["present"] is True

    fiona = pytest.importorskip("fiona")
    with fiona.open(result_case_dir / "step5_domains.gpkg") as src:
        rows = list(src)
    assert any(
        row["properties"]["component_role"] == "case_bridge_zone_geometry"
        for row in rows
    )
